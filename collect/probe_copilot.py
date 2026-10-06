# -*- coding: utf-8 -*-
r"""P-CP 능력 탐침(B §4.11 · §7.13 · §8.1 · §12.2 · 계약 §2.17 · §3.8 · §6.7 · v1.2 C18) — 클라우드PC 에서 Copilot 을 쓸 수
있는가를 잰다: 세션(Edge·정책·로그인)·계정 등급·업무 탭·웹 근거·조회 커넥터(메일·팀즈 — 2-strike 는 브리지 능력 기록)·보정
한도. ``lm27.bridge.probe(roundtrip=True, lookup=True)`` 를 부르는 얇은 어댑터다. 내용은 0바이트 — stdout 한 줄 JSON 에
숫자·열거·사유 코드만(답 글·제목·이름·계정 없음). 이 스크립트는 pc.json 을 쓰지 않는다 — 연결자 ``lm27.collect.probe`` 가
``record_probe`` 로 쓴다(계약 §3.8 '쓰기는 record_probe 하나로').

    "<PY>" -X utf8 -I -B collect\probe_copilot.py [--pc <pc_id>] [--no-roundtrip] [--no-lookup] [--budget-sec N]

출력 ``lm27.probe/1``(v1.2 C18 — ``Invoke-CapabilityProbe.ps1``·``probe_owa.py`` 와 같은 모양): ``{schema, now_utc,
elapsed_ms, budget_sec, budget_hit, synthetic, groups{"P-CP": done|skipped|budget|error}, warnings, stub_env, cfg_used,
caps{키: {ok, status, reasons, value, sig}}}`` — caps 키 ``copilot_connector``(하위 mail·teams·calendar 판정) ·
``copilot_env``(tier·work_toggle·work_mode·web_grounding·web_exposed·추천 경로·보정 날짜) · ``mail.copilot``·
``teams.copilot``·``cal.copilot``(조회 능력 상태). status ∈ ok·fail·transport_fail·unknown(``record_probe`` 의
history.status). 사유: Edge 없음 R-NOAPP · 원격 디버깅 정책 R-EDGEPOL · 로그인 R-LOGIN(사람 — 확정 안 함) · 커넥터 없음
R-NOCONN · 무라이선스 R-NOLIC(계정 단위 — 세 조회에 함께) · 그 밖 R-TRANSPORT('불가' 근거 아님). sig = 구조 사실(Edge·정책·
로그인·등급·업무 모드·웹 근거·조회 능력 상태)만의 해시 — 환경이 바뀌면 달라진다(verdict 판정 창). rc: 0 = 결과 출력 ·
3 = 탐침 자체 실패(그때도 한 줄을 낸다 — ``fatal`` 에 예외 유형만).

``bridge.mode=off`` 면 세션을 열지 않고 ``P-CP: skipped``. 시험 주입: ``LM_COPILOT_STUB``(브리지 스텁 전송 — synthetic) ·
``LM_NO_BROWSER=1``(Edge 를 띄우지 않음).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import hashlib
import json
import re
import time
from datetime import UTC, datetime

SCHEMA = "lm27.probe/1"
GROUP = "P-CP"
CAP_KEYS = ("cal.copilot", "copilot_connector", "copilot_env", "mail.copilot", "teams.copilot")
LOOKUPS = (("lookup_mail", "mail.copilot", "mail"), ("lookup_teams", "teams.copilot", "teams"),
           ("lookup_calendar", "cal.copilot", "calendar"))
STUB_VARS = ("LM_COPILOT_STUB", "LM_NO_BROWSER")
PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
R_NOAPP, R_EDGEPOL, R_LOGIN, R_TRANSPORT, R_NOLIC, R_NOCONN = (
    "R-NOAPP", "R-EDGEPOL", "R-LOGIN", "R-TRANSPORT", "R-NOLIC", "R-NOCONN")
VERDICT_OF = {"ok": "가능", "suspect": "불가(잠정)", "unavailable": "불가(확정)", "unknown": "미확인"}


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stub_env(environ) -> list:
    """설정된 시험 주입 변수 이름(값은 싣지 않는다 — 배포 PC 면 경고 재료)."""
    return sorted(k for k in STUB_VARS if str((environ or {}).get(k) or "").strip() not in ("", "0"))


def sig_of(parts) -> str:
    t = "|".join("~" if p is None else ("1" if p is True else "0" if p is False else str(p)) for p in parts)
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12]


def cap(status: str, reasons, value: dict, sig_parts) -> dict:
    ok = True if status == "ok" else (False if status in ("fail", "transport_fail") else None)
    return {"ok": ok, "status": status, "reasons": sorted(set(reasons)), "value": value, "sig": sig_of(sig_parts)}


def _session(checks: dict) -> tuple[str, list, str]:
    """세션 판정 → (status, 사유, 요약 코드). 로그인까지 됐으면 ok."""
    def code(cid):
        c = checks.get(cid) or {}
        return "" if c.get("ok") else str(c.get("code") or "")
    if (checks.get("login") or {}).get("ok"):
        return "ok", [], "ready"
    if code("edge") == "edge_not_found":
        return "fail", [R_NOAPP], "edge_not_found"
    if code("launch") == "policy_blocked" or code("policy") == "policy_blocked_suspect":
        return "fail", [R_EDGEPOL], "policy_blocked"
    if code("login") == "login_required":
        return "fail", [R_LOGIN], "login_required"
    return "transport_fail", [R_TRANSPORT], code("launch") or code("login") or "no_session"


def build_caps(res: dict, states: dict) -> tuple[dict, list]:
    """``lm27.bridge.probe`` 결과 + 조회 능력 상태 → (caps, warnings). ``states`` = {단계: {state, reasons, today}}
    (``today`` = 오늘 '조회 불가' 관찰이 있었는가)."""
    checks = {c.get("id"): c for c in res.get("checks") or () if isinstance(c, dict)}
    env = dict(res.get("env") or {}) if isinstance(res.get("env"), dict) else {}
    s_status, s_reasons, s_code = _session(checks)
    calib = (checks.get("calib") or {}).get("value") or None
    env_val = {k: env.get(k) for k in ("tier", "work_toggle", "work_mode", "web_grounding", "web_exposed")}
    env_val.update(recommend=str(res.get("recommend") or ""), calib_date=calib, session=s_code)
    env_sig = (s_code, env.get("tier"), env.get("work_toggle"), env.get("work_mode"), env.get("web_grounding"))
    env_reasons = list(s_reasons)
    if s_status == "ok" and env.get("tier") == "basic":
        env_reasons.append(R_NOLIC)
    caps = {"copilot_env": cap(s_status, env_reasons, env_val, env_sig)}
    sub, oks, fails, reasons_all = {}, 0, 0, set()
    for sid, src, short in LOOKUPS:
        st = states.get(sid) or {}
        state = st.get("state") if st.get("state") in VERDICT_OF else "unknown"
        rs = [r for r in st.get("reasons") or () if r in (R_NOLIC, R_NOCONN)]
        chk = checks.get(sid)
        if isinstance(chk, dict) and chk.get("ok"):
            status, reasons = "ok", []
        elif isinstance(chk, dict) and chk.get("code") == "unavailable":
            status, reasons = "fail", rs or [R_NOCONN]
        elif isinstance(chk, dict):
            status, reasons = "transport_fail", [R_TRANSPORT]
        elif st.get("today") and rs:
            status, reasons = "fail", rs                     # 오늘 다른 조회가 계정 단위 무라이선스를 보았다(R-NOLIC)
        else:
            status, reasons = "unknown", []
        oks += status == "ok"
        fails += status == "fail"
        reasons_all.update(reasons if status == "fail" else ())
        sub[short] = VERDICT_OF[state]
        caps[src] = cap(status, reasons, {"state": state, "verdict": VERDICT_OF[state]}, (src, s_code, state))
    conn = ("ok", []) if oks else (("fail", sorted(reasons_all)) if fails else ("unknown", []))
    caps["copilot_connector"] = cap(conn[0], conn[1], sub, (s_code,) + tuple(sorted(sub.items())))
    warnings = sorted({str(c.get("code")) for c in checks.values() if not c.get("ok") and c.get("code")})
    return dict(sorted(caps.items())), warnings


def default_probe(**kw) -> dict:
    import lm27.bridge as bridge
    return bridge.probe(**kw)


def capability_states(paths, settings) -> dict:
    """탐침 뒤의 조회 능력(``bridge_profile.capabilities`` — 상태·사유·오늘 관찰)."""
    from lm27.bridge.capability import Capabilities
    from lm27.bridge.clock import default_clock
    from lm27.bridge.session import BridgeProfile
    c = Capabilities(BridgeProfile(paths), settings, default_clock())
    return {sid: {"state": c.state(sid), "reasons": c.reasons(sid), "today": c.checked_today(sid)}
            for sid, _src, _s in LOOKUPS}


def probe(*, environ, paths, cfg, now, budget_sec: int, pc_id=None, roundtrip=True, lookup=True, probe_fn=None,
          states_fn=None, clock_mono=None) -> dict:
    """탐침 한 번 → ``lm27.probe/1`` dict."""
    from lm27.bridge import settings as BS
    mono = clock_mono or time.monotonic
    t0 = mono()
    settings = BS.from_cfg(cfg)
    out = {"schema": SCHEMA, "now_utc": utc_iso(now), "elapsed_ms": 0, "budget_sec": int(budget_sec),
           "budget_hit": False, "synthetic": bool(str(environ.get("LM_COPILOT_STUB") or "").strip()),
           "groups": {GROUP: "done"}, "warnings": [], "stub_env": stub_env(environ),
           "cfg_used": {"probe.budgetSec": int(budget_sec), "bridge.mode": settings.mode}, "caps": {}}
    if settings.mode == "off":
        out["groups"][GROUP] = "skipped"
        out["warnings"] = ["bridge_off"]
        return out
    rt_kw = {"raw_cfg": cfg}
    if pc_id:
        rt_kw["pc_id"] = pc_id
    res = (probe_fn or default_probe)(roundtrip=roundtrip, lookup=lookup, paths=paths, environ=environ, emit=None,
                                      rt_kw=rt_kw)
    states = (states_fn or capability_states)(paths, settings)
    out["caps"], out["warnings"] = build_caps(res if isinstance(res, dict) else {}, states)
    out["probe_rc"] = int(res.get("rc", 1)) if isinstance(res, dict) else 1
    el = mono() - t0
    out["elapsed_ms"] = int(el * 1000)
    if el > budget_sec:
        out["budget_hit"] = True
        out["groups"][GROUP] = "budget"
    return out


def main(argv=None, *, environ=None, paths=None, cfg=None, now=None, probe_fn=None, states_fn=None, out=None,
         err=None) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    environ = os.environ if environ is None else environ
    now = now or datetime.now(UTC)
    ap = argparse.ArgumentParser(prog="probe_copilot.py", description="P-CP 능력 탐침(숫자·열거·사유 코드만)")
    ap.add_argument("--pc", default="")
    ap.add_argument("--no-roundtrip", action="store_true", help="연결 확인 왕복을 하지 않는다")
    ap.add_argument("--no-lookup", action="store_true", help="조회 커넥터(메일·팀즈 1일)를 확인하지 않는다")
    ap.add_argument("--budget-sec", type=int, default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        a = None
    try:
        if a is None or (a.pc and not PC_ID_RX.match(a.pc)) or (a.budget_sec is not None and a.budget_sec < 1):
            raise ValueError("BadArguments")
        from lm27.util import events
        events.configure("off")                              # stdout 은 결과 한 줄만
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        try:
            budget = a.budget_sec if a.budget_sec is not None else int(cfg["probe.budgetSec"])
        except KeyError:
            budget = 60
        res = probe(environ=environ, paths=paths, cfg=cfg, now=now, budget_sec=budget, pc_id=a.pc or None,
                    roundtrip=not a.no_roundtrip, lookup=not a.no_lookup, probe_fn=probe_fn, states_fn=states_fn)
        rc = 0
    except Exception as e:  # noqa: BLE001 — 탐침 자체 실패(유형만, 원문 없음)
        res = {"schema": SCHEMA, "now_utc": utc_iso(now), "elapsed_ms": 0, "budget_sec": None, "budget_hit": False,
               "synthetic": False, "groups": {GROUP: "error"}, "warnings": [], "stub_env": stub_env(environ),
               "cfg_used": {}, "caps": {}, "fatal": "BadArguments" if str(e) == "BadArguments" else type(e).__name__}
        rc = 3
    summary = ", ".join(f"{k}={v.get('status')}" for k, v in sorted((res.get("caps") or {}).items()))
    try:
        err.write(f"[{GROUP}] {summary or '결과 없음'} · {(res.get('groups') or {}).get(GROUP)}\n")
        out.write(json.dumps(res, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        out.flush()
    except (OSError, ValueError):
        pass
    return rc


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        _r = getattr(_s, "reconfigure", None)
        if _r is not None:
            _r(encoding="utf-8", errors="replace")
    sys.exit(main())
