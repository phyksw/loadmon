# -*- coding: utf-8 -*-
r"""단일 로더(계약 §2.6, TAB §1.15) — ``data\pcs`` 를 읽는 유일한 모듈(L-08). 번들 읽기는 잠금 없이 한다.

  · ``iter_records(paths, kind, d0, d1, *, pcs, dedupe)``: 모든 pc_id 의 manifest 를 열거 → 기간과 겹치는 세그먼트만 →
    무덤표(모든 PC manifest 의 old_sha256 합집합) 제외 → sha 검증 → 레코드. 각 레코드에 ``_pc``(pc_id) ·
    ``_inst``(install_id) · ``_lpc``(논리 PC) 를 붙인 **사본**만 위로 넘긴다.
  · dedupe: 같은 ``(kind, id)`` 는 **observed_at 최대** 하나(계약 §3.10·X-032 — 진행 중 구간의 새 판은 덧붙이고 로더가
    최신을 고른다, T-11). 출처 간 msg_key 병합은 하지 않는다(정규화 소관).
  · 기간: d0·d1 = 로컬 날짜. 일자 경계는 **사람 근무 시간대**(``time.tzOffsetMin``)로 계산한다 — PC 의 수집 오프셋이
    UTC(클라우드PC)여도 같은 날로 묶인다(TAB B09).
  · 소급 가림 읽기 오버레이(``local_only\redact_overlay.json``, P §12.5)를 적용한다 — 걸린 행은 텍스트 열(``*_masked``)을
    비운 사본. 재정제(G2)는 정규화 적재(``lm27.normalize.load``)가 한다(``resanitize=`` 로 넘길 수도 있다).
  · 손상 세그먼트는 건너뛰고(다른 PC 파일은 옮기지 않는다 — 논리 격리), 없는 파일·건너뛴 수·레코드 추정치는
    ``load_report()`` 로 노출한다(조용한 손실 금지). 증거 조회는 ``privacy_audit`` 스트림을 따로 부르지 않는 한 섞지 않는다.
  · ``bundle_status`` · ``verify_bundle`` · ``session_spans`` — 화면·CLI·별칭 판단의 원천.
"""
import os
import re
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import segment as seg
from lm27.util import fsx

EVIDENCE_KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual")
READ_KINDS = EVIDENCE_KINDS + ("privacy_audit",)
OVERLAY_FILE = "redact_overlay.json"
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_OFF = timedelta(hours=14)

_report_lock = threading.Lock()
_last_report = {}


# ── 작은 도구 ────────────────────────────────────────────────────────────────
def _utc(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _as_date(d):
    if d is None or isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str) and _DATE_RX.match(d):
        return date.fromisoformat(d)
    raise ValueError("날짜는 YYYY-MM-DD")


def list_pc_ids(paths) -> list:
    """번들 안 pc_id 폴더 목록(정렬)."""
    try:
        names = os.listdir(fsx.longp(paths.pcs()))
    except (FileNotFoundError, NotADirectoryError):
        return []
    return sorted(n for n in names if _PC_RX.match(n) and os.path.isdir(fsx.longp(paths.pc_dir(n))))


def _manifests(paths, pcs=None, notes=None) -> dict:
    """pc_id → manifest(읽기 전용 — 복구 결과도 메모리에만)."""
    want = set(pcs) if pcs is not None else None
    out = {}
    for pid in list_pc_ids(paths):
        if want is not None and pid not in want:
            continue
        out[pid] = mf.load_manifest(paths.pc_dir(pid), quarantine=False, notes=notes)
    return out


def _all_tombstones(paths, manifests=None) -> set:
    ms = manifests if manifests is not None else _manifests(paths)
    dead = set()
    for m in ms.values():
        dead |= mf.tombstoned_shas(m)
    return dead


def blank_text(row: dict):
    """텍스트 열(이름이 ``_masked`` 로 끝나는 열)을 비운 사본과 바뀌었는지(행 수·키·시간 열은 그대로 — P §12.5)."""
    out, changed = dict(row), False
    for k, v in row.items():
        if not (isinstance(k, str) and k.endswith("_masked")):
            continue
        if isinstance(v, list):
            if v:
                out[k], changed = [], True
        elif isinstance(v, str):
            if v:
                out[k], changed = "", True
    return out, changed


