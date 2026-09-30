"""Collection evidence and lossless, atomic CSV updates (no network or app I/O).

A completed process is not evidence of complete mailbox/chat coverage. Collectors
write an explicit bounded scope; unknown and interrupted scopes remain partial.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time


EXTRA_FIELDS = ("context_excerpt", "context_truncated", "source_id", "source_kind",
                "source_url", "conversation_id")
VALID_STATUSES = {"complete", "partial", "failed", "blocked", "skipped", "unknown"}


def read_csv(path):
    """Read old six/seven-column CSVs without dropping rows missing new columns."""
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp949")
    csv.field_size_limit(max(csv.field_size_limit(), 16 * 1024 * 1024))
    rows = []
    for raw_row in csv.DictReader(io.StringIO(text, newline="")):
        if None in raw_row:
            raise ValueError(f"Malformed CSV row: {path.name}; original file retained")
        row = {str(key): str(value or "") for key, value in raw_row.items() if key}
        if any(row.values()):
            rows.append(row)
    return rows


def _normal(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def record_key(row, kind="mail"):
    """Prefer scoped source IDs; never match different days or chat rooms."""
    account = _normal(row.get("account"))
    source_id = str(row.get("source_id") or "").strip()
    conversation = str(row.get("conversation_id") or row.get("chat") or "").strip()
    if source_id:
        return (kind, "id", account, conversation, source_id)
    if kind == "teams":
        text = row.get("context_excerpt") or row.get("summary") or ""
        fields = (row.get("time"), row.get("from"), conversation, text)
    elif kind == "calendar":
        fields = (row.get("start"), row.get("end"), row.get("subject"),
                  row.get("location"), row.get("all_day"))
    else:
        # No ID means two different messages with identical metadata cannot be
        # distinguished. Retain distinct nonempty body excerpts conservatively.
        fields = (row.get("time"), row.get("box"), row.get("sender"),
                  row.get("conversation") or row.get("subject"),
                  row.get("context_excerpt"))
    digest = hashlib.sha256("\x1f".join(_normal(x) for x in fields).encode("utf-8")).hexdigest()
    return (kind, "derived", account, digest)


def merge_rows(existing, incoming, kind="mail"):
    """Union records; metadata-only observations never erase collected context."""
    records = {}
    metadata_index = {}

    def metadata_key(row):
        if kind == "calendar":
            return record_key(row, kind)
        if kind == "teams":
            return tuple(_normal(row.get(k)) for k in ("time", "from", "chat"))
        title = re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "",
                       _normal(row.get("conversation") or row.get("subject")))
        return (*(_normal(row.get(k)) for k in ("time", "box", "sender")), title)

    def compatible(a, b):
        if a.get("source_id") and b.get("source_id"):
            return False  # Never collapse two distinct source IDs by a weak key.
        if a.get("account") and b.get("account") and a["account"] != b["account"]:
            return False
        if a.get("conversation_id") and b.get("conversation_id") and a["conversation_id"] != b["conversation_id"]:
            return False
        left, right = _normal(a.get("context_excerpt")), _normal(b.get("context_excerpt"))
        if left and right and left != right:
            return False
        if kind == "teams":
            # Legacy summaries may match a richer excerpt, but only within the
            # same full timestamp + sender + room and with one unique candidate.
            left = left or _normal(a.get("summary"))
            right = right or _normal(b.get("summary"))
            return bool(left and right and (left.startswith(right) or right.startswith(left)))
        return True

    for row in [*existing, *incoming]:
        clean = {str(k): str(v if v is not None else "") for k, v in row.items() if k}
        key = record_key(clean, kind)
        if key not in records:
            weak = metadata_key(clean)
            matches = [k for k in metadata_index.get(weak, ()) if compatible(records[k], clean)]
            if len(matches) == 1:
                old_key = matches[0]
                old = records.pop(old_key)
                metadata_index[metadata_key(old)].discard(old_key)
                key = key if clean.get("source_id") else old_key
                records[key] = old
                metadata_index.setdefault(metadata_key(old), set()).add(key)
        if key not in records:
            records[key] = clean
            metadata_index.setdefault(metadata_key(clean), set()).add(key)
            continue
        previous = records[key]
        old_metadata = metadata_key(previous)
        sources = set(filter(None, str(previous.get("observed_sources") or "").split("|")))
        sources.update(filter(None, str(clean.get("observed_sources") or "").split("|")))
        sources.update(filter(None, (previous.get("source_kind"), clean.get("source_kind"))))
        old_context = previous.get("context_excerpt", "")
        new_context = clean.get("context_excerpt", "")
        newer_original, older_original = False, False
        context_available = (str(clean.get("context_available", "")).lower() != "false"
                             and (bool(new_context) or str(clean.get("context_available", "")).lower() == "true"))
        if (previous.get("source_id") and previous.get("source_id") == clean.get("source_id")
                and clean.get("source_kind") in {"teams_graph", "outlook_graph"}
                and previous.get("source_kind") == clean.get("source_kind")):
            try:
                old_modified = datetime.fromisoformat(str(previous.get("modified_time") or "").replace("Z", "+00:00"))
                new_modified = datetime.fromisoformat(str(clean.get("modified_time") or "").replace("Z", "+00:00"))
                newer_original = bool(context_available and old_modified.tzinfo and new_modified.tzinfo and new_modified > old_modified)
                older_original = bool(old_modified.tzinfo and new_modified.tzinfo and new_modified < old_modified)
            except (ValueError, TypeError):
                pass
        if older_original:
            if sources:
                previous["observed_sources"] = "|".join(sorted(sources))
            continue
        keep_context = bool(old_context and len(old_context) > len(new_context) and not newer_original)
        precision = {"estimated": 0, "ai_reported": 0, "unknown": 0, "date": 1, "minute": 2, "second": 3, "exact": 3}
        def time_rank(value):
            return precision.get(value.get("time_precision"), 3 if len(value.get("time", "")) > 10 else 1)
        keep_time = time_rank(previous) > time_rank(clean)
        for field, value in clean.items():
            if (field == "modified_time" and not context_available
                    and clean.get("source_kind") in {"teams_graph", "outlook_graph"}):
                continue  # Missing/disabled body cannot promote the version of stored context.
            if field in {"context_excerpt", "source_kind", "context_truncated"} and keep_context:
                continue
            if field in {"time", "time_precision"} and keep_time:
                continue
            if field == "source_kind" and keep_time and old_context == new_context:
                continue
            if value or (newer_original and field in {"context_excerpt", "context_truncated"}):
                previous[field] = value
        if sources:
            previous["observed_sources"] = "|".join(sorted(sources))
        if metadata_key(previous) != old_metadata:
            metadata_index[old_metadata].discard(key)
            metadata_index.setdefault(metadata_key(previous), set()).add(key)
    return sorted(records.values(), key=lambda r: (r.get("time") or r.get("start") or "",
                                                   r.get("source_id") or ""))


def _atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows scanners/readers can briefly hold a handle without delete
        # sharing. Retry only those errors; never unlink the previous snapshot.
        for delay in (0.05, 0.1, 0.2, 0.4, 0.8, None):
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33) or delay is None:
                    raise
                time.sleep(delay)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_csv(path, rows, fieldnames):
    """Atomically replace a validated snapshot, preserving optional extra fields."""
    fields = list(dict.fromkeys([*fieldnames, *(key for row in rows for key in row if key)]))
    if not fields:
        raise ValueError("CSV headers are required")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_text(path, buffer.getvalue())


def merge_csv(path, rows, fieldnames, kind="mail"):
    merged = merge_rows(read_csv(path), rows, kind)
    write_csv(path, merged, fieldnames)
    return len(merged)


def write_status(root, source, d0, d1, status="partial", rows=0, scope="", reasons=(), **extra):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", source):
        raise ValueError("Invalid collection source name")
    if status not in VALID_STATUSES:
        raise ValueError("Invalid collection status")
    payload = dict(extra)
    payload.update(schema=1, source=source, requested_from=str(d0), requested_to=str(d1),
                   status=status, rows=max(0, int(rows)), scope=str(scope),
                   reasons=list(dict.fromkeys(str(x) for x in reasons if x)),
                   finished_at=time.time())
    # 'complete' only covers this explicitly named source/scope, never the tenant.
    if status == "complete" and not scope:
        payload.update(status="partial", reasons=[*payload["reasons"], "scope_not_declared"])
    target = Path(root) / "data" / "collection_status" / f"{source}.json"
    _atomic_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def load_status(root, source, d0=None, d1=None, since=None):
    try:
        payload = json.loads((Path(root) / "data" / "collection_status" / f"{source}.json").read_text("utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("source") != source:
            return None
        if d0 is not None and payload.get("requested_from") != str(d0):
            return None
        if d1 is not None and payload.get("requested_to") != str(d1):
            return None
        if since is not None and float(payload.get("finished_at", 0)) < float(since):
            return None
        if payload.get("status") not in VALID_STATUSES:
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def status_snapshot(root):
    result = []
    directory = Path(root) / "data" / "collection_status"
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            if re.fullmatch(r"[a-z][a-z0-9_]*", path.stem):
                status = load_status(root, path.stem)
                if status:
                    result.append(status)
    return result


def needs_supplement(status):
    return not status or status.get("status") != "complete"
