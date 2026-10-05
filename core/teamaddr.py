# -*- coding: utf-8 -*-
r"""팀 서버 주소(서버 IP·포트) — **단일원** (LM24 v5).

v4 까지는 팀 서버 주소가 config.teamServerUrl 한 줄(http://IP:포트)에 묶여 있었고, 팀 서버·업로드·
대시보드가 그 문자열을 각자 쪼개 썼다. 기본 IP 는 화면 안내문·오류 문구에도 박혀 있었다. 그래서
서버 PC 가 바뀌면(IP 변경) 고칠 곳이 여러 군데였다. 사용자 지시(2026-10-05):
  · "서버 ip 설정하는 것 포트까지 따로 빼 주세요"
  · "팀서버 업로드에서 바꾸는 게 아니라 그냥 따로 별도 bat 에서 바꿀 수 있도록"
  · "그대로 폴더를 옮기면 그 서버 IP 변경이 유지되는 채로 일반 유저는 분석 후 그쪽 IP 로 올릴 수 있게
     하고, 팀 서버는 그 IP 로 해서 데이터를 취합할 수 있도록"

v5 는:
  · 서버 IP 와 포트를 **설치 폴더의 config\team_server.json** 에 따로 둔다(config.json 과 분리).
    설치 폴더 안의 파일이라 폴더를 통째로 옮기거나 복사해 나눠 주면 바꾼 주소가 그대로 따라간다
    (PC 이동 묶음·배포본 만들기도 이 파일을 담는다).
  · 바꾸는 곳은 **LoadMonitor24-팀서버주소.bat 하나**다. 대시보드는 지금 주소를 보여 주기만 한다.
  · 쓰는 곳: 업로드(teamup.py · 대시보드 [팀 서버 업로드] · 분석 후 자동 업로드)는 http://서버IP:포트 로
    보내고, 팀 서버(teamserver.py)는 그 포트로 열면서 설정된 서버 IP 가 이 PC 의 주소인지 확인해 알린다.
  · 기본값 상수는 여기 한 곳뿐이다(tools\check_teamaddr.py 관문이 다른 곳의 IP 리터럴·옛 키 직접 읽기를 막는다).

읽는 순서(값마다 따로, 앞이 이긴다): config\team_server.json → config\config.json 의 옛 teamServerUrl
(v4 이하에서 고쳐 둔 주소를 이어받는다) → 기본값. 파일 값이 형식에 어긋나면 그 값만 버리고 경고를
남긴다 — 손으로 고치다 틀려도 멀쩡한 나머지 값까지 사라지지 않게.

  python core\teamaddr.py --show [--json]
  python core\teamaddr.py --set [--host <IP>] [--port <번호>] [--json]
  python core\teamaddr.py --reset          # 따로 둔 파일을 지우고 이전 값·기본값으로
이 파일은 표준 라이브러리만 쓴다 — bat 이 스크립트로 바로 부른다(동봉 파이썬은 스크립트 폴더를
sys.path 에 넣지 않으므로 형제 모듈을 import 하지 않는다).
"""
import io
import json
import os
import re
import socket
import sys
import time
import unicodedata

# ── 기본값(단일원) — 팀 표준 서버. 사용자 지시로 기본값은 그대로 두고 '바꾸는 길'만 연다. ──
DEFAULT_HOST = "10.115.147.68"
DEFAULT_PORT = 9310
FILE_NAME = "team_server.json"
LEGACY_KEY = "teamServerUrl"          # v4 이하 config.json 의 한 줄 주소 — 읽기만(이어받기) 한다
EDIT_BAT = "LoadMonitor24-팀서버주소.bat"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LABEL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
# 메신저·메일에서 복사한 주소에 섞여 오는 보이지 않는 글자(BOM·폭 없는 공백·단어 결합자)
_INVISIBLE = "﻿​‌‍⁠"


