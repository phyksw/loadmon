"""Read explicitly selected mail/Teams exports; never discover account caches.

Normalized CSVs, full-body evidence and count-only import status are written
under root. Source files remain unchanged; summaries contain counts,
not message content, addresses, or selected paths. MSG/PST are unsupported.
"""
from __future__ import annotations

import csv
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
    from .communication_exports import ExportError, load_export, parse_record
    from .communication_archive import archive_records
except ImportError:
    from collection_state import merge_csv, read_csv, record_key, write_status
    from communication_exports import ExportError, load_export, parse_record
    from communication_archive import archive_records


FIELDS = ("box", "time", "sender", "subject", "conversation", "rcv", "time_precision",
          "context_excerpt", "context_truncated", "source_id", "source_kind", "source_url",
          "conversation_id", "folder", "account", "message_id", "in_reply_to", "references",
          "sender_address", "to_addresses", "cc_addresses", "date_original", "time_utc",
          "source_sha256", "message_fingerprint", "attachment_count", "import_format")
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
PERSIST_BATCH_ROWS = 1000


class ImportPersistenceError(RuntimeError):
    """Writing evidence failed; do not downgrade it to a malformed input."""


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
    row["_full_body"] = body
    defects = any(part.defects for part in message.walk())
    return row, stamp.date() if stamp else None, defects


