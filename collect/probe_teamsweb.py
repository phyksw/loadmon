# -*- coding: utf-8 -*-
r"""P-WEB 능력 탐침(CT §12 · C §4 · 계약 §2.17 · §6.7 · v1.2 C18) — 백필 PC 에서 Teams 웹을 쓸 수 있는가를 잰다.
내용은 0바이트: stdout 한 줄 JSON 에 숫자·열거·사유 코드만(방 이름·작성자·본문·원 ID 없음). 디스크에 쓰지 않는다.

    "<PY>" -X utf8 -I -B collect\probe_teamsweb.py [--pc <pc_id>] [--budget-sec N]

재는 것: Teams 웹(teams.microsoft.com — teams.cloud.microsoft 도착도 정상) 로그인 상태(R-LOGIN · 조직 정책 조건부 액세스 → R-CA,
장치 기반·외부 보안 과제는 R-LOGIN), Edge 설치·원격 디버깅 정책(R-NOAPP · R-EDGEPOL —
레지스트리 읽기만), 채팅 목록을 알아보는가(R-WEBSEL)·목록이 가상화되어 내려야 더 나오는가, 첫 대화 화면의 메시지 중
``data-mid``(메시지 ID)·``<time datetime>`` 이 보이는 비율(CT 미결 3 — 정밀 시각과 경로 간 중복 키가 한 번에 풀리는지).
Edge 는 ``lm27.bridge.session.EdgeSession.open(role="teams_web")`` 로만 연다(G-B12). 사용자 대신 로그인하지 않는다.

출력 ``lm27.probe/1``(``probe_owa.py`` 와 같은 모양): ``{schema, now_utc, elapsed_ms, budget_sec, budget_hit, synthetic,
groups{"P-WEB": done|skipped|budget|error}, warnings, stub_env, cfg_used, caps{"teams.web": {ok, status, reasons, value,
sig}}}``. sig = Edge·정책·로그인·화면 구조·ID/시각 노출 여부만의 해시(비율·건수 제외). rc: 0 = 결과 출력 · 3 = 탐침 자체 실패.

시험 주입: ``LM_TEAMSWEB_FAKE``(수집기와 같은 화면 응답 — synthetic) · ``LM_NO_BROWSER=1``(Edge 를 띄우지 않음 → skipped).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import importlib.util
import json
from datetime import UTC, datetime

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


T = _sibling("Get-TeamsWeb.py", "lm27_collect_teams_web")
P = _sibling("probe_owa.py", "lm27_collect_probe_owa")
W = T.W

SCHEMA = P.SCHEMA
GROUP = "P-WEB"
CAP = "teams.web"


def msg_sample(page: dict) -> dict:
    """대화 화면 한 장 → 메시지 수·ID 노출 비율·<time datetime> 노출 비율(숫자만)."""
    msgs = [x for x in (page or {}).get("items") or [] if isinstance(x, dict) and x.get("t") == "msg"]
    n = len(msgs)
    with_mid = sum(1 for m in msgs if str(m.get("mid") or "").strip())
    with_iso = sum(1 for m in msgs if any(T.parse_iso(v) for v in m.get("iso") or []))
    return {"sample_n": n, "mid_ratio": round(with_mid / n, 3) if n else None,
            "time_ratio": round(with_iso / n, 3) if n else None, "msg_sel_ok": bool((page or {}).get("how"))}


def probe(*, environ, paths, cfg, clock, now, budget_sec, session_factory=None, edge_info=None, err=None) -> dict:
    t0 = clock.mono()
    dl = Deadline.after(clock, budget_sec) if budget_sec > 0 else Deadline(clock, INF)
    stub = W.stub_env(environ)
    out = {"schema": SCHEMA, "now_utc": W.utc_iso(now), "elapsed_ms": 0, "budget_sec": budget_sec, "budget_hit": False,
           "synthetic": False, "groups": {GROUP: "done"}, "warnings": ["stub_env_set"] if stub else [],
           "stub_env": stub, "cfg_used": {"probe.budgetSec": budget_sec}, "caps": {}}
    counts: dict = {}
    try:
        fake = W.load_fake(environ, T.FAKE_ENV)
    except W.FakeError:
        out["warnings"].append("fake_unreadable")
        out["groups"][GROUP] = "error"
        out["caps"][CAP] = P.cap("unknown", [], {}, (CAP, "fake_unreadable"))
        return out
    if fake is not None:
        out["synthetic"] = True
        screen = T.FakeTeamsScreen(fake, clock)
        ef = {"edge": "fake", "policy_debug": "unset", "policy_devtools": "unset"}
    elif str(environ.get(W.NO_BROWSER_ENV) or "").strip() not in ("", "0"):
        out["groups"][GROUP] = "skipped"
        out["caps"][CAP] = P.cap("unknown", [], {"login": "unknown"}, (CAP, "no_browser"))
        return out
    else:
        ef = P.edge_facts(edge_info)
        if ef["edge"] != "found":
            why = "R-NOAPP" if ef["edge"] == "missing" else "R-EDGEPOL"
            out["caps"][CAP] = P.cap("fail", [why], {"login": "unknown", "edge": ef["edge"]},
                                     (CAP, ef["edge"], ef["policy_debug"], ef["policy_devtools"]))
            return out
        factory = session_factory or W.edge_session
        screen = T.CdpTeamsScreen(factory(T.ROLE, W.tz.new_run_id(), paths=paths, clock=clock, environ=environ),
                                  clock, counts)
        screen.wait_login = False                          # 탐침은 로그인을 기다리지 않는다(V10 — 대기는 수집기가)
    base = (ef["edge"], ef["policy_debug"], ef["policy_devtools"])
    try:
        state = screen.open(dl)
        login = P.login_of(state)
        if state != "ready":
            rc, why = W.session_failure(state, getattr(getattr(screen, "s", None), "error", None))
            st = "fail" if rc == W.RC_LOGIN or why in ("R-EDGEPOL", "R-NOAPP") else "transport_fail"
            out["caps"][CAP] = P.cap(st, [why], {"login": login, "aadsts": counts.get("aadsts"),
                                                 "aadsts_kind": counts.get("aadsts_kind"), "edge": ef["edge"],
                                                 **P.login_value(screen, rc)},
                                     (CAP, *base, login, counts.get("aadsts")))
            return out
        lp = screen.list_page("chats", dl) or {}
        items = [x for x in lp.get("items") or [] if isinstance(x, dict)]
        sel_ok = bool(lp.get("how"))
        virtualized = None
        ms = {"sample_n": 0, "mid_ratio": None, "time_ratio": None, "msg_sel_ok": False}
        opened = None
        if items:
            virtualized = screen.list_scroll("chats", dl) == "scrolled"
            # 앞 두 방까지(머리 항목 제외) — 앱이 처음부터 열어 둔 방은 눌러도 화면이 그대로라 확인되지 않을 수 있다(M8)
            cands = [x for x in items if not (x.get("hdr") and not x.get("tid"))][:2]
            opened = False
            for k, it in enumerate(cands):
                room = {"rid": f"probe:{k}", "idx": it.get("idx", k), "tid": str(it.get("tid") or ""), "mid": "",
                        "label": str(it.get("label") or ""), "source": "chats", "gone": bool(it.get("gone"))}
                if screen.open_room(room, dl) == "ok":
                    opened = True
                    ms = msg_sample(screen.room_page(room, dl))
                    break
        out["budget_hit"] = dl.at != INF and dl.expired()
        if out["budget_hit"]:
            out["groups"][GROUP] = "budget"
        value = {"login": "ok", "chats_n": len(items), "list_virtualized": virtualized, "room_opened": opened,
                 "sample_n": ms["sample_n"], "mid_ratio": ms["mid_ratio"], "time_ratio": ms["time_ratio"]}
        # 방을 열어 확인하지 못했으면(화면 전환 미확인) 메시지 화면 구조는 '모름' — R-WEBSEL(구조·확정) 근거로 쓰지 않는다
        ok = sel_ok and (ms["msg_sel_ok"] or not items or opened is False)
        sig = (CAP, *base, "ok", sel_ok, ms["msg_sel_ok"], bool(ms["mid_ratio"]), bool(ms["time_ratio"]),
               virtualized)
        out["caps"][CAP] = P.cap("ok" if ok else "fail", [] if ok else ["R-WEBSEL"], value, sig)
        return out
    except W.ScreenStop as x:
        rc, why = W.session_failure(x.state, x.info)
        st = "fail" if rc == W.RC_LOGIN else "transport_fail"
        out["caps"][CAP] = P.cap(st, [why], {"login": P.login_of(x.state), **P.login_value(screen, rc)},
                                 (CAP, *base, x.state))
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
    ap = argparse.ArgumentParser(prog="probe_teamsweb.py", description="P-WEB 능력 탐침(숫자·열거·사유 코드만)")
    ap.add_argument("--pc", default="")
    ap.add_argument("--budget-sec", type=int, default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        if e.code in (0, None):
            return 0
        a = None
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
    c = (res.get("caps") or {}).get(CAP) or {}
    W.human(f"[P-WEB] {CAP}={c.get('status')} · {(res.get('groups') or {}).get(GROUP)}", err)
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
