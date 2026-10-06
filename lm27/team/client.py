# -*- coding: utf-8 -*-
r"""팀 서버 클라이언트 — 신원 확인·보낼 곳 고르기·HTTP·레지스트리 받기(TAB §1.5 · §2.9 · §3.5 · §3.10 · §5.3,
계약 §2.15 · §4.7 · §6.1 · §6.7 P-TEAM · L-21 · CR-13).

    h = hello(base, timeout)                       # cli `team ping` — result ∈ ok·other_lm·lm24·other_app·http_error·
                                                   #   wrong_major·proxy·timeout·refused·dns (판정표 = schema.judge_hello)
    tgt, h, pick = pick_target(cfg)               # 기본 주소 → team.serverAlternates 차례 — LM27-team 이고 v1 을 받는 첫 곳
    r = fetch_registry(base, etag)                # GET /api/registry(If-None-Match) — 파일을 쓰지 않는다(HTTP 만)
    refresh_registry(paths, cfg, force=True)      # 받아서 캐시 data\team\registry.json·registry.etag 원자 교체(O-14 ②)
    load_effective(paths, cfg, fetch=registry_fetcher(paths, cfg))   # 분류 레지스트리 적재 주입(H §3.1 — 200 이면 캐시 교체)

- **기본 주소는 이 파일의 ``DEFAULT_TEAM_URL`` 한 곳**(L-21 · CR-13 — 설정 ``team.serverHost``·``serverPort`` 기본값과
  바이트 일치). 클라이언트는 설정을 바꾸지 않는다(대체 주소는 ``team.serverAlternates`` 를 차례로 묻기만 한다).
- 시스템 프록시를 쓰지 않는다(``ProxyHandler({})`` — ``team.useSystemProxy=true`` 일 때만 기본 opener). ``team.allowPublicHost``
  가 false 면 사설 IPv4(10/8·172.16/12·192.168/16)·루프백 주소만, 호스트 이름은 쓰지 않는다(TAB §7.1).
- 이전 판(LM24)·다른 앱 판정을 위해 읽은 ``/api/whoami``·``/api/team`` 응답은 **모양만 보고 버린다**(경로·토큰이 들어 있다 —
  기록·표시 금지). 결과·문구에는 주소(URL·IP)를 싣지 않고 대상 이름(``primary``·``alt1``…)만 쓴다(TAB §1.5).
- 업로드 토큰(공유 비밀 — 계정 비밀번호 아님)은 설정이 아니라 ``data\keys\secrets.json``(반출 금지)에 둔다.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lm27.team import schema as S
from lm27.util import fsx

__all__ = ["DEFAULT_TEAM_URL", "Hello", "Pick", "RegistryFetch", "RegistryRefresh", "Resp", "Target", "adopt_offline",
           "base_of", "fetch_members", "fetch_registry", "hello", "host_allowed", "http_post", "pick_target", "reach",
           "refresh_registry", "registry_fetcher", "set_upload_token", "split_hostport", "targets", "token_fp",
           "token_state", "upload_token"]

DEFAULT_TEAM_URL = "http://10.115.147.68:9310"     # 사용자 지시 고정값(L-21 · CR-13) — 바꾸는 '옵션'만 둔다
_DEFAULT = urllib.parse.urlsplit(DEFAULT_TEAM_URL)
DEFAULT_HOST, DEFAULT_PORT = _DEFAULT.hostname, _DEFAULT.port
SHA_HEADER = "X-LM27-Bundle-SHA256"
CLIENT_HEADER = "X-LM27-Client"
SENT_HEADER = "X-LM27-Sent-At"
TOKEN_HEADER = "X-LM27-Upload-Token"
SECRETS_SCHEMA = "lm27.secrets/1"
REGISTRY_SCHEMA = "lm27.registry/1"
UNREACHABLE = frozenset({"timeout", "refused", "dns", "proxy"})
OTHER_SERVER = frozenset({"other_lm", "lm24", "other_app", "http_error"})
MAX_BODY = 32 * 1024 * 1024                      # 응답 본문 상한(레지스트리 2MB · members · 오류 JSON)
_PRIVATE4 = (ipaddress.IPv4Network((10 << 24, 8)), ipaddress.IPv4Network(((172 << 24) | (16 << 16), 12)),
             ipaddress.IPv4Network(((192 << 24) | (168 << 16), 16)))
_HELLO_KEEP = ("app", "proto", "version", "api", "accepts", "auth", "max_body_mb", "registry_version", "pepper_id")

TEXT_KO = {
    "ok": "LM27 팀 서버가 응답합니다",
    "other_lm": "이 주소에는 LM27 이 아닌 다른 판의 팀 서버가 응답합니다",
    "lm24": "이 주소에는 LM27 이 아니라 이전 판(LM24) 팀 서버가 응답합니다 — LM27 팀 서버의 포트를 확인해 설정에서 바꾸세요",
    "other_app": "LM27 팀 서버가 아닌 프로그램이 응답합니다",
    "http_error": "LM27 팀 서버가 아닌 프로그램이 응답합니다(HTTP {code})",
    "wrong_major": "팀 서버 판과 맞지 않습니다(묶음 v1) — LM27 판을 맞추세요",
    "proxy": "프록시가 대신 응답합니다 — 시스템 프록시를 쓰지 않게 설정했는지 확인하세요",
    "timeout": "응답이 없습니다 — 다른 망(클라우드PC·재택)이거나 방화벽이 막고 있을 수 있습니다",
    "refused": "그 주소의 PC 는 켜져 있으나 그 포트에 서버가 없습니다(팀 서버가 꺼졌거나 포트가 다름)",
    "dns": "주소 이름을 찾지 못했습니다",
}


def target_ko(name: str) -> str:
    if name == "primary":
        return "기본 주소"
    if name.startswith("alt") and name[3:].isdigit():
        return f"대체 주소 {name[3:]}"
    return name


# ───────────────────────────── 주소 ─────────────────────────────
@dataclass(frozen=True)
class Target:
    name: str                                    # primary · alt1 · alt2 …
    base: str                                    # http://host:port (화면·기록에는 싣지 않는다)


def base_of(host: str, port: int) -> str:
    h = str(host).strip()
    if ":" in h and not h.startswith("["):
        h = f"[{h}]"                             # IPv6 리터럴
    return f"http://{h}:{int(port)}"


def split_hostport(s) -> tuple[str, int | None]:
    """'host:port' · '[v6]:port' → (host, port). 형식이 아니면 ('', None)."""
    t = str(s or "").strip()
    if t.startswith("["):
        host, _, rest = t[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = t.rpartition(":")
    return (host, int(port)) if host and port.isdigit() else ("", None)


def host_allowed(host: str, allow_public: bool) -> bool:
    """TAB §7.1 — ``team.allowPublicHost`` 가 false 면 사설 IPv4·루프백만(호스트 이름 불가)."""
    h = str(host or "").strip().strip("[]")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return bool(allow_public) and bool(h)
    if allow_public or ip.is_loopback:
        return True
    return ip.version == 4 and any(ip in n for n in _PRIVATE4)


def targets(cfg) -> tuple[list[Target], list[str]]:
    """보낼 곳 후보(기본 주소 → 대체 주소 차례) + 쓰지 못한 후보 사유(주소 값 없이)."""
    allow = bool(cfg["team.allowPublicHost"])
    cand = [("primary", str(cfg["team.serverHost"] or "").strip(), cfg["team.serverPort"])]
    for i, hp in enumerate(cfg["team.serverAlternates"] or (), start=1):
        h, p = split_hostport(hp)
        cand.append((f"alt{i}", h, p))
    out, notes = [], []
    for name, h, p in cand:
        if not h or not isinstance(p, int) or isinstance(p, bool) or not 1 <= p <= 65535:
            notes.append(f"{target_ko(name)}: 주소 형식이 아닙니다(host:port)")
        elif not host_allowed(h, allow):
            notes.append(f"{target_ko(name)}: 사설 IPv4·루프백 주소만 쓸 수 있습니다(공개 주소 허용 설정이 꺼짐)")
        else:
            out.append(Target(name, base_of(h, p)))
    return out, notes


# ───────────────────────────── HTTP ─────────────────────────────
@dataclass
class Resp:
    """HTTP 결과 한 건. status None = 연결 실패(error = timeout·refused·dns) 또는 HTTP 가 아닌 응답(error None)."""
    status: int | None
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    error: str | None = None
    ms: int = 0

    @property
    def obj(self):
        return _json_obj(self.body)

    @property
    def via_proxy(self) -> bool:
        return any(k.lower() == "via" or k.lower().startswith("proxy-") for k in self.headers)


def _json_obj(raw):
    if not raw:
        return None
    try:
        obj = fsx.loads_strict(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _err_kind(x) -> str:
    if isinstance(x, socket.gaierror):
        return "dns"
    if isinstance(x, TimeoutError):
        return "timeout"
    if isinstance(x, ConnectionRefusedError):
        return "refused"
    we = getattr(x, "winerror", None)
    if we == 10060:
        return "timeout"
    if we in (11001, 11002, 11003, 11004):
        return "dns"
    if isinstance(x, str) and "timed out" in x:
        return "timeout"
    return "refused"


def _opener(proxy: bool):
    if proxy:
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(method: str, url: str, *, data: bytes | None = None, headers=None, timeout: float = 4.0,
             proxy: bool = False) -> Resp:
    req = urllib.request.Request(url, data=data, headers={str(k): str(v) for k, v in (headers or {}).items()},
                                 method=method)
    t0 = time.monotonic()

    def ms() -> int:
        return int((time.monotonic() - t0) * 1000)
    try:
        with _opener(proxy).open(req, timeout=timeout) as r:
            body = r.read(MAX_BODY + 1)
            return Resp(r.status, body[:MAX_BODY], dict(r.headers.items()), None, ms())
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BODY)
        except (OSError, http.client.HTTPException):
            body = b""
        hdrs = dict(e.headers.items()) if e.headers is not None else {}
        return Resp(e.code, body, hdrs, None, ms())
    except urllib.error.URLError as e:
        return Resp(None, error=_err_kind(e.reason), ms=ms())
    except http.client.HTTPException:
        return Resp(None, error=None, ms=ms())             # 무엇인가 답했지만 HTTP 가 아니다 → other_app
    except OSError as e:
        return Resp(None, error=_err_kind(e), ms=ms())


def http_post(url: str, data: bytes, headers, timeout: float, *, proxy: bool = False) -> Resp:
    """POST 본문 그대로(TAB §2.9 — 보내는 시점 정보는 헤더로만, 본문은 고치지 않는다)."""
    return _request("POST", url, data=data, headers=headers, timeout=timeout, proxy=proxy)


# ───────────────────────────── hello(신원) ─────────────────────────────
@dataclass
class Hello:
    """``/api/hello`` 판정(TAB §2.9 · 계약 §6.1 매핑). info = 응답의 허용 목록 필드(경로·pid·토큰·호스트명 없음)."""
    result: str
    ms: int = 0
    status: int | None = None
    reason: str | None = None                    # R-TEAM-*(ok 면 None)
    text_ko: str = ""
    info: dict = field(default_factory=dict)
    target: str = "primary"

    @property
    def ok(self) -> bool:
        return self.result == "ok"

    @property
    def auth_upload(self) -> bool:
        return bool((self.info.get("auth") or {}).get("upload")) if isinstance(self.info.get("auth"), dict) else False

    @property
    def auth_read(self) -> bool:
        return bool((self.info.get("auth") or {}).get("read")) if isinstance(self.info.get("auth"), dict) else False

    @property
    def accepts_v1(self) -> bool:
        acc = self.info.get("accepts")
        tb = acc.get("team_bundle") if isinstance(acc, dict) else None
        return isinstance(tb, dict) and str(S.SCHEMA_MAJOR) in tb


def _text(result: str, status) -> str:
    return TEXT_KO.get(result, TEXT_KO["other_app"]).format(code=status if status is not None else "-")


def hello(base: str, timeout, *, proxy: bool = False, target: str = "primary") -> Hello:
    """그 주소의 신원(TAB §2.9 판정표 — ``schema.judge_hello``). 404 면 이전 판(LM24) 모양을 확인하려고
    ``/api/whoami``·``/api/team`` 을 한 번씩 보고 **모양만** 판정에 쓴 뒤 버린다."""
    b = str(base).rstrip("/")
    r = _request("GET", b + "/api/hello", timeout=float(timeout), proxy=proxy)
    whoami = team = None
    if r.status == 404:
        w = _request("GET", b + "/api/whoami", timeout=float(timeout), proxy=proxy)
        whoami = w.obj if w.status == 200 else None
        if not (isinstance(whoami, dict) and "root" in whoami):
            t = _request("GET", b + "/api/team", timeout=float(timeout), proxy=proxy)
            team = t.obj if t.status == 200 else None
    body = r.obj
    result = S.judge_hello(r.status, body, whoami=whoami, team=team, proxy=r.via_proxy, error=r.error)
    whoami = team = None                                      # 이전 판 응답(경로·토큰)은 남기지 않는다
    info = {}
    if result in ("ok", "wrong_major") and isinstance(body, dict):
        info = {k: body[k] for k in _HELLO_KEEP if k in body}
        if isinstance(body.get("name"), str):
            info["name"] = body["name"][:40]
    return Hello(result=result, ms=r.ms, status=r.status, reason=S.HELLO_REASON.get(result), text_ko=_text(result, r.status),
                 info=info, target=target)


@dataclass
class Pick:
    """보낼 곳 고르기 결과 — 대상마다 hello 판정(주소 없이 이름만)."""
    hellos: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def results(self) -> list:
        return [(h.target, h.result) for h in self.hellos]

    @property
    def all_unreachable(self) -> bool:
        """모든 대상이 연결 실패(망·방화벽·꺼짐) — 묶음은 대기하고 다음 계기에 다시(TAB §2.9)."""
        return bool(self.hellos) and all(h.result in UNREACHABLE for h in self.hellos)

    @property
    def version_mismatch(self) -> bool:
        return any(h.result == "wrong_major" for h in self.hellos)

    @property
    def other_server(self) -> bool:
        return any(h.result in OTHER_SERVER for h in self.hellos)

    def describe_ko(self) -> str:
        parts = [f"{target_ko(h.target)}: {h.text_ko}" for h in self.hellos]
        parts += self.notes
        return "; ".join(parts) if parts else "팀 서버 주소가 설정되어 있지 않습니다 — 설정 > 팀 서버에서 주소를 넣으세요"

    @property
    def reasons(self) -> list:
        return sorted({h.reason for h in self.hellos if h.reason})


def pick_target(cfg, *, hello_fn=None) -> tuple[Target | None, Hello | None, Pick]:
    """TAB §2.9 ``pick_target`` — 기본 주소, 아니면 대체 주소를 차례로. hello 가 LM27-team 이고 묶음 v1 을 받는 첫 주소.
    설정 값은 바꾸지 않는다(기본 주소 고정 — 사용자 지시)."""
    ts, notes = targets(cfg)
    fn = hello_fn or hello
    pick = Pick(notes=notes)
    for t in ts:
        h = fn(t.base, cfg["team.connectTimeoutSec"], proxy=bool(cfg["team.useSystemProxy"]), target=t.name)
        pick.hellos.append(h)
        if h.ok and h.accepts_v1:
            return t, h, pick
    return None, None, pick


def reach(cfg, *, hello_fn=None) -> dict:
    """능력 탐침 P-TEAM(계약 §6.7 · TAB §1.5 ``team_server_reach``) 값 — {ok, status, value{target, result, ms}, reasons}.
    URL·IP 는 싣지 않는다. 연결 실패는 history ``transport_fail``(확정 근거 아님), 다른 앱은 ``fail``."""
    tgt, h, pick = pick_target(cfg, hello_fn=hello_fn)
    if tgt is not None and h is not None:
        return {"ok": True, "status": "ok", "value": {"target": tgt.name, "result": "ok", "ms": h.ms}, "reasons": []}
    first = pick.hellos[0] if pick.hellos else None
    if first is None:
        return {"ok": False, "status": "unknown", "value": {"target": "", "result": "", "ms": 0}, "reasons": []}
    st = "transport_fail" if pick.all_unreachable else "fail"
    return {"ok": False, "status": st, "value": {"target": first.target, "result": first.result, "ms": first.ms},
            "reasons": pick.reasons}


# ───────────────────────────── 업로드 토큰(data\keys\secrets.json) ─────────────────────────────
def upload_token(paths) -> str | None:
    r"""업로드 토큰(팀 앱 공유 비밀) — ``data\keys\secrets.json`` ``{schema, team{upload_token}}``. 없으면 None."""
    obj = fsx.read_json(paths.secrets(), None, want=dict) or {}
    team = obj.get("team") if isinstance(obj.get("team"), dict) else {}
    tok = team.get("upload_token")
    return tok.strip() if isinstance(tok, str) and tok.strip() else None


def set_upload_token(paths, token: str | None) -> bool:
    """업로드 토큰 저장·지우기(화면 [변경] — 값은 응답·화면에 다시 보이지 않는다). 바뀌었으면 True."""
    obj = fsx.read_json(paths.secrets(), None, want=dict) or {}
    team = dict(obj.get("team") or {}) if isinstance(obj.get("team"), dict) else {}
    tok = str(token).strip() if token is not None else ""
    if (team.get("upload_token") or "") == tok:
        return False
    if tok:
        team["upload_token"] = tok
    else:
        team.pop("upload_token", None)
    new = {k: v for k, v in obj.items() if k not in ("schema", "team")}
    new["schema"] = SECRETS_SCHEMA
    new["team"] = team
    fsx.atomic_write(paths.secrets(), fsx.canon_bytes(new))
    return True


def token_state(paths) -> str:
    """화면 표시용(값 없이) — '설정됨' · '없음'."""
    return "설정됨" if upload_token(paths) else "없음"


def token_fp(token: str | None) -> str:
    """토큰이 바뀌었는지만 아는 지문(대기열 meta 의 자동 재개 판단 — 토큰 값은 저장하지 않는다)."""
    return hashlib.sha256(("lm27.tokenfp|" + token).encode("utf-8")).hexdigest()[:8] if token else ""


def _token_headers(token: str | None) -> dict:
    return {TOKEN_HEADER: token} if token else {}


# ───────────────────────────── 레지스트리·구성원 ─────────────────────────────
@dataclass
class RegistryFetch:
    """GET /api/registry 결과 — status 200(새 판, obj) · 304(캐시 최신) · 그 밖 HTTP 코드 · None(연결 실패)."""
    status: int | None
    obj: dict | None = field(default=None, repr=False)
    etag: str | None = None
    error: str | None = None
    ms: int = 0


def _reg_timeout(cfg):
    if cfg is not None:
        return float(cfg["team.registryTimeoutSec"])
    from lm27.config import registry_meta
    return float(registry_meta("team.registryTimeoutSec").default)


def fetch_registry(base: str, etag: str | None, *, timeout=None, token: str | None = None, proxy: bool = False,
                   cfg=None) -> RegistryFetch:
    """팀 레지스트리 받기(TAB §3.10) — HTTP 만(파일을 쓰지 않는다). etag 가 None 이면 강제(If-None-Match 없음).
    저장까지 하는 상위 함수는 ``refresh_registry``(계약 O-14 ② — 이 모듈의 결정)."""
    hdr = {"Accept": "application/json"}
    if etag:
        hdr["If-None-Match"] = etag
    hdr.update(_token_headers(token))
    t = float(timeout) if timeout is not None else _reg_timeout(cfg)
    r = _request("GET", str(base).rstrip("/") + "/api/registry", headers=hdr, timeout=t, proxy=proxy)
    et = r.headers.get("ETag") or r.headers.get("Etag")
    obj = r.obj if r.status == 200 else None
    return RegistryFetch(r.status, obj, et, r.error, r.ms)


def fetch_members(base: str, *, timeout: float = 15.0, token: str | None = None, proxy: bool = False) -> Resp:
    """GET /api/members(TAB §3.11) — 오프라인으로 내보낸 항목의 '전달 확인'(sha12 대조)에 쓴다."""
    return _request("GET", str(base).rstrip("/") + "/api/members", headers=_token_headers(token), timeout=timeout,
                    proxy=proxy)


def _registry_ok(obj) -> bool:
    """운반 형식(schema·정수 version·pepper 64hex 또는 없음) + 분류 명세 client 검증(H §2.4 — 파일 단위 거부 없음)."""
    if not isinstance(obj, dict) or obj.get("schema") != REGISTRY_SCHEMA:
        return False
    v = obj.get("version")
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        return False
    pep = obj.get("pepper")
    if pep is not None and not (isinstance(pep, str) and len(pep) == 64 and all(c in "0123456789abcdef" for c in pep)):
        return False
    from lm27.hier.registry_schema import blocking, validate_registry
    return not blocking(validate_registry(obj, "client"))


def _cache_version(paths) -> int | None:
    obj = fsx.read_json(paths.registry_cache(), None, want=dict)
    v = obj.get("version") if isinstance(obj, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _read_etag(paths) -> str | None:
    try:
        raw = fsx.read_bytes(paths.registry_etag())
    except OSError:
        return None
    t = raw.decode("utf-8", "replace").strip()
    return t[:64] or None


def _save_cache(paths, obj: dict, etag: str | None) -> None:
    r"""캐시 원자 교체 — ``data\team\registry.json``(pepper 포함 — 반출 금지) + ``registry.etag``."""
    fsx.atomic_write(paths.registry_cache(), fsx.canon_bytes(obj))
    fsx.atomic_write(paths.registry_etag(), (etag or f'"{obj.get("version")}"').encode("utf-8"))


def adopt_offline(paths, cfg) -> bool:
    r"""TAB §5.3 — 서버에 닿지 않을 때 ``team.offlineDir\lm27_registry.json`` 의 판이 캐시보다 크고 검증을 통과하면 캐시로
    채택한다(분류 적재기 ``RegistryStatus.adopt_offline`` 의 짝 — WP-21 요청)."""
    from lm27.team.offline import read_offline_registry
    off = read_offline_registry(cfg)
    if off is None or not _registry_ok(off):
        return False
    cv = _cache_version(paths)
    if cv is not None and off["version"] <= cv:
        return False
    _save_cache(paths, off, f'"{off["version"]}"')
    return True


@dataclass
class RegistryRefresh:
    """``refresh_registry`` 결과 — rc 0 받아 저장 · 4 이미 최신(304·주기 안) · 2 받지 못함(캐시·사본 사용)."""
    rc: int
    status: int | None = None
    version: int | None = None
    source: str = "none"                         # server · cache · offline · none
    saved: bool = False
    message: str = ""


def _cache_age_h(paths, now) -> float | None:
    try:
        st = os.stat(fsx.longp(paths.registry_cache()))
    except OSError:
        return None
    n = now or datetime.now(UTC)
    return max(0.0, (n.timestamp() - st.st_mtime) / 3600.0)


def refresh_registry(paths, cfg, *, force: bool = False, now=None, hello_fn=None) -> RegistryRefresh:
    r"""레지스트리 받아 캐시 교체(TAB §3.10 — 분석 전·``team.registryRefreshH`` 마다·[지금 받기]). 계약 O-14 ② 결정:
    저장 주체는 이 함수(``fetch_registry`` 는 HTTP 만). force = 주기·ETag 무시(cli ``team registry-fetch``)."""
    ver = _cache_version(paths)
    if not force and ver is not None:
        age = _cache_age_h(paths, now)
        if age is not None and age < float(cfg["team.registryRefreshH"]):
            return RegistryRefresh(4, None, ver, "cache", False, "레지스트리를 최근에 받았습니다")
    tgt, h, pick = pick_target(cfg, hello_fn=hello_fn)
    if tgt is None:
        if adopt_offline(paths, cfg):
            v = _cache_version(paths)
            return RegistryRefresh(0, None, v, "offline", True, f"공유폴더의 레지스트리 v{v} 를 받았습니다")
        return RegistryRefresh(2, None, ver, "cache" if ver is not None else "none", False,
                               "팀 서버에 닿지 않아 레지스트리를 받지 못했습니다 — " + pick.describe_ko())
    token = upload_token(paths) if h.auth_read else None
    r = fetch_registry(tgt.base, None if force else _read_etag(paths), timeout=cfg["team.registryTimeoutSec"],
                       token=token, proxy=bool(cfg["team.useSystemProxy"]))
    if r.status == 200:
        if r.obj is None or not _registry_ok(r.obj):
            return RegistryRefresh(2, 200, ver, "cache" if ver is not None else "none", False,
                                   "서버 레지스트리가 형식 검사를 통과하지 못해 캐시를 그대로 둡니다")
        _save_cache(paths, r.obj, r.etag)
        return RegistryRefresh(0, 200, r.obj["version"], "server", True, f"레지스트리 v{r.obj['version']} 를 받았습니다")
    if r.status == 304:
        try:
            os.utime(fsx.longp(paths.registry_cache()))
        except OSError:
            pass
        return RegistryRefresh(4, 304, ver, "cache", False, "레지스트리가 이미 최신입니다")
    if r.status == 401:
        return RegistryRefresh(2, 401, ver, "cache" if ver is not None else "none", False,
                               "팀 서버가 읽기 토큰을 요구합니다 — 설정 > 팀 서버 > 토큰")
    return RegistryRefresh(2, r.status, ver, "cache" if ver is not None else "none", False,
                           f"레지스트리를 받지 못했습니다(HTTP {r.status if r.status is not None else r.error})")


def registry_fetcher(paths, cfg, *, hello_fn=None):
    r"""``lm27.hier.registry.load_effective(fetch=…)`` 주입용(H §3.1 · WP-21 요청): ``fetch(timeout_s) -> (status, obj)``.
    200 이고 형식이 맞으면 캐시를 원자 교체한 뒤 돌려준다. 서버에 닿지 않으면 공유폴더 사본이 캐시보다 새것일 때 캐시로
    채택하고(TAB §5.3 — 적재기는 사본을 캐시에 쓰지 않는다) OSError(적재기가 경고로 받고 캐시를 읽는다)."""
    def fetch(timeout_s=None):
        tgt, h, pick = pick_target(cfg, hello_fn=hello_fn)
        if tgt is None:
            adopt_offline(paths, cfg)
            raise OSError("팀 서버에 닿지 않습니다: " + ", ".join(r for _t, r in pick.results))
        token = upload_token(paths) if h.auth_read else None
        r = fetch_registry(tgt.base, _read_etag(paths), timeout=timeout_s if timeout_s else cfg["team.registryTimeoutSec"],
                           token=token, proxy=bool(cfg["team.useSystemProxy"]))
        if r.status is None:
            raise OSError("팀 서버 레지스트리 받기 실패: " + str(r.error))
        if r.status == 200 and r.obj is not None and _registry_ok(r.obj):
            _save_cache(paths, r.obj, r.etag)
            return 200, r.obj
        return r.status, None
    return fetch
