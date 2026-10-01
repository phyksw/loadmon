"""Capability checks and a content-free collection report for another PC.

No COM activation, mailbox reads, browser profiles, process command lines or
account identifiers. Missing evidence is never converted into zero work.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from urllib.parse import urlsplit

from collection_state import status_snapshot


def outlook_capability(registry=None):
    """Read registration/profile existence only; never instantiate Outlook."""
    if registry is None:
        try:
            import winreg as registry
        except ImportError:
            return {"oom_registered": None, "classic_profile": None}

    def exists(hive, path, children=False):
        results = []
        for view in (registry.KEY_WOW64_64KEY, registry.KEY_WOW64_32KEY):
            try:
                with registry.OpenKey(hive, path, 0, registry.KEY_READ | view) as key:
                    if children:
                        try:
                            registry.EnumKey(key, 0)
                        except OSError as error:
                            if getattr(error, "winerror", None) == 259:
                                results.append(False)
                                continue
                            raise
                    return True
            except FileNotFoundError:
                results.append(False)
            except OSError:
                results.append(None)
        return None if None in results else False

    registered = exists(registry.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID")
    profiles = [exists(registry.HKEY_CURRENT_USER, path, True) for path in (
        r"Software\Microsoft\Office\16.0\Outlook\Profiles",
        r"Software\Microsoft\Office\15.0\Outlook\Profiles",
        r"Software\Microsoft\Office\14.0\Outlook\Profiles",
        r"Software\Microsoft\Windows NT\CurrentVersion\Windows Messaging Subsystem\Profiles")]
    return {"oom_registered": registered,
            "classic_profile": True if True in profiles else None if None in profiles else False}


def client_snapshot():
    result = outlook_capability()
    result.update(running_clients=[], client_probe="unavailable", platform=os.name)
    if os.name != "nt":
        return result
    command = ("$ErrorActionPreference='Stop'; @('OUTLOOK','olk','ms-teams','Teams') | ForEach-Object { "
               "Get-Process -Name $_ -ErrorAction SilentlyContinue | ForEach-Object { "
               "[pscustomobject]@{name=$_.ProcessName;version=$_.FileVersion} } } | ConvertTo-Json -Compress")
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, timeout=4, creationflags=0x08000000)
        if proc.returncode:
            return result
        rows = json.loads(proc.stdout.decode("utf-8-sig", "replace") or "[]")
        for row in rows if isinstance(rows, list) else [rows]:
            if not isinstance(row, dict) or row.get("name", "").lower() not in {"outlook", "olk", "ms-teams", "teams"}:
                continue
            version = re.search(r"\b\d+(?:\.\d+){1,5}\b", str(row.get("version") or ""))
            result["running_clients"].append({"name": row["name"].lower(),
                                               "version": version.group() if version else "unknown"})
        result["client_probe"] = "observed_running_processes_only"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return result


CAUSES = {
    "login_required": ("로그인 필요", "수집용 Edge 창에서 회사 계정 로그인 후 같은 기간으로 재실행하세요."),
    "access_blocked": ("접근 제한", "브라우저에 표시된 조직 접근 조건·계정 권한을 확인하세요."),
    "browser_unavailable": ("브라우저 연결 실패", "Edge 실행 및 조직의 브라우저 자동화 허용 여부를 확인하세요."),
    "browser_profile_unverified": ("수집용 브라우저 확인 실패", "같은 포트를 쓰는 다른 LM 설치본이 있는지 확인하세요. 현재 설치본의 전용 프로필 연결을 확인해야 합니다."),
    "browser_port_unavailable": ("수집용 브라우저 포트 사용 불가", "수집용 포트를 확보하지 못했습니다. 실행 중인 다른 설치본과 포트 제한을 확인하세요."),
    "page_not_ready": ("화면 준비 실패", "수집용 웹 창에 메일·채팅 목록이 실제로 표시되는지 확인하세요."),
    "selector_unmatched": ("화면 구조 인식 실패", "원인표의 경로·화면 인식 건수로 해당 화면 형식을 점검해야 합니다."),
    "page_evaluation_failed": ("화면 읽기 연결 오류", "원인표의 브라우저 단계와 오류 종류를 확인해야 합니다. 빈 사서함으로 판정하지 않습니다."),
    "context_unverified": ("대화·본문 연결 확인 실패", "열린 대화가 선택한 항목과 일치하지 않아 해당 본문을 확정하지 않았습니다."),
    "chat_read_failed": ("일부 대화 화면 읽기 실패", "읽지 못한 대화가 있습니다. 다른 대화에서 저장한 자료는 유지하며 원인표의 화면·날짜 건수를 확인하세요."),
    "date_unconfirmed": ("날짜를 확인하지 못함", "날짜가 확인되지 않은 메시지는 선택 기간의 건수에 넣지 않습니다."),
    "budget_reached": ("시간 한도 도달", "저장된 중간 자료를 보존했습니다. 같은 기간으로 다시 실행하면 체크포인트를 사용합니다."),
    "search_unverified": ("검색 범위 확인 실패", "웹 검색 결과를 전체 원문 확보로 간주하지 않습니다."),
    "com_unavailable": ("클래식 Outlook 경로 사용 불가", "새 Outlook·웹은 웹 경로 또는 승인된 Graph 경로로 수집합니다."),
    "graph_unconfigured": ("Graph 연결 없음", "승인된 앱 연결이 없으므로 앱·웹에서 확인된 자료만 수집합니다."),
    "disabled": ("경로 생략", "실행 옵션·설정 또는 앞 경로의 완료 범위를 확인하세요."),
    "status_write_failed": ("수집 상태 저장 실패", "상태 파일 잠금·폴더 쓰기 권한을 확인하세요. 다른 수집 경로는 계속 실행합니다."),
    "other": ("추가 확인 필요", "해당 경로의 상태·처리 건수와 실행 중 표시된 안내를 확인하세요."),
}
SOURCES = {"outlook_com", "outlook_index", "outlook_web", "outlook_graph", "outlook_copilot",
           "teams_app", "teams_web", "teams_graph", "teams_copilot", "communication_import", "outlook_files"}
COUNTERS = {"rows", "mail_rows", "calendar_rows", "parsed_messages", "period_excluded", "date_unconfirmed",
            "undated_rows", "parsed", "undated", "period_filtered", "elements_seen", "rows_seen", "body_rows",
            "search_attempts", "search_failures", "elapsed_sec", "budget_sec", "body_requested",
            "messages_seen", "chats_seen", "completed_chats", "pending_rows", "body_read", "body_failed",
            "observed_messages", "dated_messages", "no_time", "no_body", "time_budget_sec"}
WEB_COUNTERS = {"search", "items", "parsed", "sent", "cc", "date_only", "pages", "sent_pass_new",
                "body_rows", "detail_failed", "completed_units", "search_failed", "search_unverified",
                "search_attempts", "undated", "period_filtered", "empty_results", "unsupported_pages",
                "navigation_failed", "visible_unverified", "total_units", "thread_messages", "context_filtered"}

BROWSER_ENUMS = {
    "phase": {"starting", "browser_connected", "tab_connected", "navigating", "waiting_login",
              "waiting_surface", "surface_ready", "reading", "failed"},
    "surface": {"mail", "teams", "login", "other", "unknown"},
    "last_error": {"TimeoutError", "OSError", "ConnectionError", "RuntimeError", "ValueError", "other"},
}
BROWSER_COUNTERS = {"page_checks", "page_errors", "items", "chats", "messages", "listboxes"}
BROWSER_FLAGS = {"browser_connected", "tab_connected", "login_seen", "ready_seen", "loading", "empty", "search"}


def browser_snapshot(value):
    """Only fixed enums/booleans/counts; no URL, DOM text, identities or errors."""
    value = value if isinstance(value, dict) else {}
    result = {k: v for k, v in value.items() if k in BROWSER_ENUMS and isinstance(v, str) and v in BROWSER_ENUMS[k]}
    result.update({k: v for k, v in value.items() if k in BROWSER_COUNTERS and type(v) is int and 0 <= v < 1e9})
    result.update({k: v for k, v in value.items() if k in BROWSER_FLAGS and type(v) is bool})
    return result


def observe_browser(browser, phase, href=None, page=None, error=None):
    """Track the actual browser readiness boundary without storing page content."""
    state = browser_snapshot(getattr(browser, "observation", {}))
    state["phase"] = phase
    if phase in {"browser_connected", "tab_connected"}:
        state[phase] = True
    if phase == "waiting_login":
        state["login_seen"] = True
    if phase == "surface_ready":
        state["ready_seen"] = True
        state.pop("last_error", None)
    if href is not None:
        try:
            host = urlsplit(str(href)).hostname or ""
        except ValueError:
            host = ""
        state["surface"] = (
            "mail" if host in {"outlook.office.com", "outlook.cloud.microsoft", "outlook.office365.com", "outlook.live.com"} else
            "teams" if host in {"teams.microsoft.com", "teams.cloud.microsoft", "teams.office.com", "teams.live.com"} else
            "login" if host in {"login.microsoftonline.com", "login.live.com", "login.microsoft.com"} else
            "other" if host else "unknown")
    if isinstance(page, dict):
        state["page_checks"] = state.get("page_checks", 0) + 1
        for key in ("items", "chats", "messages", "listboxes"):
            value = page.get(key)
            if isinstance(value, list):
                state[key] = len(value)
            elif type(value) is int and 0 <= value < 1e9:
                state[key] = value
        for key in ("loading", "empty", "search"):
            if type(page.get(key)) is bool:
                state[key] = page[key]
    if error is not None:
        state["page_errors"] = state.get("page_errors", 0) + 1
        kind = next((kind.__name__ for kind in (TimeoutError, ConnectionError, OSError, ValueError, RuntimeError)
                     if isinstance(error, kind)), "other")
        state["last_error"] = kind
    browser.observation = browser_snapshot(state)
    return browser.observation


def cause_code(reason):
    value = str(reason).lower()
    for code, patterns in (
        ("status_write_failed", ("status_write_failed",)),
        ("browser_profile_unverified", ("browser_profile_unverified",)),
        ("browser_port_unavailable", ("browser_port_unavailable",)),
        ("login_required", ("login", "로그인")),
        ("com_unavailable", ("com_unregistered", "classic_profile_missing")),
        ("graph_unconfigured", ("graph 앱 연결 미설정",)),
        ("access_blocked", ("access_denied", "policy", "forbidden", "403", "conditional_access")),
        ("browser_unavailable", ("edge startup", "browser_start", "debug_port", "cdp_unavailable", "driver_unavailable", "browser_failed", "driver_error")),
        ("page_evaluation_failed", ("page_evaluation_failed",)),
        ("chat_read_failed", ("chat_read_failed",)),
        ("context_unverified", ("context_room_changed", "anchor_unconfirmed", "chat_switch_unconfirmed", "chat_open_failed")),
        ("page_not_ready", ("page_timeout", "page timeout", "not_ready", "page_not", "shell_only", "page_load_error")),
        ("selector_unmatched", ("selector", "list_not_found", "no_chat_list")),
        ("date_unconfirmed", ("date_unconfirmed", "undated", "unknown_date", "date_unknown")),
        ("budget_reached", ("budget", "시간 예산", "timed_out", "timeout", "time_limit")),
        ("search_unverified", ("search", "query", "검색")),
        ("disabled", ("생략", "비활성", "--no-", "앞 경로")),
    ):
        if any(pattern in value for pattern in patterns):
            return code
    return "other"


def build_diagnostics(root, d0, d1, run):
    """Whitelist fixed labels/counters. Never serialize raw collector errors or logs."""
    routes = []
    started = run.get("started_at")
    states = {state["source"]: state for state in status_snapshot(root)}
    # A status file can remain locked while actual collection proceeds. Use the
    # current in-memory result instead of presenting that file's stale success.
    for family in (run.get("collection") or {}).values():
        if not isinstance(family, dict):
            continue
        for state in family.get("sources", []):
            if (isinstance(state, dict) and state.get("source") in SOURCES
                    and [state.get("requested_from"), state.get("requested_to")] == [d0, d1]
                    and isinstance(started, (int, float))
                    and isinstance(state.get("finished_at"), (int, float)) and state["finished_at"] >= started):
                states[state["source"]] = state
    for state in states.values():
        if state.get("source") not in SOURCES:
            continue
        same = [state.get("requested_from"), state.get("requested_to")] == [d0, d1]
        current = bool(same and isinstance(started, (int, float)) and
                       isinstance(state.get("finished_at"), (int, float)) and state["finished_at"] >= started)
        item = {"source": state["source"], "status": state.get("status", "unknown"),
                "matches_period": same, "current_run": current,
                "causes": list(dict.fromkeys(cause_code(s) for s in state.get("reasons", []) if isinstance(s, str)))}
        item["counters"] = {k: v for k, v in state.items() if k in COUNTERS and type(v) in {int, float, bool}
                            and (type(v) is bool or 0 <= v < 1e12)}
        item["browser"] = browser_snapshot(state.get("browser"))
        details = state.get("diagnostics") or {}
        if isinstance(details, dict):
            for kind in ("mail", "cal"):
                values = details.get(kind) or {}
                if isinstance(values, dict):
                    item["counters"].update({kind + "_" + k: v for k, v in values.items()
                        if k in WEB_COUNTERS and type(v) in {int, float} and 0 <= v < 1e12})
        routes.append(item)
    summaries = []
    for item in routes:
        if not item["current_run"]:
            continue
        codes = item["causes"] or (["other"] if item["status"] in {"blocked", "failed"} else [])
        for code in codes:
            if code not in {"other", "disabled", "graph_unconfigured"} or (
                    code == "other" and item["status"] in {"blocked", "failed"}):
                summaries.append(f"{item['source']}: {CAUSES[code][0]} — {CAUSES[code][1]}")
    stages = []
    for stage in run.get("stages", []):
        name = str(stage.get("name") or "")
        family = next((s for s in ("Outlook", "Teams", "메일", "PC", "파일", "최근 문서", "git") if name.startswith(s)), None)
        seconds = stage.get("sec")
        if family and type(seconds) in {int, float} and 0 <= seconds < 1e7:
            stages.append({"family": family, "ok": stage.get("ok") is True, "seconds": seconds})
    caps = run.get("client_capabilities") or {}
    capability = {k: caps[k] for k in ("oom_registered", "classic_profile")
                  if k in caps and (caps[k] is None or type(caps[k]) is bool)}
    capability["running_clients"] = [r for r in caps.get("running_clients", [])
                                      if isinstance(r, dict) and set(r) == {"name", "version"}
                                      and isinstance(r["name"], str) and r["name"] in {"outlook", "olk", "ms-teams", "teams"}
                                      and re.fullmatch(r"(?:\d+(?:\.\d+){1,5}|unknown)", str(r["version"]))]
    evidence = run.get("communication_evidence") or {}
    saved = {}
    if evidence.get("period") == [d0, d1]:
        allowed = {"raw_rows", "in_period_rows", "unique_rows", "context_rows", "unknown_date_rows", "pending_rows",
                   "context_filtered_rows", "files", "unreadable_files", "pending_unreadable_files", "dated_rows",
                   "web_body_observed_rows", "web_body_partial_rows"}
        for family in ("mail", "teams"):
            values = (evidence.get("families") or {}).get(family) or {}
            saved[family] = {k: v for k, v in values.items() if k in allowed and type(v) is int and 0 <= v < 1e12}
            if saved[family].get("raw_rows", 0) and not saved[family].get("in_period_rows", 0):
                summaries.append(f"{family}: 저장된 행은 있지만 선택 기간의 확정 신호가 없습니다. 날짜·기간·시간 보정 값을 확인하세요.")
    offset = evidence.get("mail_time_offset_hours") if evidence.get("period") == [d0, d1] else None
    date_settings = {"mail_time_offset_hours": offset} if type(offset) in {int, float} and -24 <= offset <= 24 else {}
    return {"schema": 2, "version": "v25.14", "period": [d0, d1], "created_at": time.time(),
            "client_capabilities": capability, "routes": routes, "stages": stages,
            "saved_evidence": saved, "date_settings": date_settings,
            "summary": list(dict.fromkeys(summaries)), "includes_message_content": False,
            "scope_note": "현재 실행과 이전 기록을 구분합니다. 관측 자료·웹 목록은 서버 전체 확보율이 아닙니다."}


def write_diagnostics(root, d0, d1, run):
    result = build_diagnostics(root, d0, d1, run)
    path = Path(root) / "report" / "communication_diagnostics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return result
