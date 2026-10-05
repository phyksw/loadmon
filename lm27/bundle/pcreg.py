# -*- coding: utf-8 -*-
r"""PC 레지스트리 ``pc.json`` ``lm27.pc/1``(계약 §3.8, TAB §1.5) — 능력 기록·``verdict`` 유일 판정·번들 도착 경로 탐침.

``{schema, pc_id, id_source, label_auto, label_user(로컬 전용), host_display(로컬 전용), host_class, kind,
kind_evidence, kind_confirmed, tz{utc_offset_min, windows_tz, changes[]}, roles[], first_seen, last_seen, anchor_since,
installs[], visits[], flags[], capabilities{<키>: {ok, value, reasons[], history[{date, status, reasons, probe_sig}],
verdict}}}``

  · 쓰기는 그 PC 의 전경 프로세스가 번들 잠금을 쥔 채로만 한다(호출자 책임). 같은 내용이면 다시 쓰지 않는다.
  · 능력 기록은 ``record_probe`` 하나(수집 탐침·브리지 capability 모두). ``history`` 는 최근 30건(오래된 것부터 버리고
    버린 수는 ``history_dropped``), ``verdict`` 는 ``verdict()`` 만 계산한다(계약 §6.4 — 6단계).
  · ``anchor_since`` 는 처음 한 번만 정하고 바꾸지 않는다(그보다 앞선 흔적은 그 PC 의 증거로 쓰지 않는다).
  · ``host_display`` 는 로컬 화면 표시 전용이다 — 팀 묶음 빌더는 읽지 않는다(L-22).
"""
import os
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.collect import rcmap as _rcmap
from lm27.util import fsx

SCHEMA = "lm27.pc/1"
HISTORY_MAX = 30
VISITS_MAX = 200
STATUSES = ("ok", "fail", "transport_fail", "unknown")
VERDICTS = ("미확인", "가능", "불가(잠정)", "불가(확정)")
# 계약 §6.1 '확정 ✔' 사유 — 서로 다른 날 collect.confirmBlockedCount 회면 '불가(확정)' 근거가 된다.
# 코드 단일원은 lm27.collect.rcmap.CONFIRMABLE(X-336) — 표를 두 벌 두지 않고 그것을 쓴다.
CONFIRMABLE = _rcmap.CONFIRMABLE
DEFAULT_ROLES = {"cloud": ("pc_usage", "account_backfill", "copilot")}
DEFAULT_ROLES_PC = ("pc_usage", "mail_local", "teams_window")
LOWSPACE_MB = 500
LONGPATH_ROOT = 140
FLAG_COLLISION = "pc_id_collision"

_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_KEY_RX = re.compile(r"^[a-z][a-z0-9_.]{1,47}$")
_RCODE_RX = re.compile(r"^R-[A-Z]{2,}(-[A-Z0-9]+)*$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _now(now=None) -> str:
    return now or fsx.utcnow_iso()


def today_local(now_utc=None) -> date:
    """이 PC 의 로컬 날짜(수집 순간 오프셋 — lm27.util.tz)."""
    from lm27.util import tz
    u = datetime.now(UTC) if now_utc is None else now_utc
    return (u + timedelta(minutes=tz.capture_offset_min(u))).date()


def _as_date(d):
    if d is None:
        return today_local()
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str) and _DATE_RX.match(d):
        return date.fromisoformat(d)
    raise ValueError("날짜는 YYYY-MM-DD")


def _pc_of(pcdir) -> str:
    pc_id = Path(pcdir).name
    if not _PC_RX.match(pc_id):
        raise ValueError("pcreg: pcdir 이름이 pc_id 가 아닙니다")
    return pc_id


def _cfg_int(cfg, key):
    """설정 값(정수). cfg 가 없으면 레지스트리 선언 기본값."""
    if cfg is not None:
        return int(cfg[key])
    from lm27.config import registry_meta
    return int(registry_meta(key).default)


# ── 읽기·쓰기 ────────────────────────────────────────────────────────────────
def load_pc(pcdir):
    """pc.json(dict) — 없거나 깨졌으면 None."""
    pc_id = _pc_of(pcdir)
    obj = fsx.read_json(Path(pcdir) / "pc.json", None, want=dict)
    if not obj or obj.get("pc_id") != pc_id:
        return None
    return obj


