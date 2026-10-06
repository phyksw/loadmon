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


def current_view(app, runs: list | None = None) -> dict | None:
    """머리 띠 재료(R §2.4.3 · RPT-04): current.json + 라벨 출처 수(AI n · 규칙 n — current.json 에는 없다).
    출처 수는 그 실행의 보고서 모델 ``flags.label_sources``(AI 를 돌리지 않은 실행도 규칙 수가 있다), 모델이 없으면 브리지
    결과 봉투 수. 분석 시각이 없으면 run_status 의 끝(시작) 시각."""
    from lm27.ui.api_report import current, model_or_none
    cur = current(app)
    if not cur or not _RUN_RX.match(str(cur.get("run_id") or "")):
        return cur
    rid = cur["run_id"]
    out = dict(cur)
    if not isinstance(out.get("label_sources"), dict):
        m = model_or_none(app, rid, "full") or {}
        ls = (m.get("flags") or {}).get("label_sources") if isinstance(m.get("flags"), dict) else None
        if not isinstance(ls, dict) or not ls:
            row = next((r for r in runs or () if r.get("run_id") == rid and isinstance(r.get("label_sources"), dict)), None)
            ls = row["label_sources"] if row else _label_counts(app, rid)
        out["label_sources"] = ls
    if not out.get("built_at"):
        from lm27.report.inputs import analysis_time
        at = analysis_time(app.paths, rid, int(app.cfg()["time.tzOffsetMin"]))
        if at:
            out["built_at"] = at
    return out


