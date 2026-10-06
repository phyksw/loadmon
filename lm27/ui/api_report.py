# -*- coding: utf-8 -*-
r"""개인 보고서 API(R §5.4 · §6 · §6.9 · §6.10 · §6.11 · §2.3.6) — 모델·드릴다운·확인 질문·분류 고치기·내보내기.

    GET  /api/report?run=&variant=full|redacted   report_model.json(run 생략 = current.json 이 가리키는 실행 — R §2.4.3)
    GET  /api/report/unit/<unit_id>?run=        단위업무 근거 드릴다운(§6.10.3) · GET /api/report/day/<YYYY-MM-DD>?run=  날짜(§6.10.2)
    POST /api/report/build {run_id}             report_build 작업 · POST /api/report/export {run_id, formats?, variants?}
    POST /api/report/export/open {dir}          만든 폴더 열기(ROOT\out\ 아래만)
    POST /api/queue/answer {qid, answer}        확인 질문 응답 → 수동 기록(증거 키) + 디바운스 빠른 재분석(RPT-48)
    POST /api/agentic/need/drop {need_id}       팀 묶음에서 그 니즈 빼기(TAB §2.5 overrides.json)
    GET  /api/hier/state · POST /api/hier/correction · /api/hier/proposal · /api/hier/codename · /api/hier/rule   분류(§6.11)

결과 선택(R §2.4.3 · RPT-03 · RPT-05): 화면은 ``current.json`` 하나만 본다. 없으면 404 ``no_current``, 가리키는 실행이 정리됐으면
404 ``run_missing``(다른 실행으로 조용히 바꾸지 않는다). 모델이 없거나 판이 다르면 ``report_build`` 를 자동 1회 띄우고 409
``rebuilding`` + ``job_id``(코파일럿 재질의 없음 — RP14).

확인 질문 응답(W §2.7 · R §6.9): 응답은 **업무 ID 가 아니라 증거 키**로 저장한다 — 질문의 ``evidence_keys`` · 단위업무 경계 키를
``ref_keys`` 에 담은 ``manual`` 레코드(``instr``·``report``·``work``·``must_link`` …)를 정제 파이프로 덧붙인다. 재분석으로 unit_id 가
바뀌어도 응답이 따라간다(RPT-48). 응답 뒤 ``ui.autoReanalyzeAfterAnswers`` 면 마지막 응답에서 ``ui.reanalyzeDebounceSec`` 뒤
빠른 재분석(``analyze --rerun <current> --stages classify,time,mining,report --no-ai``)을 한 번 띄운다(디바운스 — 여러 응답을 묶음).

분류 고치기(H §11.3 · RPT-49): ``corrections.jsonl``(추가 전용)에 **증거 키**(anchor·unit_keys·fam_keys·conv_keys — 서버가
시간 코어 단위업무에서 채움)와 ``set``·``scope`` 를 한 줄로 쓰고 같은 디바운스 빠른 재분석(분류부터)을 띄운다.
"""
from __future__ import annotations

import os
import re
import secrets
import threading

from lm27.ui.server import ApiError, ui_today

__all__ = ["ROUTES", "current", "forget_models", "model_or_none", "schedule_reanalyze", "unit_evidence"]

_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_UNIT_RX = re.compile(r"^u_[0-9A-Za-z_]{1,24}$")
_QID_RX = re.compile(r"^[0-9a-f]{12}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AT_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})T((?:[01]\d|2[0-3]):[0-5]\d)$")
_HHMM_RX = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_REF_RX = re.compile(r"^(?:[me][0-9a-f]{24}|[dh][0-9a-f]{16})$")
_KEY_RX = re.compile(r"^[a-z][0-9a-f]{8,32}$")
_GROUP_RX = re.compile(r"^grp:[0-9a-f]{12}$")
_PROJ_RX = re.compile(r"^(?:[PL]-\d{4}|UNC|NONE)$")
_VOCAB_RX = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$|^L_[A-Za-z0-9_]{1,16}$")
_NEED_RX = re.compile(r"^n_[0-9a-f]{6}$")
_PROP_RX = re.compile(r"^pr_\d{1,4}$")
_RULE_RX = re.compile(r"^L[KT]-[0-9A-Za-z_\-]{1,40}$")
_DOM_RX = re.compile(r"^[A-Z]{2,3}$")
VARIANTS = ("full", "redacted")
REANALYZE_KEY = "quick_reanalyze"
# 확인 질문 선택 → 수동 기록 man_kind(W §7.3 표). None = 기록 없이 응답만 남김(그대로 둠·승인·진행 중 등)
CHOICE_KIND = {"instr": "instr", "report": "report", "must_link": "must_link", "cannot_link": "cannot_link",
               "work": "work", "offsite": "offsite", "exclude": "exclude", "absence": "absence", "attended": "attended",
               "approve": None, "open": None, "not_started": None, "absent": None, "utc": None, "shared_doc": None,
               "same": None, "different": None}
SET_FIELDS = ("project", "field", "func", "wtype", "title")
SCOPES = ("this", "similar")
PROPOSAL_ACTIONS = ("accept", "map", "rename", "merge", "reject", "unreject")
CODENAME_ACTIONS = ("project", "customer", "ignore", "proceed", "skip")


# ───────────────────────────── 결과 선택·모델 ─────────────────────────────
def current(app) -> dict | None:
    from lm27.pipeline.analyze import read_current
    cur = read_current(app.paths)
    return dict(cur) if isinstance(cur, dict) else None


def _run_exists(app, rid: str) -> bool:
    try:
        return os.path.isdir(os.fspath(app.paths.analysis(rid)))
    except ValueError:
        return False


def forget_models(app) -> None:
    """화면의 모델 캐시와 [근거] 드릴다운 캐시를 바로 비운다(결과 선택·보고서 다시 만들기·분석/보고서 작업 끝 — W2 C18)."""
    with _model_lock:
        app.scratch.pop("_models", None)
    from lm27.report.drill import forget
    forget()


_model_lock = threading.Lock()


