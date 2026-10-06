# -*- coding: utf-8 -*-
r"""로컬 앱 서버(R §2.3 · 계약 §1.3 ``ui\`` · §2.14 · §3.23 · §4.7 · §7.1 · §8.3) — 127.0.0.1 전용, 표준 라이브러리 HTTP.

    rc = serve(cfg, port=None, open_browser=True)      # lm27 ui [--port N] [--no-browser]   → 0 정상 종료 · 3 포트 전부 실패
    rc = check(cfg, port=None)                         # lm27 ui --check(LoadMonitor27-UI.bat 의 첫 단계) → 0 · 3(한국어 사유)

보안(R §2.3.3 · RPT-36):
  · 바인드 주소는 **127.0.0.1 고정**(설정 없음). ``UiHTTPServer`` = ``allow_reuse_address = False`` + ``SO_EXCLUSIVEADDRUSE``
    (L-20 — 살아 있는 리스너 위 덧바인드 차단).
  · ``Host`` 가 ``127.0.0.1:<port>`` · ``localhost:<port>`` 가 아니면 421 ``bad_host``(DNS 재바인딩 방어).
  · 쓰기(POST·PUT·PATCH·DELETE)는 헤더 ``X-LM27-UI-Token`` 이 기동 때 만든 ``secrets.token_hex(16)`` 과 같아야 한다
    (``hmac.compare_digest`` — 아니면 403 ``ui_token``). 토큰은 ``index.html`` 을 내보낼 때 ``<meta name="lm27-ui-token">`` 의
    content 자리만 응답에서 채운다(파일은 고치지 않는다).
  · 쓰기 본문은 ``application/json`` 만(415), 상한 2MB(413 — ``/api/bridge/manual/import`` 는 4MB). ``OPTIONS`` 는 405,
    ``Access-Control-Allow-*`` 는 보내지 않는다. 응답 머리: CSP · nosniff · ``Referrer-Policy: no-referrer`` · API ``no-store``.
  · 정적 파일은 **고정 사전** ``STATIC`` 만(요청 경로를 파일 경로로 조합하지 않는다 — ``/static/../config/config.json`` 은 404).
  · 로그 ``ui\logs\ui_YYYYMMDD.log`` = 메서드·경로(쿼리 제외)·상태·소요 ms 만(본문·라벨·이름 금지), ``ui.logKeepDays`` 보관.
  · ``POST /api/shutdown`` = 토큰 + 루프백, 200 응답 0.5초 뒤 종료.

단일 인스턴스·포트(R §2.3.1 · §2.3.2 · RPT-37 · RPT-38):
  · ``ui\ui_server.json`` = ``{pid, port, started_at, instance_id, root_id}``(``root_id`` = ``sha256(ROOT 정규화 경로)[:8]``).
    그 pid 가 살아 있고 ``/api/hello`` 의 ``instance_id``·``root_id`` 가 같으면 새로 띄우지 않고 브라우저만 그 주소로 연다.
  · ``ui.port``(19280) 가 막히면 +1 … +``ui.portFallbackCount``(9) 를 차례로(팀 서버·별개 프로젝트·이전 판 포트는 건너뜀).
    점유한 쪽이 같은 ROOT 의 LM27 화면이면 그 화면을 연다(두 설치본 공존 — 다른 ROOT 면 다음 포트). 모두 실패하면 포트 진단
    (TAB §3.4 ``diagnose_port`` 와 같은 함수)으로 원인을 한국어로 알리고 rc 3(``ui_start_error.txt`` 에도 — pythonw 는 콘솔이 없다).

긴 일은 ``lm27.ui.jobs.JobManager`` 가 ``lm27_cli.py`` 하위 프로세스로 띄운다. API 처리기는 ``lm27.ui.api_*`` 의 ``ROUTES``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lm27 import LM27_VERSION
from lm27.ui import jobs as J
from lm27.util import fsx

__all__ = ["APP_ID", "CSP", "HOST", "STATIC", "TOKEN_HEADER", "ApiError", "Req", "UiApp", "UiDeps", "UiHTTPServer",
           "candidates", "check", "find_existing", "make_handler", "root_id_of", "serve"]

APP_ID = "LM27-ui"                               # 로컬 앱 신원(계약 §4.7)
HOST = "127.0.0.1"                               # 바인드 고정(R §2.3.2)
TOKEN_HEADER = "X-LM27-UI-Token"
# 정적 고정 사전(R §2.3.4) — 요청 경로 → (web 아래 파일, Content-Type)
STATIC = {"/": ("app/index.html", "text/html; charset=utf-8"),
          "/static/app.js": ("app/app.js", "text/javascript; charset=utf-8"),
          "/static/report.js": ("app/report.js", "text/javascript; charset=utf-8"),
          "/static/lm27charts.js": ("common/lm27charts.js", "text/javascript; charset=utf-8"),
          "/static/lm27ui.js": ("common/lm27ui.js", "text/javascript; charset=utf-8"),
          "/static/lm27.css": ("common/lm27.css", "text/css; charset=utf-8"),
          "/static/icons.svg": ("common/icons.svg", "image/svg+xml")}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
MB = 1024 * 1024
BODY_MAX = 2 * MB
BODY_MAX_BY_PATH = {"/api/bridge/manual/import": 4 * MB}
DRAIN_MAX = 8 * MB
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
BIND_FAIL = frozenset({10048, 10013, 98, 13, 48})        # WinError 주소 사용 중·접근 거부(POSIX 대응 값 포함)
SHUTDOWN_DELAY_S = 0.5
HELLO_TIMEOUT_S = 1.5
TEAM_SEND_TRIGGERS = ("startup", "timer")      # 화면이 거는 팀 묶음 재시도 계기(TAB §2.8 — 승인된 항목만)
TEAM_SEND_STARTUP_DELAY_S = 5.0
TEAM_SEND_EVERY_S = 15 * 60.0                  # 화면이 떠 있는 동안 15분마다(TAB §2.8)
_TOKEN_META_RX = re.compile(rb'(<meta\s+name="lm27-ui-token"\s+content=")[^"]*(")')
_LOG_NAME_RX = re.compile(r"^ui_(\d{8})\.log$")


# ───────────────────────────── 공통 형 ─────────────────────────────
class ApiError(Exception):
    """API 오류 — 응답 ``{"ok": false, "code", "error"(한국어), "detail": [...]}``(R §2.3.6, 팀 서버와 같은 형)."""

    def __init__(self, status: int, code: str, error: str, detail=(), *, extra=None):
        super().__init__(error)
        self.status, self.code, self.error, self.detail = int(status), code, error, list(detail)
        self.extra = dict(extra or {})               # 화면이 더 읽는 키(예 rebuilding 의 job_id, run_missing 의 run_id)

    def body(self) -> dict:
        out = {"ok": False, "code": self.code, "error": self.error, "detail": self.detail}
        out.update(self.extra)
        return out


class Req:
    """처리기 입력 — 경로 매치 그룹(groups) · 쿼리(첫 값) · JSON 본문(쓰기) · 클라이언트 IP."""

    __slots__ = ("body", "client_ip", "groups", "method", "path", "query")

    def __init__(self, method, path, query=None, body=None, groups=(), client_ip=HOST):
        self.method, self.path = method, path
        self.query = dict(query or {})
        self.body = body if isinstance(body, dict) else {}
        self.groups = tuple(groups)
        self.client_ip = client_ip

    def q(self, name, default=None):
        v = self.query.get(name)
        return v if v not in (None, "") else default


def root_id_of(paths) -> str:
    """``sha256(ROOT 정규화 경로)[:8]``(R §2.3.1) — 두 설치본을 가린다(경로 자체는 내보내지 않는다)."""
    norm = os.path.normcase(os.path.abspath(os.fspath(paths.root)))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:8]


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _say(msg: str) -> None:
    st = sys.stdout
    if st is None:
        return
    try:
        st.write(msg + "\n")
        st.flush()
    except (OSError, ValueError):
        pass


def _winerror(e: BaseException) -> int:
    w = getattr(e, "winerror", None)
    if isinstance(w, int):
        return w
    return int(getattr(e, "errno", 0) or 0)


# ───────────────────────────── 외부 효과(시험 주입점) ─────────────────────────────
class UiDeps:
    """서버가 바깥 세계에 닿는 곳 — 브라우저·폴더 열기·포트 진단·정제 파이프·PC 식별. 시험은 하위 클래스로 바꾼다."""

    def __init__(self, paths):
        self.paths = paths
        self._ident = None
        self._lock = threading.Lock()

    def now(self) -> datetime:
        return datetime.now(UTC)

    def identify(self):
        """이 PC 식별(``lm27.bundle.ids.identify_pc`` — 한 번만)."""
        with self._lock:
            if self._ident is None:
                from lm27.bundle.ids import identify_pc
                self._ident = identify_pc(self.paths)
            return self._ident

    def open_url(self, url: str) -> None:
        if os.name == "nt":
            os.startfile(url)                    # 기본 브라우저(R §2.3.1)

    def open_folder(self, path) -> None:
        if os.name == "nt":
            os.startfile(os.fspath(path))

    def diagnose_port(self, port: int, code: int, cfg):
        """바인드 실패 원인(TAB §3.4 ``diagnose_port`` 와 같은 함수) → PortDiag."""
        from lm27.team.portdiag import diagnose_port
        return diagnose_port(port, code, cfg)

    def firewall_diag(self, exe_path: str) -> dict:
        """방화벽 진단(TAB §3.14) — 읽기만(규칙을 만들지 않는다)."""
        from lm27.team.firewall import firewall_diag
        return firewall_diag(exe_path)

    def team_hello(self, base: str, timeout: float):
        """팀 서버 신원 판정(TAB §2.9 ``hello``)."""
        from lm27.team.client import hello
        return hello(base, timeout)

    def spawn_detached(self, argv):
        """분리 프로세스(팀 서버) — 창 없이, 표준 입출력 없이, 작업 폴더 %TEMP%. 화면이 꺼져도 산다."""
        import tempfile

        from lm27.util import proc
        return proc.spawn(argv, stdin=proc.DEVNULL, stdout=proc.DEVNULL, stderr=proc.DEVNULL, cwd=tempfile.gettempdir())

    def run_pipe(self, kind: str, src: str, pc_id: str, raws: list, cfg) -> dict:
        """원시 레코드 → 정제 파이프(``lm27_pipe.py --kind --src --pc --mode append`` — 계약 §7.3, 연결자 = 화면).
        원문은 파이프 stdin 으로만 간다(디스크 0). 반환 {rc, summary}."""
        from lm27.util import proc
        exe = self.paths.python_exe()
        py = os.fspath(exe) if os.path.isfile(fsx.longp(exe)) else J._sys_python()
        argv = [py, "-X", "utf8", "-I", "-B", os.fspath(self.paths.pipe_script()), "--kind", kind, "--src", src,
                "--pc", pc_id, "--mode", "append"]
        data = "".join(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n" for r in raws)
        data += json.dumps({"_cursor": {}}, ensure_ascii=False) + "\n"
        res = proc.run_child(argv, timeout_s=float(cfg["privacy.pipe.waitSec"]), stdin=data)
        summary = {}
        for ln in reversed(res.out_text().splitlines()):
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    obj = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    summary = obj
                    break
        return {"rc": 99 if res.timed_out else res.rc, "summary": summary}


# ───────────────────────────── 앱 상태 ─────────────────────────────
class UiApp:
    """요청 처리에 필요한 상태: 경로·설정(파일이 바뀌면 다시 읽음)·토큰·작업 관리자·경로표."""

    def __init__(self, paths, cfg, *, deps=None, jobs=None, token=None, instance_id=None, spawn=None):
        self.paths = paths
        self._cfg = cfg
        self._cfg_sig = self._sig()
        self.deps = deps or UiDeps(paths)
        self.token = token or secrets.token_hex(16)
        self.instance_id = instance_id or ("i_" + secrets.token_hex(8))
        self.root_id = root_id_of(paths)
        self.port = None
        self.jobs = jobs or J.JobManager(paths, cfg, spawn=spawn, on_done=self._job_done)
        self.routes = build_routes()
        self.last_request = time.monotonic()
        self.shutdown_cb = None
        self.scratch: dict = {}                  # api 모듈의 짧은 상태(응답 대기 수 등 — 디스크 아님)
        self.detached: list = []                 # 분리 프로세스(팀 서버) 핸들 — 서버 종료 때 닫는다(끄지는 않는다)
        self._lock = threading.RLock()
        self._static: dict = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # 설정 --------------------------------------------------------------
    def _sig(self):
        out = []
        for p in (self.paths.config_json(), self.paths.settings_registry()):
            try:
                st = os.stat(fsx.longp(p))
                out.append((st.st_mtime_ns, st.st_size))
            except OSError:
                out.append(None)
        return tuple(out)

    def cfg(self):
        """실효 설정 — config.json·레지스트리가 바뀌었으면 다시 읽는다(버튼을 누르는 순간 파일을 다시 읽는다 — R §5.0.1)."""
        sig = self._sig()
        with self._lock:
            if sig != self._cfg_sig:
                from lm27.config import load_config
                self._cfg = load_config(self.paths)
                self._cfg_sig = sig
            return self._cfg

    def reload_cfg(self):
        with self._lock:
            self._cfg_sig = None
        return self.cfg()

    # 신원·문턱 ------------------------------------------------------------
    def host_ok(self, host) -> bool:
        if not isinstance(host, str) or self.port is None:
            return False
        h = host.strip().lower()
        return h in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def token_ok(self, given) -> bool:
        return isinstance(given, str) and hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))

    def touch(self) -> None:
        self.last_request = time.monotonic()

    def pc_brief(self) -> dict:
        """이 PC 의 라벨·종류·역할(``/api/hello`` — 30초 캐시)."""
        with self._lock:
            ent = self.scratch.get("_pc_brief")
            if ent and time.monotonic() - ent[0] < 30:
                return dict(ent[1])
        out = {"label_auto": "", "kind": "", "roles": []}
        try:
            from lm27.bundle import loader, pcreg
            ident = self.deps.identify()
            pc = pcreg.load_pc(loader.pc_dir_of(self.paths, ident.pc_id)) or {}
            out = {"label_auto": str(pc.get("label_user") or pc.get("label_auto") or ""),
                   "kind": str(pc.get("kind") or getattr(ident, "kind_guess", "") or ""),
                   "roles": sorted(str(r) for r in pc.get("roles") or () if isinstance(r, str))}
        except Exception:                          # 번들이 아직 없거나 식별 실패 — 빈 값(화면은 '정보 없음')
            pass
        try:                                       # 이 PC 에서 분석하면 AI 판정을 하는가 — 분석과 같은 판단(계약 v1.3 §0.8 V11)
            from lm27.ui.api_analysis import _ai_here
            out["ai_here"] = bool(_ai_here(self.cfg(), {"roles": out["roles"]}))
        except Exception:
            out["ai_here"] = "copilot" in out["roles"]
        with self._lock:
            self.scratch["_pc_brief"] = (time.monotonic(), out)
        return dict(out)

    def hello(self) -> dict:
        # port = 화면 머리의 '판 · 127.0.0.1:<포트> · 로컬 전용' 표시용(LM24 머리와 같은 자리)
        return {"app": APP_ID, "version": LM27_VERSION, "instance_id": self.instance_id, "root_id": self.root_id,
                "port": self.port, "pc": self.pc_brief(), "token_meta": False,
                "job_poll_ms": int(self.cfg()["ui.jobPollMs"])}

    # 작업 --------------------------------------------------------------
    def start_job(self, kind: str, argv) -> dict:
        try:
            job = self.jobs.start(kind, argv)
        except J.BusyError as e:
            raise ApiError(409, "busy", str(e), [e.job.kind]) from None
        return {"ok": True, "job_id": job.job_id}

    # 팀 묶음 자동 재시도(TAB §2.8 — 화면 기동·떠 있는 동안 15분마다; 빌드 직후는 team build, [수집] 끝은 collect) -----
    def _team_due(self) -> bool:
        """승인된(또는 ``team.autoSend``) 막힘 없는 대기 묶음이 있는가 — 대기열 meta 만 읽는다(네트워크 0)."""
        try:
            from lm27.team import queue
            auto = bool(self.cfg()["team.autoSend"])
            for it in queue.list_items(paths=self.paths) or ():
                m = getattr(it, "meta", None) or {}
                if getattr(it, "folder", "") == "pending" and (m.get("approved") or auto) and not m.get("blockers"):
                    return True
        except Exception:                          # 대기열·번들이 아직 없거나 읽기 실패 — 이번 계기는 건너뛴다
            return False
        return False

    def auto_team_send(self, trigger: str):
        """보낼 것이 있고 net 차선이 비어 있을 때만 작업 ``team send --all --trigger <계기>``(하위 프로세스 — 서버 안에서
        네트워크 일을 하지 않는다). 반환 job_id 또는 None."""
        if trigger not in TEAM_SEND_TRIGGERS or not self._team_due():
            return None
        try:
            return self.jobs.start("team_send", ["team", "send", "--all", "--trigger", trigger]).job_id
        except J.BusyError:
            return None

    def start_team_send_watch(self) -> None:
        def loop():
            if self._stop.wait(TEAM_SEND_STARTUP_DELAY_S):
                return
            self.auto_team_send("startup")
            while not self._stop.wait(TEAM_SEND_EVERY_S):
                self.auto_team_send("timer")
        self._spawn(loop, "lm27-ui-teamsend")

    def _job_done(self, job) -> None:
        if job.kind == "move_prepare" and job.state == "done":       # 이동 준비 → 도우미 창이 뜨고 서버 종료(TAB §1.11)
            self.request_shutdown(1.0)

    # 정적 --------------------------------------------------------------
    def static_body(self, rel: str) -> bytes:
        p = self.paths.web_file(rel)
        st = os.stat(fsx.longp(p))
        key = (st.st_mtime_ns, st.st_size)
        with self._lock:
            ent = self._static.get(rel)
            if ent is not None and ent[0] == key:
                return ent[1]
        body = fsx.read_bytes(p)
        with self._lock:
            self._static[rel] = (key, body)
        return body

    def index_body(self) -> bytes:
        raw = self.static_body(STATIC["/"][0])
        tok = self.token.encode("ascii")
        return _TOKEN_META_RX.sub(lambda m: m.group(1) + tok + m.group(2), raw, count=1)

    # 경로표 ------------------------------------------------------------
    def match(self, method: str, path: str):
        for m, rx, fn in self.routes:
            if m == method:
                mt = rx.fullmatch(path)
                if mt:
                    return fn, mt.groups()
        return None, ()

    # 로그 --------------------------------------------------------------
    def log_file(self, dt: datetime):
        fn = getattr(self.paths, "ui_log_file", None)
        if callable(fn):
            return fn(dt)
        return self.paths.ui_logs() / ("ui_" + dt.strftime("%Y%m%d") + ".log")

    def log_request(self, method: str, path: str, status: int, ms: int) -> None:
        now = datetime.now(UTC)
        p = re.sub(r"[^\w/.\-:]", "_", path)[:160]
        try:
            fsx.append_line(self.log_file(now), f"{_utc_iso(now)} {method} {p} {int(status)} {int(ms)}ms")
        except (OSError, ValueError):
            pass
        day = now.strftime("%Y%m%d")
        if self.scratch.get("_log_day") != day:          # 날이 바뀌면 보관 기간 지난 로그 정리(ui.logKeepDays)
            self.scratch["_log_day"] = day
            self.prune_logs()

    def prune_logs(self) -> int:
        keep = int(self.cfg()["ui.logKeepDays"])
        cut = (datetime.now(UTC) - timedelta(days=keep)).strftime("%Y%m%d")
        n = 0
        d = self.paths.ui_logs()
        try:
            names = os.listdir(fsx.longp(d))
        except OSError:
            return 0
        for name in names:
            m = _LOG_NAME_RX.match(name)
            if m and m.group(1) < cut:
                try:
                    os.remove(fsx.longp(d / name))
                    n += 1
                except OSError:
                    pass
        return n

    # 종료 --------------------------------------------------------------
    def request_shutdown(self, delay: float = SHUTDOWN_DELAY_S) -> None:
        cb = self.shutdown_cb
        if cb is None:
            return

        def later():
            if not self._stop.wait(delay):
                cb()
        self._spawn(later, "lm27-ui-shutdown")

    def start_idle_watch(self) -> None:
        mins = int(self.cfg()["ui.idleShutdownMin"])
        if mins <= 0:
            return

        def loop():
            lim = mins * 60.0
            while not self._stop.wait(min(30.0, lim)):
                if time.monotonic() - self.last_request > lim and not self.jobs.running():
                    cb = self.shutdown_cb
                    if cb is not None:
                        cb()
                    return
        self._spawn(loop, "lm27-ui-idle")

    def _spawn(self, fn, name) -> None:
        t = threading.Thread(target=fn, name=name, daemon=True)
        with self._lock:
            self._threads = [x for x in self._threads if x.is_alive()]
            self._threads.append(t)
        t.start()

    def close(self) -> None:
        """작업 관리자를 닫고 보조 스레드를 합류한다(분리 프로세스는 끄지 않고 핸들만 닫는다)."""
        self._stop.set()
        self.jobs.close()
        cur = threading.current_thread()
        for t in list(self._threads):
            if t is not cur:
                t.join(5.0)
        for ch in self.detached:
            try:
                ch.close()
            except OSError:
                pass
        self.detached.clear()
        with self._lock:
            self._static.clear()


def build_routes() -> list:
    """api 모듈들의 ``ROUTES``((메서드, 경로 정규식, 처리기)) — 정규식은 전체 일치."""
    from lm27.ui import api_analysis, api_collect, api_home, api_privacy, api_report, api_settings, api_team
    out = [("GET", re.compile(r"/api/hello"), _hello),
           ("GET", re.compile(r"/api/jobs"), _jobs_list),
           ("GET", re.compile(r"/api/jobs/(j\d{14}[0-9a-f]{4})"), _job_get),
           ("POST", re.compile(r"/api/jobs/(j\d{14}[0-9a-f]{4})/cancel"), _job_cancel),
           ("POST", re.compile(r"/api/shutdown"), _shutdown)]
    for mod in (api_home, api_collect, api_analysis, api_report, api_team, api_settings, api_privacy):
        for method, pat, fn in mod.ROUTES:
            out.append((method, re.compile(pat), fn))
    return out


def _hello(app, req):
    return app.hello()


def _jobs_list(app, req):
    return {"jobs": app.jobs.list()}


def _job_get(app, req):
    try:
        since = int(req.q("since", 0))
    except (TypeError, ValueError):
        since = 0
    v = app.jobs.get(req.groups[0], max(0, since))
    if v is None:
        raise ApiError(404, "no_job", "그 작업 기록이 없습니다")
    return v


def _job_cancel(app, req):
    if not app.jobs.cancel(req.groups[0]):
        raise ApiError(404, "no_job", "진행 중인 그 작업이 없습니다")
    return {"ok": True, "cancel_grace_s": J.CANCEL_GRACE_S}


def _shutdown(app, req):
    if req.client_ip not in ("127.0.0.1", "::1"):
        raise ApiError(403, "loopback_only", "이 PC 에서만 화면 서버를 끝낼 수 있습니다")
    app.request_shutdown(SHUTDOWN_DELAY_S)
    return {"ok": True, "stopping": True}


# ───────────────────────────── HTTP ─────────────────────────────
class UiHTTPServer(ThreadingHTTPServer):
    """배타 바인드 서버(L-20). 기본 HTTPServer 는 allow_reuse_address=1 — 윈도우에서 살아 있는 리스너 위 덧바인드가 된다."""

    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 32

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)             # getfqdn(역방향 DNS)을 하지 않는다
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def handle_error(self, request, client_address):
        """처리 중 예외 — 콘솔에 아무것도 찍지 않는다(요청 로그에 상태만 남는다)."""


def make_handler(app: UiApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = APP_ID
        sys_version = ""
        protocol_version = "HTTP/1.0"                       # 응답마다 연결을 닫는다(대기 스레드가 남지 않게)
        timeout = 20

        def log_message(self, fmt, *args):                 # 기본 stderr 로그 끔 — 우리 로그는 메서드·경로·상태·ms 만
            pass

        # 응답 ------------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str, *, api: bool = True, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store" if api else "no-cache")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)
            return code

        def _json(self, code: int, obj, extra=None):
            try:
                raw = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError):
                code = 500
                raw = json.dumps(ApiError(500, "internal", "응답을 만들지 못했습니다").body(),
                                 ensure_ascii=False).encode("utf-8")
            return self._send(code, raw, "application/json; charset=utf-8", extra=extra)

        def _err(self, e: ApiError, extra=None):
            return self._json(e.status, e.body(), extra)

        def _length(self):
            v = (self.headers.get("Content-Length") or "").strip()
            if not v:
                return None
            return int(v) if v.isdigit() else -1

        def _drain(self, n):
            left = min(max(int(n or 0), 0), DRAIN_MAX)
            try:
                while left > 0:
                    chunk = self.rfile.read(min(MB, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except OSError:
                pass

        def _reject(self, e: ApiError, extra=None):
            """본문이 있으면 읽고(상한까지) 거절한다 — 안 읽고 답하면 연결이 끊겨 응답조차 못 갈 수 있다."""
            n = self._length()
            if self.command in WRITE_METHODS and n and n > 0:
                self._drain(n)
            return self._err(e, extra)

        # 진입 ------------------------------------------------------------
        def _run(self, method: str):
            t0 = time.monotonic()
            path = urllib.parse.urlsplit(self.path).path
            status = 500
            try:
                status = self._dispatch(method)
            except (ConnectionError, TimeoutError):
                status = 499
            finally:
                app.log_request(method, path, status, int((time.monotonic() - t0) * 1000))

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

        def do_PUT(self):
            self._run("PUT")

        def do_PATCH(self):
            self._run("PATCH")

        def do_DELETE(self):
            self._run("DELETE")

        def do_OPTIONS(self):
            self._run("OPTIONS")

        def do_HEAD(self):
            self._run("HEAD")

        def _dispatch(self, method: str) -> int:
            u = urllib.parse.urlsplit(self.path)
            path = u.path
            if not app.host_ok(self.headers.get("Host")):
                return self._reject(ApiError(421, "bad_host", "이 주소로는 화면을 열 수 없습니다 — 127.0.0.1 주소로 여세요"))
            app.touch()
            if method in ("OPTIONS", "HEAD"):
                return self._reject(ApiError(405, "method", "허용되지 않는 메서드입니다"), {"Allow": "GET, POST, PUT"})
            body = None
            if method in WRITE_METHODS:
                if not app.token_ok(self.headers.get(TOKEN_HEADER)):
                    return self._reject(ApiError(403, "ui_token",
                                                 "화면 보안 확인값이 맞지 않습니다 — 화면을 새로 고치면 이어서 합니다"))
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    return self._reject(ApiError(415, "content_type", "application/json 만 받습니다"))
                n = self._length()
                if n is None or n < 0:
                    return self._reject(ApiError(411, "length_required", "Content-Length 가 필요합니다"))
                if n > BODY_MAX_BY_PATH.get(path, BODY_MAX):
                    return self._reject(ApiError(413, "too_large", "보낼 내용이 너무 큽니다"))
                raw = self.rfile.read(n) if n else b""
                if len(raw) != n:
                    return self._err(ApiError(400, "bad_json", "본문을 끝까지 받지 못했습니다"))
                if raw.strip():
                    try:
                        body = fsx.loads_strict(raw)
                    except (ValueError, UnicodeDecodeError):
                        return self._err(ApiError(400, "bad_json", "JSON 으로 읽을 수 없습니다"))
                    if not isinstance(body, dict):
                        return self._err(ApiError(400, "not_object", "JSON 객체가 아닙니다"))
                else:
                    body = {}
            if method == "GET" and path in STATIC:
                return self._static(path)
            fn, groups = app.match(method, path)
            if fn is None:
                return self._err(ApiError(404, "not_found", "없는 경로입니다"))
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=False).items() if v}
            req = Req(method, path, q, body, groups, self.client_address[0] if self.client_address else HOST)
            try:
                res = fn(app, req)
            except ApiError as e:
                return self._err(e)
            except Exception as e:                       # 처리기 결함 — 유형만(본문·경로·원문은 싣지 않는다)
                return self._err(ApiError(500, "internal", "화면 서버가 이 요청을 처리하지 못했습니다 — 다시 누르면 이어서 합니다",
                                          [type(e).__name__]))
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], int):
                return self._json(res[0], res[1])
            return self._json(200, res if res is not None else {"ok": True})

        def _static(self, path: str) -> int:
            rel, ctype = STATIC[path]
            try:
                body = app.index_body() if path == "/" else app.static_body(rel)
            except OSError:
                return self._err(ApiError(404, "not_found", "화면 파일이 없습니다"))
            return self._send(200, body, ctype, api=path == "/")

    return Handler


# ───────────────────────────── 포트·단일 인스턴스 ─────────────────────────────
def _avoid(cfg) -> set:
    """대체 포트에서 건너뛸 번호 — 별개 프로젝트·이전 판·코파일럿(portdiag.AVOID) + 팀 서버 포트·대체 후보(R §2.3.2)."""
    from lm27.team.portdiag import AVOID
    out = set(AVOID)
    for k in ("teamServer.bindPort", "team.serverPort"):
        try:
            out.add(int(cfg[k]))
        except (KeyError, TypeError, ValueError):
            pass
    try:
        for a, b in cfg["teamServer.suggestRanges"]:
            out |= set(range(int(a), int(b) + 1))
    except (KeyError, TypeError, ValueError):
        pass
    return out


def candidates(cfg, port=None) -> list:
    """시도할 포트: 기본(``--port`` 또는 ``ui.port``) → +1 … +``ui.portFallbackCount``(회피 집합은 건너뜀)."""
    base = int(port) if port is not None else int(cfg["ui.port"])
    n = int(cfg["ui.portFallbackCount"])
    avoid = _avoid(cfg)
    return [p for p in range(base, base + n + 1) if 1024 <= p <= 65535 and (p == base or p not in avoid)]


def _get_hello(port: int, timeout: float = HELLO_TIMEOUT_S) -> dict | None:
    """``http://127.0.0.1:<port>/api/hello`` — LM27 화면이면 그 응답(dict), 아니면 None. 시스템 프록시를 타지 않는다."""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(urllib.request.Request(f"http://{HOST}:{int(port)}/api/hello",
                                            headers={"Accept": "application/json"}), timeout=timeout) as r:
            raw = r.read(65536)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and obj.get("app") == APP_ID else None


