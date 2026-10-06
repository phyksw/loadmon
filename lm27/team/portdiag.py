# -*- coding: utf-8 -*-
r"""포트 점유 진단과 대체 포트 제안(TAB §3.4 · X-276) — 오류 코드만으로 원인을 단정하지 않고 OS 사실로 판정한다.

    d = diagnose_port(9310, 10048, cfg, store_id=store.store_id)     # → PortDiag(kind, message, suggest, …)
    p = suggest_port(9310, cfg)                                       # 0 = 못 찾음("포트를 직접 입력하세요")

kind: ``lm27_same`` · ``lm27_other`` · ``lm24`` · ``other_lm`` · ``other_program`` · ``reserved`` · ``ephemeral`` · ``unknown``.

원칙(LM24 ui\app 포트 도우미 계승)
  · 리스너 = ``netstat -ano``(``-p TCP`` 금지 — IPv6 행이 빠진다), 데이터 행은 ascii 로 읽는다. 실패하면 PowerShell
    ``Get-NetTCPConnection``. **못 알아낸 것(None)과 아무도 없는 것([])을 구분한다.**
  · 프로세스 정보는 ``Get-CimInstance Win32_Process`` — 다른 계정이면 NULL 이라 '확인 불가'로 전한다(남의 것으로 단정 금지).
  · **남의 프로세스를 죽이지 않는다.** 포트를 몰래 바꾸지 않는다 — 제안만 한다(사람이 [대체 포트 N 으로 시작]).
  · 대체 포트는 임시(동적) 범위·예약 범위·별개 프로젝트·이전 판 대시보드·로컬 앱(설정값 + 실제 ui_server.json)·CDP 를 피한다.
  · ``SO_REUSEADDR`` 를 쓰지 않는다(덧바인드 성공 실측) — 빈 포트 확인은 ``SO_EXCLUSIVEADDRUSE`` 바인드.
외부 명령은 ``run`` 주입점으로 바꿔 끼울 수 있다(시험은 출력 모사만 — 실제 시스템 설정을 바꾸지 않는다).
"""
from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

from lm27.team import schema

# 피하는 포트 — 별개 프로젝트(D:\배포\LM26, 다른 도구) 개인·팀·데모 · 이전 판 대시보드 대역 · 이전 판 코파일럿 ·
# LM27 코파일럿 CDP(계약 §4.7). 숫자는 식으로 적는다(이 값들은 '쓰지 않을' 포트다 — L-28 은 쓰는 쪽을 막는다).
AVOID = frozenset(range(8765, 8768)) | frozenset(range(9148, 9168)) | {9333} | frozenset(range(9343, 9354))   # L-28 예외(C22)
NETSH_TIMEOUT = 25
PS_TIMEOUT = 40
_CACHE: dict = {}


def clear_cache() -> None:
    """netsh 결과 캐시(재부팅 전에는 거의 안 바뀐다) 비우기 — 시험용."""
    _CACHE.clear()


def _sys(name: str) -> str:
    from lm27.util.proc import _system_exe
    return _system_exe(name)


def _ps_exe() -> str:
    return os.path.join(os.path.dirname(_sys("cmd.exe")), "WindowsPowerShell", "v1.0", "powershell.exe")


def _default_run(argv, timeout):
    """(rc, stdout 바이트) — 실행 자체가 실패하면 None."""
    from lm27.util.proc import run_child
    try:
        r = run_child(argv, timeout_s=timeout)
    except OSError:
        return None
    if r.timed_out:
        return None
    return r.rc, r.stdout


def winerror_of(e: BaseException) -> int:
    return int(getattr(e, "winerror", 0) or getattr(e, "errno", 0) or 0)


# ───────────────────────────── OS 사실 ─────────────────────────────
def listeners(port: int, *, run=None) -> list[int] | None:
    """그 포트를 LISTENING 으로 쥔 pid 전부(IPv4·IPv6). 알아내지 못했으면 None."""
    run = run or _default_run
    r = run([_sys("netstat.exe"), "-ano"], NETSH_TIMEOUT)
    if r is not None and r[0] == 0 and r[1].strip():
        out = []
        for ln in r[1].decode("ascii", "replace").splitlines():
            f = ln.split()
            if len(f) >= 5 and f[0].upper() == "TCP" and f[3].upper() == "LISTENING" \
                    and f[1].rsplit(":", 1)[-1] == str(int(port)):
                try:
                    pid = int(f[4])
                except ValueError:
                    continue
                if pid not in out:
                    out.append(pid)
        return out
    r = run([_ps_exe(), "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue).OwningProcess"],
            PS_TIMEOUT)
    if r is None or r[0] != 0:
        return None
    out = []
    for tok in r[1].decode("utf-8", "replace").split():
        if tok.isdigit() and int(tok) not in out:
            out.append(int(tok))
    return out