def model_or_none(app, rid: str, variant: str = "full") -> dict | None:
    """그 실행의 보고서 모델(파일 시각 기준 캐시 — 실행·변형마다 하나). 없거나 읽지 못하면 None."""
    from lm27.report import MODEL_FILE, load_model
    from lm27.report.inputs import report_file
    try:
        p = report_file(app.paths, rid, MODEL_FILE)
        st = os.stat(os.fspath(p))
    except (OSError, ValueError, RuntimeError):         # 모델 없음 · run_id 형식 · 경로 메서드 아직 없음(PathsMethodMissing — CR)
        return None
    key = (rid, variant, st.st_mtime_ns, st.st_size)
    with _model_lock:
        cache = app.scratch.setdefault("_models", {})
        hit = cache.get(variant)
        if hit is not None and hit[0] == key:
            return hit[1]
    try:
        m = load_model(rid, variant, paths=app.paths, cfg=app.cfg())
    except Exception:                                   # 깨진 모델·가림판 검사 실패 — 호출자가 '읽지 못함'으로
        return None
    with _model_lock:
        app.scratch.setdefault("_models", {})[variant] = (key, m)
    return m


def _pick_run(app, req) -> str:
    rid = req.q("run")
    if rid:
        if not _RUN_RX.match(rid):
            raise ApiError(400, "bad_run", "실행 ID 형식이 아닙니다")
        return rid
    cur = current(app)
    if not cur:
        raise ApiError(404, "no_current", "아직 분석 결과가 없습니다 — [분석] 화면에서 기간을 정해 실행하세요")
    return cur["run_id"]


def _rebuild(app, rid: str) -> None:
    """보고서 판이 다르거나 없음 — report_build 작업을 자동 1회(R §2.4.3) 띄우고 409 rebuilding + job_id.
    이미 띄운 작업이 끝났으면(그래도 모델이 없음·판 다름) 아무것도 하지 않는다 — 호출자가 있는 모델을 보인다."""
    asked = app.scratch.setdefault("_rebuild_asked", {})
    job = asked.get(rid)
    if job is not None:
        j = app.jobs.get(job)
        if j is not None and j.get("state") not in ("done", "partial", "failed", "cancelled"):
            raise ApiError(409, "rebuilding", "보고서를 새 형식으로 다시 만드는 중입니다", extra={"job_id": job})
        return
    try:
        r = app.start_job("report_build", ["report", "build", "--run", rid])
    except ApiError as e:
        if e.code == "busy":
            raise ApiError(409, "rebuilding", "보고서를 새 형식으로 다시 만드는 중입니다(다른 작업 뒤)") from None
        raise
    asked[rid] = r["job_id"]
    raise ApiError(409, "rebuilding", "보고서를 새 형식으로 다시 만드는 중입니다", extra={"job_id": r["job_id"]})


def get_report(app, req):
    from lm27.report import model_status
    variant = req.q("variant", "full")
    if variant not in VARIANTS:
        raise ApiError(400, "bad_variant", "변형은 full·redacted 중 하나입니다")
    rid = _pick_run(app, req)
    try:
        st = model_status(rid, paths=app.paths)
    except RuntimeError:                                # 보고서 경로 메서드가 아직 없음(PathsMethodMissing — CR)
        raise ApiError(503, "paths_method_missing", "이 판에서는 보고서 파일 위치를 아직 정하지 못했습니다") from None
    if st in ("missing", "stale"):
        if not _run_exists(app, rid):
            raise ApiError(404, "run_missing", "보던 결과가 정리되었습니다 — 분석 이력에서 고르세요", extra={"run_id": rid})
        _rebuild(app, rid)
    m = model_or_none(app, rid, variant)
    if m is None:
        if st == "missing":
            raise ApiError(404, "no_model", "이 결과의 보고서를 만들지 못했습니다 — 분석 화면에서 [보고서 다시 만들기]를 누르세요")
        raise ApiError(500, "model_unreadable", "보고서를 읽지 못했습니다 — 다시 읽으면 이어서 보입니다")
    cfg = app.cfg()
    out = dict(m)
    run = dict(out.get("run") or {})
    if not run.get("built_at"):                         # 머리 띠 '분석 MM-DD HH:MM' — 모델 파일 밖 값(G-R1), 응답에만
        from lm27.report.inputs import analysis_time
        at = analysis_time(app.paths, rid, int(cfg["time.tzOffsetMin"]))
        if at:
            run["built_at"] = at
            out["run"] = run
    if not run.get("chosen"):                           # '자동/직접 선택'도 모델 밖 값 — 현재 결과일 때만(W2 C01, V16)
        from lm27.report.inputs import chosen_of
        ch = chosen_of(app.paths, rid)
        if ch:
            run["chosen"] = ch
            out["run"] = run
    out["export_defaults"] = {"formats": list(cfg["report.export.formats"]), "variants": list(cfg["report.export.variants"])}
    out["table_max_rows"] = int(cfg["ui.tableMaxRows"])
    return out


def get_unit(app, req):
    from lm27.report.drill import unit_drill
    uid = req.groups[0]
    if not _UNIT_RX.match(uid):
        raise ApiError(404, "no_unit", "그 단위업무가 없습니다")
    rid = _pick_run(app, req)
    v = unit_drill(rid, uid, req.q("variant", "full") if req.q("variant") in VARIANTS else "full", paths=app.paths,
                   cfg=app.cfg())
    if v is None:
        raise ApiError(404, "no_unit", "그 단위업무가 이 결과에 없습니다")
    return v


def get_day(app, req):
    from lm27.report.drill import day_drill
    d = req.groups[0]
    if not _DATE_RX.match(d):
        raise ApiError(404, "no_day", "날짜 형식이 아닙니다")
    rid = _pick_run(app, req)
    v = day_drill(rid, d, req.q("variant", "full") if req.q("variant") in VARIANTS else "full", paths=app.paths,
                  cfg=app.cfg())
    if v is None:
        raise ApiError(404, "no_day", "그 날짜의 기록이 이 결과에 없습니다")
    return v


def post_build(app, req):
    rid = req.body.get("run_id")
    if not isinstance(rid, str) or not _RUN_RX.match(rid):
        raise ApiError(400, "bad_run", "실행을 고르세요")
    forget_models(app)
    return app.start_job("report_build", ["report", "build", "--run", rid])