class Addr:
    """읽어 들인 팀 서버 주소 — source 는 값마다 어디서 왔는지('file'|'legacy'|'default')."""

    __slots__ = ("host", "port", "source", "warnings", "file")

    def __init__(self, host, port, source=None, warnings=None, file=""):
        self.host = host
        self.port = int(port)
        self.source = dict(source or {})
        self.warnings = list(warnings or [])
        self.file = file

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"

    def as_dict(self):
        return {"host": self.host, "port": self.port, "url": self.url,
                "source": dict(self.source), "warnings": list(self.warnings), "file": self.file,
                "default": {"host": DEFAULT_HOST, "port": DEFAULT_PORT}, "edit_bat": EDIT_BAT}


# ── 형식 검사 ─────────────────────────────────────────────────────────────────
def _norm(v):
    r"""입력 정리 — 전각 숫자·마침표(한글 입력기 전각 모드: １０．０．０．５)는 반각으로 펴고,
    복사에 딸려 온 보이지 않는 글자는 지운다. 그래도 남는 비 ASCII 글자는 검사 쪽이 거부한다
    (str.isdigit 은 다른 문자권 숫자도 참이라 그대로 두면 주소가 깨진 채 저장된다)."""
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
    r"""서버 IP — IPv4(예: 10.0.0.5) 또는 PC 이름(예: TEAM-PC, team-pc.corp.local).
    returns (정규화 값 | None, 오류 문구)"""
    s = _norm(h)
    if not s:
        return None, "서버 IP 가 비어 있습니다"
    if not s.isascii():
        return None, f"서버 IP 에는 영문·숫자·점·하이픈만 쓸 수 있습니다: {s[:60]}"
    if any(c.isspace() for c in s) or "/" in s or "\\" in s or "@" in s:
        return None, f"서버 IP 형식이 아닙니다: {s[:60]} — 예: 10.0.0.5 또는 PC 이름"
    if ":" in s:
        return None, ("서버 IP 칸에는 IP 만 적으세요(포트는 포트 칸에). "
                      "IPv6 주소는 지원하지 않습니다 — IPv4 주소나 PC 이름을 쓰세요")
    if s.replace(".", "").isdigit():
        return (s, "") if _ipv4(s) else (None, f"IPv4 주소 형식이 아닙니다: {s[:40]} — 예: 10.0.0.5")
    if len(s) > 253 or not all(_LABEL.match(x) for x in s.rstrip(".").split(".")):
        return None, f"PC 이름 형식이 아닙니다: {s[:60]}"
    return s, ""


def check_port(p):
    """포트 번호 1~65535 — returns (int | None, 오류 문구)"""
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
    return v, ""


def parse_url(u):
    r"""'http://IP:포트' 꼴 → (host, port|None). 형식이 아니면 None.
    bat 의 IP 칸에 주소를 통째로 붙여 넣은 경우와 v4 의 teamServerUrl 을 읽을 때 쓴다."""
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
    return host, port


def split_input(host, port=None):
    r"""bat 입력 정리 — IP 칸에 'http://IP:포트' 나 'IP:포트' 를 붙여 넣어도 나눠 받는다.
    returns (host|None, port|None, 오류 문구). 칸이 비면 None(바꾸지 않음). 포트 칸에 적은 값이 이긴다."""
    h = _norm(host)
    p = port
    if h and (":" in h or "/" in h):
        pu = parse_url(h)
        if pu is None:
            return None, None, f"서버 주소 형식이 아닙니다: {h[:60]} — 예: 10.0.0.5"
        h, up = pu
        if (p is None or str(p).strip() == "") and up:
            p = up
    hh = None
    if h:
        hh, err = check_host(h)
        if not hh:
            return None, None, err
    pp = None
    if p is not None and str(p).strip() != "":
        pp, err = check_port(p)
        if pp is None:
            return None, None, err
    return hh, pp, ""


# ── 읽기·쓰기 ─────────────────────────────────────────────────────────────────
def path(root=None):
    return os.path.join(root or ROOT, "config", FILE_NAME)


def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError, RecursionError):
        return None


