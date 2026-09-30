"""App-owned delegated Graph OAuth, trusted HTTP, and durable page transactions.

No browser/application token discovery. Checkpoints advance only after the caller
has archived and merged the complete processed page. They certify enumerated API
scopes, never inaccessible, purged, archived or organization-wide data.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from collection_state import _atomic_text, read_csv, record_key

GRAPH = "https://graph.microsoft.com/v1.0"
BASE_SCOPES = ["User.Read", "offline_access"]
MAIL_SCOPES = ["Mail.Read"]
CHAT_SCOPES = ["Chat.Read"]
CHANNEL_SCOPES = ["Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"]


class GraphError(Exception):
    def __init__(self, reason, status=0):
        super().__init__(reason)
        self.reason, self.status = reason, status


class GraphBudget(GraphError):
    def __init__(self):
        super().__init__("time_budget")


def trusted_url(url):
    """Never send a bearer token to a nextLink-controlled host or redirect."""
    if not isinstance(url, str) or any(ord(c) < 32 for c in url) or "\\" in url:
        raise GraphError("untrusted_next_link")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc.lower() != "graph.microsoft.com"
            or not parsed.path.startswith("/v1.0/") or parsed.fragment):
        raise GraphError("untrusted_next_link")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GraphError("redirect_refused", code)


def query(path, **params):
    return GRAPH + path + ("?" + urllib.parse.urlencode(params, safe="$,:()") if params else "")


def request_json(url, token, timeout=30, headers=None):
    request = urllib.request.Request(trusted_url(url), headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", **(headers or {})})
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise GraphError("response_size_limit")
        return json.loads(data.decode("utf-8"))


class GraphClient:
    def __init__(self, token, getter=None, headers=None, clock=None, sleep=None, refresh=None):
        self.token, self.getter, self.headers = token, getter or request_json, headers or {}
        self.clock, self.sleep = clock or time.monotonic, sleep or time.sleep
        self.refresh = refresh

    def get(self, url, deadline):
        trusted_url(url)
        attempts, refreshed = 0, False
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise GraphBudget()
            try:
                kwargs = {"timeout": max(0.1, min(30, remaining))}
                if self.headers:
                    kwargs["headers"] = self.headers
                return self.getter(url, self.token, **kwargs)
            except urllib.error.HTTPError as error:
                if error.code == 401 and self.refresh and not refreshed:
                    refreshed = True
                    new_token, _ = self.refresh()
                    if new_token:
                        self.token = new_token
                        continue
                if error.code not in {429, 500, 502, 503, 504}:
                    raise GraphError(f"http_{error.code}", error.code) from None
                attempts += 1
                if attempts > 6:
                    raise GraphError("retry_exhausted", error.code) from None
                retry = (error.headers or {}).get("Retry-After", "")
                try:
                    delay = float(retry)
                except (TypeError, ValueError):
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds()
                    except (TypeError, ValueError, OverflowError):
                        delay = min(60, 2 ** attempts)
                delay = max(0.1, delay)
                if delay >= deadline - self.clock():
                    raise GraphBudget() from None
                # Long Retry-After is honored, in small waits that remain interruptible.
                while delay > 0:
                    part = min(30, delay)
                    self.sleep(part)
                    delay -= part
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise GraphError("network_unavailable:" + type(error).__name__) from None
            except (ValueError, UnicodeError):
                raise GraphError("invalid_json") from None


def _scope_names(scopes):
    return {str(item).rsplit("/", 1)[-1].casefold() for item in scopes if item}


class GraphAuth:
    """Device-code OAuth using this app's cache, bound to app/tenant/scopes."""
    def __init__(self, root, config, poster=None, clock=None, sleep=None, emit=print):
        self.root, self.config = Path(root), config
        self.graph = config.get("graph") or {}
        self.path = self.root / "data" / "graph_token.json"
        self.poster = poster or self.post
        self.clock, self.sleep, self.emit = clock or time.time, sleep or time.sleep, emit

    @staticmethod
    def post(url, values):
        req = urllib.request.Request(url, data=urllib.parse.urlencode(values).encode(), method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8")), None
        except urllib.error.HTTPError as error:
            try:
                code = str(json.loads(error.read().decode("utf-8")).get("error") or "")
            except (ValueError, UnicodeError):
                code = ""
            return None, {"error": code if re.fullmatch(r"[A-Za-z0-9_]+", code) else f"http_{error.code}"}
        except (OSError, ValueError, GraphError):
            return None, {"error": "oauth_connection_failed"}

    def load(self):
        try:
            payload = json.loads(self.path.read_text("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, token, old=None):
        token = dict(token)
        if not token.get("refresh_token") and (old or {}).get("refresh_token"):
            token["refresh_token"] = old["refresh_token"]
        if not token.get("scope") and (old or {}).get("scope"):
            token["scope"] = old["scope"]
        token.update(_client_id=str(self.graph.get("clientId", "")).strip(),
                     _tenant_id=str(self.graph.get("tenantId") or "organizations").strip(),
                     _requested_scopes=list(self.graph.get("scopes") or BASE_SCOPES + CHAT_SCOPES),
                     _expires_at=self.clock() + float(token.get("expires_in", 3600)) - 120)
        _atomic_text(self.path, json.dumps(token))
        if os.name == "nt":
            try:
                subprocess.run(["icacls", str(self.path), "/inheritance:r", "/grant:r",
                                f"{os.environ.get('USERNAME', '')}:F"], capture_output=True,
                               timeout=15, creationflags=0x08000000)
            except (OSError, subprocess.SubprocessError):
                pass
        return token

    def acquire(self, interactive=False, force_refresh=False, force_login=False):
        client = str(self.graph.get("clientId") or "").strip()
        tenant = str(self.graph.get("tenantId") or "organizations").strip()
        scopes = list(self.graph.get("scopes") or BASE_SCOPES + CHAT_SCOPES)
        if not client:
            return None, "unconfigured: graph.clientId"
        try:
            uuid.UUID(client)
        except ValueError:
            return None, "invalid_client_id"
        if not re.fullmatch(r"(?:organizations|common|consumers|[0-9a-fA-F-]{36}|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", tenant):
            return None, "invalid_tenant_id"
        token = self.load()
        bound = token.get("_client_id") == client and token.get("_tenant_id") == tenant
        requested = _scope_names(scopes) - {"offline_access", "openid", "profile"}
        granted = _scope_names(str(token.get("scope") or "").split())
        if not force_login and not force_refresh and bound and requested <= granted and token.get("access_token") and token.get("_expires_at", 0) > self.clock():
            return token["access_token"], None
        base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
        if not force_login and bound and token.get("refresh_token"):
            got, _ = self.poster(base + "/token", {"client_id": client, "grant_type": "refresh_token",
                                    "refresh_token": token["refresh_token"], "scope": " ".join(scopes)})
            if got and got.get("access_token"):
                refreshed = self.save(got, token)
                if requested <= _scope_names(str(refreshed.get("scope") or "").split()):
                    return got["access_token"], None
        if not interactive:
            return None, "authentication_or_consent_required: run Get-TeamsChats.py --login-only"
        device, error = self.poster(base + "/devicecode", {"client_id": client, "scope": " ".join(scopes)})
        if not device or not device.get("device_code"):
            return None, "device_code_failed:" + str((error or {}).get("error") or "unknown")
        # Only the app's device challenge is shown; tokens and raw OAuth errors never are.
        self.emit("[graph] https://microsoft.com/devicelogin 에서 코드 " + str(device.get("user_code") or "") + " 입력", flush=True)
        expires = self.clock() + int(device.get("expires_in", 900))
        interval = max(1, int(device.get("interval", 5)))
        while self.clock() < expires:
            wait = min(interval, expires - self.clock())
            while wait > 0:
                part = min(wait, 30)
                self.sleep(part)
                wait -= part
            if self.clock() >= expires:
                break
            got, error = self.poster(base + "/token", {"client_id": client,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": device["device_code"]})
            if got and got.get("access_token"):
                self.save(got)
                return got["access_token"], None
            code = (error or {}).get("error", "unknown")
            if code == "slow_down":
                interval += 5
            elif code != "authorization_pending":
                return None, "authentication_blocked:" + str(code)
        return None, "authentication_timeout"


class _Text(HTMLParser):
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


def plain_body(body):
    body = body or {}
    content = str(body.get("content") or "")
    if str(body.get("contentType") or "html").lower() != "text":
        parser = _Text()
        parser.feed(content)
        content = "".join(parser.parts)
    return re.sub(r"[ \t]+", " ", content).strip()


def parse_time(raw, tz=None):
    try:
        value = re.sub(r"\.(\d{6})\d+", r".\1", str(raw or "")).replace("Z", "+00:00")
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.astimezone(tz)
    except (TypeError, ValueError, OverflowError):
        return None


def local_bounds(d0, d1, tz=None):
    start = datetime.strptime(str(d0), "%Y-%m-%d")
    end = datetime.strptime(str(d1), "%Y-%m-%d") + timedelta(days=1)
    if start >= end:
        raise ValueError("invalid_date_range")
    return (start.replace(tzinfo=tz), end.replace(tzinfo=tz)) if tz else (start.astimezone(), end.astimezone())


class PageRun:
    """Round-robin durable work queue. Handler writes archive/CSV before commit."""
    def __init__(self, root, source, account, d0, d1, signature, client, force=False,
                 storage_path=None, storage_kind="mail"):
        self.client = client
        self.storage_path = Path(storage_path) if storage_path else None
        self.storage_kind, self.source, self.account = storage_kind, source, account
        self.d0, self.d1 = str(d0), str(d1)
        self.reasons, self.observed, self.attempted = [], 0, 0
        self.recovery_reason = ""
        identity = [source, account, str(d0), str(d1), signature]
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.path = Path(root) / "data" / "graph_checkpoints" / (source + "_" + digest + ".json")
        self.state = {"schema": 1, "identity": identity, "units": {}, "sequence": 0}
        if not force:
            try:
                prior = json.loads(self.path.read_text("utf-8"))
                if prior.get("identity") == identity and isinstance(prior.get("units"), dict):
                    self.state = prior
            except (OSError, ValueError, TypeError):
                pass
        if self.state["units"] and self.storage_path:
            # A cursor proves traversal only while its committed observations
            # still exist. PC transfer moves CSVs separately from this checkpoint;
            # another route may also add rows without invalidating our progress.
            saved = self.state.get("storage_inventory")
            present = self.storage_inventory()
            if saved is None or present is None or not set(saved) <= present:
                self.state = {"schema": 1, "identity": identity, "units": {}, "sequence": 0}
                self.recovery_reason = "saved_observations_missing_restarted"
        # A fully traversed previous snapshot is refreshed; partial runs resume.
        if self.state["units"] and all(u.get("done") for u in self.state["units"].values()):
            self.state = {"schema": 1, "identity": identity, "units": {}, "sequence": 0}
        elif self.state["units"]:
            # A permanently denied channel must not freeze previously complete
            # chats/mail ranges forever. Resume pending cursors first, then refresh
            # completed units at lower priority during this invocation.
            priority = self.state["sequence"] + 1
            for unit in self.state["units"].values():
                if unit.get("done"):
                    unit.update(next=unit["initial"], done=False, offset=0, last=priority,
                                pages=0, rows=0, issues=[], visited=[], page_signature="")
                    priority += 1
            self.state["sequence"] = priority

    def storage_inventory(self):
        if not self.storage_path or not self.storage_path.is_file():
            return None
        rows = read_csv(self.storage_path)  # Malformed CSV must remain untouched.
        result = set()
        for row in rows:
            if (row.get("source_kind") != self.source or row.get("account") != self.account
                    or not self.d0 <= row.get("time", "")[:10] <= self.d1):
                continue
            observation = [record_key(row, self.storage_kind), row.get("context_excerpt", ""),
                           row.get("summary", ""), row.get("subject", "")]
            result.add(hashlib.sha256(json.dumps(observation, ensure_ascii=False).encode()).hexdigest())
        return result

    def add(self, key, kind, url, **meta):
        if key not in self.state["units"]:
            self.state["units"][key] = {"key": key, "kind": kind, "initial": url, "next": url,
                "done": False, "offset": 0, "last": 0, "pages": 0, "rows": 0, "issues": [], **meta}

    def save(self):
        if self.storage_path:
            inventory = self.storage_inventory()
            # An initial HTTP failure can precede creation of an empty CSV.
            if inventory is not None:
                self.state["storage_inventory"] = sorted(inventory)
        _atomic_text(self.path, json.dumps(self.state, ensure_ascii=False))

    def run(self, handler, deadline, limits=None):
        limits, used, blocked, restarted = limits or {}, {}, set(), set()
        while True:
            pending = [u for u in self.state["units"].values() if not u.get("done") and u["key"] not in blocked]
            if not pending:
                break
            if self.client.clock() >= deadline:
                self.reasons.append("time_budget")
                break
            unit = min(pending, key=lambda u: (u.get("last", 0), u["key"]))
            kind, url = unit["kind"], unit["next"]
            cap = limits.get(kind)
            if cap and used.get(kind, 0) >= cap:
                self.reasons.append("chat_limit" if kind == "chat_list" else "message_limit")
                blocked.add(unit["key"])
                continue
            self.state["sequence"] += 1
            unit["last"] = self.state["sequence"]
            self.attempted += 1
            try:
                page = self.client.get(url, deadline)
                if not isinstance(page, dict) or not isinstance(page.get("value"), list):
                    raise GraphError("invalid")
            except GraphBudget:
                self.reasons.append("time_budget")
                self.save()
                break
            except GraphError as error:
                if error.status == 400 and unit.get("fallback") and url == unit["initial"]:
                    unit["next"] = unit["initial"] = unit.pop("fallback")
                    unit["offset"] = 0
                    self.save()
                    continue
                if error.status in {400, 410} and url != unit["initial"] and unit["key"] not in restarted:
                    # Expired continuation token: restart only this unit, retaining
                    # all stored rows. Limit restart attempts within a run.
                    restarted.add(unit["key"])
                    unit.update(next=unit["initial"], offset=0, visited=[], page_signature="")
                    self.reasons.append("cursor_expired_restarted")
                    self.save()
                    continue
                prefix = "chat_list" if kind == "chat_list" else "messages" if kind in {"chat_messages", "channel_messages", "replies"} else kind
                reason = prefix + ("_invalid" if error.reason == "invalid" else "_failed:" + (str(error.status) if error.status else error.reason))
                unit["error"] = reason
                unit["http_status"] = error.status
                blocked.add(unit["key"])
                self.reasons.append(reason)
                self.save()
                continue
            items = page["value"]
            signature = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
            offset = unit.get("offset", 0) if unit.get("page_signature") == signature else 0
            stop = len(items) if not cap else min(len(items), offset + cap - used.get(kind, 0))
            selected = items[offset:stop]
            next_url = page.get("@odata.nextLink") or ""
            issues = []
            if next_url:
                try:
                    trusted_url(next_url)
                    digest = hashlib.sha256(next_url.encode()).hexdigest()
                    if next_url == url or digest in unit.get("visited", []):
                        raise GraphError("page_repeated")
                except GraphError as error:
                    issues.append(error.reason)
                    next_url = ""
            try:
                rows, extra_issues = handler(unit, selected)
            except (OSError, ValueError, TypeError) as error:
                self.reasons.append("page_save_failed:" + type(error).__name__)
                # Never save a cursor or child jobs after a failed archive/CSV write.
                break
            used[kind] = used.get(kind, 0) + len(selected)
            self.observed += rows
            unit["rows"] += rows
            unit["issues"] = sorted({*unit.get("issues", []), *issues, *extra_issues})
            unit.pop("error", None)
            unit.pop("http_status", None)
            if stop < len(items):
                unit.update(offset=stop, page_signature=signature)
                self.reasons.append("chat_limit" if kind == "chat_list" else "message_limit")
                blocked.add(unit["key"])
            else:
                unit.update(offset=0, page_signature="", next=next_url, done=not next_url, pages=unit["pages"] + 1)
                unit.setdefault("visited", []).append(hashlib.sha256(url.encode()).hexdigest())
            self.save()
        return self

    def status(self, kinds=None):
        units = [u for u in self.state["units"].values() if kinds is None or u["kind"] in kinds]
        if not units:
            return "skipped"
        if all(u.get("done") and not u.get("issues") for u in units):
            return "complete"
        return "partial" if any(u.get("pages") or u.get("rows") for u in units) else "failed"

    def issues(self):
        return sorted(set(self.reasons + [r for u in self.state["units"].values()
                                          for r in [*u.get("issues", []), u.get("error", "")] if r]))
