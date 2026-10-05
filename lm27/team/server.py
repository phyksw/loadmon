# -*- coding: utf-8 -*-
r"""팀 서버(TAB §3 · 계약 §1.4 · §4.7 · D-18) — 표준 라이브러리 HTTP, 배타 바인드, 사람 단위 원자 교체, 재취합 워커.

    rc = serve(cfg)                       # lm27 team-server [--host H] [--port N] [--store DIR]

  · ``LM27HTTPServer``: ``allow_reuse_address = False`` + ``SO_EXCLUSIVEADDRUSE``(L-20 — 살아 있는 리스너 위 덧바인드 차단).
  · 시작: 저장소 잠금(``run\server.lock``) → 바인드(실패 = 포트 진단 + ``run\port_diag.json`` + rc 3, 포트를 몰래 바꾸지 않음)
    → ``run\server.json``(자기 pid 일 때만 지움) → 워커(재취합·반입 감시·로그 정리·방화벽 진단 타이머).
  · 모든 요청: Host 허용 목록(421 bad_host — DNS 재바인딩) · ``allow_cidrs``(403) · API ``Cache-Control: no-store`` ·
    ``X-Content-Type-Options: nosniff`` · ``Access-Control-Allow-Origin`` 없음 · OPTIONS 405.
  · ``/api/hello`` 에 경로·pid·토큰·호스트명 0. 오류 응답 = ``{ok:false, code, error, detail[경로: 코드]}`` — 값 없음.
  · 본문이 있는 요청은 '읽고' 거절한다(64MB 까지 drain — 안 읽고 답하면 RST 로 응답조차 못 간다, LM24 실측).
  · 서버는 묶음을 고치지 않고 거절(422)한다. 재취합은 하위 프로세스(``team-aggregate``)가 ``result.json`` 을 쓰고 서버는
    그것만 읽는다(표준출력 파싱 없음). 성공하면 ``out\current.json`` 원자 교체, 실패면 이전 세대를 계속 서빙.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lm27 import LM27_VERSION
from lm27.team import firewall, offline, portdiag, schema
from lm27.team.store import PK_RX, err_body, ingest_bytes, now_local, open_store, token_ok
from lm27.util import fsx

MB = 1024 * 1024
DRAIN_MAX = 64 * MB
JSON_BODY_MAX = 4 * MB                      # 레지스트리(2MB)·명단 수정 본문 상한
CSP_DASH = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
CSP_REPORT = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"
# 정적 파일 고정 사전(TAB §3.12 · X-279 — team.css 없음). 경로 조합 금지.
STATIC = {
    "/": ("team/index.html", "text/html; charset=utf-8"),
    "/admin": ("team/admin.html", "text/html; charset=utf-8"),
    "/static/lm27.css": ("common/lm27.css", "text/css; charset=utf-8"),
    "/static/lm27charts.js": ("common/lm27charts.js", "text/javascript; charset=utf-8"),
    "/static/lm27ui.js": ("common/lm27ui.js", "text/javascript; charset=utf-8"),
    "/static/icons.svg": ("common/icons.svg", "image/svg+xml"),
    "/static/team.js": ("team/team.js", "text/javascript; charset=utf-8"),
}
REPORTS = {"/report": "team_report.html", "/report/share": "team_report_share.html"}
ADMIN_HEADER = "X-LM27-Admin-Token"
UPLOAD_HEADER = "X-LM27-Upload-Token"
_ROLE_RX = re.compile(r"r_[0-9a-f]{6}")


def _say(msg: str) -> None:
    st = sys.stdout
    if st is not None:
        try:
            st.write(msg + "\n")
            st.flush()
        except (OSError, ValueError):
            pass


class LM27HTTPServer(ThreadingHTTPServer):
    """배타 바인드 서버. 기본 HTTPServer 는 allow_reuse_address=1 — 윈도우에서 살아 있는 리스너 위 덧바인드를 허용한다(실측)."""

    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 32

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)            # getfqdn(역방향 DNS) 을 하지 않는다
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def handle_error(self, request, client_address):
        """처리 중 예외 — 유형만 로그(본문·경로를 콘솔에 찍지 않는다)."""
        app = getattr(self, "app", None)
        exc = sys.exc_info()[1]
        if app is not None:
            app.store.log_line("error", f"요청 처리 예외 {type(exc).__name__}")


# ───────────────────────────── 재취합 워커 ─────────────────────────────
def subprocess_runner(store, gen: int, cfg) -> dict:
    """``python lm27_cli.py team-aggregate --store <dir> --gen N``(시간 제한 ``teamServer.aggregateTimeoutSec``, cwd = 저장소).
    서버는 표준출력이 아니라 ``out\\gen_N\\result.json`` 을 읽는다. stderr 끝 20줄은 aggregate 로그로."""
    from lm27.paths import Paths
    from lm27.util.proc import run_child
    paths = store.paths or Paths()
    exe = paths.python_exe() if paths.python_exe().is_file() else sys.executable
    argv = [str(exe), "-X", "utf8", "-B", str(paths.cli_script()), "team-aggregate", "--store", str(store.dir),
            "--gen", str(int(gen))]
    r = run_child(argv, timeout_s=cfg["teamServer.aggregateTimeoutSec"], cwd=str(store.dir))
    tail = r.stderr.decode("utf-8", "replace").splitlines()[-20:]
    for ln in tail:
        store.log_aggregate("stderr " + ln[:200])
    res = fsx.read_json(store.gen_dir(gen) / "result.json", None)
    if r.timed_out:
        return {"ok": False, "members": 0, "warnings": ["재취합 시간 초과"], "sec": r.elapsed_s}
    if not isinstance(res, dict):
        return {"ok": False, "members": 0, "warnings": [f"재취합 결과 없음(rc {r.rc})"], "sec": r.elapsed_s}
    return res


class AggWorker:
    """단일 재취합 워커(LM24 AGG_LOCK 계승) — 연속 요청을 ``aggregateDebounceSec`` 동안 모아 한 번 돈다(세대 번호 증가)."""

    def __init__(self, store, cfg, runner=None):
        self.store, self.cfg = store, cfg
        self.runner = runner or (lambda st, gen: subprocess_runner(st, gen, cfg))
        self.cond = threading.Condition()
        self.req = 0
        self.done = 0
        self.running = False
        self.last = {"gen": (store.current_gen() or {}).get("gen"), "state": "idle", "at": None, "sec": None, "note": ""}
        self._stop = False
        self.thread = None
        self.runs = 0

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="lm27-team-agg", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        with self.cond:
            self._stop = True
            self.cond.notify_all()

    def request(self) -> int:
        with self.cond:
            self.req += 1
            self.cond.notify_all()
            return self.req

    def status(self) -> dict:
        with self.cond:
            st = dict(self.last)
            if self.req > self.done:
                st["state"] = "running" if self.running else "queued"
            return st

    def request_and_wait(self, timeout_s: float) -> dict:
        ticket = self.request()
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self.cond:
            while self.done < ticket and not self._stop:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.cond.wait(left)
            st = dict(self.last)
            if self.done < ticket:
                st["state"] = "queued"
            return {"gen": st.get("gen"), "state": st.get("state"), "note": st.get("note", "")}

    def _loop(self):
        while True:
            with self.cond:
                while self.done >= self.req and not self._stop:
                    self.cond.wait(1.0)
                if self._stop:
                    return
            time.sleep(max(0.0, float(self.cfg["teamServer.aggregateDebounceSec"])))
            with self.cond:
                take = self.req
                self.running = True
            gen = self.store.next_gen()
            t0 = time.monotonic()
            try:
                res = self.runner(self.store, gen)
                res = res.as_result_json() if hasattr(res, "as_result_json") else dict(res or {})
                ok = bool(res.get("ok"))
                if ok:
                    self.store.publish_gen(gen, res)
            except Exception as e:                      # 워커는 죽지 않는다 — 이전 세대를 계속 서빙
                ok, res = False, {"warnings": [f"재취합 예외 {type(e).__name__}"]}
            sec = time.monotonic() - t0
            note = (f"{res.get('members', 0)}명 취합" if ok else
                    "실패 — " + "; ".join(str(x) for x in (res.get("warnings") or [])[-1:]))
            self.store.log_aggregate(f"gen {gen} {'done' if ok else 'failed'} {sec:.1f}s")
            with self.cond:
                self.running = False
                self.runs += 1
                self.done = take
                self.last = {"gen": gen if ok else (self.store.current_gen() or {}).get("gen"),
                             "state": "done" if ok else "failed", "at": now_local().isoformat(), "sec": sec,
                             "note": note[:200]}
                self.cond.notify_all()


# ───────────────────────────── 앱(요청 공통 상태) ─────────────────────────────
def local_ipv4s() -> set[str]:
    out = set()
    try:
        for fam, _t, _p, _c, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if fam == socket.AF_INET:
                out.add(sa[0])
    except OSError:
        pass
    return out


class TeamServerApp:
    """요청 처리기가 공유하는 상태 — 저장소·설정·워커·계측. ``client_ip`` 는 시험 주입점(HTTP 헤더가 아니다)."""

    def __init__(self, store, cfg, *, runner=None, firewall_run=None, clock=None):
        self.store, self.cfg = store, cfg
        self.clock = clock or now_local
        self.instance_id = secrets.token_hex(8)
        self.upload_sem = threading.BoundedSemaphore(max(1, int(cfg["teamServer.maxConcurrentUploads"])))
        self.agg = AggWorker(store, cfg, runner)
        self.firewall_run = firewall_run
        self.started = time.monotonic()
        self.external = 0
        self._lk = threading.Lock()
        self.firewall_hint = None
        self.port = 0
        self.bind_host = cfg["teamServer.bindHost"]
        self.ips = local_ipv4s()
        self.shutdown_cb = None
        self.client_ip = lambda h: h.client_address[0]
        self._td = (None, None, None)
        self.cidrs = []
        for c in cfg["teamServer.allowCidrs"] or ():
            try:
                self.cidrs.append(ipaddress.ip_network(c, strict=False))
            except ValueError:
                continue

    # 판정 ---------------------------------------------------------------
    def host_ok(self, host: str | None) -> bool:
        if not host:
            return False
        h = host.strip().lower()
        names = {"127.0.0.1", "localhost", "[::1]"} | {x.lower() for x in self.ips}
        if self.bind_host not in ("0.0.0.0", "::", ""):
            names.add(str(self.bind_host).lower())
        names |= {str(x).strip().lower() for x in self.cfg["teamServer.allowedHosts"] or ()}
        if h in names:
            return True
        m = re.fullmatch(r"(.+):(\d{1,5})", h)
        return bool(m) and m.group(1) in names and int(m.group(2)) == self.port

    @staticmethod
    def is_loopback(ip: str) -> bool:
        try:
            return ipaddress.ip_address(ip.split("%")[0]).is_loopback
        except ValueError:
            return False

    def ip_ok(self, ip: str) -> bool:
        if not self.cidrs or self.is_loopback(ip):
            return True
        try:
            a = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        return any(a in n for n in self.cidrs)

    def count_request(self, ip: str) -> None:
        if not self.is_loopback(ip):
            with self._lk:
                self.external += 1

    def current_td(self):
        """현재 세대 team_data(gen 별 캐시) → (gen, dict|None, details|None)."""
        cur = self.store.current_gen()
        g = (cur or {}).get("gen")
        if g is None:
            return None, None, None
        if self._td[0] != g:
            td = fsx.read_json(self.store.gen_dir(g) / "team_data.json", None)
            det = fsx.read_json(self.store.gen_dir(g) / "details.json", None)
            self._td = (g, td, det)
        return self._td

    def hello(self) -> dict:
        tok = self.cfg["teamServer.uploadTokenSha256"]
        return {"app": schema.APP_ID, "proto": schema.PROTO, "version": LM27_VERSION, "api": schema.API_LEVEL,
                "accepts": {"team_bundle": dict(schema.ACCEPTS)},
                "auth": {"upload": bool(tok), "read": bool(self.cfg["teamServer.readRequiresToken"])},
                "max_body_mb": self.cfg["teamServer.maxBodyMb"], "instance_id": self.instance_id,
                "store_id": self.store.store_id, "name": self.cfg["teamServer.displayName"] or "",
                "registry_version": self.store.registry_version(), "pepper_id": self.store.pepper_id,
                "server_time": self.clock().isoformat()}

    def status(self) -> dict:
        n, last = self.store.uploads_today()
        pending = sum(1 for _n, _p, st in offline._candidates(str(self.store.inbox()), 1 << 62, time.time())
                      if st in ("ok", "copying"))
        rejected = sum(1 for x in os.listdir(fsx.longp(self.store.inbox("rejected")))
                       if x.endswith(".json") and not x.endswith(".reason.json")) if self.store.inbox("rejected").is_dir() else 0
        return {"uploads_today": n, "last_upload_at": last, "aggregate": self.agg.status(),
                "members": len(self.store.member_keys()), "inbox": {"pending": pending, "rejected": rejected},
                "external_requests": self.external, "firewall_hint": self.firewall_hint}


# ───────────────────────────── 요청 처리기 ─────────────────────────────
def make_handler(app: TeamServerApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = schema.APP_ID
        sys_version = ""
        protocol_version = "HTTP/1.1"
        timeout = app.cfg["teamServer.requestTimeoutSec"]

        def log_message(self, fmt, *args):            # 콘솔 소음 억제 — 결과는 저장소 로그로만
            pass

        # 응답 ------------------------------------------------------------
        def _send(self, code: int, body: bytes, ctype: str, extra=None, api=True):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if api:
                self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)

        def _json(self, code: int, obj, extra=None):
            self._send(code, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                       "application/json; charset=utf-8", extra)

        def _err(self, code: int, ecode: str, msg: str, detail=(), extra=None):
            self._json(code, err_body(ecode, msg, detail), extra)

        def _length(self):
            v = self.headers.get("Content-Length")
            if v is None:
                return None
            v = v.strip()
            return int(v) if v.isdigit() else -1

        def _drain(self, n):
            left = min(max(n or 0, 0), DRAIN_MAX)
            try:
                while left > 0:
                    chunk = self.rfile.read(min(MB, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except OSError:
                self.close_connection = True
            if (n or 0) > DRAIN_MAX:
                self.close_connection = True

        def _reject(self, code, ecode, msg, detail=(), extra=None):
            """본문을 읽고(64MB 까지) 거절한다 — 안 읽고 답하면 RST 로 응답이 유실된다."""
            n = self._length()
            if self.command in ("POST", "PUT", "PATCH", "OPTIONS", "DELETE"):
                self._drain(n if n and n > 0 else 0)
            self._err(code, ecode, msg, detail, extra)

        def _read_exact(self, n: int) -> bytes | None:
            buf, left = [], n
            try:
                while left > 0:
                    chunk = self.rfile.read(min(MB, left))
                    if not chunk:
                        return None
                    buf.append(chunk)
                    left -= len(chunk)
            except OSError:
                return None
            return b"".join(buf)

        # 공통 관문 --------------------------------------------------------
        def _gate(self) -> bool:
            ip = app.client_ip(self)
            if not app.host_ok(self.headers.get("Host")):
                self._reject(421, "bad_host", "Host 헤더가 이 서버 주소가 아닙니다")
                return False
            if not app.ip_ok(ip):
                self._reject(403, "forbidden_ip", "이 주소에서는 접근할 수 없습니다(허용 대역 밖)")
                return False
            app.count_request(ip)
            return True

        def _read_auth(self) -> bool:
            if not app.cfg["teamServer.readRequiresToken"]:
                return True
            return self._token_ok(UPLOAD_HEADER, app.cfg["teamServer.uploadTokenSha256"])

        def _token_ok(self, header, want) -> bool:
            given = self.headers.get(header)
            if want and token_ok(given, want):
                return True
            self._reject(401, "token_required" if not given else "token_invalid",
                         "토큰이 필요합니다" if not given else "토큰이 맞지 않습니다")
            return False

        def _admin_ok(self) -> bool:
            if app.is_loopback(app.client_ip(self)):
                return True
            want = app.cfg["teamServer.adminTokenSha256"]
            if want and token_ok(self.headers.get(ADMIN_HEADER), want):
                return True
            self._reject(403, "admin_only", "관리 권한이 필요합니다(관리 토큰 또는 이 PC 에서)")
            return False

        def _json_body(self, maxb=JSON_BODY_MAX):
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                self._reject(415, "content_type", "application/json 만 받습니다")
                return None
            n = self._length()
            if n is None:
                self._reject(411, "length_required", "Content-Length 가 필요합니다")
                return None
            if n <= 0:
                self._reject(400, "bad_json", "본문이 비었습니다")
                return None
            if n > maxb:
                self._reject(413, "too_large", "본문이 너무 큽니다")
                return None
            raw = self._read_exact(n)
            if raw is None:
                self.close_connection = True
                self._err(400, "bad_json", "본문을 끝까지 받지 못했습니다")
                return None
            try:
                obj = fsx.loads_strict(raw)
            except ValueError as e:
                self._err(400, "dup_key" if "dup key" in str(e) else "bad_json", "JSON 으로 읽을 수 없습니다")
                return None
            if not isinstance(obj, dict):
                self._err(400, "not_object", "JSON 객체가 아닙니다")
                return None
            return obj

        # 메서드 ----------------------------------------------------------
        def do_OPTIONS(self):                      # 교차 출처 사전 요청에 허용을 주지 않는다
            self._reject(405, "method", "허용되지 않는 메서드입니다", extra={"Allow": "GET, POST, PUT, PATCH"})

        def do_DELETE(self):
            self.do_OPTIONS()

        def do_HEAD(self):
            self.do_OPTIONS()

        def do_GET(self):
            if not self._gate():
                return
            u = urllib.parse.urlsplit(self.path)
            path = u.path
            if path == "/api/hello":
                return self._json(200, app.hello())
            if path == "/api/status":
                return self._json(200, app.status())
            if path in STATIC:
                return self._static(path)
            if path in REPORTS:
                return self._report(path)
            if path.startswith("/api/") and not self._read_auth():
                return None
            if path == "/api/registry":
                reg = app.store.registry_for_client()
                etag = f'"{reg.get("version", 0)}"'
                if self.headers.get("If-None-Match") == etag:
                    return self._send(304, b"", "application/json; charset=utf-8", {"ETag": etag})
                return self._json(200, reg, {"ETag": etag})
            if path == "/api/members":
                return self._json(200, app.store.members_view(app.current_td()[1]))
            if path == "/api/team":
                g, _td, _d = app.current_td()
                raw = app.store.current_file("team_data.json") if g is not None else None
                if raw is None:
                    return self._err(404, "not_found", "아직 취합 결과가 없습니다 — 첫 업로드 뒤 생깁니다")
                return self._send(200, raw, "application/json; charset=utf-8")
            if path == "/api/team/detail":
                return self._detail(urllib.parse.parse_qs(u.query))
            return self._err(404, "not_found", "없는 경로입니다")

        def _static(self, path):
            from lm27.paths import Paths
            rel, ctype = STATIC[path]
            try:
                body = fsx.read_bytes((app.store.paths or Paths()).web_file(rel))
            except OSError:
                return self._err(404, "not_found", "화면 파일이 아직 없습니다")
            return self._send(200, body, ctype, {"Content-Security-Policy": CSP_DASH, "Referrer-Policy": "no-referrer"},
                              api=False)

        def _report(self, path):
            if app.cfg["teamServer.readRequiresToken"]:
                return self._err(403, "read_token_mode", "토큰 모드에서는 대시보드의 [보고서 내려받기]로만 받습니다")
            body = app.store.current_file(REPORTS[path])
            if body is None:
                return self._err(404, "not_found", "팀 보고서가 아직 없습니다")
            return self._send(200, body, "text/html; charset=utf-8",
                              {"Content-Security-Policy": CSP_REPORT, "Referrer-Policy": "no-referrer"}, api=False)

        def _detail(self, q):
            pk = (q.get("person") or [""])[0]
            rid = (q.get("role") or [""])[0]
            if not PK_RX.fullmatch(pk) or not _ROLE_RX.fullmatch(rid):
                return self._err(404, "not_found", "사람 키·역할 ID 형식이 아닙니다")
            _g, td, det = app.current_td()
            idx = None
            for p in (td or {}).get("people") or ():
                if p.get("person_key") == pk or pk in (p.get("linked") or ()):
                    idx = p.get("i")
            item = (det or {}).get(f"{idx}|{rid}") if idx is not None else None
            if item is None:
                return self._err(404, "not_found", "그 사람·역할의 상세가 없습니다")
            return self._json(200, item)

        def do_POST(self):
            if not self._gate():
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/bundles":
                return self._post_bundle()
            if path == "/api/upload":
                return self._reject(410, "lm24_endpoint", "이 서버는 LM27 팀 서버입니다. LM24 업로드는 받지 않습니다.")
            if path == "/api/shutdown":
                if not app.is_loopback(app.client_ip(self)):
                    return self._reject(403, "admin_only", "로컬에서만 가능합니다")
                self._drain(self._length() or 0)
                self.close_connection = True
                self._json(200, {"ok": True, "stopping": True})
                if app.shutdown_cb is not None:
                    threading.Thread(target=app.shutdown_cb, daemon=True).start()
                return None
            if path == "/api/aggregate":
                if not self._admin_ok():
                    return None
                self._drain(self._length() or 0)
                app.agg.request()
                return self._json(200, {"ok": True, "aggregate": app.agg.status()})
            return self._reject(404, "not_found", "없는 경로입니다")

        def _post_bundle(self):
            cfg = app.cfg
            want = cfg["teamServer.uploadTokenSha256"]
            n = self._length()
            if want and not token_ok(self.headers.get(UPLOAD_HEADER), want):
                given = self.headers.get(UPLOAD_HEADER)
                return self._reject(401, "token_required" if not given else "token_invalid",
                                    "업로드 토큰이 필요합니다" if not given else "업로드 토큰이 맞지 않습니다")
            if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                return self._reject(415, "content_type", "application/json 만 받습니다")
            if n is None:
                return self._reject(411, "length_required", "Content-Length 가 필요합니다")
            if n <= 0:
                return self._reject(400, "bad_json", "본문이 비었거나 길이가 숫자가 아닙니다")
            if n > cfg["teamServer.maxBodyMb"] * MB:
                return self._reject(413, "too_large", "묶음이 서버 상한보다 큽니다 — 기간을 나눠 다시 만드세요")
            if not app.upload_sem.acquire(blocking=False):
                return self._reject(429, "busy", "동시 업로드가 많습니다 — 잠시 뒤 다시 보냅니다", extra={"Retry-After": "30"})
            try:
                raw = self._read_exact(n)
                if raw is None:
                    self.close_connection = True
                    return self._err(400, "bad_json", "본문을 끝까지 받지 못했습니다")
                r = ingest_bytes(app.store, raw, source="http", claimed_sha=self.headers.get("X-LM27-Bundle-SHA256"),
                                 client=(self.headers.get("X-LM27-Client") or "")[:20], ip=app.client_ip(self))
            finally:
                app.upload_sem.release()
            if not r.ok:
                return self._json(r.http, r.body())
            agg = app.agg.request_and_wait(cfg["teamServer.aggregateWaitSec"]) if r.status == "stored" \
                else app.agg.status()
            body = r.body()
            body["aggregate"] = {"gen": agg.get("gen"), "state": agg.get("state"), "note": agg.get("note", "")}
            return self._json(200, body)

        def do_PUT(self):
            if not self._gate():
                return
            if urllib.parse.urlsplit(self.path).path != "/api/registry":
                return self._reject(404, "not_found", "없는 경로입니다")
            if not self._admin_ok():
                return None
            obj = self._json_body()
            if obj is None:
                return None
            code, body = app.store.put_registry(obj)
            if code == 200:
                offline.publish_registry(app.store, app.cfg)
                app.agg.request()
            return self._json(code, body)

        def do_PATCH(self):
            if not self._gate():
                return
            m = re.fullmatch(r"/api/members/(p_[0-9a-f]{12})", urllib.parse.urlsplit(self.path).path)
            if not m:
                return self._reject(404, "not_found", "없는 경로입니다")
            if not self._admin_ok():
                return None
            obj = self._json_body()
            if obj is None:
                return None
            code, body = app.store.patch_member(m.group(1), obj)
            if code == 200:
                app.agg.request()
            return self._json(code, body)

    return Handler


# ───────────────────────────── 서버 ─────────────────────────────
class TeamServer:
    """바인드·서빙·워커 묶음. ``serve`` 와 시험이 같은 클래스를 쓴다."""

    def __init__(self, cfg, store, *, host=None, port=None, runner=None, firewall_run=None, inbox=True,
                 maintenance=True):
        self.cfg, self.store = cfg, store
        self.host = cfg["teamServer.bindHost"] if host is None else host
        self.port = cfg["teamServer.bindPort"] if port is None else port
        self.app = TeamServerApp(store, cfg, runner=runner, firewall_run=firewall_run)
        self.httpd = None
        self._stop = threading.Event()
        self._threads = []
        self._inbox, self._maint = inbox, maintenance
        self._fw_done = False
        self._serving = None

    def bind(self):
        """배타 바인드 — 실패하면 OSError 를 그대로(호출자가 포트 진단)."""
        self.httpd = LM27HTTPServer((self.host, int(self.port)), make_handler(self.app))
        self.httpd.app = self.app
        self.port = self.httpd.server_address[1]
        self.app.port = self.port
        self.app.shutdown_cb = self.shutdown
        return self

    def start_workers(self):
        self.app.agg.start()
        cur = self.store.current_gen()
        stale = cur is not None and cur.get("registry_version") != self.store.registry_version()
        if (cur is None and self.store.member_keys()) or stale:
            self.app.agg.request()                       # 시작 때 재취합 1회(세대 없음 또는 레지스트리 바뀜)
        if self._inbox:
            self._spawn(self._inbox_loop, "lm27-team-inbox")
        if self._maint:
            self._spawn(self._maint_loop, "lm27-team-maint")

    def _spawn(self, fn, name):
        t = threading.Thread(target=fn, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _inbox_loop(self):
        while not self._stop.is_set():
            try:
                r = offline.scan_inboxes(self.store, self.cfg)
                if r["stored"]:
                    self.app.agg.request()
            except Exception as e:                       # 감시는 멈추지 않는다
                self.store.log_line("inbox", f"반입 감시 예외 {type(e).__name__}")
            if self._stop.wait(float(self.cfg["teamServer.inboxPollSec"])):
                return

    def _maint_loop(self):
        day = None
        while not self._stop.is_set():
            today = now_local().date()
            if today != day:
                day = today
                self.store.cleanup_logs()
            up = time.monotonic() - self.app.started
            if firewall.hint_due(up, self.app.external, self.cfg, done=self._fw_done):
                self._fw_done = True
                self.run_firewall_diag(quiet_min=self.cfg["teamServer.firewallHintAfterMin"])
            if self._stop.wait(30):
                return

    def run_firewall_diag(self, quiet_min=None) -> dict:
        d = firewall.firewall_diag(sys.executable, run=self.app.firewall_run, port=self.port, quiet_min=quiet_min)
        fsx.atomic_write(self.store.run_file("firewall_diag.json"), fsx.canon_bytes(d))
        self.app.firewall_hint = {"suspect": d["suspect"], "level": d["level"], "message_ko": d["message_ko"],
                                  "at": now_local().isoformat()}
        if d["suspect"]:
            _say("[팀 서버] " + d["message_ko"] + f" (막힌 실행 파일: {sys.executable})")   # 경로는 콘솔에만
        return d

    def start(self):
        """시험용 — 백그라운드 스레드에서 서빙 + 워커."""
        self.start_workers()
        self._serving = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                         name="lm27-team-http", daemon=True)
        self._serving.start()
        return self

    def serve_forever(self):
        self.start_workers()
        self.httpd.serve_forever(poll_interval=0.5)

    def shutdown(self):
        self._stop.set()
        self.app.agg.stop()
        if self.httpd is not None:
            self.httpd.shutdown()

    def close(self):
        self._stop.set()
        self.app.agg.stop()
        if self.httpd is not None:
            self.httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def serve(cfg, *, store=None, runner=None, ready=None, diag=None) -> int:
    """``lm27 team-server`` — rc 0 정상 종료 · 3 환경 실패(저장소를 다른 서버가 씀 · 포트 점유).
    ``diag(port, winerror, cfg, store_id) -> PortDiag`` 는 시험 주입점(기본 ``portdiag.diagnose_port``)."""
    store = store or open_store(cfg)
    if not store.lock_server():
        info = store.server_info() or {}
        _say(f"[팀 서버] 이 저장소를 이미 쓰는 서버가 있습니다(pid {info.get('pid', '?')}) — 새로 띄우지 않습니다.")
        return 3
    srv = None
    try:
        srv = TeamServer(cfg, store, runner=runner)
        try:
            srv.bind()
        except OSError as e:
            d = (diag or (lambda p, c, cf, sid: portdiag.diagnose_port(p, c, cf, store_id=sid)))(
                int(srv.port), portdiag.winerror_of(e), cfg, store.store_id)
            fsx.atomic_write(store.run_file("port_diag.json"), fsx.canon_bytes(d.as_dict()))
            store.log_line("start", f"바인드 실패 포트 {srv.port} {d.kind} WinError {d.code}")
            _say("[팀 서버] 시작 실패 — " + d.message)
            srv = None
            return 3
        store.write_server_json(pid=os.getpid(), port=srv.port, host=srv.host, instance_id=srv.app.instance_id,
                                exe=sys.executable)
        store.log_line("start", f"가동 포트 {srv.port}")
        ips = sorted(local_ipv4s()) or ["<이 PC 의 IP>"]
        _say("[팀 서버] 가동 — 팀원에게 알릴 주소: " + ", ".join(f"http://{ip}:{srv.port}" for ip in ips))
        _say(f"[팀 서버] 저장소: {store.dir}")              # 경로는 이 콘솔에만(응답·로그에는 쓰지 않는다)
        if ready is not None:
            ready(srv)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            _say("[팀 서버] 종료")
        return 0
    finally:
        if srv is not None:
            srv.close()
            store.clear_server_json_if_mine(os.getpid(), srv.app.instance_id)
            store.log_line("stop", "종료")
        store.release_server()
