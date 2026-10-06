# -*- coding: utf-8 -*-
r"""mail.copilot — Copilot 메일 존재 증인 어댑터(B §8.1 · CM §11.4 · 계약 §2.17 · §3.2 · §3.10 · §3.11 · §6.5 · §7.3 · §8.1 ·
X-046 · X-082 · X-257 · X-258 · v1.2 C1). **클라우드PC**에서 브리지 조회 단계 ``lookup_mail`` 을 부르는 얇은 어댑터이며,
``Get-TeamsViaCopilot.py``(teams.copilot · ``lookup_teams``)·``Get-CalViaCopilot.py``(cal.copilot · ``lookup_calendar`` — 기본
꺼짐)가 이 파일의 ``run(src, …)`` 을 같이 쓴다.

    "<PY>" -X utf8 -I -B collect\Get-MailViaCopilot.py --pc <pc_id> --run-id <run_id>
           [--blanks-file F] [--from D --to D] [--force] [--events jsonl|text|off]

흐름(B §8.1 '어댑터'):
  1. 빈칸: ``--blanks-file F``(없으면 ``data\derived\collect\<run_id>\blanks_<src>.json`` — X-315, ``lm27.collect.todo`` 가 그
     실행 폴더에 쓴다) = ``[{todo_id, date_range:[from, to], kind_axis}]`` 의 날짜. 빈칸 파일이 없으면 ``--from``·``--to`` 를
     둘 다 준 경우만 그 구간(수동 진단), 아니면 대상 없음(rc 1). 오늘(근무 시간대)과 그 뒤는 묻지 않는다(하루가 끝나지 않았다).
     커서의 ``witnessed_days`` 에 든 날은 다시 묻지 않는다(``--force`` = 무시).
  2. 날짜를 ``bridge.lookup.windowDays`` 이하 구간으로 묶어 ``data\derived\ai_in\<단계>.jsonl`` 에 쓴다(``lookup.plan_windows`` —
     조회 능력 TTL 뒤 첫 확인이면 첫 구간을 하루로, B §7.13).
  3. ``lm27.bridge.run_stages(run_id, [단계])`` — 세션·게이트·저널·재개·능력 기록·결과 봉투는 브리지 몫. ``LM_COPILOT_STUB``·
     ``LM_NO_BROWSER`` 주입은 브리지가 받는다.
  4. ``ai_out\<단계>.json`` 의 구간 답(쪼갠 구간은 펼친다)에서 행을 날짜별로 모아 증인 행으로 바꾸고
     ``lm27.privacy.sanitize.sanitize_record(kind, raw, rc)`` → ``lm27.store.SegmentWriter`` 로 쓴다(in-process — 원문·답 글은
     정제를 거친 ``text_masked`` 로만, 계약 §1.5). 증인 행: ``ts_precision="summary"`` · ``confidence`` 0.3 · 그 날짜 00:00(근무
     시간대 ``time.tzOffsetMin``)의 UTC · ``msg_key`` 는 'cp' 재료 HMAC(계약 §4.2) — **메시지 행과 병합하지 않는다**.
  5. 커서(계약 §3.10 ``*.copilot`` = ``{witnessed_days[]}``)는 ``SegmentWriter.flush()`` 성공 뒤에만 ``save_raw_cursor`` —
     답을 받은 구간의 날(행 0건 포함)을 더한다. 원장은 이것으로 0건 증인(zero_ok)을 안다(세그먼트만으로는 알 수 없다).

구간 → 셀(B §8.1 표, 셀 키 = 날짜 × kind_axis — 메일은 ``d`` 로 mail_in·mail_out): 답 받음·그 날 행 ≥1 → ``ok``(n = 행 수,
n_date = 행 수, n_minute = 0) · 행 0 → ``zero_ok``(Copilot 은 존재 증인이라 다른 출처의 미관측을 덮지 못한다, 계약 §3.11) ·
``capped`` → ``partial`` + R-CAP · ``skipped(capability_unavailable)`` → ``blocked`` + 능력 사유(R-NOLIC·R-NOCONN) ·
``skipped(mode_web)`` → basic 이면 ``blocked`` + R-NOLIC, 아니면 ``not_attempted`` · 로그인 → ``blocked`` + R-LOGIN · 정책 차단
(수동 경로 전환 포함) → ``blocked`` + R-EDGEPOL · 예산 → ``transport_fail`` + R-BUDGET · 그 밖 수송 실패 → ``transport_fail`` +
R-TRANSPORT('불가' 근거 아님).

rc(B §8.1 표 · X-257 — 위에서부터): 2 어느 구간이든 R-LOGIN · 3 답 받은 구간 0 이고 ``blocked``·``transport_fail`` 구간이 있음
(드라이버 불가·불완전 — 무라이선스도 ``blocked`` + R-NOLIC) · 0 새 증거 행 ≥ 1 · 4 물을 날이 모두 이미 증인 기록 · 1 그 밖
(배정 0 · 모든 구간 행 0). 상태 줄(v1.2 C1): stderr 마지막 줄 ``{"_status": {schema:"lm27.collector_status/1", src, rc,
reasons[], partial, cap_hit, budget_hit, n, counts{}, cells[], run_id, stage, bridge{}}}`` — 숫자·열거·사유 코드·날짜만.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # L-05 · 계약 §9.1 — collect\*.py 는 첫 실행문에서 자기 루트를 넣는다

import argparse
import json
import re
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta

SRC = "mail.copilot"
SCHEMA = "lm27.collector_status/1"
SRCS = ("mail.copilot", "teams.copilot", "cal.copilot")
PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
RUN_ID_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TODO_ID_RX = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")
WITNESSED_MAX = 800                # 커서의 증인 날짜 상한(최근 것부터)
EVENTS_MODES = ("jsonl", "text", "off")
R_LOGIN, R_EDGEPOL, R_TRANSPORT, R_BUDGET, R_CAP, R_NOLIC, R_NOCONN = (
    "R-LOGIN", "R-EDGEPOL", "R-TRANSPORT", "R-BUDGET", "R-CAP", "R-NOLIC", "R-NOCONN")
CELL_OK = ("ok", "zero_ok")
STATUS_RANK = {"blocked": 0, "transport_fail": 1, "not_attempted": 2, "partial": 3, "zero_ok": 4, "ok": 5}


class AdapterError(Exception):
    """인자·빈칸 파일 오류(rc 3 + R-TRANSPORT, 원문 없이 유형만)."""


# ───────────────────────────── 인자·빈칸 ─────────────────────────────
def parse_args(argv, src: str):
    ap = argparse.ArgumentParser(prog=os.path.basename(_script_of(src)), add_help=True,
                                 description=f"{src} — Copilot 존재 증인(브리지 조회 단계)")
    ap.add_argument("--pc", required=True, help="pc_id")
    ap.add_argument("--run-id", dest="run_id", default="", help="수집 실행 run_id(브리지 실행 폴더·빈칸 파일)")
    ap.add_argument("--from", dest="d0", default="", help="YYYY-MM-DD(로컬) — 빈칸 파일이 없을 때 수동 진단")
    ap.add_argument("--to", dest="d1", default="", help="YYYY-MM-DD(로컬, 포함)")
    ap.add_argument("--blanks-file", dest="blanks_file", default="", help="빈칸 파일(lm27.collect.todo 가 쓴 blanks_<src>.json)")
    ap.add_argument("--force", action="store_true", help="이미 증인 기록한 날도 다시 묻는다")
    ap.add_argument("--events", default="jsonl", choices=EVENTS_MODES)
    a = ap.parse_args(argv)
    if not PC_ID_RX.match(a.pc or ""):
        raise AdapterError("BadPcId")
    if a.run_id and not RUN_ID_RX.match(a.run_id):
        raise AdapterError("BadRunId")
    for v in (a.d0, a.d1):
        if v and not DATE_RX.match(v):
            raise AdapterError("BadDate")
    return a


def _script_of(src: str) -> str:
    return {"mail.copilot": "Get-MailViaCopilot.py", "teams.copilot": "Get-TeamsViaCopilot.py",
            "cal.copilot": "Get-CalViaCopilot.py"}.get(src, "Get-MailViaCopilot.py")


def load_blanks(path, axes) -> list:
    """``[{todo_id, date_range:[from, to], kind_axis}]``(또는 ``{"blanks": [...]}``) → [(todo_id, from, to, axis)].
    이 경로의 축이 아닌 항목은 뺀다(축이 비면 이 경로의 모든 축)."""
    from lm27.util import fsx
    obj = fsx.read_json(path, None, want=None)
    if isinstance(obj, dict) and isinstance(obj.get("blanks"), list):
        obj = obj["blanks"]
    if not isinstance(obj, list):
        raise AdapterError("BlanksFormat")
    out = []
    for x in obj:
        if not isinstance(x, dict):
            continue
        axis = str(x.get("kind_axis") or "")
        if axis and axis not in axes:
            continue
        dr = x.get("date_range")
        if not (isinstance(dr, list) and len(dr) == 2 and all(isinstance(s, str) and DATE_RX.match(s) for s in dr)):
            continue
        try:
            a, b = date.fromisoformat(dr[0]), date.fromisoformat(dr[1])
        except ValueError:
            continue
        if a > b:
            continue
        tid = str(x.get("todo_id") or "")
        out.append((tid if TODO_ID_RX.match(tid) else "", a, b, axis))
    return out


def assigned_days(opts, paths, src: str, axes) -> tuple[dict, dict]:
    """배정된 날 → {날짜(date): {축…}} · 기록용 {blanks, todo_ids, source}."""
    meta = {"source": "none", "blanks": 0}
    path = opts.blanks_file
    if not path and opts.run_id:
        p = paths.blanks_file(opts.run_id, src)
        path = str(p) if os.path.isfile(p) else ""
    elif path and not os.path.isfile(path):
        raise AdapterError("BlanksMissing")
    days: dict = {}
    if path:
        blanks = load_blanks(path, axes)
        meta.update(source="blanks", blanks=len(blanks))
        for _tid, a, b, axis in blanks:
            d = a
            while d <= b:
                days.setdefault(d, set()).update([axis] if axis else axes)
                d += timedelta(days=1)
    elif opts.d0 and opts.d1:
        a, b = date.fromisoformat(opts.d0), date.fromisoformat(opts.d1)
        meta["source"] = "range"
        d = a
        while d <= b:
            days.setdefault(d, set()).update(axes)
            d += timedelta(days=1)
    return days, meta


# ───────────────────────────── 정제·저장 묶음(L-10: lm27.privacy 는 sanitize 만) ─────────────────────────────
def store_api() -> dict:
    from lm27.privacy.sanitize import make_record_context, sanitize_record
    from lm27.store import SegmentWriter, load_raw_cursor, save_raw_cursor
    return {"make_record_context": make_record_context, "sanitize_record": sanitize_record,
            "SegmentWriter": SegmentWriter, "load_raw_cursor": load_raw_cursor, "save_raw_cursor": save_raw_cursor}


def default_bridge(run_id: str, stages, **kw) -> int:
    """브리지 공개 API(계약 §2.12) — 단계들을 한 프로세스·한 세션에서."""
    import lm27.bridge as bridge
    return bridge.run_stages(run_id, stages, **kw)


def default_caps(paths, settings):
    """조회 능력(``bridge_profile.capabilities`` — 읽기·재확인 표식)."""
    from lm27.bridge.capability import Capabilities
    from lm27.bridge.clock import default_clock
    from lm27.bridge.session import BridgeProfile
    return Capabilities(BridgeProfile(paths), settings, default_clock())


def _cfg(cfg, key, default):
    try:
        v = cfg[key]
    except KeyError:
        return default
    return default if v is None else v


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────── 셀 ─────────────────────────────
def _pending_cell(res, shown, caps_reasons) -> tuple[str, list]:
    """답을 받지 못한 구간의 셀(B §8.1 표). ``res`` = 이번 호출의 결과 봉투(없으면 None — 브리지가 돌지 않음)."""
    if not isinstance(res, dict):
        return "transport_fail", [R_TRANSPORT]
    state, sk, reason = res.get("state"), res.get("stop_kind"), res.get("reason")
    tier = (res.get("env") or {}).get("tier") if isinstance(res.get("env"), dict) else None
    if state == "skipped":
        if reason == "capability_unavailable":
            return "blocked", list(caps_reasons) or [R_NOCONN]
        if reason == "mode_web":
            return ("blocked", [R_NOLIC]) if tier == "basic" else ("not_attempted", [])
        if reason in ("disabled", "web_exposed", "no_input"):
            return "not_attempted", []
        return _phase_cell(reason, shown)
    if sk == "refused":
        return "blocked", [reason] if reason in (R_NOLIC, R_NOCONN) else (list(caps_reasons) or [R_NOCONN])
    if sk == "fatal":
        return _phase_cell(reason, shown)
    if sk == "budget":
        return "transport_fail", [R_BUDGET]
    if "BR-POLICY" in shown:
        return "blocked", [R_EDGEPOL]
    return "transport_fail", [R_TRANSPORT]


def _phase_cell(phase, shown) -> tuple[str, list]:
    if phase == "login_required" or "BR-LOGIN-TIMEOUT" in shown:
        return "blocked", [R_LOGIN]
    if phase == "policy_blocked" or "BR-POLICY" in shown:
        return "blocked", [R_EDGEPOL]
    return "transport_fail", [R_TRANSPORT]


def _cell(day: str, axis: str, status: str, n: int = 0, reasons=()) -> dict:
    c = {"date": day, "axis": axis, "status": status, "n": int(n)}
    if status in CELL_OK or status == "partial":
        c["n_date"], c["n_minute"] = int(n), 0
    if reasons:
        c["reasons"] = sorted(set(reasons))
    return c


def _row_axis(src: str, row: dict) -> str:
    if src == "mail.copilot":
        return "mail_out" if row.get("d") == "out" else "mail_in"
    return "teams" if src == "teams.copilot" else "cal"


# ───────────────────────────── 수집 ─────────────────────────────
def collect(src: str, opts, *, paths, cfg, environ, now, api=None, bridge=None, bridge_kw=None, caps_factory=None,
            notices=None) -> dict:
    """경로 하나(``*.copilot``) → 상태 dict(rc · reasons · counts · cells)."""
    from lm27.bridge import settings as BS
    from lm27.bridge.stages import lookup as L
    from lm27.util import fsx
    from lm27.util.tz import new_run_id
    stage = L.STAGE_OF[src]
    kind = L.KIND_OF[src]
    axes = L.AXES_OF[src]
    st = {"schema": SCHEMA, "src": src, "stage": stage, "rc": 3, "reasons": [], "partial": False, "cap_hit": False,
          "budget_hit": False, "n": 0, "counts": {}, "cells": []}
    c: Counter = Counter()
    settings = BS.from_cfg(cfg)
    if settings.mode == "off" or not settings.stage_on(stage):
        st["rc"], st["skipped"] = 1, "disabled"                  # 꺼진 단계 — 배정이 있어도 묻지 않는다(대상 없음)
        return st
    off = int(_cfg(cfg, "time.tzOffsetMin", 540))
    today = (now.astimezone(UTC) + timedelta(minutes=off)).date()
    days, meta = assigned_days(opts, paths, src, axes)
    c["blanks"] = meta["blanks"]
    c["assigned_days"] = len(days)
    if not days:
        st["rc"] = 1
        st["counts"] = dict(c)
        return st
    api = api or store_api()
    cur = (api["load_raw_cursor"](paths, opts.pc) or {}).get(src)
    witnessed = set(cur.get("witnessed_days") or ()) if isinstance(cur, dict) else set()
    ask, skipped = [], []
    for d in sorted(days):
        if d >= today:
            c["not_past"] += 1
            continue
        if d.isoformat() in witnessed and not opts.force:
            skipped.append(d)
            continue
        ask.append(d)
    c["already_witnessed"] = len(skipped)
    if not ask:
        st["rc"] = 4 if skipped else 1
        st["counts"] = dict(c)
        return st
    run_id = opts.run_id or new_run_id(now)
    st["run_id"] = run_id
    caps = (caps_factory or default_caps)(paths, settings)
    recheck = bool(caps.recheck_pending(stage)) if caps is not None else False
    windows = L.plan_windows(ask, settings.lookup.window_days, recheck=recheck)
    c["windows"] = len(windows)
    if recheck:
        c["recheck"] = 1
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in L.ai_in_rows(stage, windows)]
    fsx.atomic_write(paths.ai_in(stage), ("\n".join(lines) + "\n").encode("utf-8"))
    # ── 브리지 ──
    if notices is None:
        from lm27.bridge.messages import Notices
        from lm27.util import events
        notices = Notices(events.emit)
    kw = {"paths": paths, "pc_id": opts.pc, "environ": environ, "notices": notices, "raw_cfg": cfg}
    kw.update(bridge_kw or {})
    ran = True
    try:
        st["bridge"] = {"rc": int((bridge or default_bridge)(run_id, [stage], **kw))}
    except Exception as e:  # noqa: BLE001 — 브리지 기동 실패(세션·주입 폴더 등)는 수송 실패로(유형만, 원문 없음)
        ran = False
        st["bridge"] = {"error": type(e).__name__}
    from lm27.bridge.journal import run_file
    res = fsx.read_json(run_file(paths, run_id, "result", stage), None) if ran else None
    if isinstance(res, dict) and (res.get("run_id") != run_id or res.get("stage") != stage):
        res = None
    out = fsx.read_json(paths.ai_out(stage), None) if res is not None else None
    items = out.get("items") if isinstance(out, dict) and out.get("run_id") == run_id and \
        isinstance(out.get("items"), dict) else {}
    if isinstance(res, dict):
        st["bridge"].update({k: res.get(k) for k in ("state", "stop_kind", "reason", "rc", "transport")})
        for k, v in sorted((res.get("dropped") or {}).items()):
            if isinstance(v, int) and v:
                c["dropped." + k] = v
    caps2 = (caps_factory or default_caps)(paths, settings)
    caps_reasons = [r for r in (caps2.reasons(stage) if caps2 is not None else []) if r in (R_NOLIC, R_NOCONN)]
    shown = list(getattr(notices, "shown", ()) or ())
    # ── 구간 → 잎 → 날짜 ──
    day_rows: dict = {}                                   # 답 받은 날 → 행 목록
    day_capped: set = set()
    pend_cell = _pending_cell(res, shown, caps_reasons)
    day_pending: dict = {}                                # 답 못 받은 날 → (상태, 사유)
    answered_leaves = 0
    for a, b in windows:
        for key, e in L.leaves(items, L.window_key(stage, a, b)):
            win = L.parse_window_key(key) or (a, b)
            ds = _days(win[0], win[1])
            by = e.get("by") if isinstance(e, dict) else None
            ans = e.get("ans") if isinstance(e, dict) and isinstance(e.get("ans"), dict) else None
            if by in ("ai", "manual") and ans is not None:
                answered_leaves += 1
                for d in ds:
                    day_rows.setdefault(d, [])
                for row in ans.get("rows") or ():
                    if isinstance(row, dict) and row.get("t") in day_rows and row.get("t") in ds:
                        day_rows[row["t"]].append(row)
                if ans.get("capped"):
                    day_capped.update(ds)
                continue
            cell = ("transport_fail", [R_TRANSPORT]) if by == "rule" else pend_cell
            for d in ds:
                day_pending.setdefault(d, cell)
    c["answered_windows"] = answered_leaves
    # ── 증인 행 → 정제 → 저장 ──
    observed = _utc_iso(now)
    raws = []
    for d in sorted(day_rows):
        for row in day_rows[d]:
            raws.append(L.witness_raw(src, row, off_min=off, observed=observed))
    c["rows"] = len(raws)
    stored, per_day = [], Counter()
    drops: Counter = Counter()
    rc_ctx = None
    if raws:
        rc_ctx = api["make_record_context"](paths.root, src, opts.pc)
        for raw in raws:
            o = api["sanitize_record"](kind, raw, rc_ctx)
            if o.status == "stored":
                stored.append((raw["cp_row"], o.row))
            else:
                drops[o.reason or o.status] += 1
        raws = None                                       # 답 글 참조 해제(메모리에서만)
    for k, v in sorted(drops.items()):
        c["sanitize." + str(k)] = v
    try:
        if stored:
            w = api["SegmentWriter"](paths, opts.pc, kind, src)
            try:
                for _r, row in stored:
                    w.append(row)
                w.flush()
            finally:
                w.close()
    except Exception as e:  # noqa: BLE001 — 저장 실패는 rc 3 + 수송 사유, 커서는 진전하지 않는다
        st["rc"], st["reasons"], st["error"] = 3, [R_TRANSPORT], type(e).__name__
        st["counts"] = dict(c)
        return st
    if rc_ctx is not None and getattr(rc_ctx, "audit", None) is not None:
        rc_ctx.audit.flush(rows_in=c["rows"], rows_out=len(stored))
    for cp_row, _row in stored:
        per_day[(cp_row.get("t"), _row_axis(src, cp_row))] += 1
    c["stored"] = len(stored)
    # ── 커서(flush 성공 뒤에만) ──
    if day_rows:
        wd = sorted(witnessed | {d for d in day_rows if date.fromisoformat(d) < today})[-WITNESSED_MAX:]
        api["save_raw_cursor"](paths, opts.pc, src, {"witnessed_days": wd})
        st["cursor_saved"] = True
    # ── 셀·rc ──
    cells = []
    for d in sorted(x.isoformat() for x in ask):
        for axis in sorted(days[date.fromisoformat(d)]):
            if d in day_rows:
                n = per_day[(d, axis)]
                if d in day_capped:
                    cells.append(_cell(d, axis, "partial", n, [R_CAP]))
                else:
                    cells.append(_cell(d, axis, "ok" if n else "zero_ok", n))
            else:
                status, reasons = day_pending.get(d, pend_cell)
                cells.append(_cell(d, axis, status, 0, reasons))
    st["cells"] = cells
    reasons = sorted({r for x in cells for r in x.get("reasons", ())})
    st["reasons"] = reasons
    st["cap_hit"] = bool(day_capped)
    st["budget_hit"] = R_BUDGET in reasons
    st["n"] = len(stored)
    bad = [x for x in cells if x["status"] in ("blocked", "transport_fail")]
    if R_LOGIN in reasons:
        st["rc"] = 2
    elif answered_leaves == 0 and bad:
        st["rc"] = 3
    elif stored:
        st["rc"] = 0
    else:
        st["rc"] = 1
    st["partial"] = st["rc"] in (0, 1) and any(x["status"] not in CELL_OK for x in cells)
    c["cells"] = len(cells)
    st["counts"] = dict(sorted(c.items()))
    return st


def _days(d0: str, d1: str) -> list[str]:
    a, b = date.fromisoformat(d0), date.fromisoformat(d1)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


# ───────────────────────────── 진입점 ─────────────────────────────
def status_line(st: dict, err=None) -> None:
    err = err if err is not None else sys.stderr
    err.write(json.dumps({"_status": st}, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    err.flush()


def run(src: str, argv=None, *, paths=None, cfg=None, environ=None, now=None, api=None, bridge=None, bridge_kw=None,
        caps_factory=None, notices=None, err=None) -> int:
    """인자 해석 → 수집 → 상태 줄(stderr 마지막 줄) → rc. 시험은 ``paths``·``cfg``·``api``·``bridge``·``bridge_kw``·
    ``caps_factory``·``notices``·``now``·``environ`` 을 주입한다."""
    t0 = time.monotonic()
    if src not in SRCS:
        raise ValueError("경로 ID 가 아닙니다")
    try:
        opts = parse_args(argv, src)
    except SystemExit as e:
        if e.code in (0, None):
            return 0                                          # --help: 사용법만(수집이 아니므로 상태 줄 없음)
        status_line({"schema": SCHEMA, "src": src, "rc": 3, "reasons": [R_TRANSPORT], "partial": False,
                     "cap_hit": False, "budget_hit": False, "n": 0, "counts": {}, "error": "BadArguments"}, err)
        return 3
    except AdapterError as e:
        status_line({"schema": SCHEMA, "src": src, "rc": 3, "reasons": [R_TRANSPORT], "partial": False,
                     "cap_hit": False, "budget_hit": False, "n": 0, "counts": {}, "error": str(e)}, err)
        return 3
    from lm27.util import events
    events.configure(opts.events)                             # 브리지 진행 이벤트(30초 progress — 계약 §8.6)
    try:
        if paths is None:
            from lm27.paths import Paths
            paths = Paths(ROOT)
        if cfg is None:
            from lm27.config import load_config
            cfg = load_config(paths)
        st = collect(src, opts, paths=paths, cfg=cfg, environ=os.environ if environ is None else environ,
                     now=now or datetime.now(UTC), api=api, bridge=bridge, bridge_kw=bridge_kw,
                     caps_factory=caps_factory, notices=notices)
    except AdapterError as e:
        st = {"schema": SCHEMA, "src": src, "rc": 3, "reasons": [R_TRANSPORT], "partial": False, "cap_hit": False,
              "budget_hit": False, "n": 0, "counts": {}, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — 어댑터 내부 오류는 rc 3 + 수송 사유(예외 유형만, 원문·메시지 없음)
        st = {"schema": SCHEMA, "src": src, "rc": 3, "reasons": [R_TRANSPORT], "partial": False, "cap_hit": False,
              "budget_hit": False, "n": 0, "counts": {}, "error": type(e).__name__}
    st["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    status_line(st, err)
    return int(st.get("rc", 3))


def main(argv=None, src: str = SRC) -> int:
    for s in (sys.stdout, sys.stderr):
        r = getattr(s, "reconfigure", None)
        if r is not None:
            r(encoding="utf-8", errors="replace")
    return run(src, argv)


if __name__ == "__main__":
    sys.exit(main())