def post_export(app, req):
    from lm27.cli import EXPORT_FORMATS, EXPORT_VARIANTS
    b = req.body
    rid = b.get("run_id") or (current(app) or {}).get("run_id")
    if not isinstance(rid, str) or not _RUN_RX.match(rid):
        raise ApiError(400, "bad_run", "내보낼 결과를 고르세요")
    cfg = app.cfg()
    fm = b.get("formats") or list(cfg["report.export.formats"])
    vs = b.get("variants") or list(cfg["report.export.variants"])
    if not isinstance(fm, list) or not fm or any(x not in EXPORT_FORMATS for x in fm):
        raise ApiError(400, "bad_formats", "형식은 html·csv·json 중에서 고르세요")
    if not isinstance(vs, list) or not vs or any(x not in EXPORT_VARIANTS for x in vs):
        raise ApiError(400, "bad_variants", "변형은 full·redacted 중에서 고르세요")
    return app.start_job("report_export", ["report", "export", "--run", rid, "--formats", ",".join(fm),
                                           "--variant", ",".join(vs)])


def post_export_open(app, req):
    d = req.body.get("dir")
    base = os.path.realpath(os.fspath(app.paths.out_dir()))
    if isinstance(d, str) and d.strip():
        p = os.path.realpath(os.path.join(os.fspath(app.paths.root), d.strip()) if not os.path.isabs(d) else d)
    else:
        p = os.path.join(base, "personal")
    if os.path.normcase(p) != os.path.normcase(base) and not os.path.normcase(p).startswith(os.path.normcase(base) + os.sep):
        raise ApiError(400, "outside_out", "내보내기 폴더(out) 밖은 열지 않습니다")
    if not os.path.isdir(p):
        raise ApiError(404, "no_dir", "그 폴더가 아직 없습니다 — 내보내기를 먼저 하세요")
    app.deps.open_folder(p)
    return {"ok": True}


def post_need_drop(app, req):
    """{need_id, drop: true} → 팀 묶음에서 그 니즈 빼기 · {drop: false} → 되돌리기(다시 팀에 올리기). 둘 다 다음 빌드부터.
    빼면 그 니즈가 든 대기 묶음은 다시 만들 때까지 보내지 않는다(``build.drop_need`` — C16). 팀 묶음 미리보기에서 부르면
    (``item`` = 대기열 항목) 그 기간 묶음을 다시 만드는 작업을 띄운다(``job_id`` — ``api_team.rebuild_after_mask``)."""
    nid = req.body.get("need_id")
    if not isinstance(nid, str) or not _NEED_RX.match(nid):
        raise ApiError(400, "bad_need", "니즈 ID 형식이 아닙니다")
    drop = req.body.get("drop", True)
    if not isinstance(drop, bool):
        raise ApiError(400, "bad_drop", "drop 은 true(빼기)·false(다시 올리기)입니다")
    item = req.body.get("item")
    if item is not None and not isinstance(item, str):
        raise ApiError(400, "bad_item", "대기열 항목 이름이 아닙니다")
    from lm27.team.build import drop_need, keep_need
    r = drop_need(app.paths, nid) if drop else keep_need(app.paths, nid)
    if r.get("rc") == 1:
        raise ApiError(400, "bad_need", r.get("message") or "니즈 ID 형식이 아닙니다")
    out = {"ok": True, "dropped": drop, "changed": r.get("rc") == 0, "stale_n": len(r.get("stale") or ()),
           "text_ko": r.get("message")}
    if r.get("rc") == 0 and item:
        from lm27.ui.api_team import rebuild_after_mask
        out.update(rebuild_after_mask(app, r, item))
    return out


# ───────────────────────────── 빠른 재분석(디바운스) ─────────────────────────────
def schedule_reanalyze(app) -> str | None:
    """마지막 응답·수정에서 ``ui.reanalyzeDebounceSec`` 뒤 빠른 재분석 1회(같은 키로 묶음). 자동이 꺼져 있으면 None."""
    cfg = app.cfg()
    if not bool(cfg["ui.autoReanalyzeAfterAnswers"]):
        return None
    from lm27.pipeline.stages import QUICK_RERUN

    def argv():
        cur = current(app)
        if not cur:
            return None
        return ["analyze", "--rerun", cur["run_id"], "--stages", ",".join(QUICK_RERUN), "--no-ai"]
    job = app.jobs.schedule("quick_reanalyze", argv, delay_s=float(cfg["ui.reanalyzeDebounceSec"]), key=REANALYZE_KEY)
    return job.job_id


# ───────────────────────────── 증거 키 ─────────────────────────────
def _tasks(app, rid: str) -> dict:
    """시간 코어 단위업무 표(tasks.json) — unit_id → 행. 증거 키(첫 근거·경계·문서군·대화)를 얻는다."""
    from lm27.util import fsx
    try:
        rows = fsx.read_json(app.paths.analysis_time_file(rid, "tasks.json"), None, want=list) or []
    except (ValueError, AttributeError):
        rows = []
    return {r.get("unit_id"): r for r in rows if isinstance(r, dict) and isinstance(r.get("unit_id"), str)}


def unit_evidence(app, rid: str, unit_id: str, model: dict | None = None) -> dict:
    """단위업무의 증거 키(H §11.3 target · W §2.7 ref_keys 재료) — anchor·unit_keys·fam_keys·conv_keys."""
    t = _tasks(app, rid).get(unit_id) or {}
    anchor = t.get("first_key") if isinstance(t.get("first_key"), str) else ""
    ukeys = {anchor} if anchor else set()
    for c in t.get("cycles") or ():
        if isinstance(c, dict):
            for k in ("s_ref", "e_ref"):
                if isinstance(c.get(k), str) and _KEY_RX.match(c[k]):
                    ukeys.add(c[k])
    fams = sorted(k for k in (t.get("docs") or {}) if isinstance(k, str) and _KEY_RX.match(k))
    convs = sorted({t["conv"]} if isinstance(t.get("conv"), str) and _KEY_RX.match(t["conv"]) else set())
    if model is not None:                               # 모델 단위업무의 경계 키(전체판) — 시간 결과가 없을 때 보충
        mu = next((u for u in model.get("units") or () if isinstance(u, dict) and u.get("unit_id") == unit_id), None)
        for c in (mu or {}).get("cycles") or ():
            for k in ("s_key", "e_key"):
                if isinstance(c, dict) and isinstance(c.get(k), str) and _KEY_RX.match(c[k]):
                    ukeys.add(c[k])
    return {"anchor": anchor, "unit_keys": sorted(x for x in ukeys if x), "fam_keys": fams, "conv_keys": convs}


