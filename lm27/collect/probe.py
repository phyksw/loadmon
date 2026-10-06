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

  · P-OWA·P-WEB(``collect\probe_owa.py``·``probe_teamsweb.py`` — ``web=True``, 웹 경로를 도는 PC: 계약 §2.17 '모든 PC(V5)')
    과 P-CP(``collect\probe_copilot.py --no-roundtrip --no-lookup`` — ``copilot=True``, 클라우드PC)도 자식으로 띄워 같은
    ``lm27.probe/1`` 줄을 읽고 caps 를 합친다(``mail.owa``·``cal.owa``·``web_login``·``teams.web``·``copilot_env``·
    ``copilot_connector``·``*.copilot``). 같은 전용 Edge 프로필이라 차례로(V9). 웹 탐침은 로그인을 오래 기다리지 않는다
    (로그인 대기는 수집기가 [수집]마다 한 번 — V10). P-WEB·P-CP 는 P-OWA 가 로그인을 확인했을 때만(로그인 전이면 같은 결과).
    언제 돌릴지(하루 한 번 — 오늘 로그인된 기록이 이미 있으면 건너뜀)는 ``web_probe_due``·``copilot_probe_due``.

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
import sys
import time
from dataclasses import dataclass, field

from lm27.collect import rcmap
from lm27.util import fsx, proc

__all__ = [
    "CFG_KEYS", "COPILOT_PROBE", "PROBE_SCRIPT", "REACH_REASON", "SCHEMA", "WEB_PROBES", "ProbeResult",
    "copilot_probe_due", "in_line", "parse_probe", "powershell_exe", "probe_argv", "probe_capabilities", "py_probe_argv",
    "record_probes", "sampler_cap", "team_reach", "web_probe_due",
]

PROBE_SCRIPT = "Invoke-CapabilityProbe.ps1"
# 파이썬 탐침(계약 §6.7 · §2.17): (스크립트, 묶음 이름, 덧붙일 인자)
WEB_PROBES = (("probe_owa.py", "P-OWA", ()), ("probe_teamsweb.py", "P-WEB", ()))
COPILOT_PROBE = ("probe_copilot.py", "P-CP", ("--no-roundtrip", "--no-lookup"))   # 세션·환경만(질의 없음 — 조회는 수집 단계)
# P-CP 에서 합칠 caps — 조회 능력(``*.copilot``·``copilot_connector``)은 조회 단계가 ``lm27.bridge.capability`` 로 직접
# 남긴다(질의 없이 잰 'unknown' 을 날마다 덧쌓아 진짜 관찰을 이력 상한 밖으로 밀지 않게). 여기서는 환경만.
COPILOT_KEYS = ("copilot_env",)
PY_SLACK_S = 60                    # 파이썬 탐침: 예산 + Edge 기동(최대 20초)·세션 정리 여유
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


def py_probe_argv(paths, ident, script: str, budget_sec: int, *, python=None, extra=()) -> list:
    """파이썬 탐침 명령줄(``-X utf8 -I -B`` — 계약 §7.3 수집기와 같은 실행 플래그)."""
    exe = python or (str(paths.python_exe()) if os.path.isfile(paths.python_exe()) else sys.executable)
    return [exe, "-X", "utf8", "-I", "-B", str(paths.collect_script(script)), "--pc", ident.pc_id,
            "--budget-sec", str(int(budget_sec)), *extra]


def _run_py_probe(runner, argv, timeout, env, group: str) -> ProbeResult:
    """파이썬 탐침 하나 → ProbeResult(실패는 rc 3 + error — 합칠 caps 없음)."""
    try:
        r = runner(argv, timeout_s=timeout, stdin=None, env=env)
    except OSError as e:
        return ProbeResult(rc=3, error=f"{group}:spawn_{type(e).__name__}")
    if getattr(r, "timed_out", False):
        return ProbeResult(rc=3, error=f"{group}:timeout")
    out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, (bytes, bytearray)) else str(r.stdout or "")
    obj = parse_probe(out)
    if obj is None:
        return ProbeResult(rc=3, error=f"{group}:no_output")
    sub = _from_obj(obj)
    if sub.rc != 0:
        sub.error = f"{group}:{sub.error or 'fatal'}"
    return sub


