# -*- coding: utf-8 -*-
r"""WP-27 시험 도우미 — 시험용 팀 서버(같은 프로세스·백그라운드 스레드)·HTTP 호출·흉내 서버·가짜 정제 모듈.

    with running_server(tmp, **cfg_over) as ts:        # ts.url · ts.store · ts.app · ts.call(method, path, body, headers)
        code, obj, hdr = ts.call("GET", "/api/hello")

포트는 시험 전용 대역(19350~19399, 바인드 시험 통과분)만 쓴다 — 별개 프로젝트·이전 판 포트·실제 팀 서버 포트를 쓰지 않는다.
"""
from __future__ import annotations

import contextlib
import json
import sys
import threading
import types
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.fixtures.wp27 import bundles as B

TEST_PORTS = range(19350, 19400)


def free_port(skip=()) -> int:
    """시험 포트(19350~19399) 하나. 시작 위치를 프로세스·호출마다 돌린다 — 시험 파일을 여러 프로세스로 함께 돌릴 때
    모두 19350 부터 집어 같은 포트를 두고 다투던 것(바인드 실패 → 포트 진단 수십 초 → 준비 대기 초과)을 막는다."""
    import os
    import secrets
    from lm27.team.portdiag import bind_test
    ports = list(TEST_PORTS)
    k = (os.getpid() * 7 + secrets.randbelow(len(ports))) % len(ports)
    for p in ports[k:] + ports[:k]:
        if p not in skip and bind_test(p):
            return p
    raise RuntimeError("시험 포트(19350~19399)가 모두 쓰이고 있습니다")


def http(method: str, url: str, body: bytes | None = None, headers=None, timeout: float = 30):
    """(HTTP 코드, JSON|bytes, 응답 헤더). 프록시를 타지 않는다."""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with op.open(req, timeout=timeout) as r:
            raw, code, hdr = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, code, hdr = e.read(), e.code, e.headers
    try:
        obj = json.loads(raw.decode("utf-8")) if raw else None
    except ValueError:
        obj = raw
    return code, obj, hdr


class TS:
    def __init__(self, srv):
        self.srv = srv
        self.store = srv.store
        self.app = srv.app
        self.url = srv.url
        self.port = srv.port

    def call(self, method, path, body=None, headers=None, timeout=30):
        return http(method, self.url + path, body, headers, timeout)

    def post_bundle(self, obj_or_raw, *, headers=None, sha=None):
        raw = obj_or_raw if isinstance(obj_or_raw, bytes) else B.canon(obj_or_raw)
        h = {"Content-Type": "application/json", "X-LM27-Bundle-SHA256": sha if sha is not None else B.sha(raw)}
        h.update(headers or {})
        return self.call("POST", "/api/bundles", raw, h)


@contextlib.contextmanager
def running_server(root, *, payload_check=None, runner=None, firewall_run=None, inbox=False, **over):
    """임시 저장소 + 시험 포트로 팀 서버를 백그라운드에서 띄운다(재취합 = 같은 프로세스 aggregate, 대기 0초)."""
    from lm27.team import aggregate as A
    from lm27.team.server import TeamServer
    over.setdefault("teamServer.aggregateDebounceSec", 0)
    store = B.new_store(root, **over)
    if payload_check is not None:
        store.payload_check = payload_check
    srv = TeamServer(store.cfg, store, host="127.0.0.1", port=free_port(),
                     runner=runner or (lambda s, g: A.aggregate(s, g)), firewall_run=firewall_run,
                     inbox=inbox, maintenance=False).bind().start()
    try:
        yield TS(srv)
    finally:
        srv.shutdown()
        srv.close()


# ── 흉내 서버(이전 판·다른 앱) ────────────────────────────────────────────
def _fake_handler(routes):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            code, obj = routes.get(self.path, (404, {"error": "not found"}))
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_GET
    return H


@contextlib.contextmanager
def fake_server(routes, port=None):
    """routes = {경로: (코드, JSON)} — 이전 판(LM24 모양)·다른 LM 판·다른 앱 흉내. 시험 전용(배타 바인드 아님)."""
    p = port or free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", p), _fake_handler(routes))
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    t.start()
    try:
        yield p
    finally:
        httpd.shutdown()
        httpd.server_close()


LM24_ROUTES = {"/api/whoami": (200, {"root": "X", "store": "Y", "pid": 1, "token": "Z"})}
LM24_TEAM_ROUTES = {"/api/team": (200, {"ok": True, "members": [], "uploads": 0, "agg_note": ""})}


# ── 가짜 정제 모듈(WP-11 lm27.privacy 대역 — 통합 창에서 실물로 다시 돈다) ─────────────────────
@contextlib.contextmanager
def fake_privacy(bad_words=("BAD",)):
    """``lm27.privacy`` 를 잠시 가짜로: check_team_label·forbidden_codes 는 bad_words 포함 시 위반,
    make_gate_context·check_team_payload 도 둔다. 끝나면 원래 모듈(있으면)을 돌려놓는다."""
    saved = sys.modules.get("lm27.privacy")
    m = types.ModuleType("lm27.privacy")
    calls = {"payload": 0}

    def check_team_label(s, gctx, max_len=40):
        return ["not_clean"] if any(w in s for w in bad_words) else []

    def forbidden_codes(s, gctx):
        return ["forbidden:email"] if "@" in s else []

    def make_gate_context(sctx, cfg, kr, *, stage, audit, web_grounding=False):
        return types.SimpleNamespace(stage=stage)

    def check_team_payload(payload, gctx, spec):
        calls["payload"] += 1
        assert spec is not None
        out = []
        lab = (payload.get("person") or {}).get("self_label") or ""
        if any(w in lab for w in bad_words):
            out.append(types.SimpleNamespace(path="person.self_label", code="label:not_clean"))
        return out
    m.check_team_label, m.forbidden_codes = check_team_label, forbidden_codes
    m.make_gate_context, m.check_team_payload = make_gate_context, check_team_payload
    m.calls = calls
    import lm27
    had_attr = hasattr(lm27, "privacy")
    saved_attr = getattr(lm27, "privacy", None)
    sys.modules["lm27.privacy"] = m
    lm27.privacy = m                                  # `from lm27 import privacy` 는 부모 속성을 먼저 본다
    try:
        yield m
    finally:
        if saved is None:
            sys.modules.pop("lm27.privacy", None)
        else:
            sys.modules["lm27.privacy"] = saved
        if had_attr:
            lm27.privacy = saved_attr
        else:
            del lm27.privacy