def load_overlay(paths) -> dict:
    r"""``local_only\redact_overlay.json`` = ``{"chat": {chat_key: since UTC}, "msg": [msg_key…]}``(없으면 빈 것)."""
    obj = fsx.read_json(paths.local_only_file(OVERLAY_FILE), None, want=dict) or {}
    chat = obj.get("chat") if isinstance(obj.get("chat"), dict) else {}
    msg = obj.get("msg") if isinstance(obj.get("msg"), list) else []
    return {"chat": {k: v for k, v in chat.items() if isinstance(k, str) and isinstance(v, str)},
            "msg": sorted({m for m in msg if isinstance(m, str)})}


def overlay_hit(row: dict, ov: dict) -> bool:
    """행이 소급 가림 대상인가 — 대화방(chat_key, since 이후) 또는 메시지(msg_key)."""
    if not ov:
        return False
    mk = row.get("msg_key")
    if isinstance(mk, str) and mk in ov.get("msg", ()):
        return True
    ck = row.get("chat_key")
    since = ov.get("chat", {}).get(ck) if isinstance(ck, str) else None
    return since is not None and str(row.get("ts_utc") or "") >= since


def _local_date(ts: str, off_min: int):
    return (_utc(ts) + timedelta(minutes=off_min)).date()


def program_cfg(paths, cfg):
    """설정 — 주어진 cfg, 없으면 그 프로그램 폴더의 ``load_config``(레지스트리가 없는 시험 루트면 None)."""
    if cfg is not None:
        return cfg
    if os.path.isfile(fsx.longp(paths.settings_registry())):
        from lm27.config import load_config
        return load_config(paths)
    return None


def _person_offset(paths, cfg, off_min):
    if off_min is not None:
        return int(off_min)
    cfg = program_cfg(paths, cfg)
    if cfg is None:
        return _registry_default("time.tzOffsetMin")
    return int(cfg["time.tzOffsetMin"])


def _seg_overlaps(s: dict, lo, hi) -> bool:
    t0, t1 = s.get("t0"), s.get("t1")
    if not (isinstance(t0, str) and _UTC_RX.match(t0) and isinstance(t1, str) and _UTC_RX.match(t1)):
        return True                                  # 모르면 읽는다(아래 레코드 단위로 거른다)
    if lo is not None and _utc(t1) < lo:
        return False
    if hi is not None and _utc(t0) >= hi:
        return False
    return True


# ── 레코드 읽기 ──────────────────────────────────────────────────────────────
def _new_report(kind) -> dict:
    return {"kind": kind, "segments_total": 0, "segments_read": 0, "records_read": 0, "records_out": 0,
            "duplicates": 0, "tombstoned": 0, "overlay_rows": 0, "skipped": [], "missing": [], "notes": []}


