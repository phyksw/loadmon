# -*- coding: utf-8 -*-
r"""가짜 디버그 HTTP·기동기·연결자(B §11.2) — 실 Edge·네트워크 없이 L0 를 시험한다.

``FakeNet`` 하나가 ``EdgeSession`` 의 네 주입 자리를 모두 맡는다:
  http=net(``json(port, path, method)``) · connector=net(``connect(ws_url, origin=)``) · launcher=net.launch ·
  can_bind=net.can_bind · in_use=net.in_use

  · 포트별 '브라우저'(소유 프로필 경로·browser_id·탭 목록). 남의 디버그 Edge(다른 프로필)·CDP 가 아닌 프로그램이
    점유한 포트·기동 실패 방식(exit·policy·busy·slow)을 만든다.
  · ``DevToolsActivePort`` 는 임시 프로필 폴더에 실제로 쓴다(크로미움 동작 흉내).
  · 기록: ``http_log``(포트·경로·메서드) · ``connects``(포트·대상 종류·대상 id·Origin) · ``launches``(기동 인자) ·
    ``closed_tabs``(닫힌 탭) — 시험이 '남의 탭을 닫지 않음'·'남의 브라우저에 연결 시도 0' 을 단언한다.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote

from lm27.bridge.cdp import HandshakeRejected
from lm27.bridge.clock import VirtualClock
from lm27.bridge.messages import Notices
from lm27.bridge.session import EdgeSession, read_policy
from lm27.bridge.settings import load_settings
from lm27.config import load_config
from lm27.paths import Paths

from tests.bridge.fake_cdp import CHAT_URL, FakeBrowserCDP, FakePage, FakeTabCDP

_ARG_RX = re.compile(r"^--([a-z-]+)=(.*)$")


class FakeTab:
    def __init__(self, port: int, url: str, page: FakePage | None):
        self.id = uuid.uuid4().hex[:16].upper()
        self.port = port
        self.url = url
        self.page = page

    def info(self) -> dict:
        url = self.page.current_url() if self.page is not None else self.url
        return {"id": self.id, "type": "page", "url": url, "title": "",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/{self.id}"}


class FakeBrowser:
    def __init__(self, net, port: int, profile_dir: str, *, foreign: bool = False, allow_origin: str = "",
                 available_at: float = 0.0):
        self.net = net
        self.port = port
        self.profile_dir = profile_dir
        self.foreign = foreign
        self.uuid = str(uuid.uuid4())
        self.alive = True
        self.allow_origin = allow_origin
        self.available_at = available_at
        self.tabs: list[FakeTab] = []
        self.closed_by_cdp = 0

    @property
    def ws(self) -> str:
        return f"ws://127.0.0.1:{self.port}/devtools/browser/{self.uuid}"

    def up(self) -> bool:
        return self.alive and self.net.clock.mono() >= self.available_at

    def new_tab(self, url: str) -> FakeTab:
        page = None if self.foreign else self.net.page_factory(url)
        t = FakeTab(self.port, url, page)
        self.tabs.append(t)
        return t

    def close_by_cdp(self) -> None:
        self.closed_by_cdp += 1
        if self.net.browser_close_works:
            self.shutdown()

    def shutdown(self) -> None:
        self.alive = False
        for t in self.tabs:
            if t.page is not None:
                t.page.alive = False
        dap = os.path.join(self.profile_dir, "DevToolsActivePort")
        if os.path.isfile(dap):
            os.remove(dap)


class FakeProc:
    _next = 41000

    def __init__(self, net, browser: FakeBrowser | None, alive: bool):
        FakeProc._next += 1
        self.pid = FakeProc._next
        self.net = net
        self.browser = browser
        self._alive = alive
        self.killed = 0

    def alive(self) -> bool:
        return self._alive

    def kill_tree(self) -> bool:
        self.killed += 1
        self._alive = False
        if self.browser is not None:
            self.browser.shutdown()
        return True


class FakeNet:
    """가짜 디버그 포트 세계. ``page_factory(url) -> FakePage`` 로 우리 탭 페이지 모형을 정한다."""

    def __init__(self, clock, *, page_factory=None):
        self.clock = clock
        self.page_factory = page_factory or (lambda url: FakePage(clock, url=url))
        self.browsers: dict[int, FakeBrowser] = {}
        self.occupied: set[int] = set()          # CDP 가 아닌 프로그램이 묶은 포트
        self.in_use_profiles: set[str] = set()
        self.http_log: list[tuple] = []
        self.connects: list[tuple] = []
        self.launches: list[list[str]] = []
        self.procs: list[FakeProc] = []
        self.closed_tabs: list[tuple] = []
        self.launch_mode = "ok"                  # ok | exit | policy | busy | slow:<초>
        self.reject_no_origin = False            # True 면 Origin 없는 핸드셰이크를 403 으로 거절
        self.browser_close_works = True
        self.put_supported = True

    # ── 세계 꾸미기 ─────────────────────────────────────────────────────
    def add_foreign(self, port: int, urls=("https://outlook.example/mail",)) -> FakeBrowser:
        """남의 디버그 Edge(다른 프로필) — 우리 세션은 여기에 연결하지 않아야 한다."""
        b = FakeBrowser(self, port, os.path.join("Z:", "other-profile"), foreign=True)
        for u in urls:
            b.new_tab(u)
        self.browsers[port] = b
        return b

    def add_ours(self, port: int, profile_dir, urls=(CHAT_URL,), *, write_dap: bool = True) -> FakeBrowser:
        """이미 떠 있는 우리 프로필 Edge(재사용 대상)."""
        b = FakeBrowser(self, port, os.fspath(profile_dir))
        for u in urls:
            b.new_tab(u)
        self.browsers[port] = b
        if write_dap:
            self._write_dap(b)
        return b

    def _write_dap(self, b: FakeBrowser) -> None:
        os.makedirs(b.profile_dir, exist_ok=True)
        with open(os.path.join(b.profile_dir, "DevToolsActivePort"), "w", encoding="utf-8") as fh:
            fh.write(f"{b.port}\n/devtools/browser/{b.uuid}\n")

    def our_pages(self) -> list[FakePage]:
        return [t.page for b in self.browsers.values() if not b.foreign for t in b.tabs if t.page is not None]

    # ── Http ───────────────────────────────────────────────────────────
    def json(self, port: int, path: str, method: str = "GET"):
        self.http_log.append((port, path, method))
        if port in self.occupied:
            raise ValueError("fake: CDP 가 아닌 응답")
        b = self.browsers.get(port)
        if b is None or not b.up():
            raise ConnectionRefusedError(f"fake: {port} 응답 없음")
        if path == "/json/version":
            return {"Browser": "Edg/129.0.2792.65", "webSocketDebuggerUrl": b.ws}
        if path in ("/json", "/json/list"):
            return [t.info() for t in b.tabs]
        if path.startswith("/json/new?"):
            if method != "PUT" and self.put_supported:
                raise ValueError("fake: PUT 필요")
            return b.new_tab(unquote(path[len("/json/new?"):])).info()
        if path.startswith("/json/close/"):
            tid = path.rsplit("/", 1)[-1]
            for t in list(b.tabs):
                if t.id == tid:
                    b.tabs.remove(t)
                    if t.page is not None:
                        t.page.alive = False
                    self.closed_tabs.append((port, tid))
            return "Target is closing"
        if path.startswith("/json/activate/"):
            return "Target activated"
        raise ValueError(f"fake: 모르는 경로 {path}")

    # ── Connector ──────────────────────────────────────────────────────
    def connect(self, ws_url: str, *, origin=None):
        m = re.match(r"^ws://127\.0\.0\.1:(\d+)/devtools/(page|browser)/(.+)$", ws_url or "")
        if not m:
            raise ValueError("fake: ws 주소 형식")
        port, kind, target = int(m.group(1)), m.group(2), m.group(3)
        self.connects.append((port, kind, target, origin))
        b = self.browsers.get(port)
        if b is None or not b.up():
            raise ConnectionRefusedError("fake: 연결 거부")
        if self.reject_no_origin and (not origin or origin != b.allow_origin):
            raise HandshakeRejected(403)
        if kind == "browser":
            return FakeBrowserCDP(b)
        for t in b.tabs:
            if t.id == target and t.page is not None:
                return FakeTabCDP(t.page, origin=origin)
        raise ConnectionRefusedError("fake: 대상 없음")

    # ── 기동기·포트 ─────────────────────────────────────────────────────
    def launch(self, args) -> FakeProc:
        self.launches.append(list(args))
        opts = {}
        for a in args[1:]:
            m = _ARG_RX.match(a)
            if m:
                opts[m.group(1)] = m.group(2)
        port = int(opts.get("remote-debugging-port", "0"))
        prof = opts.get("user-data-dir", "")
        url = args[-1]
        mode = self.launch_mode
        if mode == "exit":
            p = FakeProc(self, None, alive=False)
        elif mode == "policy":
            p = FakeProc(self, None, alive=True)
        elif mode == "busy":
            self.in_use_profiles.add(os.path.normcase(os.path.abspath(prof)))
            p = FakeProc(self, None, alive=False)
        else:
            delay = float(mode.split(":", 1)[1]) if mode.startswith("slow:") else 0.0
            b = FakeBrowser(self, port, prof, allow_origin=opts.get("remote-allow-origins", ""),
                            available_at=self.clock.mono() + delay)
            b.new_tab(url)
            self.browsers[port] = b
            self._write_dap(b)
            p = FakeProc(self, b, alive=True)
        self.procs.append(p)
        return p

    def can_bind(self, port: int) -> bool:
        return port not in self.occupied and not (port in self.browsers and self.browsers[port].alive)

    def in_use(self, profile_dir) -> bool:
        return os.path.normcase(os.path.abspath(os.fspath(profile_dir))) in self.in_use_profiles


def no_edge_reg(hive, key, value):
    """레지스트리 없음(정책 미설정·App Paths 없음)."""
    return None


def policy_blocked_reg(hive, key, value):
    """정책: RemoteDebuggingAllowed = 0(금지)."""
    return 0 if value == "RemoteDebuggingAllowed" else None


TREE = Path(__file__).resolve().parents[2]
REGISTRY = TREE / "config" / "settings_registry.json"
RUN_A = "20261005-101500-3fa2"


def bridge_settings(tmp: str, overrides=None):
    """트리의 설정 레지스트리 + 개인 덮어쓰기 없음(+ 시험 덮어쓰기)."""
    cfg = load_config(registry_path=REGISTRY, config_path=Path(tmp) / "no_config.json", overrides=overrides)
    return load_settings(cfg=cfg)


class World:
    """가짜 세계 하나: %TEMP% 임시 트리(Paths) · 가상 시계 · FakeNet · 설정 · Notices. ``session()`` 이 EdgeSession 을 만든다."""

    def __init__(self, *, page_factory=None, overrides=None, edge_path=r"C:\fake\Edge\msedge.exe",
                 policy_reg=no_edge_reg):
        self.tmp = tempfile.mkdtemp(prefix="lm27t_bridge_")
        self.paths = Paths(os.path.join(self.tmp, "root"), lad=os.path.join(self.tmp, "lad"))
        os.makedirs(self.paths.root, exist_ok=True)
        self.clock = VirtualClock()
        self.net = FakeNet(self.clock, page_factory=page_factory)
        self.cfg = bridge_settings(self.tmp, overrides)
        self.notices = Notices()
        self.edge_path = edge_path
        self.policy_reg = policy_reg
        self.alive_pids: set[int] = {os.getpid()}
        self.environ: dict = {}

    def probe(self, pid, ctime=None) -> bool:
        return pid in self.alive_pids

    def session(self, role="bridge", run_id=RUN_A, **kw) -> EdgeSession:
        opts = {"paths": self.paths, "cfg": self.cfg, "clock": self.clock, "http": self.net, "connector": self.net,
                "launcher": self.net.launch, "can_bind": self.net.can_bind, "edge_finder": lambda: self.edge_path,
                "policy_reader": lambda: read_policy(self.policy_reg), "proc_probe": self.probe,
                "in_use": self.net.in_use, "notices": self.notices, "environ": self.environ, "pid_ctime": 1}
        opts.update(kw)
        return EdgeSession(role, run_id, **opts)

    @property
    def profile_dir(self) -> Path:
        return Path(self.paths.edge_profile())

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
