# -*- coding: utf-8 -*-
"""WP-23 CDP 연결 층(B §4.4) — 127.0.0.1 의 작은 WebSocket 시험 서버(스레드)로 실제 프레임을 주고받는다.

Origin 기본 미전송 · 403 거절 · 이벤트 메시지 버림 · ping 응답 · JS 예외 · 시간 초과 뒤 재사용 금지 · 프레임 상한 ·
허용 메서드 목록 · 127.0.0.1 외 주소 거부 · /json 경로만 · DevToolsActivePort 읽기 · 포트 점유 확인.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import tempfile
import threading
import time
import unittest

from lm27.bridge import cdp as C
from lm27.bridge.clock import RealClock

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def _send_frame(conn, opcode, payload, *, fake_len=None):
    n = len(payload) if fake_len is None else fake_len
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack(">H", n)
    else:
        head += bytes([127]) + struct.pack(">Q", n)
    conn.sendall(head + payload)


def _recv_frame(conn):
    b1, b2 = _recv_exact(conn, 2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", _recv_exact(conn, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", _recv_exact(conn, 8))[0]
    key = _recv_exact(conn, 4) if b2 & 0x80 else b""
    data = _recv_exact(conn, n)
    if key:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return b1 & 0x0F, data


class MiniWS:
    """연결마다 핸드셰이크 → 요청 프레임마다 behavior(msg) 가 돌려준 프레임들을 보낸다."""

    def __init__(self, behavior, *, status=101):
        self.behavior = behavior
        self.status = status
        self.headers: list[dict] = []
        self.pongs = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.stop = False
        self.t = threading.Thread(target=self.loop, daemon=True)
        self.t.start()

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/devtools/page/ABC"

    def loop(self):
        self.sock.settimeout(0.2)
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        try:
            req = b""
            while b"\r\n\r\n" not in req:
                req += conn.recv(4096)
            lines = req.decode("latin-1").split("\r\n")
            hdr = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in lines[1:] if ":" in x)}
            self.headers.append(hdr)
            if self.status != 101:
                conn.sendall(f"HTTP/1.1 {self.status} Forbidden\r\nContent-Length: 0\r\n\r\n".encode())
                return
            acc = base64.b64encode(hashlib.sha1((hdr["sec-websocket-key"] + GUID).encode()).digest()).decode()
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
            while True:
                op, data = _recv_frame(conn)
                if op == 0xA:
                    self.pongs += 1
                    continue
                if op != 0x1:
                    return
                for frame in self.behavior(json.loads(data)):
                    if frame == "ping":
                        _send_frame(conn, 0x9, b"hi")
                    elif frame == "huge":
                        _send_frame(conn, 0x1, b"", fake_len=C.S.WS_MAX_FRAME + 1)
                    elif frame == "silence":
                        pass
                    else:
                        _send_frame(conn, 0x1, json.dumps(frame).encode())
        except (OSError, ConnectionError, KeyError, ValueError):
            pass
        finally:
            conn.close()

    def close(self):
        self.stop = True
        self.sock.close()


def ok_eval(msg):
    """이벤트 1건 + 응답(값 = 식 길이)."""
    yield {"method": "Page.loadEventFired", "params": {}}
    yield {"id": msg["id"], "result": {"result": {"type": "number", "value": len(msg["params"]["expression"])}}}


class TestWebSocket(unittest.TestCase):
    def server(self, behavior=ok_eval, **kw):
        s = MiniWS(behavior, **kw)
        self.addCleanup(s.close)
        return s

    def test_eval_without_origin(self):
        s = self.server()
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        self.assertEqual(c.eval("1+1"), 3)
        self.assertNotIn("origin", s.headers[0])

    def test_explicit_origin_header(self):
        s = self.server()
        origin = f"http://127.0.0.1:{s.port}"
        c = C.CDP(s.url, clock=RealClock(), origin=origin)
        self.addCleanup(c.close)
        c.eval("x")
        self.assertEqual(s.headers[0]["origin"], origin)

    def test_403_rejected(self):
        s = self.server(status=403)
        with self.assertRaises(C.HandshakeRejected) as cm:
            C.CDP(s.url, clock=RealClock())
        self.assertEqual(cm.exception.status, 403)

    def test_ping_answered_and_events_dropped(self):
        def beh(msg):
            yield "ping"
            yield {"method": "Runtime.consoleAPICalled", "params": {}}
            yield {"id": msg["id"] + 100, "result": {}}
            yield {"id": msg["id"], "result": {"result": {"type": "string", "value": "ok"}}}
        s = self.server(beh)
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        self.assertEqual(c.eval("a"), "ok")
        end = time.monotonic() + 3.0                       # 서버 스레드가 pong 을 읽을 때까지(응답은 그보다 먼저 온다)
        while s.pongs < 1 and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(s.pongs, 1)

    def test_js_exception_and_cdp_error(self):
        def beh(msg):
            if msg["method"] == "Runtime.evaluate":
                yield {"id": msg["id"], "result": {"result": {"subtype": "error", "description": "TypeError: x\n  at y"},
                                                   "exceptionDetails": {}}}
            else:
                yield {"id": msg["id"], "error": {"message": "No target"}}
        s = self.server(beh)
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        with self.assertRaises(C.CdpError) as cm:
            c.eval("bad()")
        self.assertEqual(str(cm.exception), "JS: TypeError: x")
        with self.assertRaises(C.CdpError):
            c.call("Page.reload", {})

    def test_timeout_breaks_connection_until_reconnect(self):
        s = self.server(lambda msg: ["silence"])
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        with self.assertRaises(C.CdpTimeout):
            c.call("Page.bringToFront", {}, timeout=0.6)
        self.assertTrue(c.broken)
        with self.assertRaises(C.CdpTimeout):
            c.call("Page.bringToFront", {}, timeout=0.6)
        c.reconnect()
        self.assertFalse(c.broken)
        self.assertEqual(len(s.headers), 2)

    def test_frame_limit(self):
        s = self.server(lambda msg: ["huge"])
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        with self.assertRaises(ConnectionError):
            c.eval("x")

    def test_method_allow_list(self):
        s = self.server()
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        for m in ("Network.getCookies", "Storage.getStorageKeyForFrame", "Target.closeTarget"):
            with self.assertRaises(ValueError):
                c.call(m, {})

    def test_non_local_ws_refused(self):
        for u in ("ws://example.com:9343/devtools/page/x", "wss://127.0.0.1:9343/devtools/page/x", "http://127.0.0.1:1/"):
            with self.assertRaises(ValueError):
                C.WS(u)
        self.assertTrue(C.local_ws_url("ws://127.0.0.1:9343/devtools/page/x"))
        self.assertFalse(C.local_ws_url("ws://example.com:9343/devtools/page/x"))

    def test_large_message_roundtrip(self):
        big = "가" * 70000
        s = self.server()
        c = C.CDP(s.url, clock=RealClock())
        self.addCleanup(c.close)
        self.assertEqual(c.eval(big), len(big))


class TestHttpHelpers(unittest.TestCase):
    def test_json_path_only(self):
        h = C.UrllibHttp()
        with self.assertRaises(ValueError):
            h.json(9343, "/devtools/x")
        with self.assertRaises(ValueError):
            h.json(0, "/json")

    def test_version_none_when_closed(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.assertIsNone(C.version(C.UrllibHttp(timeout=1.0), port))
        self.assertFalse(C.debugger_alive(C.UrllibHttp(timeout=1.0), port))

    def test_can_bind(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertFalse(C.can_bind(port))
        finally:
            s.close()
        self.assertTrue(C.can_bind(port))

    def test_devtools_active_port(self):
        d = tempfile.mkdtemp(prefix="lm27t_dap_")
        self.addCleanup(shutil.rmtree, d, True)
        self.assertIsNone(C.read_devtools_active_port(d))
        with open(os.path.join(d, "DevToolsActivePort"), "w", encoding="utf-8") as fh:
            fh.write("9344\n/devtools/browser/6b0c-11\n")
        self.assertEqual(C.read_devtools_active_port(d), (9344, "/devtools/browser/6b0c-11"))
        with open(os.path.join(d, "DevToolsActivePort"), "w", encoding="utf-8") as fh:
            fh.write("garbage")
        self.assertIsNone(C.read_devtools_active_port(d))

    def test_browser_id(self):
        self.assertEqual(C.browser_id("ws://127.0.0.1:9343/devtools/browser/6b0c-11"), "6b0c-11")


if __name__ == "__main__":
    unittest.main()