def _refs_of(ev: dict, extra=()) -> list:
    """수동 레코드 ref_keys(정제기 형식 — m/e+24hex · d/h+16hex, 최대 5)."""
    out = []
    for k in list(extra) + [ev.get("anchor")] + list(ev.get("unit_keys") or ()) + list(ev.get("conv_keys") or ()) + \
            list(ev.get("fam_keys") or ()):
        if isinstance(k, str) and _REF_RX.match(k) and k not in out:
            out.append(k)
    return out[:5]


# ───────────────────────────── 확인 질문 ─────────────────────────────
def _queue_item(model, qid):
    return next((q for q in (model or {}).get("queue") or () if isinstance(q, dict) and q.get("qid") == qid), None)


def post_answer(app, req):
    from lm27.ui.api_collect import manual_raw, write_manual
    b = req.body
    ans = b.get("answer")
    if not isinstance(ans, dict):
        raise ApiError(400, "bad_answer", "응답을 고르세요")
    choice = ans.get("choice")
    if choice not in CHOICE_KIND:
        raise ApiError(400, "bad_choice", "응답을 고르세요")
    qid = b.get("qid")
    cur = current(app)
    if not cur:
        raise ApiError(409, "no_current", "분석 결과가 없어 응답을 받을 수 없습니다")
    rid = cur["run_id"]
    model = model_or_none(app, rid, "full") or {}
    item = None
    if qid is not None:
        if not isinstance(qid, str) or not _QID_RX.match(qid):
            raise ApiError(400, "bad_qid", "질문 번호 형식이 아닙니다")
        item = _queue_item(model, qid)
        if item is None:
            raise ApiError(404, "no_question", "그 질문이 지금 결과에 없습니다 — 다시 분석했을 수 있습니다")
    elif b.get("code") != "Q12":
        raise ApiError(400, "bad_qid", "질문 번호가 없습니다")
    kind = CHOICE_KIND[choice]
    raws = []
    if kind is not None:
        raws.append(_answer_raw(app, rid, model, item or {"code": "Q12", "target": None}, kind, ans, manual_raw))
    if raws:
        write_manual(app, raws)
    answered = app.scratch.setdefault("answered", {})
    if qid:
        answered[qid] = app.deps.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    app.scratch["answers_pending"] = int(app.scratch.get("answers_pending", 0)) + 1
    job = schedule_reanalyze(app)
    out = {"ok": True, "stored": len(raws)}
    if job:
        out["reanalyze_job"] = job
    return out


def _answer_raw(app, rid, model, item, kind, ans, manual_raw):
    """응답 → 수동 레코드 원시 행. 시각(at)·구간(a·b)·시간(hours)·대상 업무(unit) — 증거 키는 질문·업무에서."""
    target = item.get("target")
    extra = [k for k in item.get("evidence_keys") or () if isinstance(k, str)]
    ev = unit_evidence(app, rid, target, model) if isinstance(target, str) and target.startswith("u_") else {}
    d = ans.get("d") if isinstance(ans.get("d"), str) and _DATE_RX.match(ans["d"]) else None
    start = end = None
    at = ans.get("at")
    if isinstance(at, str):
        m = _AT_RX.match(at)
        if not m:
            raise ApiError(400, "bad_at", "시각 형식이 아닙니다(YYYY-MM-DDTHH:MM)")
        d, start = m.group(1), m.group(2)
    a, bb = ans.get("a"), ans.get("b")
    if a or bb:
        if not (isinstance(a, str) and _HHMM_RX.match(a) and isinstance(bb, str) and _HHMM_RX.match(bb)) or bb <= a:
            raise ApiError(400, "bad_span", "시작·끝 시각을 확인해 주세요")
        start, end = a, bb
    hours = ans.get("hours")
    if hours is not None and (not isinstance(hours, (int, float)) or isinstance(hours, bool) or not 0.25 <= hours <= 16):
        raise ApiError(400, "bad_hours", "시간은 0.25~16 입니다")
    units = []
    if isinstance(ans.get("unit"), str):
        units.append(ans["unit"])
    for u in ans.get("units") or ():
        if isinstance(u, str):
            units.append(u)
    first, rest = [], []                                 # 고른 업무마다 첫 근거 키를 먼저(ref_keys 최대 5 — 업무가 빠지지 않게)
    for u in units:
        if not _UNIT_RX.match(u):
            raise ApiError(400, "bad_unit", "업무를 다시 골라 주세요")
        ev2 = unit_evidence(app, rid, u, model)
        keys = [ev2.get("anchor")] + list(ev2.get("unit_keys") or ()) + list(ev2.get("fam_keys") or ())
        keys = [k for k in keys if isinstance(k, str) and _REF_RX.match(k)]
        first += keys[:1]
        rest += keys[1:]
    extra = extra + first + rest
    if kind in ("must_link", "cannot_link") and not units and not ev:
        raise ApiError(400, "bad_unit", "같이 볼 업무를 골라 주세요")
    if d is None:
        d = str(item.get("date") or "")[:10]
        if not _DATE_RX.match(d):
            d = ui_today(app).isoformat()
    proj = None
    pv = ans.get("project")
    if isinstance(pv, str) and _PROJ_RX.match(pv):
        proj = pv
    return manual_raw(app, kind=kind, d=d, start=start, end=end, hours=float(hours) if hours is not None else None,
                      project=proj, refs=_refs_of(ev, extra))


# ───────────────────────────── 분류(H §6.11) ─────────────────────────────
def _hier_at(app) -> str:
    from lm27.util.tz import fmt_offset, to_local
    off = int(app.cfg()["time.tzOffsetMin"])
    return to_local(app.deps.now(), off).strftime("%Y-%m-%dT%H:%M:%S") + fmt_offset(off)


