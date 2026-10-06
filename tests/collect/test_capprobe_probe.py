# -*- coding: utf-8 -*-
r"""WP-17 능력 탐침 — 가짜 환경 주입 시나리오(collect\Invoke-CapabilityProbe.ps1).

근거: 계약 §6.7(탐침 묶음 — 내용 0바이트, 숫자·열거·사유만) · §6.1(사유 코드) · §3.8(capabilities 키) · §6.4(history.status) ·
§7.3(stdin 제어 줄 _in) · §11.3(주입점·stub_env_set) · X-124 · X-125 · X-134 · X-192, C §4, CM §14, CT §12, CP §1.3·§12.1.

실제 Outlook·색인·Teams·이벤트 로그·레지스트리를 읽지 않는다. 사실은 LM_PROBE_FAKE(tests\fixtures\wp17\healthy.json 위에
시나리오를 덮어쓴 합성 JSON — CR 로 계약 §11.3 등재 요청)·LM_OUTLOOK_SELFTEST·LM_INDEX_FAKE 로만 넣는다. 탐침은 %TEMP%
복제 트리(WP-05 tree.make_clone)에서 돌고, 시나리오는 병렬로 한 번에 돌린 뒤 결과를 단언한다.

워치독은 진짜 자식 PowerShell 로 시험한다: 가짜 COM·UIA 자식이 무한 대기(Start-Sleep)하면 부모가 mail.com.watchdogSec ·
mail.com.protectedReadSec · teams.uia.windowWatchdogSec · probe.budgetSec 안에 끝내야 한다.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import time
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lm27.collect import rcmap
from tests.fixtures import synth
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.synth.inject import in_line, index_fake
from tests.fixtures.tree import guard_write, make_clone

ROOT = Path(__file__).resolve().parents[2]
HEALTHY = ROOT / "tests" / "fixtures" / "wp17" / "healthy.json"
PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
CREATE_NO_WINDOW = 0x08000000
TEST_NOW = "2026-10-05T17:00:00+09:00"
NOW_UTC = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
DEL = "__del__"                      # 덮어쓰기에서 그 키를 지운다
SCHEMA = "lm27.probe/1"
GROUPS = ("P-ENV", "P-OL-INST", "P-OL-COM", "P-IDX", "P-EDGE", "P-TEAMS", "P-PC")
KEYS_BY_GROUP = {
    "P-ENV": ("env",), "P-OL-INST": ("mail.com", "cal.com"), "P-OL-COM": ("mail.com", "cal.com"),
    "P-IDX": ("mail.index", "cal.index"), "P-EDGE": ("edge_cdp_policy",), "P-TEAMS": ("teams.uia",),
    "P-PC": ("pc.sampler", "pc.events", "pc.recent", "pc.mru", "pc.git"),
}
ALL_KEYS = tuple(dict.fromkeys(k for g in GROUPS for k in KEYS_BY_GROUP[g]))
STATUSES = ("ok", "fail", "transport_fail", "unknown")
INJECT_NAMES = {"LM_OUTLOOK_SELFTEST", "LM_INDEX_FAKE", "LM_OWA_FAKE", "LM_TEAMSWEB_FAKE", "LM_COPILOT_STUB",
                "LM_NO_BROWSER", "LM_PROBE_FAKE"}
OL = "P-OL-INST,P-OL-COM"
BASE = json.loads(HEALTHY.read_bytes().decode("utf-8"))
BASE.pop("_doc", None)
# PowerShell 5.1 기동은 동시 4개를 넘기면 거의 직렬로 느려진다(실측 4개 평균 2.7초 · 16개 10초) — 시나리오마다 자식이
# 하나 더 뜨므로 4개로 묶는다(워치독 시간 단언이 기동 지연에 흔들리지 않게).
WORKERS = max(2, min(4, (os.cpu_count() or 4)))
KILL_SLACK_MS = 2500        # 워치독 시각 → 자식을 끊고 거둘 때까지의 여유(부하가 큰 개발 PC 실측 ≤ 0.5초)

# ── 출력 문자열 허용 목록(필드별) — '허용 필드 외 문자열 0건'(계획 WP-17 완료 기준) ──────────────────────────
ENUMS = {
    SCHEMA, "done", "skipped", "budget", "error", "stub_env_set", "fake_unreadable", *STATUSES,
    "FullLanguage", "ConstrainedLanguage", "RestrictedLanguage", "NoLanguage",
    "Restricted", "AllSigned", "RemoteSigned", "Unrestricted", "Bypass", "Undefined", "Default",
    "blocked", "missing", "unavailable", "rejected", "timeout", "crash", "not_attempted", "not_running",
    "auto", "always", "never", "valid", "invalid", "running", "stopped", "disabled", "none", "unauthorized",
    "denied", "empty", "cfg", "path", "candidate", "on", "off", "policy", "newacct_default",
}
RX = {
    "version": r"\d{1,6}(\.\d{1,6}){0,3}", "date": r"\d{4}-\d{2}-\d{2}", "iso": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
    "hresult": r"0x[0-9A-F]{8}", "type": r"[A-Za-z][A-Za-z0-9_.]{0,79}", "tz": r"[A-Za-z][A-Za-z0-9 .()+\-]{0,63}",
    "sig": r"[0-9a-f]{12}", "office": r"\d{1,2}\.\d",
}
FIELD_RX = {"version": "version", "new_version": "version", "classic_version": "version", "ps_version": "version",
            "hresult": "hresult", "horizon_oldest": "date", "horizon_newest": "date", "newest": "date", "oldest": "date",
            "sent_horizon_oldest": "date", "sent_horizon_newest": "date",
            "now_utc": "iso", "sig": "sig", "tz_id": "tz"}


def bad_strings(obj, key: str = "", parent: str = "") -> list[str]:
    """출력의 모든 문자열이 필드별 허용 규칙에 맞는지 — 어긋난 '경로' 목록(값은 돌려주지 않는다)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += bad_strings(v, str(k), key)
    elif isinstance(obj, list):
        for v in obj:
            out += bad_strings(v, key, parent)
    elif isinstance(obj, str):
        ok = False
        if key == "reasons":
            ok = obj in rcmap.REASONS
        elif key == "stub_env":
            ok = obj in INJECT_NAMES
        elif key == "versions":
            ok = re.fullmatch(RX["office"], obj) is not None
        elif parent == "error_types":
            ok = re.fullmatch(RX["type"], obj) is not None
        elif key in FIELD_RX:
            ok = re.fullmatch(RX[FIELD_RX[key]], obj) is not None
        else:
            ok = obj in ENUMS
        if not ok:
            out.append(f"{parent}.{key}")
    return out


# ── 시나리오 ─────────────────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Spec:
    over: dict | None = None                 # healthy 위 덮어쓰기
    cfg: dict | None = None                  # stdin _in.cfg (None = stdin 비움 → 기본값)
    only: str = ""
    env: dict = field(default_factory=dict)  # 추가 주입 변수(값이 함수면 그 폴더에 파일을 만들고 경로를 돌려준다)
    fake: bool = True                        # LM_PROBE_FAKE 를 넣는가
    raw: dict | None = None                  # healthy 대신 이 사실 묶음
    clm: bool = False                        # 실제 제한 언어 모드 세션에서 실행


