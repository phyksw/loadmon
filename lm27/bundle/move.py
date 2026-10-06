# -*- coding: utf-8 -*-
r"""이동 준비·도착 점검(계약 §2.6, TAB §1.11·§1.12) — ``prepare_move(paths, cfg) -> MoveLaunch`` · ``arrival_check(paths)``.

[이동 준비] 의 파이썬 쪽(사용자는 [이동 준비] → "[완료]" 확인 → 폴더 드래그만 한다):
  1. 마지막 내보내기 — 에이전트 kind 만(전경 수집기 없이) ``export_agent_streams``. 실패해도 이동은 막지 않는다(사유 표시).
  2. 검증 — 이 PC manifest 의 모든 세그먼트 sha 재계산(검증 캐시에 통과 기록이 있으면 생략). 불일치는 그 PC 의
     ``quarantine\`` 로 격리 + 표시(이동은 막지 않는다).
  3. ``move_ready.json``(``lm27.moveready/1`` — 그 PC 폴더 안에만) 을 **파이썬이** 쓴다: 이 PC manifest 의 전 목록
     (이름·sha·크기), 그 시점 번들 안 다른 PC 별 세그먼트 수. 도착 PC 가 이것으로 누락을 이름별로 찾는다.
  4. 이동 시험 도우미 ``collect\move\Prepare-Move.ps1`` 을 ``%TEMP%\lm27_move_<rand>.ps1`` 로 복사해 **보이는 콘솔
     창**으로 띄운다(``-Root -WaitPid -Gen -RenameRetries -StopWaitSec``). 파이썬은 ROOT 안의 ``python.exe`` 라 실행
     중에는 폴더 이름을 못 바꾸므로, 이 프로세스(와 화면 서버)가 끝나기를 도우미가 기다린 뒤 이름 바꾸기 시험을 한다.
     도우미는 디스크에 쓰지 않는다(L-09) — 결과는 그 창에만 보인다.
  · 에이전트는 멈추지 않는다(ROOT 밖 사본) — 떠난 뒤에도 그 PC 에 계속 쌓인다.
  · bat 경로(``LoadMonitor27-이동준비.bat``)는 도우미를 ``-WaitPid`` 없이 띄우고, 그 도우미가 먼저 ``lm27 move-prepare`` 를
    불러 이 함수(1~3단계)를 돌린 뒤 여기서 띄운 새 도우미가 시험을 이어 간다(X-332) — 두 경로가 같은 단계를 거친다.
"""
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field

from lm27.bundle import manifest as mf
from lm27.util import fsx

SCHEMA = "lm27.moveready/1"
HELPER_REL = "move/Prepare-Move.ps1"
HELPER_PREFIX = "lm27_move_"
PROFILE_TRACE_NAMES = ("user data", "local state", "cookies")
_SCAN_DEPTH = 4
_SKIP_DIRS = frozenset({"python", "__pycache__", ".git", ".ruff_cache", "node_modules"})
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")


@dataclass
class MoveLaunch:
    """``rc`` 0 = 도우미를 띄움(또는 ``launch=False`` 로 준비만) · 2 = 띄웠으나 확인 필요(내보내기 실패·sha 불일치) ·
    3 = 도우미를 띄우지 못함(파일 없음·실행 실패)."""
    rc: int = 0
    pc_id: str = ""
    manifest_gen: int = 0
    sha_ok: bool = True
    quarantined: list = field(default_factory=list)
    move_ready: str = ""
    helper: str = ""
    argv: list = field(default_factory=list)
    pid: int = 0
    bundle_mb: float = 0.0
    derived_mb: float = 0.0
    notes: list = field(default_factory=list)


@dataclass
class Missing:
    """도착 점검 한 줄 — state ∈ 없음 · 크기 다름 · sha 다름 · 읽기 불가 · 폴더 없음."""
    pc_id: str
    label: str
    kind: str
    file: str
    expected: object
    state: str


def _mb(n: int) -> float:
    return round(n / (1 << 20), 1)


def _dir_bytes(path) -> int:
    total = 0
    for dp, _dn, fns in os.walk(fsx.longp(path)):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def bundle_bytes(paths) -> int:
    r"""번들(``bundle.json`` · ``pc_aliases.json`` · ``pcs\**``) 크기."""
    n = _dir_bytes(paths.pcs())
    for p in (paths.bundle_json(), paths.pc_aliases()):
        try:
            n += os.path.getsize(fsx.longp(p))
        except OSError:
            pass
    return n


def profile_traces(root) -> int:
    """ROOT 아래 브라우저 프로필 흔적(``User Data``·``*Profile*``·``Local State``·``Cookies``) 수 — 번들 밖이어야 한다
    (TAB §1.10 계약 위반 탐지). 경로는 돌려주지 않는다."""
    base = os.fspath(root)
    n = 0
    base_depth = base.rstrip("\\/").count(os.sep)
    for dp, dns, fns in os.walk(fsx.longp(base)):
        depth = dp.rstrip("\\/").count(os.sep) - base_depth
        dns[:] = [d for d in dns if d.lower() not in _SKIP_DIRS and depth < _SCAN_DEPTH]
        for nm in list(dns) + list(fns):
            low = nm.lower()
            if low in PROFILE_TRACE_NAMES or "profile" in low and nm in dns:
                n += 1
    return n


