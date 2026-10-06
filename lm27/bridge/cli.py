# -*- coding: utf-8 -*-
r"""브리지 명령(B §12.1) — ``lm27 bridge <명령>`` · ``python\python.exe tools\bridge.py <명령>`` 의 본체.

| 명령 | 하는 일 | 종료 코드 |
|---|---|---|
| ``run --run-id <id> --stages a,b [--mode auto|manual]`` | 단계 실행(B §7.16) | 단계 rc 최악값(1 > 2 > 0) |
| ``probe [--no-roundtrip] [--lookup]`` | 연결 진단(B §12.2) | 0 정상 · 2 제한적(수동 권장·경고) · 1 경로 없음 |
| ``calibrate [--force] [--model fast|deep]`` | 입출력 한도 보정(B §7.14) | 0 · 1 |
| ``diagnose [--model]`` | 화면 구조 덤프(B §12.4, 형식 보존 마스킹) | 0 · 1 |
| ``manual-export [--stages a,b]`` | 수동 묶음 내보내기 | 0 내보낼 것 없음 · 2 대기 생김 |
| ``manual-import [--file <경로>|--clipboard]`` | 답 반입(B §10.4) | 0 · 2 남은 묶음 · 1 반입 0 |
| ``replay --run-id <id> --stage <s> --seq <n>`` | 개발용: 저널의 질의를 입력 재료로 다시 조립해 1회 보냄 | 0 · 1 |
| ``unlock`` | 죽은 잠금 정리(살아 있는 소유자는 건드리지 않음) | 0 · 1 |

결과는 표준 출력 JSON 한 건(``--events jsonl`` 이면 이벤트 줄 + 마지막 ``result`` 이벤트), 사람용 요약은 표준 오류.
``lm27 bridge …`` 로 부를 때는 ``lm27.cli`` 가 ``--job``·``--events`` 를 소비하고 나머지만 넘긴다. ``tools\bridge.py`` 로 바로
부르면 여기서 그 둘을 받아 ``events.configure`` 하고 끝에 ``run_end`` 를 낸다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta

from lm27.bridge import fsio
from lm27.bridge.stages import base as B

RUN_ID_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
JOB_RX = re.compile(r"^j\d{14}[0-9a-f]{4}$")
STAGE_RX = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
REQUIRED_CHECKS = ("edge", "launch", "tab", "identity", "login", "account", "roundtrip")
LIST_PROBE_MODEL = "목록확인용모델"            # 없는 이름으로 메뉴를 열어 항목만 읽는다(진단)


class CliError(Exception):
    def __init__(self, msg: str, rc: int = 1):
        super().__init__(msg)
        self.msg, self.rc = msg, rc


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("인자 오류: " + message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="bridge", description="LM27 코파일럿 브리지")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="단계 실행")
    r.add_argument("--run-id", dest="run_id")
    r.add_argument("--stages", required=True)
    r.add_argument("--mode", choices=("auto", "manual"))
    pr = sub.add_parser("probe", help="연결 진단")
    pr.add_argument("--no-roundtrip", dest="no_roundtrip", action="store_true")
    pr.add_argument("--lookup", action="store_true")
    c = sub.add_parser("calibrate", help="입출력 한도 보정")
    c.add_argument("--force", action="store_true")
    c.add_argument("--model", choices=("fast", "deep"), default="fast")
    d = sub.add_parser("diagnose", help="화면 구조 덤프")
    d.add_argument("--model", action="store_true")
    me = sub.add_parser("manual-export", help="수동 묶음 내보내기")
    me.add_argument("--stages")
    mi = sub.add_parser("manual-import", help="답 반입")
    g = mi.add_mutually_exclusive_group()
    g.add_argument("--file")
    g.add_argument("--clipboard", action="store_true")
    rp = sub.add_parser("replay", help="개발용 재전송")
    rp.add_argument("--run-id", dest="run_id", required=True)
    rp.add_argument("--stage", required=True)
    rp.add_argument("--seq", type=int, required=True)
    sub.add_parser("unlock", help="죽은 잠금 정리")
    return p


def _stage_list(s) -> list:
    out = [x.strip() for x in str(s or "").split(",") if x.strip()]
    for x in out:
        if not STAGE_RX.match(x):
            raise CliError(f"단계 이름 형식이 아닙니다: {x[:40]}")
    return out


def _say(text: str) -> None:
    if sys.stderr is not None:
        try:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass


def _out(name: str, obj: dict) -> None:
    from lm27.util import events
    if events.mode() == "jsonl":
        events.emit("result", cmd=name, result=obj)
        return
    if sys.stdout is not None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
        sys.stdout.flush()


# ───────────────────────── run · manual-export ─────────────────────────
def _summary(results: dict) -> dict:
    return {sid: {k: r.get(k) for k in ("state", "rc", "items_total", "items_ok", "items_pending", "items_failed",
                                        "stop_kind", "reason")} for sid, r in results.items() if r}


def cmd_run(a, env) -> int:
    from lm27.bridge import runner
    from lm27.util.tz import new_run_id
    if a.run_id is not None and not RUN_ID_RX.match(a.run_id):
        raise CliError("--run-id 형식이 아닙니다(YYYYMMDD-HHMMSS-xxxx)")
    try:
        specs = runner.resolve_specs(_stage_list(a.stages))
    except LookupError as e:
        raise CliError(str(e)) from None
    run_id = a.run_id or new_run_id()
    rt = runner.open_runtime(env.get("paths"), run_id, mode=a.mode, calibrate_model=specs[0].model_class if specs
                             else None, **env.get("rt_kw", {}))
    try:
        table = {s.id: s for s in specs}
        runner.inbox_import(rt, table)
        results = runner.run_stages(rt, specs)
    finally:
        runner.close_runtime(rt)
    rc = runner.worst_rc(results)
    _out("run", {"run_id": run_id, "rc": rc, "stages": _summary(results)})
    for sid, r in results.items():
        _say(f"[브리지] {sid}: {r.get('state')} (항목 {r.get('items_ok')}/{r.get('items_total')})")
    return rc


def cmd_manual_export(a, env) -> int:
    from lm27.bridge import runner
    from lm27.util.tz import new_run_id
    try:
        specs = runner.resolve_specs(_stage_list(a.stages) if a.stages else None)
    except LookupError as e:
        raise CliError(str(e)) from None
    run_id = new_run_id()
    rt = runner.open_runtime(env.get("paths"), run_id, mode="manual", **env.get("rt_kw", {}))
    try:
        results = runner.run_stages(rt, specs)
        k = rt.transport.open_count() if getattr(rt.transport, "kind", "") == "manual" else 0
    finally:
        runner.close_runtime(rt)
    worst = runner.worst_rc(results)
    rc = 1 if worst == 1 else (2 if k > 0 else 0)
    _out("manual-export", {"run_id": run_id, "rc": rc, "open": k, "stages": _summary(results)})
    _say(f"[브리지] 수동 묶음 {k}개 대기")
    return rc


def cmd_manual_import(a, env) -> int:
    from lm27.bridge import manual, runner
    from lm27.util.tz import new_run_id
    text = None
    if a.file:
        text = fsio.read_text(a.file)
        if text is None:
            raise CliError("답 파일을 읽지 못했습니다")
    elif a.clipboard:
        text = manual.read_clipboard()
    try:
        table = {s.id: s for s in runner.resolve_specs(None)}
    except LookupError as e:
        raise CliError(str(e)) from None
    rt = runner.open_runtime(env.get("paths"), new_run_id(), mode="manual", **env.get("rt_kw", {}))
    try:
        reps = runner.inbox_import(rt, table)
        if text is not None:
            reps.append(runner.manual_import(text, rt=rt, specs=table))
    finally:
        runner.close_runtime(rt)
    if not reps:
        _out("manual-import", {"rc": 1, "error": "no_input"})
        return 1
    if all(r.get("rc", 1) == 1 for r in reps):
        rc = 1                                                        # 반입 0
    else:
        rc = 2 if reps[-1].get("open", 0) > 0 else 0                  # 남은 묶음이 있으면 2
    _out("manual-import", {"rc": rc, "reports": reps})
    return rc


# ───────────────────────── calibrate · diagnose · unlock ─────────────────────────
def cmd_calibrate(a, env) -> int:
    from lm27.bridge import calibrate as CAL
    from lm27.bridge import runner
    rt = runner.open_runtime(env.get("paths"), None, mode="auto", **env.get("rt_kw", {}))
    try:
        if getattr(rt.transport, "kind", "") != "cdp":
            _out("calibrate", {"rc": 1, "error": "no_cdp"})
            return 1
        entry = CAL.run_calibration(rt, model_class=a.model, force=a.force)
        if entry is None and not a.force:
            cur = CAL.current(rt.profile.load(), rt.profile_id, rt.cfg.model_for(a.model), rt.edge_major, rt.cfg,
                              rt.clock)
            if cur is not None:
                _out("calibrate", {"rc": 0, "skipped": "valid", "calibration": cur})
                return 0
    finally:
        runner.close_runtime(rt)
    _out("calibrate", {"rc": 0 if entry else 1, "calibration": entry})
    return 0 if entry else 1


def _session(env, run_id: str):
    from lm27.bridge import settings as S
    from lm27.bridge.session import EdgeSession
    from lm27.paths import Paths
    mk = env.get("session_factory")
    if mk is not None:
        return mk()
    paths = env.get("paths") or Paths()
    return EdgeSession.open("bridge", run_id, paths=paths, cfg=S.load_settings(paths))


def cmd_diagnose(a, env) -> int:
    from lm27.util.tz import new_run_id
    s = _session(env, new_run_id())
    out = {"rc": 1, "state": "", "file": None}
    try:
        out["state"] = s.start()
        if s.cdp is not None:
            out["file"] = s.dump_diagnose()
            if a.model:
                note = s.select_model(LIST_PROBE_MODEL)
                out["model_menu"] = list(note.menu_seen)
        out["rc"] = 0 if out["file"] else 1
    finally:
        s.close()
    _out("diagnose", out)
    return out["rc"]


def cmd_unlock(a, env) -> int:
    from lm27.bridge.clock import default_clock
    from lm27.bridge.session import SessionLock
    from lm27.paths import Paths
    paths = env.get("paths") or Paths()
    lock = SessionLock(paths, env.get("clock") or default_clock(), role="bridge", run_id="unlock",
                       **({"proc_probe": env["proc_probe"]} if env.get("proc_probe") else {}))
    cur = fsio.read_json(lock.path, None)
    if cur is None:
        _out("unlock", {"rc": 0, "lock": "none"})
        return 0
    if lock.is_stale(cur):
        fsio.move_aside(lock.path, str(lock.path) + ".stale")
        _out("unlock", {"rc": 0, "lock": "removed"})
        return 0
    _out("unlock", {"rc": 1, "lock": "busy", "owner_role": str(cur.get("role") or "")})
    _say("[브리지] 잠금을 쥔 프로세스가 살아 있어 건드리지 않았습니다")
    return 1


# ───────────────────────── replay ─────────────────────────
def cmd_replay(a, env) -> int:
    import hashlib

    from lm27.bridge import exchange as X
    from lm27.bridge import journal as J
    from lm27.bridge import runner
    from lm27.bridge.transport import SendRequest
    if not RUN_ID_RX.match(a.run_id) or not STAGE_RX.match(a.stage):
        raise CliError("--run-id·--stage 형식이 아닙니다")
    try:
        spec = runner.resolve_specs([a.stage])[0]
    except LookupError as e:
        raise CliError(str(e)) from None
    rt = runner.open_runtime(env.get("paths"), a.run_id, **env.get("rt_kw", {}))
    try:
        block = runner.send_block(rt)                  # 로그인 보류·회사 계정 미확인이면 업무 자료를 다시 보내지 않는다(H4)
        if block:
            _out("replay", {"rc": 1, "error": block})
            return 1
        req = next((r for r in J.read_journal(rt.paths, a.run_id, a.stage) if r.get("t") == "req"
                    and int(r.get("seq") or -1) == a.seq), None)
        if req is None:
            raise CliError("저널에 그 질의가 없습니다")
        items, _d = runner.load_ai_in(rt.paths, spec)
        by_key = {it.key: it for it in items}
        batch = [by_key[i["key"]] for i in req.get("items") or [] if i.get("key") in by_key]
        if not batch:
            raise CliError("입력 재료(ai_in)에 그 항목이 없습니다")
        ctx = runner._stage_ctx(spec, rt, rt.cfg.answer_max_chars)
        old = X.assemble(spec, batch, ctx, str(req.get("rid") or "R22222"))
        same = hashlib.sha256(old.text.encode("utf-8")).hexdigest() == req.get("prompt_sha256")
        if not same:
            _say("[경고] 입력이 바뀌어 프롬프트가 저널과 다릅니다 — 그대로 보냅니다")
        sg = rt.gate_base.for_stage(spec.id, web_exposed=runner._web(rt)) if rt.gate_base is not None else None
        rid = X.new_rid(rt.used_rids, sg.rid_ok if sg is not None else None)
        asm = X.assemble(spec, batch, ctx, rid)
        if sg is not None and not sg.prompt(asm.text)[0]:
            _out("replay", {"rc": 1, "error": "gate_blocked"})
            return 1
        reply, first = rt.cfg.rung_timeouts(0)
        res = rt.transport.roundtrip(SendRequest(rid, asm.text, True, rt.cfg.model_for(spec.model_class), reply, first,
                                                 rt.clock.mono() + rt.cfg.roundtrip_max_sec, spec.id,
                                                 bool(spec.want_work_mode), item_keys=tuple(i.key for i in batch)))
        status, info = X.classify(spec, res, asm, ctx, None)
    finally:
        runner.close_runtime(rt)
    rc = 0 if status in ("ok", "partial") else 1
    _out("replay", {"rc": rc, "status": status, "same_prompt": same, "ok": len(info["answers"])})
    return rc


# ───────────────────────── probe(B §12.2) ─────────────────────────
class ProbeStage(B.StageSpec):
    """연결 확인 질의(B §12.3 글자 그대로) — 단어 2개를 그대로 돌려받는다."""
    id = "probe"
    title_ko = "연결 확인"
    prompt_ver = "probe/1.0"
    kind = "items"
    chat_policy = "fresh_each"
    max_items = 2
    send_fields = ("w",)
    text_fields = ("w",)
    item_schema = (B.F("w", "str", max_len=20),)
    stub = {"w": "사과"}

    def header(self, ctx, compact=False):
        return "연결 확인입니다. 각 항목의 단어를 그대로 돌려주세요."

    def columns(self):
        return "[항목] 번호 | 단어"

    def format_line(self):
        return '{"rid": <요청번호>, "n": 2, "items": [ {"id": <번호>, "w": <단어>} ]}'

    def unknown_rule(self):
        return "단어를 그대로 씁니다"

    def fallback(self, it, ctx, why):
        return {"w": it.fields.get("w", "")}


PROBE_WORDS = ("사과", "바다")


def do_probe(env, *, roundtrip: bool = True, lookup: bool = False) -> dict:
    """연결 진단 → 결과 dict(``probe_last.json`` 에도). 조회(``--lookup``)는 어제 하루를 조회 단계로 1회."""
    from lm27.bridge import calibrate as CAL
    from lm27.bridge import exchange as X
    from lm27.bridge import runner
    from lm27.bridge.clock import iso_now
    from lm27.bridge.transport import CdpTransport, SendRequest
    from lm27.util import events
    from lm27.util.tz import new_run_id
    emit = env.get("emit", events.emit)
    checks = []

    def add(cid, ok, value="", code="", hint=""):
        checks.append({"id": cid, "ok": bool(ok), "value": value, "code": code, "hint": hint})
        if emit is not None:
            emit("check", id=cid, ok=bool(ok))
    run_id = new_run_id()
    environ = env.get("environ")
    if environ is None:
        import os
        environ = os.environ
    stub = any(str(environ.get(k) or "").strip() not in ("", "0") for k in ("LM_COPILOT_STUB", "LM_NO_BROWSER"))
    add("stub_env", not stub, code="stub_env_set" if stub else "")
    rt_kw = dict(env.get("rt_kw", {}))
    rt_kw.setdefault("check_chat", False)              # 연결 진단은 '채팅 차단' 기록과 무관하게 늘 다시 본다(M5)
    rt = runner.open_runtime(env.get("paths"), run_id, mode="auto", environ=environ, heartbeat=False, **rt_kw)
    # 정책 차단 등으로 수동 경로로 바뀌었어도 진단은 그 직전 세션(Edge·정책·단계)을 읽는다(M4 — 'Edge 없음' 오진 방지)
    sess = getattr(rt.transport, "s", None) or getattr(rt, "prev_session", None)
    try:
        st = getattr(sess, "state", "") if sess is not None else getattr(rt.transport, "kind", "")
        ed = getattr(sess, "edge", None)
        info = getattr(sess, "info", None)
        add("edge", bool(ed and ed.path), getattr(ed, "version", ""), "" if ed and ed.path else "edge_not_found")
        blocked = bool(ed and ed.policy_blocked)
        udd = getattr(ed, "policy_user_data_dir", "unset") == "forced"
        add("policy", not (blocked or udd), getattr(ed, "policies", dict)() if ed is not None else {},
            "policy_blocked_suspect" if blocked else ("user_data_dir_forced" if udd else ""))
        add("lock", st != "lock_busy", code="lock_busy" if st == "lock_busy" else "")
        add("port", bool(info and info.port), str(getattr(info, "port", "") or ""),
            "" if info and info.port else "port_exhausted")
        bad_launch = st in ("launch_failed", "policy_blocked", "edge_not_found", "profile_busy")
        add("launch", not bad_launch and sess is not None and sess.cdp is not None, code=st if bad_launch else "")
        add("origin", True, getattr(info, "origin_mode", ""), "origin_explicit"
            if getattr(info, "origin_mode", "") == "explicit" else "")
        add("tab", bool(info and info.target_id), code="" if info and info.target_id else "tab_lost")
        ident = getattr(info, "identity", "")
        add("identity", st == "ready" and ident in ("strong", "weak"), ident,
            "weak_identity" if ident == "weak" else ("" if st == "ready" else (st or "no_input")),
            "BR-INPUT" if st == "input_not_found" else "")
        add("login", st == "ready", code="" if st == "ready" else ("login_required" if st == "login_required" else st))
        wm = getattr(info, "work_mode", "unknown")
        add("work_mode", wm in ("work", "unknown"), wm, "web_mode" if wm == "web" else "")
        envv = rt.env
        tier = getattr(envv, "tier", "unknown")
        add("tier", tier == "premium", tier, "basic" if tier == "basic" else ("" if tier == "premium" else "unknown"))
        wg = getattr(envv, "web_grounding", "unknown")
        add("web_grounding", wg == "off", wg, "web_on" if wg == "on" else ("wg_missing" if wg == "unknown" else ""))
        wx = bool(getattr(envv, "web_exposed", True))
        add("web_exposed", not wx, wx, "web_exposed" if wx else "")
        acct = getattr(envv, "account", "unknown") if st == "ready" else ""
        # 회사(Entra) 계정 확인(H4) — 아니면 분석 단계는 보내지 않는다. 아래 시험 낱말 왕복은 계정과 무관하게 한다(화면 조작 확인)
        add("account", acct == "work", acct, "" if acct == "work" else
            ("personal_account" if acct == "personal" else ("account_unknown" if st == "ready" else (st or "no_session"))))
        ready = st == "ready" and isinstance(rt.transport, CdpTransport)
        if ready:
            nf = sess.select_model(rt.cfg.model_fast)
            nd = sess.select_model(rt.cfg.model_deep)
            ok_m = (nf.ok or not rt.cfg.model_fast) and (nd.ok or not rt.cfg.model_deep)
            add("model", ok_m, nf.picked or "", "" if ok_m else ("model_item_missing" if nf.menu_seen or nd.menu_seen
                                                                 else "model_menu_missing"))
        if roundtrip and ready:
            spec = ProbeStage()
            ctx = B.StageCtx(run_id=run_id, env=rt.env, cfg=rt.cfg, clock=rt.clock)
            batch = [runner.WorkItem(key=f"probe:{i}", group="", fields={"w": w}, rule={}, ck="")
                     for i, w in enumerate(PROBE_WORDS, 1)]
            psg = rt.gate_base.for_stage(spec.id, web_exposed=True) if rt.gate_base is not None else None
            rid = X.new_rid(rt.used_rids, psg.rid_ok if psg is not None else None)
            asm = X.assemble(spec, batch, ctx, rid)
            reply, first = rt.cfg.rung_timeouts(0)
            res = rt.transport.roundtrip(SendRequest(rid, asm.text, True, rt.cfg.model_fast, reply, first,
                                                     rt.clock.mono() + rt.cfg.roundtrip_max_sec, spec.id, False))
            status, inf = X.classify(spec, res, asm, ctx, None)
            words_ok = status == "ok" and [inf["answers"][i].get("w") for i in sorted(inf["answers"])] == \
                list(PROBE_WORDS)
            add("roundtrip", words_ok and res.done_by == "pledge", f"{status}/{res.done_by}",
                "" if words_ok and res.done_by == "pledge" else status)
            add("busy", bool(res.busy_seen), code="" if res.busy_seen else "busy_unseen",
                hint="" if res.busy_seen else "BR-PROBE-BUSY")
            add("dom", res.pick == "dom", res.pick, "" if res.pick == "dom" else "anchor_fallback")
        elif not roundtrip:
            add("roundtrip", True, "skipped")
        else:
            add("roundtrip", False, code=st or "no_session")
        cal = CAL.current(rt.profile.load(), rt.profile_id, rt.cfg.model_fast, rt.edge_major, rt.cfg, rt.clock)
        add("calib", cal is not None, (cal or {}).get("date", ""), "" if cal else "calib_none")
        if lookup and ready and acct == "work":
            _probe_lookup(rt, add)                     # 조회는 회사 계정에서만(개인 계정이면 능력 기록도 하지 않는다)
        elif lookup and ready:
            for sid in ("lookup_mail", "lookup_teams"):
                add(sid, False, code="personal_account" if acct == "personal" else "account_unknown")
    finally:
        runner.close_runtime(rt)
    by = {c["id"]: c for c in checks}
    blocked_codes = {by["launch"]["code"], by["edge"]["code"]} & {"policy_blocked", "edge_not_found"}
    if all(by.get(k, {}).get("ok") for k in REQUIRED_CHECKS):
        recommend = "auto"
    elif blocked_codes:
        recommend = "manual"
    else:
        recommend = "none"
    warn = any(not c["ok"] for c in checks if c["id"] not in REQUIRED_CHECKS)
    out = {"ok": recommend == "auto", "recommend": recommend, "sec": round(rt.clock.mono(), 1),
           "env": rt.env.brief() if rt.env is not None and hasattr(rt.env, "brief") else {}, "checks": checks,
           "rc": 0 if recommend == "auto" and not warn else (2 if recommend in ("auto", "manual") else 1)}
    try:
        fsio.write_atomic(fsio.bridge_file(rt.paths, "probe_last"), out)

        def put(d):
            d.setdefault("health", {})["last_probe"] = iso_now(rt.clock)
        rt.profile.update(put)
    except OSError:
        pass
    return out


def _probe_lookup(rt, add) -> None:
    """``--lookup``: 어제 하루를 조회 단계마다 1회(저장소에 커밋하지 않는다 — 능력 관찰만)."""
    from lm27.bridge import exchange as X
    from lm27.bridge import runner
    from lm27.bridge.clock import today
    yday = (date.fromisoformat(today(rt.clock)) - timedelta(days=1)).isoformat()
    for sid in ("lookup_mail", "lookup_teams"):
        try:
            spec = runner.resolve_specs([sid])[0]
        except LookupError:
            add(sid, False, code="stage_missing")
            continue
        ctx = runner._stage_ctx(spec, rt, rt.cfg.answer_max_chars)
        fields = {k: v for k, v in {"d0": yday, "d1": yday}.items() if k in spec.send_fields}
        it = runner.WorkItem(key=f"{sid}:{yday}:{yday}", group="", fields=fields, rule={}, ck="")
        sg = rt.gate_base.for_stage(sid, web_exposed=runner._web(rt)) if rt.gate_base is not None else None
        ac = X.AskCtx(cfg=rt.cfg, clock=rt.clock, transport=rt.transport, gate=sg, used_rids=rt.used_rids,
                      stage_ctx=ctx, web_exposed=runner._web(rt), run_id=rt.run_id)
        ar = X.ask(spec, [it], ac)
        if ar.status in ("ok", "partial", "truncated"):
            rt.caps.observe_ok(sid)
            add(sid, True, ar.status)
        elif ar.status == "refusal" and ar.reason == "unavailable":
            rt.caps.observe_unavailable(sid, "R-NOLIC" if ar.lic == "nolic" else "R-NOCONN")
            add(sid, False, code="unavailable")
        else:
            add(sid, False, code=ar.status)
    runner._recompute_env(rt)
    runner.finish(rt, {"lookup_mail": {}, "lookup_teams": {}})


def cmd_probe(a, env) -> int:
    out = do_probe(env, roundtrip=not a.no_roundtrip, lookup=a.lookup)
    _out("probe", out)
    _say(f"[브리지] 진단: 권장 {out['recommend']}")
    return int(out["rc"])


COMMANDS = {"run": cmd_run, "probe": cmd_probe, "calibrate": cmd_calibrate, "diagnose": cmd_diagnose,
            "manual-export": cmd_manual_export, "manual-import": cmd_manual_import, "replay": cmd_replay,
            "unlock": cmd_unlock}


def _take_events(argv: list) -> tuple[list, str | None, str | None]:
    rest, job, ev, i = [], None, None, 0
    while i < len(argv):
        t = argv[i]
        if t in ("--job", "--events") and i + 1 < len(argv):
            if t == "--job":
                job = argv[i + 1]
            else:
                ev = argv[i + 1]
            i += 2
            continue
        rest.append(t)
        i += 1
    return rest, job, ev


def main(argv=None, **env) -> int:
    """명령 실행 → rc. ``env`` = 시험 주입(paths·session_factory·rt_kw·clock·proc_probe·environ·emit)."""
    from lm27.util import events
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, job, ev = _take_events(argv)
    own_events = ev is not None or job is not None
    if own_events:
        if ev not in (None, "jsonl", "text") or (job is not None and not JOB_RX.match(job)):
            _say("인자 오류: --events 는 jsonl·text, --job 은 j + 14자리 시각 + 4hex")
            return 1
        events.configure(mode=ev or "text", job=job)
    rc = 1
    try:
        a = build_parser().parse_args(argv)
        fn = COMMANDS.get(a.cmd or "")
        if fn is None:
            raise CliError("명령이 필요합니다: " + " · ".join(COMMANDS))
        rc = fn(a, env)
    except CliError as e:
        _say(e.msg)
        rc = e.rc
    except SystemExit as e:                                          # --help(argparse) — 0 이면 정상
        rc = 0 if e.code in (0, None) else 1
    except KeyboardInterrupt:
        _say("사용자가 중단했습니다 — 다시 실행하면 이어서 합니다")
        rc = 2
    if own_events and events.mode() == "jsonl":
        events.emit("run_end", rc=rc)
    return rc