def load(root=None):
    r"""지금 쓸 주소 — 값마다 파일 → 옛 teamServerUrl → 기본값 순."""
    root = root or ROOT
    warn = []
    src = {"host": "default", "port": "default"}
    host, port = DEFAULT_HOST, DEFAULT_PORT
    # 옛 설정(v4 이하 config.json 의 teamServerUrl)을 먼저 깔고, 따로 둔 파일이 그 위를 덮는다
    cfg = _read_json(os.path.join(root, "config", "config.json")) or {}
    legacy = str(cfg.get(LEGACY_KEY) or "").strip()
    if legacy:
        pu = parse_url(legacy)
        if pu is None:
            warn.append(f"config.json 의 옛 {LEGACY_KEY} 값이 주소 형식이 아니어서 무시했습니다")
        else:
            host, src["host"] = pu[0], "legacy"
            if pu[1]:
                port, src["port"] = pu[1], "legacy"
    fp = path(root)
    d = None
    if os.path.exists(fp):
        d = _read_json(fp)
        if d is None:
            warn.append(f"{FILE_NAME} 을 읽지 못했습니다(형식 오류) — 이전 값으로 동작합니다. "
                        f"{EDIT_BAT} 에서 주소를 다시 저장하면 고쳐집니다")
    if d:
        if "host" in d:
            v, err = check_host(d.get("host"))
            if v:
                host, src["host"] = v, "file"
            else:
                warn.append(f"{FILE_NAME} 의 host 무시 — {err}")
        if "port" in d:
            v, err = check_port(d.get("port"))
            if v is not None:
                port, src["port"] = v, "file"
            else:
                warn.append(f"{FILE_NAME} 의 port 무시 — {err}")
    return Addr(host, port, src, warn, fp if os.path.exists(fp) else "")


def url(root=None):
    return load(root).url


def _atomic_write(p, text):
    r"""쓰다 만 설정은 '주소가 사라졌다'로 읽힌다 — 임시 파일에 다 쓴 뒤 바꿔 끼운다.
    대상이 잠깐 잡혀 있으면(백신·동기화) 짧게 재시도한다."""
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


