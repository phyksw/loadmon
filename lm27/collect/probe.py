# -*- coding: utf-8 -*-
r"""능력 탐침 묶음 실행과 기록(계약 §2.5 · §6.7 · §3.8 · §6.4 · v1.2 C18, C §4 · TAB §1.5) — [수집]마다 맨 앞에서.

``probe_capabilities(paths, ident, cfg)``:
  · ``collect\Invoke-CapabilityProbe.ps1``(P-ENV · P-OL-INST · P-OL-COM · P-IDX · P-EDGE · P-TEAMS · P-PC)을 자식으로 띄우고
    stdin 제어 줄 ``{"_in": {"cursor": null, "cfg": {…}}}`` 로 설정을 넘긴다(계약 §7.3 — 명령줄에 싣지 않는다). 출력은 stdout
    한 줄 ``lm27.probe/1``(C18) — 숫자·열거·사유 코드만. 시간 한도 = ``probe.budgetSec`` + 여유(탐침 예산은 스크립트 시작부터
    재므로 PowerShell 기동 몫을 더한다 — WP-17).
  · P-TEAM(``team_server_reach``)은 ``lm27.team.client.hello(base, team.connectTimeoutSec)`` 로 기본 주소만 잰다(TAB §1.5 —
    값에는 URL·IP 대신 ``target`` 만). 그 모듈이 아직 없으면 건너뛴다(기록 없음). P-BUNDLE 은 호출자가 먼저 잰다
    (``lm27.bundle.pcreg.probe_bundle_location`` — 읽기 전용이면 [수집]이 거기서 멈추므로).
  · 원문 0: 탐침 값은 형식 검사(짧은 열거·숫자·날짜)를 통과한 것만 남기고, 계약 §6.1 표에 없는 사유 코드는 버린다(건수만).

``record_probes(pcdir, pr, loc)``: 능력마다 ``lm27.bundle.pcreg.record_probe``(쓰기 단일원)로 pc.json ``capabilities`` 에
남긴다 — ``history.probe_sig`` = 탐침의 ``sig``(구조 사실 해시 — 바뀌면 그 전 실패를 세지 않는다 = 자동 해제, 계약 §6.4).
``pc.sampler`` 는 탐침 값 ``{ps, py}`` 에 에이전트 설치 결과(``agent.json`` 의 impl·impl_reasons)를 ``value.impl`` 로 합친다
(WP-13·17 — 설치 자기 시험이 정본: py·ps 면 가능, none 이면 R-CLM·R-APPLOCKER 로 불가). 번들 잠금은 호출자가 쥔다.
"""
from __future__ import annotations

import importlib.util
import math
import os
import re
import time
from dataclasses import dataclass, field

from lm27.collect import rcmap
from lm27.util import fsx, proc

__all__ = [
    "CFG_KEYS", "PROBE_SCRIPT", "REACH_REASON", "SCHEMA", "ProbeResult", "in_line", "parse_probe", "powershell_exe",
    "probe_argv", "probe_capabilities", "record_probes", "sampler_cap", "team_reach",
]

PROBE_SCRIPT = "Invoke-CapabilityProbe.ps1"
SCHEMA = "lm27.probe/1"
# 탐침 스크립트가 _in.cfg 로 받는 키(스크립트 머리말 · 계약 §5.2 '읽는 곳' Invoke-CapabilityProbe)
CFG_KEYS = ("probe.budgetSec", "probe.subfolderRatio", "probe.ostStaleH", "mail.com.watchdogSec",
            "mail.com.protectedReadSec", "teams.uia.windowWatchdogSec", "teams.uia.maxElements", "teams.timeRegex",
            "pc.git.exe")
SLACK_S = 25                       # 예산 + 기동(약 2초 × 부모·COM·UIA 자식) + 끊는 시간(워치독 초 + 끊기 — C18)
TEAM_TARGET = "primary"
STATUSES = ("ok", "fail", "transport_fail", "unknown")
# team_server_reach.result → 사유(계약 §6.1 아래 주석) · 상태(도달 실패 = 수송, 다른 앱 = 실패)
REACH_REASON = {"timeout": "R-TEAM-TIMEOUT", "refused": "R-TEAM-REFUSED", "dns": "R-TEAM-DNS", "proxy": "R-TEAM-PROXY",
                "lm24": "R-TEAM-LM24", "other_lm": "R-TEAM-OTHERAPP", "other_app": "R-TEAM-OTHERAPP",
                "http_error": "R-TEAM-OTHERAPP", "wrong_major": "R-TEAM-VERSION"}
