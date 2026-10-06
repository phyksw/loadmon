# -*- coding: utf-8 -*-
r"""WP-13 시험 도우미 — %TEMP% 샌드박스(ROOT·LAD) · 시험 키링·정제 문맥 사본·agent_config · 가짜 Win32 API·기계 조회·
작업 스케줄러(``FakeOps``) · 가짜 수집기·파이프 스크립트(합성) · 합성 바로가기(.lnk) 바이트 · PS 함수 꺼내 돌리기.

실제 작업 등록·레지스트리 쓰기·실 PC 수집(전경 창 제목·이벤트 로그)은 하지 않는다. 모든 쓰기는 ``guard_write`` 로 확인한
%TEMP% 아래에만. 이름·주소·도메인은 자리표시자(홍길동·김철수·과제A·고객사A·example).
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import context as C
from lm27.privacy import keys as K
from lm27.util.proc import ChildResult
from tests.fixtures.tree import guard_write

REAL_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_JSON = REAL_ROOT / "config" / "settings_registry.json"
IID = "0123456789abcdef0123456789abcdef"
IID2 = "fedcba9876543210fedcba9876543210"
GUID1 = "11111111-2222-3333-4444-555555555555"
GUID2 = "66666666-7777-8888-9999-aaaaaaaaaaaa"
MASTER = bytes(range(1, 33))
REGISTRY = {"internal_domains": ["corp.example"],
            "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}],
            "projects": [{"id": "P-0001", "codenames": ["과제A"]}]}
OS_NAMES = ["hongtest", "홍길동"]
T0 = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
EXCEL = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"
CREATE_NO_WINDOW = 0x08000000


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def keyring(master: bytes = MASTER) -> K.Keyring:
    kid = K.kid_of(master)
    return K.Keyring(primary_kid=kid, primary_secret=master, all={kid: master})


def powershell() -> str:
    sysroot = os.environ.get("SystemRoot") or "C:\\Windows"
    return os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


class Sandbox:
    """%TEMP%\\lm27t_wp13_*\\{root\\data, lad} — 시험 하나의 ROOT·LAD(실제 트리·실제 %LOCALAPPDATA% 미접촉)."""

    def __init__(self, prefix: str = "lm27t_wp13_"):
        self.dir = guard_write(tempfile.mkdtemp(prefix=prefix))
        self.root = self.dir / "root"
        (self.root / "data").mkdir(parents=True)
        self.lad = self.dir / "lad"
        self.paths = Paths(self.root, lad=self.lad)

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def cfg(self, **over):
        return load_config(registry_path=REGISTRY_JSON, config_path=self.dir / "no_config.json", overrides=over or None)

    def agent_files(self, *, keys: bool = True, ctx: bool = True, settings: bool = True, kr=None, cfg=None) -> str | None:
        """하위 키·정제 문맥 사본·agent_config 를 샌드박스 에이전트 폴더에 쓴다(설치가 쓰는 것과 같은 함수). 문맥 해시."""
        a = self.paths.agent_dir()
        k = kr or keyring()
        if keys:
            K.write_agent_subkeys(k, a)
        c = cfg or self.cfg()
        h = None
        if ctx:
            obj = C.context_cache_obj(self.paths, c, kr=k, registry=REGISTRY, calendar={}, local=C.LocalOnly(),
                                      os_names=OS_NAMES)
            h = C.write_context_cache(a, obj)
        if settings:
            from lm27.agent.install import write_agent_config
            write_agent_config(self.paths, c, h)
        return h

    def write_json(self, path, obj) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def all_bytes(self, base: Path | None = None) -> bytes:
        import gzip
        out = []
        for p in sorted((base or self.dir).rglob("*")):
            if p.is_file() and p.suffix not in (".exe", ".dll", ".pyd", ".zip", ".cat"):
                data = p.read_bytes()
                if p.suffix == ".gz":
                    try:
                        data = gzip.decompress(data)
                    except (OSError, EOFError):
                        pass
                out.append(data)
        return b"\n".join(out)


# ───────────────────────────── 가짜 실기계 ─────────────────────────────
class FakeApi:
    """가짜 Win32(전경 창·유휴·세션·프로세스). 값은 속성으로 바꿔 가며 틱을 만든다(제목은 합성)."""

    def __init__(self, title="견적_v2.xlsx - Excel", image=EXCEL, idle_ms=3000, wts=(0, 1, 0), procs=(), cpu=None):
        self.title, self.image, self.idle_ms, self.wts_v = title, image, idle_ms, wts
        self.procs = list(procs)
        self.cpu = dict(cpu or {})
        self.tick = 10_000_000

    def foreground(self):
        return (0, 0) if self.image is None else (1, 4242)

    def window_text(self, h):
        return self.title

    def image_path(self, pid):
        return self.image or ""

    def tick64(self):
        self.tick += 1000
        return self.tick

    def last_input(self):
        return (self.tick - self.idle_ms) & 0xFFFFFFFF

    def wts(self):
        return self.wts_v

    def processes(self):
        return list(self.procs)

    def cpu_seconds(self, pid):
        v = self.cpu.get(pid)
        return v() if callable(v) else v


class FakeProbe:
    """``identify_pc`` 의 기계 조회 가짜(MachineGuid 합성 값)."""

    def __init__(self, guid=GUID1):
        self.guid = guid

    def machine_guid(self):
        return self.guid

    def computer_name(self):
        return "PCX"

    def profile_ctime(self):
        return "1"

    def offset_min(self):
        return 540

    def windows_tz(self):
        return "Korea Standard Time"

    def model(self):
        return ""

    def battery(self):
        return False

    def rdp_session(self):
        return False

    def chassis(self):
        return ()


class Clock:
    """가상 시계(감독 루프의 clock·wait)."""

    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self):
        return self.t

    def wait(self, s):
        self.t += timedelta(seconds=max(float(s), 0.001))


def make_agent(sb: Sandbox, *, api=None, clock=None, probe=None, rules_ok=True, spawn=None, run_conn=None,
               install_id: str = IID, exe_reader=None, mutex=None):
    """가짜를 끼운 ``Agent``(뮤텍스·수확 자식·연결자·기계 조회 모두 가짜). 반환 (agent, clock)."""
    from lm27.agent.main import Agent
    clk = clock or Clock()
    spawned = []
    ag = Agent(install_id, paths=sb.paths, api=api or FakeApi(), clock=clk, wait=clk.wait,
               mutex=mutex or (lambda n: (None, False)),
               spawn_harvest=spawn or (lambda ident, streams, requested: spawned.append((ident, streams, requested))),
               run_conn=run_conn or (lambda *a, **k: None), probe=probe or FakeProbe(), rules_ok=lambda: rules_ok,
               exe_reader=exe_reader, recent_dir=str(sb.dir / "recent"))
    ag.spawned = spawned
    return ag, clk


def raw_sampler(**over) -> dict:
    d = {"ts_utc": "2026-10-05T01:00:00Z", "ts_local_offset": "+09:00", "ts_precision": "exact",
         "observed_at": "2026-10-05T01:00:00Z", "confidence": 1.0, "fg_exe": "excel.exe", "app_id": "excel",
         "app_class": "office", "fg_title": "견적_v2.xlsx - Excel", "session_state": "active", "idle_sec": 3,
         "layer": "L3", "interval_sec": 60}
    d.update(over)
    return d


def write_sampler_row(paths: Paths, pc_id: str) -> int:
    """에이전트 모드 정제기로 pc.sampler 행 하나를 로컬 원장에(가짜 에이전트 기동의 'store 신선')."""
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.store import SegmentWriter
    rc = make_record_context(None, "pc.sampler", pc_id, agent_dir=paths.agent_dir())
    out = sanitize_record("pc_session", raw_sampler(), rc)
    w = SegmentWriter(paths, pc_id, "pc_session", "pc.sampler")
    w.append(out.row)
    return w.flush()


class FakeOps:
    """가짜 작업 스케줄러·뮤텍스·프로세스·자기 시험 실행(실등록 0). ``run_task`` 는 에이전트 기동을 흉내 낸다(heartbeat 쓰기 +
    pc.sampler 행 1개). ``stubborn`` 이면 정지 깃발을 무시해 kill_tree 경로로 간다."""

    def __init__(self, sb: Sandbox, ident, *, selftest_ok=("py",), register_rc: int = 0, start: bool = True,
                 stubborn: bool = False, store_on_start: bool = True):
        self.sb, self.ident = sb, ident
        self.t = datetime.now(UTC).replace(microsecond=0)
        self.tasks: dict = {}
        self.calls: list = []
        self.selftest_ok = set(selftest_ok)
        self.register_rc = register_rc
        self.start = start
        self.stubborn = stubborn
        self.store_on_start = store_on_start
        self.alive = False
        self.killed: list = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)

    def run(self, argv, timeout_s, cwd=None):
        impl = "py" if "--test-samples" in argv else "ps"
        self.calls.append(("selftest", impl))
        ok = impl in self.selftest_ok
        st = {"impl": impl, "ok": ok, "reason": None if ok else ("R-APPLOCKER" if impl == "py" else "R-CLM")}
        return ChildResult(0 if ok else 3, (json.dumps({"_selftest": st}) + "\n").encode(), b"", False, 0.1, 1)

    def query_task(self, name):
        return self.tasks.get(name)

    def register(self, install_id, ver, impl, *, no_start=True):
        from lm27.agent.install import agent_entry, task_name
        self.calls.append(("register", install_id, ver, impl))
        if self.register_rc == 0:
            e = agent_entry(self.sb.paths, ver, impl, install_id)
            self.tasks[task_name(install_id)] = {"command": e["command"], "arguments": e["arguments"], "workdir": e["workdir"]}
        return self.register_rc

    def remove(self, install_id):
        from lm27.agent.install import task_name
        self.calls.append(("remove", install_id))
        self.tasks.pop(task_name(install_id), None)
        return 0

    def heartbeat(self, *, age_s: float = 0.0, started_age_s: float = 0.0, last_error: str = "") -> None:
        t = self.t - timedelta(seconds=age_s)
        st = self.t - timedelta(seconds=max(started_age_s, age_s))
        self.sb.write_json(self.sb.paths.heartbeat(), {
            "schema": "lm27.hb/1", "install_id": self.ident.install_id, "pc_id": self.ident.pc_id, "pid": 424242,
            "agent_ver": "x", "impl": "py", "started_at": st.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_tick": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "interval_s": 60, "samples_today": 1, "harvest": {},
            "last_error": last_error, "buffered": 0, "state": "running"})

    def run_task(self, name):
        self.calls.append(("run_task", name))
        if self.start:
            self.alive = True
            self.heartbeat()
            if self.store_on_start:
                write_sampler_row(self.sb.paths, self.ident.pc_id)
        return True

    def mutex_exists(self, install_id):
        if self.alive and not self.stubborn and self.sb.paths.stop_flag().is_file():
            self.alive = False                                       # 정지 깃발을 본 에이전트가 끝난다
        return self.alive

    def pid_alive(self, pid):
        return self.alive

    def kill_tree(self, pid):
        self.killed.append(pid)
        self.alive = False
        return True

    def image_path(self, pid):
        return str(self.sb.paths.agent_bin_root() / "0.1.0-x" / "py311" / "pythonw.exe")


# ───────────────────────────── 가짜 수집기·파이프(합성 스크립트) ─────────────────────────────
FAKE_COLLECTOR = r'''
import json, sys, time
mode = sys.argv[1]
n = int(sys.argv[2])
rc = int(sys.argv[3])
line = sys.stdin.buffer.readline()
inobj = json.loads(line) if line.strip() else None
if mode == "sleep":
    time.sleep(60)
out = sys.stdout.buffer
for i in range(n):
    out.write((json.dumps({"rec": i, "fg_title": "합성 제목 %d" % i}, ensure_ascii=False) + "\n").encode("utf-8"))
out.write((json.dumps({"_cursor": {"last_ts_utc": "2026-10-05T01:00:00Z"}}) + "\n").encode("utf-8"))
out.flush()
st = {"schema": "lm27.collector_status/1", "src": "x", "rc": rc, "reasons": (["R-UIAEMPTY"] if rc == 3 else []),
      "partial": False, "cap_hit": False, "budget_hit": False, "n": n, "counts": {}, "echo_in": inobj, "extra": 1}
sys.stderr.write("진행 안내 줄\n")
if mode == "clm":                       # CLM 모드: 상태 줄을 stdout 제어 줄로(C1)
    out.write((json.dumps({"_status": st}, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()
else:
    sys.stderr.write(json.dumps({"_status": st}, ensure_ascii=False) + "\n")
sys.stderr.flush()
sys.exit(rc)
'''

FAKE_PIPE = r'''
import hashlib, json, sys, time
mode = sys.argv[1]
data = sys.stdin.buffer.read()
if mode == "sleep":
    time.sleep(60)
lines = [x for x in data.splitlines() if x.strip()]
recs = [x for x in lines if not x.startswith(b'{"_')]
saved = any(x.startswith(b'{"_cursor"') for x in lines)
sm = {"ok": True, "mode": "agent", "rows_in": len(recs), "stored": len(recs), "dropped": {}, "errors": {},
      "rules_ver": "2026.10.0", "kid": None, "out_sha256": hashlib.sha256(data).hexdigest()[:16], "cursor_saved": saved,
      "bytes": len(data)}
st = [json.loads(x)["_status"] for x in lines if x.startswith(b'{"_status"')]
if st:
    sm["collector_status"] = st[-1]      # 실제 파이프처럼 stdout 상태 줄을 요약에 싣는다
sys.stdout.write(json.dumps(sm) + "\n")
sys.exit(6 if mode == "nokey" else 0)
'''


def write_fakes(sb: Sandbox) -> tuple[Path, Path]:
    d = sb.dir / "fakes"
    d.mkdir(exist_ok=True)
    c, p = d / "fake_collector.py", d / "fake_pipe.py"
    c.write_text(FAKE_COLLECTOR, encoding="utf-8")
    p.write_text(FAKE_PIPE, encoding="utf-8")
    return c, p


def fake_runtime(sb: Sandbox, *, col_mode="ok", n=2, rc=0, pipe_mode="ok"):
    """``Runtime`` 하위 클래스 — 수집기·파이프 대신 합성 파이썬 스크립트를 띄운다(PS·정제기 없이 연결자만 시험)."""
    from lm27.agent.harvest import Runtime
    col, pipe = write_fakes(sb)
    py = sys.executable

    class _RT(Runtime):
        def collector_argv(self, spec, pc_id, extra_args=()):
            return [py, "-X", "utf8", "-B", str(col), col_mode, str(n), str(rc)]

        def pipe_argv(self, spec, pc_id):
            return [py, "-X", "utf8", "-B", str(pipe), pipe_mode]

    return _RT(paths=sb.paths, python=py, pipe=str(pipe), powershell=powershell(), cwd=str(sb.dir), env=None)


# ───────────────────────────── 합성 바로가기 ─────────────────────────────
def lnk_bytes(target: str, *, unicode: bool = False) -> bytes:
    """셸 바로가기(.lnk) 최소 바이트 — LinkInfo 의 LocalBasePath(ANSI 또는 유니코드)만 있는 합성본."""
    hdr = bytearray(0x4C)
    struct.pack_into("<I", hdr, 0, 0x4C)
    struct.pack_into("<I", hdr, 0x14, 0x2)                          # HasLinkInfo
    hs = 0x24 if unicode else 0x1C
    body = bytearray()
    off_vol = hs
    body += struct.pack("<IIII", 0x11, 3, 0, 0x10) + b"\x00"
    off_base = hs + len(body)
    body += (b"\x00" if unicode else target.encode("mbcs") + b"\x00")
    off_suf = hs + len(body)
    body += b"\x00"
    extra = b""
    if unicode:
        off_base_u = hs + len(body)
        body += target.encode("utf-16-le") + b"\x00\x00"
        off_suf_u = hs + len(body)
        body += b"\x00\x00"
        extra = struct.pack("<II", off_base_u, off_suf_u)
    li = struct.pack("<IIIIIII", hs + len(body), hs, 0x1, off_vol, off_base, 0, off_suf) + extra
    return bytes(hdr) + li + bytes(body)


def lnk_network(server_share: str, suffix: str) -> bytes:
    """네트워크 대상(CommonNetworkRelativeLink + CommonPathSuffix) 합성 바로가기."""
    hdr = bytearray(0x4C)
    struct.pack_into("<I", hdr, 0, 0x4C)
    struct.pack_into("<I", hdr, 0x14, 0x2)
    hs = 0x1C
    net = server_share.encode("mbcs") + b"\x00"
    cnrl = struct.pack("<IIIII", 0x14 + len(net), 0x2, 0x14, 0, 0) + net
    off_cn = hs
    body = bytearray(cnrl)
    off_suf = hs + len(body)
    body += suffix.encode("mbcs") + b"\x00"
    li = struct.pack("<IIIIIII", hs + len(body), hs, 0x2, 0, 0, off_cn, off_suf)
    return bytes(hdr) + li + bytes(body)


# ───────────────────────────── PS 함수 꺼내 돌리기 ─────────────────────────────
PS_RUNNER = r'''param([string]$Src, [string]$Names, [string]$Body)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$script:Utf8 = New-Object System.Text.UTF8Encoding($false)
$script:Inv = [Globalization.CultureInfo]::InvariantCulture
$IdleMax = 4294968
$GapCap = 1.5
$PsSlackSec = 30
$EventsMaxSec = 60
$OoxmlTotalSec = 90
$ScanMaxSec = 120
$tk = $null; $er = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Src, [ref]$tk, [ref]$er)
$want = @($Names -split ',')
$defs = $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)
foreach ($d in $defs) { if ($want -contains $d.Name) { . ([scriptblock]::Create($d.Extent.Text)) } }
$code = [IO.File]::ReadAllText($Body, $script:Utf8)
. ([scriptblock]::Create($code))
'''


def run_ps_funcs(sb: Sandbox, script: Path, names, body: str, *, timeout: float = 120,
                 env: dict | None = None) -> subprocess.CompletedProcess:
    """PS 스크립트에서 함수 정의만 AST 로 꺼내(스크립트 본문은 돌리지 않는다) body 를 돌린다. stdout(UTF-8) 반환."""
    d = sb.dir / "psrun"
    d.mkdir(exist_ok=True)
    runner = d / "runner.ps1"
    runner.write_bytes(b"\xef\xbb\xbf" + PS_RUNNER.replace("\n", "\r\n").encode("utf-8"))
    bodyf = d / f"body_{len(list(d.iterdir()))}.ps1"
    bodyf.write_bytes(b"\xef\xbb\xbf" + body.replace("\n", "\r\n").encode("utf-8"))
    argv = [powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(runner),
            "-Src", str(script), "-Names", ",".join(names), "-Body", str(bodyf)]
    return subprocess.run(argv, capture_output=True, timeout=timeout, cwd=str(sb.dir), env=env,
                          creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0, check=False)


FAKE_EVENTS_PS = r'''$line = $null
try { if ([Console]::IsInputRedirected) { $line = [Console]::In.ReadLine() } } catch { $line = $null }
$o = [Console]::OpenStandardOutput()
$enc = New-Object System.Text.UTF8Encoding($false)
function Send-Line([string]$s) { $b = $enc.GetBytes($s + "`n"); $o.Write($b, 0, $b.Length) }
Send-Line '{"event_class":"boot","session_state":"active","layer":"L0","ts_utc":"2026-09-01T00:00:00Z","ts_end":"2026-09-01T03:00:00Z","ts_local_offset":"+09:00","ts_precision":"minute","observed_at":"2026-09-02T00:00:00Z","confidence":1.0,"flags":{"end_uncertain":false}}'
Send-Line '{"event_class":"wake","session_state":"active","layer":"L0","ts_utc":"2026-09-01T04:00:00Z","ts_end":"2026-09-01T09:00:00Z","ts_local_offset":"+09:00","ts_precision":"minute","observed_at":"2026-09-02T00:00:00Z","confidence":1.0,"flags":{"end_uncertain":false}}'
Send-Line '{"_cursor":{"last_ts_utc":"2026-09-01T09:00:00Z"}}'
$o.Flush()
$ok = 'false'
if ($line -and $line.Contains('"_in"') -and $line.Contains('collect.lookbackDays')) { $ok = 'true' }
[Console]::Error.WriteLine('{"_status":{"schema":"lm27.collector_status/1","src":"pc.events","rc":0,"reasons":[],"partial":false,"cap_hit":false,"budget_hit":false,"n":2,"counts":{},"in_ok":' + $ok + '}}')
exit 0
'''

# CLM 모드 변형 — 상태 줄을 stderr 대신 stdout 제어 줄로(실제 파이프가 요약의 collector_status 로 넘긴다 — C1)
FAKE_EVENTS_PS_CLM = (FAKE_EVENTS_PS.replace("[Console]::Error.WriteLine(", "Send-Line (")
                      .replace("\nexit 0\n", "\n$o.Flush()\nexit 0\n"))


def write_ps(path: Path, text: str) -> None:
    """합성 PS 스크립트(UTF-8 BOM + CRLF) — 샌드박스 안에만."""
    guard_write(path)
    path.write_bytes(b"\xef\xbb\xbf" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
