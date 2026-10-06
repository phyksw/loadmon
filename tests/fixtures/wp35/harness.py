# -*- coding: utf-8 -*-
r"""WP-35 시험 도우미 — %TEMP% 모래상자 ROOT·LAD, 가짜 외부 효과(UiDeps), 서버 띄우기·HTTP 의뢰, 가짜 하위 명령.

    sb = Sandbox()                       # %TEMP%\lm27t_wp35_<rand>\{root, lad} (+ 표지 .lm27t_clone owner=<pid>)
    app = sb.app()                       # UiApp(TPaths, cfg, FakeDeps, 가짜 CLI 로 띄우는 JobManager)
    with Running(app) as srv:            # 127.0.0.1:임시 포트에서 서빙(끝나면 shutdown·server_close·스레드 합류)
        st, body, hdr = srv.req("GET", "/api/hello")
    sb.cleanup()                         # 앱·작업·폴더 정리(긴 경로·읽기 전용 처리 — tree._rmtree)

웹 정적 파일·설정 레지스트리·달력은 저장소 원본을 **읽기만** 한다(TPaths). 쓰기는 모래상자 안에만(guard_write).
합성 자료만 쓴다(자리표시자 이름·과제).
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lm27.paths import Paths  # noqa: E402
from lm27.util import fsx, proc  # noqa: E402
from tests.fixtures import tree  # noqa: E402

FAKE_CLI = Path(__file__).resolve().parent / "fake_cli.py"
RUN_ID = "20261005-101500-3fa2"
PC_ID = "pc_0123456789abcdef"
INSTALL_ID = "0123456789abcdef0123456789abcdef"


class TPaths(Paths):
    """시험용 Paths — 저장소 원본 자원(웹·레지스트리·달력)은 읽기만, 분석 하위 경로 메서드(CR)를 더한다."""

    def web_file(self, rel):
        return REPO.joinpath("web", *str(rel).replace("\\", "/").split("/"))

    def settings_registry(self):
        return REPO / "config" / "settings_registry.json"

    def calendar_json(self):
        return REPO / "config" / "calendar.json"

    def analysis_report_file(self, run_id, name):
        return self.analysis(run_id) / "report" / name

    def analysis_hier_file(self, run_id, name):
        return self.analysis(run_id) / "hier" / name

    def run_status_file(self, run_id):
        return self.analysis(run_id) / "run_status.json"


@dataclass
class FakeIdent:
    pc_id: str = PC_ID
    install_id: str = INSTALL_ID
    agent_ver: str = "0.1.0"
    kind_guess: str = "desktop"
    id_source: str = "machineguid"
    tz: dict = field(default_factory=lambda: {"utc_offset_min": 540, "windows_tz": ""})


@dataclass
class FakeDiag:
    kind: str = "other_program"
    code: int = 10048
    port: int = 0
    procs: list = field(default_factory=lambda: [{"name": "다른앱.exe", "pid": 4242, "readable": False}])
    reserved: str = ""
    dynamic: tuple = (49152, 65535)
    suggest: int = 0
    message: str = "다른 프로그램이 포트를 쓰고 있습니다"


@dataclass
class FakeHello:
    result: str = "ok"
    ms: int = 3
    status: int | None = 200
    reason: str | None = None
    text_ko: str = "LM27 팀 서버가 응답합니다"
    info: dict = field(default_factory=lambda: {"name": "팀서버A", "version": "0.1.0"})
    target: str = "primary"


def _ui_deps_base():
    from lm27.ui.server import UiDeps
    return UiDeps


class FakeDeps(_ui_deps_base()):
    """바깥 효과를 기록만 한다(브라우저·폴더·파이프·팀 서버·포트 진단)."""

    def __init__(self, paths, *, pipe_rc=0, stored=None):
        super().__init__(paths)
        self.opened: list = []
        self.folders: list = []
        self.pipe_calls: list = []
        self.pipe_rc = pipe_rc
        self.stored = stored
        self.diags: list = []
        self.hellos: list = []

    def identify(self):
        return FakeIdent()

    def open_url(self, url):
        self.opened.append(url)

    def open_folder(self, path):
        self.folders.append(os.fspath(path))

    def diagnose_port(self, port, code, cfg):
        self.diags.append((port, code))
        return FakeDiag(port=port, code=code)

    def run_pipe(self, kind, src, pc_id, raws, cfg):
        self.pipe_calls.append({"kind": kind, "src": src, "pc_id": pc_id, "raws": [dict(r) for r in raws]})
        return {"rc": self.pipe_rc, "summary": {"ok": self.pipe_rc in (0, 2),
                                                "stored": len(raws) if self.stored is None else self.stored}}

    def team_hello(self, base, timeout):
        self.hellos.append(base)
        return FakeHello()

    def firewall_diag(self, exe_path):
        return {"suspect": False, "level": "ok", "message_ko": "방화벽이 막지 않습니다"}

    def spawn_detached(self, argv):
        """시험에서는 분리 프로세스를 띄우지 않는다 — argv 만 기록하고 가짜 자식(poll = detached_rc)."""
        self.detached_argv = list(argv)
        return FakeChild(getattr(self, "detached_rc", None))

    def bridge_front(self, cfg):
        """[분석용 Edge 창 앞으로] — 시험에서는 Edge 를 띄우지 않는다. ``front_result`` 를 돌려주고 부른 횟수만 센다."""
        self.front_calls = getattr(self, "front_calls", 0) + 1
        return dict(getattr(self, "front_result", None) or {"state": "edge_not_found"})


class FakeChild:
    def __init__(self, rc=None):
        self.rc = rc
        self.closed = False

    def poll(self):
        return self.rc

    def close(self):
        self.closed = True


def fake_spawn(behaviour: dict):
    """JobManager 주입 spawn — 가짜 CLI 행동(WP35_FAKE)을 환경 변수로 넘긴다(실제 자식 프로세스, 창 없음)."""
    env = {"WP35_FAKE": json.dumps(behaviour, ensure_ascii=False)}

    def spawn(argv, **kw):
        kw.setdefault("env", env)
        return proc.spawn(argv, **kw)
    return spawn


class Sandbox:
    r"""%TEMP%\lm27t_wp35_<rand>\{root, lad}. ``cleanup()`` 이 앱(작업·스레드)과 폴더를 지운다."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="lm27t_wp35_"))
        self.apps: list = []
        try:
            (self.dir / tree.CLONE_MARK).write_text(f"owner={os.getpid()}\nwp=WP-35\n", encoding="utf-8")
            self.root = self.dir                     # 시험 ROOT 이름은 lm27t_* (tree.assert_test_root)
            self.lad = self.dir / "_lad"
            self.lad.mkdir()
            (self.root / "lm27_cli.py").write_text("# 시험 표지(program 모드)\n", encoding="utf-8")
            tree.assert_test_root(self.root)
            self.paths = TPaths(self.root, lad=self.lad)
        except BaseException:
            tree._rmtree(self.dir)
            raise

    def cfg(self, **over):
        from lm27.config import load_config
        c = load_config(self.paths)
        return c.derive(over) if over else c

    def app(self, *, behaviour=None, cfg=None, deps=None, **cfg_over):
        from lm27.ui import jobs as J
        from lm27.ui.server import UiApp
        c = cfg or self.cfg(**cfg_over)
        jm = J.JobManager(self.paths, c, spawn=fake_spawn(behaviour or {}), cli=os.fspath(FAKE_CLI),
                          python=sys.executable)
        a = UiApp(self.paths, c, deps=deps or FakeDeps(self.paths), jobs=jm)
        jm._on_done = a._job_done
        self.apps.append(a)
        return a

    def write_json(self, p, obj):
        tree.guard_write(p)
        fsx.atomic_write(p, fsx.canon_bytes(obj))

    def cleanup(self):
        for a in self.apps:
            try:
                a.close()
            except Exception:                       # 정리는 끝까지(다른 앱·폴더도 지운다)
                pass
        self.apps.clear()
        tree._rmtree(self.dir)