def get_runs(app, req):
    today = _today(app)
    f, t = period.default_range(today)
    runs = list_runs(app)
    # months 는 이전 기본(최근 n개월, report.defaultRangeMonths)의 값 — 화면은 이제 period(올해 1월 1일 ~ 오늘)를 쓴다
    return {"runs": runs, "current": current_view(app, runs),
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
    """Copilot 상태 카드: 방식·등급·웹 노출·역할 + 마지막 탐침 한 줄·보정 한도(브리지 상태 파일 — 읽기만)."""
    from lm27.util import fsx
    out = _bridge_status(app, req)
    last = fsx.read_json(app.paths.bridge_probe_last(), None, want=dict) or {}
    prof = fsx.read_json(app.paths.bridge_profile(), None, want=dict) or {}
    out["last_probe"] = _probe_view(app, last, prof)
    out["limits"] = _limits_view(app, app.cfg(), prof)
    return out


def _bridge_status(app, req):
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


# 연결 진단(B §12.2) 결과 → 화면 문구. 막힌 첫 확인 항목의 코드 → 이유
PROBE_VERDICT = {"auto": "정상 — 자동으로 물을 수 있습니다", "manual": "자동 연결이 막혀 직접 붙여넣기 방식을 권합니다",
                 "none": "아직 연결하지 못했습니다"}
PROBE_WHY = {"edge_not_found": "Edge 를 찾지 못함", "policy_blocked": "회사 정책이 Edge 자동 연결을 막음",
             "policy_blocked_suspect": "회사 정책이 Edge 자동 연결을 막은 것으로 보임", "lock_busy": "다른 작업이 Edge 창을 쓰는 중",
             "port_exhausted": "디버그 포트를 잡지 못함", "launch_failed": "Edge 를 띄우지 못함",
             "profile_busy": "전용 프로필이 다른 Edge 창에서 열려 있음", "tab_lost": "Copilot 탭을 잃음",
             "login_required": "로그인 필요 — [분석용 Edge 창 앞으로]에서 한 번 로그인", "input_not_found": "Copilot 입력창을 찾지 못함",
             "no_input": "Copilot 입력창을 찾지 못함", "stub_env_set": "시험 모드", "web_mode": "웹 모드(업무 모드 아님)",
             "basic": "기본 등급 계정", "calib_none": "입출력 한도 보정값 없음"}


def _short_ts(app, s) -> str:
    """'…Z'·로컬 ISO → 근무 시간대 'MM-DD HH:MM'(모르면 '')."""
    v = _local_ts(app, s)
    return f"{v[5:10]} {v[11:16]}" if isinstance(v, str) and len(v) >= 16 and v[10] == "T" else ""


def _probe_view(app, last: dict, prof: dict) -> dict | None:
    """마지막 탐침(``probe_last.json`` — {ok, recommend, checks[]} + ``bridge_profile.health.last_probe`` 시각) → 화면 한 줄."""
    if not isinstance(last, dict) or not last.get("recommend"):
        return None
    at = (prof.get("health") or {}).get("last_probe") if isinstance(prof.get("health"), dict) else None
    rec = str(last.get("recommend") or "")
    bad = next((c for c in last.get("checks") or () if isinstance(c, dict) and not c.get("ok")), None)
    why = PROBE_WHY.get(str((bad or {}).get("code") or ""), str((bad or {}).get("code") or "")) if bad else ""
    when = _short_ts(app, at)
    text = (when + " · " if when else "") + PROBE_VERDICT.get(rec, "결과 미상") + (f"({why})" if why and rec != "auto" else "")
    return {"at": _local_ts(app, at) if at else None, "ok": last.get("ok") is True, "recommend": rec, "text_ko": text}


def _limits_view(app, cfg, prof: dict) -> dict | None:
    """보정 한도(B §7.14 ``bridge_profile.calibration``) — 지금 프로필의 최신 보정값(빠른 모델 우선). 유효 기간이 지났으면 stale."""
    from datetime import date

    from lm27.util import fsx
    try:
        pid = fsx.read_bytes(app.paths.bridge_profile_id()).decode("utf-8", "replace").strip()
    except OSError:
        pid = ""
    ents = [e for e in prof.get("calibration") or () if isinstance(e, dict) and isinstance(e.get("input_limit"), int)
            and isinstance(e.get("output_limit"), int)]
    mine = [e for e in ents if pid and str(e.get("profile_id") or "") == pid] or ents
    if not mine:
        return None
    fast = str(cfg["bridge.modelFast"])
    e = max(mine, key=lambda x: (str(x.get("model") or "") == fast, str(x.get("date") or "")))
    stale = False
    try:
        stale = (app.deps.now().date() - date.fromisoformat(str(e.get("date"))[:10])).days > int(cfg["bridge.calibrateTtlDays"])
    except ValueError:
        stale = True
    return {"in": int(e["input_limit"]), "out": int(e["output_limit"]), "pack_in": e.get("pack_in"),
            "pack_out": e.get("pack_out"), "date": str(e.get("date") or ""), "model": str(e.get("model") or ""),
            "stale": stale}


def _ai_here(cfg, pc) -> bool:
    """이 PC 에서 분석하면 AI 판정을 하는가 — 분석과 같은 판단(``report.aiAnyPc`` 또는 pc.json 역할 copilot)."""
    from lm27.pipeline.analyze import ai_any_pc
    return ai_any_pc(cfg) or ("copilot" in (pc.get("roles") or ()) if pc else False)


def _manifest(app):
    from lm27.bridge.clock import default_clock
    from lm27.bridge.manual import Manifest
    return Manifest(app.paths, default_clock())


# 직접 붙여넣기 묶음 상태(B §10 manifest)·반입 결과(B §7.11 상태) → 화면 이름
MANUAL_STATE_KO = {"open": "답 기다림", "answered": "답 반영함", "expired": "기간 지남", "superseded": "새 묶음으로 대체됨"}
IMPORT_STATUS_KO = {"ok": "반영", "partial": "일부 반영", "truncated": "잘림(다시 물음)", "echo": "질문을 되풀이함",
                    "format": "형식 오류", "empty": "빈 답", "service_error": "서비스 오류", "timeout": "시간 초과",
                    "refusal": "답 거절", "transport_fatal": "전송 실패"}
IMPORT_ERROR_KO = {"BR-MANUAL-NOENV": "붙여넣은 글에서 답(요청 번호가 든 JSON 블록)을 찾지 못했습니다 — Copilot 답 전체를 복사해 주세요"}


def _stage_names() -> dict:
    """브리지 단계 id → 한국어 제목(단계 등록부 ``title_ko`` — 단일원). 등록부를 읽지 못하면 빈 표."""
    from lm27.bridge import runner
    try:
        return {s.id: str(getattr(s, "title_ko", "") or s.id) for s in runner.resolve_specs(None)}
    except (LookupError, AttributeError):
        return {}


def get_manual(app, req):
    try:
        mf = _manifest(app)
    except (OSError, ValueError):
        return {"batches": [], "open": 0}
    names = _stage_names()
    rows = []
    for b in mf.batches:
        if b.get("state") != "open":
            continue
        n = len(b.get("items") or ())
        rows.append({"seq": b.get("seq"), "stage": b.get("stage"), "stage_ko": names.get(b.get("stage"), b.get("stage")),
                     "items": n, "items_n": n, "in_chars": b.get("in_chars"), "state": b.get("state"),
                     "state_ko": MANUAL_STATE_KO.get(b.get("state"), b.get("state")), "created": b.get("created")})
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
    names = _stage_names()
    results = []
    for r in rep.get("results") or ():
        if not isinstance(r, dict):
            continue
        x = {k: r.get(k) for k in ("rid", "stage", "seq", "status", "ok", "retry", "was") if k in r}
        x["stage_ko"] = names.get(r.get("stage"), r.get("stage"))
        x["status_ko"] = IMPORT_STATUS_KO.get(r.get("status"), r.get("status"))
        x["counts_ko"] = f"반영 {int(r.get('ok') or 0)} · 다시 물음 {int(r.get('retry') or 0)}"
        results.append(x)
    out["results"] = results
    out["rejected"] = len(rep.get("rejected") or ())
    out["ok"] = rep.get("rc") != 1
    if rep.get("error"):
        out["text_ko"] = IMPORT_ERROR_KO.get(rep["error"], "답을 반입하지 못했습니다")
    elif results:
        out["text_ko"] = (f"답 {len(results)}묶음을 반입했습니다(반영 {int(rep.get('committed') or 0)} · 다시 물음 "
                          f"{int(rep.get('retry') or 0)}) — 남은 묶음 {int(rep.get('open') or 0)}개")
    elif out["rejected"]:
        out["text_ko"] = "이미 반영했거나 목록에 없는 요청 번호의 답이라 반입하지 않았습니다"
    return out


# [분석용 Edge 창 앞으로] 결과 → 문구·상태(R §5.3 · B §10.5). 사람에게 시키는 일은 로그인 한 번뿐(§5.0.4)
FRONT_OK = {"front": "분석용 Edge 창을 앞으로 가져왔습니다 — 로그인이 필요하면 그 창에서 회사 계정으로 한 번 로그인해 주세요",
            "launched": "분석용 Edge 창을 새로 열었습니다 — 그 창에서 회사 계정으로 한 번 로그인해 주세요(Outlook 웹·Teams 웹·Copilot "
                        "이 같은 로그인을 씁니다). 로그인을 마치면 창을 닫아도 됩니다"}
FRONT_FAIL = {"edge_not_found": (409, "Edge 를 찾지 못했습니다 — Microsoft Edge 가 설치돼 있어야 분석용 창을 열 수 있습니다"),
              "policy_blocked": (409, "회사 정책이 Edge 자동 연결을 막아 분석용 창을 열지 못했습니다 — Copilot 은 직접 붙여넣기 방식으로 "
                                      "쓸 수 있습니다"),
              "profile_busy": (409, "분석용 Edge 프로필이 다른 Edge 창에서 열려 있습니다 — 작업 표시줄의 Edge 창을 확인해 주세요"),
              "lock_busy": (409, "다른 작업(분석·수집)이 분석용 Edge 창을 여는 중입니다 — 잠시 뒤 다시 눌러 주세요"),
              "port_exhausted": (409, "Edge 연결 포트를 잡지 못했습니다 — 잠시 뒤 다시 눌러 주세요"),
              "launch_failed": (500, "분석용 Edge 창을 띄우지 못했습니다 — 잠시 뒤 다시 눌러 주세요")}


def post_front(app, req):
    """분석용 Edge 창(브리지 전용 프로필 — Outlook 웹·Teams 웹·Copilot 공용) 앞으로. 떠 있으면 앞으로, 없으면 띄워 Microsoft 365
    로그인 화면을 연다(사람이 한 번 로그인). 자격 증명은 다루지 않는다."""
    r = app.deps.bridge_front(app.cfg())
    st = str((r or {}).get("state") or "")
    if st in FRONT_OK:
        return {"ok": True, "state": st, "port": (r or {}).get("port"), "restored": bool((r or {}).get("restored")),
                "text_ko": FRONT_OK[st]}
    code, msg = FRONT_FAIL.get(st, (500, "분석용 Edge 창을 앞으로 가져오지 못했습니다 — 잠시 뒤 다시 눌러 주세요"))
    raise ApiError(code, st or "front_failed", msg)


ROUTES = (("GET", r"/api/analysis/runs", get_runs),
          ("GET", r"/api/analysis/run/([^/]+)", get_run),
          ("POST", r"/api/analysis/run", post_run),
          ("POST", r"/api/analysis/current", post_current),
          ("GET", r"/api/bridge/status", get_bridge_status),
          ("GET", r"/api/bridge/manual", get_manual),
          ("POST", r"/api/bridge/manual/copy", post_manual_copy),
          ("POST", r"/api/bridge/manual/import", post_manual_import),
          ("POST", r"/api/bridge/front", post_front))
