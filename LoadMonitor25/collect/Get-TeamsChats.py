# -*- coding: utf-8 -*-
"""Read Graph chats and optional joined-team channels/replies using app-owned OAuth.

Configure graph.clientId/tenantId/scopes; explicitly run --login-only once.
Automated callers use --non-interactive. Chat.Read/User.Read cover chats;
graph.includeChannels requires Team.ReadBasic.All, Channel.ReadBasic.All and
ChannelMessage.Read.All. Admin policy may block consent. All nextLink pages are
followed without default row/chat caps. Durable account/period checkpoints advance
only after full-body archive and CSV merge. Joined teams exclude external shared
channel host teams; inaccessible/purged messages are not covered.
"""
import argparse
from datetime import UTC, datetime, timedelta
import json
import os
import sys
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
from collection_state import merge_csv, read_csv, record_key, write_status  # noqa: E402
from communication_archive import archive_records  # noqa: E402
from graph_client import (GraphAuth, GraphClient, GraphError, PageRun, local_bounds,  # noqa: E402
                          parse_time, plain_body, query, request_json)

LOCAL_TZ = None
CFG_PATH = os.path.join(ROOT, "config", "config.json")
TOKEN_PATH = os.path.join(ROOT, "data", "graph_token.json")
OUT_DIR = os.path.join(ROOT, "data", "m365")
GRAPH = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = ["Chat.Read", "User.Read", "offline_access"]
FIELDS = ["time", "from", "summary", "replied_time", "chat", "kind", "context_excerpt",
          "context_truncated", "source_id", "source_kind", "source_url", "conversation_id", "time_precision",
          "account", "message_id", "reply_to_id", "message_type", "created_time", "modified_time", "deleted_time",
          "team_id", "channel_id", "sender_id", "context_available"]
SCOPE = "Graph /me/chats accessible messages by creation date; channels are a separate scope"
CHANNEL_SCOPE = "joined teams and visible channels, root/reply pages by creation date; external shared-channel host teams and purged/inaccessible messages excluded"
ORDER_HINTS = ("요청", "검토", "부탁", "송부", "확인", "회신", "공유", "전달", "리뷰",
               "please", "review", "asap", "필요", "일정", "언제", "가능")