def post_correction(app, req):
    from lm27.util import fsx
    b = req.body
    st = b.get("set")
    if not isinstance(st, dict) or not st or any(k not in SET_FIELDS + ("pick",) for k in st):
        raise ApiError(400, "bad_set", "고칠 항목을 고르세요(과제·분야·기능·유형·제목)")
    st = dict(st)
    fq = b.get("from_queue")
    if "pick" in st:                                    # H02 규칙·AI 충돌 — 고른 쪽의 과제(질문 proposal.rule|ai)
        pick = st.pop("pick")
        item = _queue_item(model_or_none(app, (current(app) or {}).get("run_id", ""), "full"),
                           str(fq or "").split(":")[-1])
        proj = ((item or {}).get("proposal") or {}).get(pick) if pick in ("rule", "ai") else None
        if not isinstance(proj, str) or not proj:
            raise ApiError(409, "no_pick", "그 질문의 후보 과제를 찾지 못했습니다 — 다시 분석했을 수 있습니다")
        st["project"] = proj
        if not st:
            raise ApiError(400, "bad_set", "고칠 항목을 고르세요")
    clean = {}
    for k, v in st.items():
        if k == "project":
            if v == "__not_work__":
                v = "NONE"
            if v == "__new__":
                raise ApiError(409, "new_project", "새 과제는 [분류] 화면의 제안에서 [내 과제로 받기]로 만들 수 있습니다")
            if not isinstance(v, str) or not _PROJ_RX.match(v):
                raise ApiError(400, "bad_project", "과제를 다시 골라 주세요")
        elif k == "title":
            if not isinstance(v, str) or not v.strip() or len(v) > 40 or any(ord(c) < 32 for c in v):
                raise ApiError(400, "bad_title", "제목은 40자 이하로 넣어 주세요")
            v = v.strip()
        elif not isinstance(v, str) or not _VOCAB_RX.match(v):
            raise ApiError(400, "bad_code", "분야·기능·유형은 어휘 코드로 고르세요")
        clean[k] = v
    scope = b.get("scope") or "similar"
    if scope not in SCOPES:
        raise ApiError(400, "bad_scope", "범위는 이 업무만·비슷한 업무도 중 하나입니다")
    cur = current(app)
    if not cur:
        raise ApiError(409, "no_current", "분석 결과가 없어 분류를 고칠 수 없습니다")
    target = {"group": "", "anchor": "", "unit_keys": [], "fam_keys": [], "conv_keys": [], "dir_keys": []}
    uid, grp = b.get("unit_id"), b.get("group")
    if isinstance(uid, str) and _GROUP_RX.match(uid):  # 분류 질문(H01·H02·H05·H06)의 대상은 군집 키
        grp, uid = uid, None
    if isinstance(grp, str) and grp:
        if not _GROUP_RX.match(grp):
            raise ApiError(400, "bad_group", "군집 형식이 아닙니다")
        target["group"] = grp
    if isinstance(uid, str) and uid:
        if not _UNIT_RX.match(uid):
            raise ApiError(400, "bad_unit", "단위업무를 다시 골라 주세요")
        ev = unit_evidence(app, cur["run_id"], uid, model_or_none(app, cur["run_id"], "full"))
        target.update(ev)
    if not (target["group"] or target["anchor"] or target["unit_keys"] or (target["fam_keys"] and target["conv_keys"])):
        raise ApiError(404, "no_evidence", "그 업무의 근거 키를 찾지 못했습니다 — 다시 분석한 뒤 고쳐 주세요")
    rec = {"at": _hier_at(app), "id": "c_" + secrets.token_hex(4), "target": target, "set": clean, "scope": scope,
           "from_queue": fq if isinstance(fq, str) and len(fq) <= 40 else None, "note": ""}
    fsx.append_line(app.paths.hier_local_file("corrections.jsonl"), fsx.canon_bytes(rec).decode("utf-8"))
    app.scratch["answers_pending"] = int(app.scratch.get("answers_pending", 0)) + 1
    out = {"ok": True, "id": rec["id"]}
    job = schedule_reanalyze(app)
    if job:
        out["reanalyze_job"] = job
    return out


def post_proposal(app, req):
    from lm27.hier.proposals import ProposalQueue
    b = req.body
    pid, act = b.get("proposal_id"), b.get("action")
    if not isinstance(pid, str) or not _PROP_RX.match(pid) or act not in PROPOSAL_ACTIONS:
        raise ApiError(400, "bad_proposal", "제안과 처리를 고르세요")
    q = ProposalQueue.for_paths(app.paths)
    at = _hier_at(app)
    out = {"ok": True}
    try:
        if act == "accept":
            # [내 과제로 받기] 폼: 영역(domain) + 알아볼 낱말(keywords — 옛 화면은 words 로 보냈다, 둘 다 받는다)
            kws = b.get("keywords") if b.get("keywords") is not None else b.get("words")
            if kws is not None and (not isinstance(kws, list) or any(not isinstance(w, str) for w in kws)):
                raise ApiError(400, "bad_keywords", "알아볼 낱말은 글자 목록입니다")
            dom = b.get("domain")
            if dom not in (None, "") and (not isinstance(dom, str) or not _DOM_RX.match(dom)):
                raise ApiError(400, "bad_domain", "업무 영역을 다시 골라 주세요")
            out["project"] = q.accept_local(pid, [w.strip() for w in kws or () if w.strip()], paths=app.paths, at=at,
                                            dom=dom or None)
        elif act == "map":
            proj = b.get("project")
            if not isinstance(proj, str) or not _PROJ_RX.match(proj):
                raise ApiError(400, "bad_project", "같은 과제를 골라 주세요")
            q.map_to(pid, proj, at=at)
        elif act == "rename":
            q.rename(pid, str(b.get("name") or b.get("label") or ""), at=at)
        elif act == "merge":
            into = b.get("into")
            if not isinstance(into, str) or not _PROP_RX.match(into):
                raise ApiError(400, "bad_proposal", "합칠 제안을 골라 주세요")
            q.merge(pid, into, at=at)
        elif act == "reject":
            q.reject(pid, at=at)
        else:
            q.unreject(pid, at=at)
    except ValueError:
        raise ApiError(409, "proposal_state", "그 제안은 지금 그 처리를 할 수 없습니다 — 화면을 다시 읽어 주세요") from None
    q.save()
    job = schedule_reanalyze(app)
    if job:
        out["reanalyze_job"] = job
    return out


