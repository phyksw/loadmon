# -*- coding: utf-8 -*-
r"""
teamup.py — 조직장 팀 서버로 공유하기 (AgentFinder32 · spec §7 · D14). 화면 [공유] 탭이 부른다. 자동으로 보내는 길은 없다.

공유는 두 갈래이고 따로 고른다(처음에는 둘 다 꺼져 있다):
  (a) 개인 리포트 — 공유용 리포트(report_out.build(variant="share"))를 조직장에게. 조직장만 연다.
  (b) 익명 팀 집계 — 고른 Agentic AI 전환 후보의 이름·업무 유형과 기간의 끝 달만. 이름·설치 ID 를 싣지 않는다.
  두 갈래는 서로 다른 요청으로 보내고 둘을 잇는 값이 없다. 실패한 전송은 자동으로 다시 보내지 않는다.

명령(모두 마지막 줄에 JSON 한 줄 {"ok","code","msg",...} · 종료 코드 0 성공 · 1 오류 · 2 거절 · 3 서버에 닿지 않음)
  python teamup.py --status [--offline] [--verify]
      주소·조직 이름·전송 방식·닿는지·영수증(보낸 날·갈래·보관기한). --offline 은 서버에 묻지 않는다(저장한 주소와 영수증만 —
      화면 [공유] 탭을 열 때). --offline 이 없으면 hello 를 한 번 묻는다([연결 확인]·[보내기…]).
  python teamup.py --ping                  hello 만(보내지 않는다)
  python teamup.py --preview [--tag T] [--personal] [--team] [--owner 이름 --function 파트]
      → report\share\preview_<tag>.json(항목과 id) + preview_<tag>.html(공유용 리포트 — 개인 리포트를 고를 때). 화면 체크 상자용 항목.
      가린 뒤에도 이름이 남았을 수 있는 항목은 "flagged": true, "flag_terms": [...] — 익명 팀 집계에는 넣지 않는다(parts 에 team 없음).
  python teamup.py --share --ticket report\share\ticket_<nonce>.json --preview-file P [--sha256 H] [--include id ...]
                   [--personal] [--team]
      화면이 확인 창에서 [보내기]를 누른 뒤 쓴 일회용 표(ticket)가 있어야 보낸다. 표는 읽자마자 지운다(한 번만). 30분이 지난 표·
      미리보기 파일(sha256)·고른 항목·갈래와 다른 표·지금 서버의 hello(주소·server_id·조직 이름·전송 방식·서버 보관기한)와 다른 표면
      보내지 않는다. --sha256·--include·--personal·--team 은 주면 표와 같아야 하고, 주지 않으면 표의 것을 쓴다.
      참여 코드는 환경변수 AF32_JOIN(없으면 teamaddr 에 저장한 값) — 명령줄로 받지 않는다. 미리보기가 바뀌었거나 30분이 지났거나
      제한 고객 목록이 분석 뒤에 바뀌었으면 보내지 않는다. 보낼 글은 미리보기 파일에서 가져오지 않고 분석
      결과에서 다시 만들어(가리기 포함) 미리보기와 같을 때만 보낸다. 보내기 전에 data\share_receipts.json 에 영수증(서버·server_id·
      조직·갈래·id·이 PC 가 만든 토큰·보낸 날·보관기한 · "pending": true)을 먼저 쓰고, 서버가 받았다고 답하면 pending 을 뗀다 —
      답을 못 받아도 그 영수증으로 서버 사본을 지울 수 있다. 결과의 "sent" 는 서버가 받았다고 답한 갈래만이고, 받았는지 모르는
      갈래가 있으면 "unknown": true · "unsure": [갈래] 를 싣는다(서버가 거절한 것은 받지 않은 것 — 영수증도 남기지 않는다).
  python teamup.py --withdraw [--all] [--part personal|team]
      영수증마다 그 서버에 DELETE. 그 주소의 서버가 영수증의 server_id 와 같을 때만 지운다(다른 서버의 404 를 '지웠다'로 보지
      않는다). 200·404 면 영수증을 지운다. --all 이 없으면 지금 주소의 서버 것만. --part personal 이면 같은 서버의 익명 기여분 중
      '개인 리포트를 함께 보냈다'로 표시된 것도 함께 거둔다(표시가 틀린 채 남지 않게).
code ∈ ok · no_consent · no_address · not_af32 · unreachable · bad_join · token_mismatch · no_result · too_big · server_error ·
       not_internal · http_personal_refused
API(가져다 쓸 때 부작용 없음): status · ping · preview · share · withdraw · withdraw_all(root, cfg, timeout=10) ·
     retry_withdrawals(root, cfg, timeout=5) · load_receipts · resolve_target · hello_problem

망 규칙: 프록시를 쓰지 않는다(urllib.request.build_opener(ProxyHandler({}))). 서버 주소가 루프백·사내 대역(10/8 · 172.16/12 ·
192.168/16) 또는 설정 share.allowedNetworks 안으로 풀릴 때만 보낸다(not_internal). HTTP·HTTPS 모두 확인한 IP 로 바로 붙는다
(HTTPS 는 인증서·SNI 만 이름으로 — 이름을 다시 풀지 않는다). 보내기 전에 GET /af32/hello 가 product AgentFinder32 · schema
af32-share-1 · server_id · 하한(minGroupSize ≥ 5 · minCellSize ≥ 3 · serverPersonalDays ≤ 90 · serverTeamDays ≤ 180)을 말해야
한다(not_af32). hello 가 transport=http 이고 personalOverHttp=false 면 개인 리포트는 보내지 않는다(http_personal_refused).
"""
import hashlib
import html
import http.client
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(ROOT, "core"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)        # 동봉 파이썬(._pth)은 스크립트 폴더를 sys.path 에 넣지 않는다
import afcfg  # noqa: E402
import consent  # noqa: E402
import install  # noqa: E402
import lmname  # noqa: E402
import teamaddr  # noqa: E402