def find_existing(paths, cfg, port=None):
    """이미 떠 있는 같은 ROOT 의 화면 → (port, hello) 또는 None. ``ui_server.json`` 의 pid 가 살아 있고 hello 의
    instance_id·root_id 가 같아야 한다(R §2.3.1)."""
    rid = root_id_of(paths)
    info = fsx.read_json(paths.ui_server_json(), None, want=dict)
    if isinstance(info, dict) and isinstance(info.get("port"), int) and isinstance(info.get("pid"), int):
        from lm27.util.proc import pid_alive
        if info["pid"] != os.getpid() and pid_alive(info["pid"]):
            h = _get_hello(info["port"])
            if h and h.get("root_id") == rid and h.get("instance_id") == info.get("instance_id"):
                return info["port"], h
    return None


def _bind_free(port: int) -> bool:
    """127.0.0.1 에 배타 바인드가 되는가(시험 바인드 후 즉시 닫음)."""
    so = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            so.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        so.bind((HOST, int(port)))
        return True
    except OSError:
        return False
    finally:
        so.close()


def _port_text(cands, code, diag) -> str:
    """포트 전부 실패 — 원인 문구(R §2.3.2 · RPT-37). 사용자에게 시키는 일은 다시 누르기뿐(R §5.0.4)."""
    rng = f"{cands[0]}~{cands[-1]}" if len(cands) > 1 else str(cands[0]) if cands else "?"
    head = f"화면 서버를 열 포트를 찾지 못했습니다(127.0.0.1:{rng} 모두 사용 중{f', WinError {code}' if code else ''})."
    kind = getattr(diag, "kind", "") if diag is not None else ""
    procs = getattr(diag, "procs", None) or []
    who = ""
    if procs and isinstance(procs[0], dict):
        who = f"({procs[0].get('name') or '이름 모름'}, pid {procs[0].get('pid', '?')})"
    if kind == "other_program":
        tail = f" 다른 프로그램{who}이 첫 포트를 쓰고 있습니다. 그 프로그램은 끄지 않습니다."
    elif kind == "reserved":
        tail = f" 윈도우가 {getattr(diag, 'reserved', '') or '이'} 포트 범위를 예약해 두었습니다."
    elif kind == "ephemeral":
        lo, hi = getattr(diag, "dynamic", (0, 0)) or (0, 0)
        tail = f" 다른 프로그램의 바깥 연결이 잠깐 쓰는 번호입니다(임시 포트 범위 {lo}~{hi}). 잠시 뒤 다시 누르면 열릴 수 있습니다."
    elif kind in ("lm27_other", "other_lm"):
        tail = " 다른 폴더의 LM27 화면이나 다른 판 프로그램이 그 포트들을 쓰고 있습니다."
    else:
        tail = " 누가 쓰는지 알아내지 못했습니다."
    return head + tail + " 'lm27 ui --port <1024~65535>' 로 다른 포트를 고를 수 있습니다."