def save(root=None, host=None, port=None):
    r"""주소를 config\team_server.json 에 남긴다 — 준 값만 바꾸고 나머지는 지금 값 그대로.
    returns (ok, 오류 문구, Addr). 형식이 틀린 값은 저장하지 않는다(멀쩡하던 주소가 사라지지 않게)."""
    root = root or ROOT
    cur = load(root)
    h, p = cur.host, cur.port
    if host is not None:
        h, err = check_host(host)
        if not h:
            return False, err, cur
    if port is not None:
        p, err = check_port(port)
        if p is None:
            return False, err, cur
    doc = {
        "_설명": ("팀 서버 주소(LM24 v5). host = 팀 서버 PC 의 IP(또는 PC 이름), port = 포트. "
                 "팀원은 분석 후 http://host:port 로 올리고, 팀 서버는 이 포트로 열려 그 IP 로 들어온 자료를 취합한다. "
                 f"바꾸는 곳: {EDIT_BAT}. 설치 폴더 안의 파일이라 폴더를 옮기거나 나눠 주면 같은 주소가 따라간다. "
                 "이 파일을 지우면 기본 주소로 돌아간다."),
        "host": h, "port": int(p),
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        _atomic_write(path(root), json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        return False, f"{FILE_NAME} 을 쓰지 못했습니다({type(e).__name__}) — 파일이 열려 있거나 권한이 없습니다", cur
    return True, "", load(root)


def reset(root=None):
    r"""따로 둔 파일을 지운다 → 옛 teamServerUrl(있으면) 또는 기본값으로 돌아간다."""
    fp = path(root)
    try:
        if os.path.exists(fp):
            os.remove(fp)
        return True, ""
    except OSError as e:
        return False, f"{FILE_NAME} 을 지우지 못했습니다({type(e).__name__})"


# ── 이 PC 가 팀 서버인가 ─────────────────────────────────────────────────────
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
    r"""설정된 서버 주소가 이 PC 인가 — True/False. PC 이름이 이 PC 이름과 다르면 None(모름).
    DNS 는 묻지 않는다 — 느리고, 사내망 밖에서는 틀린 답을 준다."""
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
    r"""이 PC 와 설정된 서버 주소의 관계 — (종류, 문구). 종류: server | loopback | member | unknown.
    팀 서버 PC 는 '설정된 IP = 이 PC' 여야 팀원 업로드가 이 서버로 모인다."""
    ips = local_ipv4s() if ips is None else ips
    mine = ", ".join(ips) or "확인 못 함"
    if is_loopback(a.host):
        return "loopback", (f"{a.host} 는 이 PC 안에서만 닿는 주소입니다 — 팀원 PC 는 이 주소로 올릴 수 없습니다 "
                            f"(이 PC 의 IP: {mine})")
    loc = is_local(a.host, ips)
    if loc:
        return "server", "이 PC 의 주소입니다 — 이 PC 에서 팀 서버를 켜면 팀원이 이 주소로 올립니다"
    if loc is False:
        return "member", (f"다른 PC 의 주소입니다 — 이 PC 는 분석 후 이 주소로 올립니다 "
                          f"(이 PC 가 팀 서버라면 서버 IP 를 이 PC 의 IP 로 바꾸세요: {mine})")
    return "unknown", f"PC 이름이라 이 PC 인지 확인하지 않았습니다 (이 PC 의 IP: {mine})"


def describe(a, ips=None):
    """사람이 읽는 한 덩어리 — bat·CLI·자가점검 출력용."""
    where = {"file": FILE_NAME, "legacy": f"config.json 의 옛 {LEGACY_KEY}", "default": "기본값"}
    lines = [f"  서버 IP    : {a.host}   ({where[a.source['host']]})",
             f"  포트       : {a.port}   ({where[a.source['port']]})",
             f"  업로드 주소: {a.url}",
             f"  이 PC 와   : {relation(a, ips)[1]}"]
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
    if "--set-env" in argv:
        # bat(LoadMonitor24-팀서버주소.bat) 전용 — 사람이 입력한 값을 명령줄에 끼워 넣지 않고 환경변수로 받는다
        # ('&'·'"' 같은 문자가 섞여도 cmd 가 명령으로 해석하지 않게). 빈 값 = 그대로 둔다.
        env = {k: _norm(os.environ.get(v, "")) for k, v in (("host", "LM24_TA_HOST"), ("port", "LM24_TA_PORT"))}
        if not any(env.values()):
            a = load(root)
            return out(dict(a.as_dict(), ok=True, changed=False),
                       "[teamaddr] 바꾼 값이 없어 그대로 둡니다\n" + describe(a), 0)
        argv = ["--set"] + [x for k, flag in (("host", "--host"), ("port", "--port"))
                            if env[k] for x in (flag, env[k])] + (["--json"] if js else [])
    if "--set" in argv:
        host, port = _arg(argv, "--host"), _arg(argv, "--port")
        if host == "" or port == "":
            return out({"ok": False, "error": "값이 빠진 인자가 있습니다"},
                       f"[teamaddr] 값이 빠진 인자가 있습니다 — 예: --set --host 10.0.0.5 --port {DEFAULT_PORT}", 2)
        if host is None and port is None:
            return out({"ok": False, "error": "바꿀 값이 없습니다"},
                       "[teamaddr] 바꿀 값이 없습니다 — --host / --port 중 하나 이상", 2)
        if host is not None:
            h, p2, err = split_input(host, port)
            if err:
                return out({"ok": False, "error": err}, f"[teamaddr] 저장하지 않았습니다 — {err}", 1)
            host, port = h, (p2 if p2 is not None else port)
        ok, err, a = save(root, host=host, port=port)
        if not ok:
            return out({"ok": False, "error": err}, f"[teamaddr] 저장하지 않았습니다 — {err}", 1)
        return out(dict(a.as_dict(), ok=True, changed=True), "[teamaddr] 저장했습니다\n" + describe(a), 0)
    if "--reset" in argv:
        ok, err = reset(root)
        a = load(root)
        return out(dict(a.as_dict(), ok=ok, error=err),
                   ("[teamaddr] 따로 둔 주소 파일을 지웠습니다\n" if ok else f"[teamaddr] {err}\n") + describe(a),
                   0 if ok else 1)
    a = load(root)
    if "--url" in argv:
        return out({"ok": True, "url": a.url}, a.url, 0)
    return out(dict(a.as_dict(), ok=True), "[teamaddr] 지금 쓰는 팀 서버 주소\n" + describe(a), 0)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))
    sys.exit(main())
