# -*- coding: utf-8 -*-
r"""수집 화면 API(R §5.2 · §2.3.6 · COLLECT_PC §10) — 수집 실행·이 PC·번들 현황·커버리지·할 일·수동 업무 기록.

    GET  /api/collect/status              이 PC·번들·에이전트·최근 수집 결과·todo·수동 기록 목록·반입 폴더(R §5.2.1)
    GET  /api/collect/coverage?from&to    일자 × 축 합성 상태 + 출처별 셀(CH-H01, 최대 400일)
    POST /api/collect/run                 {"mode": "auto|probe-only|recollect", "since"?, "until"?} → {job_id}(lane bundle)
    POST /api/worklog                     수동 기록(R §5.2.4) 또는 {"retract": id} → 정제 파이프 → manual 레코드
    POST /api/pc/label · /api/pc/roles · /api/pc/kind     이 PC pc.json(번들 잠금 안, ``lm27.bundle.pcreg``)
    POST /api/move/prepare · /api/bundle/merge · /api/agent/repair → {job_id}

- 수동 기록은 **정제 파이프로만** 저장한다(``lm27_pipe.py --kind manual --src manual --mode append`` — 화면이 연결자, 계약 §7.3).
  메모 원문은 파이프 stdin(메모리)으로만 가고 디스크에는 정제본(``text_masked``)만 남는다(계약 §1.5). 삭제는 없다 — [취소 기록]은
  같은 id 를 가리키는 ``retract`` 레코드를 덧붙인다(세그먼트 불변 — R §5.2.4).
- 응답의 위치 표기는 ROOT 상대 경로(``data\import``)만(R §5.0.4 ③).
"""
from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, timedelta

from lm27.ui.server import ApiError

__all__ = ["KIND_KO", "ROUTES", "last_collect", "manual_raw", "pc_stale", "write_manual"]

MODES = ("auto", "probe-only", "recollect")
KIND_KO = {"work": "업무", "offsite": "외근·출장·현장", "instr": "오프라인 지시 받음", "report": "오프라인 보고함",
           "absence": "부재", "exclude": "업무 아님", "retract": "취소 기록", "attended": "참석 확인",
           "must_link": "같은 업무", "cannot_link": "다른 업무"}
# 수동 기록 범주(정제기 CATEGORY_RX — 1~20자 한글·영숫자·공백·-·_, 사람 이름 없음)
CATEGORY_OF = {"work": "수동 업무 기록", "offsite": "외근 출장 현장", "instr": "오프라인 지시", "report": "오프라인 보고",
               "absence": "부재", "exclude": "업무 아님", "retract": "취소 기록", "attended": "참석 확인",
               "must_link": "업무 잇기", "cannot_link": "업무 나누기"}
UI_KINDS = ("work", "offsite", "instr", "report", "absence", "exclude")
ROLES_ALL = ("pc_usage", "mail_local", "teams_window", "account_backfill", "copilot")
PC_KINDS = ("desktop", "laptop", "vdi", "cloud")
TODO_KO = {"open": "열림", "assigned": "배정됨", "blocked_confirmed": "불가(확정)", "released": "다시 열림"}
STATUS_KO = {"ok": "정상", "zero_ok": "0건(정상)", "partial": "일부", "out_of_horizon": "보관 기간 밖", "blocked": "막힘",
             "transport_fail": "일시 실패", "not_attempted": "시도 안 함"}
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM_RX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_REG_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,15}$")
_VOCAB_RX = re.compile(r"^[0-9A-Za-z가-힣_]{1,20}$")
_REF_RX = re.compile(r"^(?:[me][0-9a-f]{24}|[dh][0-9a-f]{16})$")
_HEX16_RX = re.compile(r"^[0-9a-f]{16}$")
_LABEL_MAX = 20
COVERAGE_MAX_DAYS = 400
WORKLOG_DAYS = 120
WORKLOG_LIST = 30
STALE_OTHER_DAYS = 7


