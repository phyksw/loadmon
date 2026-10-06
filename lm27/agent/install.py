# -*- coding: utf-8 -*-
r"""에이전트 설치·판 올림·작업 등록·생존 판정·자동 복구·제거(계약 §2.4 · §1.3 · §3.9 · §7.1 · X-026~X-029 · X-303 · X-305 ·
O-16, TAB §1.6.1~§1.6.6, CP §1.3~§1.6). 프로그램 폴더(ROOT)에서만 돈다 — 에이전트 bin 사본에는 넣지 않는다(설치 코드는
ROOT 설정 ``lm27.config`` 를 읽으므로 '사본 모듈은 사본 안 모듈만 import' 원칙과 맞지 않는다 — 계약 §1.3).

``ensure_agent(ident)`` — [수집]·화면 기동·설치 전용 진입점(``agent install --only``)이 부른다. 사용자에게 묻지 않는다:
  1. bin 사본(계약 §1.3 목록 — ``py311\``·``lm27\{__init__, paths, catalog, util\, privacy\, store\, agent\(실행 모듈),
     normalize\{__init__, cues}, bundle\{__init__, ids}}``·``lm27_pipe.py``·``agent_main.py``(원본 ``lm27\agent\main.py``, CR-04)·
     ``ps\``(agent.ps1·harvest.ps1·수확 수집기 5개)). 판 = ``LM27_VERSION`` + ``-`` + 사본 내용 해시 앞 8자 — 같은 판이면 sha256
     대조만(다른 바이트만 다시), 새 판이면 ``bin\<새 판>\`` 에 복사 → 작업 재등록(Action 교체) → 옛 에이전트 정지 → 새 판 기동,
     옛 판은 2판까지만 보관. 새로 복사하기 전에 정제 회귀 말뭉치(``run_selftest(perf=False)``)가 통과해야 한다(P §18.3 — 실패하면
     설치 거부).
  2. 키링(없으면 생성 — P §9.5) → 하위 키(``write_agent_subkeys``, 주 키 없음 — P §9.4) → 정제 문맥 사본
     (``refresh_context_cache`` — 해시 = config_hash) → ``agent_config.json``(``Cfg.agent_subset()`` + config_hash — X-303).
  3. 구현 고르기(처음·판 바뀜·none 일 때): ``agent.impl``(auto = py → ps) 순서로 자기 시험(``-TestSamples 3``)을 돌려 통과한 것,
     둘 다 실패면 ``impl=none`` + R-CLM 또는 R-APPLOCKER(X-029 — rc 3, 작업 등록 안 함).
  4. ``agent.json``(``lm27.agent/1`` — install_id 유지, ``prior_install_ids``) → 생존 판정 → 등록(``Register-Agent.ps1``)·
     (재)기동(정지 깃발 → 15초 → 그 pid 만 kill_tree → ``schtasks /Run``) → heartbeat·store 신선 확인(최대 60초).
  반환 dict ``rc``: 0 설치·복구함 · 4 이미 정상(바뀐 것 없음) · 2 작업 등록·기동 실패 · 3 두 구현 자기 시험 실패(impl none) ·
  1 내부 오류(사본 원천 없음·회귀 말뭉치 실패).

``agent_health(ident)`` = 생존 네 조건(TAB §1.6.5 — 작업 등록 · Action 이 이 설치의 사본 · heartbeat 신선 · store 신선) + ``healthy``.
``request_harvest_now(ident, wait_s)`` = ``run\harvest_now.flag`` → ``harvest_done.json`` 이 깃발 뒤에 시작된 수확으로 바뀌기를 기다림.
``uninstall(ident, purge)`` = 정지 + 작업 삭제 + 하위 키·문맥 사본·bin 삭제(store 는 남김). ``purge`` 면 로컬 원장
(``lm27.store.purge_store``)·감사(``lm27.privacy.audit.purge_audit``)·운영 파일까지(L-11 — store 경로를 직접 쓰지 않는다, O-16).

실기계 조작(작업 스케줄러·뮤텍스·프로세스·자기 시험 실행)은 ``SystemOps`` 한 곳 — 시험은 같은 메서드의 가짜를 ``ops=`` 로 넣는다
(실제 작업 등록·레지스트리 쓰기 0).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27 import LM27_VERSION
from lm27.paths import Paths
from lm27.util import fsx, proc

__all__ = [
    "AGENT_SCHEMA", "AGENTCFG_SCHEMA", "SystemOps", "agent_entry", "agent_health", "bin_files", "build_ver",
    "ensure_agent", "install_bin", "register_task", "request_harvest_now", "self_test_impl", "stop_agent",
    "task_name", "uninstall", "write_agent_config",
]

AGENT_SCHEMA = "lm27.agent/1"
AGENTCFG_SCHEMA = "lm27.agentcfg/1"
INSTALL_ID_RX = re.compile(r"^[0-9a-f]{32}$")
VER_RX = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$")
KEEP_BINS = 2
HB_WAIT_S = 60.0                 # 기동 뒤 heartbeat·store 신선을 기다리는 상한(TAB §1.6.5)
STOP_WAIT_S = 15.0               # 정지 깃발 뒤 기다림(TAB §1.6.5)
ALIVE_GRACE_S = 10.0             # 뮤텍스는 있는데 heartbeat 가 낡았을 때(절전 복귀 직후) 더 기다려 보는 시간
SELFTEST_TIMEOUT_S = 60.0
TASK_TIMEOUT_S = 60.0
PRIOR_MAX = 10
REASONS_IMPL = ("R-CLM", "R-APPLOCKER")
AGENT_MODULES = ("__init__.py", "main.py", "sampler.py", "harvest.py", "exemeta.py")   # 사본에 드는 실행 모듈
PS_FILES = (("ps/agent.ps1", "agent/agent.ps1"), ("ps/harvest.ps1", "agent/harvest.ps1"),
            ("ps/Get-EventActivity.ps1", "Get-EventActivity.ps1"), ("ps/Get-FileActivity.ps1", "Get-FileActivity.ps1"),
            ("ps/Get-OfficeMru.ps1", "Get-OfficeMru.ps1"), ("ps/Get-RecentFiles.ps1", "Get-RecentFiles.ps1"),
            ("ps/Get-TeamsWindow.ps1", "Get-TeamsWindow.ps1"))
OPTIONAL = frozenset({"lm27/normalize/cues.py"})          # 정제 훅(WP-18) — 아직 없으면 act_cues 가 빈다(records 가 find_spec 으로 확인)
COPY_EXT = (".py", ".json", ".jsonl")


def task_name(install_id: str) -> str:
    return f"LM27-{install_id}"


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bin_paths(paths: Paths, ver: str) -> Paths:
    """사본 폴더의 Paths(에이전트 모드, LAD 는 같은 곳)."""
    return Paths(paths.agent_bin(ver), lad=paths.lad())


# ───────────────────────────── bin 사본(계약 §1.3) ─────────────────────────────
def _walk_pkg(pkg: Path, rel: str) -> list:
    out = []
    for dp, dn, fns in os.walk(pkg):
        dn[:] = sorted(d for d in dn if d != "__pycache__" and not d.startswith("."))
        for fn in sorted(fns):
            if fn.endswith(COPY_EXT):
                p = Path(dp) / fn
                out.append((rel + "/" + p.relative_to(pkg).as_posix(), p))
    return out


def bin_files(paths: Paths) -> tuple[list, list]:
    """사본 목록 [(사본 상대 경로 '/', 원본 절대 경로)](정렬)와 없는 필수 원본 목록. 원본 = 프로그램 폴더(ROOT)."""
    pkg = paths.package_dir()
    items = []
    pyd = paths.python_dir()
    if pyd.is_dir():
        items += [("py311/" + f.name, f) for f in sorted(pyd.iterdir()) if f.is_file()]
    items += [("lm27/" + n, pkg / n) for n in ("__init__.py", "paths.py", "catalog.py")]
    for sub in ("util", "privacy", "store"):
        items += _walk_pkg(pkg / sub, "lm27/" + sub)
    items += [("lm27/agent/" + n, pkg / "agent" / n) for n in AGENT_MODULES]
    items += [("lm27/normalize/__init__.py", pkg / "normalize" / "__init__.py"),
              ("lm27/normalize/cues.py", pkg / "normalize" / "cues.py"),
              ("lm27/bundle/__init__.py", pkg / "bundle" / "__init__.py"), ("lm27/bundle/ids.py", pkg / "bundle" / "ids.py"),
              ("lm27_pipe.py", paths.pipe_script()), ("agent_main.py", pkg / "agent" / "main.py")]
    items += [(dst, paths.collect_script(src)) for dst, src in PS_FILES]
    missing = sorted(rel for rel, p in items if not p.is_file() and rel not in OPTIONAL)
    if not any(rel.startswith("py311/") for rel, _p in items):
        missing.append("py311/")
    items = sorted((rel, p) for rel, p in items if p.is_file())
    return items, missing


def build_ver(files) -> str:
    """판 = ``LM27_VERSION-<사본 내용 해시 앞 8자>``(같은 내용 = 같은 판 — 바뀌면 새 폴더에 복사해 실행 중 파일과 부딪히지 않는다)."""
    h = hashlib.sha256()
    for rel, p, *rest in files:
        sha = rest[0] if rest else _sha(fsx.read_bytes(p))
        h.update(f"{rel}\t{sha}\n".encode())
    return f"{LM27_VERSION}-{h.hexdigest()[:8]}"


def _hashed(files) -> list:
    return [(rel, p, _sha(fsx.read_bytes(p))) for rel, p in files]


def _dest(bin_dir: Path, rel: str) -> Path:
    return bin_dir.joinpath(*rel.split("/"))


def bin_diff(bin_dir: Path, hashed) -> list:
    """사본에서 원본과 바이트가 다른(또는 없는) 상대 경로."""
    out = []
    for rel, _p, sha in hashed:
        d = _dest(bin_dir, rel)
        try:
            if d.is_file() and _sha(fsx.read_bytes(d)) == sha:
                continue
        except OSError:
            pass
        out.append(rel)
    return out


def install_bin(paths: Paths, hashed, ver: str, only=None) -> list:
    """사본 복사(파일마다 ``fsx.atomic_write`` — 반쪽 파일 없음). ``only`` = 이 상대 경로만. 복사한 상대 경로 목록."""
    bin_dir = paths.agent_bin(ver)
    done = []
    for rel, p, sha in hashed:
        if only is not None and rel not in only:
            continue
        data = fsx.read_bytes(p)
        if _sha(data) != sha:
            raise OSError("bin 원본이 복사 중에 바뀌었습니다")
        fsx.atomic_write(_dest(bin_dir, rel), data)
        done.append(rel)
    return done


def prune_bins(paths: Paths, keep) -> list:
    """``bin\\`` 아래 keep 밖의 판 폴더를 지운다(쓰는 중이면 다음 기회로). 지운 판 목록."""
    root = paths.agent_bin_root()
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if d.is_dir() and d.name not in keep and VER_RX.match(d.name):
            shutil.rmtree(fsx.longp(d), ignore_errors=True)
            if not d.exists():
                out.append(d.name)
    return out


# ───────────────────────────── 작업 Action ─────────────────────────────
def agent_entry(paths: Paths, ver: str, impl: str, install_id: str) -> dict:
    """작업 Action(계약 §1.3): py = 사본 ``pythonw.exe`` + ``agent_main.py``, ps = ``powershell.exe`` + ``ps\\agent.ps1``.
    작업 폴더 = ``agent\\``(프로그램 폴더가 아니다 — L-15·TAB §1.6.4 ★)."""
    b = _bin_paths(paths, ver)
    if impl == "ps":
        from lm27.agent.harvest import powershell_exe
        return {"command": powershell_exe(),
                "arguments": f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{b.collect_script("agent.ps1")}" '
                             f"-InstallId {install_id}",
                "script": str(b.collect_script("agent.ps1")), "workdir": str(paths.agent_dir())}
    return {"command": str(b.pythonw_exe()),
            "arguments": f'-X utf8 -I -B "{b.agent_main_script()}" --install-id {install_id}',
            "script": str(b.agent_main_script()), "workdir": str(paths.agent_dir())}


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p or "").strip().strip('"')))


def _flat(s) -> str:
    return str(s or "").replace('"', "").replace("/", "\\").lower()


def same_action(task: dict | None, want: dict, install_id: str) -> bool:
    """등록된 Action 이 이 설치의 사본을 가리키는가(실행 파일·스크립트·install_id·작업 폴더)."""
    if not task:
        return False
    args = str(task.get("arguments") or "")
    return (_norm(task.get("command")) == _norm(want["command"]) and _flat(want["script"]) in _flat(args)
            and install_id in args and _norm(task.get("workdir")) == _norm(want["workdir"]))


# ───────────────────────────── 실기계 조작 ─────────────────────────────
def _system_exe(name: str) -> str:
    sysroot = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(sysroot, "System32", name)


class SystemOps:
    """작업 스케줄러·뮤텍스·프로세스·자식 실행. 시험은 같은 이름의 메서드를 가진 가짜를 쓴다(실등록 0)."""

    def __init__(self, paths: Paths):
        self.paths = paths

    def now(self) -> datetime:
        return _now()

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def run(self, argv, timeout_s: float, cwd=None):
        c = cwd if cwd and os.path.isdir(cwd) else None
        return proc.run_child(argv, timeout_s=timeout_s, cwd=c)

    def _cwd(self):
        d = self.paths.agent_dir()
        return str(d) if d.is_dir() else None

    def query_task(self, name: str) -> dict | None:
        """``schtasks /Query /XML``(읽기) → {command, arguments, workdir} · 없으면 None."""
        import xml.etree.ElementTree as ET
        r = self.run([_system_exe("schtasks.exe"), "/Query", "/TN", name, "/XML"], 30, self._cwd())
        if r.timed_out or r.rc != 0 or not r.stdout:
            return None
        try:
            text = r.stdout.decode("oem", errors="replace")
        except LookupError:
            text = r.stdout.decode("utf-8", errors="replace")
        text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("\ufeff"))
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        ex = root.find(".//t:Actions/t:Exec", ns)
        if ex is None:
            return {"command": "", "arguments": "", "workdir": ""}
        g = lambda tag: (ex.findtext("t:" + tag, default="", namespaces=ns) or "").strip()   # noqa: E731
        return {"command": g("Command"), "arguments": g("Arguments"), "workdir": g("WorkingDirectory")}

    def _register_script(self, args) -> int:
        from lm27.agent.harvest import powershell_exe
        script = str(self.paths.collect_script("agent/Register-Agent.ps1"))
        r = self.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script,
                      *args], TASK_TIMEOUT_S, self._cwd())
        return 1 if r.timed_out or r.rc is None else int(r.rc)

    def register(self, install_id: str, ver: str, impl: str, *, no_start: bool = True) -> int:
        return self._register_script(["-InstallId", install_id, "-AgentVer", ver, "-Impl", impl]
                                     + (["-NoStart"] if no_start else []))

    def remove(self, install_id: str) -> int:
        return self._register_script(["-InstallId", install_id, "-Remove"])

    def run_task(self, name: str) -> bool:
        r = self.run([_system_exe("schtasks.exe"), "/Run", "/TN", name], 30, self._cwd())
        return not r.timed_out and r.rc == 0

    def mutex_exists(self, install_id: str) -> bool:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenMutexW.restype = wintypes.HANDLE
        k.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        from lm27.agent.main import mutex_name
        h = k.OpenMutexW(0x00100000, False, mutex_name(install_id))          # SYNCHRONIZE
        if h:
            k.CloseHandle(h)
            return True
        return ctypes.get_last_error() == 5                                  # 접근 거부 = 있음

    def pid_alive(self, pid: int) -> bool:
        return proc.pid_alive(pid)

    def kill_tree(self, pid: int) -> bool:
        return proc.kill_tree(pid)

    def image_path(self, pid: int) -> str:
        from lm27.agent.sampler import WinApi
        return WinApi().image_path(pid)


# ───────────────────────────── 파일 ─────────────────────────────
def _read(path) -> dict:
    obj = fsx.read_json(path, default={})
    return obj if isinstance(obj, dict) else {}


def _write_json(path, obj) -> bool:
    """내용이 같으면 쓰지 않는다. 바뀌었으면 True."""
    if _read(path) == obj:
        return False
    fsx.atomic_write(path, fsx.canon_bytes(obj) + b"\n")
    return True


def _remove(path) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def write_agent_config(paths: Paths, cfg, config_hash: str | None) -> bool:
    """``agent_config.json``(``lm27.agentcfg/1``) = ``Cfg.agent_subset()``(키 이름순 값) + 정제 설정 해시(X-303 · 계약 §5.1-8).
    바뀌었으면 True."""
    obj = {"schema": AGENTCFG_SCHEMA, **cfg.agent_subset()}
    if config_hash:
        obj["config_hash"] = config_hash
    return _write_json(paths.agent_config(), obj)


# ───────────────────────────── 생존 판정 ─────────────────────────────
def _stale_s(cfg) -> int:
    v = cfg["agent.heartbeatStaleSec"] if cfg is not None else 600
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 600


def _store_age(paths: Paths, pc_id: str, now: datetime):
    """pc.sampler 로컬 원장 마지막 쓰기(플러시)로부터 지난 초. 없으면 None. 경로는 ``lm27.store`` 가 안다(L-11)."""
    from lm27.store import store_files
    files = store_files(paths, pc_id, "pc_session", "pc.sampler")
    if not files:
        return None
    try:
        mt = max(os.stat(f[1]).st_mtime for f in files[-2:])
    except OSError:
        return None
    return max(0.0, now.timestamp() - mt)


def _freshness(ident, paths: Paths, stale: int, now: datetime) -> dict:
    """heartbeat·store 신선도와 그에 따른 사유(작업 조회 없이 — 기다리는 동안 매초 부른다)."""
    hb = _read(paths.heartbeat())
    last = _parse_utc(hb.get("last_tick")) if hb.get("install_id") == ident.install_id else None
    hb_fresh = last is not None and (now - last).total_seconds() <= stale
    age = _store_age(paths, ident.pc_id, now)
    store_fresh = age is not None and age <= stale
    reasons = []
    started = _parse_utc(hb.get("started_at"))
    if hb_fresh and not store_fresh and started is not None and (now - started).total_seconds() > stale:
        reasons.append("R-SAMPLER-ZOMBIE")
    le = hb.get("last_error") if hb_fresh else None
    if le in ("R-RULESMISMATCH", "R-NOKEY"):
        reasons.append(le)
    return {"hb_fresh": hb_fresh, "store_fresh": store_fresh, "reasons": reasons,
            "last_tick": hb.get("last_tick") if last is not None else None}


def agent_health(ident, *, paths: Paths | None = None, cfg=None, ops=None) -> dict:
    """생존 네 조건(TAB §1.6.5): ``registered``(작업 ``LM27-<install_id>``) · ``action_ok``(Action 이 이 설치의 사본) ·
    ``hb_fresh``(heartbeat 의 install_id 같고 ``agent.heartbeatStaleSec`` 안) · ``store_fresh``(pc.sampler 원장 쓰기가 같은
    시간 안) → ``healthy``. 덧붙임: ``impl``·``agent_ver``·``reasons``(R-SAMPLER-ZOMBIE — 뮤텍스는 쥐었는데 쓰지 않음, heartbeat 의
    R-RULESMISMATCH·R-NOKEY, impl none 의 R-CLM·R-APPLOCKER)·``last_tick``."""
    paths = paths or Paths()
    if cfg is None:
        from lm27.config import load_config                          # 프로그램 폴더 전용(이 모듈은 사본에 없다)
        cfg = load_config(paths)
    ops = ops or SystemOps(paths)
    aj = _read(paths.agent_json())
    ver = aj.get("agent_ver") if aj.get("install_id") == ident.install_id else None
    impl = aj.get("impl") if aj.get("install_id") == ident.install_id else None
    t = ops.query_task(task_name(ident.install_id))
    registered = t is not None
    action_ok = bool(registered and isinstance(ver, str) and VER_RX.match(ver) and impl in ("py", "ps")
                     and same_action(t, agent_entry(paths, ver, impl, ident.install_id), ident.install_id))
    f = _freshness(ident, paths, _stale_s(cfg), ops.now())
    reasons = list(f["reasons"])
    if impl == "none":
        reasons += [r for r in aj.get("impl_reasons") or () if r in REASONS_IMPL]
    return {"registered": registered, "action_ok": action_ok, "hb_fresh": f["hb_fresh"], "store_fresh": f["store_fresh"],
            "healthy": registered and action_ok and f["hb_fresh"] and f["store_fresh"], "impl": impl, "agent_ver": ver,
            "reasons": sorted(set(reasons)), "last_tick": f["last_tick"]}


# ───────────────────────────── 정지·기동 ─────────────────────────────
def _ours(paths: Paths, image: str) -> bool:
    """그 pid 의 실행 파일이 이 에이전트 사본(또는 ps 구현의 powershell)인가 — 남의 프로세스를 끄지 않는다."""
    img = _norm(image)
    if not img:
        return False
    root = _norm(paths.agent_bin_root())
    return img.startswith(root + os.sep) or os.path.basename(img) == "powershell.exe"


def stop_agent(paths: Paths, install_id: str, ops, wait_s: float = STOP_WAIT_S) -> bool:
    """정지 깃발 → wait_s 동안 뮤텍스가 사라지기를 → 남았으면 heartbeat.pid(이 사본의 프로세스일 때만) kill_tree. 깃발은 지운다.
    정지했거나 처음부터 없었으면 True."""
    if not ops.mutex_exists(install_id):
        return True
    flag = paths.stop_flag()
    fsx.atomic_write(flag, b"")
    try:
        end = ops.now() + timedelta(seconds=wait_s)
        while ops.mutex_exists(install_id) and ops.now() < end:
            ops.sleep(0.5)
        if ops.mutex_exists(install_id):
            hb = _read(paths.heartbeat())
            pid = hb.get("pid") if hb.get("install_id") == install_id else None
            if isinstance(pid, int) and pid > 0 and pid != os.getpid() and ops.pid_alive(pid) \
                    and _ours(paths, ops.image_path(pid)):
                ops.kill_tree(pid)
            end = ops.now() + timedelta(seconds=5)
            while ops.mutex_exists(install_id) and ops.now() < end:
                ops.sleep(0.5)
    finally:
        _remove(flag)
    return not ops.mutex_exists(install_id)


def _wait_fresh(ident, paths, cfg, ops, wait_s: float, *, store: bool) -> dict:
    """heartbeat(와 store)가 신선해질 때까지 최대 wait_s 초(작업 조회는 끝에 한 번 — agent_health)."""
    end = ops.now() + timedelta(seconds=wait_s)
    stale = _stale_s(cfg)
    f = _freshness(ident, paths, stale, ops.now())
    while not (f["hb_fresh"] and (f["store_fresh"] or not store)) and ops.now() < end:
        ops.sleep(1.0)
        f = _freshness(ident, paths, stale, ops.now())
    return agent_health(ident, paths=paths, cfg=cfg, ops=ops)


def register_task(ident, *, paths: Paths | None = None, ops=None, no_start: bool = True) -> int:
    """작업 ``LM27-<install_id>`` 등록(같은 이름 덮어쓰기 — ``Register-Agent.ps1``). agent.json 의 판·구현을 쓴다. 반환 rc(0 성공)."""
    paths = paths or Paths()
    ops = ops or SystemOps(paths)
    aj = _read(paths.agent_json())
    ver, impl = aj.get("agent_ver"), aj.get("impl")
    if aj.get("install_id") != ident.install_id or not isinstance(ver, str) or not VER_RX.match(ver) \
            or impl not in ("py", "ps"):
        return 1
    return ops.register(ident.install_id, ver, impl, no_start=no_start)


# ───────────────────────────── 자기 시험·구현 고르기 ─────────────────────────────
def _selftest_line(stdout: bytes) -> dict:
    for ln in reversed((stdout or b"").decode("utf-8", errors="replace").splitlines()):
        s = ln.strip().lstrip("\ufeff")
        if s.startswith("{"):
            try:
                obj = fsx.loads_strict(s)
            except ValueError:
                continue
            st = obj.get("_selftest") if isinstance(obj, dict) else None
            if isinstance(st, dict):
                return st
    return {}


def _self_test(impl: str, paths: Paths, install_id: str, ver: str, ops) -> tuple[bool, str | None]:
    """(통과, 실패 사유 R-*) — py: 사본 python + agent_main.py --test-samples 3 · ps: agent.ps1 -TestSamples 3."""
    b = _bin_paths(paths, ver)
    cwd = str(paths.agent_dir())
    if impl == "py":
        argv = [str(b.python_exe()), "-X", "utf8", "-I", "-B", str(b.agent_main_script()), "--install-id", install_id,
                "--test-samples", "3"]
    else:
        from lm27.agent.harvest import powershell_exe
        argv = [powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                str(b.collect_script("agent.ps1")), "-InstallId", install_id, "-TestSamples", "3"]
    try:
        r = ops.run(argv, SELFTEST_TIMEOUT_S, cwd)
    except OSError:
        return False, "R-APPLOCKER"                       # 실행 자체가 막힘(그룹 정책·AppLocker)
    st = _selftest_line(r.stdout)
    if not r.timed_out and r.rc == 0 and st.get("ok") is True:
        return True, None
    why = st.get("reason")
    if why in REASONS_IMPL:
        return False, why
    return False, ("R-APPLOCKER" if impl == "py" else "R-CLM")


def self_test_impl(impl: str, *, paths: Paths | None = None, install_id: str | None = None, ver: str | None = None,
                   ops=None) -> bool:
    """구현 하나의 자기 시험(``-TestSamples 3``) 통과 여부(계약 §2.4). 판·install_id 는 agent.json 에서 읽는다."""
    paths = paths or Paths()
    ops = ops or SystemOps(paths)
    aj = _read(paths.agent_json())
    iid = install_id or aj.get("install_id")
    v = ver or aj.get("agent_ver")
    if impl not in ("py", "ps") or not isinstance(iid, str) or not isinstance(v, str):
        return False
    return _self_test(impl, paths, iid, v, ops)[0]


def _choose_impl(paths, install_id, ver, pref, ops) -> tuple[str, list]:
    order = ["ps", "py"] if pref == "ps" else ["py", "ps"]
    reasons = []
    for impl in order:
        ok, why = _self_test(impl, paths, install_id, ver, ops)
        if ok:
            return impl, []
        if why:
            reasons.append(why)
    return "none", sorted(set(reasons)) or ["R-CLM"]


# ───────────────────────────── ensure_agent ─────────────────────────────
def _selftest_quiet() -> int:
    from lm27.privacy.selftest import run_selftest
    return run_selftest(perf=False)


def ensure_agent(ident, *, paths: Paths | None = None, cfg=None, ops=None, selftest=None, keyring=None, os_names=None,
                 wait_hb_s: float = HB_WAIT_S) -> dict:
    """에이전트 설치·판 올림·등록·생존 복구(모듈 머리말 1~4). 반환 dict 의 ``rc`` 는 계약 §8.3 agent install 형."""
    paths = paths or Paths()
    if cfg is None:
        from lm27.config import load_config                          # 프로그램 폴더 전용
        cfg = load_config(paths)
    ops = ops or SystemOps(paths)
    iid = ident.install_id
    res = {"rc": 0, "install_id": iid, "pc_id": ident.pc_id, "agent_ver": None, "impl": None, "changed": [],
           "reasons": [], "notes": []}
    if not INSTALL_ID_RX.match(iid or ""):
        res.update(rc=1, notes=["bad_install_id"])
        return res
    aj = _read(paths.agent_json())
    if aj and aj.get("install_id") not in (None, iid):
        prior = [aj["install_id"]] if INSTALL_ID_RX.match(str(aj.get("install_id"))) else []
    else:
        prior = []
    prior = sorted({*prior, *(x for x in aj.get("prior_install_ids") or () if isinstance(x, str)
                               and INSTALL_ID_RX.match(x) and x != iid)})[-PRIOR_MAX:]
    same_inst = aj.get("install_id") == iid
    # 1. bin 사본
    files, missing = bin_files(paths)
    if missing:
        res.update(rc=1, notes=["bin_source_missing"], missing=missing)
        return res
    hashed = _hashed(files)
    ver = build_ver(hashed)
    res["agent_ver"] = ver
    diff = bin_diff(paths.agent_bin(ver), hashed)
    old_ver = aj.get("agent_ver") if same_inst else None
    if diff:
        if (selftest or _selftest_quiet)() != 0:
            res.update(rc=1, notes=["selftest_failed"])                    # P §18.3 — 회귀 말뭉치 실패면 설치 거부
            return res
        if old_ver == ver and ops.mutex_exists(iid):
            stop_agent(paths, iid, ops)                                   # 같은 판 파일을 바꾸려면 먼저 멈춘다
        install_bin(paths, hashed, ver, only=set(diff))
        res["changed"].append("bin")
    # 2. 키·문맥·설정
    from lm27.privacy import AuditSink, load_keyring, refresh_context_cache, write_agent_subkeys
    from lm27.privacy.rules import RULES_HASH
    audit = AuditSink.open(paths.data(), ident.pc_id, "collect", "agent", paths=paths)
    kr = keyring or load_keyring(paths.data(), audit, create=True, origin=ident.pc_id)
    kid = write_agent_subkeys(kr, paths.agent_dir(), audit)
    try:
        ch = refresh_context_cache(paths, cfg, kr=kr, audit=audit, os_names=os_names)
    except (OSError, ValueError, KeyError, TypeError) as e:
        ch = None
        res["notes"].append("ctxcache_" + type(e).__name__)
    if write_agent_config(paths, cfg, ch):
        res["changed"].append("config")
    c = audit.counts()
    if any(c.get(k) for k in ("masked", "dropped", "priv", "ad", "err")):
        audit.flush("key")                                                # 키 생성·교체·설정 검증 건수(있을 때만)
    # 3. 구현
    pref = cfg["agent.impl"]
    impl = aj.get("impl") if same_inst and old_ver == ver and aj.get("impl") in ("py", "ps") else None
    if impl is not None and pref in ("py", "ps") and impl != pref:
        impl = None                                                       # 강제 구현이 바뀌었다(agent.impl)
    impl_reasons = []
    if impl is None:
        impl, impl_reasons = _choose_impl(paths, iid, ver, pref, ops)
        res["changed"].append("impl")
    res["impl"] = impl
    # 4. agent.json
    keep = [ver] + ([old_ver] if isinstance(old_ver, str) and old_ver != ver and VER_RX.match(old_ver) else [])
    now = ops.now()
    new_aj = {"schema": AGENT_SCHEMA, "install_id": iid, "pc_id": ident.pc_id, "agent_ver": ver,
              "installed_at": aj.get("installed_at") if same_inst and _parse_utc(aj.get("installed_at")) else _utc(now),
              "impl": impl, "impl_reasons": impl_reasons, "task_name": task_name(iid),
              "mutex": f"Local\\LM27-{iid}-agent", "bin": f"bin\\{ver}", "keep_bins": keep[:KEEP_BINS],
              "rules_hash": RULES_HASH, "subkeys_kid": kid, "prior_install_ids": prior}
    _write_json(paths.agent_json(), new_aj)
    if impl == "none":
        res.update(rc=3, reasons=impl_reasons)                            # X-029 — 사람 조치 없이 전경 경로만 쓴다
        return res
    # 5. 등록
    h = agent_health(ident, paths=paths, cfg=cfg, ops=ops)
    if not h["hb_fresh"] and ops.mutex_exists(iid):                       # 절전 복귀 직후 — 산 에이전트가 틱을 낼 때까지 잠깐
        h = _wait_fresh(ident, paths, cfg, ops, ALIVE_GRACE_S, store=False)
    need_reg = not h["registered"] or not h["action_ok"]
    if need_reg:
        if ops.register(iid, ver, impl, no_start=True) != 0:
            res.update(rc=2, notes=res["notes"] + ["register_failed"], health=h)
            return res
        res["changed"].append("task")
    # 6. 기동·재기동
    zombie = "R-SAMPLER-ZOMBIE" in h["reasons"] or "R-RULESMISMATCH" in h["reasons"]
    restart = "bin" in res["changed"] or "impl" in res["changed"] or need_reg or not h["hb_fresh"] or zombie
    if restart:
        stop_agent(paths, iid, ops)
        _remove(paths.stop_flag())
        if not ops.run_task(task_name(iid)):
            res["notes"].append("run_failed")
        h = _wait_fresh(ident, paths, cfg, ops, wait_hb_s, store=True)
        res["changed"].append("started")
    prune_bins(paths, set(keep[:KEEP_BINS]))
    res["health"] = h
    res["reasons"] = h["reasons"]
    significant = [x for x in res["changed"] if x != "config"]           # 설정·문맥 사본 갱신은 [수집]마다 하는 일상 작업
    if not h["hb_fresh"]:
        res["rc"] = 2
        res["notes"].append("hb_not_fresh")
    elif not significant and h["healthy"]:
        res["rc"] = 4
    else:
        res["rc"] = 0
    return res


# ───────────────────────────── 수확 요청 ─────────────────────────────
def request_harvest_now(ident, wait_s: float, *, paths: Paths | None = None, ops=None) -> dict:
    """``run\\harvest_now.flag`` 를 놓고 그 뒤에 시작된 수확이 ``harvest_done.json`` 을 쓸 때까지 최대 wait_s 초 기다린다
    (TAB §1.7 ②). 반환 ``{rc, done, waited_s, result?}`` — rc 0 수확 끝(흐름 모두 정상) · 3 수확은 끝났으나 막힌 흐름 있음 ·
    2 시간 안에 끝나지 않음(에이전트가 없거나 바쁨 — 전경 경로가 채운다)."""
    paths = paths or Paths()
    ops = ops or SystemOps(paths)
    t0 = ops.now().replace(microsecond=0)
    fsx.atomic_write(paths.harvest_now_flag(), fsx.canon_bytes({"requested_at": _utc(t0)}) + b"\n")
    end = t0 + timedelta(seconds=max(0.0, float(wait_s)))
    while True:
        done = _read(paths.harvest_done())
        st = _parse_utc(done.get("started_at"))
        if done.get("install_id") == ident.install_id and st is not None and st >= t0:
            rc = 0 if done.get("rc") == 0 else 3
            return {"rc": rc, "done": True, "waited_s": round((ops.now() - t0).total_seconds(), 1), "result": done}
        if ops.now() >= end:
            return {"rc": 2, "done": False, "timed_out": True, "waited_s": round(float(wait_s), 1)}
        ops.sleep(1.0)


# ───────────────────────────── 제거 ─────────────────────────────
OPS_FILES = ("agent_json", "heartbeat", "agent_config", "person_dir_delta", "export_log", "harvest_done", "harvest_lock",
             "harvest_now_flag", "stop_flag")


def _rm_empty_dirs(base: Path) -> None:
    if not base.is_dir():
        return
    for dp, _dn, _fn in sorted(os.walk(base), key=lambda x: -len(x[0])):
        if dp == str(base):
            continue
        try:
            os.rmdir(dp)
        except OSError:
            pass


def uninstall(ident, purge: bool, *, paths: Paths | None = None, ops=None) -> dict:
    """정지 + 작업 삭제 + 하위 키·정제 문맥 사본·bin 삭제(P §9.4 — 하위 키는 제거 때 함께 지운다). store 는 남긴다.
    ``purge`` 면 로컬 원장·감사(store·privacy 함수로만 — L-11·O-16)와 운영 파일·로그까지. 반환 ``{rc, …}``(0 · 2 일부 남음)."""
    paths = paths or Paths()
    ops = ops or SystemOps(paths)
    iid = ident.install_id
    res = {"rc": 0, "stopped": stop_agent(paths, iid, ops), "task_removed": ops.remove(iid) == 0, "purged": 0,
           "notes": []}
    for p in (paths.agent_subkeys(), paths.context_cache()):
        _remove(p)
    res["bins_removed"] = prune_bins(paths, set())
    _remove(paths.harvest_now_flag())
    if purge:
        from lm27.privacy.audit import purge_audit
        from lm27.store import LockTimeout, purge_store
        try:
            res["purged"] += purge_store(paths)
            res["purged"] += purge_audit(paths)
        except (LockTimeout, OSError) as e:
            res["rc"] = 2
            res["notes"].append("purge_" + type(e).__name__)
        for name in OPS_FILES:
            if _remove(getattr(paths, name)()):
                res["purged"] += 1
        logs = paths.agent_logs()
        if logs.is_dir():
            for f in logs.iterdir():
                if f.is_file() and _remove(f):
                    res["purged"] += 1
        _rm_empty_dirs(paths.agent_dir())
    if not res["stopped"]:
        res["rc"] = 2
        res["notes"].append("still_running")
    if not res["task_removed"]:
        res["rc"] = 2
        res["notes"].append("task_remove_failed")
    return res