def post_codename(app, req):
    from lm27.hier.proposals import mark_codename_review
    b = req.body
    cand, act = b.get("cand"), b.get("action")
    if act not in CODENAME_ACTIONS:
        raise ApiError(400, "bad_action", "처리를 고르세요")
    if act in ("project", "customer", "ignore") and (not isinstance(cand, str) or not 2 <= len(cand.strip()) <= 40):
        raise ApiError(400, "bad_cand", "후보를 고르세요")
    try:
        if act == "ignore":
            cr = mark_codename_review(paths=app.paths, ignore=[cand])
        elif act == "proceed":
            cr = mark_codename_review(paths=app.paths, done_at=_hier_at(app))
        elif act == "skip":
            cr = mark_codename_review(paths=app.paths, skipped=True)
        elif act == "project":
            from lm27.hier.proposals import ProposalQueue
            from lm27.ui.api_team import registry_view
            reg, _st = registry_view(app)
            if reg is None:
                raise ApiError(409, "no_registry", "레지스트리를 읽지 못했습니다")
            q = ProposalQueue.for_paths(app.paths)
            lid = q.from_codename(cand, str(b.get("domain") or "DEV"), reg, paths=app.paths, at=_hier_at(app))
            q.save()
            cr = mark_codename_review(paths=app.paths, ignore=[cand])
            return {"ok": True, "project": lid, "codename_review": cr}
        else:
            cid, word, added = _add_customer(app, cand)
            cr = mark_codename_review(paths=app.paths, ignore=[cand])
            text = (f"'{word}' 을(를) 고객사 이름({cid})으로 등록했습니다 — 다음 [수집]부터 정제기가 가립니다" if added else
                    f"'{word}' 은(는) 이미 고객사 이름({cid})입니다")
            return {"ok": True, "customer": cid, "codename_review": cr, "text_ko": text}
    except ValueError:
        raise ApiError(409, "local_registry", "개인 레지스트리를 고치지 못했습니다 — 다시 누르면 이어서 합니다") from None
    return {"ok": True, "codename_review": cr}


def _add_customer(app, cand: str) -> tuple[str, str, bool]:
    """코드네임 검토 [고객사 이름](H §8.1) → 개인 설정 ``privacy.customers`` 에 ``{"id": "C9xx", "names": [후보]}`` 를 더한다
    (설정 단일 검증 ``save_settings`` — 정제기가 다음 수집부터 ``[고객사:C9xx]`` 로 가린다). id 는 팀 레지스트리 고객사와
    겹치지 않는 C901~C999. 이미 같은 이름이 있으면 쓰지 않는다. 반환 (id, 정규화한 이름, 새로 더했는가)."""
    import unicodedata
    from collections.abc import Mapping

    from lm27.ui.api_settings import save_settings
    from lm27.ui.api_team import registry_view
    word = " ".join(unicodedata.normalize("NFKC", cand).split())
    cur = []
    for c in app.cfg()["privacy.customers"] or ():          # 설정 값은 얼린 형(튜플·읽기 전용 사전)일 수 있다
        if isinstance(c, Mapping):
            cur.append({"id": str(c.get("id") or ""), "names": [str(x) for x in c.get("names") or ()],
                        "domains": [str(x) for x in c.get("domains") or ()]})
    for c in cur:
        if any(n.casefold() == word.casefold() for n in c["names"]):
            return c["id"], word, False
    reg, _st = registry_view(app)
    used = {c["id"] for c in cur} | {str((c or {}).get("id") or "") for c in (getattr(reg, "customers", ()) or ())
                                     if isinstance(c, Mapping)}
    cid = next((f"C9{n:02d}" for n in range(1, 100) if f"C9{n:02d}" not in used), None)
    if cid is None:
        raise ApiError(409, "customer_full", "개인 고객사 이름 자리(C901~C999)가 다 찼습니다 — 설정 › 개인정보에서 정리해 주세요")
    save_settings(app, {"privacy.customers": cur + [{"id": cid, "names": [word], "domains": []}]})
    return cid, word, True


def post_rule(app, req):
    from lm27.hier.learn import load_learned, save_learned
    b = req.body
    rid, act = b.get("rule_id"), b.get("action")
    if not isinstance(rid, str) or not _RULE_RX.match(rid) or act not in ("off", "on", "copy_team"):
        raise ApiError(400, "bad_rule", "규칙과 처리를 고르세요")
    lr = load_learned(app.paths)
    rule = next((r for r in lr["rules"] if r.get("id") == rid), None)
    if rule is None:
        raise ApiError(404, "no_rule", "그 학습 규칙이 없습니다")
    if act == "copy_team":
        reg = _registry(app)
        v = _rule_view(rule, reg, _HierRefs(app, reg))
        txt = f"팀 규칙 제안: {v['kind_ko']} {v['cond']} → {v['result']}(적중 {v['hits']}건 · 학습 규칙 {rid})"
        return {"ok": True, "text_ko": txt}
    rule["status"] = "active" if act == "on" else "off"
    save_learned(app.paths, lr["rules"], lr["learned_from"])
    return {"ok": True, "status": rule["status"]}


# 분류 화면 이름표(R §6.11 · H §7.3 · §11.4) — 코드는 툴팁·CSV 에만, 화면은 이름
PROP_STATE_KO = {"pending": "검토 대기", "accepted_local": "내 과제로 받음", "mapped": "기존 과제에 연결됨",
                 "rejected": "거절함", "merged": "다른 제안에 합쳐짐"}
PROP_SRC_KO = {"task_label": "AI", "bootstrap": "부트스트랩", "user": "내가 만듦", "codename_review": "코드네임 검토"}
RULE_STATE_KO = {"active": "켜짐", "candidate": "후보(같은 과제로 한 번 더 고치면 켜짐)", "off": "끔",
                 "retired": "은퇴(맞힌 비율이 낮음)", "superseded": "대체됨(나중 수정이 이김)"}
RULE_KIND_KO = {"conv": "대화방", "fam": "문서", "repo": "저장소", "dir": "폴더", "token": "낱말", "app": "앱"}
SET_KO = {"project": "과제", "field": "분야", "func": "기능", "wtype": "유형", "title": "제목"}
_VOCAB_OF = {"field": "fields", "func": "functions", "wtype": "activity_types"}
NOTICE_DAYS = 14                                         # 팀 과제 자동 연결 알림을 보이는 기간(H §7.6 화면 알림)