def iter_records(paths, kind, d0=None, d1=None, *, pcs=None, dedupe=True, overlay=True, off_min=None, cfg=None,
                 resanitize=None):
    """kind 레코드 사본을 (ts_utc, id, _pc) 순으로 낸다. ``pcs`` = pc_id 목록으로 제한, ``off_min`` = 일자 경계 오프셋
    (기본 ``time.tzOffsetMin``), ``resanitize(kind, row) -> row|None`` = 재정제 훅(None 반환 행은 뺀다)."""
    if kind not in READ_KINDS:
        raise ValueError("iter_records: kind 가 아닙니다")
    d0, d1 = _as_date(d0), _as_date(d1)
    off = _person_offset(paths, cfg, off_min) if (d0 is not None or d1 is not None) else 0
    lo = datetime(d0.year, d0.month, d0.day, tzinfo=UTC) - timedelta(minutes=off) if d0 else None
    hi = datetime(d1.year, d1.month, d1.day, tzinfo=UTC) + timedelta(days=1) - timedelta(minutes=off) if d1 else None
    rep = _new_report(kind)
    notes = rep["notes"]
    ms = _manifests(paths, pcs, notes)
    dead = _all_tombstones(paths) if pcs is not None else _all_tombstones(paths, ms)
    from lm27.bundle.aliases import logical_map
    amap = logical_map(paths)
    ov = load_overlay(paths) if overlay and kind != "privacy_audit" else None
    best = {}
    order = 0
    for pid in sorted(ms):
        m = ms[pid]
        pcdir = paths.pc_dir(pid)
        segs = [s for s in m["segments"] if s.get("kind") == kind]
        segs.sort(key=lambda s: (str(s.get("created") or ""), s.get("seq") or 0, s.get("file") or ""))
        for s in segs:
            rep["segments_total"] += 1
            if s.get("sha256") in dead:
                rep["tombstoned"] += 1
                continue
            if not _seg_overlaps(s, lo, hi):
                continue
            path = pcdir.joinpath(*str(s.get("file")).split("/"))
            n_est = s.get("n") if isinstance(s.get("n"), int) else None
            try:
                data = fsx.read_bytes(path)
            except FileNotFoundError:
                rep["missing"].append({"pc_id": pid, "file": s.get("file"), "n_est": n_est})
                continue
            except OSError:
                rep["skipped"].append({"pc_id": pid, "file": s.get("file"), "reason": "unreadable", "n_est": n_est})
                continue
            try:
                head, recs = seg.parse_segment_bytes(data, expect_sha=s.get("sha256"), name=path.name)
            except seg.SegmentCorrupt as e:
                rep["skipped"].append({"pc_id": pid, "file": s.get("file"), "reason": e.reason, "n_est": n_est})
                continue
            if head.get("pc_id") != pid:
                rep["skipped"].append({"pc_id": pid, "file": s.get("file"), "reason": "foreign_pc", "n_est": n_est})
                continue
            rep["segments_read"] += 1
            inst = head.get("install_id")
            for r in recs:
                rep["records_read"] += 1
                ts = r.get("ts_utc")
                if (d0 or d1) and isinstance(ts, str) and _UTC_RX.match(ts):
                    ld = _local_date(ts, off)
                    if (d0 and ld < d0) or (d1 and ld > d1):
                        continue
                row = dict(r)
                if ov is not None and overlay_hit(row, ov):
                    row, ch = blank_text(row)
                    if ch:
                        rep["overlay_rows"] += 1
                if resanitize is not None:
                    row = resanitize(kind, row)
                    if row is None:
                        continue
                row["_pc"], row["_inst"], row["_lpc"] = pid, inst, amap.get(pid, pid)
                order += 1
                key = row.get("id") if dedupe else order
                cur = best.get(key)
                if cur is None:
                    best[key] = row
                else:
                    rep["duplicates"] += 1
                    if str(row.get("observed_at") or "") > str(cur.get("observed_at") or ""):
                        best[key] = row
    out = sorted(best.values(), key=lambda r: (str(r.get("ts_utc") or ""), str(r.get("id") or ""), r["_pc"]))
    rep["records_out"] = len(out)
    with _report_lock:
        _last_report.clear()
        _last_report.update(rep)
    yield from out


def load_report() -> dict:
    """마지막 ``iter_records`` 의 읽기 보고(건너뛴 세그먼트·없는 파일·레코드 추정치·중복·무덤표·오버레이)."""
    with _report_lock:
        out = dict(_last_report)
    for k in ("skipped", "missing", "notes"):
        if k in out:
            out[k] = [dict(x) for x in out[k]]
    return out


def session_spans(paths, pc_id) -> list:
    """그 PC 의 pc_session 세그먼트 구간 [(t0, t1)](정렬) — 논리 PC 판단(별칭)의 근거."""
    if not _PC_RX.match(pc_id or ""):
        raise ValueError("pc_id 형식이 아닙니다")
    if not os.path.isdir(fsx.longp(paths.pc_dir(pc_id))):
        return []
    m = mf.load_manifest(paths.pc_dir(pc_id), quarantine=False)
    dead = mf.tombstoned_shas(m)
    out = [(s["t0"], s["t1"]) for s in m["segments"]
           if s.get("kind") == "pc_session" and s.get("sha256") not in dead
           and _UTC_RX.match(str(s.get("t0"))) and _UTC_RX.match(str(s.get("t1")))]
    return sorted(out)


# ── 검증·상태 ────────────────────────────────────────────────────────────────
def _load_cache(paths) -> dict:
    return fsx.read_json(paths.verify_cache(), {}, want=dict) or {}


def _save_cache(paths, cache: dict, before: bytes) -> None:
    data = fsx.canon_bytes(cache)
    if data != before:
        fsx.atomic_write(paths.verify_cache(), data, fsync=False)