def _start_failed(paths, text: str) -> None:
    _say("[화면] 시작 실패 — " + text)
    try:
        fsx.atomic_write(paths.ui_start_error(), (_utc_iso() + " " + text + "\n").encode("utf-8"))
    except OSError:
        pass


def _write_server_json(paths, app: UiApp) -> None:
    fsx.atomic_write(paths.ui_server_json(), fsx.canon_bytes(
        {"pid": os.getpid(), "port": app.port, "started_at": _utc_iso(), "instance_id": app.instance_id,
         "root_id": app.root_id}))


def _clear_server_json(paths, app: UiApp) -> None:
    info = fsx.read_json(paths.ui_server_json(), None, want=dict)
    if isinstance(info, dict) and info.get("pid") == os.getpid() and info.get("instance_id") == app.instance_id:
        try:
            os.remove(fsx.longp(paths.ui_server_json()))
        except OSError:
            pass


def serve(cfg, port=None, open_browser=True, *, paths=None, deps=None, jobs=None, spawn=None, ready=None) -> int:
    """``lm27 ui`` — rc 0(정상 종료·이미 떠 있는 화면을 엶) · 3(포트 전부 실패 — 계약 §8.3).
    키워드는 시험 주입점: ``paths``·``deps``(UiDeps)·``jobs``·``spawn``(작업 자식)·``ready(app, httpd)``(기동 직후 콜백)."""
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
        try:                                             # 작업 폴더 = %TEMP%(ROOT 를 쥐고 있으면 폴더 이동이 막힌다 — TAB §1.9)
            import tempfile
            os.chdir(tempfile.gettempdir())
        except OSError:
            pass
    deps = deps or UiDeps(paths)
    want_open = bool(open_browser) and bool(cfg["ui.openBrowser"])
    rid = root_id_of(paths)
    hit = find_existing(paths, cfg, port)
    if hit is not None:
        url = f"http://{HOST}:{hit[0]}/"
        _say(f"[화면] 이미 열려 있습니다 — {url}")
        if want_open:
            deps.open_url(url)
        return 0
    cands = candidates(cfg, port)
    app = UiApp(paths, cfg, deps=deps, jobs=jobs, spawn=spawn)
    httpd, last_code = None, 0
    try:
        for p in cands:
            try:
                httpd = UiHTTPServer((HOST, p), make_handler(app))
                break
            except OSError as e:
                last_code = _winerror(e)
                h = _get_hello(p)
                if h is not None and h.get("root_id") == rid:            # 같은 ROOT 의 화면이 그 포트에 있다
                    url = f"http://{HOST}:{p}/"
                    _say(f"[화면] 이미 열려 있습니다 — {url}")
                    if want_open:
                        deps.open_url(url)
                    return 0
        if httpd is None:
            diag = None
            if cands:
                try:
                    diag = deps.diagnose_port(cands[0], last_code, cfg)
                except Exception:                                      # 진단 자체가 막혀도 실패 사유는 알린다
                    diag = None
            _start_failed(paths, _port_text(cands, last_code, diag))
            return 3
        app.port = httpd.server_address[1]
        httpd.app = app
        app.shutdown_cb = httpd.shutdown
        try:
            _write_server_json(paths, app)
        except OSError:
            pass
        try:
            os.remove(fsx.longp(paths.ui_start_error()))
        except OSError:
            pass
        app.prune_logs()
        app.start_idle_watch()
        app.start_team_send_watch()
        url = f"http://{HOST}:{app.port}/"
        _say(f"[화면] 열림 — {url}")
        if want_open:
            try:
                deps.open_url(url)
            except OSError:
                _say("[화면] 브라우저를 열지 못했습니다 — 주소를 직접 여세요")
        if ready is not None:
            ready(app, httpd)
        try:
            httpd.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        app.close()
        if httpd is not None:
            httpd.server_close()
            _clear_server_json(paths, app)


