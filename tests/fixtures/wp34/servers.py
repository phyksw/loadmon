# -*- coding: utf-8 -*-
r"""WP-34 시험 서버 — 127.0.0.1 에만 묶는다(0.0.0.0 금지 — 방화벽 창). 포트는 시험 전용 19400~19449(WP-27 시험 대역
19350~19399 와 겹치지 않게, 별개 프로젝트·이전 판·실제 팀 서버 포트를 쓰지 않는다). 바인드는 배타(덧바인드 없음).

    with fake_team("lm27") as fs:        # 흉내 서버 — fs.port · fs.posts(받은 POST) · fs.state(응답 바꾸기)
    with real_team(tmp) as ts:           # WP-27 팀 서버 실물(저장소·정제 재검사·취합) — U01 미리보기 = 실전송 = 저장 sha
    p = dead_port()                      # 아무도 듣지 않는 시험 포트(연결 거부)

흉내 모드: lm27(정상) · v2(묶음 주판 2만 받음) · lm24(이전 판 모양) · other_lm(다른 판 LM) · other_app(다른 프로그램).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lm27.team import schema as S

TREE = Path(__file__).resolve().parents[3]
APP_ID, PROTO = S.APP_ID, S.PROTO                 # 팀 서버 신원 — 상수를 한 곳(schema)에서(L-15: 이름 문자열을 새로 쓰지 않음)
PORTS = range(19400, 19450)
HOST = "127.0.0.1"


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False                   # 덧바인드 금지(L-20 와 같은 원칙)
    daemon_threads = True


def _bind(handler, port: int | None = None) -> tuple[_Server, int]:
    last = None
    for p in ((port,) if port is not None else PORTS):
        if p not in PORTS:
            raise ValueError("시험 포트(19400~19449)만 씁니다")
        try:
            return _Server((HOST, p), handler), p
        except OSError as e:                      # 다른 시험·프로그램이 쓰는 포트 — 다음 포트
            last = e
    raise RuntimeError(f"시험 포트(19400~19449)를 하나도 묶지 못했습니다: {type(last).__name__}")


def dead_port() -> int:
    """지금 아무도 듣지 않는 시험 포트(묶었다가 바로 놓는다 — 연결 거부 시험)."""
    for p in reversed(PORTS):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((HOST, p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("빈 시험 포트가 없습니다")


# LM24 흉내 /api/whoami 응답 — 이 값들이 클라이언트 쪽 어디에도 남으면 안 된다(U06 '응답 본문 기록 0')
WHOAMI = {"root": "WHOAMI-ROOT-CANARY", "store": "WHOAMI-STORE-CANARY", "pid": 1, "token": "WHOAMI-TOKEN-CANARY"}


class FakeState:
    """흉내 서버 상태 — 시험이 고쳐 응답을 바꾼다. 받은 요청은 경로·헤더 일부·본문 sha 만 남긴다."""

    def __init__(self, mode: str = "lm27"):
        self.mode = mode
        self.auth_upload = False
        self.auth_read = False
        self.token = None                          # 기대 업로드 토큰(평문 — 시험 값)
        self.post_status = None                    # None = 정상(200 + 받은 바이트 sha), 정수 = 그 코드로 거절
        self.bad_sha = False                       # 200 이지만 다른 sha 를 돌려준다
        self.posts: list = []
        self.gets: list = []
        self.members = {"members": []}
        self.registry = None
        self.via = False                           # 응답에 프록시 표식 헤더(Via)를 붙인다
        self.post_delay = 0.0                      # POST 응답 전 지연(초) — 동시 전송 시험
        self.lock = threading.Lock()

    @property
    def etag(self) -> str:
        return f'"{(self.registry or {}).get("version", 0)}"'

    def hello(self):
        if self.mode in ("lm27", "v2"):
            acc = {"1": 0} if self.mode == "lm27" else {"2": 0}
            return 200, {"app": APP_ID, "proto": PROTO, "version": "0.1.0", "api": 1,
                         "accepts": {"team_bundle": acc}, "auth": {"upload": self.auth_upload, "read": self.auth_read},
                         "max_body_mb": 16, "instance_id": "0" * 16, "store_id": "1" * 16, "name": "시험 팀 서버",
                         "registry_version": (self.registry or {}).get("version", 0), "pepper_id": None,
                         "server_time": "2026-10-01T09:00:00+09:00"}
        if self.mode == "other_lm":
            return 200, {"app": "LM25-team", "proto": "lm25-team/1"}
        if self.mode == "other_app":
            return 200, {"service": "something-else"}
        return 404, {"error": "not found"}


def _handler(st: FakeState):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code: int, obj=None, extra=None):
            body = b"" if obj is None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            if st.via:
                self.send_header("Via", "1.1 test-proxy")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _tok_ok(self, need: bool) -> bool:
            return not need or (st.token is not None and self.headers.get("X-LM27-Upload-Token") == st.token)

        def do_GET(self):
            with st.lock:
                st.gets.append(self.path)
            if self.path == "/api/hello":
                return self._send(*st.hello())
            if st.mode == "lm24":
                if self.path == "/api/whoami":
                    return self._send(200, WHOAMI)
                return self._send(404, {"error": "not found"})
            if self.path == "/api/members":
                if not self._tok_ok(st.auth_read):
                    return self._send(401, {"ok": False, "code": "token_required", "error": "토큰이 필요합니다"})
                return self._send(200, st.members)
            if self.path == "/api/registry":
                if not self._tok_ok(st.auth_read):
                    return self._send(401, {"ok": False, "code": "token_required", "error": "토큰이 필요합니다"})
                if st.registry is None:
                    return self._send(404, {"ok": False, "code": "not_found", "error": "없음"})
                if self.headers.get("If-None-Match") == st.etag:
                    return self._send(304, None, {"ETag": st.etag})
                return self._send(200, st.registry, {"ETag": st.etag})
            return self._send(404, {"ok": False, "code": "not_found", "error": "없는 경로입니다"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n > 0 else b""
            sha = hashlib.sha256(raw).hexdigest()
            if st.post_delay:
                time.sleep(st.post_delay)
            with st.lock:
                st.posts.append({"path": self.path, "sha": sha, "claimed": self.headers.get("X-LM27-Bundle-SHA256"),
                                 "client": self.headers.get("X-LM27-Client"), "sent_at": self.headers.get("X-LM27-Sent-At"),
                                 "token": self.headers.get("X-LM27-Upload-Token"), "bytes": len(raw)})
                seen = sum(1 for p in st.posts if p["sha"] == sha) > 1
            if self.path != "/api/bundles":
                return self._send(404, {"ok": False, "code": "not_found", "error": "없는 경로입니다"})
            if not self._tok_ok(st.auth_upload):
                code = "token_required" if not self.headers.get("X-LM27-Upload-Token") else "token_invalid"
                return self._send(401, {"ok": False, "code": code, "error": "업로드 토큰이 맞지 않습니다", "detail": []})
            if st.post_status is not None:
                return self._send(st.post_status, {"ok": False, "code": "schema", "error": "검증 실패",
                                                   "detail": ["units[0].title: schema"]})
            return self._send(200, {"ok": True, "status": "already_have" if seen else "stored",
                                    "sha256": ("0" * 64) if st.bad_sha else sha, "person_key": "p_000000000000",
                                    "period_key": "x", "replaced": None,
                                    "aggregate": {"gen": 1, "state": "done", "note": ""}})
    return H


@contextlib.contextmanager
def fake_team(mode: str = "lm27", *, port: int | None = None):
    """흉내 서버 — ``port`` 를 주면 그 시험 포트에만 묶는다(꺼져 있던 서버가 다시 켜지는 U05 · U14)."""
    st = FakeState(mode)
    srv, port = _bind(_handler(st), port)
    st.port = port
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    try:
        yield st
    finally:
        srv.shutdown()
        srv.server_close()


@contextlib.contextmanager
def real_team(store_dir, **over):
    """WP-27 팀 서버 실물(같은 프로세스, 재취합 = 같은 프로세스 aggregate). 정제 재검사는 실물(privacy_payload_check)."""
    from lm27.config import load_config
    from lm27.paths import Paths
    from lm27.team import aggregate as A
    from lm27.team.server import TeamServer
    from lm27.team.store import open_store
    ov = {"teamServer.storeDir": str(store_dir), "teamServer.aggregateDebounceSec": 0}
    ov.update(over)
    none = os.path.join(tempfile.gettempdir(), "lm27t_wp34_none_config.json")
    c = load_config(registry_path=str(TREE / "config" / "settings_registry.json"), config_path=none, overrides=ov)
    store = open_store(c, paths=Paths(TREE))
    srv = None
    for p in PORTS:
        cand = TeamServer(c, store, host=HOST, port=p, runner=lambda s, g: A.aggregate(s, g), inbox=False,
                          maintenance=False)
        try:
            srv = cand.bind()
            break
        except OSError:
            cand.close()
    if srv is None:
        raise RuntimeError("시험 포트(19400~19449)를 하나도 묶지 못했습니다")
    srv.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.close()