def proc_info(pids, *, run=None) -> list[dict]:
    """pid → {pid, name, exe, readable}. 다른 계정이면 이름·경로가 없어 ``readable=False``('확인 불가')."""
    pids = [int(x) for x in pids or () if x]
    if not pids:
        return []
    run = run or _default_run
    filt = " or ".join(f"ProcessId={x}" for x in pids)
    cmd = (f"@(Get-CimInstance Win32_Process -Filter '{filt}' -ErrorAction SilentlyContinue | ForEach-Object "
           "{ [PSCustomObject]@{ ProcessId=$_.ProcessId; Name=$_.Name; ExecutablePath=$_.ExecutablePath } }) "
           "| ConvertTo-Json -Compress")
    r = run([_ps_exe(), "-NoProfile", "-NonInteractive", "-Command", cmd], PS_TIMEOUT)
    seen = {}
    if r is not None and r[0] == 0:
        try:
            o = json.loads(r[1].decode("utf-8", "replace").strip() or "[]")
        except ValueError:
            o = []
        for x in [o] if isinstance(o, dict) else o if isinstance(o, list) else []:
            if isinstance(x, dict) and str(x.get("ProcessId") or "").isdigit():
                seen[int(x["ProcessId"])] = x
    out = []
    for pid in pids:
        x = seen.get(pid) or {}
        name, exe = str(x.get("Name") or ""), str(x.get("ExecutablePath") or "")
        out.append({"pid": pid, "name": name or "(확인 불가)", "exe": exe or "확인 불가", "readable": bool(name and exe)})
    return out


