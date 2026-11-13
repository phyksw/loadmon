# -*- coding: utf-8 -*-
r"""teamaddr.py — 조직장 팀 서버 주소·참여 코드 단일원 (AgentFinder32 · spec §7).

팀원 PC 가 공유할 곳(조직장 PC 의 팀 서버)을 설치 폴더의 config\af32_team_server.json 에 둔다:
  {"product":"AgentFinder32", "host", "port", "scheme":"http"|"https", "join", "saved_at":"YYYY-MM-DD"(날짜만)}
  · 기본 주소는 없다. 저장하기 전에는 어디로도 보내지 않는다(teamup 은 no_address 로 멈춘다).
  · 바꾸는 곳은 AgentFinder32-팀서버주소.bat 하나다. bat 은 입력값을 명령줄에 끼우지 않고 환경변수
    AF32_TA_HOST · AF32_TA_PORT · AF32_TA_JOIN 으로 넘기고 이 파일의 --set-env 가 읽는다. 화면은 보여 주기만 한다.
  · LoadMonitor 의 옛 주소 파일은 읽지 않는다(옛 판 정리 retention.purge_legacy 가 지운다).
  · LoadMonitor 가 쓰던 포트(팀 서버 LEGACY_TEAM_PORT·그 대체 포트 대역, 옛 대시보드 대역, 옛 Edge 디버그 포트)와
    AgentFinder32 자신의 대시보드·Edge 포트는 받지 않는다 — 옛 팀 서버에 공유가 섞이거나 화면과 부딪치지 않게.
  · 참여 코드(join)는 조직장 서버가 처음 켤 때 만든 12자(XXXX-XXXX-XXXX)다. 팀원 공유 요청에 X-AF32-Join 머리글로만
    싣는다. 화면·로그에는 앞 4자만 보인다.
  · scheme 은 주소 칸에 https:// 를 붙여 적으면 https(조직장 서버가 teamdata\tls 인증서로 켠 경우), 아니면 http.

  python core\teamaddr.py --show [--json]
  python core\teamaddr.py --set [--host <IP 또는 https://IP:포트>] [--port <번호>] [--json]   (참여 코드는 --set-env 로만)
  python core\teamaddr.py --set-env [--json]      # bat 전용 — AF32_TA_HOST·AF32_TA_PORT·AF32_TA_JOIN, 빈 값은 그대로 둔다
  python core\teamaddr.py --reset                 # 저장한 주소 파일을 지운다(공유할 곳 없음)
  python core\teamaddr.py --url                   # 지금 주소(없으면 빈 줄)
표준 라이브러리와 core\lmname.py 만 쓴다 — bat 이 스크립트로 바로 부른다.
"""
import io
import json
import os
import re
import socket
import sys
import time
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)     # 동봉 파이썬(._pth)은 스크립트 폴더를 sys.path 에 넣지 않는다
import lmname  # noqa: E402

ROOT = os.path.dirname(_HERE)
FILE_NAME = "af32_team_server.json"
EDIT_BAT = lmname.BAT_PREFIX + "-팀서버주소.bat"
DEFAULT_PORT = lmname.TEAM_DEFAULT_PORT
JOIN_ENV = "AF32_TA_JOIN"                    # bat → --set-env (lmname.TEAM_ADDR_ENV 의 짝)
ENV_NAMES = tuple(lmname.TEAM_ADDR_ENV) + (JOIN_ENV,)
SCHEMES = ("http", "https")

# ── LoadMonitor·자기 포트(받지 않음) ─────────────────────────────────────────────────────────
LEGACY_TEAM_PORT = 9310                      # LoadMonitor 팀 서버 기본 포트
REFUSED_RANGES = (
    (range(LEGACY_TEAM_PORT, LEGACY_TEAM_PORT + 1), "LoadMonitor 팀 서버 포트"),
    (range(LEGACY_TEAM_PORT + 10000, LEGACY_TEAM_PORT + 10021), "LoadMonitor 팀 서버가 제안하던 대체 포트"),
    (range(9100, 9200), "LoadMonitor(LM24) 대시보드 대역"),
    (range(9248, 9308), "LoadMonitor(LM28·LM29·LM30) 대시보드 대역"),
    (tuple(lmname.OLD_CDP_PORTS), "LoadMonitor 전용 Edge 디버그 포트"),
    (lmname.UI_PORTS, "AgentFinder32 화면(대시보드) 대역"),
    ((lmname.CDP_PORT,), "AgentFinder32 전용 Edge 디버그 포트"),
)