def import_paths(root, paths, d0, d1, config=None):
    """Import selected EML/MBOX, Graph JSON or explicit normalized v1 exports.

    Counts describe selected files, never the whole mailbox or tenant. Optional
    communicationImportExpectedCount is the number of records before date filters,
    including duplicates. Unknown normalized dates/timezones are rejected.
    """
    d0, d1 = date.fromisoformat(str(d0)), date.fromisoformat(str(d1))
    if d0 > d1:
        raise ValueError("invalid_date_range")
    if isinstance(paths, (str, Path)):
        paths = [paths]
    collection = (config or {}).get("collection") or {}
    recursive = bool(collection.get("communicationImportRecursive", False))
    context_chars = min(20000, max(0, int(collection.get("contextChars", 4000))))
    # No record/file-count cap: retrying a fixed prefix would strand later data.
    # File/record byte limits remain explicit, independently configurable bounds.
    max_file_mb = collection.get("communicationImportMaxFileMB", MAX_FILE_BYTES // (1024 * 1024))
    max_json_mb = collection.get("communicationImportMaxJsonMB", 64)
    if any(type(value) is not int or not 1 <= value <= 16384 for value in (max_file_mb, max_json_mb)):
        raise ValueError("invalid_export_size_limit")
    max_file_bytes, max_json_bytes = max_file_mb * 1024 * 1024, max_json_mb * 1024 * 1024
    own = collection.get("communicationImportOwnAddresses") or []
    if isinstance(own, str):
        own = re.split(r"[;,\s]+", own)
    own = {str(item).strip().casefold() for item in own if str(item).strip()}
    account = str(collection.get("communicationImportAccount") or "").strip()
    expected = collection.get("communicationImportExpectedCount")
    if expected is not None and (type(expected) is not int or expected < 0):
        raise ValueError("invalid_expected_count")
    counters = ("files", "messages", "observed", "added", "duplicates", "outside_range", "undated",
                "unsupported", "errors", "malformed", "body_rows", "truncated", "unknown_direction",
                "discarded", "body_missing", "archived")
    counts = dict.fromkeys(counters, 0)
    family_counts = {family: dict.fromkeys(counters, 0) for family in ("mail", "teams")}
    reasons, selected, visited = [], [], set()
    formats = set()
    outputs = {"mail": Path(root) / "data/outlook/mail.csv", "teams": Path(root) / "data/m365/teams_import.csv"}
    existing = {family: read_csv(path) for family, path in outputs.items()}
    known = {family: {record_key(row, family) for row in rows} for family, rows in existing.items()}
    fingerprints = {family: {record_key(row, family): row.get("message_fingerprint", "") for row in rows}
                    for family, rows in existing.items()}
    pending = {"mail": [], "teams": []}
    extensions = {".eml", ".mbox", ".json", ".jsonl", ".csv"}

    def bump(counter, family=None, value=1):
        counts[counter] += value
        if family in family_counts:
            family_counts[family][counter] += value

    def problem(reason, counter="errors", family=None):
        bump(counter, family)
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
                    if item.is_file() and not item.is_symlink() and item.suffix.lower() in extensions:
                        selected.append(item)
            elif candidate.is_file():
                selected.append(candidate)
            else:
                problem("input_not_regular_file")
        except (OSError, ValueError, TypeError):
            problem("input_unavailable")

    def flush(family):
        rows = pending[family]
        if rows:
            try:
                merge_csv(outputs[family], rows, FIELDS if family == "mail" else
                          ("time", "kind", "from", "chat", "summary", "time_precision"), kind=family)
            except (OSError, ValueError) as error:
                raise ImportPersistenceError("normalized_evidence_write_failed") from error
            rows.clear()

    def accept(family, row, when):
        if when is None:
            problem("undated_message_skipped", "undated", family)
            bump("discarded", family)
            return
        if not d0 <= when <= d1:
            bump("outside_range", family)
            return
        key = record_key(row, family)
        if fingerprints[family].get(key) and fingerprints[family][key] != row["message_fingerprint"]:
            row["source_id"] += ":collision:" + row["message_fingerprint"]
            key = record_key(row, family)
            problem("conflicting_message_id_retained_separately", "malformed", family)
        fingerprints[family][key] = row["message_fingerprint"]
        # Archive complete plain body BEFORE publishing its bounded analysis row.
        # Failure propagates: an old success receipt must not be written for it.
        body = row.pop("_full_body")
        try:
            archived = archive_records(root, family, [dict(row, body=body)])
        except (OSError, ValueError) as error:
            raise ImportPersistenceError("original_evidence_write_failed") from error
        bump("archived", family, archived)
        if key in known[family]:
            bump("duplicates", family)
        else:
            known[family].add(key)
            bump("added", family)
        bump("observed", family)
        bump("body_rows", family, bool(row["context_excerpt"]))
        bump("truncated", family, row["context_truncated"] == "true")
        bump("unknown_direction", family, family == "mail" and row["box"] == "unknown")
        pending[family].append(row)
        if len(pending[family]) >= PERSIST_BATCH_ROWS:
            flush(family)

    def consume(raw, path, kind):
        bump("messages", "mail")
        if len(raw) > MAX_MESSAGE_BYTES:
            problem("message_size_limit", family="mail")
            bump("discarded", "mail")
            return
        try:
            row, when, defects = _parse(raw, path, kind, context_chars, own, account)
        except (ValueError, TypeError, LookupError, UnicodeError, OverflowError, IndexError):
            problem("message_parse_failed", family="mail")
            bump("discarded", "mail")
            return
        if defects:
            problem("malformed_mime", "malformed", "mail")
        accept("mail", row, when)

    def consume_export(kind, item, hint, path, format_name):
        family = "teams" if kind == "graph" else item.get("family") if isinstance(item, dict) else None
        if family not in family_counts:
            family = None
        bump("messages", family)
        def visible_html(body):
            parser = _VisibleHTML()
            parser.feed(body)
            return "".join(parser.parts)
        try:
            family, row, when = parse_record(kind, item, hint, path, context_chars, account, visible_html)
        except ExportError as error:
            code = str(error)
            counter = "undated" if code == "undated_or_timezone_unknown" else "body_missing" if code == "body_missing" else "malformed"
            problem(code, counter, family)
            bump("discarded", family)
            return
        row["import_format"] = format_name
        accept(family, row, when)

    # Mark this selected-file run in progress so failure cannot leave an old
    # complete status looking like the result of the new attempt.
    write_status(root, "communication_import", d0, d1, status="partial", scope="selected export files only",
                 reasons=["import_in_progress"], mail_status="partial", teams_status="partial")
    for path in selected:
        if path in visited:
            continue
        visited.add(path)
        counts["files"] += 1
        suffix = path.suffix.lower()
        if suffix not in extensions:
            problem("unsupported_export_format", "unsupported")
            continue
        try:
            if path.stat().st_size > (MAX_MESSAGE_BYTES if suffix == ".eml" else max_file_bytes):
                problem("file_size_limit")
                continue
            if suffix == ".eml":
                formats.add("eml")
                family_counts["mail"]["files"] += 1
                with path.open("rb") as stream:
                    consume(stream.read(MAX_MESSAGE_BYTES + 1), path, "eml")
            elif suffix == ".mbox":
                formats.add("mbox")
                family_counts["mail"]["files"] += 1
                box = mailbox.mbox(path, create=False)
                try:
                    before = counts["messages"]
                    for key in box.iterkeys():
                        with box.get_file(key) as stream:
                            consume(stream.read(MAX_MESSAGE_BYTES + 1), path, "mbox")
                    if counts["messages"] == before and path.stat().st_size:
                        problem("nonempty_mbox_has_no_messages")
                finally:
                    box.close()
            else:
                format_name, records, warnings = load_export(path, max_json_bytes=max_json_bytes)
                formats.add(format_name)
                for reason in warnings:
                    problem(reason, "malformed")
                file_families = set()
                before = counts["messages"]
                for kind, item, hint in records:
                    family = "teams" if kind == "graph" else item.get("family") if isinstance(item, dict) else None
                    if family in family_counts:
                        file_families.add(family)
                    consume_export(kind, item, hint, path, format_name)
                if counts["messages"] == before and format_name == "jsonl":
                    problem("empty_export")
                for family in file_families:
                    family_counts[family]["files"] += 1
        except ExportError as error:
            problem(str(error), "unsupported")
        except (OSError, ValueError, mailbox.Error, UnicodeError, csv.Error):
            problem("file_read_failed")
        # A persistence error must escape rather than be reported as read failure.
        for family in pending:
            flush(family)
    if not selected:
        problem("no_supported_files_selected")
    if expected is not None and counts["messages"] != expected:
        problem("selected_export_expected_count_mismatch", "malformed")
    partial = bool(reasons)
    status = "partial" if partial and counts["observed"] else "failed" if partial else "complete"
    final_counts = {family: len(read_csv(path)) for family, path in outputs.items()}
    for family in family_counts:
        family_counts[family]["added"] = max(0, final_counts[family] - len(existing[family]))
    counts["added"] = sum(value["added"] for value in family_counts.values())
    reconciliation = {"scope": "selected_export_only", "expected_count": expected,
                      "encountered_count": counts["messages"],
                      "matched": counts["messages"] == expected if expected is not None else None,
                      "server_coverage_verified": False,
                      "selected_files_fully_processed": not bool(reasons),
                      "count_reconciled": counts["messages"] == counts["observed"] + counts["outside_range"] + counts["discarded"]}
    family_status = {family: (status if value["messages"] else "skipped") for family, value in family_counts.items()}
    return write_status(root, "communication_import", d0, d1, status=status,
                        rows=counts["observed"], scope="explicitly selected export files within requested dates; not mailbox or chat coverage",
                        reasons=reasons, counts=counts, family_counts=family_counts, formats=sorted(formats),
                        reconciliation=reconciliation, imported_rows=counts["added"],
                        limits={"max_file_mb": max_file_mb, "max_json_csv_mb": max_json_mb,
                                "max_message_bytes": MAX_MESSAGE_BYTES, "record_count_limit": None},
                        observed_rows=counts["observed"], existing_total=sum(final_counts.values()),
                        existing_totals=final_counts, mail_status=family_status["mail"], teams_status=family_status["teams"],
                        calendar_status="skipped", mail_rows=family_counts["mail"]["observed"],
                        teams_rows=family_counts["teams"]["observed"], calendar_rows=0, recursive=recursive)