def reserved_ranges(*, run=None) -> list[tuple[int, int]]:
    """윈도우 예약(제외) TCP 포트 구간 — 프로세스마다 한 번(캐시)."""
    if "rsv" not in _CACHE:
        r = (run or _default_run)([_sys("netsh.exe"), "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
                                  NETSH_TIMEOUT)
        txt = r[1].decode("cp949", "replace") if r is not None and r[0] == 0 else ""
        _CACHE["rsv"] = [(int(a), int(b)) for a, b in re.findall(r"^\s*(\d+)\s+(\d+)", txt, re.M) if int(a) <= int(b)]
    return _CACHE["rsv"]


def reserved_range_of(port: int, *, run=None) -> str:
    for a, b in reserved_ranges(run=run):
        if a <= int(port) <= b:
            return f"{a}~{b}"
    return ""


def dynamic_range(*, run=None) -> tuple[int, int]:
    """임시(동적) 포트 범위 (시작, 끝) — 못 읽으면 (0, 0). 이 PC 실측 1024~15000(9310 포함, TAB §3.4)."""
    if "dyn" not in _CACHE:
        r = (run or _default_run)([_sys("netsh.exe"), "interface", "ipv4", "show", "dynamicport", "tcp"], NETSH_TIMEOUT)
        txt = r[1].decode("cp949", "replace") if r is not None and r[0] == 0 else ""
        nums = [int(x) for x in re.findall(r":\s*(\d+)", txt)]
        _CACHE["dyn"] = (nums[0], nums[0] + nums[1] - 1) if len(nums) >= 2 and nums[1] > 0 else (0, 0)
    return _CACHE["dyn"]


def bind_test(port: int) -> bool:
    """정말 빈 포트인가 — 0.0.0.0·127.0.0.1 둘 다 ``SO_EXCLUSIVEADDRUSE`` 로 바인드해 보고 즉시 닫는다."""
    for host in ("0.0.0.0", "127.0.0.1"):
        so = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                so.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            so.bind((host, int(port)))
        except OSError:
            return False
        finally:
            so.close()
    return True


def _get_json(url: str, timeout: float):
    """(HTTP 코드, JSON 객체 또는 None, 프록시 표식). 연결 실패면 (None, None, 종류)."""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # 시스템 프록시를 타지 않는다
    try:
        with op.open(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
            body, code, hdr = r.read(65536), r.status, r.headers
    except urllib.error.HTTPError as e:
        body, code, hdr = e.read(65536), e.code, e.headers
    except TimeoutError:
        return None, None, "timeout"
    except ConnectionRefusedError:
        return None, None, "refused"
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            return None, None, "timeout"
        if isinstance(reason, ConnectionRefusedError):
            return None, None, "refused"
        if isinstance(reason, socket.gaierror):
            return None, None, "dns"
        return None, None, "refused"
    try:
        obj = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        obj = None
    proxy = any(h.lower() in ("via", "proxy-connection", "proxy-agent") for h in (hdr.keys() if hdr else ()))
    return code, obj if isinstance(obj, dict) else None, ("proxy" if proxy else "")


def probe_identity(port: int, *, host: str = "127.0.0.1", timeout: float = 2.0) -> dict:
    """그 포트에 무엇이 답하는가 — TAB §2.9 판정표(``schema.judge_hello``). LM24 응답 본문은 모양만 보고 버린다.
    반환 {result, store_id?, instance_id?, name?} — 경로·pid·토큰은 담지 않는다."""
    base = f"http://{host}:{int(port)}"
    code, obj, note = _get_json(base + "/api/hello", timeout)
    if code is None:
        return {"result": schema.judge_hello(None, error=note)}
    whoami = team = None
    if code == 404:
        _c, w, _n = _get_json(base + "/api/whoami", timeout)
        whoami = {"root": True} if isinstance(w, dict) and "root" in w else None
        if whoami is None:
            _c, t, _n = _get_json(base + "/api/team", timeout)
            team = {k: True for k in ("members", "uploads", "agg_note") if isinstance(t, dict) and k in t} or None
            if team and "members" in team:
                team["members"] = []
    res = schema.judge_hello(code, obj, whoami=whoami, team=team, proxy=note == "proxy")
    out = {"result": res}
    if res in ("ok", "wrong_major") and isinstance(obj, dict):
        for k in ("store_id", "instance_id", "name", "version"):
            if isinstance(obj.get(k), str):
                out[k] = obj[k][:60]
    elif res == "other_lm" and isinstance(obj, dict) and isinstance(obj.get("app"), str):
        out["app"] = obj["app"][:30]
    return out


# ───────────────────────────── 판정·제안 ─────────────────────────────
@dataclass
class PortDiag:
    kind: str
    code: int
    port: int
    listeners: list | None = None
    procs: list = field(default_factory=list)
    ident: dict = field(default_factory=dict)
    reserved: str = ""
    dynamic: tuple = (0, 0)
    suggest: int = 0
    message: str = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["dynamic"] = list(self.dynamic)
        return d


def classify(lis, procs, ident, rsv, dyn, port, *, store_id=None) -> str:
    res = (ident or {}).get("result")
    if res in ("ok", "wrong_major"):
        return "lm27_same" if store_id and ident.get("store_id") == store_id else "lm27_other"
    if res == "lm24":
        return "lm24"
    if res == "other_lm":
        return "other_lm"
    if lis is None:
        return "unknown"
    if lis:
        return "other_program"
    if rsv:
        return "reserved"
    lo, hi = dyn
    if lo and lo <= int(port) <= hi:
        return "ephemeral"
    return "unknown"


def _proc_text(procs) -> str:
    if not procs:
        return "프로세스 확인 불가"
    p = procs[0]
    where = p.get("exe") if p.get("readable") else "확인 불가"
    return f"{p.get('name')}, pid {p.get('pid')}, {where}"


def message_ko(d: PortDiag) -> str:
    """콘솔·화면 문구(요지는 TAB §3.4 표). 대체 포트 안내 포함."""
    alt = (f" 대체 포트 {d.suggest} 로 시작할 수 있습니다(명령줄: --port {d.suggest})." if d.suggest
           else " 비어 있는 대체 포트를 찾지 못했습니다 — 포트를 직접 입력하세요.")
    code = f"(WinError {d.code}) " if d.code else ""
    k = d.kind
    if k == "lm27_same":
        pid = (d.listeners or ["?"])[0]
        return f"{code}이 저장소의 LM27 팀 서버가 이미 실행 중입니다(pid {pid}). 새로 띄울 필요가 없습니다."
    if k == "lm27_other":
        nm = d.ident.get("name") or "이름 없음"
        return f"{code}다른 저장소의 LM27 팀 서버({nm})가 포트 {d.port} 를 쓰고 있습니다." + alt
    if k == "lm24":
        return (f"{code}이전 판(LM24) 팀 서버가 {d.port} 를 쓰고 있습니다({_proc_text(d.procs)}). 두 서버가 같은 포트를 쓸 수 "
                "없습니다. LM27 은 대체 포트로 열고, 팀원 설정의 포트(또는 대체 주소)를 그 번호로 바꾸세요." + alt)
    if k == "other_lm":
        return f"{code}다른 판({d.ident.get('app', 'LM')})의 팀 서버가 포트 {d.port} 를 쓰고 있습니다." + alt
    if k == "other_program":
        return f"{code}다른 프로그램({_proc_text(d.procs)})이 포트 {d.port} 를 쓰고 있습니다. 그 프로그램은 끄지 않습니다." + alt
    if k == "reserved":
        return f"{code}윈도우가 {d.reserved} 포트를 예약해 두었습니다." + alt
    if k == "ephemeral":
        lo, hi = d.dynamic
        return (f"{code}다른 프로그램의 바깥 연결이 이 번호를 잠깐 쓰고 있습니다(임시 포트 범위 {lo}~{hi}). 잠시 뒤 다시 "
                "시도하거나 범위 밖 포트를 쓰세요. 임시 범위 변경·예약 추가는 관리자 권한이라 LM27 은 하지 않습니다"
                "(IT 에 요청할 수 있는 내용)." + alt)
    return f"{code}포트 {d.port} 를 누가 쓰는지 알아내지 못했습니다(조회 차단)." + alt


def _ui_ports(cfg) -> set[int]:
    """로컬 앱 포트 — 설정 ``ui.port``(+ 대체 수) 와 실제 ``ui_server.json`` 의 포트 둘 다(X-276)."""
    out = set()
    try:
        base, n = int(cfg["ui.port"]), int(cfg["ui.portFallbackCount"])
        out |= set(range(base, base + n + 1))
    except (KeyError, TypeError, ValueError):
        pass
    from lm27.paths import Paths
    from lm27.util import fsx
    info = fsx.read_json(Paths().ui_server_json(), None)
    if isinstance(info, dict) and isinstance(info.get("port"), int):
        out.add(info["port"])
    return out


def suggest_port(cur: int, cfg, *, run=None, bind=None, extra_avoid=()) -> int:
    """``teamServer.suggestRanges`` 를 앞 구간부터 — 현재·회피·임시 범위·예약 범위를 건너뛰고 바인드 시험 통과한 첫 포트.
    못 찾으면 0."""
    lo, hi = dynamic_range(run=run)
    avoid = set(AVOID) | _ui_ports(cfg) | set(extra_avoid)
    bind = bind or bind_test
    for rng in cfg["teamServer.suggestRanges"]:
        a, b = int(rng[0]), int(rng[1])
        for p in range(a, b + 1):
            if p == int(cur) or p in avoid or (lo and lo <= p <= hi) or reserved_range_of(p, run=run):
                continue
            if bind(p):
                return p
    return 0


def diagnose_port(port: int, code: int, cfg, *, store_id: str | None = None, run=None, ident=None,
                  bind=None) -> PortDiag:
    """바인드 실패 원인 판정(TAB §3.4). ``ident`` 를 주지 않으면 127.0.0.1 로 hello 판정을 해 본다."""
    lis = listeners(port, run=run)
    procs = proc_info(lis or [], run=run)
    ident = ident if ident is not None else probe_identity(port)
    rsv = reserved_range_of(port, run=run)
    dyn = dynamic_range(run=run)
    kind = classify(lis, procs, ident, rsv, dyn, port, store_id=store_id)
    d = PortDiag(kind=kind, code=int(code or 0), port=int(port), listeners=lis, procs=procs, ident=dict(ident or {}),
                 reserved=rsv, dynamic=dyn)
    d.suggest = 0 if kind == "lm27_same" else suggest_port(port, cfg, run=run, bind=bind)
    d.message = message_ko(d)
    return d