def _registry(app):
    from lm27.ui.api_team import registry_view
    return registry_view(app)[0]


def _parse_at(s):
    from datetime import UTC, datetime
    if not isinstance(s, str) or not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=UTC)


class _HierRefs:
    """분류 화면이 로컬 키를 이름으로 풀 때 쓰는 지금 결과(전체판 모델 — 문서 이름·단위업무 제목, tasks.json — 대화 키)."""

    def __init__(self, app, reg):
        self.app, self.reg = app, reg
        cur = current(app)
        self.rid = cur["run_id"] if cur else None
        self.model = (model_or_none(app, self.rid, "full") or {}) if self.rid else {}
        self._tasks = None
        refs = self.model.get("refs") or {}
        self.docs = {str(v.get("key")): str(v.get("name") or "") for v in (refs.get("docs") or {}).values()
                     if isinstance(v, dict) and v.get("key")}
        self.titles = {u.get("unit_id"): str(u.get("title") or "") for u in self.model.get("units") or ()
                       if isinstance(u, dict)}

    def tasks(self) -> dict:
        if self._tasks is None:
            self._tasks = _tasks(self.app, self.rid) if self.rid else {}
        return self._tasks

    def project(self, pid) -> str:
        pv = self.reg.project(pid) if self.reg is not None and hasattr(self.reg, "project") else None
        return str(getattr(pv, "name", "") or pid) if pv is not None else str(pid)

    def vocab(self, axis: str, code) -> str:
        it = ((getattr(self.reg, "vocab", None) or {}).get(_VOCAB_OF.get(axis, "")) or {}).get(code)
        return str(getattr(it, "name", "") or code)

    def conv(self, key) -> str:
        """대화 키 → 그 대화가 근거인 단위업무 제목(첫 하나) — 대화방 정제 제목은 결과 파일에 없다."""
        for uid, t in sorted(self.tasks().items()):
            if t.get("conv") == key and self.titles.get(uid):
                return f"'{self.titles[uid]}' 업무의 대화"
        return "이번 결과에 없는 대화"


def _rule_view(r: dict, reg, hx: _HierRefs) -> dict:
    """학습 규칙 한 줄(H §11.4 화면) — 종류·조건·결과를 이름으로. 로컬 키 자체는 보이지 않는다."""
    cond = r.get("if") if isinstance(r.get("if"), dict) else {}
    then = r.get("then") if isinstance(r.get("then"), dict) else {}
    ck, cv = next(iter(sorted(cond.items())), ("", ""))
    tk, tv = next(iter(sorted(then.items())), ("", ""))
    if ck == "token":
        ctext = f"'{cv}' 낱말"
    elif ck == "app":
        from lm27.report.resolve import Resolver
        ctext = Resolver("full").app(str(cv))
    elif ck in ("fam", "repo"):
        ctext = hx.docs.get(str(cv)) or ("이번 결과에 없는 " + ("저장소" if ck == "repo" else "문서"))
    elif ck == "conv":
        ctext = hx.conv(cv)
    elif ck == "dir":
        ctext = "같은 폴더의 문서"
    else:
        ctext = str(cv or "")
    if tk == "project":
        rtext = hx.project(tv)
    elif tk in _VOCAB_OF:
        rtext = f"{SET_KO[tk]} {hx.vocab(tk, tv)}"
    else:
        rtext = str(tv or "")
    st = str(r.get("status") or "")
    return {"rule_id": r.get("id"), "kind": ck or r.get("kind"), "kind_ko": RULE_KIND_KO.get(ck, str(r.get("kind") or "")),
            "cond": ctext, "result": rtext, "state": st, "state_ko": RULE_STATE_KO.get(st, st),
            "hits": int(r.get("hits") or 0), "agree": int(r.get("agree") or 0), "disagree": int(r.get("disagree") or 0),
            "reason": str(r.get("reason") or "")}


def _prop_view(it: dict) -> dict:
    """새 과제 제안 한 줄(H §7.3) — 매 실행 다시 센 근거(n_units·effort_min·first_at·last_at)와 이름표."""
    st = str(it.get("status") or "")
    hist = [h for h in it.get("history") or () if isinstance(h, dict)]
    srcs = [s for s in it.get("sources") or () if isinstance(s, dict)]
    src = str(srcs[0].get("from") or "") if srcs else str((hist[0] if hist else {}).get("by") or "")
    st_ko = PROP_STATE_KO.get(st, st)
    if st == "mapped" and any(h.get("event") == "mapped" and h.get("by") == "registry" for h in hist):
        st_ko = "팀 과제로 연결됨"
    return {"proposal_id": it.get("proposal_id"), "name": it.get("label"), "domain_guess": it.get("domain_guess"),
            "units": int(it.get("n_units") or 0), "effort_min": int(it.get("effort_min") or 0),
            "first": it.get("first_at"), "last": it.get("last_at"), "src": src, "src_ko": PROP_SRC_KO.get(src, src),
            "state": st, "state_ko": st_ko, "mapped_to": it.get("mapped_to"), "merged_into": it.get("merged_into"),
            "local_project": it.get("local_project")}


def _notices(items, hx: _HierRefs, now) -> list:
    """팀 레지스트리를 받아 자동으로 팀 과제에 연결된 제안 알림(H §7.6) — 최근 NOTICE_DAYS 일 안의 연결만."""
    out = []
    for it in items:
        if it.get("status") != "mapped":
            continue
        ev = next((h for h in reversed(it.get("history") or ()) if isinstance(h, dict) and h.get("event") == "mapped"),
                  None)
        at = _parse_at((ev or {}).get("at"))
        if ev is None or ev.get("by") != "registry" or at is None or (now - at).days > NOTICE_DAYS:
            continue
        pid = str(ev.get("project") or it.get("mapped_to") or "")
        name = hx.project(pid)
        out.append({"proposal_id": it.get("proposal_id"), "project": pid,
                    "text_ko": f"제안 '{it.get('label')}' → 팀 과제 {pid}" + (f"({name})" if name != pid else "") + " 로 연결됨"})
    return out