class Running:
    """앱을 127.0.0.1:임시 포트(0 → OS 가 고름)에서 서빙. with 를 나가면 shutdown · server_close · 서빙 스레드 합류."""

    def __init__(self, app, port: int = 0):
        from lm27.ui.server import HOST, UiHTTPServer, make_handler
        self.app = app
        self.httpd = UiHTTPServer((HOST, port), make_handler(app))
        app.port = self.httpd.server_address[1]
        self.httpd.app = app
        app.shutdown_cb = self.httpd.shutdown
        self.port = app.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                       name="wp35-serve", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        if self.thread.is_alive():
            self.httpd.shutdown()
            self.thread.join(10)
        self.httpd.server_close()

    def req(self, method, path, body=None, *, token=True, host=None, ctype="application/json", raw=None,
            headers=None, timeout=10):
        """(상태, JSON 또는 바이트, 머리) — Host 는 기본 127.0.0.1:<port>. 쓰기는 기본으로 토큰·JSON."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            h = {"Host": host or f"127.0.0.1:{self.port}"}
            data = raw
            if data is None and body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                if data is None:
                    data = b"{}"
                if ctype:
                    h["Content-Type"] = ctype
                if token:
                    h["X-LM27-UI-Token"] = self.app.token if token is True else token
            h.update(headers or {})
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            raw_b = r.read()
            hdr = {k.lower(): v for k, v in r.getheaders()}
            out = raw_b
            if hdr.get("content-type", "").startswith("application/json"):
                try:
                    out = json.loads(raw_b.decode("utf-8"))
                except ValueError:
                    out = raw_b
            return r.status, out, hdr
        finally:
            c.close()


def free_ports(n: int, lo: int = 41000, hi: int = 60000) -> int:
    """연속 n 개가 127.0.0.1 에 비어 있는 첫 포트(시험 바인드로 확인 — 회피 포트 대역 밖)."""
    import socket
    p = lo + secrets.randbelow(2000)
    while p + n < hi:
        ok = True
        for q in range(p, p + n):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                s.bind(("127.0.0.1", q))
            except OSError:
                ok = False
            finally:
                s.close()
            if not ok:
                break
        if ok:
            return p
        p += n + 1
    raise RuntimeError("빈 포트를 찾지 못했습니다")


def hold_ports(start: int, n: int) -> list:
    """start..start+n-1 을 배타 바인드로 잡아 두는 소켓들(듣지 않음 — 연결은 바로 거절. 시험 끝에 close)."""
    import socket
    out = []
    for q in range(start, start + n):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", q))
        out.append(s)
    return out


def sample_model(run_id: str = RUN_ID) -> dict:
    """합성 보고서 모델(화면이 읽는 필드 일부 — 자리표시자). 확인 질문 Q01 하나와 단위업무 둘."""
    return {
        "schema": "lm27.report", "schema_version": "1.0", "variant": "full",
        "run": {"run_id": run_id, "from": "2026-09-01", "to": "2026-09-30", "as_of": "2026-09-30T18:00"},
        "months": [{"m": "2026-09", "env_min": 9600, "denom_min": 9600, "avail_min": 9600, "overtime_window_min": 600,
                    "unattr_min": 480, "quality": {"grade": "caution"}}],
        "units": [{"unit_id": "u_a1a1a1a1a1", "title": "전원부 검증", "project_id": "P-0007",
                   "cycles": [{"s_key": "m" + "1" * 24, "e_key": "m" + "2" * 24}]},
                  {"unit_id": "u_b2b2b2b2b2", "title": "회로 해석", "project_id": "P-0007",
                   "cycles": [{"s_key": "m" + "3" * 24, "e_key": None}]}],
        "queue": [{"qid": "9f2c01ab3e4d", "code": "Q01", "target": "u_a1a1a1a1a1", "date": "2026-09-03",
                   "evidence_keys": ["m" + "4" * 24], "status": "open", "week": "2026-W36"},
                  {"qid": "aa11bb22cc33", "code": "Q09", "target": "2026-09-23", "date": "2026-09-23",
                   "evidence_keys": [], "status": "open", "week": "2026-W39"}],
        "projects": [{"key": "P-0007", "name": "과제A"}], "flags": {"hier": {"ai_share": 0.5}},
    }


def sample_tasks() -> list:
    """시간 코어 tasks.json 일부(계약 §3.14 열 — 증거 키만 의미 있음)."""
    return [{"unit_id": "u_a1a1a1a1a1", "first_key": "m" + "1" * 24, "conv": "h" + "5" * 16,
             "docs": {"d" + "6" * 16: {"n": 2}}, "cycles": [{"s_ref": "m" + "1" * 24, "e_ref": "m" + "2" * 24}]},
            {"unit_id": "u_b2b2b2b2b2", "first_key": "m" + "3" * 24, "conv": "h" + "5" * 16,
             "docs": {"d" + "7" * 16: {"n": 1}}, "cycles": [{"s_ref": "m" + "3" * 24, "e_ref": None}]}]


def seed_analysis(sb: Sandbox, run_id: str = RUN_ID, *, model=True) -> None:
    """분석 결과 자리: run_status.json · current.json · time\\tasks.json · report\\report_model.json(+ model_meta)."""
    p = sb.paths
    sb.write_json(p.run_status_file(run_id), {
        "schema": "lm27.runstatus/1", "run_id": run_id, "from": "2026-09-01", "to": "2026-09-30",
        "as_of": "2026-09-30T18:00", "state": "done", "stages": [{"id": "report", "state": "done"}]})
    sb.write_json(p.analysis_current(), {"schema": "lm27.current/1", "run_id": run_id, "from": "2026-09-01",
                                         "to": "2026-09-30", "as_of": "2026-09-30T18:00", "chosen": "auto"})
    sb.write_json(p.analysis_time_file(run_id, "tasks.json"), sample_tasks())
    if model:
        from lm27.report import REPORT_VERSION, SCHEMA_VERSION
        sb.write_json(p.analysis_report_file(run_id, "report_model.json"), sample_model(run_id))
        sb.write_json(p.analysis_report_file(run_id, "model_meta.json"),
                      {"report_version": REPORT_VERSION, "schema_version": SCHEMA_VERSION, "inputs": {}})
