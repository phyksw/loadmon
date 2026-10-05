# -*- coding: utf-8 -*-
r"""방화벽 차단 진단(TAB §3.14) — 서버는 클라이언트 실패를 볼 수 없으므로 OS 사실로 **의심**만 표시한다.

    d = firewall_diag(sys.executable)          # {network_category, profile_on, block_inbound, app_rules, level, suspect, message_ko, rc}

  · 모두 비관리자로 읽히는 것만: ``Get-NetConnectionProfile`` 의 망 범주, ``netsh advfirewall show currentprofile`` 의
    상태·정책, ``Get-NetFirewallApplicationFilter -Program <이 서버 실행 파일> | Get-NetFirewallRule`` 의 규칙.
    포트 필터(``Get-NetFirewallPortFilter``)는 비관리자에게 'Access is denied' 라 조회하지 않는다.
  · 규칙을 바꾸지 않는다(관리자 권한·정책 우회 금지). 결과는 '의심'이며 문구는 IT 에 요청할 내용을 알려 준다.
  · 반환 사전·API·로그에는 **경로를 싣지 않는다**(실행 파일은 이름만). 경로는 콘솔 안내에만.
외부 명령은 ``run`` 주입점(시험은 출력 모사).
"""
from __future__ import annotations

import json
import os
import re

PS_TIMEOUT = 30


def _default_run(argv, timeout):
    from lm27.util.proc import run_child
    try:
        r = run_child(argv, timeout_s=timeout)
    except OSError:
        return None
    if r.timed_out:
        return None
    return r.rc, r.stdout


def _ps_exe() -> str:
    from lm27.util.proc import _system_exe
    return os.path.join(os.path.dirname(_system_exe("cmd.exe")), "WindowsPowerShell", "v1.0", "powershell.exe")


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _ps_script(exe_path: str) -> str:
    """한 번의 PowerShell 호출 — 망 범주 + 이 실행 파일의 방화벽 규칙(JSON 한 줄)."""
    return ("$ErrorActionPreference='SilentlyContinue'; "
            "$c=@(Get-NetConnectionProfile | ForEach-Object { \"$($_.NetworkCategory)\" }); "
            f"$r=@(Get-NetFirewallApplicationFilter -Program {_ps_quote(exe_path)} | Get-NetFirewallRule | "
            "ForEach-Object { [PSCustomObject]@{ action=\"$($_.Action)\"; direction=\"$($_.Direction)\"; "
            "enabled=\"$($_.Enabled)\"; profile=\"$($_.Profile)\" } }); "
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
            "[PSCustomObject]@{ category=$c; rules=$r } | ConvertTo-Json -Compress -Depth 4")


def parse_profile(txt: str) -> tuple[bool | None, bool | None]:
    """``netsh advfirewall show currentprofile`` → (켜짐?, 인바운드 기본 차단?) — 한국어·영어 출력 모두."""
    on = None
    for ln in txt.splitlines():
        low = ln.strip().lower()
        if low.startswith(("state", "상태")):
            if re.search(r"\b(off)\b|끄기|사용 안 함", low):
                on = False
            elif re.search(r"\b(on)\b|켜기|사용", low):
                on = True
    block = None
    m = re.search(r"(?i)\b(BlockInboundAlways|BlockInbound|AllowInbound)\b", txt)
    if m:
        block = m.group(1).lower().startswith("block")
    return on, block


def _rules(obj) -> list[dict]:
    rs = obj.get("rules") if isinstance(obj, dict) else None
    rs = [rs] if isinstance(rs, dict) else rs if isinstance(rs, list) else []
    out = []
    for r in rs:
        if not isinstance(r, dict):
            continue
        out.append({k: str(r.get(k) or "")[:40] for k in ("action", "direction", "enabled", "profile")})
    return out