P = lmname.SHARE_PREFIX
JOIN_ENV = "AF32_JOIN"
RECEIPTS_FILE = consent.RECEIPTS_FILE          # data\share_receipts.json
SHARE_DIR = ("report", "share")
PREVIEW_MAX_AGE = 30 * 60                      # 미리보기를 믿는 시간(초)
TICKET_MAX_AGE = 30 * 60                       # 화면이 쓴 보내기 표(ticket)를 믿는 시간(초) — 파일 수정 시각으로
MAX_BODY = 5 * 1024 * 1024                     # 서버 상한과 같다
RESP_MAX = 1024 * 1024
RETRY_PAUSE = 1.0
TEAM_LIMITS = {"needs": 30, "name": 200, "task_type": 40}   # 서버(teamserver NEEDS_MAX·NEED_*_MAX)와 같다
FLAG_TERMS_MAX = 8
FLAG_FIELDS = ("name", "logic", "reason", "agent_how", "task_type")
TAG_RX = re.compile(r"^\d{8}-\d{8}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TICKET_NAME = re.compile(r"^ticket_[A-Za-z0-9_-]{8,128}\.json$")
RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
FLOORS = {"minGroupSize": (afcfg.TEAM_MIN["minGroupSize"], None), "minCellSize": (afcfg.TEAM_MIN["minCellSize"], None),
          "serverPersonalDays": (1, afcfg.RETENTION_MAX["serverPersonalDays"]),
          "serverTeamDays": (1, afcfg.RETENTION_MAX["serverTeamDays"])}
# 기다림 값의 범위 — 상한을 올리면 화면이 --share 를 기다리는 상한(ui\app.SHARE_WAIT_SEC)도 올린다(먼저 끊으면 영수증을 잃는다)
_WAIT_RANGE = {"pingTries": (1, 3), "pingTimeoutSec": (1.0, 10.0), "timeoutSec": (5.0, 90.0)}
CODES = ("ok", "no_consent", "no_address", "not_af32", "unreachable", "bad_join", "token_mismatch", "no_result",
         "too_big", "server_error", "not_internal", "http_personal_refused")
EXIT = {"ok": 0, "server_error": 1, "unreachable": 3}          # 그 밖의 code 는 2(거절)
PARTS = ("personal", "team")
PART_LABEL = {"personal": "개인 리포트", "team": "익명 팀 집계"}
PENDING_MSG = "조직장 서버에서 아직 지우지 못했습니다 (서버 보관기한 {date} 에 자동 삭제)"
NO_ADDRESS_MSG = (f"공유할 조직장 팀 서버가 정해지지 않았습니다 — 조직장이 알려 준 주소와 참여 코드를 "
                  f"{teamaddr.EDIT_BAT} 에서 저장하세요")
TICKET_MSG = "화면 [공유] 탭의 확인 창에서 [보내기]를 눌러야 보냅니다 — 다시 미리 보고 보내세요"
STALE_MSG = "제한 고객 목록이 분석 뒤에 바뀌었습니다 — 다시 분석한 뒤 공유하세요"
UNSURE_MSG = " — 서버가 받았는지 확인하지 못했습니다. [보낸 공유 모두 거두기]로 서버 사본을 지울 수 있습니다"
GONE_MSG = " · 앞서 보낸 익명 팀 집계 기여분 {n}건은 지웠습니다 — 다시 넣으려면 익명 팀 집계를 골라 보내세요"
MOVED_MSG = "영수증의 서버가 아닙니다 — 주소의 서버가 바뀌었습니다(지우지 않고 영수증을 남깁니다)"


class ShareError(Exception):
    """공유 명령의 실패 — code 는 CODES 중 하나, msg 는 사람에게 보일 한국어 문장."""

    def __init__(self, code, msg, **extra):
        super().__init__(msg)
        self.code = code if code in CODES else "server_error"
        self.msg = msg
        self.extra = extra

    def result(self):
        return result(self.code, self.msg, **self.extra)


def result(code="ok", msg="", **kw):
    d = {"ok": code == "ok", "code": code, "msg": msg}
    d.update(kw)
    return d


def exit_code(res):
    return EXIT.get(res.get("code"), 2)


def _today():
    return date.today()


def _cfg(cfg, root):
    if isinstance(cfg, dict):
        c, _w = afcfg.effective(cfg)
        return c
    c, _w = afcfg.load_effective(root)
    return c


def wait_limits(cfg):
    """share.pingTries·pingTimeoutSec·timeoutSec → {tries, ping, timeout} (범위 밖이면 가장자리로)."""
    def pick(key, dflt):
        lo, hi = _WAIT_RANGE[key]
        v = afcfg.get(cfg, "share." + key, dflt)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float(dflt)
        if v != v:
            v = float(dflt)
        return min(hi, max(lo, v))
    return {"tries": int(pick("pingTries", 2)), "ping": pick("pingTimeoutSec", 3), "timeout": pick("timeoutSec", 45)}


def require_consent(root, cfg):
    """내 자료이고 지우는 중이 아닌가(consent.require · D17) — 아니면 ShareError('no_consent')."""
    try:
        return consent.require(root, cfg)
    except consent.ConsentRequired as e:
        raise ShareError("no_consent", e.message) from None


def _other_user(root, cfg):
    r"""이 설치 폴더의 자료가 다른 Windows 사용자의 것이거나 주인을 알 수 없는 것인가(D17). 상태만 보는 길이라 data\install.json
    을 새로 만들지 않는다 — 그 파일이 없으면 이 설치의 자료(살아 있는 영수증 포함 — install.owned_data)가 남아 있을 때만 참이다
    (그 파일을 지워도 남의 공유 기록이 열리지 않는다). 확인하지 못하면 참(보이지 않는 쪽)."""
    root = str(root)
    try:
        if not os.path.isfile(os.path.join(root, "data", "install.json")):
            fn = getattr(install, "owned_data", None)
            return bool(fn(root)) if callable(fn) else False
        st = consent.status(root, cfg)
    except Exception:  # noqa: BLE001 - 누구 것인지 확인하지 못한 자료는 보이지 않는다
        return True
    return bool(st.get("other_user") or st.get("unknown_owner"))


# ── 망 ────────────────────────────────────────────────────────────────────────
def _nets(cfg):
    out = []
    for n in afcfg.get(cfg, "share.allowedNetworks") or []:
        try:
            out.append(ipaddress.ip_network(str(n).strip(), strict=False))
        except ValueError:
            continue
    return out


def internal_ip(ip, nets=()):
    """루프백 · 사내 대역(RFC1918) · share.allowedNetworks 안인가."""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    if a.is_loopback:
        return True
    if a.version == 4 and any(a in n for n in RFC1918):
        return True
    return any(a.version == n.version and a in n for n in nets)


class Target:
    """확인을 마친 서버 — scheme·host·port 와 붙을 IP."""

    def __init__(self, scheme, host, port, ip):
        self.scheme, self.host, self.port, self.ip = scheme, host, int(port), ip

    @property
    def url(self):
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def host_header(self):
        return f"{self.host}:{self.port}"

    def request_url(self, path):
        if self.scheme == "https":
            return f"https://{self.host}:{self.port}{path}"     # 인증서·SNI 는 이 이름 — 붙는 곳은 확인한 IP(_PinnedHTTPSConnection)
        ip = f"[{self.ip}]" if ":" in self.ip else self.ip
        return f"http://{ip}:{self.port}{path}"                  # 확인한 IP 로 바로(이름을 다시 풀지 않는다)


def resolve_target(scheme, host, port, cfg):
    """서버 이름 → Target. 모든 주소가 사내망이어야 한다(not_internal). 찾지 못하면 unreachable."""
    try:
        infos = socket.getaddrinfo(host, int(port), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise ShareError("unreachable", f"서버 주소 {host} 를 찾지 못했습니다 — 사내망에서 다시 하세요") from None
    ips = []
    for i in infos:
        ip = str(i[4][0])
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ShareError("unreachable", f"서버 주소 {host} 를 찾지 못했습니다 — 사내망에서 다시 하세요")
    nets = _nets(cfg)
    bad = [ip for ip in ips if not internal_ip(ip, nets)]
    if bad:
        raise ShareError("not_internal", (f"서버 주소 {host} 가 사내망 주소가 아니어서 보내지 않습니다({', '.join(bad[:3])}) — "
                                          "사내 IP(10.x · 172.16~31.x · 192.168.x)이거나 설정 share.allowedNetworks 의 망이어야 합니다"))
    ips.sort(key=lambda x: ":" in x)                             # IPv4 먼저
    return Target(scheme, host, port, ips[0])


def target_of_url(url, cfg):
    pu = teamaddr.parse_url(url)
    if pu is None or not pu[1]:
        raise ShareError("no_address", f"영수증의 서버 주소를 읽지 못했습니다: {str(url)[:60]}")
    return resolve_target(pu[2] or "http", pu[0], pu[1], cfg)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """다른 곳으로 넘기는 답은 따르지 않는다 — 오류로 본다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS 연결 — 이름을 다시 풀지 않고 resolve_target 이 사내망으로 확인한 IP 에 붙는다. 인증서 확인·SNI·Host 는 이름 그대로."""

    def __init__(self, host, *, pin_ip, **kw):
        super().__init__(host, **kw)
        self._pin_ip = str(pin_ip)
        self._create_connection = self._connect_pinned

    def _connect_pinned(self, address, *a, **kw):
        return socket.create_connection((self._pin_ip, address[1]), *a, **kw)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, pin_ip, context):
        super().__init__(context=context)
        self._pin_ip = pin_ip

    def https_open(self, req):
        ip = self._pin_ip
        return self.do_open(lambda host, **kw: _PinnedHTTPSConnection(host, pin_ip=ip, **kw), req, context=self._context)


def _opener(scheme, ip=None):
    hs = [urllib.request.ProxyHandler({}), _NoRedirect()]
    if scheme == "https":
        ctx = ssl.create_default_context()
        hs.append(_PinnedHTTPSHandler(ip, ctx) if ip else urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*hs)


def _parse(raw):
    try:
        d = json.loads((raw or b"").decode("utf-8", "replace"))
    except ValueError:
        return None
    return d


def _call(t, method, path, *, body=None, headers=None, timeout=5.0):
    """요청 하나 → (HTTP 상태, JSON|None). 연결 실패·시간 초과는 ShareError('unreachable')."""
    hdr = {"Host": t.host_header, "Accept": "application/json", "User-Agent": lmname.PRODUCT}
    hdr.update(headers or {})
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdr["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(t.request_url(path), data=data, method=method, headers=hdr)
    try:
        with _opener(t.scheme, t.ip).open(req, timeout=timeout) as r:
            return r.status, _parse(r.read(RESP_MAX))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read(RESP_MAX)
        except (OSError, http.client.HTTPException):
            raw = b""
        return e.code, _parse(raw)
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, ssl.SSLCertVerificationError):
            raise ShareError("unreachable", ("서버 인증서를 확인하지 못했습니다 — 조직장 서버의 인증서가 회사가 발급한 것인지, "
                                             "주소가 인증서의 이름과 같은지 조직장에게 확인하세요")) from None
        if isinstance(reason, (TimeoutError, socket.timeout)) or isinstance(e, (TimeoutError, socket.timeout)):
            raise ShareError("unreachable", f"서버가 {timeout:.0f}초 안에 답하지 않았습니다 — 사내망에서 다시 하세요") from None
        raise ShareError("unreachable", f"서버에 닿지 않았습니다({type(reason).__name__}) — 사내망에서 다시 하세요") from None


def hello_problem(h, scheme=None, *, need_id=True, minimal=False):
    """hello 응답이 AgentFinder32 팀 서버의 것이 아니거나 하한을 어기면 까닭, 아니면 None.
    need_id: server_id(32 hex)도 있어야 한다(보내기·상태). minimal: 제품·형식만 본다(철회 — 지우기는 하한과 상관없이 한다)."""
    if not isinstance(h, dict):
        return "응답이 AgentFinder32 팀 서버의 것이 아닙니다"
    if h.get("product") != lmname.PRODUCT or h.get("schema") != lmname.SHARE_SCHEMA:
        return "이 주소의 서버는 AgentFinder32 팀 서버가 아닙니다(옛 LoadMonitor 서버일 수 있습니다)"
    if minimal:
        return None
    for k, (lo, hi) in FLOORS.items():
        v = h.get(k)
        if isinstance(v, bool) or not isinstance(v, int) or v < lo or (hi is not None and v > hi):
            return f"서버 설정 {k}={v!r} 이(가) 규칙(최소 인원·보관기한)에 맞지 않아 보내지 않습니다"
    if h.get("transport") not in ("http", "https") or (scheme and h.get("transport") != scheme):
        return "서버의 전송 방식이 주소와 맞지 않습니다"
    if not isinstance(h.get("personalOverHttp"), bool):
        return "서버가 개인 리포트 전송 규칙을 말하지 않았습니다"
    if need_id and not _HEX32.match(str(h.get("server_id") or "")):
        return "서버가 자기 ID(server_id)를 말하지 않았습니다 — 조직장에게 AgentFinder32 팀 서버를 새 판으로 켜 달라고 하세요"
    return None


def hello(t, cfg, *, need_id=True, minimal=False, timeout=None, tries=None):
    """GET /af32/hello(pingTries 번까지 · tries·timeout 으로 줄일 수 있다) → 확인한 hello dict. 닿지 않으면 unreachable,
    아니면 not_af32."""
    lim = wait_limits(cfg)
    n = lim["tries"] if tries is None else max(1, int(tries))
    tmo = lim["ping"] if timeout is None else float(timeout)
    last = None
    for i in range(n):
        if i:
            time.sleep(RETRY_PAUSE)
        try:
            code, d = _call(t, "GET", P + "/hello", timeout=tmo)
            break
        except ShareError as e:
            last = e
    else:
        raise last
    if code != 200:
        raise ShareError("not_af32", f"이 주소의 서버는 AgentFinder32 팀 서버가 아닙니다(HTTP {code})")
    why = hello_problem(d, t.scheme, need_id=need_id, minimal=minimal)
    if why:
        raise ShareError("not_af32", why)
    return d


def _http_error(code, d):
    err = d.get("error") if isinstance(d, dict) else ""
    if code == 401:
        return ShareError("bad_join", f"참여 코드가 맞지 않습니다 — 조직장에게 받은 참여 코드를 {teamaddr.EDIT_BAT} 에서 다시 저장하세요")
    if code == 403 and err == "http_personal_refused":
        return ShareError("http_personal_refused", "이 서버는 암호화 없는 HTTP 로는 개인 리포트를 받지 않습니다")
    if code == 403:
        return ShareError("token_mismatch", ("이 서버에 앞서 보낸 공유의 영수증이 이 PC 에 없어 바꾸거나 지울 수 없습니다 — "
                                             "조직장에게 삭제를 요청하거나 서버 보관기한이 지난 뒤 다시 보내세요"))
    if code == 413:
        return ShareError("too_big", "보낼 내용이 서버 상한(5MB)을 넘습니다 — 항목을 줄여 다시 미리 보세요")
    if code == 404:
        return ShareError("not_af32", "이 주소의 서버가 공유를 받지 않습니다(AgentFinder32 팀 서버가 아닙니다)")
    if code == 429:
        return ShareError("server_error", "요청이 많아 서버가 잠시 막았습니다 — 1분 뒤 다시 하세요")
    if code == 400:
        return ShareError("server_error", "서버가 보낸 내용의 형식을 받지 않았습니다 — 다시 미리 본 뒤 보내세요")
    return ShareError("server_error", f"서버 오류(HTTP {code})")


# ── 영수증 ──────────────────────────────────────────────────────────────────────
def receipts_path(root=None):
    return os.path.join(str(root or ROOT), "data", RECEIPTS_FILE)


def load_receipts(root=None, *, prune=True):
    r"""data\share_receipts.json → 영수증 목록. 서버 보관기한이 지난 것은 서버에서 이미 지워졌으므로 뺀다(prune)."""
    p = receipts_path(root)
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    lst = d.get("receipts") if isinstance(d, dict) else d
    out = []
    today = _today().isoformat()
    for r in lst if isinstance(lst, list) else []:
        if not isinstance(r, dict) or r.get("part") not in PARTS or not r.get("token") or not r.get("server"):
            continue
        if prune and str(r.get("expires") or "9999") < today:
            continue
        out.append(r)
    if prune and isinstance(lst, list) and len(out) != len(lst):
        save_receipts(root, out)
    return out


def save_receipts(root, items):
    p = receipts_path(root)
    if not items:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"product": lmname.PRODUCT, "receipts": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def public_receipt(r):
    """화면·로그용 — 토큰·id·server_id 없이. pending = 서버가 받았는지 아직 모른다(거두기로 지울 수 있다)."""
    return {"server": r.get("server"), "org_label": r.get("org_label") or "", "part": r.get("part"),
            "sent": r.get("sent"), "expires": r.get("expires"), "pending": bool(r.get("pending"))}


def _same_server(r, h):
    """영수증 r 이 hello h 를 답한 서버의 것인가 — server_id 로. server_id 가 없는 옛 영수증은 조직 이름이 같을 때만."""
    sid = str(r.get("server_id") or "")
    if sid:
        return sid == str(h.get("server_id") or "")
    return bool(r.get("org_label")) and r.get("org_label") == (h.get("org_label") or "")


def _on_server(r, t, h):
    """보내기에서 '이 서버의 앞선 영수증' — server_id 가 같으면(주소 글자가 달라도). 옛 영수증은 주소·조직 이름이 같을 때만."""
    if r.get("server_id"):
        return _same_server(r, h)
    return r.get("server") == t.url and _same_server(r, h)


def _expect(h, part):
    """서버 보관기한의 예상 날짜(영수증 — 서버 답을 받기 전) — 개인 리포트 오늘+serverPersonalDays · 기여분 이달 1일+serverTeamDays."""
    today = _today()
    if part == "personal":
        return (today + timedelta(days=int(h.get("serverPersonalDays") or 0))).isoformat()
    return (today.replace(day=1) + timedelta(days=int(h.get("serverTeamDays") or 0))).isoformat()


# ── 상태·연결 확인 ──────────────────────────────────────────────────────────────
def _server_info(h):
    return {"org_label": h.get("org_label") or "", "server_id": str(h.get("server_id") or ""),
            "transport": h.get("transport"), "personalOverHttp": h.get("personalOverHttp"),
            "serverPersonalDays": h.get("serverPersonalDays"), "serverTeamDays": h.get("serverTeamDays"),
            "minGroupSize": h.get("minGroupSize"), "minCellSize": h.get("minCellSize")}


def ping(root=None, cfg=None):
    """hello 만 — 보내지 않는다."""
    root = root or ROOT
    cfg = _cfg(cfg, root)
    a = teamaddr.load(root)
    if not a.configured:
        raise ShareError("no_address", NO_ADDRESS_MSG)
    t = resolve_target(a.scheme, a.host, a.port, cfg)
    h = hello(t, cfg)
    return result("ok", f"{h.get('org_label') or '조직'} 의 팀 서버에 닿습니다({t.url} · {str(h.get('transport')).upper()})",
                  address=t.url, reachable=True, **_server_info(h))


def _withdrawal_pending(root):
    return os.path.exists(os.path.join(str(root), "data", consent.WITHDRAWAL_FILE))


def status(root=None, cfg=None, *, verify=False, offline=False):
    """주소·조직·전송 방식·닿는지·영수증. 주소가 없거나 닿지 않아도 영수증은 싣는다.
    offline=True 면 서버에 묻지 않는다(주소와 영수증만 — reachable None · checked False). 다른 사용자의 자료면 영수증 없이
    no_consent(D17)."""
    root = root or ROOT
    cfg = _cfg(cfg, root)
    if _other_user(root, cfg):
        return result("no_consent", install.OTHER_USER_MSG, address="", configured=False, join_set=False, transport="",
                      org_label="", reachable=None, checked=False, receipts=[], withdrawal_pending=False, warnings=[],
                      other_user=True)
    a = teamaddr.load(root)
    recs = load_receipts(root)
    base = {"address": a.url, "configured": a.configured, "join_set": bool(a.join), "transport": a.scheme,
            "org_label": "", "reachable": None if offline else False, "checked": not offline,
            "receipts": [public_receipt(r) for r in recs],
            "withdrawal_pending": any(_marked(r) for r in recs) and _withdrawal_pending(root), "warnings": list(a.warnings)}
    if not a.configured:
        return result("no_address", NO_ADDRESS_MSG, **base)
    if offline:
        return result("ok", "저장한 주소와 보낸 공유 기록입니다 — 조직장 서버에는 묻지 않았습니다", **base)
    try:
        t = resolve_target(a.scheme, a.host, a.port, cfg)
        h = hello(t, cfg)
    except ShareError as e:
        return result(e.code, e.msg, **base)
    base.update(_server_info(h), reachable=True)
    if verify:
        for pr, r in zip(base["receipts"], recs, strict=True):
            if not _on_server(r, t, h):
                continue
            try:
                code, d = _call(t, "GET", f"{P}/share/{r['part']}/{r['id']}", headers={"X-AF32-Token": r["token"]},
                                timeout=wait_limits(cfg)["ping"])
                pr["on_server"] = code == 200
            except ShareError:
                pr["on_server"] = None
    return result("ok", f"{h.get('org_label') or '조직'} 의 팀 서버에 닿습니다", **base)


# ── 미리보기 ────────────────────────────────────────────────────────────────────
def _share_dir(root):
    return os.path.join(str(root), *SHARE_DIR)


def _typed(v, cap=40):
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()[:cap]


def _sha_file(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _sources(root, tag):
    rep = os.path.join(str(root), "report")
    names = (f"run_meta_{tag}.json", f"agentic_{tag}.json", f"workflow_{tag}.json",
             f"work_rows_{tag}.csv", f"work_rows_{tag}_refined.csv", f"entities_{tag}.json")
    return {n: _sha_file(os.path.join(rep, n)) for n in names}


def _write_bytes(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, p)


def _scrubber(cfg, root, tag):
    import privacy
    try:
        return privacy.ShareScrubber(cfg, root=root, tag=tag)
    except privacy.RestrictedListError as e:
        raise ShareError("no_result", e.message) from None


def _restricted_stale(root, tag, restricted):
    r"""분석 결과(report\run_meta_<tag>.json 의 restricted_sha256)가 지금 제한 고객 목록으로 만든 것이 아닌가 — 값이 없거나
    다르면 참(retention.restricted_stale 이 있으면 그것을 쓴다)."""
    try:
        import retention
        fn = getattr(retention, "restricted_stale", None)
        if callable(fn):
            return bool(fn(str(root), tag, restricted))
    except Exception:  # noqa: BLE001 - 아래의 같은 규칙으로 본다
        pass
    try:
        with open(os.path.join(str(root), "report", f"run_meta_{tag}.json"), encoding="utf-8-sig") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return True
    want = str(meta.get("restricted_sha256") or "") if isinstance(meta, dict) else ""
    return not want or want != str(getattr(restricted, "sha256", "") or "")


def _refuse_stale(root, tag, sc):
    """제한 고객 목록이 분석 뒤에 바뀌었으면 보내지도 미리 보지도 않는다(그 고객의 메일로 만든 후보가 남아 있을 수 있다 — D9)."""
    if _restricted_stale(root, tag, getattr(sc, "restricted", None)):
        raise ShareError("no_result", STALE_MSG)


def _blocked(it, cfg, sc=None):
    """가린 뒤에도 민감한 낱말·식별번호·제한 고객의 이름·도메인이 남은 항목은 미리보기에 올리지 않는다(보내지 않는다).
    제한 고객은 가림 도구(sc — privacy.ShareScrubber)가 같은 맞춤 규칙으로 이미 가린다. 여기는 가림을 지나친 글을 한 번 더 막는
    자리다(privacy.restricted_hit — 가림 도구가 목록을 들고 있지 않으면 닫는다). 가림 도구 없이 부르면 목록을 모르므로 보지 않는다."""
    import privacy
    t = " ".join(str(it.get(k) or "") for k in ("name", "logic", "reason", "task_type", "agent_how"))
    if privacy.sensitive_hit(t, cfg) or privacy.has_identifier(t):
        return True
    return bool(sc is not None and privacy.restricted_hit(t, getattr(sc, "restricted", None)))


def _flag_terms(sc, it):
    """가린 뒤에도 이름(고객사·제품·사람)일 수 있는 낱말 — privacy.ShareScrubber.leftover. 없으면 []."""
    fn = getattr(sc, "leftover", None) if sc is not None else None
    if not callable(fn):
        return []
    import report_out
    out = []
    for k in FLAG_FIELDS:
        v = str(it.get(k) or "").strip()
        if not v or (k == "task_type" and v in report_out.WORKTYPES):
            continue
        try:
            terms = fn(v)
        except Exception:  # noqa: BLE001 - 확인하지 못한 글은 표시한다(안전한 쪽)
            terms = ["(확인하지 못함)"]
        for x in terms or ():
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
    return out[:FLAG_TERMS_MAX]


def _share_html(root, cfg, tag, scrubber, ids, owner, function):
    """공유용 리포트(report_out.build(variant="share")) — 스크립트가 없어야 한다."""
    import report_out
    h = report_out.build(tag, variant="share", scrubber=scrubber, include=list(ids), owner=owner, function=function,
                         root=root, cfg=cfg)
    if not isinstance(h, str) or not h.strip():
        raise ShareError("no_result", "공유용 리포트를 만들지 못했습니다 — 분석 결과를 확인하세요")
    if "<script" in h.lower():
        raise ShareError("no_result", "공유용 리포트에 스크립트가 있어 보내지 않습니다")
    return h


def _allowed(items, cfg, personal, team, sc=None):
    r"""report_out.share_items 의 항목 → (미리보기에 올릴 항목[parts 붙임], 민감한 내용이 남아 뺀 수). 미리보기와 보내기가 같은 규칙을 쓴다.
    가린 뒤에도 민감한 낱말·식별번호·제한 고객의 이름이 남은 항목은 뺀다(_blocked).
    가린 뒤에도 이름일 수 있는 낱말이 남은 항목은 "flagged": true · "flag_terms" 를 붙이고 익명 팀 집계에는 넣지 않는다(parts 에
    team 없음 — 화면은 표시하고 체크를 꺼 둔다. 개인 리포트에는 팀원이 확인하고 고를 때만 실린다)."""
    allowed, blocked = [], 0
    for it in items:
        kind = it.get("kind")
        if kind not in ("candidate", "step") or (kind == "step" and not personal):
            continue
        if not str(it.get("name") or "").strip():
            continue
        if _blocked(it, cfg, sc):
            blocked += 1
            continue
        terms = _flag_terms(sc, it)
        parts = [p for p in PARTS if (p == "personal" and personal)
                 or (p == "team" and team and kind == "candidate" and not terms)]
        row = dict(it, parts=parts)
        if terms:
            row.update(flagged=True, flag_terms=terms)
        allowed.append(row)
    return allowed, blocked


def _canon(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True)


def _rederive(root, cfg, doc, sc):
    r"""보낼 때 공유본 항목·기간을 분석 결과에서 다시 만든다(report_out.share_items · ShareScrubber — 미리보기와 같은 규칙).
    미리보기 파일의 것과 하나라도 다르면 보내지 않는다 — 미리보기 파일을 손으로 고치고 해시를 맞춰도 가리지 않은 글(고객사·과제·
    사람 이름)이 명령줄·API 로 나가지 않는다(R6·R9). → (항목 목록, 기간 'YYYY-MM~YYYY-MM')."""
    import report_out
    tag = str(doc.get("tag") or "")
    fresh = report_out.share_items(tag, scrubber=sc, root=root, cfg=cfg)
    if fresh is None:
        raise ShareError("no_result", f"{tag} 는 AgentFinder32 분석 결과가 아닙니다 — 다시 분석하세요")
    pp = doc.get("parts") if isinstance(doc.get("parts"), dict) else {}
    items, _b = _allowed(fresh, cfg, bool(pp.get("personal")), bool(pp.get("team")), sc)
    per = report_out.share_period(tag, root=root)
    if (_canon(items) != _canon(doc.get("items")) or doc.get("period") != per
            or doc.get("month") != (per.split("~")[-1] if per else "")):
        raise ShareError("no_result", "미리보기와 지금 만든 공유본이 다릅니다 — 다시 미리 보세요")
    return items, per


def _check_excluded(text, items, keep_ids):
    """고르지 않은 항목의 글이 공유용 리포트에 남아 있으면 ShareError — 미리보기와 보내는 것이 같아야 한다."""
    kept = " ".join(str(it.get(k) or "") for it in items if it["id"] in keep_ids for k in ("name", "logic", "reason", "agent_how"))
    for it in items:
        if it["id"] in keep_ids:
            continue
        for k in ("name", "logic", "reason", "agent_how"):
            v = str(it.get(k) or "").strip()
            if len(v) >= 4 and v not in kept and html.escape(v, quote=True) in text:
                raise ShareError("no_result", "고르지 않은 항목이 공유용 리포트에 남아 보내지 않았습니다 — 다시 미리 보세요")


def preview(root=None, cfg=None, *, tag=None, personal=True, team=True, owner="", function=""):
    r"""공유 미리보기 — report\share\preview_<tag>.json(+ 개인 리포트를 고르면 preview_<tag>.html). 보내지 않는다."""
    root = os.path.abspath(str(root or ROOT))
    cfg = _cfg(cfg, root)
    require_consent(root, cfg)
    import report_out
    if not personal and not team:
        personal = team = True
    tag = tag or report_out.latest_tag(os.path.join(root, "report"))
    if not tag or not TAG_RX.match(str(tag)):
        raise ShareError("no_result", "공유할 분석 결과가 없습니다 — 먼저 [분석 실행]을 하세요")
    sc = _scrubber(cfg, root, tag)
    _refuse_stale(root, tag, sc)
    items = report_out.share_items(tag, scrubber=sc, root=root, cfg=cfg)
    if items is None:
        raise ShareError("no_result", f"{tag} 는 AgentFinder32 분석 결과가 아닙니다 — 다시 분석하세요")
    owner, function = _typed(owner), _typed(function)
    allowed, blocked = _allowed(items, cfg, personal, team, sc)
    if not allowed:
        raise ShareError("no_result", "공유할 수 있는 항목이 없습니다")
    if not any(it["parts"] for it in allowed):
        raise ShareError("no_result", "보낼 수 있는 항목이 없습니다 — 이름이 남았을 수 있는 후보는 익명 팀 집계에 넣지 않습니다")
    flagged = sum(1 for it in allowed if it.get("flagged"))
    sdir = _share_dir(root)
    html_rel, html_sha = "", ""
    if personal:
        text = _share_html(root, cfg, tag, sc, [i["id"] for i in allowed], owner, function)
        hp = os.path.join(sdir, f"preview_{tag}.html")
        _write_bytes(hp, text.encode("utf-8"))
        html_rel = os.path.relpath(hp, root)
        html_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    per = report_out.share_period(tag, root=root)
    # 시각(epoch)은 글에 두지 않는다(D10 — report\ 아래는 날짜만). 30분 신선도는 미리보기 파일의 수정 시각으로 본다(_load_preview).
    doc = {"product": lmname.PRODUCT, "schema": lmname.SHARE_SCHEMA, "kind": "preview", "tag": tag,
           "created": _today().isoformat(),
           "owner": owner, "function": function, "period": per,
           "month": per.split("~")[-1] if per else "", "parts": {"personal": bool(personal), "team": bool(team)},
           "team_fields": ["name", "task_type"], "items": allowed, "blocked": blocked,
           "html": html_rel, "html_sha256": html_sha, "sources": _sources(root, tag), "masked": sc.table()}
    raw = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    pf = os.path.join(sdir, f"preview_{tag}.json")
    _write_bytes(pf, raw)
    msg = f"미리보기를 만들었습니다 — 항목 {len(allowed)}개"
    if blocked:
        msg += f" · 민감한 내용이 남아 뺀 항목 {blocked}개"
    if flagged:
        msg += f" · 이름이 남았을 수 있어 표시한 항목 {flagged}개(익명 팀 집계에는 넣지 않습니다)"
    return result("ok", msg, tag=tag, preview_file=pf, sha256=hashlib.sha256(raw).hexdigest(),
                  html=(os.path.join(root, html_rel) if html_rel else ""), items=allowed, blocked=blocked, flagged=flagged,
                  parts=doc["parts"], period=per, owner=owner, function=function, masked=doc["masked"])


# ── 보내기 표(화면이 확인 창 뒤에 쓴다 — 계약 C9) ───────────────────────────────────────────────
def _take_ticket(root, path):
    r"""report\share\ticket_<nonce>.json → dict. 읽자마자 지운다(한 번만 쓴다). report\share 밖·이름이 틀림·링크·30분이 지남·
    형식이 틀림이면 ShareError('no_result'). report\share 밖의 파일은 지우지 않는다."""
    sdir = os.path.normcase(os.path.abspath(_share_dir(root)))
    p = os.path.abspath(str(path or ""))
    if not path or os.path.normcase(os.path.dirname(p)) != sdir or not _TICKET_NAME.match(os.path.basename(p)):
        raise ShareError("no_result", TICKET_MSG)
    try:
        st = os.lstat(p)
        if not stat.S_ISREG(st.st_mode) or (getattr(st, "st_file_attributes", 0) or 0) & 0x400:
            raise ShareError("no_result", TICKET_MSG)
        with open(p, "rb") as f:
            raw = f.read(65536)
    except OSError:
        raise ShareError("no_result", TICKET_MSG) from None
    finally:
        try:
            if os.path.isfile(p) and not os.path.islink(p):
                os.remove(p)
        except OSError:
            pass
    age = time.time() - st.st_mtime
    if not -300 <= age <= TICKET_MAX_AGE:
        raise ShareError("no_result", "확인 창에서 보내기를 누른 지 30분이 지났습니다 — 다시 미리 보고 보내세요")
    try:
        d = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ShareError("no_result", TICKET_MSG) from None
    if not _ticket_ok(d):
        raise ShareError("no_result", TICKET_MSG)
    return d


def _ticket_ok(d):
    if not isinstance(d, dict) or d.get("product") != lmname.PRODUCT or d.get("kind") != "share_ticket":
        return False
    if not _DATE_RX.match(str(d.get("created") or "")) or not _HEX64.match(str(d.get("preview_sha256") or "")):
        return False
    ids, parts = d.get("ids"), d.get("parts")
    if not isinstance(ids, list) or not ids or not all(isinstance(x, str) and x for x in ids):
        return False
    if not isinstance(parts, list) or not parts or len(set(parts)) != len(parts) or not set(parts) <= set(PARTS):
        return False
    if not isinstance(d.get("server"), str) or not _HEX32.match(str(d.get("server_id") or "")):
        return False
    if not isinstance(d.get("org_label"), str) or not d["org_label"] or d.get("transport") not in ("http", "https"):
        return False
    days = d.get("server_days")
    return isinstance(days, dict) and all(isinstance(days.get(k), int) and not isinstance(days.get(k), bool)
                                          for k in PARTS)


def _bind_ticket(tk, sha256, include, personal, team):
    """명령줄 값과 표를 맞춘다 → (sha256, include, personal, team). 주지 않은 값은 표의 것 · 준 값이 표와 다르면 거절."""
    if sha256 and str(sha256).strip().lower() != tk["preview_sha256"]:
        raise ShareError("no_result", "확인한 미리보기와 보내려는 미리보기가 다릅니다 — 다시 미리 보세요")
    ids = list(dict.fromkeys(tk["ids"]))
    if include and set(include) != set(ids):
        raise ShareError("no_result", "확인한 항목과 보내려는 항목이 다릅니다 — 다시 미리 보세요")
    parts = set(tk["parts"])
    if (personal or team) and {p for p, on in (("personal", personal), ("team", team)) if on} != parts:
        raise ShareError("no_result", "확인한 갈래(개인 리포트·익명 팀 집계)와 보내려는 갈래가 다릅니다 — 다시 미리 보세요")
    return tk["preview_sha256"], list(include) if include else ids, "personal" in parts, "team" in parts


def _ticket_vs_hello(tk, t, h):
    """확인 창에서 본 서버(표)와 지금 hello 가 같아야 보낸다 — 주소·server_id·조직 이름·전송 방식·서버 보관기한."""
    want = {"server": t.url, "server_id": str(h.get("server_id") or ""), "org_label": h.get("org_label") or "",
            "transport": h.get("transport"),
            "server_days": {"personal": h.get("serverPersonalDays"), "team": h.get("serverTeamDays")}}
    bad = [k for k, v in want.items() if tk.get(k) != v]
    if bad:
        raise ShareError("not_af32", f"확인 창에서 본 서버와 지금 서버가 다릅니다({', '.join(bad)}) — 다시 미리 보고 확인하세요")


# ── 보내기 ──────────────────────────────────────────────────────────────────────
def _load_preview(root, cfg, preview_file, sha256):
    sdir = os.path.normcase(os.path.abspath(_share_dir(root)))
    pf = os.path.abspath(str(preview_file or ""))
    if os.path.normcase(os.path.dirname(pf)) != sdir or not re.fullmatch(r"preview_\d{8}-\d{8}\.json", os.path.basename(pf)):
        raise ShareError("no_result", "미리보기 파일이 report\\share 의 것이 아닙니다 — 다시 미리 보세요")
    try:
        with open(pf, "rb") as f:
            raw = f.read()
    except OSError:
        raise ShareError("no_result", "미리보기 파일이 없습니다 — 다시 미리 보세요") from None
    if not sha256 or hashlib.sha256(raw).hexdigest() != str(sha256).strip().lower():
        raise ShareError("no_result", "미리보기가 바뀌었습니다 — 다시 미리 보세요")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ShareError("no_result", "미리보기 파일이 깨졌습니다 — 다시 미리 보세요") from None
    if not isinstance(doc, dict) or doc.get("product") != lmname.PRODUCT or doc.get("kind") != "preview":
        raise ShareError("no_result", "AgentFinder32 미리보기가 아닙니다 — 다시 미리 보세요")
    try:
        age = time.time() - os.path.getmtime(pf)       # 미리보기를 쓴 때 = 파일 수정 시각(글에는 날짜만 — D10)
    except OSError:
        raise ShareError("no_result", "미리보기 파일이 없습니다 — 다시 미리 보세요") from None
    if not -300 <= age <= PREVIEW_MAX_AGE:
        raise ShareError("no_result", "미리보기를 만든 지 30분이 지났습니다 — 다시 미리 보세요")
    tag = str(doc.get("tag") or "")
    if not TAG_RX.match(tag) or doc.get("sources") != _sources(root, tag):
        raise ShareError("no_result", "미리보기 뒤에 분석 결과가 바뀌었습니다 — 다시 미리 보세요")
    return doc


def _post(t, path, body, headers, cfg):
    """보내기 요청 하나 → 서버 답 dict. 실패는 ShareError — 서버가 HTTP 로 거절했으면 extra["http"] 에 그 상태(받지 않았다),
    닿지 않았거나 답을 읽지 못했으면 없음(받았는지 모른다)."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_BODY:
        raise ShareError("too_big", "보낼 내용이 서버 상한(5MB)을 넘습니다 — 항목을 줄여 다시 미리 보세요", http=0)
    code, d = _call(t, "POST", path, body=raw, headers=headers, timeout=wait_limits(cfg)["timeout"])
    if code == 200 and isinstance(d, dict) and d.get("ok") and isinstance(d.get("token"), str) and d["token"]:
        return d
    if code == 200:
        raise ShareError("server_error", "서버 답을 읽지 못했습니다")
    e = _http_error(code, d)
    e.extra["http"] = code
    raise e


def _not_stored(e):
    """서버가 받지 않은 것이 확실한 실패인가 — HTTP 4xx 거절이거나 보내기 전에 멈춘 것(http=0). 그 밖(닿지 않음·시간 초과·5xx·
    답을 못 읽음)은 받았는지 모른다."""
    h = e.extra.get("http")
    return isinstance(h, int) and (h == 0 or 400 <= h < 500)


def _delete(t, r, cfg, timeout):
    """영수증 하나를 그 서버에서 지운다 → True(지움·이미 없음) | ShareError. 부르는 쪽이 그 서버가 영수증의 서버(server_id)인지
    먼저 확인한다 — 다른 서버의 404 를 '지웠다'로 보지 않게."""
    code, d = _call(t, "DELETE", f"{P}/share/{r['part']}/{r['id']}", headers={"X-AF32-Token": r["token"]}, timeout=timeout)
    if code in (200, 404):
        return True
    raise _http_error(code, d)


def _personal_on_server(t, h, recs, cfg, root):
    """익명 팀 집계만 보낼 때 — 이 서버에 내 개인 리포트가 있나(영수증으로 본다 · personal_also 의 근거). 받은 것이 확인된 개인
    리포트 영수증이 있으면 참. '받았는지 모르는'(pending) 영수증뿐이면 서버에 한 번 물어 정한다: 200 받았다(표시를 뗀다) → 참 ·
    403 다른 토큰으로 저장된 내 개인 리포트가 있다(이 영수증으로는 못 지우니 지운다) → 참 · 404 없다(영수증을 지운다) → 거짓 ·
    닿지 않거나 그 밖의 답이면 None(모른다 — 부르는 쪽이 보내지 않는다). → (참|거짓|None, 새 영수증 목록)"""
    out, found, unsure, changed = list(recs), False, False, False
    for r in [x for x in recs if x["part"] == "personal" and _on_server(x, t, h)]:
        if not r.get("pending"):
            found = True
            continue
        try:
            code, d = _call(t, "GET", f"{P}/share/personal/{r['id']}", headers={"X-AF32-Token": r["token"]},
                            timeout=wait_limits(cfg)["ping"])
        except ShareError:
            unsure = True
            break
        if code == 200:
            r.pop("pending", None)
            if isinstance(d, dict) and d.get("expires"):
                r["expires"] = str(d["expires"])
            found = changed = True
        elif code in (403, 404):
            out = [x for x in out if x is not r]
            changed = True
            found = found or code == 403
        else:
            unsure = True
    if changed:
        save_receipts(root, out)
    return (True if found else (None if unsure else False)), out


def _sent_copy(root, tag, part, data):
    r"""보낸 사본(report\share — 보관기한 shareDays)."""
    try:
        name = f"sent_{tag}_{part}." + ("html" if part == "personal" else "json")
        _write_bytes(os.path.join(_share_dir(root), name),
                     data.encode("utf-8") if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError:
        pass


def share(root=None, cfg=None, *, preview_file=None, sha256=None, include=None, personal=False, team=False, join=None,
          ticket=None):
    """미리보기에서 고른 항목을 보낸다 — (a) 개인 리포트 (b) 익명 팀 집계, 각각 따로. ticket(화면이 쓴 보내기 표 경로)을 주면
    표를 먼저 지우고(한 번만) 그 값과 미리보기·지금 hello 를 맞춘다 — 명령줄(--share)은 표가 있어야 한다."""
    root = os.path.abspath(str(root or ROOT))
    tk = _take_ticket(root, ticket) if ticket is not None else None
    cfg = _cfg(cfg, root)
    require_consent(root, cfg)
    if tk is not None:
        sha256, include, personal, team = _bind_ticket(tk, sha256, include, personal, team)
    doc = _load_preview(root, cfg, preview_file, sha256)
    if not personal and not team:
        raise ShareError("no_result", "보낼 갈래(개인 리포트·익명 팀 집계)를 하나 이상 고르세요")
    for p, on in (("personal", personal), ("team", team)):
        if on and not (doc.get("parts") or {}).get(p):
            raise ShareError("no_result", f"미리보기에 {PART_LABEL[p]} 이(가) 없습니다 — 그 갈래를 골라 다시 미리 보세요")
    tag = doc["tag"]
    sc = _scrubber(cfg, root, tag)
    _refuse_stale(root, tag, sc)
    # 보낼 글(후보 이름·업무 유형·단계·기간)은 미리보기 파일에서 가져오지 않고 분석 결과에서 다시 만든다 — 미리본 것과 같아야 보낸다
    items, per = _rederive(root, cfg, doc, sc)
    by_id = {it["id"]: it for it in items}
    want = []
    for i in include or []:
        if i not in by_id:
            raise ShareError("no_result", "미리보기에 없는 항목을 골랐습니다 — 다시 미리 보세요")
        if i not in want:
            want.append(i)
    keep = set(want)
    sel = [it for it in items if it["id"] in keep]
    if not sel:
        raise ShareError("no_result", "보낼 항목을 하나 이상 고르세요")
    flagged = [it for it in sel if it.get("kind") == "candidate" and it.get("flagged")]
    cands = [it for it in sel if it.get("kind") == "candidate" and "team" in (it.get("parts") or ()) and not it.get("flagged")]
    if team and not personal and flagged:           # 표시된 후보는 익명 팀 집계에 넣지 않는다(C4) — 그것만 보내려 하면 거절
        raise ShareError("no_result", ("익명 팀 집계에 넣을 수 없는 후보를 골랐습니다(가린 뒤에도 이름이 남았을 수 있습니다) — "
                                       "표시된 항목의 체크를 끄고 보내세요"))
    if team and not cands:
        raise ShareError("no_result", "익명 팀 집계에 넣을 Agentic AI 전환 후보를 하나 이상 고르세요"
                         + (" — 이름이 남았을 수 있는 후보는 익명 팀 집계에 넣지 않습니다" if flagged else ""))
    if team and (len(cands) > TEAM_LIMITS["needs"]
                 or any(len(str(c.get("name") or "")) > TEAM_LIMITS["name"]
                        or len(str(c.get("task_type") or "")) > TEAM_LIMITS["task_type"] for c in cands)):
        raise ShareError("no_result", f"익명 팀 집계에는 후보를 {TEAM_LIMITS['needs']}개까지, 이름은 {TEAM_LIMITS['name']}자까지 넣을 수 "
                                      "있습니다 — 후보를 줄여 고르세요")
    owner, function = _typed(doc.get("owner")), _typed(doc.get("function"))
    body_p = None
    if personal:
        if not owner:
            raise ShareError("no_result", "개인 리포트에 쓸 이름을 [공유] 탭에 적고 다시 미리 보세요")
        text = _share_html(root, cfg, tag, sc, [it["id"] for it in sel], owner, function)
        _check_excluded(text, items, keep)
        body_p = {"owner_id": install.install_id(root), "owner": owner, "function": function, "period": per,
                  "report_html": text}
        if len(json.dumps(body_p, ensure_ascii=False).encode("utf-8")) > MAX_BODY:
            raise ShareError("too_big", "개인 리포트가 서버 상한(5MB)을 넘습니다 — 항목을 줄여 다시 미리 보세요")
    a = teamaddr.load(root)
    if not a.configured:
        raise ShareError("no_address", NO_ADDRESS_MSG)
    jn = teamaddr.norm_join(join or os.environ.get(JOIN_ENV) or a.join)
    if not jn:
        raise ShareError("bad_join", f"참여 코드가 없습니다 — 조직장이 알려 준 참여 코드를 {teamaddr.EDIT_BAT} 에서 저장하세요")
    t = resolve_target(a.scheme, a.host, a.port, cfg)
    h = hello(t, cfg)
    if tk is not None:
        _ticket_vs_hello(tk, t, h)
    if personal and h["transport"] == "http" and not h["personalOverHttp"]:
        raise ShareError("http_personal_refused", (f"{h.get('org_label') or '조직장'} 서버는 암호화 없는 HTTP 로는 개인 리포트를 받지 "
                                                   "않습니다 — 익명 팀 집계만 고르거나 조직장에게 HTTPS 를 요청하세요"))
    info = _server_info(h)
    sent = []
    today = _today().isoformat()
    lim = wait_limits(cfg)
    recs = load_receipts(root)
    live_personal = False                                   # 익명 팀 집계만 보낼 때 — 이 서버에 내 개인 리포트가 있나
    if team and not personal:
        live_personal, recs = _personal_on_server(t, h, recs, cfg, root)
        if live_personal is None:
            raise ShareError("server_error", ("앞서 보낸 개인 리포트가 서버에 있는지 확인하지 못해 익명 기여분을 보내지 않았습니다 — "
                                              "잠시 뒤 다시 보내거나 [보낸 공유 모두 거두기]로 지운 뒤 보내세요"),
                             sent=sent, server=t.url, **info)
    mine = [r for r in recs if _on_server(r, t, h)]
    gone = 0                                                # 지우고 새 기여분으로 바꾸지 못한(않은) 앞선 익명 기여분 수

    def failed(e, unsure=None):
        """보내기 실패에 어디까지 갔는지를 싣는다 — sent(받았다고 답한 갈래) · unsure(받았는지 모르는 갈래 · unknown) ·
        team_removed(지우고 새로 보내지 못한 앞선 익명 기여분) · 서버 값. → e"""
        if unsure:
            e.msg += UNSURE_MSG
            e.extra.update(unsure=[unsure], unknown=True)
        if gone and unsure != "team":
            e.msg += GONE_MSG.format(n=gone)
        e.extra.update(sent=list(sent), server=t.url, team_removed=gone, **info)
        e.extra.pop("http", None)
        return e

    def drop_team(rs):
        nonlocal recs, gone
        for r in rs:
            try:
                _delete(t, r, cfg, lim["timeout"])
            except ShareError as e:
                raise failed(ShareError(e.code, "앞서 보낸 익명 기여분을 지우지 못해 새로 보내지 않았습니다 — " + e.msg)) from None
            recs = [x for x in recs if x is not r]
            save_receipts(root, recs)
            gone += 1

    old_team = [r for r in mine if r["part"] == "team"]
    if personal:
        # 개인 리포트를 보내면 이 서버의 익명 기여분은 '개인 리포트를 함께 보냈다'(personal_also)가 참이어야 한다 — 참이 아닌 것은
        # 개인 리포트를 보내기 전에 거둔다(표시가 틀린 기여분이 개인 리포트와 함께 서버에 있으면 D16 의 기준이 틀어진다)
        drop_team([r for r in old_team if r.get("personal_also") is not True])
        old_team = [r for r in old_team if r.get("personal_also") is True]
        prev = [r for r in recs if _on_server(r, t, h) and r["part"] == "personal" and r.get("id") == body_p["owner_id"]]
        was_live = any(not r.get("pending") for r in prev)
        tok = prev[-1]["token"] if prev else secrets.token_hex(24)
        rec = {"server": t.url, "server_id": info["server_id"], "org_label": info["org_label"], "part": "personal",
               "id": body_p["owner_id"], "token": tok, "sent": today, "expires": _expect(h, "personal"), "pending": True}
        others = [r for r in recs if not any(r is x for x in prev)]
        recs = others + [rec]
        save_receipts(root, recs)                           # 보내기 전에 영수증부터(답을 못 받아도 지울 수 있게)
        try:
            d = _post(t, P + "/share/personal", body_p, {"X-AF32-Join": jn, "X-AF32-Token": tok}, cfg)
        except ShareError as e:
            unsure = not _not_stored(e)
            if not unsure:
                recs = others + prev                        # 받지 않았다 — 영수증을 보내기 전으로
            elif was_live:
                rec.pop("pending", None)                    # 앞서 받은 사본이 같은 토큰으로 서버에 있다
            save_receipts(root, recs)
            failed(e, "personal" if unsure else None)
            raise
        rec.update(token=str(d.get("token") or tok), expires=str(d.get("expires") or rec["expires"]))
        rec.pop("pending", None)
        save_receipts(root, recs)
        sent.append("personal")
        _sent_copy(root, tag, "personal", body_p["report_html"])
    if team:
        drop_team(old_team)                                 # 한 사람 = 기여분 하나 — 앞서 보낸 것은 지우고 새로 보낸다
        personal_also = "personal" in sent or live_personal
        tok = secrets.token_hex(24)
        body_t = {"contribution_id": secrets.token_hex(16), "month": (per.split("~")[-1] if per else "") or today[:7],
                  "personal_also": personal_also,
                  "needs": [{"name": c.get("name"), "task_type": c.get("task_type") or ""} for c in cands]}
        rec = {"server": t.url, "server_id": info["server_id"], "org_label": info["org_label"], "part": "team",
               "id": body_t["contribution_id"], "token": tok, "sent": today, "expires": _expect(h, "team"),
               "personal_also": personal_also, "pending": True}
        recs = recs + [rec]
        save_receipts(root, recs)
        try:
            d = _post(t, P + "/share/team", body_t, {"X-AF32-Join": jn, "X-AF32-Token": tok}, cfg)
        except ShareError as e:
            unsure = not _not_stored(e)
            if not unsure:
                recs = [x for x in recs if x is not rec]
            save_receipts(root, recs)
            failed(e, "team" if unsure else None)
            raise
        rec.update(token=str(d.get("token") or tok), expires=str(d.get("expires") or rec["expires"]))
        rec.pop("pending", None)
        save_receipts(root, recs)
        sent.append("team")
        gone = 0                                            # 새 기여분으로 바꿨다
        _sent_copy(root, tag, "team", {k: body_t[k] for k in ("month", "personal_also", "needs")})
    labels = " · ".join(PART_LABEL[p] for p in sent)
    msg = f"{info['org_label'] or '조직장'} 에게 보냈습니다: {labels}"
    if gone:                                                # 개인 리포트만 보냈다 — 표시가 틀려 거둔 기여분
        msg += (f" · 앞서 보낸 익명 팀 집계 기여분 {gone}건은 개인 리포트를 함께 보냈는지가 바뀌어 지웠습니다 — 다시 넣으려면 "
                "익명 팀 집계를 골라 보내세요")
    if team and flagged:
        msg += f" · 이름이 남았을 수 있는 후보 {len(flagged)}개는 익명 팀 집계에 넣지 않았습니다"
    return result("ok", msg, sent=sent, server=t.url, team_removed=gone,
                  receipts=[public_receipt(r) for r in recs if _on_server(r, t, h)], **info)


# ── 철회 ──────────────────────────────────────────────────────────────────────
def _hello_at(url, cfg, seen, timeout):
    """영수증 주소의 서버 hello(철회용 — 제품·형식만 본다 · 한 번만 묻는다) → (Target, hello). 주소마다 한 번만(seen)."""
    v = seen.get(url)
    if v is None:
        try:
            t = target_of_url(url, cfg)
            v = (t, hello(t, cfg, need_id=False, minimal=True, timeout=timeout, tries=1))
        except ShareError as e:
            v = e
        seen[url] = v
    if isinstance(v, ShareError):
        raise v
    return v


def _locate(r, cfg, seen, timeout, cur):
    """영수증 r 의 서버를 찾는다 → (Target, hello). 영수증 주소의 서버가 그 서버(server_id)가 아니거나 닿지 않으면 지금 저장한
    주소를 본다 — 같은 서버면 영수증 주소를 그리로 옮긴다. 아니면 ShareError(다른 서버면 not_af32)."""
    first = None
    for url in dict.fromkeys(u for u in (r.get("server"), cur) if u):
        try:
            t, h = _hello_at(url, cfg, seen, timeout)
        except ShareError as e:
            first = first or e
            continue
        if _same_server(r, h):
            if url != r.get("server"):
                r["server"] = url                    # 같은 서버를 지금 주소에서 찾았다(서버 IP·이름이 바뀌었다)
            return t, h
        first = first or ShareError("not_af32", MOVED_MSG)
    raise first or ShareError("no_address", "영수증의 서버 주소를 읽지 못했습니다")


def _withdraw(root, cfg, select, budget=None):
    """고른 영수증을 그 서버에서 지운다 → (지운 수, 남은 영수증 목록, 첫 실패 ShareError|None)."""
    t0 = time.time()
    recs = load_receipts(root)
    todo = [r for r in recs if select(r)]
    lim = wait_limits(cfg)
    a = teamaddr.load(root)
    cur = a.url if a.configured else ""
    removed, first, moved, done = 0, None, False, []
    seen = {}
    for r in todo:
        left = None if budget is None else budget - (time.time() - t0)
        if left is not None and left <= 0.5:
            first = first or ShareError("unreachable", "시간 안에 다 지우지 못했습니다 — 다음 시작 때 다시 합니다")
            break
        timeout = lim["timeout"] if left is None else max(1.0, min(lim["ping"] + 2.0, left))
        before = r.get("server")
        try:
            t, _h = _locate(r, cfg, seen, timeout, cur)
            moved = moved or r.get("server") != before
            _delete(t, r, cfg, timeout)
        except ShareError as e:
            first = first or e
            continue
        recs = [x for x in recs if x is not r]
        save_receipts(root, recs)
        done.append(r)
        removed += 1
    if moved:
        save_receipts(root, recs)
    return removed, [r for r in todo if not any(r is x for x in done)], first


def _same_place(a, b):
    """두 영수증이 같은 서버의 것인가(server_id, 없으면 주소)."""
    if a.get("server_id") and b.get("server_id"):
        return a["server_id"] == b["server_id"]
    return a.get("server") == b.get("server")


def _rkey(r):
    """영수증 하나를 가리키는 값 — 서버(server_id, 없으면 주소)·갈래·id. 개인 리포트의 id(설치 ID)는 어느 서버에서나 같으므로
    서버를 함께 봐야 다른 서버의 영수증과 섞이지 않는다."""
    return (r.get("server_id") or r.get("server"), r.get("part"), r.get("id"))


def withdraw(root=None, cfg=None, *, all_servers=False, part=None):
    """공유 철회 — 영수증마다 그 서버에 DELETE(200·404 면 영수증을 지운다). 시작 확인을 거치지 않는다(지우기는 늘 할 수 있다).
    all_servers 가 아니면 지금 저장한 주소의 서버 것만(그 주소로 적힌 영수증과, 그것과 server_id 가 같은 영수증).
    part="personal" 이면 같은 서버의 익명 기여분 중 '개인 리포트를 함께 보냈다'(personal_also)가 거짓이 아닌 것도 함께 거둔다."""
    root = os.path.abspath(str(root or ROOT))
    cfg = _cfg(cfg, root)
    a = teamaddr.load(root)
    cur = a.url if (a.configured and not all_servers) else None
    recs = load_receipts(root)
    here = {r["server_id"] for r in recs if cur is not None and r["server"] == cur and r.get("server_id")}

    def base(r):
        return ((cur is None or r["server"] == cur or r.get("server_id") in here)
                and (part is None or r["part"] == part))
    chosen = [r for r in recs if base(r)]
    extra = set()
    if part == "personal":
        extra = {_rkey(r) for r in recs if r["part"] == "team" and r.get("personal_also") is not False
                 and any(_same_place(r, p) for p in chosen)}
    if not chosen:
        return result("ok", "지울 공유가 없습니다", removed=0, left=0, pending=[])
    removed, left, first = _withdraw(root, cfg, lambda r: base(r) or _rkey(r) in extra)
    pending = [public_receipt(r) for r in left]
    also = (" · 개인 리포트를 함께 보냈다고 표시한 익명 팀 집계 기여분도 함께 거뒀습니다 — 다시 넣으려면 [공유] 탭에서 익명 팀 집계를 "
            "골라 보내세요") if extra else ""
    if left:
        last = max(str(r.get("expires") or "") for r in left)
        return result(first.code if first else "server_error", PENDING_MSG.format(date=last) + (f" — {first.msg}" if first else ""),
                      removed=removed, left=len(left), pending=pending)
    return result("ok", f"조직장 서버에서 공유 {removed}건을 지웠습니다" + also, removed=removed, left=0, pending=[])


def withdraw_all(root=None, cfg=None, timeout=10):
    """모두 지우기 ②(spec §6.2) — 모든 영수증을 각 서버에서 지운다(전체 timeout 초). 예외를 던지지 않는다.
    → {"ok","removed","left","pending":[{server, org_label, part, sent, expires, pending}],"msg"} (토큰·id 없음 — withdrawal.json
    에 그대로 남겨도 된다)."""
    root = os.path.abspath(str(root or ROOT))
    try:
        cfg = _cfg(cfg, root)
        if not load_receipts(root):
            return {"ok": True, "removed": 0, "left": 0, "pending": [], "msg": ""}
        removed, left, first = _withdraw(root, cfg, lambda r: True, budget=float(timeout))
    except Exception as e:  # noqa: BLE001 - 지우기의 나머지(이 PC 자료 지우기)는 계속돼야 한다
        recs = load_receipts(root, prune=False)
        return {"ok": False, "removed": 0, "left": len(recs), "pending": [public_receipt(r) for r in recs],
                "msg": f"서버 사본을 지우는 중 오류({type(e).__name__})"}
    msg = ""
    if left:
        msg = PENDING_MSG.format(date=max(str(r.get("expires") or "") for r in left))
    return {"ok": not left, "removed": removed, "left": len(left), "pending": [public_receipt(r) for r in left],
            "msg": msg, "code": "ok" if not left else (first.code if first else "server_error")}


def _marked(r):
    """모두 지우기 때 서버에서 못 지워 남긴 영수증인가(consent.withdraw 가 "withdraw": true 를 붙인다)."""
    return bool(r.get("withdraw"))


def retry_withdrawals(root=None, cfg=None, timeout=5):
    r"""모두 지우기를 했는데 서버에서 못 지운 영수증이 남았으면 다시 지운다 — 화면·run.py 가 시작할 때 부른다. 할 일이 없으면 None.
    그때 표시한 영수증("withdraw": true)만 지운다 — 그 뒤에 새로 보낸 공유는 그대로 둔다."""
    root = os.path.abspath(str(root or ROOT))
    if not _withdrawal_pending(root) or not [r for r in load_receipts(root) if _marked(r)]:
        return None
    try:
        cfg = _cfg(cfg, root)
        removed, left, first = _withdraw(root, cfg, _marked, budget=float(timeout))
    except Exception as e:  # noqa: BLE001 - 시작을 막지 않는다(다음 시작 때 다시)
        left = [r for r in load_receipts(root, prune=False) if _marked(r)]
        return {"ok": False, "removed": 0, "left": len(left), "pending": [public_receipt(r) for r in left],
                "msg": f"서버 사본을 지우는 중 오류({type(e).__name__})"}
    msg = PENDING_MSG.format(date=max(str(r.get("expires") or "") for r in left)) if left else ""
    return {"ok": not left, "removed": removed, "left": len(left), "pending": [public_receipt(r) for r in left],
            "msg": msg, "code": "ok" if not left else (first.code if first else "server_error")}


# ── 명령줄 ──────────────────────────────────────────────────────────────────────
def _arg(argv, flag, d=""):
    if flag in argv:
        i = argv.index(flag) + 1
        if i < len(argv) and not argv[i].startswith("--"):
            return argv[i]
    return d


def _args_after(argv, flag):
    if flag not in argv:
        return []
    out = []
    for x in argv[argv.index(flag) + 1:]:
        if x.startswith("--"):
            break
        out += [y for y in x.split(",") if y.strip()]
    return [y.strip() for y in out]


def run(argv, root=None):
    """명령 하나 → 결과 dict(마지막 줄 JSON 이 될 것)."""
    root = os.path.abspath(_arg(argv, "--root") or root or ROOT)
    try:
        cfg, _w = afcfg.load_effective(root)
        if "--status" in argv:
            return status(root, cfg, verify="--verify" in argv, offline="--offline" in argv)
        if "--ping" in argv:
            return ping(root, cfg)
        if "--preview" in argv:
            return preview(root, cfg, tag=_arg(argv, "--tag") or None, personal="--personal" in argv,
                           team="--team" in argv, owner=_arg(argv, "--owner"), function=_arg(argv, "--function"))
        if "--share" in argv:
            tk = _arg(argv, "--ticket")
            if not tk:
                return result("no_result", TICKET_MSG)          # 화면의 확인 창(일회용 표) 없이는 보내지 않는다(D14)
            return share(root, cfg, preview_file=_arg(argv, "--preview-file"), sha256=_arg(argv, "--sha256"),
                         include=_args_after(argv, "--include"), personal="--personal" in argv, team="--team" in argv,
                         ticket=tk)
        if "--withdraw" in argv:
            part = _arg(argv, "--part") or None
            if part is not None and part not in PARTS:
                return result("no_result", "--part 는 personal 또는 team 입니다")
            return withdraw(root, cfg, all_servers="--all" in argv, part=part)
        return result("no_result", "명령을 고르세요 — --status · --ping · --preview · --share · --withdraw")
    except ShareError as e:
        return e.result()
    except Exception as e:  # noqa: BLE001 - 마지막 줄 JSON 계약을 지킨다(화면이 읽는다)
        return result("server_error", f"뜻밖의 오류({type(e).__name__}) — 다시 해 보고, 계속되면 담당자에게 알리세요")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    res = run(argv)
    if res.get("msg"):
        print(f"[teamup] {res['msg']}")
    print(json.dumps(res, ensure_ascii=False))
    return exit_code(res)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