def _skeleton(pc_id: str, now: str) -> dict:
    return {"schema": SCHEMA, "pc_id": pc_id, "id_source": "machineguid", "label_auto": "", "label_user": "",
            "host_display": "", "host_class": "", "kind": "desktop", "kind_evidence": {}, "kind_confirmed": False,
            "tz": {"utc_offset_min": None, "windows_tz": "", "changes": []}, "roles": list(DEFAULT_ROLES_PC),
            "first_seen": now, "last_seen": now, "anchor_since": now, "installs": [], "visits": [], "flags": [],
            "capabilities": {}}


def save_pc(pcdir, pc: dict) -> bool:
    """pc.json 원자 쓰기 — 바이트가 같으면 쓰지 않는다. 썼으면 True."""
    pc_id = _pc_of(pcdir)
    if not isinstance(pc, dict) or pc.get("pc_id") != pc_id:
        raise ValueError("save_pc: pc_id 가 폴더와 다릅니다")
    pc["schema"] = SCHEMA
    data = fsx.canon_bytes(pc)
    p = Path(pcdir) / "pc.json"
    if os.path.isfile(fsx.longp(p)) and fsx.read_bytes(p) == data:
        return False
    fsx.atomic_write(p, data)
    return True


def update_pc(pcdir, changes=None, *, fn=None, now=None) -> dict:
    """pc.json 을 고친다 — ``changes``(최상위 키 덮어쓰기) 또는 ``fn(pc) -> pc``. 없으면 뼈대에서 시작한다."""
    pc_id = _pc_of(pcdir)
    pc = load_pc(pcdir) or _skeleton(pc_id, _now(now))
    if changes:
        for k, v in changes.items():
            if k in ("schema", "pc_id"):
                continue
            pc[k] = v
    if fn is not None:
        pc = fn(pc) or pc
    save_pc(pcdir, pc)
    return pc


def list_pcs(paths) -> list:
    r"""``data\pcs`` 아래 pc_id 폴더 이름 목록(정렬). 형식이 아닌 항목(.probe_* 등)은 뺀다."""
    try:
        names = os.listdir(fsx.longp(paths.pcs()))
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(n for n in names if _PC_RX.match(n) and os.path.isdir(fsx.longp(paths.pc_dir(n))))


def load_all_pcs(paths) -> list:
    """모든 PC 의 pc.json(읽히는 것만, pc_id 순)."""
    out = []
    for pid in list_pcs(paths):
        pc = load_pc(paths.pc_dir(pid))
        if pc:
            out.append(pc)
    return out


def _profile_ctime_iso():
    up = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    try:
        t = os.stat(up).st_ctime
    except OSError:
        return None
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_label(paths, pc_id: str, kind: str) -> str:
    others = [p for p in load_all_pcs(paths) if p.get("pc_id") != pc_id]
    if kind == "cloud":
        n = sum(1 for p in others if p.get("kind") == "cloud")
        return "클라우드PC" if n == 0 else f"클라우드PC{n + 1}"
    n = sum(1 for p in others if p.get("kind") != "cloud")
    return f"PC{n + 1}"


def ensure_pc_dir(paths, ident, *, host=None, host_class=None, anchor_since=None, now=None) -> Path:
    r"""``pcs\<pc_id>\`` 와 pc.json 을 보장한다(설치 전용 진입점의 최소 기록: 식별·kind·tz·installs).
    이미 있으면 last_seen·installs·tz 변화만 갱신한다. 다른 pc_id 폴더는 손대지 않는다. 반환: pcdir."""
    pcdir = paths.pc_dir(ident.pc_id)
    fsx.ensure_dir(pcdir)
    now = _now(now)
    pc = load_pc(pcdir)
    tz = dict(getattr(ident, "tz", None) or {})
    if pc is None:
        pc = _skeleton(ident.pc_id, now)
        kind = ident.kind_guess if getattr(ident, "kind_guess", None) in ("desktop", "laptop", "vdi", "cloud") \
            else "desktop"
        anchor = anchor_since or min(x for x in (now, _profile_ctime_iso()) if x)
        pc.update({"id_source": ident.id_source, "label_auto": _next_label(paths, ident.pc_id, kind),
                   "host_display": host if host is not None else os.environ.get("COMPUTERNAME", ""),
                   "host_class": host_class or "", "kind": kind,
                   "kind_evidence": dict(getattr(ident, "kind_evidence", None) or {}),
                   "tz": {"utc_offset_min": tz.get("utc_offset_min"), "windows_tz": tz.get("windows_tz") or "",
                          "changes": []},
                   "roles": list(DEFAULT_ROLES.get(kind, DEFAULT_ROLES_PC)), "anchor_since": anchor})
    else:
        pc["last_seen"] = max(pc.get("last_seen") or now, now)
        if host_class and not pc.get("host_class"):
            pc["host_class"] = host_class
        old = pc.get("tz") or {}
        if tz.get("utc_offset_min") is not None and old.get("utc_offset_min") != tz.get("utc_offset_min"):
            changes = list(old.get("changes") or [])
            changes.append({"at": now, "from": old.get("utc_offset_min"), "to": tz.get("utc_offset_min")})
            pc["tz"] = {"utc_offset_min": tz.get("utc_offset_min"), "windows_tz": tz.get("windows_tz") or "",
                        "changes": changes[-20:]}
    _add_install(pc, ident.install_id, now)
    save_pc(pcdir, pc)
    return pcdir