def _unapplied(app, hx: _HierRefs, corrections: list) -> list:
    """미적용 수정(H §11.3) — 지금 결과의 어느 단위업무에도 맞지 않는 수정 기록. 분석과 같은 대응 함수
    (``lm27.hier.learn.match_units``)를 tasks.json 의 증거 키(첫 근거·경계·문서군·대화)와 군집(groups.json)으로 다시 돈다.
    분석 뒤에 쓴 기록은 아직 적용 전(다음 분석 대기)이라 넣지 않는다. 분석이 '미적용 0' 이라고 남겼으면 빈 목록."""
    if not hx.rid or not corrections:
        return []
    from lm27.hier.learn import match_units
    from lm27.pipeline.analyze import read_run_status
    from lm27.report.inputs import hier_file
    from lm27.util import fsx
    try:
        meta = fsx.read_json(hier_file(app.paths, hx.rid, "hier_meta.json"), None, want=dict) or {}
        groups = fsx.read_json(hier_file(app.paths, hx.rid, "groups.json"), None, want=dict) or {}
    except (OSError, ValueError, RuntimeError):
        meta, groups = {}, {}
    warns = [str(w) for w in meta.get("warnings") or () if isinstance(w, str)]
    if meta and not any(w.startswith("unapplied_corrections:") for w in warns):
        return []
    st = read_run_status(app.paths, hx.rid) or {}
    started = _parse_at(st.get("started"))
    units = {}
    for uid, t in hx.tasks().items():
        bk = {c.get(k) for c in t.get("cycles") or () if isinstance(c, dict) for k in ("s_ref", "e_ref")}
        units[uid] = {"first_key": t.get("first_key") or "", "bkeys": {x for x in bk if isinstance(x, str) and x},
                      "fams": {k: 1 for k in (t.get("docs") or {}) if isinstance(k, str)},
                      "convs": {t["conv"]} if isinstance(t.get("conv"), str) and t.get("conv") else set()}
    group_of = {m: k for k, g in groups.items() if isinstance(g, dict) for m in g.get("members") or ()}
    out = []
    for c in corrections:
        at = _parse_at(c.get("at"))
        if started is not None and at is not None and at > started:
            continue
        if match_units(c, units, group_of):
            continue
        tg = c.get("target") if isinstance(c.get("target"), dict) else {}
        n_keys = len({x for k in ("unit_keys", "fam_keys", "conv_keys", "dir_keys") for x in tg.get(k) or ()} |
                     ({tg["anchor"]} if tg.get("anchor") else set()) | ({tg["group"]} if tg.get("group") else set()))
        parts = []
        for k, v in sorted((c.get("set") or {}).items(), key=lambda kv: SET_FIELDS.index(kv[0]) if kv[0] in SET_FIELDS
                           else 9):
            if k == "project":
                parts.append(f"과제 → {'업무 아님' if v in (None, '', 'NONE', 'UNC') else hx.project(v)}")
            elif k in _VOCAB_OF:
                parts.append(f"{SET_KO[k]} → {hx.vocab(k, v)}")
            elif k == "title":
                parts.append(f"제목 → '{v}'")
        out.append({"id": c.get("id"), "date": str(c.get("at") or "")[:10], "set": c.get("set"),
                    "set_ko": " · ".join(parts) or "—", "n_keys": n_keys})
    return out


def get_hier_state(app, req):
    from lm27.hier.learn import load_corrections, load_learned
    from lm27.hier.proposals import ProposalQueue
    from lm27.ui.api_team import registry_view
    reg, rst = registry_view(app)
    projects, vocab, regv = [], {}, {}
    if reg is not None:
        team = sum(1 for p in reg.projects.values() if p.origin == "team")
        mine = sum(1 for p in reg.projects.values() if p.origin == "local")
        res = sum(1 for p in reg.projects.values() if p.origin == "reserved")
        regv = {"version": getattr(rst, "version", None), "fetched_at": getattr(rst, "fetched_at", None),
                "source": getattr(rst, "source", None), "team_projects": team, "my_projects": mine, "reserved": res,
                "status_text": rst.label_ko() if rst is not None else ""}
        projects = [{"key": p.id, "label": p.name or p.id} for p in sorted(reg.projects.values(), key=lambda x: x.id)
                    if p.status == "active" and not p.merged_into]
        for kind in ("fields", "functions", "activity_types"):
            vocab[kind] = [{"code": c, "name": getattr(it, "name", c) or c} for c, it in (reg.vocab.get(kind) or {}).items()
                           if getattr(it, "status", "active") == "active"]
    hx = _HierRefs(app, reg)
    q = ProposalQueue.for_paths(app.paths)
    props = [_prop_view(it) for it in q.items]
    lr = load_learned(app.paths)
    rules = [_rule_view(r, reg, hx) for r in lr["rules"] if isinstance(r, dict)]
    h = (hx.model.get("flags") or {}).get("hier") if isinstance(hx.model.get("flags"), dict) else None
    ai_share = h.get("ai_share") if isinstance(h, dict) else None
    corrections = load_corrections(app.paths)
    cn = (reg.codename_review if reg is not None else None) or {}
    return {"registry": regv, "ai_share": ai_share,
            "codename": {"show": bool(cn.get("cands")) and not cn.get("done_at") and not cn.get("skipped"),
                         "skipped": bool(cn.get("skipped")), "cands": list(cn.get("cands") or ())[:30]},
            "proposals": props, "rules": rules, "unapplied": _unapplied(app, hx, corrections),
            "corrections": len(corrections), "notices": _notices(q.items, hx, app.deps.now()),
            "projects": projects, "vocab": vocab}


ROUTES = (("GET", r"/api/report", get_report),
          ("GET", r"/api/report/unit/([^/]+)", get_unit),
          ("GET", r"/api/report/day/([^/]+)", get_day),
          ("POST", r"/api/report/build", post_build),
          ("POST", r"/api/report/export", post_export),
          ("POST", r"/api/report/export/open", post_export_open),
          ("POST", r"/api/queue/answer", post_answer),
          ("POST", r"/api/agentic/need/drop", post_need_drop),
          ("GET", r"/api/hier/state", get_hier_state),
          ("POST", r"/api/hier/correction", post_correction),
          ("POST", r"/api/hier/proposal", post_proposal),
          ("POST", r"/api/hier/codename", post_codename),
          ("POST", r"/api/hier/rule", post_rule))