REACH_TRANSPORT = frozenset({"timeout", "refused", "dns", "proxy"})
SAMPLER_IMPLS = ("py", "ps", "none")
_KEY_RX = re.compile(r"^[a-z][a-z0-9_.]{1,47}$")
_SIG_RX = re.compile(r"^[0-9a-f]{12}$")
_VKEY_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_.\-]{0,47}$")
_CTRL_RX = re.compile(r"[\x00-\x1f\x7f]")
_VSTR_MAX = 64
_LIST_MAX = 64
_DEPTH = 4


def powershell_exe() -> str:
    """Windows PowerShell 5.1 절대 경로(PATH 에 흔들리지 않게 — 시스템 경로이지 데이터 경로가 아니다)."""
    sysroot = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


@dataclass
class ProbeResult:
    """탐침 한 번의 결과. ``rc`` 0 = 결과 있음(예산 소진도 0 + ``budget_hit``) · 3 = 탐침 실패(``error`` = 예외 유형 ·
    ``timeout`` · ``no_output`` · ``spawn``). ``caps`` = ``{키: {ok, status, reasons, value, sig}}``, ``team`` = P-TEAM."""
    rc: int = 3
    caps: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    budget_hit: bool = False
    elapsed_ms: int | None = None
    synthetic: bool = False
    warnings: list = field(default_factory=list)
    stub_env: list = field(default_factory=list)
    cfg_used: dict = field(default_factory=dict)
    now_utc: str | None = None
    error: str | None = None
    team: dict | None = None
    unknown_reasons: int = 0

    def cap(self, key: str) -> dict:
        c = self.caps.get(key)
        return dict(c) if isinstance(c, dict) else {}

    def reasons(self) -> list:
        """모든 능력의 사유 코드 합집합(정렬)."""
        out = set()
        for c in self.caps.values():
            out.update(c.get("reasons") or ())
        if self.team:
            out.update(self.team.get("reasons") or ())
        return sorted(out)


# ── 실행 ────────────────────────────────────────────────────────────────────
def in_line(cfg) -> dict:
    """탐침 stdin 제어 줄(계약 §7.3) — 그 스크립트가 쓰는 설정만."""
    return {"_in": {"cursor": None, "cfg": {k: cfg[k] for k in CFG_KEYS}}}


def probe_argv(paths, ident, *, only=None, test_now=None) -> list:
    argv = [powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(paths.collect_script(PROBE_SCRIPT)), "-Pc", ident.pc_id]
    if only:
        argv += ["-Only", ",".join(only)]
    if test_now:
        argv += ["-TestNow", str(test_now)]
    return argv


def _short(v) -> bool:
    return isinstance(v, str) and len(v) <= _VSTR_MAX and not _CTRL_RX.search(v) and "\\" not in v and "@" not in v


