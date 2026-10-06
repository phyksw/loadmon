# -*- coding: utf-8 -*-
r"""분석 화면 API(R §5.3 · §2.3.6 · COPILOT §10.5) — 분석 실행·이력·결과 선택·코파일럿 상태·직접 붙여넣기.

    GET  /api/analysis/runs                실행 이력(R §5.3.4) + 지금 보는 결과(current) + 기본 기간(defaults.period — 올해 1월 1일 ~
                                           오늘과 빠른 선택 7개, lm27.ui.period 단일원)
    GET  /api/analysis/run/<run_id>        run_status.json + 라벨 출처 통계 + 시간 코어 감사 + 경고 + 확인 질문 수(R §5.3.5)
    POST /api/analysis/run                 {from, to, as_of?, ai} → analyze 작업 · from·to 를 둘 다 빼면 기본 기간(올해 1월 1일 ~
                                           오늘, period_source 'default') · {rerun, stages, ai:false} → 빠른 재분석
    POST /api/analysis/current             {run_id} → current.json 명시 선택(``lm27.pipeline.analyze.choose_current`` 하나)
    GET  /api/bridge/status · /api/bridge/manual
    POST /api/bridge/manual/copy {seq} → {text}(프롬프트 글은 이 응답에만 — 저장·로그 금지) · /api/bridge/manual/import {text}
    POST /api/bridge/front                 분석용 Edge 창 앞으로(창이 없으면 안내)

- 빠른 재분석 = ``analyze --rerun <id> --stages classify,time,mining,report --no-ai``(``lm27.pipeline.stages.QUICK_RERUN`` — X-281).
- 강제 종료로 ``state=running`` 이 남은 실행은 그 pid 가 살아 있지 않으면 '중단됨'(cancelled)으로 보인다(WP-32 — 다음 분석이 재개).
"""
from __future__ import annotations

import re
from datetime import datetime

from lm27.ui import period
from lm27.ui.server import ApiError

__all__ = ["ROUTES", "list_runs", "run_view"]

_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STAGE_RX = re.compile(r"^[a-z][a-z0-9_:]{0,31}$")
_PERIOD_SOURCES = period.PERIOD_SOURCES                  # = cli PERIOD_SOURCES(R RP8 — 사본 일치는 tests\ui\test_period.py)
AI_STAGES = ("task_label", "workflow_label", "agentic_match", "subagent_review", "review_text")
RUNS_MAX = 50
LABEL_RUNS = 10                          # 라벨 출처 통계를 싣는 최근 실행 수(실행마다 결과 봉투 5개를 읽는다)
MODE_KO = {"auto": "자동", "manual": "직접 붙여넣기", "off": "꺼짐"}


def _quick_stages() -> tuple:
    """빠른 재분석 단계(``lm27.pipeline.stages.QUICK_RERUN`` 단일원 — 계약 X-281)."""
    from lm27.pipeline.stages import QUICK_RERUN
    return tuple(QUICK_RERUN)


def _alive(pid) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool):
        return False
    from lm27.util.proc import pid_alive
    try:
        return pid_alive(pid)
    except (OSError, NotImplementedError):
        return False


def _status(app, rid: str) -> dict | None:
    from lm27.pipeline.analyze import read_run_status
    st = read_run_status(app.paths, rid)
    if isinstance(st, dict) and st.get("state") == "running" and not _alive(st.get("pid")):
        st = dict(st)
        st["state"], st["interrupted"] = "cancelled", True            # 강제 종료로 남은 실행(재개 가능)
    return st


def _label_counts(app, rid: str) -> dict:
    """단계별 라벨 출처 수(브리지 결과 봉투 — B §7.11 ``ai·manual·rule·pending``)."""
    from lm27.util import fsx
    out = {}
    for stg in AI_STAGES:
        try:
            p = app.paths.ai_result(rid, stg)
        except ValueError:
            continue
        obj = fsx.read_json(p, None, want=dict)
        if not isinstance(obj, dict):
            continue
        src = obj.get("counts") if isinstance(obj.get("counts"), dict) else obj
        out[stg] = {k: int(src.get(k) or 0) for k in ("ai", "manual", "rule", "pending")
                    if isinstance(src.get(k, 0), int)}
    return out