def _add_install(pc: dict, install_id: str, now: str, impl=None) -> None:
    ins = pc.setdefault("installs", [])
    for e in ins:
        if isinstance(e, dict) and e.get("install_id") == install_id:
            if impl and e.get("impl") != impl:
                e["impl"] = impl
            return
    ins.append({"install_id": install_id, "created": now, "task": f"LM27-{install_id}", "impl": impl})


def touch_visit(pcdir, ident, *, manifest_gen=None, impl=None, now=None) -> dict:
    """[수집] 한 번의 방문 기록: last_seen · visits(최근 200) · installs."""
    now = _now(now)

    def fn(pc):
        pc["last_seen"] = max(pc.get("last_seen") or now, now)
        _add_install(pc, ident.install_id, now, impl)
        v = list(pc.get("visits") or [])
        v.append({"at": now, "install_id": ident.install_id, "agent_ver": ident.agent_ver,
                  "manifest_gen": manifest_gen})
        pc["visits"] = v[-VISITS_MAX:]
        return pc
    return update_pc(pcdir, fn=fn, now=now)


# ── 능력 기록·판정 ───────────────────────────────────────────────────────────
def _clean_hist(history) -> list:
    out = []
    for h in history or ():
        if isinstance(h, dict) and h.get("status") in STATUSES and isinstance(h.get("date"), str) \
                and _DATE_RX.match(h["date"]):
            out.append(h)
    return out


def verdict(history, cfg=None, *, today=None) -> str:
    """능력 판정 — 계약 §6.4 의 유일 구현. history = 오래된 것부터 ``{date, status, reasons, probe_sig}``.

    1. 기록이 없으면 ``미확인``.  2. 가장 최근 기록이 ``ok`` 면 ``가능``.
    3. 판정 창 = 마지막 ``ok`` 이후이면서 현재(가장 최근 기록의) ``probe_sig`` 와 같은 기록(탐침 값이 바뀌면 그 전 실패는
       세지 않는다 = 자동 해제).
    4. 창 안 ``fail`` 에서 '확정 ✔' 사유별로 서로 다른 날짜 수를 센다. 어떤 사유가 ``collect.confirmBlockedCount`` 이상이고
       그 사유의 마지막 확인이 ``collect.confirmTtlDays`` 안이면 ``불가(확정)``(TTL 이 지나면 ``불가(잠정)`` 로 내려간다).
    5. 창 안에 ``fail`` 이 있으면 ``불가(잠정)``.  6. 그 밖(``transport_fail``·``unknown`` 만)은 ``미확인``."""
    hist = _clean_hist(history)
    if not hist:
        return "미확인"
    if hist[-1]["status"] == "ok":
        return "가능"
    last_ok = max((i for i, h in enumerate(hist) if h["status"] == "ok"), default=-1)
    sig = hist[-1].get("probe_sig")
    window = [h for h in hist[last_ok + 1:] if h.get("probe_sig") == sig]
    fails = [h for h in window if h["status"] == "fail"]
    if not fails:
        return "미확인"
    need = _cfg_int(cfg, "collect.confirmBlockedCount")
    ttl = _cfg_int(cfg, "collect.confirmTtlDays")
    t = _as_date(today)
    days_by = {}
    for h in fails:
        for r in h.get("reasons") or ():
            if r in CONFIRMABLE:
                days_by.setdefault(r, set()).add(h["date"])
    for _r, days in sorted(days_by.items()):
        if len(days) >= need and (t - date.fromisoformat(max(days))).days <= ttl:
            return "불가(확정)"
    return "불가(잠정)"


