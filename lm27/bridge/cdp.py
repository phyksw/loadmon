# -*- coding: utf-8 -*-
r"""CDP 연결 층(B §4.3·§4.4, LM24 ``copilot_auto.py`` 240-374 이식) — 표준 라이브러리 WebSocket(RFC 6455)·CDP 호출·``/json`` HTTP.

  · 접속 대상은 ``127.0.0.1``(또는 localhost) 디버그 포트뿐이다. 다른 호스트는 거부한다(계약 §9.1).
  · WebSocket 핸드셰이크에 ``Origin`` 을 **보내지 않는 것이 기본**이다. ``403`` 이면 ``HandshakeRejected(status=403)`` —
    세션이 ``origin_mode="explicit"`` 로 Edge 를 다시 띄우고 ``Origin: http://127.0.0.1:<port>`` 만 넣는다(B §4.4).
  · 호출마다 시간 한도, 소켓 ``settimeout(min(남은 시간, 30))``, 시간 초과가 나면 그 연결은 재사용하지 않는다(``broken``)
    → ``reconnect()``. 이벤트 메시지(id 없음)는 버린다. 수신 프레임 길이 상한 64MB(넘으면 연결 폐기).
  · ``Runtime.evaluate`` 는 ``returnByValue=True``, JS 예외는 ``CdpError("JS: …")``(200자, 페이지 원문 없음).
  · 부를 수 있는 CDP 메서드는 허용 목록(``ALLOWED_METHODS``)뿐이다 — 쿠키·저장소 같은 도메인은 부르지 않는다(B §4.1).
    창 상태(``Browser.getWindowForTarget``·``Browser.setWindowBounds``)는 화면 [분석용 Edge 창 앞으로]가 전용 창을 되살려
    앞으로 가져올 때만 쓴다(창 안 내용은 읽지도 바꾸지도 않는다).

시험은 ``Http``·``Connector`` 자리에 ``tests\bridge\fake_http.py``·``fake_cdp.py`` 를 끼운다.
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import struct
import urllib.error
import urllib.request
from typing import Protocol
from urllib.parse import urlsplit

from lm27.bridge import settings as S

LOCAL_HOSTS = ("127.0.0.1", "localhost")
ALLOWED_METHODS = ("Runtime.evaluate", "Input.insertText", "Input.dispatchKeyEvent", "Page.bringToFront",
                   "Page.reload", "Page.navigate", "Browser.close", "Browser.getVersion", "Browser.getWindowForTarget",
                   "Browser.setWindowBounds")
_WS_RX = re.compile(r"^ws://(127\.0\.0\.1|localhost):(\d{1,5})(/[A-Za-z0-9/_.\-]*)$")


class CdpError(RuntimeError):
    """CDP 호출 오류·JS 예외(문구 200자, 페이지 원문 없음)."""


class CdpTimeout(TimeoutError):
    """CDP 호출 시간 초과 — 그 연결은 다시 쓰지 않는다(reconnect 필요)."""


class HandshakeRejected(ConnectionError):
    """WebSocket 핸드셰이크 거절(예: 403 = Origin 검사)."""

    def __init__(self, status: int):
        super().__init__(f"ws handshake rejected: {status}")
        self.status = status


# ───────────────────────── /json HTTP ─────────────────────────
class Http(Protocol):
    def json(self, port: int, path: str, method: str = "GET"): ...


class UrllibHttp:
    """``http://127.0.0.1:<port>/json…`` 조회(시스템 프록시 미사용)."""

    def __init__(self, timeout: float = S.HTTP_TIMEOUT_S):
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def json(self, port: int, path: str, method: str = "GET"):
        if not isinstance(port, int) or not 1 <= port <= 65535 or not str(path).startswith("/json"):
            raise ValueError("cdp.http: 디버그 포트의 /json 경로만 조회합니다")
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
        with self._opener.open(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))


HTTP_ERRORS = (OSError, ValueError, urllib.error.URLError)


def version(http: Http, port: int) -> dict | None:
    """``/json/version`` — 디버그 포트가 CDP 로 응답하면 dict, 아니면 None."""
    try:
        v = http.json(port, "/json/version")
    except HTTP_ERRORS:
        return None
    return v if isinstance(v, dict) and isinstance(v.get("webSocketDebuggerUrl"), str) else None


def debugger_alive(http: Http, port: int) -> bool:
    return version(http, port) is not None


def browser_id(ws_url: str) -> str:
    """``ws://…/devtools/browser/<uuid>`` 의 끝 UUID(B §4.2 SessionInfo.browser_id)."""
    return str(ws_url or "").rstrip("/").rsplit("/", 1)[-1]


