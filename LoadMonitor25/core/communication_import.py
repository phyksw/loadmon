"""Read explicitly selected EML/MBOX exports; never discover account caches.

Only data/outlook/mail.csv and data/collection_status/communication_import.json
are written under root. Source files remain unchanged; summaries contain counts,
not message content, addresses, or selected paths. MSG/PST are unsupported.
"""
from __future__ import annotations

from datetime import UTC, date
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import mailbox
from pathlib import Path
import re

try:
    from .collection_state import merge_csv, read_csv, record_key, write_status
except ImportError:
    from collection_state import merge_csv, read_csv, record_key, write_status


FIELDS = ("box", "time", "sender", "subject", "conversation", "rcv", "time_precision",
          "context_excerpt", "context_truncated", "source_id", "source_kind", "source_url",
          "conversation_id", "folder", "account", "message_id", "in_reply_to", "references",
          "sender_address", "to_addresses", "cc_addresses", "date_original", "time_utc",
          "source_sha256", "message_fingerprint", "attachment_count", "import_format")
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_MESSAGES = 10000
MAX_FILES = 10000


class _VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "tr"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _header(message, name):
    return str(message.get(name) or "").strip()[:16384]


def _addresses(message, name):
    return [address.casefold() for _, address in getaddresses(message.get_all(name, [])) if address]


def _body(message):
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None or part.get_content_disposition() == "attachment":
        return ""
    value = part.get_content()
    if not isinstance(value, str):
        return ""
    if part.get_content_type() == "text/html":
        parser = _VisibleHTML()
        parser.feed(value)
        value = "".join(parser.parts)
    return re.sub(r"[ \t]+", " ", value.replace("\r\n", "\n")).strip()


def _parse(raw, path, format_name, context_chars, own_addresses, account):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if not any(message.get(name) for name in ("From", "To", "Subject", "Message-ID", "Date")):
        raise ValueError("not_email")
    original_date = _header(message, "Date")
    try:
        stamp = parsedate_to_datetime(original_date) if original_date else None
    except (TypeError, ValueError, OverflowError):
        stamp = None
    # The Date header is a sender-declared time, not proof of delivery time.
    # Missing timezone stays unverified; never assign today's date to an export.
    utc = ""
    if stamp and stamp.tzinfo is not None:
        utc = stamp.astimezone(UTC).isoformat()
        stamp = stamp.astimezone()
    sender_addresses = _addresses(message, "From")
    to_addresses, cc_addresses = _addresses(message, "To"), _addresses(message, "Cc")
    sender = sender_addresses[0] if sender_addresses else _header(message, "From")
    box, rcv = "unknown", ""
    if set(sender_addresses) & own_addresses:
        box = "sent"
    elif set(to_addresses + cc_addresses) & own_addresses:
        box = "inbox"
        rcv = "to" if set(to_addresses) & own_addresses else "cc"
    subject = _header(message, "Subject")
    conversation = re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", subject, flags=re.I).strip()
    message_id = _header(message, "Message-ID")
    references, in_reply_to = _header(message, "References"), _header(message, "In-Reply-To")
    digest = hashlib.sha256(raw).hexdigest()
    body = _body(message)
    canonical = "\0".join((sender, ";".join(sorted(to_addresses)), ";".join(sorted(cc_addresses)),
                             utc or original_date, subject, re.sub(r"\s+", " ", body).strip()))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    identity = hashlib.sha256(message_id.encode("utf-8")).hexdigest() if message_id else fingerprint
    row = dict(zip(FIELDS, [""] * len(FIELDS), strict=True))
    row.update(box=box, time=stamp.strftime("%Y-%m-%d %H:%M:%S") if stamp else "",
               time_precision="second" if utc else "unknown", sender=sender, subject=subject,
               conversation=conversation, rcv=rcv, context_excerpt=body[:context_chars],
               context_truncated=str(len(body) > context_chars).lower(), source_id="mail-import:" + identity,
               source_kind="mail-import", source_url=path.as_uri(), conversation_id="",
               account=account, message_id=message_id, in_reply_to=in_reply_to, references=references,
               sender_address=";".join(sender_addresses), to_addresses=";".join(to_addresses),
               cc_addresses=";".join(cc_addresses), date_original=original_date, time_utc=utc,
               source_sha256=digest, message_fingerprint=fingerprint, attachment_count=str(sum(1 for p in message.walk()
                   if p.get_content_disposition() == "attachment")), import_format=format_name)
    defects = any(part.defects for part in message.walk())
    return row, stamp.date() if stamp else None, defects