def record_probe(pcdir, key, ok, value, reasons, status=None, *, probe_sig=None, date=None, cfg=None,
                 today=None, now=None) -> dict:
    """능력 기록 하나를 pc.json ``capabilities[key]`` 에 남기고 그 항목을 돌려준다(쓰기는 이 함수 하나).
    ``status`` 가 없으면 ok 에서(True → ok · False → fail · None → unknown). ``date`` = 탐침 로컬 날짜(기본 오늘).
    탐침은 내용 0바이트 — value 에는 숫자·열거·사유 코드만 담는다(호출자 책임)."""
    if not isinstance(key, str) or not _KEY_RX.match(key):
        raise ValueError("record_probe: 능력 키 형식이 아닙니다")
    if status is None:
        status = "ok" if ok is True else ("fail" if ok is False else "unknown")
    if status not in STATUSES:
        raise ValueError("record_probe: status 는 ok·fail·transport_fail·unknown")
    rs = sorted(set(reasons or ()))
    for r in rs:
        if not isinstance(r, str) or not _RCODE_RX.match(r):
            raise ValueError("record_probe: 사유 코드 형식이 아닙니다")
    d = _as_date(date if date is not None else today).isoformat()
    entry_out = {}

    def fn(pc):
        caps = pc.setdefault("capabilities", {})
        ent = dict(caps.get(key) or {})
        hist = list(ent.get("history") or [])
        hist.append({"date": d, "status": status, "reasons": rs, "probe_sig": probe_sig})
        dropped = int(ent.get("history_dropped") or 0)
        if len(hist) > HISTORY_MAX:
            dropped += len(hist) - HISTORY_MAX
            hist = hist[-HISTORY_MAX:]
        ent.update({"ok": ok, "value": value, "reasons": rs, "history": hist,
                    "verdict": verdict(hist, cfg, today=today if today is not None else d)})
        if dropped:
            ent["history_dropped"] = dropped
        caps[key] = ent
        entry_out.update(ent)
        return pc
    update_pc(pcdir, fn=fn, now=now)
    return entry_out


def refresh_verdicts(pcdir, cfg=None, *, today=None) -> dict:
    """모든 능력의 verdict 를 오늘 기준으로 다시 계산(TTL 경과 반영). 반환: {키: verdict}."""
    out = {}

    def fn(pc):
        for k, ent in sorted((pc.get("capabilities") or {}).items()):
            if isinstance(ent, dict):
                ent["verdict"] = verdict(ent.get("history"), cfg, today=today)
                out[k] = ent["verdict"]
        return pc
    update_pc(pcdir, fn=fn)
    return out