def _local_ts(app, s):
    """run_status 의 UTC 시각('…Z') → 근무 시간대 벽시계('…+09:00'). 화면 이력 표가 머리 띠(current.json — 로컬)와
    같은 시각을 보이게 한다(UTC 를 그대로 보이면 9시간 어긋나 보인다). 형식이 다르면 그대로."""
    if not isinstance(s, str) or not s.endswith("Z"):
        return s
    from lm27.util.tz import to_local
    try:
        return to_local(s, int(app.cfg()["time.tzOffsetMin"])).isoformat(timespec="seconds")
    except (ValueError, TypeError):
        return s


def list_runs(app) -> list:
    from lm27.pipeline.retention import list_runs as _list
    from lm27.ui.api_report import current
    cur = current(app) or {}
    out = []
    for i, rid in enumerate(sorted(_list(app.paths), reverse=True)[:RUNS_MAX]):
        st = _status(app, rid)
        if st is None:
            continue
        out.append({"run_id": rid, "from": st.get("from"), "to": st.get("to"), "as_of": st.get("as_of"),
                    "label_sources": _label_counts(app, rid) if i < LABEL_RUNS else None,
                    "built_at": _local_ts(app, st.get("ended") or st.get("started")), "state": st.get("state"),
                    "chosen": cur.get("chosen") if cur.get("run_id") == rid else None,
                    "current": cur.get("run_id") == rid, "report_version": st.get("report_version"),
                    "period_source": st.get("period_source"), "period_months": st.get("period_months"),
                    "warnings": [w for w in st.get("warnings") or () if isinstance(w, dict)][:10],
                    "reason": st.get("reason"), "reason_ko": st.get("reason_ko")})
    return out


def _today(app):
    """근무 시간대(time.tzOffsetMin) 벽시계의 오늘 — 기본 기간의 끝(lm27.ui.period.today_local)."""
    return period.today_local(int(app.cfg()["time.tzOffsetMin"]), app.deps.now())


def get_runs(app, req):
    from lm27.ui.api_report import current
    today = _today(app)
    f, t = period.default_range(today)
    # months 는 이전 기본(최근 n개월, report.defaultRangeMonths)의 값 — 화면은 이제 period(올해 1월 1일 ~ 오늘)를 쓴다
    return {"runs": list_runs(app), "current": current(app),
            "defaults": {"months": int(app.cfg()["report.defaultRangeMonths"]),
                         "keep": int(app.cfg()["report.analysisKeep"]),
                         "period": {"today": today.isoformat(), "key": period.DEFAULT_KEY, "from": f, "to": t,
                                    "presets": period.presets(today)}}}


def run_view(app, rid: str) -> dict:
    from lm27.util import fsx
    st = _status(app, rid)
    if st is None:
        raise ApiError(404, "no_run", "그 분석 실행 기록이 없습니다")
    audit = {}
    try:
        meta = fsx.read_json(app.paths.analysis_time_file(rid, "run_meta.json"), None, want=dict) or {}
        a = meta.get("audit")
        if isinstance(a, dict):
            audit = {str(k): v for k, v in a.items() if isinstance(v, int) and not isinstance(v, bool)}
    except (ValueError, AttributeError):
        pass
    q = {"open": 0, "answered": 0}
    from lm27.ui.api_report import model_or_none
    model = model_or_none(app, rid, "full")
    answered = app.scratch.get("answered", {})
    for it in (model or {}).get("queue") or ():
        if not isinstance(it, dict):
            continue
        if it.get("status") == "answered" or it.get("qid") in answered:
            q["answered"] += 1
        else:
            q["open"] += 1
    return {"status": st, "labels": _label_counts(app, rid), "time_audit": audit,
            "warnings": [w for w in st.get("warnings") or () if isinstance(w, dict)], "queue": q}


def get_run(app, req):
    rid = req.groups[0]
    if not _RUN_RX.match(rid):
        raise ApiError(404, "no_run", "그 분석 실행 기록이 없습니다")
    return run_view(app, rid)


def _as_of_ok(s) -> bool:
    if not isinstance(s, str) or len(s) > 40:
        return False
    try:
        datetime.fromisoformat(s)
    except ValueError:
        return False
    return True