def _clean(v, depth=0):
    """탐침 값 정리 — 수·불리언·짧은 열거 문자열(경로·주소 모양 제외)·그것의 목록·사전만. 그 밖은 None."""
    if v is None or isinstance(v, bool) or (isinstance(v, int) and not isinstance(v, bool)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        return v if _short(v) else None
    if depth >= _DEPTH:
        return None
    if isinstance(v, list):
        return [_clean(x, depth + 1) for x in v[:_LIST_MAX]]
    if isinstance(v, dict):
        return {k: _clean(x, depth + 1) for k, x in sorted(v.items()) if isinstance(k, str) and _VKEY_RX.match(k)}
    return None


def _cap(raw) -> tuple:
    """탐침 출력 능력 하나 → (정리된 능력, 버린 사유 수)."""
    raw = raw if isinstance(raw, dict) else {}
    ok = raw.get("ok") if raw.get("ok") in (True, False, None) else None
    st = raw.get("status") if raw.get("status") in STATUSES else "unknown"
    rs = rcmap.norm_reasons(raw.get("reasons"))
    known = sorted(r for r in rs if rcmap.is_reason(r))
    sig = raw.get("sig") if isinstance(raw.get("sig"), str) and _SIG_RX.match(raw["sig"]) else None
    val = _clean(raw.get("value")) if isinstance(raw.get("value"), dict) else {}
    return {"ok": ok, "status": st, "reasons": known, "value": val, "sig": sig}, len(rs) - len(known)


def parse_probe(stdout_text: str) -> dict | None:
    """stdout 의 마지막 ``lm27.probe/1`` 줄(dict). 없으면 None."""
    for ln in reversed((stdout_text or "").splitlines()):
        s = ln.strip().lstrip("\ufeff")
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = fsx.loads_strict(s)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("schema") == SCHEMA:
            return obj
    return None


def _from_obj(obj: dict) -> ProbeResult:
    pr = ProbeResult(rc=0)
    if isinstance(obj.get("fatal"), str) or not isinstance(obj.get("caps"), dict):
        pr.rc, pr.error = 3, (obj.get("fatal") if _short(obj.get("fatal")) else "fatal")
        return pr
    for k, raw in sorted(obj["caps"].items()):
        if isinstance(k, str) and _KEY_RX.match(k):
            pr.caps[k], bad = _cap(raw)
            pr.unknown_reasons += bad
    pr.groups = {k: v for k, v in (obj.get("groups") or {}).items() if _short(k) and _short(v)} \
        if isinstance(obj.get("groups"), dict) else {}
    pr.budget_hit = obj.get("budget_hit") is True
    em = obj.get("elapsed_ms")
    pr.elapsed_ms = em if isinstance(em, int) and not isinstance(em, bool) else None
    pr.synthetic = obj.get("synthetic") is True
    pr.warnings = sorted({w for w in obj.get("warnings") or () if _short(w)})
    pr.stub_env = sorted({w for w in obj.get("stub_env") or () if _short(w)})
    cu = obj.get("cfg_used")
    pr.cfg_used = {k: v for k, v in cu.items() if _short(k) and isinstance(v, (int, float)) and not isinstance(v, bool)} \
        if isinstance(cu, dict) else {}
    pr.now_utc = obj.get("now_utc") if _short(obj.get("now_utc")) else None
    return pr


def probe_capabilities(paths, ident, cfg, *, run=None, only=None, test_now=None, env=None, team=True,
                       hello=None) -> ProbeResult:
    """계약 함수: 탐침 묶음 실행 → ``ProbeResult``. 측정은 잠금 없이(TAB §1.7). ``run(argv, timeout_s=, stdin=, env=)`` =
    자식 실행(기본 ``lm27.util.proc.run_child`` — 시험은 가짜), ``only`` = 묶음 이름 목록(``-Only``), ``test_now`` =
    스크립트 ``-TestNow``, ``team`` = P-TEAM 도 잴지, ``hello`` = ``lm27.team.client.hello`` 대체(시험)."""
    runner = run or proc.run_child
    timeout = float(cfg["probe.budgetSec"]) + SLACK_S
    line = fsx.canon_bytes(in_line(cfg)) + b"\n"
    try:
        r = runner(probe_argv(paths, ident, only=only, test_now=test_now), timeout_s=timeout, stdin=line, env=env)
    except OSError as e:
        pr = ProbeResult(rc=3, error="spawn_" + type(e).__name__)
    else:
        if getattr(r, "timed_out", False):
            pr = ProbeResult(rc=3, error="timeout")
        else:
            out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, (bytes, bytearray)) else str(r.stdout or "")
            obj = parse_probe(out)
            pr = _from_obj(obj) if obj is not None else ProbeResult(rc=3, error="no_output")
            if pr.rc == 0 and getattr(r, "rc", 0) not in (0, None):
                pr.warnings = sorted(set(pr.warnings) | {"probe_rc"})
    if team:
        pr.team = team_reach(cfg, hello=hello)
    return pr


