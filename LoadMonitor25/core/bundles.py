"""Publish complete team snapshots with one atomic pointer replacement.

Readers pin and verify one immutable run. Legacy folders remain readable until
their first LM25 publication; failed or corrupt new runs never fall back to them.
"""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import uuid


_RUN = re.compile(r"^[0-9a-f]{32}$")
_TAG = re.compile(r"^\d{8}-\d{8}$")
_FILE = re.compile(r"^(?:mm_rows_\d{8}-\d{8}(?:_refined)?\.csv|"
                   r"signals_\d{8}-\d{8}\.csv|"
                   r"(?:mm_meta|pivots|ai_narratives|entities|agentic|workflow)_\d{8}-\d{8}\.json)$")


def _plain(path):
    """Reject redirects, including Windows junctions, before any write/read."""
    full = os.path.abspath(path)
    if os.name == "nt" and not full.startswith("\\\\?\\"):
        full = "\\\\?\\UNC\\" + full[2:] if full.startswith("\\\\") else "\\\\?\\" + full
    path = Path(full)
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("팀 묶음 경로에 링크/정션이 있습니다")
    return path


def _json(path):
    with open(_plain(path), encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("팀 묶음 메타데이터가 객체가 아닙니다")
    return value


def resolve_member_dir(member_root):
    """Return a verified immutable directory, or the untouched legacy directory."""
    root = _plain(member_root)
    pointer = root / "current.json"
    if not os.path.lexists(pointer):
        return str(root)
    ref = _json(pointer)
    run_id = ref.get("run_id", "")
    if ref.get("schema") != 1 or not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
        raise ValueError("팀 묶음 current.json 형식 오류")
    run = _plain(root / ".runs" / run_id)
    manifest = _json(run / "bundle.json")
    hashes = manifest.get("files")
    if (manifest.get("schema") != 1 or manifest.get("run_id") != run_id
            or not isinstance(hashes, dict) or "member.json" not in hashes):
        raise ValueError("팀 묶음 manifest 형식 오류")
    for name, digest in hashes.items():
        if name != "member.json" and not _FILE.fullmatch(name):
            raise ValueError("팀 묶음 파일명 오류")
        with open(_plain(run / name), "rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != digest:
            raise ValueError(f"팀 묶음 무결성 오류: {name}")
    actual_files = {p.name for p in run.iterdir()}
    if actual_files != set(hashes) | {"bundle.json"}:
        raise ValueError("팀 묶음에 manifest 외 파일이 있습니다")
    member = _json(run / "member.json")
    if member.get("bundle_run_id") != run_id or member.get("tag") != manifest.get("tag"):
        raise ValueError("팀 묶음 실행/기간 불일치")
    return str(run)


def _write(path, body):
    with open(_plain(path), "xb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _publication_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with open(_plain(root / ".publish.lock"), "a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_bundle(member_root, member, files):
    """Serialize publishers across processes; OS releases the lock on crashes."""
    root = _plain(member_root)
    with _publication_lock(root):
        return _publish(root, member, files)


def _publish(member_root, member, files):
    """Stage a validated full snapshot; a failure leaves the published run intact."""
    root = _plain(member_root)
    if not isinstance(member, dict) or not isinstance(files, dict) or not files:
        raise ValueError("비어 있거나 잘못된 팀 묶음입니다")
    tag = member.get("tag")
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError("팀 묶음 기간 오류")
    if any(not isinstance(n, str) or not _FILE.fullmatch(n) or tag not in n
           or not isinstance(v, str) for n, v in files.items()):
        raise ValueError("팀 묶음 파일명/기간/본문 오류")
    # A normalized name is not proof that two sources identify the same person.
    previous = Path(resolve_member_dir(root)) / "member.json"
    if previous.exists():
        old = _json(previous)
        old_id, new_id = old.get("member_id"), member.get("member_id")
        if old_id and old_id != new_id:
            raise ValueError("동일 폴더의 구성원 식별값이 다릅니다. 이름/계정을 확인하세요")
        if not old_id and new_id and member.get("owner_source") != member.get("owner"):
            raise ValueError("구버전 폴더와 정규화 이름이 겹칩니다. 구성원 이름을 구분해 설정하세요")
    root.mkdir(parents=True, exist_ok=True)
    runs = _plain(root / ".runs")
    runs.mkdir(exist_ok=True)
    run_id = uuid.uuid4().hex
    run = runs / run_id
    run.mkdir()
    body = dict(files)
    body["member.json"] = json.dumps(dict(member, bundle_run_id=run_id), ensure_ascii=False, indent=1)
    hashes = {}
    for name, value in body.items():
        raw = value.encode("utf-8")
        _write(run / name, raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {"schema": 1, "run_id": run_id, "tag": tag, "files": hashes}
    _write(run / "bundle.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"))
    temp = root / (".current-" + run_id + ".tmp")
    try:
        _write(temp, json.dumps({"schema": 1, "run_id": run_id}).encode("ascii"))
        os.replace(temp, _plain(root / "current.json"))
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return str(run)
