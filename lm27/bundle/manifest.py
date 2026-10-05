# -*- coding: utf-8 -*-
r"""PC 별 manifest ``lm27.manifest/1``(계약 §3.7, TAB §1.4) — 세그먼트 sha256 집합 + 내보내기 커서 + 무덤표.

``{schema, pc_id, gen, updated_at, segments:[{kind, seq, file, install_id, t0, t1, n, bytes, sha256, rules_ver, kid,
created, src_to}], cursors:{<install_id>:{"<kind>/<src>":{file, offset, last_ts}}}, observed_from:{<install_id>: UTC},
gaps:[{install_id, stream, from_t, to_t, reason}], tombstones:[...], quarantine:[...], agent_status:{…}}``

  · manifest = 세그먼트 sha256 의 집합(D-18) — 두 사본 번들 합치기는 sha 합집합이므로 멱등이다.
  · 저장(``save_manifest``): ``gen`` +1 → 지금 manifest.json(읽히는 것일 때만)을 manifest.prev.json 으로 복사 →
    ``atomic_write(manifest.json)``.
  · 읽기(``load_manifest``) 실패 시 자동 복구: ① manifest.prev.json ② ``rebuild_manifest`` = ``seg\**\*.jsonl.gz`` 전수
    스캔 → 머리말·꼬리말·sha 로 목록 재구성, 커서는 (install, ``<kind>/<src>``) 별 가장 앞선 ``src_to``, 무덤표는
    ``quarantine\tombstones.json`` 사본에서. 사용자에게 묻지 않고 "목록을 다시 만들었습니다(세그먼트 N개)" 만 알린다.
    복구 결과는 메모리에만 있다 — 저장은 그 PC 의 쓰기 주체가 잠금을 쥐고 ``save_manifest`` 로 한다.
  · 고아 편입(``adopt_orphans``): manifest 에 없는 세그먼트 파일을 검증해 편입하고(커서는 고아의 ``src_to`` 로 전진),
    검증 실패·무덤표에 오른 고아는 그 PC 자기 폴더의 ``quarantine\`` 로 옮긴다(지우지 않는다).
  · 밑줄로 시작하는 키(``_recovered`` 등)는 메모리 표지이며 저장하지 않는다.
"""
import os
import re
from pathlib import Path

from lm27.bundle import segment as seg
from lm27.util import events, fsx

SCHEMA = "lm27.manifest/1"
TOMBSTONES_COPY = "tombstones.json"
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_LIST_KEYS = ("segments", "gaps", "tombstones", "quarantine")
_DICT_KEYS = ("cursors", "observed_from")


def new_manifest(pc_id: str) -> dict:
    return {"schema": SCHEMA, "pc_id": pc_id, "gen": 0, "updated_at": None, "segments": [], "cursors": {},
            "observed_from": {}, "gaps": [], "tombstones": [], "quarantine": [], "agent_status": None}


def _pc_of(pcdir) -> str:
    pc_id = Path(pcdir).name
    if not _PC_RX.match(pc_id):
        raise ValueError("manifest: pcdir 이름이 pc_id 가 아닙니다")
    return pc_id


def _valid(m, pc_id) -> bool:
    if not isinstance(m, dict) or m.get("schema") != SCHEMA or m.get("pc_id") != pc_id:
        return False
    if not isinstance(m.get("gen"), int) or isinstance(m.get("gen"), bool):
        return False
    if any(not isinstance(m.get(k), list) for k in _LIST_KEYS):
        return False
    if any(not isinstance(m.get(k), dict) for k in _DICT_KEYS):
        return False
    return all(isinstance(s, dict) and isinstance(s.get("sha256"), str) and isinstance(s.get("file"), str)
               for s in m["segments"])


def _read_manifest_file(path, pc_id):
    if not os.path.isfile(fsx.longp(path)):
        return None
    m = fsx.read_json(path, None, want=dict)
    return m if _valid(m, pc_id) else False