def post_run(app, req):
    b = req.body
    ai = bool(b.get("ai", False))
    rerun = b.get("rerun")
    if rerun:
        if not isinstance(rerun, str) or not _RUN_RX.match(rerun):
            raise ApiError(400, "bad_run", "다시 분석할 실행을 고르세요")
        stages = b.get("stages") or list(_quick_stages())
        if not isinstance(stages, list) or not stages or any(not isinstance(s, str) or not _STAGE_RX.match(s)
                                                             for s in stages):
            raise ApiError(400, "bad_stages", "다시 돌릴 단계를 고르세요")
        argv = ["analyze", "--rerun", rerun, "--stages", ",".join(stages)] + ([] if ai else ["--no-ai"])
        kind = "quick_reanalyze" if tuple(stages) == _quick_stages() and not ai else "analyze"
        return app.start_job(kind, argv)
    f, t = b.get("from"), b.get("to")
    ps = b.get("period_source")
    if f in (None, "") and t in (None, ""):
        # 날짜를 주지 않으면 화면과 같은 규칙(lm27.ui.period 단일원): 기간 출처가 없거나 default → 올해 1월 1일 ~ 오늘,
        # 분기·반기(q1~q4·h1·h2) → 그 기간. 날짜와 함께만 쓰는 출처(this_month 등)·아직 오지 않은 기간은 거절.
        rng = period.range_for_source(ps, _today(app))
        if rng is None:
            raise ApiError(400, "bad_period", "그 기간은 아직 오지 않았거나 시작·끝 날짜와 함께 보내야 하는 기간 출처입니다")
        f, t = rng
        if ps in (None, ""):
            ps = "default"
    if not (isinstance(f, str) and _DATE_RX.match(f) and isinstance(t, str) and _DATE_RX.match(t)):
        raise ApiError(400, "bad_date", "시작·끝 날짜를 넣어 주세요(둘 다 비우면 올해 1월 1일 ~ 오늘)")
    if t < f:
        raise ApiError(400, "bad_range", "끝 날짜가 시작보다 앞섭니다")
    argv = ["analyze", "--from", f, "--to", t]
    as_of = b.get("as_of")
    if as_of not in (None, ""):
        if not _as_of_ok(as_of):
            raise ApiError(400, "bad_as_of", "기준 시각 형식이 아닙니다(YYYY-MM-DDTHH:MM)")
        argv += ["--as-of", as_of]
    # 기간 출처(R RP8 — RPT-04 '기간 출처' 표시 근거). cli analyze --period-source·--period-months(W2 통합)
    if ps not in (None, ""):
        if ps not in _PERIOD_SOURCES:
            raise ApiError(400, "bad_period_source", "기간 출처 값이 아닙니다")
        argv += ["--period-source", ps]
    pm = b.get("period_months")
    if pm not in (None, ""):
        if isinstance(pm, bool) or not isinstance(pm, int) or not 1 <= pm <= 36:
            raise ApiError(400, "bad_period_months", "기간 개월 수는 1~36 입니다")
        argv += ["--period-months", str(pm)]
    if not ai:
        argv.append("--no-ai")
    return app.start_job("analyze", argv)


def post_current(app, req):
    rid = req.body.get("run_id")
    if not isinstance(rid, str) or not _RUN_RX.match(rid):
        raise ApiError(400, "bad_run", "결과를 고르세요")
    from lm27.pipeline.analyze import choose_current
    try:
        cur = choose_current(app.paths, app.cfg(), rid)
    except ValueError as e:
        raise ApiError(409, "not_choosable", str(e)) from None
    from lm27.ui import api_report
    api_report.forget_models(app)
    return {"ok": True, "current": cur}


