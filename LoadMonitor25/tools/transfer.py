"""Create a verified PC-transfer ZIP without changing the source application.

Unlike Make-Package.ps1 this preserves personal configuration, collected data,
reports and team data. Only explicitly named disposable directories are omitted.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
import zipfile


MANIFEST_NAME = "_LM25_TRANSFER_MANIFEST.json"
CACHE_DIRS = frozenset({"__pycache__", ".ruff_cache", ".pytest_cache", ".git"})
CACHE_CODE_TREES = frozenset({"core", "ui", "tools", "collect", "python"})
REPARSE_POINT = 0x400
CHUNK_SIZE = 1024 * 1024


class TransferError(Exception):
    """A transfer cannot safely produce a complete archive."""


def _check_cancel(cancelled):
    if cancelled is not None and cancelled():
        raise TransferError("이동 ZIP 취소 요청을 받았습니다. 원본은 변경하지 않았습니다.")


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & REPARSE_POINT
    )


def _check_chain(path):
    """Reject junctions as well as symbolic links, including parent directories."""
    for candidate in reversed((path, *path.parents)):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if _is_link(info):
            raise TransferError(f"링크 또는 junction은 이동할 수 없습니다: {candidate}")


def _fingerprint(info):
    return (info.st_size, info.st_mtime_ns, info.st_dev, info.st_ino,
            info.st_mode, getattr(info, "st_file_attributes", 0))


def _opened_matches(info, expected):
    actual = _fingerprint(info)
    # Windows stat infers executable permission bits from the file extension;
    # fstat cannot infer them from a handle. Compare identity and file type.
    return (actual[:4] == expected[:4]
            and stat.S_IFMT(actual[4]) == stat.S_IFMT(expected[4])
            and actual[5:] == expected[5:])


def _root_path(root):
    root = _absolute(root)
    _check_chain(root)
    if not root.is_dir() or root == root.parent:
        raise TransferError("애플리케이션 하위 폴더를 --root로 지정하세요.")
    return root


def _output_path(root, output=None):
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = root.parent / f"LoadMonitor25_이동_{stamp}_{uuid.uuid4().hex[:12]}.zip"
    output = _absolute(output)
    _check_chain(output)
    if output == root or output.is_relative_to(root) or root.is_relative_to(output):
        raise TransferError("출력 ZIP은 원본 폴더 및 그 하위 경로와 겹칠 수 없습니다.")
    if output.suffix.lower() != ".zip":
        raise TransferError("출력 파일의 확장자는 .zip이어야 합니다.")
    if output.exists():
        raise TransferError(f"기존 출력은 덮어쓰지 않습니다: {output}")
    if not output.parent.is_dir():
        raise TransferError(f"출력 폴더가 없습니다: {output.parent}")
    return output


def _custom_profile(root):
    """Read only the exact profile path; never treat generic cache names as junk.

    Relative profile paths have a working-directory-dependent meaning in the
    browser launcher. They are therefore rejected rather than guessed here.
    A profile outside the application is already outside the transfer scope.
    """
    config = root / "config" / "config.json"
    _check_chain(config)
    if not config.exists():
        return None
    try:
        before = config.stat()
        value = json.loads(config.read_text(encoding="utf-8-sig"))
        if _fingerprint(before) != _fingerprint(config.stat()):
            raise TransferError("설정을 읽는 동안 파일이 변경되었습니다.")
    except (ValueError, UnicodeError) as error:
        raise TransferError(f"사용자 설정을 확인할 수 없습니다: {error}") from error
    if not isinstance(value, dict):
        raise TransferError("config/config.json은 JSON 객체여야 합니다.")
    settings = value.get("copilotAuto") or {}
    if not isinstance(settings, dict):
        raise TransferError("copilotAuto 설정은 JSON 객체여야 합니다.")
    configured = settings.get("profileDir")
    if configured is None or configured == "":
        return None
    if not isinstance(configured, str) or not Path(configured).is_absolute():
        raise TransferError("copilotAuto.profileDir은 절대경로로 설정한 뒤 이동하세요.")
    path = _absolute(configured)
    # A broad exclusion could erase actual data/configuration from the archive.
    if path == root or root.is_relative_to(path):
        raise TransferError("브라우저 프로필 경로가 애플리케이션 루트/상위와 겹칩니다.")
    if not path.is_relative_to(root):
        return None
    relative = path.relative_to(root)
    if relative.parts[0].casefold() in {"config", "report", "teamdata", "python", "core", "tools", "collect", "ui"}:
        raise TransferError("브라우저 프로필 경로가 보존할 애플리케이션 폴더와 겹칩니다.")
    protected_data = {"data", "data/추가pc", "data/files", "data/outlook", "data/pc",
                      "data/m365", "data/activity", "data/manual", "data/license"}
    folded = [part.casefold() for part in relative.parts]
    extra_pc_data = (folded[:2] == ["data", "추가pc"]
                     and (len(folded) <= 3 or (len(folded) == 4 and folded[3] in {
                         "files", "outlook", "pc", "m365", "activity", "manual", "license"})))
    if relative.as_posix().casefold() in protected_data or extra_pc_data:
        raise TransferError("브라우저 프로필 제외 범위가 너무 넓습니다.")
    _check_chain(path)
    if path.exists() and not path.is_dir():
        raise TransferError("브라우저 프로필 경로가 폴더가 아닙니다.")
    return relative.as_posix()


def _exclude_reason(relative, custom):
    parts = relative.parts
    name = parts[-1].casefold()
    folded = [part.casefold() for part in parts]
    # Data and user folders may use these names for PC names or real evidence.
    # Only the application root and known code trees contain disposable caches.
    if name in CACHE_DIRS and (len(parts) == 1 or folded[0] in CACHE_CODE_TREES):
        return "regenerable_cache_or_repository_metadata"
    if name == "copilot_profile" and (
        folded == ["data", "copilot_profile"]
        or (len(parts) == 4 and folded[:2] == ["data", "추가pc"])
    ):
        return "dedicated_browser_profile_relogin_on_destination"
    if custom is not None and relative.as_posix().casefold() == custom.casefold():
        return "configured_browser_profile_relogin_on_destination"
    return None


def _previous_manifest(path, expected):
    """Recognize only our versioned, generated manifest, never arbitrary files."""
    if expected[0] > 128 * 1024 * 1024:
        raise TransferError("이전 이동 manifest가 너무 큽니다. 원본 파일을 별도로 보관한 뒤 확인하세요.")
    raw = path.read_bytes()
    if len(raw) != expected[0] or _fingerprint(path.lstat()) != expected:
        raise TransferError("이전 이동 manifest가 읽는 동안 변경되었습니다.")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
        valid = (isinstance(value, dict) and value.get("format") == "lm25-pc-transfer"
                 and value.get("version") == 1 and isinstance(value.get("app_name"), str)
                 and isinstance(value.get("created_at"), str)
                 and isinstance(value.get("files"), list)
                 and isinstance(value.get("excluded_dirs"), list)
                 and isinstance(value.get("policy"), dict)
                 and value["policy"].get("source_modified") is False
                 and set(value["policy"].get("exclude", [])) == CACHE_DIRS)
        if valid:
            for item in value["files"]:
                if (not isinstance(item, dict) or not isinstance(item.get("path"), str)
                        or not isinstance(item.get("size"), int) or item["size"] < 0
                        or not isinstance(item.get("mtime_ns"), int)
                        or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))):
                    valid = False
                    break
    except (ValueError, UnicodeError, TypeError):
        valid = False
    if not valid:
        raise TransferError(f"이동 manifest 이름과 일반 파일이 충돌합니다. 원본은 보존했습니다: {path.name}")
    return {"path": path.name, "size": len(raw), "mtime_ns": expected[1],
            "sha256": hashlib.sha256(raw).hexdigest(), "created_at": value["created_at"],
            "reason": "validated_generated_transfer_manifest_replaced_by_new_manifest"}


def _scan(root, custom, cancelled=None):
    files, directories, excluded, excluded_files = {}, {}, [], []
    stack = [root]
    while stack:
        _check_cancel(cancelled)
        folder = stack.pop()
        _check_chain(folder)
        folder_info = folder.lstat()
        if not stat.S_ISDIR(folder_info.st_mode):
            raise TransferError(f"폴더가 이동 중 변경되었습니다: {folder}")
        relative_dir = folder.relative_to(root).as_posix()
        directories[relative_dir] = (folder_info.st_dev, folder_info.st_ino)
        with os.scandir(folder) as entries:
            entries = sorted(entries, key=lambda item: item.name.casefold())
        for entry in entries:
            _check_cancel(cancelled)
            path = folder / entry.name
            relative = path.relative_to(root)
            if any(part in {".", ".."} or "\\" in part or ":" in part for part in relative.parts):
                raise TransferError(f"ZIP 안에서 안전하게 표현할 수 없는 경로: {relative}")
            # Windows DirEntry.stat reports st_dev/st_ino as zero. Use lstat
            # so the snapshot can be compared with the opened file's fstat.
            info = path.lstat()
            if _is_link(info):
                raise TransferError(f"링크 또는 junction은 이동할 수 없습니다: {relative}")
            if stat.S_ISDIR(info.st_mode):
                reason = _exclude_reason(relative, custom)
                if reason:
                    excluded.append({"path": relative.as_posix(), "reason": reason})
                else:
                    stack.append(path)
            elif stat.S_ISREG(info.st_mode):
                if relative.as_posix().casefold() == MANIFEST_NAME.casefold():
                    excluded_files.append(_previous_manifest(path, _fingerprint(info)))
                    continue
                files[relative.as_posix()] = _fingerprint(info)
            else:
                raise TransferError(f"일반 파일/폴더가 아닌 항목은 이동할 수 없습니다: {relative}")
    return {
        "files": dict(sorted(files.items())),
        "directories": dict(sorted(directories.items())),
        "excluded_dirs": sorted(excluded, key=lambda item: item["path"]),
        "excluded_files": excluded_files,
    }


def _summary(root, output, snapshot, status):
    return {
        "status": status, "root": str(root), "output": str(output),
        "app_name": root.name, "file_count": len(snapshot["files"]),
        "total_bytes": sum(info[0] for info in snapshot["files"].values()),
        "excluded_dirs": snapshot["excluded_dirs"],
        "excluded_files": snapshot["excluded_files"],
        "excluded_contents_scanned": False,
    }


def plan_transfer(root, output=None, cancelled=None):
    """Return a read-only plan. Excluded directories are never traversed."""
    _check_cancel(cancelled)
    root = _root_path(root)
    output = _output_path(root, output)
    custom = _custom_profile(root)
    snapshot = _scan(root, custom, cancelled)
    return _summary(root, output, snapshot, "planned")


def _zip_info(name, fingerprint=None):
    info = zipfile.ZipInfo(name)
    if fingerprint:
        # ZIP has a two-second timestamp; manifest also retains exact mtime_ns.
        parts = time.localtime(fingerprint[1] / 1_000_000_000)[:6]
        info.date_time = (max(1980, min(2107, parts[0])), *parts[1:])
        info.external_attr = fingerprint[4] << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info._compresslevel = 1
    return info


def _copy_file(archive, root, relative, expected, cancelled=None):
    _check_cancel(cancelled)
    path = root / relative
    _check_chain(path)
    if _fingerprint(path.lstat()) != expected:
        raise TransferError(f"압축 전 파일이 변경되었습니다: {relative}")
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        if not _opened_matches(os.fstat(source.fileno()), expected):
            raise TransferError(f"파일을 여는 동안 변경되었습니다: {relative}")
        info = _zip_info(f"{root.name}/{relative}", expected)
        with archive.open(info, "w", force_zip64=True) as target:
            while True:
                _check_cancel(cancelled)
                block = source.read(CHUNK_SIZE)
                if not block:
                    break
                target.write(block)
                digest.update(block)
                count += len(block)
        if not _opened_matches(os.fstat(source.fileno()), expected):
            raise TransferError(f"파일을 읽는 동안 변경되었습니다: {relative}")
    _check_chain(path)
    if count != expected[0] or _fingerprint(path.lstat()) != expected:
        raise TransferError(f"압축 중 파일이 변경되었습니다: {relative}")
    return {"path": relative, "size": count, "mtime_ns": expected[1], "sha256": digest.hexdigest()}


def _verify_zip(path, prefix, files, cancelled=None):
    """Verify archived bytes against the hashes generated while reading sources."""
    with zipfile.ZipFile(path, "r") as archive:
        for item in files:
            _check_cancel(cancelled)
            digest = hashlib.sha256()
            count = 0
            with archive.open(f"{prefix}/{item['path']}") as entry:
                while True:
                    _check_cancel(cancelled)
                    block = entry.read(CHUNK_SIZE)
                    if not block:
                        break
                    digest.update(block)
                    count += len(block)
            if count != item["size"] or digest.hexdigest() != item["sha256"]:
                raise TransferError(f"압축 파일 검증 실패: {item['path']}")


def _publish_no_replace(temporary, output):
    _check_chain(output)
    if os.name == "nt":
        # Windows rename is atomic and fails when the destination exists.
        os.rename(temporary, output)
    else:
        # POSIX rename overwrites. A hard link publishes atomically without it.
        os.link(temporary, output)


def _remove_owned_temporary(path, identity):
    """Only unlink the exact regular temporary file created by this invocation."""
    try:
        _check_chain(path)
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
            path.unlink()
    except (OSError, TransferError):
        pass


def create_transfer(root, output=None, progress=None, cancelled=None):
    """Create and publish a complete ZIP, or fail without a final ZIP.

    progress receives processed_files/processed_bytes and plan totals. It may
    raise to cancel; cleanup still removes only this invocation's temporary file.
    cancelled is an optional zero-argument callback checked between file chunks,
    verification reads, directory entries and immediately before publication.
    """
    _check_cancel(cancelled)
    root = _root_path(root)
    output = _output_path(root, output)
    custom = _custom_profile(root)
    snapshot = _scan(root, custom, cancelled)
    result = _summary(root, output, snapshot, "completed")
    temporary = output.parent / f".lm25-transfer-{uuid.uuid4().hex}.tmp"
    identity = None
    files = []
    processed_bytes = 0
    try:
        # xb prevents replacing a preexisting file, including a link.
        with temporary.open("xb") as handle:
            info = os.fstat(handle.fileno())
            identity = (info.st_dev, info.st_ino)
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=1, allowZip64=True) as archive:
                for relative in snapshot["directories"]:
                    _check_cancel(cancelled)
                    suffix = "" if relative == "." else f"{relative}/"
                    archive.writestr(_zip_info(f"{root.name}/{suffix}"), b"")
                for relative, expected in snapshot["files"].items():
                    _check_cancel(cancelled)
                    item = _copy_file(archive, root, relative, expected, cancelled)
                    files.append(item)
                    processed_bytes += item["size"]
                    if progress:
                        progress({"processed_files": len(files), "processed_bytes": processed_bytes,
                                  "file_count": result["file_count"], "total_bytes": result["total_bytes"]})
                manifest = {
                    "format": "lm25-pc-transfer", "version": 1,
                    "created_at": datetime.now().astimezone().isoformat(),
                    "app_name": root.name,
                    "policy": {
                        "preserve": "All application files, personal configuration, data, reports and team data",
                        "exclude": sorted(CACHE_DIRS),
                        "cache_scope": {
                            "application_root": True, "code_trees": sorted(CACHE_CODE_TREES),
                            "other_directories": "preserved",
                        },
                        "browser_profiles": "Only dedicated/default or exact configured profile directories",
                        "source_modified": False, "profile_relogin_may_be_required": True,
                        "excluded_contents_scanned": False,
                    },
                    "excluded_dirs": snapshot["excluded_dirs"], "files": files,
                    "previous_manifest": snapshot["excluded_files"],
                }
                manifest_entry = f"{root.name}/{MANIFEST_NAME}"
                archive.writestr(_zip_info(manifest_entry),
                                 json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _verify_zip(temporary, root.name, files, cancelled)
        digest = hashlib.sha256()
        with temporary.open("rb") as handle:
            while True:
                _check_cancel(cancelled)
                block = handle.read(CHUNK_SIZE)
                if not block:
                    break
                digest.update(block)
        zip_bytes = temporary.stat().st_size
        # Check after all ZIP reads, immediately before publishing. Also detect
        # changed configuration/exclusion boundaries and newly created files.
        if _custom_profile(root) != custom or _scan(root, custom, cancelled) != snapshot:
            raise TransferError("압축 중 원본 파일 목록/크기/수정시각이 변경되었습니다. 작업을 마친 뒤 다시 시도하세요.")
        _check_cancel(cancelled)
        _publish_no_replace(temporary, output)
        result.update(processed_files=len(files), processed_bytes=processed_bytes,
                      zip_bytes=zip_bytes, zip_sha256=digest.hexdigest(), manifest_entry=manifest_entry)
        return result
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
        raise TransferError(f"이동 ZIP을 완성하지 못했습니다: {error}") from error
    finally:
        if identity is not None:
            _remove_owned_temporary(temporary, identity)


def main(argv=None):
    parser = argparse.ArgumentParser(description="개인 상태를 보존하는 경량 PC 이동 ZIP")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output")
    parser.add_argument("--cancel-file", help="이 파일이 생성되면 원본을 보존하며 이동 ZIP 생성을 취소")
    parser.add_argument("--plan", action="store_true", help="원본을 변경하지 않고 복사 계획만 표시")
    parser.add_argument("--json", action="store_true", help="결과 JSON 한 줄을 stdout으로 출력")
    args = parser.parse_args(argv)
    if args.json and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    last_update = [0.0]
    cancel_file = Path(args.cancel_file) if args.cancel_file else None

    def cancelled():
        return cancel_file is not None and cancel_file.exists()

    def progress(update):
        current = time.monotonic()
        if current - last_update[0] >= 1 or update["processed_files"] == update["file_count"]:
            print(json.dumps({"status": "progress", **update}), file=sys.stderr, flush=True)
            last_update[0] = current

    try:
        result = (plan_transfer(args.root, args.output, cancelled=cancelled) if args.plan
                  else create_transfer(args.root, args.output, progress=progress, cancelled=cancelled))
    except (TransferError, OSError) as error:
        result = {"status": "failed", "error": str(error)}
        print(json.dumps(result, ensure_ascii=False) if args.json else f"[실패] {error}", flush=True)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        print(f"[{result['status']}] {result['file_count']}개 · {result['total_bytes']} bytes")
        print(result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