def load_manifest(pcdir, *, quarantine=False, notes=None) -> dict:
    r"""manifest 를 읽는다. 없으면 빈 manifest(세그먼트 파일이 있으면 재구성), 깨졌으면 prev → 재구성.
    ``quarantine=True`` 면 재구성 중 검증 실패 세그먼트를 그 PC 의 ``quarantine\`` 로 옮긴다(그 PC 의 쓰기 주체만).
    ``notes`` 목록을 주면 복구 사실을 ``{"code", "n"}`` 로 덧붙인다."""
    pcdir = Path(pcdir)
    pc_id = _pc_of(pcdir)
    cur = _read_manifest_file(pcdir / "manifest.json", pc_id)
    if cur:
        return _normalize(cur)
    prev = _read_manifest_file(pcdir / "manifest.prev.json", pc_id)
    if cur is None and not prev and not _has_segment_files(pcdir):
        return new_manifest(pc_id)
    if prev:
        prev = _normalize(prev)
        prev["_recovered"] = "prev"
        if notes is not None:
            notes.append({"code": "manifest_prev", "pc_id": pc_id, "n": len(prev["segments"])})
        return prev
    m = rebuild_manifest(pcdir, quarantine=quarantine)
    m["_recovered"] = "rebuilt"
    n = len(m["segments"])
    if notes is not None:
        notes.append({"code": "manifest_rebuilt", "pc_id": pc_id, "n": n})
    events.emit("notice", text_ko=f"목록을 다시 만들었습니다(세그먼트 {n}개)")
    return m


def _normalize(m: dict) -> dict:
    """빠진 선택 필드를 채운다(읽은 dict 를 그대로 고친다)."""
    for k in _LIST_KEYS:
        m.setdefault(k, [])
    for k in _DICT_KEYS:
        m.setdefault(k, {})
    m.setdefault("agent_status", None)
    m.setdefault("updated_at", None)
    return m


def _strip_private(m: dict) -> dict:
    return {k: v for k, v in m.items() if not (isinstance(k, str) and k.startswith("_"))}


def manifest_body(m: dict) -> bytes:
    """비교용 정규 바이트(gen·updated_at·메모리 표지 제외) — '바뀐 것이 있을 때만 저장' 판정."""
    body = {k: v for k, v in _strip_private(m).items() if k not in ("gen", "updated_at")}
    return fsx.canon_bytes(body)


def save_manifest(pcdir, m, *, now=None) -> dict:
    """gen+1 · updated_at · prev 보관 · 원자 쓰기. 저장한 manifest(dict, 메모리 표지 제외)를 돌려준다."""
    pcdir = Path(pcdir)
    pc_id = _pc_of(pcdir)
    out = _strip_private(_normalize(dict(m)))
    out["schema"] = SCHEMA
    out["pc_id"] = pc_id
    if not _valid(out, pc_id):
        raise ValueError("save_manifest: manifest 형식이 아닙니다")
    out["gen"] = int(out.get("gen") or 0) + 1
    out["updated_at"] = now or fsx.utcnow_iso()
    cur = pcdir / "manifest.json"
    if os.path.isfile(fsx.longp(cur)):
        old = fsx.read_bytes(cur)
        try:
            ok = _valid(fsx.loads_strict(old), pc_id)
        except ValueError:
            ok = False
        if ok:
            fsx.atomic_write(pcdir / "manifest.prev.json", old)
    fsx.atomic_write(cur, fsx.canon_bytes(out))
    m.clear()
    m.update(out)
    return out


# ── 디스크 스캔 ──────────────────────────────────────────────────────────────
def _has_segment_files(pcdir: Path) -> bool:
    return any(True for _ in iter_segment_files(pcdir))


def iter_segment_files(pcdir):
    """(kind, 상대 경로 'seg/<kind>/<name>', 절대 경로) — 이름 형식이 맞는 파일만, 정렬."""
    root = Path(pcdir) / "seg"
    try:
        kinds = sorted(os.listdir(fsx.longp(root)))
    except (FileNotFoundError, NotADirectoryError):
        return
    for kind in kinds:
        if kind not in seg.SEG_KINDS:
            continue
        d = root / kind
        try:
            names = sorted(os.listdir(fsx.longp(d)))
        except (FileNotFoundError, NotADirectoryError):
            continue
        for nm in names:
            if seg.parse_segment_name(nm):
                yield kind, f"seg/{kind}/{nm}", d / nm