def check_segment(paths, pc_id, s: dict, cache=None, *, deep=True) -> str:
    """manifest 항목 하나 검증 → '' 정상 · 'missing' · 'size_mismatch' · 'sha_mismatch' · 손상 사유.
    검증 캐시(``derived\\verify_cache.json``)에 크기·mtime 이 같은 통과 기록이 있으면 다시 해시하지 않는다."""
    path = paths.pc_dir(pc_id).joinpath(*str(s.get("file")).split("/"))
    lp = fsx.longp(path)
    try:
        st = os.stat(lp)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if isinstance(s.get("bytes"), int) and st.st_size != s["bytes"]:
        return "size_mismatch"
    rel = f"{pc_id}/{s.get('file')}"
    if cache is not None:
        c = cache.get(rel)
        if isinstance(c, dict) and c.get("size") == st.st_size and c.get("mtime_ns") == st.st_mtime_ns \
                and c.get("sha256") == s.get("sha256") and c.get("ok") is True:
            return ""
    if not deep:
        return ""
    try:
        data = fsx.read_bytes(path)
        seg.parse_segment_bytes(data, expect_sha=s.get("sha256"), name=path.name)
        why = ""
    except seg.SegmentCorrupt as e:
        why = e.reason
    except OSError:
        why = "unreadable"
    if cache is not None:
        cache[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": s.get("sha256"), "ok": why == ""}
    return why


def verify_bundle(paths, *, use_cache=False) -> dict:
    """모든 PC 의 세그먼트 sha·형식을 검증한다(읽기 전용 — 격리는 그 PC 의 쓰기 주체가 한다).
    반환 ``{rc, checked, bad[{pc_id, file, reason}], tombstoned}`` — rc 0 정상 · 2 문제 있음 · 4 번들 없음."""
    ms = _manifests(paths)
    if not ms:
        return {"rc": 4, "checked": 0, "bad": [], "tombstoned": 0}
    cache = _load_cache(paths)
    before = fsx.canon_bytes(cache)
    dead = _all_tombstones(paths, ms)
    bad, checked, tomb = [], 0, 0
    for pid in sorted(ms):
        for s in ms[pid]["segments"]:
            if s.get("sha256") in dead:
                tomb += 1
                continue
            checked += 1
            fresh = cache if use_cache else {}
            why = check_segment(paths, pid, s, fresh)
            if not use_cache:
                cache.update(fresh)
            if why:
                bad.append({"pc_id": pid, "file": s.get("file"), "reason": why})
        for b in ms[pid].get("_bad", ()):
            bad.append({"pc_id": pid, "file": b.get("file"), "reason": b.get("reason")})
    _save_cache(paths, cache, before)
    return {"rc": 2 if bad else 0, "checked": checked, "bad": bad, "tombstoned": tomb}


def _dir_bytes(path) -> int:
    total = 0
    for dp, _dn, fns in os.walk(fsx.longp(path)):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def _mb(n: int) -> float:
    return round(n / (1 << 20), 1)


def arrival_missing(paths, ms=None) -> list:
    r"""``pcs\*\move_ready.json`` 대비 없는·크기 다른 세그먼트(TAB §1.12 — sha 는 ``verify_bundle``).
    move_ready 보다 manifest 가 새것이면 기준은 manifest 다."""
    ms = ms if ms is not None else _manifests(paths)
    out = []
    for pid in sorted(ms):
        pcdir = paths.pc_dir(pid)
        mr = fsx.read_json(paths.move_ready(pid), None, want=dict)
        if not mr:
            continue
        m = ms[pid]
        if isinstance(mr.get("manifest_gen"), int) and mr["manifest_gen"] >= int(m.get("gen") or 0):
            items = [(x[0], x[2]) for x in mr.get("segments") or () if isinstance(x, list) and len(x) >= 3]
        else:
            dead = mf.tombstoned_shas(m)
            items = [(s.get("file"), s.get("bytes")) for s in m["segments"] if s.get("sha256") not in dead]
        seen = mr.get("other_pcs_seen") if isinstance(mr.get("other_pcs_seen"), dict) else {}
        for other, n in sorted(seen.items()):
            if isinstance(other, str) and _PC_RX.match(other) and other not in ms \
                    and not any(x["pc_id"] == other and x["file"] is None for x in out):
                out.append({"pc_id": other, "file": None, "expected": n, "state": "폴더 없음"})
        for rel, size in items:
            if not isinstance(rel, str) or not rel.startswith("seg/"):
                continue
            p = pcdir.joinpath(*rel.split("/"))
            try:
                st = os.stat(fsx.longp(p))
            except FileNotFoundError:
                out.append({"pc_id": pid, "file": rel, "expected": size, "state": "없음"})
                continue
            except OSError:
                out.append({"pc_id": pid, "file": rel, "expected": size, "state": "읽기 불가"})
                continue
            if isinstance(size, int) and st.st_size != size:
                out.append({"pc_id": pid, "file": rel, "expected": size, "state": "크기 다름"})
    return out


def bundle_status(paths, cfg=None) -> dict:
    """PC 별 현황(라벨·kind·첫/마지막 방문·kind 별 세그먼트·레코드 수·gaps·격리·observed_from·agent_status·탐침 verdict·
    move_ready 대비 누락)과 번들 크기(``bundle.warnSizeMb`` 초과 경고). rc 0 정상 · 2 확인 필요 · 4 번들 없음."""
    from lm27.bundle import pcreg
    from lm27.bundle.aliases import logical_map
    notes = []
    ms = _manifests(paths, notes=notes)
    bj = fsx.read_json(paths.bundle_json(), None, want=dict)
    if not ms and not bj:
        return {"rc": 4, "bundle": None, "pcs": [], "notes": notes}
    amap = logical_map(paths)
    missing = arrival_missing(paths, ms)
    pcs_out, total, problems = [], 0, bool(missing)
    for pid in sorted(ms):
        m = ms[pid]
        pc = pcreg.load_pc(paths.pc_dir(pid)) or {}
        dead = mf.tombstoned_shas(m)
        kinds = {}
        for s in m["segments"]:
            if s.get("sha256") in dead:
                continue
            k = kinds.setdefault(s.get("kind"), {"segments": 0, "records": 0, "bytes": 0})
            k["segments"] += 1
            k["records"] += s.get("n") if isinstance(s.get("n"), int) else 0
            k["bytes"] += s.get("bytes") if isinstance(s.get("bytes"), int) else 0
        size = _dir_bytes(paths.pc_dir(pid))
        total += size
        caps = pc.get("capabilities") if isinstance(pc.get("capabilities"), dict) else {}
        if m.get("_recovered") or m.get("quarantine") or m.get("_bad"):
            problems = True
        pcs_out.append({
            "pc_id": pid, "label_auto": pc.get("label_auto", ""), "label_user": pc.get("label_user", ""),
            "kind": pc.get("kind"), "logical": amap.get(pid, pid), "first_seen": pc.get("first_seen"),
            "last_seen": pc.get("last_seen"), "flags": pc.get("flags", []), "manifest_gen": m.get("gen"),
            "manifest_recovered": m.get("_recovered"), "kinds": kinds, "gaps": m.get("gaps", []),
            "quarantine": m.get("quarantine", []) + m.get("_bad", []), "observed_from": m.get("observed_from", {}),
            "agent_status": m.get("agent_status"), "mb": _mb(size),
            "verdicts": {k: v.get("verdict") for k, v in sorted(caps.items()) if isinstance(v, dict)},
            "missing": [x for x in missing if x["pc_id"] == pid]})
    total += sum(_file_size(p) for p in (paths.bundle_json(), paths.pc_aliases()))
    cfg = program_cfg(paths, cfg)
    warn_mb = int(cfg["bundle.warnSizeMb"]) if cfg is not None else _registry_default("bundle.warnSizeMb")
    return {"rc": 2 if problems else 0, "bundle": _bundle_public(bj), "pcs": pcs_out, "total_mb": _mb(total),
            "warn_size_mb": warn_mb, "over_size": _mb(total) > warn_mb, "derived_mb": _mb(_dir_bytes(paths.derived())),
            "notes": notes}


def _registry_default(key):
    from lm27.config import registry_meta
    return int(registry_meta(key).default)


def _file_size(p) -> int:
    try:
        return os.path.getsize(fsx.longp(p))
    except OSError:
        return 0


def _bundle_public(bj):
    if not isinstance(bj, dict):
        return None
    return {k: bj.get(k) for k in ("schema", "bundle_id", "created_at", "created_on_pc", "lm27_version")}


def pc_dir_of(paths, pc_id) -> Path:
    """시험·화면용: pc_id 폴더 경로(존재 확인 없음)."""
    return paths.pc_dir(pc_id)