# 참여 코드 — 헷갈리는 글자(0·O·1·I)를 뺀 32자에서 12자(60비트)
JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
JOIN_LEN = 12

_LABEL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
# 메신저·메일에서 복사한 주소에 섞여 오는 보이지 않는 글자(BOM·폭 없는 공백·단어 결합자)
_INVISIBLE = "﻿​‌‍⁠"


class Addr:
    """읽어 들인 팀 서버 주소. host 가 빈 문자열이면 아직 정하지 않았다(공유할 곳 없음)."""

    __slots__ = ("host", "port", "scheme", "join", "saved_at", "warnings", "file")

    def __init__(self, host="", port=DEFAULT_PORT, scheme="http", join="", saved_at="", warnings=None, file=""):
        self.host = host or ""
        self.port = int(port)
        self.scheme = scheme if scheme in SCHEMES else "http"
        self.join = join or ""
        self.saved_at = saved_at or ""
        self.warnings = list(warnings or [])
        self.file = file

    @property
    def configured(self):
        return bool(self.host)

    @property
    def url(self):
        return f"{self.scheme}://{self.host}:{self.port}" if self.host else ""

    def as_dict(self):
        """화면·CLI 용 — 참여 코드 원문은 싣지 않는다(join_set · join_hint 만)."""
        return {"host": self.host, "port": self.port, "scheme": self.scheme, "url": self.url,
                "configured": self.configured, "join_set": bool(self.join), "join_hint": join_hint(self.join),
                "saved_at": self.saved_at, "warnings": list(self.warnings), "file": self.file,
                "default_port": DEFAULT_PORT, "edit_bat": EDIT_BAT}


# ── 형식 검사 ─────────────────────────────────────────────────────────────────
def _norm(v):
    r"""입력 정리 — 전각 숫자·마침표(１０．０．０．５)는 반각으로 펴고 복사에 딸려 온 보이지 않는 글자는 지운다."""
    s = unicodedata.normalize("NFKC", str(v if v is not None else ""))
    for z in _INVISIBLE:
        s = s.replace(z, "")
    return s.strip()


def _ipv4(s):
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        # 앞자리 0 은 받지 않는다(010 을 8진수로 읽는 도구가 있어 같은 주소가 둘로 갈린다)
        if not (p.isascii() and p.isdigit()) or len(p) > 3 or (len(p) > 1 and p[0] == "0") or int(p) > 255:
            return False
    return True


def check_host(h):
    r"""서버 주소 — IPv4(예: 10.0.0.5) 또는 PC 이름(예: TEAM-PC, team-pc.corp.local). returns (정규화 값 | None, 오류 문구)"""
    s = _norm(h)
    if not s:
        return None, "서버 주소가 비어 있습니다"
    if not s.isascii():
        return None, f"서버 주소에는 영문·숫자·점·하이픈만 쓸 수 있습니다: {s[:60]}"
    if any(c.isspace() for c in s) or "/" in s or "\\" in s or "@" in s:
        return None, f"서버 주소 형식이 아닙니다: {s[:60]} — 예: 10.0.0.5 또는 PC 이름"
    if ":" in s:
        return None, ("서버 주소 칸에는 IP 만 적으세요(포트는 포트 칸에). "
                      "IPv6 주소는 지원하지 않습니다 — IPv4 주소나 PC 이름을 쓰세요")
    if s.replace(".", "").isdigit():
        return (s, "") if _ipv4(s) else (None, f"IPv4 주소 형식이 아닙니다: {s[:40]} — 예: 10.0.0.5")
    if len(s) > 253 or not all(_LABEL.match(x) for x in s.rstrip(".").split(".")):
        return None, f"PC 이름 형식이 아닙니다: {s[:60]}"
    return s.lower(), ""


