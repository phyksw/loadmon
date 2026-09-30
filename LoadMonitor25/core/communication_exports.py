"""Strict offline communication formats; no account access, URL fetch or XML execution.

Graph: https://learn.microsoft.com/en-us/graph/api/resources/chatmessage
and https://learn.microsoft.com/en-us/graph/api/chats-getallmessages
LM25 normalized v1 is our explicit conversion contract, not a Microsoft schema.
Personal Teams messages.json and Purview transcripts require conversion until
their exact producer schema can be independently verified.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import re
from urllib.parse import unquote

try:
    from .collection_state import read_csv
except ImportError:
    from collection_state import read_csv

SCHEMA = "lm25.communication.v1"
REQUIRED = {"family", "time", "body", "conversation_id", "source_id", "sender"}
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_RECORD_BYTES = 16 * 1024 * 1024


class ExportError(ValueError):
    """Fixed diagnostic codes only; never include selected content or paths."""


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _graph(item):
    return isinstance(item, dict) and {"id", "createdDateTime", "body", "from"} <= item.keys()


def _jsonl_records(path):
    # Bound one record, not the whole export. Invalid/oversized lines are counted
    # once and later records remain reachable on this same run.
    with path.open("rb") as stream:
        first = True
        while True:
            line = stream.readline(MAX_RECORD_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_RECORD_BYTES:
                while line and not line.endswith(b"\n"):
                    line = stream.readline(MAX_RECORD_BYTES + 1)
                yield "oversize", None, ""
                first = False
                continue
            if first:
                line = line.removeprefix(b"\xef\xbb\xbf")
                first = False
            if not line.strip():
                continue
            try:
                item = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeError):
                item = None
            yield ("graph" if _graph(item) else "normalized"), item, ""


def load_export(path, max_json_bytes=MAX_EXPORT_BYTES):
    """Return (format, records, fixed warnings); malformed rows remain countable.

    Records carry a parser kind plus declared containing conversation, never a
    guessed room name. JSONL supports standalone Graph or schema-marked v1 rows.
    """
    if path.suffix.lower() == ".jsonl":
        return "jsonl", _jsonl_records(path), []
    if path.stat().st_size > max_json_bytes:
        raise ExportError("export_file_size_limit")
    if path.suffix.lower() == ".csv":
        rows = read_csv(path)
        if not rows or not (REQUIRED | {"schema"}) <= rows[0].keys():
            raise ExportError("normalized_csv_schema_required")
        return "lm25-csv", [("normalized", row, "") for row in rows], []
    payload = json.loads(path.read_text("utf-8-sig"))
    warnings = []
    if isinstance(payload, dict) and payload.get("schema") == SCHEMA:
        messages = payload.get("messages")
        if not isinstance(messages, list):
            if REQUIRED <= payload.keys():
                messages = [payload]
            else:
                raise ExportError("normalized_json_messages_required")
        rows = [("normalized", dict(item, schema=SCHEMA) if isinstance(item, dict) else item, "") for item in messages]
        expected = payload.get("expected_count")
        if expected is not None and (type(expected) is not int or expected < 0 or expected != len(messages)):
            warnings.append("export_declared_count_mismatch")
        return "lm25-json", rows, warnings
    if isinstance(payload, dict) and "conversations" in payload:
        raise ExportError("personal_teams_export_requires_normalized_conversion")
    pages = payload if isinstance(payload, list) and payload and all(isinstance(p, dict) and "value" in p for p in payload) else [payload]
    rows = []
    for page in pages:
        conversation = ""
        if isinstance(page, dict) and isinstance(page.get("value"), list):
            context = str(page.get("@odata.context") or "")
            messages = page["value"]
            if not ("chatMessage" in context or "/messages" in context or any(_graph(item) for item in messages)):
                raise ExportError("graph_chatmessage_schema_required")
            match = re.search(r"chats\('([^']+)'\)", context)
            conversation = unquote(match.group(1)) if match else ""
            if page.get("@odata.nextLink"):
                warnings.append("graph_page_has_unverified_next_page")
        elif isinstance(page, list) and page and any(_graph(item) for item in page):
            messages = page
        elif _graph(page):
            messages = [page]
        else:
            raise ExportError("unsupported_json_schema")
        rows.extend(("graph", item, conversation) for item in messages)
    return "graph-json", rows, list(dict.fromkeys(warnings))


def parse_record(kind, item, conversation_hint, path, context_chars, account, visible_html):
    """Normalize one strict dated message; body remains full until archive write."""
    if kind == "oversize":
        raise ExportError("message_size_limit")
    if not isinstance(item, dict):
        raise ExportError("malformed_export_record")
    if kind == "graph":
        if not _graph(item):
            raise ExportError("malformed_graph_message")
        if item.get("deletedDateTime") or item.get("@removed"):
            raise ExportError("deleted_message_without_original_body")
        if item.get("messageType", "message") != "message":
            raise ExportError("non_message_event_skipped")
        family, source_kind = "teams", "teams-graph-import"
        channel = item.get("channelIdentity") or {}
        if not isinstance(channel, dict):
            raise ExportError("malformed_graph_conversation")
        conversation = _text(item.get("chatId")) or conversation_hint
        if not conversation and channel.get("teamId") and channel.get("channelId"):
            conversation = "channel:" + str(channel["teamId"]) + "/" + str(channel["channelId"])
        sender_set = item.get("from") or {}
        if not isinstance(sender_set, dict):
            raise ExportError("malformed_graph_sender")
        sender_data = sender_set.get("user") or sender_set.get("application") or sender_set.get("device") or {}
        if not isinstance(sender_data, dict):
            raise ExportError("malformed_graph_sender")
        sender_id = _text(sender_data.get("id"))
        sender = _text(sender_data.get("displayName")) or sender_id
        source_id = _text(item.get("id"))
        if not source_id:
            raise ExportError("required_identity_or_sender_missing")
        if conversation.startswith("channel:"):
            reply = _text(item.get("replyToId"))
            source_id = "graph-channel:" + conversation.removeprefix("channel:") + "/" + (reply + "/" if reply else "") + source_id
        else:
            source_id = "graph:" + conversation + "/" + source_id if source_id else ""
        stamp = item.get("createdDateTime")
        body_obj = item.get("body")
        if not isinstance(body_obj, dict) or body_obj.get("contentType") not in {"html", "text"}:
            raise ExportError("malformed_graph_body")
        body = body_obj.get("content")
        html = body_obj.get("contentType") == "html"
        subject = _text(item.get("subject"))
        title, box, rcv = conversation, "unknown", ""
        source_url = _text(item.get("webUrl"))
        original_id = _text(item.get("id"))
        reply_to = _text(item.get("replyToId"))
    else:
        if item.get("schema") != SCHEMA or not REQUIRED <= item.keys():
            raise ExportError("normalized_record_schema_required")
        family = item.get("family")
        if family not in {"mail", "teams"}:
            raise ExportError("normalized_family_invalid")
        source_kind = "teams-normalized-import" if family == "teams" else "mail-normalized-import"
        conversation, source_id = _text(item.get("conversation_id")), _text(item.get("source_id"))
        original_id = source_id
        # Administrator conversion IDs have no proven equivalence to Graph/COM IDs.
        source_id = "normalized:" + source_id if source_id else ""
        sender, sender_id = _text(item.get("sender")), _text(item.get("sender_id"))
        stamp, body, html = item.get("time"), item.get("body"), False
        subject = _text(item.get("subject"))
        title = _text(item.get("conversation")) or conversation
        box, rcv = _text(item.get("box")) or "unknown", _text(item.get("rcv"))
        if box not in {"sent", "inbox", "unknown"} or rcv not in {"", "to", "cc"}:
            raise ExportError("normalized_direction_invalid")
        account = _text(item.get("account")) or account
        source_url = _text(item.get("source_url"))
        reply_to = _text(item.get("in_reply_to"))
    if not conversation or not source_id or not sender:
        raise ExportError("required_identity_or_sender_missing")
    if not isinstance(body, str):
        raise ExportError("body_missing")
    if len(body.encode("utf-8")) > 16 * 1024 * 1024:
        raise ExportError("message_size_limit")
    if html:
        body = visible_html(body)
    body = body.replace("\r\n", "\n").strip()
    if not body:
        raise ExportError("body_missing")
    try:
        if not isinstance(stamp, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", stamp):
            raise ValueError()
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError()
        utc = when.astimezone(UTC).isoformat()
        local = when.astimezone()
    except (ValueError, TypeError, OverflowError):
        raise ExportError("undated_or_timezone_unknown") from None
    fingerprint = hashlib.sha256(json.dumps([family, conversation, sender, utc, subject, body], ensure_ascii=False).encode()).hexdigest()
    row = {"time": local.strftime("%Y-%m-%d %H:%M:%S"), "time_utc": utc, "date_original": stamp,
           "time_precision": "second", "source_id": source_id, "source_kind": source_kind,
           "source_url": source_url or path.as_uri(), "conversation_id": conversation, "account": account,
           "context_excerpt": body[:context_chars], "context_truncated": str(len(body) > context_chars).lower(),
           "message_fingerprint": fingerprint, "message_id": original_id, "in_reply_to": reply_to,
           "sender_id": sender_id, "_full_body": body}
    if family == "teams":
        row.update(kind="sent" if box == "sent" else "msg", chat=title, **{"from": sender}, summary=(subject or body)[:240])
    else:
        row.update(box=box, sender=sender, subject=subject or body[:100], conversation=title, rcv=rcv)
    return family, row, local.date()