# ───────────────────────────── 읽기 도우미 ─────────────────────────────
def _parse_utc(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s[:19].rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _local_iso(dt, off_min: int):
    if dt is None:
        return None
    from lm27.util.tz import fmt_offset, to_local
    return to_local(dt, off_min).strftime("%Y-%m-%dT%H:%M:%S") + fmt_offset(off_min)


def agent_state(app) -> dict:
    """에이전트 상태(heartbeat·agent.json — 작업 스케줄러를 조회하지 않는다). state ok·stale·missing."""
    from lm27.util import fsx
    cfg = app.cfg()
    aj = fsx.read_json(app.paths.agent_json(), None, want=dict) or {}
    hb = fsx.read_json(app.paths.heartbeat(), None, want=dict) or {}
    inst = str(aj.get("install_id") or "")
    if not inst:
        return {"impl": None, "last_tick": None, "task": "", "state": "missing", "state_ko": "설치 안 됨"}
    last = _parse_utc(hb.get("last_tick")) if hb.get("install_id") in (None, inst) else None
    stale = int(cfg["agent.heartbeatStaleSec"])
    age = (app.deps.now() - last).total_seconds() if last is not None else None
    ok = age is not None and age <= stale
    return {"impl": aj.get("impl"), "last_tick": _local_iso(last, int(cfg["time.tzOffsetMin"])),
            "task": "LM27-" + inst[:8], "state": "ok" if ok else "stale", "state_ko": "정상" if ok else "멈춤",
            "age_s": int(age) if age is not None else None, "reasons": [r for r in (hb.get("last_error"),)
                                                                         if isinstance(r, str) and r.startswith("R-")]}


def pc_stale(app, pc: dict) -> bool:
    """'기록 끊김'(R §5.1.2): 이 PC = 에이전트 heartbeat 멈춤, 다른 PC = 마지막 방문이 7일 넘게 전."""
    from lm27.ui.api_home import this_pc
    me, _pc = this_pc(app)
    if pc.get("pc_id") == me:
        return agent_state(app)["state"] != "ok"
    last = _parse_utc(pc.get("last_seen"))
    return last is None or (app.deps.now() - last).days > STALE_OTHER_DAYS


def last_collect(app) -> dict | None:
    r"""가장 최근 [수집] 실행의 요약 — 단계 결과(``data\derived\collect\<run_id>``)에서."""
    from lm27.collect import ledger, stage_result
    runs = ledger.list_runs(app.paths)
    if not runs:
        return None
    rid = runs[-1]
    res = stage_result.read_stage_results(app.paths, rid)
    if not res:
        return None
    states = [r.get("state") for r in res.values()]
    state = "failed" if "failed" in states else ("partial" if "partial" in states else "done")
    new = 0
    for r in res.values():
        if isinstance(r.get("items_ok"), int):
            new += r["items_ok"]
    rc = 1 if state == "failed" else (2 if state == "partial" else (0 if new else 4))
    upd = max((str(r.get("updated") or "") for r in res.values()), default="")
    pc = next((r.get("pc_id") for r in res.values() if isinstance(r.get("pc_id"), str)), None)
    label = None
    if pc:
        from lm27.ui.api_home import all_pcs, pc_label
        label = next((pc_label(p) for p in all_pcs(app) if p.get("pc_id") == pc), None)
    reasons = sorted({str(x) for r in res.values() for x in (r.get("reasons") or ()) if isinstance(x, str)}
                     | {str(r.get("reason")) for r in res.values() if isinstance(r.get("reason"), str)
                        and str(r.get("reason")).startswith("R-")})
    unfinished = [{"stage": st, "reason": r.get("reason")} for st, r in res.items() if r.get("state") in ("partial",
                                                                                                         "failed")]
    return {"run_id": rid, "at": _local_iso(_parse_utc(upd), int(app.cfg()["time.tzOffsetMin"])), "pc": label,
            "rc": rc, "state": state, "new": {"total": new}, "reasons": reasons, "unfinished": unfinished}


def _todo_rows(app, me: str | None) -> list:
    from lm27.collect import todo as T
    from lm27.ui.api_home import AXIS_KO, all_pcs, pc_label
    labels = {p.get("pc_id"): pc_label(p) for p in all_pcs(app)}
    out = []
    for t in T.load_todo(app.paths):
        d = t if isinstance(t, dict) else getattr(t, "__dict__", {})
        rng = d.get("date_range") or [d.get("from"), d.get("to")]
        want_pc = d.get("want_pc")
        out.append({"todo_id": d.get("todo_id"), "from": rng[0] if rng else None, "to": rng[1] if rng else None,
                    "axis": d.get("kind_axis"), "axis_ko": AXIS_KO.get(d.get("kind_axis"), d.get("kind_axis")),
                    "want_src": d.get("want_src"),
                    "want_pc": "클라우드PC" if want_pc == "cloud" else labels.get(want_pc, "다른 PC"),
                    "reasons": list(d.get("reasons") or ()), "tries": len(d.get("attempts") or ()),
                    "state": d.get("state"), "state_ko": TODO_KO.get(d.get("state"), d.get("state")),
                    "mine": bool(me) and want_pc == me})
    return out


def _worklog_rows(app, me: str | None) -> list:
    """최근 수동 기록(번들 세그먼트 ∪ 이 PC 로컬 원장 — 아직 내보내지 않은 것 포함). 정제본만."""
    from lm27.bundle import loader
    cfg = app.cfg()
    off = int(cfg["time.tzOffsetMin"])
    today = app.deps.now().date()
    d0 = today - timedelta(days=WORKLOG_DAYS)
    rows = {}
    try:
        for r in loader.iter_records(app.paths, "manual", d0, None, cfg=cfg):
            rows[r.get("id")] = r
    except (OSError, ValueError):
        pass
    if me:
        try:
            from lm27.store.reader import iter_store
            for r in iter_store(app.paths, me, "manual", "manual", d0 - timedelta(days=1), None):
                if isinstance(r, dict):
                    rows.setdefault(r.get("id"), r)
        except (OSError, ValueError):
            pass
    retracted = {r.get("retract_of") for r in rows.values() if r.get("man_kind") == "retract"}
    out = []
    for r in rows.values():
        if r.get("man_kind") == "retract" or not isinstance(r.get("id"), str):
            continue
        t0, t1 = _parse_utc(r.get("ts_utc")), _parse_utc(r.get("ts_end"))
        if t0 is None:
            continue
        from lm27.util.tz import to_local
        loc = to_local(t0, off)
        mins = None
        if t1 is not None and t1 > t0:
            mins = int((t1 - t0).total_seconds()) // 60
        elif isinstance(r.get("hours"), (int, float)) and not isinstance(r.get("hours"), bool):
            mins = int(r["hours"] * 60)
        out.append({"id": r["id"], "date": loc.date().isoformat(),
                    "start": loc.strftime("%H:%M") if r.get("ts_precision") == "minute" else None,
                    "kind": r.get("man_kind"), "kind_ko": KIND_KO.get(r.get("man_kind"), r.get("man_kind")),
                    "minutes": mins, "project": r.get("project_id"), "memo": r.get("text_masked") or "",
                    "retracted": r["id"] in retracted})
    out.sort(key=lambda x: (x["date"], x.get("start") or "", x["id"]), reverse=True)
    return out[:WORKLOG_LIST]


def _import_box(app) -> dict:
    p = app.paths.import_dir()
    try:
        rel = os.path.relpath(os.fspath(p), os.fspath(app.paths.root))
    except ValueError:
        rel = os.path.basename(os.fspath(p))
    waiting = {"eml": 0, "csv": 0, "ics": 0}
    from lm27.util import fsx
    try:
        for _dp, _dn, fns in os.walk(fsx.longp(p)):
            for fn in fns:
                ext = os.path.splitext(fn)[1].lower().lstrip(".")
                if ext in waiting:
                    waiting[ext] += 1
    except OSError:
        pass
    return {"dir": rel, "waiting": waiting}


# ───────────────────────────── 처리기 ─────────────────────────────
def get_status(app, req):
    from lm27.ui import api_home
    pc_id, pc = api_home.this_pc(app)
    agent = agent_state(app)
    bl = api_home.matrix_cell(pc, "bundle_location") if pc else {"verdict": "미확인", "reasons": []}
    codes = set(bl.get("reasons") or ())
    pcs_out, arrival_missing = [], []
    try:
        from lm27.bundle import loader
        bs = loader.bundle_status(app.paths, app.cfg())
    except Exception:                                   # 번들 없음·깨짐 — 그 카드만 '정보 없음'
        bs = {"pcs": []}
    by_id = {p.get("pc_id"): p for p in api_home.all_pcs(app)}
    for b in bs.get("pcs") or ():
        p = by_id.get(b.get("pc_id"), {})
        segs = sum(int(k.get("segments") or 0) for k in (b.get("kinds") or {}).values())
        arrival_missing += [{"pc": api_home.pc_label(p) if p else "다른 PC", "file": x.get("file"), "state": x.get("state")}
                            for x in b.get("missing") or ()]
        pcs_out.append({"pc_id": b.get("pc_id"), "label": api_home.pc_label(p) if p else b.get("label_auto") or "PC",
                        "kind": b.get("kind"), "first_visit": str(b.get("first_seen") or "")[:10] or None,
                        "last_visit": str(b.get("last_seen") or "")[:10] or None, "segments": segs, "mb": b.get("mb"),
                        "this": b.get("pc_id") == pc_id,
                        "agent_ko": agent["state_ko"] if b.get("pc_id") == pc_id else "—"})
    last = last_collect(app)
    if last:
        codes.update(last.get("reasons") or ())
    todos = _todo_rows(app, pc_id)
    for t in todos:
        codes.update(t["reasons"])
    if last is not None:
        last["todo_left"] = sum(1 for t in todos if t["state"] in ("open", "assigned", "released"))
    txt = ("도착 점검: 모든 세그먼트가 복사되었습니다" if not arrival_missing else
           f"도착 점검: 복사되지 않은 기록 {len(arrival_missing)}개 — 원래 PC 에서 다시 복사하면 이어서 합칩니다")
    out = {"pc": {"pc_id": pc_id, "label_user": pc.get("label_user", "") if pc else "",
                  "label_auto": pc.get("label_auto", "") if pc else "", "kind": pc.get("kind") if pc else None,
                  "kind_confirmed": bool(pc.get("kind_confirmed")) if pc else False,
                  "roles": sorted(str(r) for r in pc.get("roles") or ()) if pc else [], "roles_all": list(ROLES_ALL),
                  "agent": agent,
                  "bundle_location": {"verdict": bl.get("verdict"),
                                      "text_ko": " ".join(api_home.reason_texts(bl.get("reasons") or ()).values())
                                      or ("쓰기 가능한 위치입니다" if bl.get("verdict") == "가능" else "")}},
           "pcs": pcs_out, "arrival": {"text_ko": txt, "missing": arrival_missing[:50]},
           "space": {"total_mb": bs.get("total_mb"), "over": bool(bs.get("over_size"))}, "last": last, "todo": todos,
           "worklog_options": _worklog_options(app), "worklog": _worklog_rows(app, pc_id), "import": _import_box(app)}
    out["reason_text"] = api_home.reason_texts(codes)
    return out


def _recent_refs(app) -> list:
    """관련 문서 고르기 목록 — 지금 결과(전체판)의 문서군 키 + 로컬 해석 이름, 투입 많은 순 30개(이름이 아니라 키로 저장)."""
    from lm27.ui.api_report import current, model_or_none
    cur = current(app)
    m = model_or_none(app, cur["run_id"], "full") if cur else None
    docs = ((m or {}).get("refs") or {}).get("docs") if isinstance((m or {}).get("refs"), dict) else None
    if not isinstance(docs, dict):
        return []
    rows = [d for d in docs.values() if isinstance(d, dict) and isinstance(d.get("key"), str) and _REF_RX.match(d["key"])]
    rows.sort(key=lambda d: (-int(d.get("min") or 0), d["key"]))
    return [{"ref": d["key"], "label": str(d.get("name") or d["key"])[:60]} for d in rows[:30]]


def _worklog_options(app) -> dict:
    from lm27.ui.api_team import registry_view
    reg, _st = registry_view(app)
    refs = _recent_refs(app)
    if reg is None:
        return {"projects": [], "fields": [], "functions": [], "refs": refs}
    projects = [{"key": p.id, "label": p.name or p.id} for p in sorted(reg.projects.values(), key=lambda x: x.id)
                if p.origin != "reserved" and p.status == "active"]

    def voc(kind):
        return [{"code": c, "name": getattr(it, "name", c) or c} for c, it in (reg.vocab.get(kind) or {}).items()
                if getattr(it, "status", "active") == "active"]
    return {"projects": projects, "fields": voc("fields"), "functions": voc("functions"), "refs": refs}


def get_coverage(app, req):
    from lm27.ui.api_home import coverage_days, load_composite
    today = app.deps.now().date()
    try:
        d1 = date.fromisoformat(req.q("to", today.isoformat()))
        d0 = date.fromisoformat(req.q("from", (d1 - timedelta(days=34)).isoformat()))
    except ValueError:
        raise ApiError(400, "bad_date", "날짜는 YYYY-MM-DD 입니다") from None
    if d1 < d0:
        raise ApiError(400, "bad_range", "끝 날짜가 시작보다 앞섭니다")
    if (d1 - d0).days + 1 > COVERAGE_MAX_DAYS:
        raise ApiError(400, "range_too_long", f"기간은 최대 {COVERAGE_MAX_DAYS}일입니다")
    comp, cells = load_composite(app)
    out = coverage_days(app, d0, d1, comp, cells)
    out["cells"] = _week_cells(cells, d0, d1)
    return out


def _week_cells(cells, d0: date, d1: date) -> list:
    """출처별 셀 표(주 단위 × 출처): n·n_minute·n_date·상태(최악)."""
    from lm27.collect.ledger import status_rank
    from lm27.report.fmt import iso_week
    agg: dict = {}
    for c in cells or ():
        try:
            d = date.fromisoformat(str(c.get("date")))
        except ValueError:
            continue
        if d < d0 or d > d1:
            continue
        k = (iso_week(d), str(c.get("src")))
        a = agg.setdefault(k, {"week": k[0], "src": k[1], "n": 0, "n_minute": 0, "n_date": 0, "status": "ok"})
        for f in ("n", "n_minute", "n_date"):
            a[f] += int(c.get(f) or 0)
        if status_rank(c.get("status")) > status_rank(a["status"]):
            a["status"] = c.get("status")
    out = sorted(agg.values(), key=lambda a: (a["week"], a["src"]))
    for a in out:
        a["status_ko"] = STATUS_KO.get(a["status"], a["status"])
    return out


def post_run(app, req):
    b = req.body
    mode = b.get("mode") or "auto"
    if mode not in MODES:
        raise ApiError(400, "bad_mode", "수집 방식은 auto·probe-only·recollect 중 하나입니다")
    argv = ["collect", "--auto"] if mode == "auto" else ["collect", "--mode", mode]
    if mode == "recollect":
        since, until = b.get("since"), b.get("until")
        if not (isinstance(since, str) and _DATE_RX.match(since) and isinstance(until, str) and _DATE_RX.match(until)):
            raise ApiError(400, "bad_date", "다시 수집할 시작·끝 날짜를 넣어 주세요")
        if until < since:
            raise ApiError(400, "bad_range", "끝 날짜가 시작보다 앞섭니다")
        argv += ["--since", since, "--until", until]
    return app.start_job("collect", argv)


# ── 수동 기록 ──
def manual_raw(app, *, kind: str, d: str, start=None, end=None, hours=None, project=None, field=None, func=None,
               refs=(), memo: str = "", retract_of=None) -> dict:
    """수동 기록 원시 레코드(Add-WorkLog.ps1 과 같은 모양 — CP §10, 정제기 records.manual 이 받는 형)."""
    from lm27.util import tz
    hm = start or "00:00"
    off = tz.capture_offset_min()
    try:
        loc = datetime.fromisoformat(f"{d}T{hm}:00")
        off = tz.capture_offset_min(loc - timedelta(minutes=off))
    except ValueError:
        pass
    return {"category": CATEGORY_OF.get(kind, "수동 업무 기록"), "hours": hours, "date": d, "start": start, "end": end,
            "note": memo or "", "entity": "", "project_id": project, "role_field": field, "role_func": func,
            "man_kind": kind, "ref_keys": [r for r in refs if isinstance(r, str) and _REF_RX.match(r)][:5],
            "retract_of": retract_of, "ts_local_offset": tz.fmt_offset(off),
            "observed_at": app.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "confidence": 1.0}


def write_manual(app, raws: list) -> dict:
    """원시 수동 레코드 → 정제 파이프(이 PC 로컬 원장 → 다음 [수집] 내보내기에서 번들 세그먼트). 반환 {rc, stored}."""
    try:
        ident = app.deps.identify()
    except Exception:                                   # 식별 실패 — 기록할 PC 를 모른다
        raise ApiError(503, "no_pc", "이 PC 를 식별하지 못해 기록하지 못했습니다 — 다시 누르면 이어서 합니다") from None
    res = app.deps.run_pipe("manual", "manual", ident.pc_id, raws, app.cfg())
    rc = res.get("rc")
    summ = res.get("summary") or {}
    if rc == 6:
        raise ApiError(409, "no_key", "개인정보 키가 아직 없어 기록하지 못했습니다 — [수집]을 한 번 하면 만들어집니다")
    if rc not in (0, 2) or not summ.get("ok", rc == 0):
        raise ApiError(500, "pipe_failed", "기록을 정제·저장하지 못했습니다 — 다시 누르면 이어서 합니다", [f"rc {rc}"])
    stored = summ.get("stored") if isinstance(summ.get("stored"), int) else None
    if stored == 0:
        raise ApiError(400, "rejected", "기록이 정제 규칙을 통과하지 못했습니다 — 입력을 고쳐 다시 보내 주세요")
    return {"rc": rc, "stored": stored}


def _hm_ok(s) -> bool:
    return isinstance(s, str) and _HHMM_RX.match(s) is not None


def post_worklog(app, req):
    b = req.body
    if "retract" in b:
        rid = b.get("retract")
        if not isinstance(rid, str) or not _HEX16_RX.match(rid):
            raise ApiError(400, "bad_id", "취소할 기록을 고르세요")
        raw = manual_raw(app, kind="retract", d=app.deps.now().date().isoformat(), retract_of=rid)
        write_manual(app, [raw])
        return {"ok": True, "id": rid, "retracted": True}
    errs = []
    d = b.get("date")
    if not (isinstance(d, str) and _DATE_RX.match(d)):
        errs.append("date")
    kind = b.get("kind") or "work"
    if kind not in UI_KINDS:
        errs.append("kind")
    a, e = b.get("a"), b.get("b")
    hours = None
    if a or e:
        if not (_hm_ok(a) and _hm_ok(e)) or e <= a:
            errs.append("a_b")
    else:
        h = b.get("hours")
        if not isinstance(h, (int, float)) or isinstance(h, bool) or not 0.25 <= h <= 16 or int(h * 4) != h * 4:
            errs.append("hours")
        else:
            hours = float(h)
    proj = b.get("project")
    if proj not in (None, "") and not (isinstance(proj, str) and _REG_RX.match(proj)):
        errs.append("project")
    fld, fn = b.get("field"), b.get("func")
    for k, v in (("field", fld), ("func", fn)):
        if v not in (None, "") and not (isinstance(v, str) and _VOCAB_RX.match(v)):
            errs.append(k)
    memo = b.get("memo") or ""
    if not isinstance(memo, str) or len(memo) > 200:
        errs.append("memo")
    ref = b.get("ref")
    if ref not in (None, "") and not (isinstance(ref, str) and _REF_RX.match(ref)):
        errs.append("ref")
    if errs:
        raise ApiError(400, "invalid", "입력을 확인해 주세요", errs)
    raw = manual_raw(app, kind=kind, d=d, start=a or None, end=e or None, hours=hours, project=proj or None,
                     field=fld or None, func=fn or None, refs=[ref] if ref else [], memo=memo)
    res = write_manual(app, [raw])
    return {"ok": True, "stored": res.get("stored"), "text_ko": "기록했습니다 — 다시 분석하면 반영됩니다"}


# ── 이 PC ──
def _update_this_pc(app, changes: dict) -> dict:
    from lm27.bundle import loader, pcreg
    from lm27.bundle.lock import BundleBusy, BundleLock
    try:
        ident = app.deps.identify()
    except Exception:                                   # 식별 실패
        raise ApiError(503, "no_pc", "이 PC 를 식별하지 못했습니다") from None
    pcdir = loader.pc_dir_of(app.paths, ident.pc_id)
    if pcreg.load_pc(pcdir) is None:
        raise ApiError(409, "no_pc_record", "이 번들에는 아직 이 PC 기록이 없습니다 — [수집]을 누르면 이 PC 부터 기록합니다")
    try:
        with BundleLock(app.paths, "fg-write", app.cfg()["bundle.lockTimeoutSec"]):
            pc = pcreg.update_pc(pcdir, changes)
    except (BundleBusy, TimeoutError):
        raise ApiError(409, "busy", "번들을 다른 작업이 쓰고 있습니다 — 끝나면 다시 눌러 주세요") from None
    except OSError:
        raise ApiError(409, "bundle_readonly", "번들 폴더에 쓸 수 없습니다") from None
    app.scratch.pop("_pc_brief", None)
    return pc


def post_label(app, req):
    lab = req.body.get("label_user")
    if not isinstance(lab, str) or len(lab.strip()) > _LABEL_MAX or any(ord(c) < 32 for c in lab):
        raise ApiError(400, "bad_label", f"이름은 {_LABEL_MAX}자 이하로 넣어 주세요")
    pc = _update_this_pc(app, {"label_user": lab.strip()})
    return {"ok": True, "label_user": pc.get("label_user", "")}


def post_roles(app, req):
    roles = req.body.get("roles")
    if not isinstance(roles, list) or any(r not in ROLES_ALL for r in roles):
        raise ApiError(400, "bad_roles", "수집 역할을 다시 골라 주세요")
    pc = _update_this_pc(app, {"roles": sorted(set(roles))})
    return {"ok": True, "roles": pc.get("roles", [])}


def post_kind(app, req):
    kind = req.body.get("kind")
    if kind not in PC_KINDS:
        raise ApiError(400, "bad_kind", "PC 종류를 다시 골라 주세요")
    pc = _update_this_pc(app, {"kind": kind, "kind_confirmed": bool(req.body.get("confirmed", True))})
    return {"ok": True, "kind": pc.get("kind"), "kind_confirmed": pc.get("kind_confirmed")}


def post_move(app, req):
    return app.start_job("move_prepare", ["move-prepare"])


def post_merge(app, req):
    d = req.body.get("dir")
    if not isinstance(d, str) or not d.strip() or len(d) > 1024 or any(ord(c) < 32 for c in d):
        raise ApiError(400, "bad_dir", "합칠 번들 폴더를 넣어 주세요")
    if not os.path.isdir(d.strip()):
        raise ApiError(400, "no_dir", "그 폴더가 없습니다")
    return app.start_job("bundle_merge", ["bundle", "merge", d.strip()])


def post_agent_repair(app, req):
    return app.start_job("agent_repair", ["agent", "repair"])


ROUTES = (("GET", r"/api/collect/status", get_status),
          ("GET", r"/api/collect/coverage", get_coverage),
          ("POST", r"/api/collect/run", post_run),
          ("POST", r"/api/worklog", post_worklog),
          ("POST", r"/api/pc/label", post_label),
          ("POST", r"/api/pc/roles", post_roles),
          ("POST", r"/api/pc/kind", post_kind),
          ("POST", r"/api/move/prepare", post_move),
          ("POST", r"/api/bundle/merge", post_merge),
          ("POST", r"/api/agent/repair", post_agent_repair))
