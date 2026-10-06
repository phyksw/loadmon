# -*- coding: utf-8 -*-
r"""P-OWA 능력 탐침(CM §14 · C §4 · 계약 §2.17 · §6.7 · v1.2 C18) — 백필 PC 에서 Outlook 웹을 쓸 수 있는가를 잰다.
내용은 0바이트: stdout 한 줄 JSON 에 숫자·열거·사유 코드만(제목·이름·주소·원 ID 없음). 디스크에 쓰지 않는다.

    "<PY>" -X utf8 -I -B collect\probe_owa.py [--pc <pc_id>] [--budget-sec N]

재는 것: 웹 로그인 상태(R-LOGIN · 조직 정책 조건부 액세스 AADSTS → R-CA — 장치 기반·외부 보안 과제는 사람이 풀 수 있어 R-LOGIN,
값 ``aadsts``·``aadsts_kind``), Edge 설치·원격 디버깅 정책(R-NOAPP · R-EDGEPOL — 정책
레지스트리 **읽기만**), 받은 편지함 목록의 최근 7일 항목 중 분 단위 시각이 보이는 비율, 행 키 종류(대화 보기 여부), 이번 주
주 보기를 알아보는가. Edge 는 ``lm27.bridge.session.EdgeSession.open(role="owa")`` 로만 연다(G-B12). 사용자 대신
로그인하지 않으며, 탐침은 로그인을 오래 기다리지 않는다(예산 ``probe.budgetSec`` 안).

출력 ``lm27.probe/1``(계약 v1.2 C18 — ``Invoke-CapabilityProbe.ps1`` 과 같은 모양, 연결자 ``lm27.collect.probe`` 가
``record_probe`` 로 pc.json 에 쓴다): ``{schema, now_utc, elapsed_ms, budget_sec, budget_hit, synthetic, groups{"P-OWA":
done|skipped|budget|error}, warnings, stub_env, cfg_used, caps{"mail.owa"|"cal.owa"|"web_login": {ok, status, reasons,
value, sig}}}``. status ∈ ok·fail·transport_fail·unknown(``record_probe`` 의 history.status). sig = 구조 사실(Edge·정책·
로그인·화면 구조)만의 해시 — 건수·비율이 바뀌어도 같고 환경이 바뀌면(로그인 완료·정책 변경) 달라진다(verdict 판정 창).
rc: 0 = 결과 출력 · 3 = 탐침 자체 실패(그때도 한 줄을 낸다 — fatal 에 예외 유형만).

시험 주입: ``LM_OWA_FAKE``(수집기와 같은 화면 응답 — synthetic) · ``LM_NO_BROWSER=1``(Edge 를 띄우지 않음 → P-OWA skipped).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta

from lm27.bridge.clock import INF, Deadline, default_clock


def _sibling(fname: str, modname: str):
    m = sys.modules.get(modname)
    if m is not None:
        return m
    spec = importlib.util.spec_from_file_location(modname, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                        fname))
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


W = _sibling("Get-OutlookWeb.py", "lm27_collect_owa_web")

SCHEMA = "lm27.probe/1"
GROUP = "P-OWA"
CAP_KEYS = ("mail.owa", "cal.owa", "web_login")
RECENT_DAYS = 7


def sig_of(parts) -> str:
    """구조 사실만의 해시(12자 16진)."""
    t = "|".join("~" if p is None else ("1" if p is True else "0" if p is False else str(p)) for p in parts)
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12]


def cap(status: str, reasons, value: dict, sig_parts) -> dict:
    ok = True if status == "ok" else (False if status in ("fail", "transport_fail") else None)
    return {"ok": ok, "status": status, "reasons": sorted(set(reasons)), "value": value, "sig": sig_of(sig_parts)}


def edge_facts(edge_info=None) -> dict:
    """Edge 설치·원격 디버깅 정책(레지스트리 읽기만 — 띄우지 않는다)."""
    if edge_info is None:
        from lm27.bridge.session import edge_info as _ei
        edge_info = _ei
    info = edge_info()
    state = "missing" if not info.path else ("blocked" if info.policy_blocked else "found")
    return {"edge": state, "edge_major": info.major or None, "policy_debug": info.policy_debug,
            "policy_devtools": info.policy_devtools}


def login_of(state: str) -> str:
    return {"ready": "ok", "login_required": "login", "ca": "ca"}.get(state, "unknown")


def login_value(screen, rc: int) -> dict:
    """로그인 필요일 때 값에 싣는 로그인 사실(v1.3 §0.8 V18 — 불리언·열거만): ``login_pending`` = 지난 대기가 로그인 없이 끝나
    짧게 확인만 함(연결자가 이 [수집]의 웹 경로를 Edge 없이 넘긴다), ``account`` = ``personal``(개인 계정 화면)."""
    if rc != W.RC_LOGIN:
        return {}
    fn = getattr(screen, "login_facts", None)
    f = fn() if callable(fn) else {}
    return {"login_pending": bool(f.get("login_pending")),
            "account": "personal" if f.get("login_account") == "personal" else ""}


def mail_sample(pages, today) -> dict:
    """받은 편지함 화면 → 최근 7일 항목 수·분 단위 비율·행 키 종류(숫자·열거만)."""
    n7 = m7 = 0
    kinds = {"c": 0, "i": 0}
    items = sel = 0
    for pg in pages:
        if pg.get("how") or pg.get("listboxes") or pg.get("search"):
            sel += 1
        for it in pg.get("items") or []:
            if not isinstance(it, dict):
                continue
            items += 1
            k = str(it.get("ck") or "")
            if k in kinds:
                kinds[k] += 1
            r = W.parse_mail_item(it, today - timedelta(days=60), today, "inbox", today)
            if not r or r.get("skip"):
                continue
            if (today - r["date"]).days < RECENT_DAYS:
                n7 += 1
                m7 += 1 if r.get("hm") else 0
    row_key = "convid" if kinds["c"] and kinds["c"] >= kinds["i"] else ("item" if kinds["i"] else "none")
    return {"items": items, "sample_7d": n7, "minute_ratio_7d": round(m7 / n7, 3) if n7 else None, "row_key": row_key,
            "sel_ok": bool(sel)}


def probe(*, environ, paths, cfg, clock, now, budget_sec, session_factory=None, edge_info=None, err=None) -> dict:
    t0 = clock.mono()
    dl = Deadline.after(clock, budget_sec) if budget_sec > 0 else Deadline(clock, INF)
    stub = W.stub_env(environ)
    out = {"schema": SCHEMA, "now_utc": W.utc_iso(now), "elapsed_ms": 0, "budget_sec": budget_sec, "budget_hit": False,
           "synthetic": False, "groups": {GROUP: "done"}, "warnings": ["stub_env_set"] if stub else [],
           "stub_env": stub, "cfg_used": {"probe.budgetSec": budget_sec}, "caps": {}}
    today = W.local_date_of(now, W.default_off)
    counts: dict = {}
    try:
        fake = W.load_fake(environ, W.FAKE_ENV)
    except W.FakeError:
        out["warnings"].append("fake_unreadable")
        out["groups"][GROUP] = "error"
        out["caps"] = {k: cap("unknown", [], {}, (k, "fake_unreadable")) for k in CAP_KEYS}
        return out
    if fake is not None:
        out["synthetic"] = True
        screen = W.FakeOwaScreen(fake, clock)
        ef = {"edge": "fake", "edge_major": None, "policy_debug": "unset", "policy_devtools": "unset"}
    elif str(environ.get(W.NO_BROWSER_ENV) or "").strip() not in ("", "0"):
        out["groups"][GROUP] = "skipped"
        out["caps"] = {k: cap("unknown", [], {"login": "unknown"}, (k, "no_browser")) for k in CAP_KEYS}
        return out
    else:
        ef = edge_facts(edge_info)
        if ef["edge"] != "found":
            why = "R-NOAPP" if ef["edge"] == "missing" else "R-EDGEPOL"
            val = {"login": "unknown", "edge": ef["edge"]}
            out["caps"] = {k: cap("fail", [why], val, (k, ef["edge"], ef["policy_debug"], ef["policy_devtools"]))
                           for k in CAP_KEYS}
            return out
        factory = session_factory or W.edge_session
        screen = W.CdpOwaScreen(factory(W.ROLE, W.tz.new_run_id(), paths=paths, clock=clock, environ=environ), clock,
                                counts)
    base = (ef["edge"], ef["policy_debug"], ef["policy_devtools"])
    try:
        state = screen.open(dl)
        if state == "ready" and not screen.synthetic:
            # 탐침은 로그인을 기다리지 않는다(첫 판정만 — 로그인 대기는 수집기가 [수집]마다 한 번, V10). 로그인 보류(V18)면
            # 세션이 그 판정을 짧은 확인으로 하고, 연결자는 이 값(login_pending)으로 웹 경로를 바로 넘긴다.
            state = screen.goto(W.OWA_BASE + dict(W.MAIL_FOLDERS)["inbox"], dl, W.OWA_HOST_RX, wait_login=False)
        login = login_of(state)
        if state != "ready":
            rc, why = W.session_failure(state, getattr(getattr(screen, "s", None), "error", None))
            st = "fail" if rc == W.RC_LOGIN or why in ("R-EDGEPOL", "R-NOAPP") else "transport_fail"
            val = {"login": login, "aadsts": counts.get("aadsts"), "aadsts_kind": counts.get("aadsts_kind"),
                   "edge": ef["edge"], **login_value(screen, rc)}
            out["caps"] = {k: cap(st, [why], val, (k, *base, login, counts.get("aadsts"))) for k in CAP_KEYS}
            return out
        pages = []
        if screen.synthetic:
            month = today.replace(day=1)
            pages = list(screen.mail_pages("inbox", month, today, dl))
        else:
            pages = [screen._wait_list(dl)]
        ms = mail_sample(pages, today)
        wk = today - timedelta(days=today.weekday())
        try:
            pg = screen.week(wk, dl)
        except W.ScreenStop as x:
            counts["week_stop"] = x.state
            pg = {}
        grid = bool(pg.get("grid") or pg.get("n"))
        out["budget_hit"] = dl.at != INF and dl.expired()
        if out["budget_hit"]:
            out["groups"][GROUP] = "budget"
        out["caps"]["web_login"] = cap("ok", [], {"login": "ok", "aadsts": None}, ("web_login", *base, "ok"))
        mval = {"login": "ok", "items": ms["items"], "sample_7d": ms["sample_7d"],
                "minute_ratio_7d": ms["minute_ratio_7d"], "row_key": ms["row_key"]}
        out["caps"]["mail.owa"] = cap("ok" if ms["sel_ok"] else "fail", [] if ms["sel_ok"] else ["R-WEBSEL"], mval,
                                      ("mail.owa", *base, "ok", ms["sel_ok"], ms["row_key"]))
        cval = {"login": "ok", "grid": grid, "events": int(pg.get("n") or len(pg.get("events") or []))}
        if counts.get("week_stop"):                        # 주 보기로 가다 세션이 끊김 — 화면 구조 탓(R-WEBSEL)이 아니다
            rc, why = W.session_failure(counts["week_stop"])
            out["caps"]["cal.owa"] = cap("fail" if rc == W.RC_LOGIN else "transport_fail", [why], cval,
                                         ("cal.owa", *base, counts["week_stop"]))
        else:
            out["caps"]["cal.owa"] = cap("ok" if grid else "fail", [] if grid else ["R-WEBSEL"], cval,
                                         ("cal.owa", *base, "ok", grid))
        return out
    except W.ScreenStop as x:
        rc, why = W.session_failure(x.state, x.info)
        st = "fail" if rc == W.RC_LOGIN else "transport_fail"
        val = {"login": login_of(x.state), **login_value(screen, rc)}
        out["caps"] = {k: cap(st, [why], val, (k, *base, x.state)) for k in CAP_KEYS}
        return out
    finally:
        screen.close()
        out["elapsed_ms"] = int((clock.mono() - t0) * 1000)


def main(argv=None, *, environ=None, paths=None, cfg=None, clock=None, now=None, session_factory=None, edge_info=None,
         out=None, err=None) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    environ = os.environ if environ is None else environ
    clock = clock or default_clock()
    now = now or datetime.now(UTC)
    ap = argparse.ArgumentParser(prog="probe_owa.py", description="P-OWA 능력 탐침(숫자·열거·사유 코드만)")
    ap.add_argument("--pc", default="")
    ap.add_argument("--budget-sec", type=int, default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        a = None
    res = None
    try:
        if a is None or (a.pc and not W.PC_ID_RX.match(a.pc)) or (a.budget_sec is not None and a.budget_sec < 1):
            raise ValueError("BadArguments")
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        budget = a.budget_sec if a.budget_sec is not None else int(W.cfg_get(cfg, "probe.budgetSec", 60) or 60)
        res = probe(environ=environ, paths=paths, cfg=cfg, clock=clock, now=now, budget_sec=budget,
                    session_factory=session_factory, edge_info=edge_info, err=err)
        rc = 0
    except Exception as e:                                   # noqa: BLE001 — 탐침 자체 실패(유형만, 원문 없음)
        res = {"schema": SCHEMA, "now_utc": W.utc_iso(now), "elapsed_ms": 0, "budget_sec": None, "budget_hit": False,
               "synthetic": False, "groups": {GROUP: "error"}, "warnings": [], "stub_env": W.stub_env(environ),
               "cfg_used": {}, "caps": {}, "fatal": type(e).__name__ if str(e) != "BadArguments" else "BadArguments"}
        rc = 3
    summary = ", ".join(f"{k}={v.get('status')}" for k, v in sorted((res.get("caps") or {}).items()))
    W.human(f"[P-OWA] {summary or '결과 없음'} · {(res.get('groups') or {}).get(GROUP)}", err)
    try:
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