def import_paths(root, paths, d0, d1, config=None):
    """Import selected files into the existing mail CSV and return a private-safe summary.

    collection.communicationImportRecursive controls directory recursion (default
    false); communicationImportOwnAddresses optionally identifies sent/received
    direction; communicationImportAccount scopes IDs. Unknown direction is kept
    explicitly, never inferred from filename or message wording.
    """
    d0, d1 = date.fromisoformat(str(d0)), date.fromisoformat(str(d1))
    if d0 > d1:
        raise ValueError("invalid_date_range")
    if isinstance(paths, (str, Path)):
        paths = [paths]
    collection = (config or {}).get("collection") or {}
    recursive = bool(collection.get("communicationImportRecursive", False))
    context_chars = min(20000, max(0, int(collection.get("contextChars", 4000))))
    own = collection.get("communicationImportOwnAddresses") or []
    if isinstance(own, str):
        own = re.split(r"[;,\s]+", own)
    own = {str(item).strip().casefold() for item in own if str(item).strip()}
    account = str(collection.get("communicationImportAccount") or "").strip()
    counts = dict.fromkeys(("files", "messages", "observed", "added", "duplicates", "outside_range",
              "undated", "unsupported", "errors", "malformed", "body_rows", "truncated", "unknown_direction"), 0)
    reasons, selected, visited = [], [], set()
    output = Path(root) / "data" / "outlook" / "mail.csv"

    def problem(reason, counter="errors"):
        counts[counter] += 1
        if reason not in reasons:
            reasons.append(reason)

    for supplied in paths or []:
        try:
            candidate = Path(supplied).expanduser()
            if candidate.is_symlink():
                problem("symlink_not_imported")
                continue
            candidate = candidate.resolve(strict=True)
            if candidate.is_dir():
                iterator = candidate.rglob("*") if recursive else candidate.iterdir()
                for item in iterator:
                    # Path.rglob does not recurse symlink directories; reject leaf links too.
                    if item.is_file() and not item.is_symlink() and item.suffix.lower() in {".eml", ".mbox"}:
                        selected.append(item)
                        if len(selected) >= MAX_FILES:
                            problem("selected_file_limit_reached")
                            break
            elif candidate.is_file():
                selected.append(candidate)
            else:
                problem("input_not_regular_file")
        except (OSError, ValueError, TypeError):
            problem("input_unavailable")
        if len(selected) >= MAX_FILES:
            break
    existing = read_csv(output)
    known = {record_key(row) for row in existing}
    fingerprints = {record_key(row): row.get("message_fingerprint", "") for row in existing}
    pending = []

    def consume(raw, path, kind):
        counts["messages"] += 1
        if len(raw) > MAX_MESSAGE_BYTES:
            problem("message_size_limit")
            return
        try:
            row, when, defects = _parse(raw, path, kind, context_chars, own, account)
        except (ValueError, TypeError, LookupError, UnicodeError, OverflowError, IndexError):
            problem("message_parse_failed")
            return
        if defects:
            problem("malformed_mime", "malformed")
        if when is None:
            problem("undated_message_skipped", "undated")
            return
        if not d0 <= when <= d1:
            counts["outside_range"] += 1
            return
        key = record_key(row)
        if fingerprints.get(key) and fingerprints[key] != row["message_fingerprint"]:
            row["source_id"] += ":collision:" + row["message_fingerprint"]
            key = record_key(row)
            problem("conflicting_message_id_retained_separately", "malformed")
        fingerprints[key] = row["message_fingerprint"]
        if key in known:
            counts["duplicates"] += 1
        else:
            known.add(key)
            counts["added"] += 1
        counts["observed"] += 1
        counts["body_rows"] += bool(row["context_excerpt"])
        counts["truncated"] += row["context_truncated"] == "true"
        counts["unknown_direction"] += row["box"] == "unknown"
        pending.append(row)

    for path in selected:
        if path in visited:
            continue
        visited.add(path)
        counts["files"] += 1
        suffix = path.suffix.lower()
        if suffix not in {".eml", ".mbox"}:
            problem("unsupported_format_eml_mbox_only", "unsupported")
            continue
        try:
            if path.stat().st_size > (MAX_MESSAGE_BYTES if suffix == ".eml" else MAX_FILE_BYTES):
                problem("file_size_limit")
                continue
            if suffix == ".eml":
                with path.open("rb") as stream:
                    consume(stream.read(MAX_MESSAGE_BYTES + 1), path, "eml")
            else:
                box = mailbox.mbox(path, create=False)
                try:
                    before = counts["messages"]
                    for key in box.iterkeys():
                        if counts["messages"] >= MAX_MESSAGES:
                            problem("message_count_limit")
                            break
                        with box.get_file(key) as stream:
                            consume(stream.read(MAX_MESSAGE_BYTES + 1), path, "mbox")
                    if counts["messages"] == before and path.stat().st_size:
                        problem("nonempty_mbox_has_no_messages")
                finally:
                    box.close()
        except (OSError, ValueError, mailbox.Error):
            problem("file_read_failed")
        if pending:
            merge_csv(output, pending, FIELDS)
            pending.clear()
        if counts["messages"] >= MAX_MESSAGES:
            problem("message_count_limit")
            break
    if not selected:
        problem("no_supported_files_selected")
    partial = bool(reasons)
    status = "partial" if partial and counts["observed"] else "failed" if partial else "complete"
    final_count = len(read_csv(output))
    counts["added"] = max(0, final_count - len(existing))
    result = write_status(root, "communication_import", d0, d1, status=status,
                          rows=counts["observed"], scope="explicitly selected EML/MBOX export files within requested dates; not mailbox coverage",
                          reasons=reasons, counts=counts, imported_rows=counts["added"],
                          observed_rows=counts["observed"], existing_total=final_count,
                          mail_status=status, calendar_status="skipped", mail_rows=counts["observed"],
                          calendar_rows=0, recursive=recursive)
    return result