# ── GUID 충돌(같은 pc_id 를 두 기계가 씀) ─────────────────────────────────────
def _utc(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def mark_collisions(pcdir, *, tol_min=10, manifest=None) -> bool:
    """같은 pc_id 아래 install_id 가 둘 이상이고 pc_session 세그먼트 구간이 ``tol_min`` 분 넘게 겹치면
    pc.json ``flags`` 에 ``pc_id_collision``(TAB §1.8). 표시만 하고 지우지 않는다. 반환: 충돌인가."""
    if manifest is None:
        from lm27.bundle.manifest import load_manifest
        manifest = load_manifest(pcdir)
    spans = {}
    for s in manifest.get("segments", ()):
        if s.get("kind") != "pc_session" or not (_UTC_RX.match(str(s.get("t0"))) and _UTC_RX.match(str(s.get("t1")))):
            continue
        spans.setdefault(s.get("install_id"), []).append((_utc(s["t0"]), _utc(s["t1"])))
    tol = timedelta(minutes=tol_min)
    insts = sorted(i for i in spans if isinstance(i, str))
    hit = False
    for i, a in enumerate(insts):
        for b in insts[i + 1:]:
            for a0, a1 in spans[a]:
                for b0, b1 in spans[b]:
                    if min(a1, b1) - max(a0, b0) > tol:
                        hit = True
    if hit:
        def fn(pc):
            fl = list(pc.get("flags") or [])
            if FLAG_COLLISION not in fl:
                fl.append(FLAG_COLLISION)
            pc["flags"] = fl
            return pc
        update_pc(pcdir, fn=fn)
    return hit


# ── 번들 도착 경로 탐침(P-BUNDLE) ────────────────────────────────────────────
class _WinLocProbe:
    """도착 경로 측정(읽기 전용 + 쓰기 시험 1회). 시험은 같은 메서드를 가진 가짜를 넣는다."""

    def drive_type(self, root: str) -> int:
        import ctypes
        drv = os.path.splitdrive(root)[0]
        if drv.startswith("\\\\"):
            base = drv + "\\"
        else:
            base = (drv or root[:2]) + "\\"
        try:
            return int(ctypes.windll.kernel32.GetDriveTypeW(base))
        except OSError:
            return 0

    def onedrive_roots(self) -> list:
        return [v for v in (os.environ.get(k) for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")) if v]

    def file_attrs(self, path: str) -> int:
        import ctypes
        try:
            v = int(ctypes.windll.kernel32.GetFileAttributesW(fsx.longp(path)))
        except OSError:
            return 0
        return 0 if v == 0xFFFFFFFF else v

    def known_folders(self) -> list:
        import ctypes
        import uuid
        from ctypes import wintypes
        out = []
        for g in ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"):
            guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(g).bytes_le)
            p = ctypes.c_wchar_p()
            try:
                hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(p))
            except OSError:
                continue
            if hr == 0 and p.value:
                out.append(p.value)
            if p:
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(p, wintypes.LPVOID))
        return out

    def free_mb(self, path: str) -> int:
        try:
            return int(shutil.disk_usage(path).free // (1 << 20))
        except OSError:
            return -1

    def try_write(self, paths) -> bool:
        r"""``data\pcs\.probe_<rand>`` 를 만들고 지운다."""
        p = paths.pcs() / f".probe_{os.urandom(4).hex()}"
        try:
            fsx.atomic_write(p, b"", fsync=False)
        except OSError:
            return False
        try:
            os.remove(fsx.longp(p))
        except OSError:
            pass
        return True


def _under(path: str, base: str) -> bool:
    if not base:
        return False
    a = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    b = os.path.normcase(os.path.abspath(base)).rstrip("\\/")
    return a == b or a.startswith(b + os.sep)


def probe_bundle_location(paths, *, probe=None) -> dict:
    """P-BUNDLE: 번들 도착 경로 측정(잠금 없이). 반환 ``{ok, status, value{drive_type, onedrive, redirected, network,
    writable, free_mb, root_len}, reasons}`` — 경고 사유는 수집을 막지 않고, 쓰기 불가만 ok=False(R-BUNDLE-READONLY)."""
    pr = probe if probe is not None else _WinLocProbe()
    root = str(paths.root)
    dt = int(pr.drive_type(root))
    network = dt == 4 or root.startswith("\\\\")
    onedrive = any(_under(root, r) for r in pr.onedrive_roots())
    if not onedrive:
        attrs = pr.file_attrs(str(paths.data())) or pr.file_attrs(root)
        onedrive = bool(attrs & 0x400000) or bool(attrs & 0x1000)
    redirected = any(k.startswith("\\\\") and _under(root, k) for k in pr.known_folders())
    writable = bool(pr.try_write(paths))
    free = int(pr.free_mb(root))
    value = {"drive_type": {2: "removable", 3: "fixed", 4: "network"}.get(dt, "other"), "onedrive": onedrive,
             "redirected": redirected, "network": network, "writable": writable, "free_mb": free,
             "root_len": len(root)}
    reasons = []
    if network:
        reasons.append("R-BUNDLE-NETWORK")
    if onedrive:
        reasons.append("R-BUNDLE-ONEDRIVE")
    if redirected:
        reasons.append("R-BUNDLE-REDIRECT")
    if not writable:
        reasons.append("R-BUNDLE-READONLY")
    if 0 <= free < LOWSPACE_MB:
        reasons.append("R-BUNDLE-LOWSPACE")
    if len(root) > LONGPATH_ROOT:
        reasons.append("R-BUNDLE-LONGPATH")
    return {"ok": writable, "status": "ok" if writable else "fail", "value": value, "reasons": reasons}