def _verify_own(paths, pcdir, m, now) -> list:
    """이 PC 세그먼트 sha 검증 — 불일치는 그 PC 의 quarantine 으로(목록에서 뺀다). 반환: 격리 목록."""
    from lm27.bundle import loader
    cache = fsx.read_json(paths.verify_cache(), {}, want=dict) or {}
    before = fsx.canon_bytes(cache)
    dead = mf.tombstoned_shas(m)
    bad = []
    for s in list(m["segments"]):
        if s.get("sha256") in dead:
            continue
        why = loader.check_segment(paths, pcdir.name, s, cache)
        if why == "missing":
            bad.append({"file": s.get("file"), "reason": why})       # 목록은 그대로 — 도착 점검이 이름으로 알린다
        elif why:
            mf.quarantine_file(pcdir, m, s["file"], why, now=now)
            bad.append({"file": s.get("file"), "reason": why})
    data = fsx.canon_bytes(cache)
    if data != before:
        fsx.atomic_write(paths.verify_cache(), data, fsync=False)
    return bad


def build_move_ready(paths, pc_id, m, pc, *, sha_ok=True, now=None) -> dict:
    """move_ready.json 내용(계약 §3.23): at pc_id label_auto manifest_gen bundle_mb derived_mb sha_ok segments
    other_pcs_seen."""
    from lm27.bundle import loader
    dead = mf.tombstoned_shas(m)
    segs = sorted(([s.get("file"), s.get("sha256"), s.get("bytes")] for s in m["segments"]
                   if s.get("sha256") not in dead), key=lambda x: str(x[0]))
    others = {}
    for pid in loader.list_pc_ids(paths):
        if pid == pc_id:
            continue
        om = mf.load_manifest(paths.pc_dir(pid), quarantine=False)
        od = mf.tombstoned_shas(om)
        others[pid] = sum(1 for s in om["segments"] if s.get("sha256") not in od)
    return {"schema": SCHEMA, "at": now or fsx.utcnow_iso(), "pc_id": pc_id,
            "label_auto": (pc or {}).get("label_auto", ""), "manifest_gen": int(m.get("gen") or 0),
            "bundle_mb": _mb(bundle_bytes(paths)), "derived_mb": _mb(_dir_bytes(paths.derived())),
            "sha_ok": bool(sha_ok), "segments": segs, "other_pcs_seen": others}


def helper_argv(paths, cfg, helper_path, *, wait_pid, gen) -> list:
    """도우미 실행 명령줄(``powershell -NoProfile -ExecutionPolicy Bypass -File <사본> -Root … -WaitPid … -Gen …``)."""
    ps = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "WindowsPowerShell", "v1.0",
                      "powershell.exe")
    return [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.fspath(helper_path),
            "-Root", str(paths.root), "-WaitPid", str(int(wait_pid)), "-Gen", str(int(gen)),
            "-RenameRetries", str(int(cfg["move.renameRetries"])), "-StopWaitSec", str(int(cfg["move.stopWaitSec"]))]


def launch_helper(argv) -> int:
    """도우미를 새 콘솔 창으로 띄우고 pid 를 돌려준다(기다리지 않는다). **표준 핸들을 물려주지 않는다** — stdin·stdout·stderr 를
    모두 None 으로 두어 새 콘솔의 핸들을 쓰게 한다. 예전에는 stdin 만 DEVNULL 이라 Popen 이 나머지 둘을 이 CLI 의 표준 핸들
    (화면 작업이면 작업 파이프)로 채워 도우미에게 넘겼고, 작업이 끝났는데도 도우미가 사는 동안 파이프가 열려 화면이 '진행 중'으로
    남았다(W2 C21 근본 원인 — 통합). 도우미 창에는 [완료]·[실패] 문구가 그대로 보인다."""
    from lm27.util import proc
    return proc.spawn(list(argv), stdin=None, stdout=None, stderr=None, new_console=True).pid


def copy_helper(paths, *, temp_dir=None) -> str:
    r"""도우미를 ``%TEMP%\lm27_move_<rand>.ps1`` 로 복사(바이트 그대로 — UTF-8 BOM + CRLF 유지). 반환: 사본 경로."""
    src = paths.collect_script(HELPER_REL)
    data = fsx.read_bytes(src)
    d = temp_dir or tempfile.gettempdir()
    dst = os.path.join(os.fspath(d), f"{HELPER_PREFIX}{secrets.token_hex(4)}.ps1")
    fsx.atomic_write(dst, data)
    return dst