def load_cfg():
    try:
        with open(CFG_PATH, encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def graph_cfg():
    graph = load_cfg().get("graph") or {}
    return (str(graph.get("clientId") or "").strip(), str(graph.get("tenantId") or "organizations").strip(),
            graph.get("scopes") or DEFAULT_SCOPES)


def post_form(url, data):
    return GraphAuth.post(url, data)


def get_json(url, token, timeout=30):
    return request_json(url, token, timeout)


def save_token(token):
    return GraphAuth(ROOT, load_cfg()).save(token)


def load_token():
    return GraphAuth(ROOT, load_cfg()).load()


def acquire_token(interactive=True):
    return GraphAuth(ROOT, load_cfg()).acquire(interactive)


def strip_html(value):
    return plain_body({"content": value, "contentType": "html"})


def parse_graph_time(raw):
    return parse_time(raw, LOCAL_TZ)


def local_day(value):
    return local_bounds(value, value, LOCAL_TZ)[0]


def collect(d0, d1, max_chats=None, max_msgs=None, interactive=True, time_budget=240.0,
            include_channels=None, force=False):
    since, until = local_bounds(d0, d1, LOCAL_TZ)
    deadline = time.monotonic() + max(0, time_budget)
    out = os.path.join(OUT_DIR, "teams_chats.csv")
    cfg = load_cfg()
    context_chars = max(0, min(20000, int((cfg.get("collection") or {}).get("contextChars", 4000))))
    channels = bool((cfg.get("graph") or {}).get("includeChannels", False)) if include_channels is None else bool(include_channels)
    scope = SCOPE + ("; " + CHANNEL_SCOPE if channels else "; channels not requested")

    def status(state="partial", reasons=(), **extra):
        return write_status(ROOT, "teams_graph", d0, d1, status=state, scope=scope, reasons=reasons, **extra)

    status(reasons=["collection_in_progress"], chats_status="partial", channels_status="partial" if channels else "skipped",
           full_requested_scope_complete=False)
    try:
        token, error = acquire_token(interactive)
        if not token:
            status("blocked", [error], auth_state="unconfigured" if str(error).startswith("unconfigured") else "authentication_required",
                   chats_status="blocked", channels_status="blocked" if channels else "skipped", full_requested_scope_complete=False)
            print("[graph] " + str(error), flush=True)
            return None
        client = GraphClient(token, getter=get_json,
                             refresh=lambda: GraphAuth(ROOT, cfg).acquire(False, force_refresh=True))
        me = client.get(GRAPH + "/me", deadline)
        if not isinstance(me, dict) or not me.get("id"):
            raise GraphError("identity_missing")
        account = str((cfg.get("graph") or {}).get("tenantId") or "organizations") + ":" + str(me["id"])
        run = PageRun(ROOT, "teams_graph", account, d0, d1,
                      {"channels": channels, "context": context_chars, "version": 2}, client, force)
        run.add("list:chats", "chat_list", query("/me/chats", **{"$top": 50, "$expand": "members"}))
        if channels:
            run.add("list:teams", "team_list", query("/me/joinedTeams"))
        since_z = (since - timedelta(seconds=1)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        def handler(unit, items):
            rows, full, issues = [], [], []
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    issues.append("item_id_missing")
                    continue
                identity = str(item["id"])
                escaped = urllib.parse.quote(identity, safe="")
                if unit["kind"] == "chat_list":
                    topic = str(item.get("topic") or ", ".join(str(member.get("displayName") or "")
                                for member in (item.get("members") or [])[:3]))[:160]
                    base = query(f"/chats/{escaped}/messages", **{"$top": 50})
                    url = base + "&$orderby=lastModifiedDateTime%20desc&$filter=lastModifiedDateTime%20gt%20" + since_z
                    run.add("chat:" + identity, "chat_messages", url, fallback=base, chat=topic, conversation_id=identity)
                    continue
                if unit["kind"] == "team_list":
                    run.add("team:" + identity, "channel_list", query(f"/teams/{escaped}/channels",
                            **{"$select": "id,displayName,membershipType"}), team_id=identity,
                            team_name=str(item.get("displayName") or ""))
                    continue
                if unit["kind"] == "channel_list":
                    team = unit["team_id"]
                    team_key = urllib.parse.quote(team, safe="")
                    channel_base = f"/teams/{team_key}/channels/{escaped}/messages"
                    run.add("channel:" + team + "/" + identity, "channel_messages", query(channel_base, **{"$top": 50}),
                            team_id=team, channel_id=identity, base_path=channel_base,
                            conversation_id="channel:" + team + "/" + identity,
                            chat=(unit.get("team_name", "") + " / " + str(item.get("displayName") or ""))[:200])
                    continue
                if unit["kind"] == "channel_messages":
                    # Even an old root can have replies inside the requested period.
                    run.add("replies:" + unit["team_id"] + "/" + unit["channel_id"] + "/" + identity,
                            "replies", query(unit["base_path"] + "/" + escaped + "/replies", **{"$top": 50}),
                            team_id=unit["team_id"], channel_id=unit["channel_id"],
                            conversation_id=unit["conversation_id"], chat=unit["chat"], root_id=identity)
                stamp = parse_graph_time(item.get("createdDateTime"))
                if stamp is None:
                    issues.append("message_time_unreadable")
                    continue
                if not since <= stamp < until:
                    continue
                available = isinstance(item.get("body"), dict) and isinstance(item["body"].get("content"), str)
                body = plain_body(item.get("body")) if available else ""
                if not available and not item.get("deletedDateTime"):
                    issues.append("message_body_unavailable")
                user = (item.get("from") or {}).get("user") or {}
                mine = user.get("id") == me["id"]
                kind = "sent" if mine else "order" if any(word in body.casefold() for word in ORDER_HINTS) else "msg"
                conversation = unit["conversation_id"]
                source_id = ("graph:" + conversation + "/" + identity if unit["kind"] == "chat_messages"
                             else "graph-channel:" + unit["team_id"] + "/" + unit["channel_id"] + "/"
                             + (unit.get("root_id", "") + "/" if unit.get("root_id") else "") + identity)
                row = {"time": stamp.strftime("%Y-%m-%d %H:%M"), "from": str(user.get("displayName") or ""),
                       "summary": body[:200], "replied_time": "", "chat": unit.get("chat", ""), "kind": kind,
                       "context_excerpt": body[:context_chars], "context_truncated": str(len(body) > context_chars).lower(),
                       "context_available": str(available).lower(),
                       "source_id": source_id, "source_kind": "teams_graph", "source_url": str(item.get("webUrl") or ""),
                       "conversation_id": conversation, "time_precision": "minute", "account": account,
                       "message_id": identity, "reply_to_id": str(item.get("replyToId") or unit.get("root_id") or ""),
                       "message_type": str(item.get("messageType") or "message"), "sender_id": str(user.get("id") or ""),
                       "created_time": str(item.get("createdDateTime") or ""), "modified_time": str(item.get("lastModifiedDateTime") or ""),
                       "deleted_time": str(item.get("deletedDateTime") or ""), "team_id": unit.get("team_id", ""),
                       "channel_id": unit.get("channel_id", "")}
                rows.append(row)
                if available:
                    full.append(dict(row, body=body))
            archive_records(ROOT, "teams", full)
            merge_csv(out, rows, FIELDS, kind="teams")
            return len(rows), issues

        run.run(handler, deadline, {"chat_list": max_chats, "chat_messages": max_msgs})
        chats_status = run.status({"chat_list", "chat_messages"})
        channel_status = run.status({"team_list", "channel_list", "channel_messages", "replies"}) if channels else "skipped"
        state = run.status()
        if run.reasons and state == "complete":
            state = "partial"
        units = list(run.state["units"].values())
        committed = {record_key(row, "teams") for row in read_csv(out) if row.get("account") == account
                     and row.get("source_kind") == "teams_graph" and str(d0) <= row.get("time", "")[:10] <= str(d1)
                     and (channels or not row.get("channel_id"))}
        status(state, run.issues(), rows=len(committed), observed_records=run.observed, chats_status=chats_status, channels_status=channel_status,
               full_requested_scope_complete=state == "complete" and channels,
               completed_units=sum(bool(unit.get("done")) for unit in units), total_units=len(units),
               pages=sum(unit.get("pages", 0) for unit in units), denied_units=sum(unit.get("http_status") == 403 for unit in units),
               completed_chat_ids=[u["conversation_id"] for u in units if u["kind"] == "chat_messages" and u.get("done")],
               channel_scope=CHANNEL_SCOPE if channels else "not_requested")
        print(f"[graph] {run.observed} observations · {state} · " + ", ".join(run.issues()), flush=True)
        return out if state == "complete" or run.observed else None
    except (GraphError, OSError, ValueError, TypeError) as error:
        reason = error.reason if isinstance(error, GraphError) else "collector_failed:" + type(error).__name__
        code = getattr(error, "status", 0)
        status("blocked" if code in {401, 403} else "failed", [reason], chats_status="failed",
               channels_status="failed" if channels else "skipped", full_requested_scope_complete=False)
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="d0", default=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"))
    parser.add_argument("--to", dest="d1", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--max-chats", type=int, default=0, help="Optional per-run cap; zero means no cap")
    parser.add_argument("--max-msgs", type=int, default=0, help="Optional per-run cap; zero means no cap")
    parser.add_argument("--time-budget", type=float, default=240)
    parser.add_argument("--include-channels", action="store_true", default=None)
    parser.add_argument("--force", action="store_true", help="Restart checkpoint, preserving CSV and archive")
    args = parser.parse_args()
    if args.status:
        client, tenant, scopes = graph_cfg()
        print(json.dumps({"configured": bool(client), "tenant": tenant, "scopes": scopes,
                          "token_cache_exists": os.path.isfile(TOKEN_PATH)}, ensure_ascii=True), flush=True)
        return 0
    if args.login_only:
        token, error = acquire_token(True)
        print("[graph] " + ("login_complete" if token else str(error)), flush=True)
        return 0 if token else 1
    return 0 if collect(args.d0, args.d1, max_chats=args.max_chats or None, max_msgs=args.max_msgs or None,
                        interactive=not args.non_interactive, time_budget=args.time_budget,
                        include_channels=args.include_channels, force=args.force) else 1


if __name__ == "__main__":
    raise SystemExit(main())