def tombstoned_shas(m: dict) -> set:
    """무덤표에 오른 옛 sha256 집합."""
    return {t.get("old_sha256") for t in m.get("tombstones", ()) if isinstance(t, dict) and t.get("old_sha256")}


def cursor_pos(c):
    """커서의 순서 키 — (파일 상대 경로, 오프셋). 파일 이름이 쓰기 날짜(YYYYMM/YYYYMMDD)라 사전순 = 시간순."""
    if not isinstance(c, dict):
        return ("", -1)
    f = c.get("file") if isinstance(c.get("file"), str) else ""
    off = c.get("offset") if isinstance(c.get("offset"), int) and not isinstance(c.get("offset"), bool) else -1
    return (f.replace("\\", "/"), off)


def advance_cursor(m: dict, install_id: str, stream: str, cur) -> bool:
    """``cursors[install_id][stream]`` 을 cur 로 — 더 앞설 때만(뒤로 가지 않는다). 바꿨으면 True."""
    if not isinstance(cur, dict) or not isinstance(install_id, str) or not install_id:
        return False
    per = m.setdefault("cursors", {}).setdefault(install_id, {})
    old = per.get(stream)
    if old is None or cursor_pos(cur) > cursor_pos(old):
        per[stream] = dict(cur)
        return True
    return False


def _entry_from_head(rel: str, head: dict, nbytes: int, sha: str) -> dict:
    return seg.seg_info(rel, head, nbytes, sha)


def _advance_from_head(m: dict, head: dict) -> None:
    src_to = head.get("src_to")
    if not isinstance(src_to, dict):
        return
    for src, cur in sorted(src_to.items()):
        if isinstance(src, str) and cur is not None:
            advance_cursor(m, head.get("install_id"), f"{head.get('kind')}/{src}", cur)


def quarantine_file(pcdir, m: dict, rel: str, reason: str, *, now=None) -> str:
    r"""그 PC 폴더 안에서 세그먼트를 ``quarantine\`` 로 옮기고 manifest ``quarantine`` 에 기록. 반환: 새 상대 경로."""
    pcdir = Path(pcdir)
    src = pcdir.joinpath(*rel.split("/"))
    qdir = pcdir / "quarantine"
    fsx.ensure_dir(qdir)
    base = os.path.basename(rel)
    dst = qdir / base
    i = 1
    while os.path.exists(fsx.longp(dst)):
        dst = qdir / f"{base}.{i}"
        i += 1
    os.replace(fsx.longp(src), fsx.longp(dst))
    new_rel = "quarantine/" + dst.name
    m.setdefault("quarantine", []).append({"file": new_rel, "reason": reason, "at": now or fsx.utcnow_iso()})
    m["segments"] = [s for s in m.get("segments", []) if s.get("file") != rel]
    return new_rel


def _load_tomb_copy(pcdir: Path) -> list:
    obj = fsx.read_json(pcdir / "quarantine" / TOMBSTONES_COPY, None, want=list)
    return [t for t in obj or [] if isinstance(t, dict) and t.get("old_sha256")]


def rebuild_manifest(pcdir, *, quarantine=False, now=None) -> dict:
    """세그먼트 파일을 전수 스캔해 manifest 를 다시 만든다(메모리 — 저장하지 않는다).
    검증 실패·무덤표에 오른 파일은 목록에서 빼고 ``quarantine=True`` 면 그 PC 의 ``quarantine\\`` 로 옮긴다."""
    pcdir = Path(pcdir)
    pc_id = _pc_of(pcdir)
    m = new_manifest(pc_id)
    m["tombstones"] = _load_tomb_copy(pcdir)
    dead = tombstoned_shas(m)
    bad = []
    for _kind, rel, path in iter_segment_files(pcdir):
        try:
            data = fsx.read_bytes(path)
            head, _recs = seg.parse_segment_bytes(data, name=path.name)
        except (OSError, seg.SegmentCorrupt) as e:
            bad.append((rel, getattr(e, "reason", "unreadable")))
            continue
        sha = fsx.sha256_hex(data)
        if sha in dead:
            bad.append((rel, "tombstoned"))
            continue
        if head.get("pc_id") != pc_id:
            bad.append((rel, "foreign_pc"))
            continue
        m["segments"].append(_entry_from_head(rel, head, len(data), sha))
        _advance_from_head(m, head)
        inst = head.get("install_id")
        t = head.get("created")
        if isinstance(t, str) and (inst not in m["observed_from"] or t < m["observed_from"][inst]):
            m["observed_from"][inst] = t
    m["segments"].sort(key=lambda s: (s["kind"], s["seq"], s["file"]))
    for rel, why in bad:
        if quarantine:
            quarantine_file(pcdir, m, rel, why, now=now)
        else:
            m.setdefault("_bad", []).append({"file": rel, "reason": why})
    return m