def firewall_diag(exe_path: str, *, run=None, port: int | None = None, quiet_min: int | None = None) -> dict:
    """의심 판정 → 사전(경로 없음). ``level`` = ``strong``(이 실행 파일 인바운드 Block 규칙) · ``weak``(공용 망 +
    인바운드 기본 차단) · ``none``. ``rc`` 0 = 의심 없음 · 2 = 사람 조치 필요(IT 요청) · 3 = 조회 실패."""
    run = run or _default_run
    from lm27.util.proc import _system_exe
    exe_name = os.path.basename(str(exe_path or "")) or "python.exe"
    r1 = run([_ps_exe(), "-NoProfile", "-NonInteractive", "-Command", _ps_script(exe_path)], PS_TIMEOUT)
    r2 = run([_system_exe("netsh.exe"), "advfirewall", "show", "currentprofile"], PS_TIMEOUT)
    obj = None
    if r1 is not None and r1[0] == 0:
        try:
            obj = json.loads(r1[1].decode("utf-8", "replace").strip() or "{}")
        except ValueError:
            obj = None
    cats = obj.get("category") if isinstance(obj, dict) else None
    cats = [cats] if isinstance(cats, str) else [str(x) for x in cats or []]
    on, block = parse_profile(r2[1].decode("cp949", "replace")) if r2 is not None and r2[0] == 0 else (None, None)
    rules = _rules(obj) if obj is not None else []
    blocked_rules = [r for r in rules if r["action"].lower() == "block" and r["direction"].lower() == "inbound"
                     and r["enabled"].lower() in ("true", "1", "")]
    public = any(c.lower() == "public" for c in cats)
    if blocked_rules:
        level = "strong"
    elif public and on is not False and block:
        level = "weak"
    else:
        level = "none"
    failed = obj is None and r2 is None
    port_s = str(port) if port else "팀 서버 포트"
    head = (f"다른 PC 에서 들어온 요청이 {quiet_min}분 동안 0건입니다. " if quiet_min else "")
    if level == "strong":
        prof = ", ".join(sorted({r["profile"] for r in blocked_rules if r["profile"]})) or "알 수 없음"
        msg = (f"{head}이 PC 의 방화벽에 이 프로그램({exe_name})을 막는 인바운드 규칙({prof})이 있습니다. 사내 IT 에 "
               f"'TCP {port_s} 인바운드 허용' 또는 이 프로그램 허용을 요청하세요. 그동안 팀원은 공유폴더로 보낼 수 있습니다.")
    elif level == "weak":
        msg = (f"{head}현재 망이 공용(Public)이고 방화벽이 들어오는 연결을 기본으로 막습니다. 허용 규칙이 없으면 다른 PC 가 "
               f"닿지 않습니다 — 사내 IT 에 'TCP {port_s} 인바운드 허용'을 요청하세요. 그동안 팀원은 공유폴더로 보낼 수 있습니다.")
    elif failed:
        msg = "방화벽 상태를 읽지 못했습니다(조회 차단) — 다른 PC 에서 접속되지 않으면 사내 IT 에 문의하세요."
    else:
        msg = (f"{head}방화벽이 이 프로그램을 막는 규칙은 보이지 않습니다. 다른 망(재택·클라우드PC)이거나 주소·포트 설정을 "
               "확인하세요." if head else "방화벽이 이 프로그램을 막는 규칙은 보이지 않습니다.")
    return {"network_category": cats, "profile_on": on, "block_inbound": block, "app_rules": rules,
            "exe_name": exe_name, "level": level, "suspect": level != "none", "message_ko": msg,
            "rc": 3 if failed else (2 if level != "none" else 0)}


def hint_due(uptime_sec: float, external_requests: int, cfg, *, done: bool = False) -> bool:
    """가동 후 ``teamServer.firewallHintAfterMin`` 분 동안 다른 PC 요청이 0건이면 진단 1회(TAB §3.14)."""
    return not done and external_requests == 0 and uptime_sec >= cfg["teamServer.firewallHintAfterMin"] * 60