def check(cfg, port=None, *, paths=None, deps=None) -> int:
    """``lm27 ui --check`` — 기동할 수 있는가만 본다(정적 파일·기록 폴더·포트·설정 경고). 사유는 한국어 한 줄씩.
    rc 0 통과(이미 떠 있는 같은 ROOT 화면이 있어도 통과) · 3 기동 불가."""
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    deps = deps or UiDeps(paths)
    bad, notes = [], []
    for rel, _ct in sorted(set(STATIC.values())):
        if not os.path.isfile(fsx.longp(paths.web_file(rel))):
            bad.append(f"화면 파일 web\\{rel.replace('/', chr(92))} 이 없어 화면을 열 수 없습니다")
    for w in getattr(cfg, "config_warnings", ()) or ():
        if isinstance(w, dict) and w.get("text_ko"):
            notes.append("[설정] " + str(w["text_ko"]))
    try:
        fsx.ensure_dir(paths.ui_dir())
        if not os.access(fsx.longp(paths.ui_dir()), os.W_OK):
            raise PermissionError
    except OSError:
        bad.append("화면 기록 폴더(%LOCALAPPDATA%\\LoadMonitor27\\ui)에 쓸 수 없습니다")
    hit = find_existing(paths, cfg, port)
    cands = candidates(cfg, port)
    free = None
    if hit is None:
        free = next((p for p in cands if _bind_free(p)), None)
        if free is None:
            diag = None
            if cands:
                try:
                    diag = deps.diagnose_port(cands[0], 10048, cfg)
                except Exception:                                  # 진단이 막혀도 사유 한 줄은 낸다
                    diag = None
            bad.append(_port_text(cands, 10048, diag))
    for n in notes:
        _say(n)
    if bad:
        for b in bad:
            _say("[화면 점검] " + b)
        return 3
    if hit is not None:
        _say(f"[화면 점검] 통과 — 이미 열려 있는 화면을 씁니다(127.0.0.1:{hit[0]})")
    else:
        _say(f"[화면 점검] 통과 — 127.0.0.1:{free} 로 열 수 있습니다")
    return 0