def _merge(pr: ProbeResult, sub: ProbeResult, group: str, keys=None) -> None:
    """파이썬 탐침 결과를 본 결과에 합친다(``keys`` = 합칠 caps 키 — None 이면 전부). 탐침 자체 실패는 경고만(본 결과 rc 는
    PS 탐침 것 — 웹 탐침 실패로 [수집]의 probe 단계를 수송 실패로 만들지 않는다)."""
    if sub.rc != 0:
        pr.groups.setdefault(group, "error")
        pr.warnings = sorted(set(pr.warnings) | {str(sub.error or group + ":error")[:_VSTR_MAX]})
        return
    for k, c in sub.caps.items():
        if keys is None or k in keys:
            pr.caps.setdefault(k, c)
    pr.groups.update(sub.groups)
    pr.unknown_reasons += sub.unknown_reasons
    pr.budget_hit = pr.budget_hit or sub.budget_hit
    pr.warnings = sorted(set(pr.warnings) | set(sub.warnings))
    pr.stub_env = sorted(set(pr.stub_env) | set(sub.stub_env))
    pr.synthetic = pr.synthetic or sub.synthetic


def _web_login_ok(pr: ProbeResult) -> bool:
    return (pr.caps.get("web_login") or {}).get("status") == "ok"


def _today_ok(pc, key: str, today) -> bool:
    caps = (pc or {}).get("capabilities") if isinstance((pc or {}).get("capabilities"), dict) else {}
    ent = caps.get(key) if isinstance(caps.get(key), dict) else {}
    hist = ent.get("history") if isinstance(ent.get("history"), list) else []
    last = hist[-1] if hist and isinstance(hist[-1], dict) else {}
    day = today.isoformat() if hasattr(today, "isoformat") else str(today or "")
    return bool(day) and last.get("date") == day and last.get("status") == "ok"


def web_probe_due(pc, today) -> bool:
    """P-OWA·P-WEB 를 이번 [수집]에서 잴까 — 오늘 이미 웹 로그인 ``ok`` 를 잰 기록이 있으면 아니다(하루 한 번 — '서로 다른
    날' 확정 규칙(계약 §6.4)에는 하루 한 번이면 된다). 로그인 전·실패·미확인이면 [수집]마다 잰다(짧은 확인 — V18)."""
    return not _today_ok(pc, "web_login", today)


def copilot_probe_due(pc, today) -> bool:
    """P-CP 를 이번 [수집]에서 잴까 — 오늘 ``copilot_env`` 를 이미 ok 로 쟀으면 아니다."""
    return not _today_ok(pc, "copilot_env", today)


def probe_capabilities(paths, ident, cfg, *, run=None, only=None, test_now=None, env=None, team=True,
                       hello=None, web=False, copilot=False, python=None) -> ProbeResult:
    """계약 함수: 탐침 묶음 실행 → ``ProbeResult``. 측정은 잠금 없이(TAB §1.7). ``run(argv, timeout_s=, stdin=, env=)`` =
    자식 실행(기본 ``lm27.util.proc.run_child`` — 시험은 가짜), ``only`` = 묶음 이름 목록(``-Only``), ``test_now`` =
    스크립트 ``-TestNow``, ``team`` = P-TEAM 도 잴지, ``hello`` = ``lm27.team.client.hello`` 대체(시험),
    ``web`` = P-OWA(→ 로그인 확인되면 P-WEB) 도, ``copilot`` = P-CP 도(웹 탐침을 돌렸으면 로그인 확인 뒤에만),
    ``python`` = 파이썬 탐침을 띄울 python.exe(기본 동봉 파이썬)."""
    runner = run or proc.run_child
    budget = int(cfg["probe.budgetSec"])
    timeout = float(budget) + SLACK_S
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
    py_timeout = float(budget) + PY_SLACK_S
    if web:
        for i, (script, group, extra) in enumerate(WEB_PROBES):
            if i and not _web_login_ok(pr):
                pr.groups.setdefault(group, "skipped")          # 로그인 전 — 팀즈 웹도 같은 로그인이라 재지 않는다
                continue
            argv = py_probe_argv(paths, ident, script, budget, python=python, extra=extra)
            _merge(pr, _run_py_probe(runner, argv, py_timeout, env, group), group)
    if copilot:
        script, group, extra = COPILOT_PROBE
        if web and not _web_login_ok(pr):
            pr.groups.setdefault(group, "skipped")              # 로그인 전에 브리지 세션을 열면 로그인을 오래 기다린다
        else:
            argv = py_probe_argv(paths, ident, script, budget, python=python, extra=extra)
            _merge(pr, _run_py_probe(runner, argv, py_timeout, env, group), group, COPILOT_KEYS)
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
