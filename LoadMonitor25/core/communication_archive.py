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

from collection_state import _atomic_text


FIELDS = {"body", "source_id", "source_kind", "conversation_id", "account", "time",
          "createdDateTime", "lastModifiedDateTime", "sender", "from", "subject",
          "chat", "conversation", "box", "rcv", "source_url", "internet_message_id",
          "reply_to_id", "body_format", "time_precision", "modified_time", "time_utc",
          "message_id", "in_reply_to", "references"}


def archive_records(root, family, records):
    """Persist each complete plain-text body before advancing a collector cursor."""
    if family not in {"mail", "teams"}:
        raise ValueError("Unsupported communication family")
    count = 0
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("body"), str):
            raise ValueError("A full text body is required for original evidence")
        clean = {key: value for key, value in record.items() if key in FIELDS
                 and isinstance(value, (str, int, float, bool))}
        identity = [family, str(clean.get("account", "")), str(clean.get("conversation_id", "")),
                    str(clean.get("source_id", ""))]
        if not identity[-1]:
            identity.append(json.dumps(clean, ensure_ascii=False, sort_keys=True))
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        path = Path(root) / "data" / "communication_originals" / family / key[:2] / (key + ".json")
        payload = {"schema": "lm25.communication.original.v1", "family": family, **clean}
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