def port_problem(p):
    """쓰지 않는 포트면 까닭(한국어), 아니면 None — LoadMonitor 포트와 AgentFinder32 자신의 화면·Edge 포트."""
    try:
        v = int(p)
    except (TypeError, ValueError):
        return None
    for rng, why in REFUSED_RANGES:
        if v in rng:
            return (f"포트 {v} 은(는) {why}라 쓰지 않습니다 — 옛 LoadMonitor 서버에 섞이지 않게 "
                    f"다른 번호(기본 {DEFAULT_PORT})를 쓰세요")
    return None


def check_port(p):
    """포트 번호 1~65535 이고 LoadMonitor·자기 포트가 아님 — returns (int | None, 오류 문구)"""
    try:
        if isinstance(p, bool):
            raise ValueError
        if isinstance(p, float) and not p.is_integer():
            raise ValueError
        if isinstance(p, (int, float)):
            v = int(p)
        else:
            t = _norm(p)
            if not (t.isascii() and t.isdigit()):
                raise ValueError
            v = int(t)
    except (TypeError, ValueError):
        return None, f"포트는 숫자여야 합니다: {str(p)[:20]}"
    if not 1 <= v <= 65535:
        return None, f"포트는 1~65535 사이여야 합니다: {v}"
    why = port_problem(v)
    if why:
        return None, why
    return v, ""


def norm_join(v):
    """참여 코드 정리 — 대문자·하이픈/공백 제거 → 'XXXX-XXXX-XXXX' 또는 None(형식이 아님)."""
    s = _norm(v).upper().replace("-", "").replace(" ", "")
    if len(s) != JOIN_LEN or any(c not in JOIN_ALPHABET for c in s):
        return None
    return "-".join(s[i:i + 4] for i in range(0, JOIN_LEN, 4))


def check_join(v):
    """returns (정리한 참여 코드 | None, 오류 문구)"""
    j = norm_join(v)
    if j is None:
        return None, "참여 코드 형식이 아닙니다 — 조직장이 알려 준 12자(예: ABCD-EFGH-JKLM)를 그대로 적으세요"
    return j, ""


def join_hint(j):
    """참여 코드의 앞 4자만 — 화면·로그용."""
    return (str(j)[:4] + "-····-····") if j else ""


def parse_url(u):
    r"""'http(s)://IP:포트' 꼴 → (host, port|None, scheme|None). 형식이 아니면 None."""
    s = _norm(u)
    m = re.match(r"^(?:(https?)://)?([^/:\s]+)(?::(\d{1,5}))?/?$", s, re.I)
    if not m:
        return None
    host, _e = check_host(m.group(2))
    if not host:
        return None
    port = None
    if m.group(3):
        port, _e = check_port(m.group(3))
        if port is None:
            return None
    return host, port, (m.group(1).lower() if m.group(1) else None)


def split_input(host, port=None):
    r"""bat 입력 정리 — 주소 칸에 'http(s)://IP:포트' 나 'IP:포트' 를 붙여 넣어도 나눠 받는다.
    returns (host|None, port|None, scheme|None, 오류 문구). 칸이 비면 None(바꾸지 않음). 포트 칸에 적은 값이 이긴다."""
    h = _norm(host)
    p = port
    scheme = None
    if h and (":" in h or "/" in h):
        m = re.match(r"^(?:(https?)://)?([^/:\s]+)(?::([^/\s]*))?/?$", h, re.I)
        if not m:
            return None, None, None, f"서버 주소 형식이 아닙니다: {h[:60]} — 예: 10.0.0.5 또는 http://10.0.0.5:{DEFAULT_PORT}"
        scheme = m.group(1).lower() if m.group(1) else None
        h = m.group(2)
        if (p is None or str(p).strip() == "") and m.group(3):
            p = m.group(3)
    hh = None
    if h:
        hh, err = check_host(h)
        if not hh:
            return None, None, None, err
    pp = None
    if p is not None and str(p).strip() != "":
        pp, err = check_port(p)
        if pp is None:
            return None, None, None, err
    return hh, pp, scheme, ""