def can_bind(port: int) -> bool:
    """127.0.0.1:port 에 묶을 수 있는가(다른 프로그램 점유 확인). 재사용 옵션 없이 묶었다 바로 닫는다."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def read_devtools_active_port(profile_dir) -> tuple[int, str] | None:
    """크로미움이 ``--remote-debugging-port`` 로 뜰 때 프로필 폴더에 쓰는 2줄 파일(포트, ``/devtools/browser/<uuid>``)."""
    from lm27.bridge.fsio import read_text
    txt = read_text(os.path.join(os.fspath(profile_dir), "DevToolsActivePort"))
    if not txt:
        return None
    lines = [x.strip() for x in txt.splitlines() if x.strip()]
    if len(lines) < 2 or not lines[0].isdigit() or not lines[1].startswith("/devtools/browser/"):
        return None
    return int(lines[0]), lines[1]


# ───────────────────────── WebSocket(RFC 6455 클라이언트) ─────────────────────────
def _mask(payload: bytes, key: bytes) -> bytes:
    if not payload:
        return b""
    n = len(payload)
    k = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")


class WS:
    """최소 WebSocket 클라이언트(LM24 ``WS`` 이식 + 선택 Origin·프레임 상한)."""

    def __init__(self, url: str, *, origin: str | None = None, timeout: float = S.CDP_SOCKET_CAP_S):
        m = _WS_RX.match(str(url or ""))
        if not m:
            raise ValueError("ws: 127.0.0.1 디버그 주소만 연결합니다")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        try:
            self._handshake(host, port, path, origin)
        except BaseException:
            self.close()
            raise

    def _handshake(self, host, port, path, origin):
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}:{port}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        if origin:
            lines.append(f"Origin: {origin}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("ws handshake: connection closed")
            resp += chunk
            if len(resp) > S.WS_HANDSHAKE_MAX:
                raise ConnectionError("ws handshake: header too long")
        status_line = resp.split(b"\r\n", 1)[0].decode("latin-1")
        parts = status_line.split()
        status = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        if status != 101:
            raise HandshakeRejected(status)

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            if not chunk:
                raise ConnectionError("ws: connection closed")
            buf += chunk
        return bytes(buf)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        key = os.urandom(4)
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(head + key + _mask(payload, key))

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self) -> str:
        """다음 완결 텍스트 메시지 1건(조각 프레임 조립, ping 자동 응답, 길이 상한)."""
        parts, total = [], 0
        while True:
            b1, b2 = self._read_exact(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            masked, n = b2 & 0x80, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            if n > S.WS_MAX_FRAME or total + n > S.WS_MAX_FRAME:
                raise ConnectionError("ws: frame too large")
            key = self._read_exact(4) if masked else b""
            payload = self._read_exact(n) if n else b""
            if key:
                payload = _mask(payload, key)
            if opcode == 0x9:                     # ping → pong
                self._send_frame(0xA, payload[:125])
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise ConnectionError("ws: closed by server")
            if opcode in (0x0, 0x1, 0x2):
                parts.append(payload)
                total += n
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def settimeout(self, sec: float) -> None:
        self.sock.settimeout(sec)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ───────────────────────── CDP ─────────────────────────
def _check_method(method: str) -> None:
    if method not in ALLOWED_METHODS:
        raise ValueError(f"cdp: 허용하지 않는 CDP 메서드 {method}")


class CDP:
    """CDP 세션 하나(탭 또는 브라우저 대상). ``clock`` 은 브리지 시계(시간 한도 계산)."""

    def __init__(self, ws_url: str, *, clock, origin: str | None = None, ws_factory=WS):
        self.ws_url = ws_url
        self.origin = origin
        self.clock = clock
        self._ws_factory = ws_factory
        self.ws = ws_factory(ws_url, origin=origin)
        self.next_id = 0
        self.broken = False

    def call(self, method: str, params: dict | None = None, timeout: float = S.CDP_CALL_TIMEOUT_S) -> dict:
        _check_method(method)
        if self.broken:
            raise CdpTimeout(f"CDP {method}: 끊긴 연결(reconnect 필요)")
        self.next_id += 1
        mid = self.next_id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}, ensure_ascii=False))
        end = self.clock.mono() + timeout
        while True:
            remain = end - self.clock.mono()
            if remain <= 0:
                self.broken = True
                raise CdpTimeout(f"CDP {method}: {timeout:.0f}초 안에 응답 없음")
            self.ws.settimeout(max(S.CDP_SOCKET_MIN_S, min(remain, S.CDP_SOCKET_CAP_S)))
            try:
                msg = json.loads(self.ws.recv_text())
            except TimeoutError as e:
                self.broken = True                 # 프레임 중간 시간 초과 — 스트림 동기가 깨졌을 수 있다
                raise CdpTimeout(f"CDP {method}: 응답 없음(연결 재수립 필요)") from e
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("id") != mid:
                continue                           # 이벤트 메시지·다른 id 는 버린다
            if "error" in msg:
                err = msg.get("error") or {}
                text = str(err.get("message", "") if isinstance(err, dict) else err)[:S.JS_ERROR_MAX]
                raise CdpError(f"CDP {method}: {text}")
            return msg.get("result") or {}

    def eval(self, expr: str, timeout: float = S.CDP_CALL_TIMEOUT_S):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": False},
                      timeout=timeout)
        res = r.get("result") or {}
        if res.get("subtype") == "error" or "exceptionDetails" in r:
            desc = str(res.get("description") or res.get("className") or "error").splitlines()[0]
            raise CdpError("JS: " + desc[:S.JS_ERROR_MAX])
        return res.get("value")

    def reconnect(self) -> None:
        """시간 초과 뒤 새 소켓으로 다시 연결(같은 Origin)."""
        self.close()
        self.ws = self._ws_factory(self.ws_url, origin=self.origin)
        self.broken = False

    def close(self) -> None:
        try:
            self.ws.close()
        except OSError:
            pass


class Connector(Protocol):
    def connect(self, ws_url: str, *, origin: str | None = None): ...


class WsConnector:
    """실제 연결자: ``connect(ws_url, origin=…) -> CDP``."""

    def __init__(self, clock):
        self.clock = clock

    def connect(self, ws_url: str, *, origin: str | None = None) -> CDP:
        return CDP(ws_url, clock=self.clock, origin=origin)


def local_ws_url(u: str) -> bool:
    """디버그 WebSocket 주소가 127.0.0.1(또는 localhost)인가."""
    try:
        return urlsplit(str(u)).hostname in LOCAL_HOSTS and str(u).startswith("ws://")
    except ValueError:
        return False
