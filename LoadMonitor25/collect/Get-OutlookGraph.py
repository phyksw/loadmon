"""App-owned Graph Mail.Read collection of the signed-in primary mailbox.

All /me/messages pages (including custom/deleted folders) matching sent OR
received dates are visited. Direction selects the final period timestamp. Online
archive, other users/shared mailboxes, purged items, attachments and draft-only
activity are outside this scope. Use --login-only to explicitly authorize the app.
"""
import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from collection_state import merge_csv, read_csv, record_key, write_status  # noqa: E402
from communication_archive import archive_records  # noqa: E402
from graph_client import GraphAuth, GraphBudget, GraphClient, GraphError, PageRun, local_bounds, parse_time, plain_body, query  # noqa: E402

FIELDS = ["box", "time", "sender", "subject", "conversation", "rcv", "time_precision",
          "context_excerpt", "context_truncated", "source_id", "source_kind", "source_url",
          "conversation_id", "folder", "account", "message_id", "in_reply_to", "references",
          "sender_address", "to_addresses", "cc_addresses", "date_original", "time_utc", "received_time", "sent_time", "modified_time", "context_available"]
SELECT = "id,subject,from,sender,toRecipients,ccRecipients,receivedDateTime,sentDateTime,lastModifiedDateTime,body,conversationId,parentFolderId,internetMessageId,internetMessageHeaders,webLink,isDraft"
SCOPE = "Graph /me/messages primary mailbox folders incl custom/deleted; sent/received date by direction; excludes online archive/shared mailboxes/drafts/attachments/purged items"
HEADERS = {"Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"'}


def load_config():
    try:
        return json.loads((ROOT / "config/config.json").read_text("utf-8-sig"))
    except (OSError, ValueError):
        return {}


def collect(root, config, d0, d1, *, interactive=False, budget=240, force=False, client=None, tz=None):
    root = Path(root)
    start, until = local_bounds(d0, d1, tz)
    deadline = (client.clock() if client else time.monotonic()) + max(0, budget)
    output = root / "data/outlook/mail.csv"
    collection = config.get("collection") or {}
    context_chars = max(0, min(20000, int(collection.get("contextChars", 4000))))
    store_subject = config.get("storeMailSubject", True)
    want_body = bool(collection.get("mailBody", True)) and bool(store_subject) and context_chars > 0
    result = None

    def status(state, reasons=(), **extra):
        return write_status(root, "outlook_graph", d0, d1, status=state, scope=SCOPE,
                            reasons=reasons, mail_status=state, calendar_status="skipped", calendar_rows=0, **extra)
    status("partial", ["collection_in_progress"])
    if client is None:
        auth = GraphAuth(root, config)
        token, error = auth.acquire(interactive)
        if not token:
            return status("blocked", [error], auth_state="unconfigured" if str(error).startswith("unconfigured") else "authentication_required")
        client = GraphClient(token, headers=HEADERS, refresh=lambda: auth.acquire(False, force_refresh=True))
    try:
        me = client.get(query("/me", **{"$select": "id,mail,userPrincipalName,otherMails"}), deadline)
        if not isinstance(me, dict) or not me.get("id"):
            raise GraphError("identity_missing")
        own = {str(value).strip().casefold() for value in [me.get("mail"), me.get("userPrincipalName"),
                *(me.get("otherMails") or []), *((config.get("graph") or {}).get("ownAddresses") or [])] if value}
        account = str((config.get("graph") or {}).get("tenantId") or "organizations") + ":" + str(me["id"])
        try:
            sent_folder = client.get(query("/me/mailFolders/sentitems", **{"$select": "id"}), deadline).get("id")
        except GraphError:
            sent_folder = None
        run = PageRun(root, "outlook_graph", account, d0, d1,
                      {"context": context_chars, "store_subject": bool(store_subject), "body": want_body, "version": 1}, client, force)
        z0, z1 = [value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") for value in (start, until)]
        # Both ranges include moved sent mail; folder membership never narrows the API inventory.
        for field in ("receivedDateTime", "sentDateTime"):
            selected_fields = SELECT if want_body else ",".join(field for field in SELECT.split(",") if field != "body")
            url = query("/me/messages", **{"$top": 100, "$select": selected_fields,
                        "$filter": f"{field} ge {z0} and {field} lt {z1}"})
            run.add(field, "mail_messages", url)

        def handler(unit, items):
            rows, full, issues = [], [], []
            for message in items:
                if not isinstance(message, dict) or not message.get("id"):
                    issues.append("message_id_missing")
                    continue
                if message.get("isDraft"):
                    continue
                sender = (message.get("from") or {}).get("emailAddress") or {}
                sender_address = str(sender.get("address") or "").casefold()
                sending_address = str(((message.get("sender") or {}).get("emailAddress") or {}).get("address") or "").casefold()
                sent = (bool(own & {sender_address, sending_address})
                        or bool(sent_folder and message.get("parentFolderId") == sent_folder))
                to = [str((r.get("emailAddress") or {}).get("address") or "").casefold() for r in message.get("toRecipients") or []]
                cc = [str((r.get("emailAddress") or {}).get("address") or "").casefold() for r in message.get("ccRecipients") or []]
                incoming = bool(own & set(to + cc))
                direction = "sent" if sent else "inbox" if incoming else "unknown"
                date_field = "sentDateTime" if sent else "receivedDateTime" if incoming else unit["key"]
                when = parse_time(message.get(date_field), tz)
                if when is None:
                    issues.append("message_time_unreadable")
                    continue
                if not start <= when < until:
                    continue
                available = want_body and isinstance(message.get("body"), dict) and isinstance(message["body"].get("content"), str)
                body = plain_body(message.get("body")) if available else ""
                if want_body and not available:
                    issues.append("message_body_unavailable")
                headers = {str(h.get("name") or "").lower(): str(h.get("value") or "")
                           for h in message.get("internetMessageHeaders") or [] if isinstance(h, dict)}
                subject = str(message.get("subject") or "")
                if not store_subject:
                    subject, body = "", ""
                row = {"box": direction, "time": when.strftime("%Y-%m-%d %H:%M:%S"),
                    "sender": str(sender.get("name") or sender_address), "subject": subject,
                    "conversation": re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", subject, flags=re.I).strip(),
                    "rcv": "" if sent else "to" if own & set(to) else "cc" if own & set(cc) else "",
                    "time_precision": "second" if direction != "unknown" else "unknown", "context_excerpt": body[:context_chars],
                    "context_available": str(available).lower(),
                    "context_truncated": str(len(body) > context_chars).lower(), "source_id": "outlook-graph:" + message["id"],
                    "source_kind": "outlook_graph", "source_url": str(message.get("webLink") or ""),
                    "conversation_id": str(message.get("conversationId") or ""), "folder": str(message.get("parentFolderId") or ""),
                    "account": account, "message_id": str(message.get("internetMessageId") or ""),
                    "in_reply_to": headers.get("in-reply-to", ""), "references": headers.get("references", ""),
                    "sender_address": sender_address, "to_addresses": ";".join(to), "cc_addresses": ";".join(cc),
                    "date_original": str(message.get(date_field) or ""),
                    "time_utc": when.astimezone(UTC).isoformat(), "received_time": str(message.get("receivedDateTime") or ""),
                    "sent_time": str(message.get("sentDateTime") or ""), "modified_time": str(message.get("lastModifiedDateTime") or "")}
                rows.append(row)
                if available:
                    full.append(dict(row, body=body))
            archive_records(root, "mail", full)
            merge_csv(output, rows, FIELDS)
            return len(rows), issues

        run.run(handler, deadline)
        state = run.status()
        enumeration_complete = state == "complete"
        if not want_body:
            run.reasons.append("metadata_only: mailBody/storeMailSubject/contextChars disables body collection")
        if run.reasons and state == "complete":
            state = "partial"
        units = list(run.state["units"].values())
        committed = {record_key(row) for row in read_csv(output) if row.get("account") == account
                     and row.get("source_kind") == "outlook_graph" and str(d0) <= row.get("time", "")[:10] <= str(d1)}
        result = status(state, run.issues(), rows=len(committed), mail_rows=len(committed), observed_records=run.observed,
                        completed_units=sum(bool(u.get("done")) for u in units), total_units=len(units),
                        pages=sum(u.get("pages", 0) for u in units),
                        checkpoint_scope="account and requested period; archived body and CSV precede cursor",
                        denied_units=sum(u.get("http_status") == 403 for u in units),
                        enumeration_complete=enumeration_complete, body_requested=want_body,
                        full_requested_scope_complete=state == "complete")
    except (GraphError, OSError, ValueError, TypeError) as error:
        reason = error.reason if isinstance(error, GraphError) else "collector_failed:" + type(error).__name__
        code = getattr(error, "status", 0)
        result = status("blocked" if code in {401, 403} else "partial" if isinstance(error, GraphBudget) else "failed",
                        [reason], auth_state="forbidden" if code == 403 else "expired" if code == 401 else "unknown")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="d0", default=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
    parser.add_argument("--to", dest="d1", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--time-budget", type=float, default=240)
    parser.add_argument("--force", action="store_true", help="Refresh even a partial checkpoint; keep all existing CSV records")
    args = parser.parse_args(argv)
    config = load_config()
    if args.login_only:
        token, error = GraphAuth(ROOT, config).acquire(True)
        print("[outlook-graph] " + ("login_complete" if token else str(error)), flush=True)
        return 0 if token else 1
    result = collect(ROOT, config, args.d0, args.d1, interactive=False, budget=args.time_budget, force=args.force)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["status"] in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