# ── 읽기·쓰기 ─────────────────────────────────────────────────────────────────
def path(root=None):
    return os.path.join(str(root or ROOT), "config", FILE_NAME)


def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def load(root=None):
    r"""지금 쓸 주소 — config\af32_team_server.json 만 읽는다. 없으면 host 가 빈 Addr(공유할 곳 없음).
    틀린 값은 그 값만 버리고 경고를 남긴다."""
    fp = path(root)
    warn = []
    if not os.path.exists(fp):
        return Addr(warnings=warn)
    d = _read_json(fp)
    if d is None:
        warn.append(f"{FILE_NAME} 을 읽지 못했습니다(형식 오류) — {EDIT_BAT} 에서 주소를 다시 저장하세요")
        return Addr(warnings=warn, file=fp)
    prod = d.get("product")
    if prod not in (None, "", lmname.PRODUCT):
        warn.append(f"{FILE_NAME} 이 {lmname.PRODUCT} 의 주소 파일이 아닙니다 — {EDIT_BAT} 에서 다시 저장하세요")
        return Addr(warnings=warn, file=fp)
    host, port, scheme, join = "", DEFAULT_PORT, "http", ""
    if d.get("host"):
        v, err = check_host(d.get("host"))
        if v:
            host = v
        else:
            warn.append(f"{FILE_NAME} 의 host 무시 — {err}")
    if d.get("port") not in (None, ""):
        v, err = check_port(d.get("port"))
        if v is not None:
            port = v
        else:
            warn.append(f"{FILE_NAME} 의 port 무시 — {err}")
            host = ""             # 주소의 반쪽만 믿고 보내지 않는다(LoadMonitor 포트일 수 있다)
    sc = str(d.get("scheme") or "http").strip().lower()
    if sc in SCHEMES:
        scheme = sc
    else:
        warn.append(f"{FILE_NAME} 의 scheme 무시 — http 또는 https 만 씁니다")
    if d.get("join"):
        j = norm_join(d.get("join"))
        if j:
            join = j
        else:
            warn.append(f"{FILE_NAME} 의 참여 코드 형식이 틀려 무시합니다 — {EDIT_BAT} 에서 다시 적으세요")
    return Addr(host, port, scheme, join, str(d.get("saved_at") or "")[:10], warn, fp)    # 옛 파일의 시각도 날짜까지만


def url(root=None):
    return load(root).url


def _atomic_write(p, text):
    r"""쓰다 만 설정은 '주소가 사라졌다'로 읽힌다 — 임시 파일에 다 쓴 뒤 바꿔 끼운다. 잠깐 잡혀 있으면 짧게 다시."""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    last = None
    for wait in (0, 0.1, 0.2, 0.4, 0.8):
        if wait:
            time.sleep(wait)
        try:
            os.replace(tmp, p)
            return
        except PermissionError as e:
            last = e
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last