def team_reach(cfg, *, hello=None) -> dict | None:
    """P-TEAM — 기본 주소의 ``/api/hello``(TAB §1.5 · §2.9). → ``{ok, status, reasons, value{target, result, ms}, sig}``.
    ``lm27.team.client`` 가 아직 없으면(W2 통합 전) None — 기록하지 않는다."""
    if hello is None:
        if importlib.util.find_spec("lm27.team.client") is None:
            return None
        from lm27.team.client import hello as _hello          # 지연 import(모듈 존재를 위에서 확인)
        hello = _hello
    base = "http://" + str(cfg["team.serverHost"]) + ":" + str(int(cfg["team.serverPort"]))
    t0 = time.monotonic()
    try:
        h = hello(base, cfg["team.connectTimeoutSec"])
    except (OSError, ValueError) as e:
        return {"ok": False, "status": "transport_fail", "reasons": [], "value": {"target": TEAM_TARGET,
                "result": "error", "error_type": type(e).__name__}, "sig": None}
    res = h.get("result") if isinstance(h, dict) else getattr(h, "result", None)
    res = res if isinstance(res, str) and (res == "ok" or res in REACH_REASON) else "http_error"
    ms = h.get("ms") if isinstance(h, dict) else getattr(h, "ms", None)
    if not isinstance(ms, int) or isinstance(ms, bool):
        ms = int((time.monotonic() - t0) * 1000)
    if res == "ok":
        return {"ok": True, "status": "ok", "reasons": [], "value": {"target": TEAM_TARGET, "result": res, "ms": ms},
                "sig": None}
    st = "transport_fail" if res in REACH_TRANSPORT else "fail"
    return {"ok": False, "status": st, "reasons": [REACH_REASON[res]],
            "value": {"target": TEAM_TARGET, "result": res, "ms": ms}, "sig": None}


# ── 기록 ────────────────────────────────────────────────────────────────────
def sampler_cap(cap: dict, agent: dict | None) -> dict:
    """``pc.sampler`` 탐침 값 ``{ps, py}`` + 에이전트 설치 결과(impl·impl_reasons) → 한 기록(WP-13·17 CR).
    설치 자기 시험이 정본이다: impl py·ps → 가능, none → 불가(R-CLM·R-APPLOCKER). 설치 정보가 없으면 탐침 그대로."""
    out = {"ok": cap.get("ok"), "status": cap.get("status") or "unknown", "reasons": list(cap.get("reasons") or ()),
           "value": dict(cap.get("value") or {}), "sig": cap.get("sig")}
    impl = (agent or {}).get("impl")
    if impl not in SAMPLER_IMPLS:
        return out
    out["value"]["impl"] = impl
    if impl == "none":
        why = [r for r in (agent or {}).get("impl_reasons") or () if r in ("R-CLM", "R-APPLOCKER")] or ["R-CLM"]
        out.update(ok=False, status="fail", reasons=sorted(set(out["reasons"]) | set(why)))
    else:
        out.update(ok=True, status="ok", reasons=[r for r in out["reasons"] if r not in ("R-CLM", "R-APPLOCKER")])
    return out


def _loc_sig(loc: dict) -> str:
    v = loc.get("value") if isinstance(loc.get("value"), dict) else {}
    facts = [v.get("drive_type"), v.get("onedrive"), v.get("redirected"), v.get("network"), v.get("writable")]
    return fsx.sha256_hex(fsx.canon_bytes(facts))[:12]


def record_probes(pcdir, pr, loc, *, cfg=None, today=None, agent=None) -> dict:
    """계약 함수: 탐침 결과 → pc.json ``capabilities``(``record_probe`` 로만 — 계약 §3.8). 반환 ``{키: 기록(verdict 포함)}``.
    ``loc`` = P-BUNDLE(``probe_bundle_location`` 결과, None 이면 건너뜀), ``agent`` = ``agent.json`` 의 impl·impl_reasons,
    ``today`` = 탐침 로컬 날짜(기본 오늘). 번들 잠금(``fg-write``·``collect-finish``)은 호출자가 쥔다."""
    from lm27.bundle import pcreg
    out = {}
    caps = dict(pr.caps) if pr is not None else {}
    if "pc.sampler" in caps:
        caps["pc.sampler"] = sampler_cap(caps["pc.sampler"], agent)
    if pr is not None and pr.team:
        caps["team_server_reach"] = pr.team
    if isinstance(loc, dict) and loc.get("status") in STATUSES:
        caps["bundle_location"] = {"ok": loc.get("ok"), "status": loc["status"],
                                   "reasons": [r for r in rcmap.norm_reasons(loc.get("reasons")) if rcmap.is_reason(r)],
                                   "value": _clean(loc.get("value")) if isinstance(loc.get("value"), dict) else {},
                                   "sig": _loc_sig(loc)}
    for key in sorted(caps):
        c = caps[key]
        out[key] = pcreg.record_probe(pcdir, key, c.get("ok"), c.get("value"), c.get("reasons") or [],
                                      c.get("status") or "unknown", probe_sig=c.get("sig"), date=today, cfg=cfg,
                                      today=today)
    return out