def _deep(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if v == DEL:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


ZERO_IDX = {"idx": {"mail": {"n30": 0, "n90": 0, "n365": 0, "newest": None, "oldest": None},
                    "cal": {"n30": 0, "n90": 0, "n365": 0, "newest": None, "oldest": None, "recurring": 0}}}
COUNTS = {   # 건수·시각만 바꾼 것 — sig 는 그대로여야 한다
    "com": {"mail_total": 120, "mail_default": 100, "folders": 3, "cal_items": 7, "inbox_newest": "2026-10-05T06:00:00Z"},
    "idx": {"mail": {"n30": 5, "n90": 9, "n365": 11}, "cal": {"n30": 1, "n90": 2, "n365": 3, "recurring": 1}},
    "uia": {"lines": 12, "time_matches": 2, "generic_matches": 0},
    "pc": {"lnk": 7, "mru": 3},
}

# 카나리아 — 출력되는 문자열 칸에는 그 칸의 허용 형식에 맞지 않는 값을, 출력되지 않는 칸에는 아무 값이나 심는다
CANARIES = [c for c in canaries(groups=("pii", "env", "ctx"), weak=False) if c.value]


def _pick(rx: str | None, n: int = 1, skip: int = 0) -> list[str]:
    vals = [c.value for c in CANARIES if rx is None or re.fullmatch(rx, c.value) is None]
    vals = vals[skip:] + vals[:skip]
    return vals[:n]


def _canary_fake() -> dict:
    b = copy.deepcopy(BASE)
    any_ = _pick(None, 12, skip=3)
    b["env"]["tz_id"] = _pick(RX["tz"], 1, 1)[0]
    b["env"]["ps_version"] = _pick(RX["version"], 1, 2)[0]
    b["env"]["exec_policy"]["Process"] = _pick(None, 1, 4)[0]
    b["env"]["user_name"] = any_[0]
    b["env"]["computer_name"] = any_[1]
    b["ol"]["version"] = _pick(RX["version"], 1, 5)[0]
    b["ol"]["profile_name"] = any_[2]
    b["ol"]["window_titles"] = [any_[3]]
    b["ol"]["av_state"] = _pick(None, 1, 6)[0]          # 열거 밖 → 'valid' 아님 → R-OMG(값은 null)
    b["com"]["store_names"] = [any_[4]]
    b["com"]["sample_subject"] = any_[5]
    b["com"]["inbox_oldest"] = any_[6]                   # 시각 아님 → 버림
    b["com"]["sent_newest"] = _pick(None, 1, 15)[0]
    b["com"]["store_types"] = {"primary": 1, _pick(None, 1, 16)[0]: 3}   # 열거 밖 키 → 버림
    b["edge"]["version"] = _pick(RX["version"], 1, 7)[0]
    b["edge"]["profile_path"] = any_[7]
    b["teams"]["new_version"] = _pick(RX["version"], 1, 8)[0]
    b["teams"]["window_title"] = any_[8]
    b["uia"]["sample_lines"] = [any_[9], any_[10]]
    b["pc"]["office_versions"] = ["16.0", _pick(RX["office"], 1, 9)[0]]
    b["pc"]["event_errors"] = {"diag_perf": _pick(RX["type"], 1, 10)[0]}
    b["pc"]["events"]["diag_perf"] = "error"
    b["pc"]["recent_names"] = [any_[11]]
    b["idx"]["mail"]["newest"] = _pick(None, 1, 11)[0]
    return b


def _canary_fake_b() -> dict:
    b = copy.deepcopy(BASE)
    b["com"]["mode"] = "error"
    b["com"]["hresult"] = _pick(RX["hresult"], 1, 12)[0]
    return b


def _write_index_fake(d: Path) -> Path:
    p = guard_write(d / "index_fake.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(json.dumps(INDEX_FAKE, ensure_ascii=False).encode("utf-8"))
    return p


INDEX_FAKE = index_fake(synth.plan_month(2026, 9))

SCEN: dict[str, Spec] = {
    # 긴 것을 먼저 — 병렬 배치가 빨리 끝나게
    "com_hang_default": Spec(over={"com": {"mode": "hang"}}, cfg=None, only="P-OL-COM"),      # stdin 없음 → 기본 워치독 20초
    "budget": Spec(over={"com": {"mode": "hang"}}, cfg={"probe.budgetSec": 6}),
    "com_hang": Spec(over={"com": {"mode": "hang"}}, cfg={"mail.com.watchdogSec": 5}, only=OL),
    # 붙은 뒤 멈춤 — 첫 진전(attached)이 자식 기동(부하 시 수 초)보다 늦지 않게 워치독 10초
    "com_hang_attached": Spec(over={"com": {"mode": "hang_after_attach"}}, cfg={"mail.com.watchdogSec": 10}, only=OL),
    "uia_hang": Spec(over={"uia": {"mode": "hang"}}, cfg={"teams.uia.windowWatchdogSec": 3}, only="P-TEAMS"),
    "omg_hang": Spec(over={"com": {"protected_mode": "hang"}}, cfg={}, only=OL),
    "healthy": Spec(cfg={}),
    "healthy_counts": Spec(over=COUNTS, cfg={}),
    "canary": Spec(raw=_canary_fake(), cfg={"teams.timeRegex": _pick(None, 1, 13)[0], "pc.git.exe": _pick(None, 1, 14)[0]}),
    "canary_b": Spec(raw=_canary_fake_b(), cfg={}, only="P-OL-COM"),
    "clm_real": Spec(over={"env": {"language_mode": DEL}}, clm=True),
    "selftest": Spec(fake=False, env={"LM_OUTLOOK_SELFTEST": "5"}, cfg={}, only=OL),
    # W1a 통합: Get-OutlookCom.ps1(WP-15)의 'N[,선택…]' 문법도 시험 모드로 읽는다 — ol·com 사실이 없는 가짜 위에서
    # 선택이 붙은 값이 시험 Outlook 으로 채워져야 한다(해석 실패로 실물 경로에 빠지지 않는다). LM_PROBE_FAKE 가 있어 실물은 읽지 않는다.
    "selftest_opts": Spec(over={"ol": DEL, "com": DEL}, env={"LM_OUTLOOK_SELFTEST": "5,newol,horizon=2026-01"}, cfg={},
                          only=OL),
    "indexfake": Spec(fake=False, env={"LM_INDEX_FAKE": _write_index_fake, "LM_OUTLOOK_SELFTEST": "3"}, cfg={}, only="P-IDX"),
    # Outlook(P-OL-INST · P-OL-COM)
    "newol": Spec(over={"ol": {"classic": False, "new_installed": True, "use_new": True, "running": False}, **ZERO_IDX},
                  cfg={}, only=OL + ",P-IDX"),
    "newol_toggle": Spec(over={"ol": {"use_new": True}}, cfg={}, only=OL),          # 토글만 — 클래식 있음(v1.3 V3)
    "newol_only": Spec(over={"ol": {"use_new": True, "new_installed": True, "classic": False, "running": False}},
                       cfg={}, only=OL),                                          # 진짜 새 Outlook 전용
    "newol_running_classic": Spec(over={"ol": {"new_installed": True, "new_running": True}}, cfg={}, only=OL),
    "noprof": Spec(over={"ol": {"profiles": 0, "running": False}, **ZERO_IDX}, cfg={}, only=OL + ",P-IDX"),
    "wizard": Spec(over={"ol": {"com_registered": False, "running": False}}, cfg={}, only=OL),
    "wizard_msi": Spec(over={"ol": {"msi": True, "running": False}}, cfg={}, only=OL),
    "wizard_running": Spec(over={"ol": {"com_server_match": False}}, cfg={}, only=OL),
    "not_running": Spec(over={"ol": {"running": False}}, cfg={}, only=OL),
    "dialog": Spec(over={"com": {"mode": "unavailable"}}, cfg={}, only=OL),
    "elev": Spec(over={"env": {"elevated": True}, "com": {"mode": "unavailable"}}, cfg={}, only=OL),
    "com_busy": Spec(over={"com": {"mode": "rejected"}}, cfg={}, only=OL),
    "com_error": Spec(over={"com": {"mode": "error", "hresult": "0x80080005"}}, cfg={}, only=OL),
    "com_crash": Spec(over={"com": {"mode": "crash"}}, cfg={}, only=OL),
    "omg_policy": Spec(over={"ol": {"omg_policy": "always"}}, cfg={}, only=OL),
    "omg_av": Spec(over={"ol": {"av_state": "invalid"}}, cfg={}, only=OL),
    "omg_blocked": Spec(over={"com": {"protected_mode": "blocked"}}, cfg={}, only=OL),
    "subfolder": Spec(over={"com": {"mail_total": 1000, "mail_default": 500}}, cfg={}, only=OL),
    "subfolder_cfg": Spec(over={"com": {"mail_total": 1000, "mail_default": 500}}, cfg={"probe.subfolderRatio": 0.6}, only=OL),
    "stale": Spec(over={"com": {"inbox_newest": "2026-10-01T04:00:00Z"}}, cfg={}, only=OL),
    "stale_cfg": Spec(over={"com": {"inbox_newest": "2026-10-01T04:00:00Z"}}, cfg={"probe.ostStaleH": 200}, only=OL),
    "office": Spec(over={"ol": {"version": "15.0.5023.1000", "c2r": False}}, cfg={}, only="P-OL-INST"),
    "online_com": Spec(over={"com": {"cached": False}, **ZERO_IDX}, cfg={}, only="P-OL-COM,P-IDX"),
    # 색인(P-IDX)
    "online_policy": Spec(over={"ol": {"cached_policy": "off"}, **ZERO_IDX}, cfg={}, only="P-IDX"),
    "noidx": Spec(over={"idx": {"service": "stopped", "connect": False}}, cfg={}, only="P-IDX"),
    "noidx_connect": Spec(over={"idx": {"connect": False}}, cfg={}, only="P-IDX"),
    "idxpolicy": Spec(over={"idx": {"policy_outlook": True}}, cfg={}, only="P-IDX"),
    "idxpaused_zero": Spec(over={"idx": {"catalog_status": 1, "paused_reason": 9, **ZERO_IDX["idx"]}}, cfg={}, only="P-IDX"),
    "idxpaused_some": Spec(over={"idx": {"catalog_status": 3}}, cfg={}, only="P-IDX"),
    "idx_zero_ok": Spec(over=ZERO_IDX, cfg={}, only="P-IDX"),
    # W2 검토 C10: 클래식·새 Outlook 모두 없음 → R-NOAPP(온라인 모드 아님) · 새 Outlook 패키지만 → R-NEWOL — 수집기와 같은 판정
    "idx_zero_noapp": Spec(over={"ol": {"classic": False, "new_installed": False, "use_new": False, "new_running": False,
                                        "running": False}, **ZERO_IDX}, cfg={}, only="P-OL-INST,P-IDX"),
    "idx_zero_newpkg": Spec(over={"ol": {"classic": False, "new_installed": True, "use_new": False, "new_running": False,
                                         "running": False}, **ZERO_IDX}, cfg={}, only="P-OL-INST,P-IDX"),
    # 환경·Edge·Teams·PC
    "clm": Spec(over={"env": {"language_mode": "ConstrainedLanguage", "ctypes": "fail", "addtype": "fail"}}, cfg={}),
    "applocker": Spec(over={"env": {"ctypes": "blocked", "addtype": "fail"}}, cfg={}, only="P-ENV,P-PC"),
    "tz": Spec(over={"env": {"tz_offset_min": 0, "tz_id": "UTC"}}, cfg={}, only="P-ENV"),
    "edgepol_rd": Spec(over={"edge": {"remote_debugging": 0}}, cfg={}, only="P-EDGE"),
    "edgepol_dt": Spec(over={"edge": {"devtools": 2}}, cfg={}, only="P-EDGE"),
    # ── M365 조사(계정 있는 회사 PC) ──
    # H7: 프로필 판정이 0 이어도 Outlook 이 떠 있으면 붙기 결과로(문서화되지 않은 레지스트리 모양으로 COM 을 막지 않는다)
    "noprof_running": Spec(over={"ol": {"profiles": 0, "profiles_total": 2}}, cfg={}, only=OL),
    # M13: 관리자 전환 정책 — 값만 남기고 막지 않는다(떠 있는 클래식에는 붙는다)
    "migration": Spec(over={"ol": {"migration_auto": 1, "migration_retry": 1}}, cfg={}, only=OL),
    # L7: 동기화 기간 정책 키(일 단위)
    "sync_policy": Spec(over={"ol": {"sync_months": 0, "sync_days": 14, "sync_src": "policy"}}, cfg={}, only="P-OL-INST"),
    # M2: 0 건이지만 옛 항목만 있음(색인이 멈춤) · 0 건 + Outlook 꺼짐(원인 미상)
    "idx_zero_old": Spec(over={"idx": {"mail": {"n30": 0, "n90": 0, "n365": 0, "newest": "2025-06-01T00:00:00Z",
                                                "oldest": "2024-01-02T00:00:00Z"}}}, cfg={}, only="P-IDX"),
    "idx_zero_notrunning": Spec(over={"ol": {"running": False}, **ZERO_IDX}, cfg={}, only="P-IDX"),
    # L7: HKCU 정책 값만(문서 경로 HKLM 아님) — 판정에 쓰지 않는다
    "idxpolicy_hkcu": Spec(over={"idx": {"policy_hkcu": True}}, cfg={}, only="P-IDX"),
    # H10(색인 쪽 경고): 메일 최신 항목이 오래됐고 Outlook 이 꺼져 있다
    "idx_stale": Spec(over={"ol": {"running": False}, "idx": {"mail": {"newest": "2026-09-20T00:00:00Z"}}}, cfg={}, only="P-IDX"),
    "edge_none": Spec(over={"edge": {"installed": False, "version": None}}, cfg={}, only="P-EDGE"),
    "uia_novisible": Spec(over={"uia": {"visible": 0, "lines": 0}}, cfg={}, only="P-TEAMS"),
    "uia_denied": Spec(over={"uia": {"mode": "denied"}}, cfg={}, only="P-TEAMS"),
    "uia_nolines": Spec(over={"uia": {"lines": 0, "time_matches": 0, "generic_matches": 0}}, cfg={}, only="P-TEAMS"),
    "teams_not_running": Spec(over={"teams": {"processes": 0}}, cfg={}, only="P-TEAMS"),
    "teams_none": Spec(over={"teams": {"new_installed": False, "classic_installed": False, "processes": 0}}, cfg={},
                       only="P-TEAMS"),
    "pc_a": Spec(over={"pc": {"events": {"security": "unauthorized"}, "recent_policy": True, "mru": 0, "office_versions": [],
                              "git": False, "git_src": None}}, cfg={}, only="P-PC"),
    "pc_b": Spec(over={"pc": {"events": {"system": "unauthorized"}, "lnk": 0}}, cfg={}, only="P-PC"),
    "sig_env": Spec(over={"env": {"elevated": True}, "ol": {"omg_policy": "never"}, "edge": {"remote_debugging": 1}}, cfg={},
                    only="P-ENV,P-OL-INST,P-EDGE,P-PC"),
    "fake_unreadable": Spec(fake=False, env={"LM_PROBE_FAKE": lambda d: d / "no_such_fake.json"}, cfg={},
                            only="P-ENV,P-OL-INST,P-IDX,P-EDGE,P-TEAMS,P-PC"),
}

E: frozenset = frozenset()
OK_ALL = dict.fromkeys(ALL_KEYS, ("ok", E))
EXPECT: dict[str, dict[str, tuple[str, set | frozenset]]] = {
    "healthy": OK_ALL,
    "healthy_counts": OK_ALL,
    "newol": {"mail.com": ("fail", {"R-NEWOL"}), "cal.com": ("fail", {"R-NEWOL"}),
              "mail.index": ("fail", {"R-NEWOL"}), "cal.index": ("fail", {"R-NEWOL"})},
    # v1.3 §0.8 V3: 클래식이 있으면 토글·새 Outlook 실행만으로 막힘이 아니다 — COM 으로 읽는다(LM24 와 같음)
    "newol_toggle": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "newol_running_classic": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "newol_only": {"mail.com": ("fail", {"R-NEWOL"}), "cal.com": ("fail", {"R-NEWOL"})},
    "noprof": {"mail.com": ("fail", {"R-NOPROF"}), "cal.com": ("fail", {"R-NOPROF"}), "mail.index": ("fail", {"R-NOPROF"})},
    "noprof_running": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "migration": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "sync_policy": {"mail.com": ("unknown", E)},
    "idx_zero_old": {"mail.index": ("unknown", {"R-STALE"}), "cal.index": ("ok", E)},
    "idx_zero_notrunning": {"mail.index": ("unknown", E), "cal.index": ("unknown", E)},
    "idxpolicy_hkcu": {"mail.index": ("ok", E), "cal.index": ("ok", E)},
    "idx_stale": {"mail.index": ("ok", {"R-STALE"}), "cal.index": ("ok", E)},
    "wizard": {"mail.com": ("fail", {"R-WIZARD"}), "cal.com": ("fail", {"R-WIZARD"})},
    "wizard_msi": {"mail.com": ("fail", {"R-WIZARD"})},
    "wizard_running": {"mail.com": ("ok", {"R-WIZARD"})},
    "not_running": {"mail.com": ("unknown", E), "cal.com": ("unknown", E)},
    "dialog": {"mail.com": ("fail", {"R-DIALOG"}), "cal.com": ("fail", {"R-DIALOG"})},
    "elev": {"mail.com": ("fail", {"R-ELEV"})},
    "com_busy": {"mail.com": ("transport_fail", {"R-COM-BUSY"})},
    "com_error": {"mail.com": ("transport_fail", {"R-TRANSPORT"})},
    "com_crash": {"mail.com": ("transport_fail", {"R-TRANSPORT"})},
    "com_hang": {"mail.com": ("transport_fail", {"R-TRANSPORT"}), "cal.com": ("transport_fail", {"R-TRANSPORT"})},
    "com_hang_attached": {"mail.com": ("transport_fail", {"R-TRANSPORT"})},
    "com_hang_default": {"mail.com": ("transport_fail", {"R-TRANSPORT"})},
    "omg_policy": {"mail.com": ("ok", {"R-OMG"}), "cal.com": ("ok", {"R-OMG"})},
    "omg_av": {"mail.com": ("ok", {"R-OMG"})},
    "omg_hang": {"mail.com": ("ok", {"R-OMG"})},
    "omg_blocked": {"mail.com": ("ok", {"R-OMG"})},
    "subfolder": {"mail.com": ("ok", {"R-SUBFOLDER"}), "cal.com": ("ok", E)},
    "subfolder_cfg": {"mail.com": ("ok", E)},
    "stale": {"mail.com": ("ok", {"R-STALE"})},
    "stale_cfg": {"mail.com": ("ok", E)},
    "office": {"mail.com": ("unknown", {"R-OFFICE"})},
    "online_com": {"mail.index": ("fail", {"R-ONLINE"}), "cal.index": ("fail", {"R-ONLINE"}), "mail.com": ("ok", E)},
    "online_policy": {"mail.index": ("fail", {"R-ONLINE"}), "cal.index": ("fail", {"R-ONLINE"})},
    "noidx": {"mail.index": ("fail", {"R-NOIDX"}), "cal.index": ("fail", {"R-NOIDX"})},
    "noidx_connect": {"mail.index": ("fail", {"R-NOIDX"})},
    "idxpolicy": {"mail.index": ("fail", {"R-IDXPOLICY"}), "cal.index": ("fail", {"R-IDXPOLICY"})},
    "idxpaused_zero": {"mail.index": ("fail", {"R-IDXPAUSED"}), "cal.index": ("fail", {"R-IDXPAUSED"})},
    "idxpaused_some": {"mail.index": ("ok", {"R-IDXPAUSED"})},
    # M365 조사 M2: 클래식이 있는데 색인에 Outlook 항목 0 — 온라인 모드의 양의 증거(붙은 COM 캐시 아님·정책 끔)가 없으면
    # 원인 미상(unknown, 사유 없음). 예전 V4 는 R-ONLINE(구조·확정 가능)으로 굳히고 '온라인 모드' 안내를 냈다
    "idx_zero_ok": {"mail.index": ("unknown", E), "cal.index": ("unknown", E)},
    "idx_zero_noapp": {"mail.index": ("fail", {"R-NOAPP"}), "cal.index": ("fail", {"R-NOAPP"})},
    "idx_zero_newpkg": {"mail.index": ("fail", {"R-NEWOL"}), "cal.index": ("fail", {"R-NEWOL"})},
    "clm": {"env": ("fail", {"R-CLM"}), "mail.com": ("fail", {"R-CLM"}), "cal.com": ("fail", {"R-CLM"}),
            "mail.index": ("fail", {"R-CLM"}), "cal.index": ("fail", {"R-CLM"}), "teams.uia": ("fail", {"R-CLM"}),
            "pc.sampler": ("fail", {"R-CLM"}), "edge_cdp_policy": ("ok", E),
            # W1 통합 창 결함 수정: PS 수집기 경로(pc.events·pc.recent·pc.mru)도 CLM 이면 막힌다(수집기 rc 3 + R-CLM)
            "pc.events": ("fail", {"R-CLM"}), "pc.recent": ("fail", {"R-CLM"}), "pc.mru": ("fail", {"R-CLM"}),
            "pc.git": ("ok", E)},
    "clm_real": {"env": ("fail", {"R-CLM"}), "mail.com": ("fail", {"R-CLM"}), "cal.com": ("fail", {"R-CLM"}),
                 "mail.index": ("fail", {"R-CLM"}), "teams.uia": ("fail", {"R-CLM"}), "pc.sampler": ("ok", E),
                 "edge_cdp_policy": ("ok", E)},
    "applocker": {"env": ("fail", {"R-APPLOCKER"}), "pc.sampler": ("fail", {"R-APPLOCKER"})},
    "tz": {"env": ("ok", {"R-TZ"})},
    "edgepol_rd": {"edge_cdp_policy": ("fail", {"R-EDGEPOL"})},
    # M365 조사 M3: DeveloperToolsAvailability=2 만으로는 원격 디버깅 금지가 아니다(문서 — RemoteDebuggingAllowed 가 정본)
    "edgepol_dt": {"edge_cdp_policy": ("ok", E)},
    "edge_none": {"edge_cdp_policy": ("fail", {"R-NOAPP"})},          # C4 — 실패에는 사유(미설치)
    "uia_novisible": {"teams.uia": ("fail", {"R-UIAEMPTY"})},
    "uia_denied": {"teams.uia": ("fail", {"R-UIAELEV"})},
    "uia_nolines": {"teams.uia": ("fail", {"R-UIAEMPTY"})},
    "uia_hang": {"teams.uia": ("transport_fail", {"R-TRANSPORT"})},
    "teams_not_running": {"teams.uia": ("unknown", E)},
    "teams_none": {"teams.uia": ("fail", {"R-NOAPP"})},              # C4
    "pc_a": {"pc.events": ("ok", E),   # C5 — 보너스 채널 권한 없음은 사유 없이
              "pc.recent": ("fail", {"R-RECENTPOLICY"}), "pc.mru": ("ok", {"R-MRUEMPTY"}),
             "pc.git": ("fail", {"R-NOGIT"}), "pc.sampler": ("ok", E)},
    "pc_b": {"pc.events": ("fail", {"R-NOEVT"}), "pc.recent": ("ok", {"R-MRUEMPTY"}), "pc.mru": ("ok", E), "pc.git": ("ok", E)},
    "budget": {"mail.com": ("unknown", {"R-BUDGET"}), "cal.com": ("unknown", {"R-BUDGET"}),
               "teams.uia": ("unknown", {"R-BUDGET"}), "env": ("ok", E), "mail.index": ("ok", E), "edge_cdp_policy": ("ok", E),
               "pc.git": ("ok", E)},
    "selftest": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "selftest_opts": {"mail.com": ("ok", E), "cal.com": ("ok", E)},
    "indexfake": {"mail.index": ("ok", E), "cal.index": ("ok", E)},
    "fake_unreadable": {k: ("unknown", E) for k in ALL_KEYS if k != "env"},
}


# ── 실행 ─────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Run:
    rc: int
    out: bytes
    err: bytes
    wall: float
    obj: dict | None


CLONE = None
RUNS: dict[str, Run] = {}


def _q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def run_probe(clone, name: str, spec: Spec) -> Run:
    d = clone.sandbox / "wp17"
    d.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {}
    if spec.fake:
        fake = spec.raw if spec.raw is not None else _deep(BASE, spec.over)
        p = guard_write(d / f"{name}.json")
        p.write_bytes(json.dumps(fake, ensure_ascii=False).encode("utf-8"))
        env["LM_PROBE_FAKE"] = str(p)
    for k, v in spec.env.items():
        val: object = v(d) if isinstance(v, Callable) else v
        env[k] = str(val)
    script = clone.path("collect", "Invoke-CapabilityProbe.ps1")
    args = ["-TestNow", TEST_NOW] + (["-Only", spec.only] if spec.only else [])
    if spec.clm:
        # 인자 이름(-TestNow 등)은 따옴표 없이, 값만 따옴표로(따옴표 친 '-X' 는 위치 인자로 묶인다)
        cmd = ("$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; & " + _q(script) + " "
               + " ".join(a if a.startswith("-") else _q(a) for a in args) + "; exit $LASTEXITCODE")
        argv = [str(PS), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd]
    else:
        argv = [str(PS), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    data = in_line(cfg=spec.cfg) if spec.cfg is not None else b""
    t0 = time.monotonic()
    cp = subprocess.run(argv, input=data, capture_output=True, cwd=str(clone.temp), env=clone.env(env), timeout=240,
                        creationflags=CREATE_NO_WINDOW, check=False)
    wall = time.monotonic() - t0
    lines = [ln for ln in cp.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    obj = None
    if len(lines) == 1:
        try:
            obj = json.loads(lines[0])
        except ValueError:
            obj = None
    return Run(cp.returncode, cp.stdout, cp.stderr, wall, obj)


def _leftover_children(clone) -> int:
    """복제 트리의 탐침 자식(-Child)이 아직 살아 있는가 — 질의 명령줄에는 복제 경로를 싣지 않는다(환경 변수로 넘김)."""
    cmd = ("@(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -and "
           "$_.CommandLine.Contains($env:LM27T_PROBE_ROOT) -and $_.CommandLine.Contains('-Child') }).Count")
    cp = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, timeout=120,
                        env=dict(os.environ, LM27T_PROBE_ROOT=str(clone.root)), creationflags=CREATE_NO_WINDOW, check=False)
    try:
        return int(cp.stdout.decode("ascii", "replace").strip() or "0")
    except ValueError:
        return -1


def setUpModule():
    global CLONE
    if os.name != "nt" or not PS.is_file():
        raise unittest.SkipTest("Windows PowerShell 5.1 없음")
    CLONE = make_clone(parts=("collect",), entry=False)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {n: ex.submit(run_probe, CLONE, n, s) for n, s in SCEN.items()}
        for n, f in futs.items():
            RUNS[n] = f.result()


def tearDownModule():
    if CLONE is not None:
        CLONE.remove()


def _obj(tc: unittest.TestCase, name: str) -> dict:
    r = RUNS[name]
    if r.obj is None:
        tc.fail(f"{name}: 출력 JSON 없음 rc={r.rc} stderr={r.err.decode('utf-8', 'replace')[-800:]}"
                f" stdout={r.out.decode('utf-8', 'replace')[:400]}")
    return r.obj


def _cap(tc: unittest.TestCase, name: str, key: str) -> dict:
    o = _obj(tc, name)
    tc.assertIn(key, o["caps"], f"{name}: caps 에 {key} 없음")
    return o["caps"][key]


# ── 시험 ─────────────────────────────────────────────────────────────────────────────────────────────────
class ReasonCodes(unittest.TestCase):
    """가짜 환경마다 기대 사유 코드·상태(계획 WP-17 완료 기준의 R-* 전부)."""

    def test_expected_status_and_reasons(self):
        for name, exp in EXPECT.items():
            for key, (status, reasons) in exp.items():
                with self.subTest(scenario=name, key=key):
                    c = _cap(self, name, key)
                    self.assertEqual(c["status"], status)
                    self.assertEqual(set(c["reasons"]), set(reasons))

    def test_every_completion_reason_covered(self):
        need = {"R-NEWOL", "R-NOPROF", "R-WIZARD", "R-DIALOG", "R-OMG", "R-CLM", "R-ELEV", "R-ONLINE", "R-NOIDX",
                "R-IDXPOLICY", "R-IDXPAUSED", "R-EDGEPOL", "R-SUBFOLDER", "R-STALE", "R-OFFICE", "R-TZ"}
        seen = {r for exp in EXPECT.values() for _s, rs in exp.values() for r in rs}
        self.assertEqual(sorted(need - seen), [])

    def test_new_outlook_index_tried(self):
        # X-124: 새 Outlook 이어도 색인은 시도하고(서비스 running 기록) Outlook 항목이 없으면 blocked:R-NEWOL
        c = _cap(self, "newol", "mail.index")
        self.assertEqual(c["value"]["service"], "running")
        self.assertEqual(c["value"]["n_365d"], 0)
        self.assertEqual(_cap(self, "newol", "mail.com")["value"]["attach"], "not_attempted")
        self.assertTrue(_cap(self, "newol", "mail.com")["value"]["new_outlook"])

    def test_no_index_is_service_only(self):
        # X-125: R-NOIDX 는 서비스 꺼짐·연결 실패만 — Outlook 항목 0 은 R-ONLINE·R-NEWOL·R-IDXPOLICY 로 나뉜다
        self.assertNotIn("R-NOIDX", _cap(self, "online_policy", "mail.index")["reasons"])
        self.assertNotIn("R-NOIDX", _cap(self, "idx_zero_ok", "mail.index")["reasons"])

    def test_omg_details(self):
        self.assertEqual(_cap(self, "omg_policy", "mail.com")["value"]["protected_read"], "skipped")
        self.assertEqual(_cap(self, "omg_av", "mail.com")["value"]["protected_read"], "skipped")
        self.assertEqual(_cap(self, "omg_hang", "mail.com")["value"]["protected_read"], "timeout")
        self.assertEqual(_cap(self, "omg_blocked", "mail.com")["value"]["protected_read"], "blocked")
        self.assertEqual(_cap(self, "healthy", "mail.com")["value"]["protected_read"], "ok")
        for n in ("omg_policy", "omg_hang", "omg_blocked"):
            v = _cap(self, n, "mail.com")["value"]
            self.assertEqual(v["attach"], "ok", n)        # A단은 그대로 — B단만 막힘
            self.assertTrue(v["omg"], n)

    def test_com_failure_details(self):
        self.assertEqual(_cap(self, "dialog", "mail.com")["value"]["hresult"], "0x800401E3")
        self.assertEqual(_cap(self, "com_busy", "mail.com")["value"]["hresult"], "0x8001010A")
        self.assertEqual(_cap(self, "com_error", "mail.com")["value"]["hresult"], "0x80080005")
        self.assertEqual(_cap(self, "com_crash", "mail.com")["value"]["attach"], "crash")
        self.assertEqual(_cap(self, "not_running", "mail.com")["value"]["attach"], "not_running")
        # 떠 있지 않은 Outlook 은 띄우지 않는다(New-Object 없음 — 마법사 무한 대기 방지, C §4.3)
        for n in ("wizard", "wizard_msi"):
            self.assertEqual(_cap(self, n, "mail.com")["value"]["attach"], "not_running", n)
        for n in ("noprof", "newol"):
            self.assertEqual(_cap(self, n, "mail.com")["value"]["attach"], "not_attempted", n)

    def test_subfolder_stale_values(self):
        v = _cap(self, "subfolder", "mail.com")["value"]
        self.assertAlmostEqual(v["subfolder_ratio"], 0.5)
        self.assertAlmostEqual(_cap(self, "healthy", "mail.com")["value"]["subfolder_ratio"], 0.1)
        self.assertEqual(_cap(self, "stale", "mail.com")["value"]["newest_age_h"], 100)
        self.assertEqual(_cap(self, "stale", "mail.com")["value"]["horizon_newest"], "2026-10-01")

    def test_horizon_and_stores(self):
        v = _cap(self, "healthy", "mail.com")["value"]
        self.assertEqual((v["horizon_oldest"], v["horizon_newest"]), ("2025-10-06", "2026-10-05"))
        self.assertEqual((v["sent_horizon_oldest"], v["sent_horizon_newest"]), ("2025-10-07", "2026-10-05"))
        self.assertEqual(v["store_types"], {"primary": 1, "delegate": 0, "public": 0, "non_exchange": 1, "additional": 0})
        self.assertEqual((v["stores"], v["exchange_mode"], v["cached"], v["sync_months"]), (2, 700, True, 12))

    def test_office_eol_value(self):
        self.assertTrue(_cap(self, "office", "mail.com")["value"]["office_eol"])
        self.assertFalse(_cap(self, "healthy", "mail.com")["value"]["office_eol"])

    def test_uia_values(self):
        self.assertEqual(_cap(self, "uia_novisible", "teams.uia")["value"]["uia"], "none")
        self.assertEqual(_cap(self, "uia_denied", "teams.uia")["value"]["uia"], "denied")
        self.assertEqual(_cap(self, "uia_nolines", "teams.uia")["value"]["uia"], "empty")
        v = _cap(self, "healthy", "teams.uia")["value"]
        self.assertEqual((v["windows"], v["visible"], v["uia_lines"], v["time_matches"]), (2, 1, 180, 36))

    def test_sampler_values(self):
        self.assertEqual(_cap(self, "healthy", "pc.sampler")["value"], {"ps": True, "py": True})
        self.assertEqual(_cap(self, "clm", "pc.sampler")["value"], {"ps": False, "py": False})
        self.assertEqual(_cap(self, "applocker", "pc.sampler")["value"], {"ps": False, "py": False})

    def test_status_semantics_all_runs(self):
        # history.status(계약 §6.4): ok ↔ ok=true · fail/transport_fail ↔ false · unknown ↔ null.
        # 수송 실패는 '불가' 확정 근거가 아니다(D-7) — transport_fail 에 확정 ✔ 사유가 섞이면 안 된다.
        for name in SCEN:
            o = _obj(self, name)
            for key, c in o["caps"].items():
                with self.subTest(scenario=name, key=key):
                    self.assertIn(c["status"], STATUSES)
                    self.assertEqual(c["ok"], {"ok": True, "fail": False, "transport_fail": False}.get(c["status"]))
                    self.assertEqual(c["reasons"], sorted(set(c["reasons"])))
                    self.assertTrue(set(c["reasons"]) <= set(rcmap.REASONS))
                    if c["status"] == "transport_fail":
                        self.assertEqual(set(c["reasons"]) & rcmap.CONFIRMABLE, set())
                    if "R-TRANSPORT" in c["reasons"]:
                        self.assertEqual(c["status"], "transport_fail")
                    self.assertRegex(c["sig"], r"^[0-9a-f]{12}$")


class CompanyPcFacts(unittest.TestCase):
    """계정 있는 회사 PC 위험(M365 조사 — 공식 문서 대조) 반영 값."""

    def test_h7_running_outlook_not_blocked_by_profile_shape(self):
        v = _cap(self, "noprof_running", "mail.com")["value"]
        self.assertEqual((v["attach"], v["profiles"], v["profiles_total"]), ("ok", 0, 2))
        self.assertEqual(_cap(self, "healthy", "mail.com")["value"]["profiles_total"], 1)

    def test_m13_migration_policy_values(self):
        v = _cap(self, "migration", "mail.com")["value"]
        self.assertEqual((v["migration_auto"], v["migration_retry"]), (1, 1))
        self.assertIsNone(_cap(self, "healthy", "mail.com")["value"]["migration_auto"])
        self.assertNotEqual(_cap(self, "migration", "mail.com")["sig"], _cap(self, "healthy", "mail.com")["sig"])

    def test_l7_sync_window_source(self):
        v = _cap(self, "sync_policy", "mail.com")["value"]
        self.assertEqual((v["sync_months"], v["sync_days"], v["sync_src"]), (0, 14, "policy"))
        self.assertEqual(_cap(self, "healthy", "mail.com")["value"]["sync_src"], "newacct_default")

    def test_m3_devtools_policy_is_value_only(self):
        v = _cap(self, "edgepol_dt", "edge_cdp_policy")["value"]
        self.assertEqual((v["devtools"], v["devtools_blocked"], v["remote_debugging"]), (2, True, None))
        self.assertFalse(_cap(self, "healthy", "edge_cdp_policy")["value"]["devtools_blocked"])
        self.assertEqual(_cap(self, "edgepol_rd", "edge_cdp_policy")["reasons"], ["R-EDGEPOL"])

    def test_l7_index_policy_hklm_only(self):
        v = _cap(self, "idxpolicy_hkcu", "mail.index")["value"]
        self.assertEqual((v["policy"], v["policy_hkcu"]), (False, True))

    def test_m2_online_evidence_values(self):
        v = _cap(self, "idx_zero_notrunning", "mail.index")["value"]
        self.assertEqual((v["online"], v["outlook_running"], v["n_365d"]), (False, False, 0))
        self.assertTrue(_cap(self, "online_com", "mail.index")["value"]["online"])
        self.assertTrue(_cap(self, "online_policy", "mail.index")["value"]["online"])


class Watchdog(unittest.TestCase):
    """자식 + 워치독(C §4.3 · CM §5.2) — 무한 대기 가짜에서도 정해진 시간 안에 끝나고 자식이 남지 않는다."""

    def test_com_hang_watchdog_5s(self):
        r = RUNS["com_hang"]
        o = _obj(self, "com_hang")
        self.assertLess(r.wall, 20.0, "무한 대기 가짜에서 20초 안에 끝나야 한다")
        v = o["caps"]["mail.com"]["value"]
        self.assertEqual(v["attach"], "timeout")
        self.assertLessEqual(v["attach_ms"], 5000 + KILL_SLACK_MS)

    def test_com_hang_after_attach(self):
        # 붙은 뒤(A단 전에) 멈춤 — 마지막 진전(attached)부터 워치독 10초 뒤에 끊는다(무진전 기준, CM §5.2)
        v = _cap(self, "com_hang_attached", "mail.com")["value"]
        self.assertEqual(v["attach"], "ok")
        self.assertGreaterEqual(v["attach_ms"], 10000)
        self.assertLess(RUNS["com_hang_attached"].wall, 40.0)

    def test_com_hang_default_watchdog(self):
        # stdin 없음 → mail.com.watchdogSec 기본 20초: COM 단계가 20초(+끊는 시간) 안에 끝난다
        o = _obj(self, "com_hang_default")
        self.assertEqual(o["cfg_used"]["mail.com.watchdogSec"], 20)
        v = o["caps"]["mail.com"]["value"]
        self.assertEqual(v["attach"], "timeout")
        self.assertGreaterEqual(v["attach_ms"], 19000)
        self.assertLessEqual(v["attach_ms"], 20000 + KILL_SLACK_MS)

    def test_protected_read_limit(self):
        o = _obj(self, "omg_hang")
        self.assertLess(RUNS["omg_hang"].wall, 20.0)
        self.assertEqual(o["caps"]["mail.com"]["value"]["protected_read"], "timeout")
        self.assertEqual(o["caps"]["mail.com"]["value"]["horizon_newest"], "2026-10-05")   # A단 결과는 남는다

    def test_uia_hang(self):
        v = _cap(self, "uia_hang", "teams.uia")["value"]
        self.assertEqual(v["uia"], "timeout")
        self.assertLessEqual(v["uia_ms"], 3000 + KILL_SLACK_MS)

    def test_budget(self):
        o = _obj(self, "budget")
        self.assertTrue(o["budget_hit"])
        self.assertEqual(o["budget_sec"], 6)
        self.assertLessEqual(o["elapsed_ms"], 6000, "probe.budgetSec 안에 끝나야 한다")
        self.assertEqual(o["groups"]["P-OL-COM"], "budget")
        self.assertEqual(o["groups"]["P-TEAMS"], "budget")
        for g in ("P-ENV", "P-OL-INST", "P-IDX", "P-EDGE", "P-PC"):
            self.assertEqual(o["groups"][g], "done", g)        # 싼 사실은 예산 앞에서 모두 남는다

    def test_no_children_left(self):
        if CLONE is None:
            self.skipTest("복제 없음")
        self.assertEqual(_leftover_children(CLONE), 0, "탐침 자식 프로세스가 남았다")


class ContentZero(unittest.TestCase):
    """출력 = 숫자·열거·사유 코드만(계약 §6.7). 허용 필드 외 문자열 0건 · 카나리아 0건 · stdout 한 줄."""

    def test_rc_and_single_line(self):
        for name, r in RUNS.items():
            with self.subTest(scenario=name):
                self.assertEqual(r.rc, 0, r.err.decode("utf-8", "replace")[-500:])
                self.assertIsNotNone(r.obj, "stdout 은 JSON 한 줄")
                self.assertEqual(r.obj["schema"], SCHEMA)

    def test_only_allowed_strings(self):
        for name in RUNS:
            with self.subTest(scenario=name):
                self.assertEqual(bad_strings(_obj(self, name)), [])

    def test_canaries_absent(self):
        for name in ("canary", "canary_b"):
            r = RUNS[name]
            with self.subTest(scenario=name):
                self.assertEqual(find_canaries(r.out, CANARIES), [], "stdout 에 카나리아")
                self.assertEqual(find_canaries(r.err, CANARIES), [], "stderr 에 카나리아")
        o = _obj(self, "canary")
        self.assertIsNone(o["caps"]["env"]["value"]["tz_id"])
        self.assertIsNone(o["caps"]["env"]["value"]["ps_version"])
        self.assertNotIn("Process", o["caps"]["env"]["value"]["exec_policy"])
        self.assertIsNone(o["caps"]["mail.com"]["value"]["version"])
        self.assertIsNone(o["caps"]["mail.com"]["value"]["av_state"])
        self.assertIsNone(o["caps"]["mail.com"]["value"]["horizon_oldest"])
        self.assertIsNone(o["caps"]["mail.com"]["value"]["sent_horizon_newest"])
        self.assertEqual(o["caps"]["mail.com"]["value"]["store_types"], {"primary": 1})
        self.assertIsNone(o["caps"]["edge_cdp_policy"]["value"]["version"])
        self.assertIsNone(o["caps"]["teams.uia"]["value"]["new_version"])
        self.assertEqual(o["caps"]["pc.mru"]["value"]["versions"], ["16.0"])
        self.assertEqual(o["caps"]["pc.events"]["value"]["error_types"], {})
        self.assertIsNone(o["caps"]["mail.index"]["value"]["newest"])
        self.assertIsNone(_obj(self, "canary_b")["caps"]["mail.com"]["value"]["hresult"])

    def test_index_fake_content_absent(self):
        r = RUNS["indexfake"]
        text = r.out + r.err
        for row in INDEX_FAKE["mail"][:20] + INDEX_FAKE["calendar"][:10]:
            for k in ("System.Subject", "System.Calendar.Location"):
                v = row.get(k)
                if isinstance(v, str) and len(v) >= 4:
                    self.assertNotIn(v.encode("utf-8"), text, k)
            for k in ("System.Message.FromAddress", "System.Message.ToAddress"):
                for a in row.get(k) or []:
                    self.assertNotIn(a.encode("utf-8").lower(), text.lower(), k)

    def test_stderr_has_no_paths(self):
        for name, r in RUNS.items():
            with self.subTest(scenario=name):
                err = r.err.decode("utf-8", "replace")
                self.assertNotIn(":\\", err)
                self.assertNotIn(str(CLONE.root) if CLONE else "\0", err)


class Inputs(unittest.TestCase):
    """stdin 제어 줄 _in(계약 §7.3)·-Only·주입점(계약 §11.3)·stub_env_set."""

    def test_defaults_without_stdin(self):
        o = _obj(self, "com_hang_default")
        self.assertEqual(o["cfg_used"], {"probe.budgetSec": 60, "probe.subfolderRatio": 0.3, "probe.ostStaleH": 72,
                                         "mail.com.watchdogSec": 20, "mail.com.protectedReadSec": 2,
                                         "teams.uia.windowWatchdogSec": 15, "teams.uia.maxElements": 4000})

    def test_cfg_changes_result(self):
        # 설정 키를 바꾸면 결과가 바뀐다(죽은 키 금지, 계약 §5.1-6)
        self.assertIn("R-SUBFOLDER", _cap(self, "subfolder", "mail.com")["reasons"])
        self.assertNotIn("R-SUBFOLDER", _cap(self, "subfolder_cfg", "mail.com")["reasons"])
        self.assertEqual(_obj(self, "subfolder_cfg")["cfg_used"]["probe.subfolderRatio"], 0.6)
        self.assertIn("R-STALE", _cap(self, "stale", "mail.com")["reasons"])
        self.assertNotIn("R-STALE", _cap(self, "stale_cfg", "mail.com")["reasons"])
        self.assertEqual(_obj(self, "budget")["cfg_used"]["probe.budgetSec"], 6)

    def test_only_selects_keys(self):
        for name, spec in SCEN.items():
            o = _obj(self, name)
            groups = [g.strip() for g in spec.only.split(",")] if spec.only else list(GROUPS)
            want = {k for g in groups for k in KEYS_BY_GROUP[g]}
            with self.subTest(scenario=name):
                self.assertEqual(set(o["caps"]), want)
                self.assertEqual(list(o["groups"]), list(GROUPS))
                for g in GROUPS:
                    if g not in groups:
                        self.assertEqual(o["groups"][g], "skipped", g)

    def test_stub_env_warning(self):
        for name, spec in SCEN.items():
            o = _obj(self, name)
            names = set(spec.env) | ({"LM_PROBE_FAKE"} if spec.fake else set())
            with self.subTest(scenario=name):
                self.assertIn("stub_env_set", o["warnings"])
                self.assertTrue(names <= set(o["stub_env"]))
                self.assertTrue(o["synthetic"])

    def test_selftest_injection(self):
        v = _cap(self, "selftest", "mail.com")["value"]
        self.assertEqual((v["attach"], v["mail_total"]), ("ok", 5))
        self.assertEqual(_cap(self, "selftest", "cal.com")["value"]["cal_items"], 2)

    def test_selftest_injection_with_options(self):
        # 'N[,선택…]'(WP-15 Get-OutlookCom.ps1 문법) — 앞 정수 N 만 쓰고 시험 Outlook·COM 으로 채운다(W1a 통합 관문)
        v = _cap(self, "selftest_opts", "mail.com")["value"]
        self.assertEqual((v["attach"], v["mail_total"]), ("ok", 5))
        self.assertEqual(_cap(self, "selftest_opts", "cal.com")["value"]["cal_items"], 2)
        self.assertTrue(_obj(self, "selftest_opts")["synthetic"])

    def test_index_fake_injection(self):
        def counts(rows, col):
            out = {30: 0, 90: 0, 365: 0}
            for row in rows:
                t = datetime.strptime(row[col], "%Y-%m-%d %H:%M").astimezone().astimezone(UTC)
                age = (NOW_UTC - t).total_seconds() / 86400
                for n in out:
                    if age <= n:
                        out[n] += 1
            return out

        m = counts(INDEX_FAKE["mail"], "System.ItemDate")
        c = counts(INDEX_FAKE["calendar"], "System.StartDate")
        self.assertGreater(m[365], 0)
        mv = _cap(self, "indexfake", "mail.index")["value"]
        cv = _cap(self, "indexfake", "cal.index")["value"]
        self.assertEqual((mv["n_30d"], mv["n_90d"], mv["n_365d"]), (m[30], m[90], m[365]))
        self.assertEqual((cv["n_30d"], cv["n_90d"], cv["n_365d"]), (c[30], c[90], c[365]))
        self.assertEqual(cv["recurring"], sum(1 for r in INDEX_FAKE["calendar"] if r.get("System.Calendar.IsRecurring")))

    def test_fake_unreadable(self):
        o = _obj(self, "fake_unreadable")
        self.assertIn("fake_unreadable", o["warnings"])

    def test_real_constrained_language(self):
        # 실제 제한 언어 모드 세션에서도 결과를 내고 R-CLM 을 단다(stdin·Add-Type·자식 없이)
        o = _obj(self, "clm_real")
        self.assertEqual(o["caps"]["env"]["value"]["language_mode"], "ConstrainedLanguage")
        self.assertEqual(o["caps"]["mail.com"]["value"]["attach"], "not_attempted")
        self.assertEqual(o["caps"]["teams.uia"]["value"]["uia"], "not_attempted")


class Signature(unittest.TestCase):
    """sig = 구조 사실(설치·정책·권한)만의 해시 — 건수·시각이 바뀌어도 같고 환경이 바뀌면 달라진다(계약 §6.4 probe_sig)."""

    def test_counts_do_not_change_sig(self):
        a = _obj(self, "healthy")["caps"]
        b = _obj(self, "healthy_counts")["caps"]
        for k in ALL_KEYS:
            with self.subTest(key=k):
                self.assertEqual(a[k]["sig"], b[k]["sig"])
        self.assertNotEqual(a["mail.com"]["value"]["mail_total"], b["mail.com"]["value"]["mail_total"])

    def test_environment_changes_sig(self):
        a = _obj(self, "healthy")["caps"]
        b = _obj(self, "sig_env")["caps"]
        for k in ("env", "mail.com", "cal.com", "edge_cdp_policy"):
            self.assertNotEqual(a[k]["sig"], b[k]["sig"], k)
        for k in ("pc.events", "pc.recent", "pc.git"):
            self.assertEqual(a[k]["sig"], b[k]["sig"], k)

    def test_reason_change_changes_sig(self):
        a = _obj(self, "healthy")["caps"]
        self.assertNotEqual(a["edge_cdp_policy"]["sig"], _cap(self, "edgepol_rd", "edge_cdp_policy")["sig"])
        self.assertNotEqual(a["mail.index"]["sig"], _cap(self, "noidx", "mail.index")["sig"])


if __name__ == "__main__":
    unittest.main()