def save(root=None, host=None, port=None, join=None, scheme=None):
    r"""주소를 config\af32_team_server.json 에 남긴다 — 준 값만 바꾸고 나머지는 지금 값 그대로.
    returns (ok, 오류 문구, Addr). 형식이 틀린 값은 저장하지 않는다(멀쩡하던 주소가 사라지지 않게)."""
    cur = load(root)
    h, p, sc, j = cur.host, cur.port, cur.scheme, cur.join
    if host is not None:
        h, err = check_host(host)
        if not h:
            return False, err, cur
    if port is not None:
        p, err = check_port(port)
        if p is None:
            return False, err, cur
    if scheme is not None:
        sc = str(scheme).strip().lower()
        if sc not in SCHEMES:
            return False, "전송 방식은 http 또는 https 입니다", cur
    if join is not None:
        j, err = check_join(join)
        if not j:
            return False, err, cur
    doc = {
        "_설명": ("조직장 팀 서버 주소(AgentFinder32). host = 조직장 PC 의 IP 또는 PC 이름, port = 포트, "
                 "scheme = http 또는 https, join = 조직장이 알려 준 참여 코드. 공유는 [공유] 탭에서 내가 고를 때만 보냅니다. "
                 f"바꾸는 곳: {EDIT_BAT}. 이 파일을 지우면 공유할 곳이 없어집니다."),
        "product": lmname.PRODUCT, "host": h, "port": int(p), "scheme": sc, "join": j,
        "saved_at": time.strftime("%Y-%m-%d"),          # 날짜만(D10 — 언제 바꿨는지 시각은 남기지 않는다)
    }
    try:
        _atomic_write(path(root), json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        return False, f"{FILE_NAME} 을 쓰지 못했습니다({type(e).__name__}) — 파일이 열려 있거나 권한이 없습니다", cur
    return True, "", load(root)


def reset(root=None):
    """저장한 주소 파일을 지운다 → 공유할 곳 없음."""
    fp = path(root)
    try:
        if os.path.exists(fp):
            os.remove(fp)
        return True, ""
    except OSError as e:
        return False, f"{FILE_NAME} 을 지우지 못했습니다({type(e).__name__})"


# ── 이 PC 의 주소(조직장 서버가 접속 정보를 쓸 때) ──────────────────────────────────────
def local_ipv4s():
    """이 PC 의 IPv4 주소들(루프백 제외). UDP connect 는 경로만 고르고 패킷은 보내지 않는다."""
    out = []
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s2.settimeout(0.2)
            s2.connect(("10.255.255.255", 1))
            ip = s2.getsockname()[0]
            if ip and ip != "0.0.0.0" and not ip.startswith("127."):
                out.append(ip)
        finally:
            s2.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out


def is_loopback(host):
    h = str(host or "").strip().lower()
    return h == "localhost" or (_ipv4(h) and h.startswith("127."))


def is_local(host, ips=None):
    r"""설정된 서버 주소가 이 PC 인가 — True/False. PC 이름이 이 PC 이름과 다르면 None(모름). DNS 는 묻지 않는다."""
    h = str(host or "").strip()
    if is_loopback(h):
        return True
    if _ipv4(h):
        return h in (local_ipv4s() if ips is None else ips)
    me = (socket.gethostname() or os.environ.get("COMPUTERNAME") or "").strip().lower()
    if me and h.lower().split(".")[0] == me.split(".")[0]:
        return True
    return None


def relation(a, ips=None):
    r"""이 PC 와 저장한 서버 주소의 관계 — (종류, 문구). 종류: none | loopback | server | member | unknown."""
    if not a.configured:
        return "none", f"공유할 곳이 없습니다 — 조직장이 알려 준 주소·참여 코드를 {EDIT_BAT} 에서 저장하세요"
    ips = local_ipv4s() if ips is None else ips
    if is_loopback(a.host):
        return "loopback", f"{a.host} 는 이 PC 안에서만 닿는 주소입니다"
    loc = is_local(a.host, ips)
    if loc:
        return "server", "이 PC 의 주소입니다(이 PC 가 조직장 팀 서버)"
    if loc is False:
        return "member", "다른 PC(조직장 팀 서버)의 주소입니다"
    return "unknown", "PC 이름이라 이 PC 인지 확인하지 않았습니다"


def describe(a, ips=None):
    """사람이 읽는 한 덩어리 — bat·CLI 출력용(참여 코드는 앞 4자만)."""
    if not a.configured:
        lines = ["  서버 주소  : (없음 — 공유할 곳이 정해지지 않았습니다)"]
    else:
        lines = [f"  서버 주소  : {a.host}",
                 f"  포트       : {a.port}",
                 f"  전송 방식  : {a.scheme.upper()}" + ("" if a.scheme == "https" else " (사내망 · 암호화 없음)"),
                 f"  공유 주소  : {a.url}"]
    lines.append(f"  참여 코드  : {join_hint(a.join) or '(없음)'}")
    _k, rel = relation(a, ips)
    lines.append(f"  이 PC 와   : {rel}")
    lines += [f"  [!] {w}" for w in a.warnings]
    return "\n".join(lines)


# ── 명령줄 ───────────────────────────────────────────────────────────────────
def _arg(argv, flag):
    if flag in argv:
        i = argv.index(flag) + 1
        if i < len(argv) and not argv[i].startswith("--"):
            return argv[i]
        return ""
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    js = "--json" in argv
    root = _arg(argv, "--root") or None

    def out(obj, text, rc):
        print(json.dumps(obj, ensure_ascii=False) if js else text)
        return rc
    join = None
    if "--set-env" in argv:
        # bat(AgentFinder32-팀서버주소.bat) 전용 — 사람이 입력한 값을 명령줄에 끼워 넣지 않고 환경변수로 받는다
        # ('&'·'"' 같은 문자가 섞여도 cmd 가 명령으로 해석하지 않게). 빈 값 = 그대로 둔다.
        # 이름은 AF32_TA_* 만 — 같은 창에서 옛 LoadMonitor bat 을 돌린 뒤의 잔여값(LM**_TA_*)을 읽지 않게.
        env = {k: _norm(os.environ.get(v, "")) for k, v in zip(("host", "port", "join"), ENV_NAMES, strict=True)}
        if not any(env.values()):
            a = load(root)
            return out(dict(a.as_dict(), ok=True, changed=False), "[teamaddr] 바꾼 값이 없어 그대로 둡니다\n" + describe(a), 0)
        argv = ["--set"] + [x for k, flag in (("host", "--host"), ("port", "--port"))
                            if env[k] for x in (flag, env[k])] + (["--json"] if js else [])
        join = env["join"] or None
    if "--set" in argv:
        host, port = _arg(argv, "--host"), _arg(argv, "--port")
        if host == "" or port == "":
            return out({"ok": False, "error": "값이 빠진 인자가 있습니다"},
                       f"[teamaddr] 값이 빠진 인자가 있습니다 — 예: --set --host 10.0.0.5 --port {DEFAULT_PORT}", 2)
        if host is None and port is None and join is None:
            return out({"ok": False, "error": "바꿀 값이 없습니다"},
                       "[teamaddr] 바꿀 값이 없습니다 — --host / --port 중 하나 이상", 2)
        scheme = None
        if host is not None:
            h, p2, scheme, err = split_input(host, port)
            if err:
                return out({"ok": False, "error": err}, f"[teamaddr] 저장하지 않았습니다 — {err}", 1)
            host, port = h, (p2 if p2 is not None else port)
        if join is not None:
            j, err = check_join(join)
            if not j:
                return out({"ok": False, "error": err}, f"[teamaddr] 저장하지 않았습니다 — {err}", 1)
        ok, err, a = save(root, host=host, port=port, join=join, scheme=scheme)
        if not ok:
            return out({"ok": False, "error": err}, f"[teamaddr] 저장하지 않았습니다 — {err}", 1)
        return out(dict(a.as_dict(), ok=True, changed=True), "[teamaddr] 저장했습니다\n" + describe(a), 0)
    if "--reset" in argv:
        ok, err = reset(root)
        a = load(root)
        return out(dict(a.as_dict(), ok=ok, error=err),
                   ("[teamaddr] 저장한 주소 파일을 지웠습니다\n" if ok else f"[teamaddr] {err}\n") + describe(a), 0 if ok else 1)
    a = load(root)
    if "--url" in argv:
        return out({"ok": True, "url": a.url}, a.url, 0)
    return out(dict(a.as_dict(), ok=True), "[teamaddr] 지금 저장한 조직장 팀 서버 주소\n" + describe(a), 0)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))
    sys.exit(main())
