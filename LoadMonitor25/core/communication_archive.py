"""Local full-text evidence, separate from bounded analysis excerpts.

Only normalized records supplied by a collector are accepted. Tokens, browser
storage and attachments are never inputs. The stored record is the latest read
version; this is not a mailbox backup or a history of deleted/edited messages.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
import json
from pathlib import Path

from collection_state import _atomic_text, web_capture_score


FIELDS = {"body", "source_id", "source_kind", "conversation_id", "account", "time",
          "createdDateTime", "lastModifiedDateTime", "sender", "from", "subject",
          "chat", "conversation", "box", "rcv", "source_url", "internet_message_id",
          "reply_to_id", "body_format", "time_precision", "modified_time", "time_utc",
          "message_id", "in_reply_to", "references", "full_body_chars",
          "body_capture_status", "capture_method", "body_truncated", "body_complete",
          "capture_truncated", "capture_limit", "capture_scope"}


def _upgrade_time(previous, current):
    """An independently proven date can improve even when the body is retained."""
    ranks = {"unknown": 0, "estimated": 0, "ai_reported": 0, "date": 1, "minute": 2, "second": 3, "exact": 3}
    precision = str(current.get("time_precision") or "").lower()
    old_rank = ranks.get(str(previous.get("time_precision") or "").lower(),
                         3 if len(str(previous.get("time") or "")) > 10 else 0)
    try:
        old_value = str(previous.get("time") or "")
        datetime.fromisoformat(old_value.replace("Z", "+00:00"))
        if old_rank > 1 and len(old_value) <= 10:
            old_rank = 0
    except (ValueError, TypeError):
        old_rank = 0
    if precision not in {"date", "minute", "second", "exact"} or ranks[precision] <= old_rank:
        return previous
    try:
        value = str(current.get("time") or "")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if precision != "date" and len(value) <= 10:
            return previous
    except (ValueError, TypeError):
        return previous
    return {**previous, "time": current["time"], "time_precision": current["time_precision"]}


def archive_records(root, family, records):
    """Persist observed plain text before advancing a collector cursor.

    Browser text can still be partial; capture metadata must describe that limit.
    Without a verified edit timestamp, a later partial or shorter browser preview
    cannot replace a richer body. This is retention, not an edit history, and does
    not prove that a retained body is the newest edited version on the server.
    """
    if family not in {"mail", "teams"}:
        raise ValueError("Unsupported communication family")
    count = 0
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("body"), str):
            raise ValueError("A full text body is required for original evidence")
        if str(record.get("context_filtered", "")).lower() in {"true", "1", "yes"}:
            continue  # Defense in depth: excluded bodies never enter the original store.
        clean = {key: value for key, value in record.items() if key in FIELDS
                 and isinstance(value, (str, int, float, bool))}
        identity = [family, str(clean.get("account", "")), str(clean.get("conversation_id", "")),
                    str(clean.get("source_id", ""))]
        web = clean.get("source_kind") in {"teams_web", "outlook_web"}
        if web:
            clean["full_body_chars"] = len(clean["body"])
            # Existing Graph/COM keys remain stable. New DOM observations do
            # not overwrite a different route's original with a reused ID.
            identity.append(clean["source_kind"])
        if not clean.get("source_id"):
            identity.append(json.dumps(clean, ensure_ascii=False, sort_keys=True))
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        path = Path(root) / "data" / "communication_originals" / family / key[:2] / (key + ".json")
        payload = {"schema": "lm25.communication.original.v1", "family": family, **clean}
        if web and path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            if web_capture_score(clean) < web_capture_score(previous):
                upgraded = _upgrade_time(previous, clean)
                if upgraded != previous:
                    _atomic_text(path, json.dumps(upgraded, ensure_ascii=False, indent=2))
                count += 1
                continue
            payload = _upgrade_time(payload, previous)
            if payload == previous:
                count += 1
                continue  # Repeated overlapping pages need no new fsync/write.
        if clean.get("source_kind") in {"teams_graph", "outlook_graph"} and path.exists():
            previous = json.loads(path.read_text(encoding="utf-8"))
            try:
                old = datetime.fromisoformat(str(previous.get("modified_time") or "").replace("Z", "+00:00"))
                new = datetime.fromisoformat(str(clean.get("modified_time") or "").replace("Z", "+00:00"))
                if old.tzinfo and new.tzinfo and new < old:
                    count += 1
                    continue
            except (ValueError, TypeError):
                pass
        _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
        count += 1
    return count
