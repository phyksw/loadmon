"""Validate user-selected connection settings without reading credentials."""
from __future__ import annotations

import json
from pathlib import Path
import re
import uuid

from collection_state import _atomic_text


BASE_SCOPES = ["User.Read", "offline_access", "Mail.Read", "Chat.Read"]
CHANNEL_SCOPES = ["Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All"]


def connection_settings(body):
    if not isinstance(body, dict):
        raise ValueError("연결 설정 객체가 필요합니다")
    try:
        client = str(uuid.UUID(str(body.get("client_id", "")).strip()))
    except (ValueError, AttributeError):
        raise ValueError("조직에서 허용한 앱의 클라이언트 ID(GUID)를 입력하세요") from None
    tenant = str(body.get("tenant_id") or "organizations").strip()
    if not re.fullmatch(r"(?:organizations|common|consumers|[0-9a-fA-F-]{36}|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", tenant):
        raise ValueError("테넌트 ID 또는 조직 도메인을 확인하세요")
    channels = body.get("include_channels", False)
    if not isinstance(channels, bool):
        raise ValueError("Teams 채널 포함 옵션을 확인하세요")
    result = {"clientId": client, "tenantId": tenant, "includeChannels": channels,
              "scopes": BASE_SCOPES + (CHANNEL_SCOPES if channels else [])}
    if "own_addresses" in body:
        result["ownAddresses"] = import_options(body, {})["collection"]["communicationImportOwnAddresses"]
    return result


def save_connection(root, settings):
    path = Path(root) / "config" / "config.json"
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("기존 설정 파일 형식이 올바르지 않습니다")
    # Keep unrelated and advanced graph settings. Do not open any token file.
    config["graph"] = {**(config.get("graph") or {}), **settings}
    _atomic_text(path, json.dumps(config, ensure_ascii=False, indent=1) + "\n")


def import_options(body, config):
    """Per-request identity/count overrides; no changes to the user's config."""
    options = dict(config.get("collection") or {})
    if "own_addresses" in body:
        addresses = body["own_addresses"]
        if (not isinstance(addresses, list) or len(addresses) > 50 or
                any(not isinstance(a, str) or len(a) > 320 or
                    not re.fullmatch(r"[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+", a) for a in addresses)):
            raise ValueError("본인 메일 주소를 쉼표로 구분해 입력하세요")
        options["communicationImportOwnAddresses"] = addresses
    if "expected_count" in body:
        count = body["expected_count"]
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100000000:
            raise ValueError("내보낸 원본 건수는 0 이상의 정수로 입력하세요")
        options["communicationImportExpectedCount"] = count
    return {**config, "collection": options}