# ───────────────────────────── 코파일럿(B §10.5) ─────────────────────────────
def get_bridge_status(app, req):
    from lm27.util import fsx
    cfg = app.cfg()
    mode = str(cfg["bridge.mode"])
    last = fsx.read_json(app.paths.bridge_probe_last(), None, want=dict) or {}
    env = last.get("env") if isinstance(last.get("env"), dict) else {}
    from lm27.ui.api_home import this_pc
    _pid, pc = this_pc(app)
    return {"mode": mode, "mode_ko": MODE_KO.get(mode, mode), "tier": env.get("tier") or "unknown",
            "web_exposed": bool(env.get("web_exposed", True)), "recommend": last.get("recommend"),
            "probe_ok": last.get("ok") if isinstance(last.get("ok"), bool) else None,
            "copilot_role": _ai_here(cfg, pc)}


def _ai_here(cfg, pc) -> bool:
    """이 PC 에서 분석하면 AI 판정을 하는가 — 분석과 같은 판단(``report.aiAnyPc`` 또는 pc.json 역할 copilot)."""
    from lm27.pipeline.analyze import ai_any_pc
    return ai_any_pc(cfg) or ("copilot" in (pc.get("roles") or ()) if pc else False)


def _manifest(app):
    from lm27.bridge.clock import default_clock
    from lm27.bridge.manual import Manifest
    return Manifest(app.paths, default_clock())


def get_manual(app, req):
    try:
        mf = _manifest(app)
    except (OSError, ValueError):
        return {"batches": [], "open": 0}
    rows = []
    for b in mf.batches:
        if b.get("state") != "open":
            continue
        rows.append({"seq": b.get("seq"), "stage": b.get("stage"), "items": len(b.get("items") or ()),
                     "in_chars": b.get("in_chars"), "state": b.get("state"), "created": b.get("created")})
    rows.sort(key=lambda r: int(r.get("seq") or 0))
    return {"batches": rows, "open": len(rows)}


def post_manual_copy(app, req):
    seq = req.body.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise ApiError(400, "bad_seq", "묶음 번호가 아닙니다")
    from lm27.bridge import fsio
    mf = _manifest(app)
    b = next((x for x in mf.open_batches() if x.get("seq") == seq), None)
    if b is None or not isinstance(b.get("file"), str):
        raise ApiError(404, "no_batch", "그 묶음이 없거나 이미 답을 받았습니다")
    text = fsio.read_text(fsio.child(mf.dir, b["file"]))
    if text is None:
        raise ApiError(404, "no_batch", "그 묶음의 글이 없습니다(보관 기간이 지났을 수 있습니다)")
    return {"ok": True, "seq": seq, "text": text}


def post_manual_import(app, req):
    text = req.body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "no_text", "붙여넣은 답이 없습니다")
    from lm27.bridge import runner
    from lm27.util.tz import new_run_id
    try:
        table = {s.id: s for s in runner.resolve_specs(None)}
    except LookupError:
        raise ApiError(409, "no_stages", "AI 단계 등록부가 아직 없어 반입하지 못했습니다") from None
    rt = runner.open_runtime(app.paths, new_run_id(), mode="manual")
    try:
        rep = runner.manual_import(text, rt=rt, specs=table)
    finally:
        runner.close_runtime(rt)
    keep = ("error", "open", "committed", "retry", "rc")
    out = {k: rep.get(k) for k in keep if k in rep}
    out["results"] = [{k: r.get(k) for k in ("stage", "seq", "status", "committed", "retry") if k in r}
                      for r in rep.get("results") or () if isinstance(r, dict)]
    out["rejected"] = len(rep.get("rejected") or ())
    out["ok"] = rep.get("rc") != 1
    return out


def post_front(app, req):
    raise ApiError(409, "no_window", "분석용 Edge 창이 지금 열려 있지 않습니다 — AI 분석을 실행하면 그 창이 뜨고, 로그인이 "
                   "필요하면 그 창에서 한 번 로그인하면 이어서 합니다")


ROUTES = (("GET", r"/api/analysis/runs", get_runs),
          ("GET", r"/api/analysis/run/([^/]+)", get_run),
          ("POST", r"/api/analysis/run", post_run),
          ("POST", r"/api/analysis/current", post_current),
          ("GET", r"/api/bridge/status", get_bridge_status),
          ("GET", r"/api/bridge/manual", get_manual),
          ("POST", r"/api/bridge/manual/copy", post_manual_copy),
          ("POST", r"/api/bridge/manual/import", post_manual_import),
          ("POST", r"/api/bridge/front", post_front))