def adopt_orphans(pcdir, m: dict, *, quarantine=True, now=None) -> int:
    """manifest 에 없는 세그먼트 파일을 검증해 편입한다(커서는 ``src_to`` 로 전진). 반환: 편입 수.
    검증 실패·무덤표에 오른 고아는 ``quarantine=True`` 면 그 PC 폴더의 quarantine 으로(호출자가 manifest 저장)."""
    pcdir = Path(pcdir)
    pc_id = _pc_of(pcdir)
    _normalize(m)
    known_files = {s.get("file") for s in m["segments"]}
    known_sha = {s.get("sha256") for s in m["segments"]}
    dead = tombstoned_shas(m)
    n = 0
    for _kind, rel, path in list(iter_segment_files(pcdir)):
        if rel in known_files:
            continue
        try:
            data = fsx.read_bytes(path)
            head, _recs = seg.parse_segment_bytes(data, name=path.name)
            why = None
        except (OSError, seg.SegmentCorrupt) as e:
            head, data, why = None, b"", getattr(e, "reason", "unreadable")
        sha = fsx.sha256_hex(data) if head is not None else ""
        if why is None and sha in dead:
            why = "tombstoned"
        if why is None and head.get("pc_id") != pc_id:
            why = "foreign_pc"
        if why is not None:
            if quarantine:
                quarantine_file(pcdir, m, rel, why, now=now)
            continue
        if sha in known_sha:
            continue
        m["segments"].append(_entry_from_head(rel, head, len(data), sha))
        known_sha.add(sha)
        known_files.add(rel)
        _advance_from_head(m, head)
        n += 1
    if n:
        m["segments"].sort(key=lambda s: (s.get("kind", ""), s.get("seq", 0), s.get("file", "")))
    return n


def add_tombstone(m: dict, *, seq, kind, old_sha256, new_sha256, reason="redact", at=None, pcdir=None) -> dict:
    r"""무덤표 한 줄을 더한다. ``pcdir`` 를 주면 ``quarantine\tombstones.json`` 사본도 갱신(manifest 재구성용)."""
    t = {"seq": int(seq), "kind": kind, "old_sha256": old_sha256, "new_sha256": new_sha256, "reason": reason,
         "at": at or fsx.utcnow_iso()}
    tl = m.setdefault("tombstones", [])
    if not any(x.get("old_sha256") == old_sha256 for x in tl if isinstance(x, dict)):
        tl.append(t)
    if pcdir is not None:
        write_tomb_copy(pcdir, tl)
    return t


def write_tomb_copy(pcdir, tombstones) -> None:
    r"""``quarantine\tombstones.json`` = 무덤표 사본(old_sha256 기준 합집합, 정렬)."""
    pcdir = Path(pcdir)
    have = {t["old_sha256"]: t for t in _load_tomb_copy(pcdir)}
    for t in tombstones or ():
        if isinstance(t, dict) and t.get("old_sha256"):
            have.setdefault(t["old_sha256"], t)
    rows = [have[k] for k in sorted(have)]
    p = pcdir / "quarantine" / TOMBSTONES_COPY
    data = fsx.canon_bytes(rows)
    if os.path.isfile(fsx.longp(p)) and fsx.read_bytes(p) == data:
        return
    fsx.atomic_write(p, data)