def prepare_move(paths, cfg, *, ident=None, launch=True, wait_pid=None, export=True, reader=None, now=None,
                 temp_dir=None, spawn=None) -> MoveLaunch:
    """[이동 준비]. ``launch=False`` 면 move_ready.json 까지만 하고 도우미 명령줄만 돌려준다(시험·화면 미리보기).
    ``spawn(argv) -> pid`` = 도우미 기동 주입(기본 ``lm27.util.proc.spawn(new_console=True)``)."""
    from lm27.bundle import pcreg
    from lm27.bundle.lock import BundleLock
    if ident is None:
        from lm27.bundle.ids import identify_pc
        ident = identify_pc(paths)
    now = now or fsx.utcnow_iso()
    res = MoveLaunch(pc_id=ident.pc_id)
    with BundleLock(paths, "move", cfg=cfg):
        pcdir = pcreg.ensure_pc_dir(paths, ident, now=now)
    if export:
        try:
            from lm27.bundle.export import export_agent_streams
            with BundleLock(paths, "move", cfg=cfg):
                ex = export_agent_streams(pcdir, ident, cfg, paths=paths, reader=reader, now=now)
            res.notes.append({"code": "final_export", "new": ex.new, "gaps": len(ex.gaps)})
        except Exception as e:                       # 이동은 막지 않는다 — 사유(예외 유형)를 보인다
            res.notes.append({"code": "final_export_failed", "error": type(e).__name__})
            res.rc = 2
    with BundleLock(paths, "move", cfg=cfg):
        m = mf.load_manifest(pcdir, quarantine=True)
        before = mf.manifest_body(m)
        res.quarantined = _verify_own(paths, pcdir, m, now)
        res.sha_ok = not res.quarantined
        if m.get("_recovered") or mf.manifest_body(m) != before:
            mf.save_manifest(pcdir, m, now=now)
        pc = pcreg.load_pc(pcdir)
        mr = build_move_ready(paths, ident.pc_id, m, pc, sha_ok=res.sha_ok, now=now)
        fsx.atomic_write(paths.move_ready(ident.pc_id), fsx.canon_bytes(mr))
    res.manifest_gen = mr["manifest_gen"]
    res.bundle_mb, res.derived_mb = mr["bundle_mb"], mr["derived_mb"]
    res.move_ready = str(paths.move_ready(ident.pc_id))
    if not res.sha_ok:
        res.rc = 2
    n_trace = profile_traces(paths.root)
    if n_trace:
        res.notes.append({"code": "browser_profile_trace", "n": n_trace})
    try:
        helper = copy_helper(paths, temp_dir=temp_dir)
    except OSError as e:
        res.notes.append({"code": "helper_missing", "error": type(e).__name__})
        res.rc = 3
        return res
    res.helper = helper
    res.argv = helper_argv(paths, cfg, helper, wait_pid=wait_pid or os.getpid(), gen=res.manifest_gen)
    if not launch:
        return res
    try:
        res.pid = int((spawn or launch_helper)(res.argv) or 0)
    except OSError as e:
        res.notes.append({"code": "helper_launch_failed", "error": type(e).__name__})
        res.rc = 3
    return res


def arrival_check(paths, *, deep=False) -> list:
    """도착 점검(TAB §1.12): 모든 ``pcs\\*\\move_ready.json`` 목록의 파일이 실제로 있고 크기가 같은지.
    ``deep=True`` 면 sha 까지(느림 — 보통은 백그라운드 ``verify_bundle``). 자동 삭제·재구성 없음. 반환: ``Missing`` 목록."""
    from lm27.bundle import loader, pcreg
    out = []
    labels = {}
    for pid in loader.list_pc_ids(paths):
        pc = pcreg.load_pc(paths.pc_dir(pid)) or {}
        labels[pid] = (pc.get("label_auto") or "", pc.get("kind") or "")
    for x in loader.arrival_missing(paths):
        lab, kind = labels.get(x["pc_id"], ("", ""))
        seg_kind = (x["file"] or "").split("/")[1] if x.get("file") and x["file"].count("/") >= 2 else kind
        out.append(Missing(x["pc_id"], lab, seg_kind, x.get("file") or "", x.get("expected"), x["state"]))
    if deep:
        for pid in loader.list_pc_ids(paths):
            mr = fsx.read_json(paths.move_ready(pid), None, want=dict)
            if not mr:
                continue
            for item in mr.get("segments") or ():
                if not (isinstance(item, list) and len(item) >= 3 and isinstance(item[0], str)):
                    continue
                if any(o.pc_id == pid and o.file == item[0] for o in out):
                    continue
                why = loader.check_segment(paths, pid, {"file": item[0], "sha256": item[1], "bytes": item[2]})
                if why == "sha_mismatch":
                    lab, _k = labels.get(pid, ("", ""))
                    out.append(Missing(pid, lab, item[0].split("/")[1], item[0], item[2], "sha 다름"))
    return out
