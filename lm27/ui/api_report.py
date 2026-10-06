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

from lm27.ui.server import ApiError

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
    with _model_lock:
        app.scratch.pop("_models", None)


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
    nid = req.body.get("need_id")
    if not isinstance(nid, str) or not _NEED_RX.match(nid):
        raise ApiError(400, "bad_need", "니즈 ID 형식이 아닙니다")
    if req.body.get("drop", True) is not True:
        raise ApiError(400, "undo_unsupported", "뺀 니즈를 다시 넣는 것은 다음 분석의 새 니즈로 돌아옵니다")
    from lm27.team.build import drop_need
    r = drop_need(app.paths, nid)
    if r.get("rc") == 1:
        raise ApiError(400, "bad_need", r.get("message") or "니즈 ID 형식이 아닙니다")
    return {"ok": True, "changed": r.get("rc") == 0, "text_ko": r.get("message")}


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
            d = app.deps.now().date().isoformat()
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
            out["project"] = q.accept_local(pid, b.get("keywords") or (), paths=app.paths, at=at)
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
            raise ApiError(409, "customer_unsupported", "고객사 등록은 설정 › 개인정보의 고객사 목록에서 합니다")
    except ValueError:
        raise ApiError(409, "local_registry", "개인 레지스트리를 고치지 못했습니다 — 다시 누르면 이어서 합니다") from None
    return {"ok": True, "codename_review": cr}


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
        cond, then = rule.get("cond") or ["", ""], rule.get("then") or ["", ""]
        txt = f"팀 규칙 제안: 조건 {cond[0] if cond else ''} → {then[1] if len(then) > 1 else ''}(학습 규칙 {rid})"
        return {"ok": True, "text_ko": txt}
    rule["status"] = "active" if act == "on" else "off"
    save_learned(app.paths, lr["rules"], lr["learned_from"])
    return {"ok": True, "status": rule["status"]}


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
    q = ProposalQueue.for_paths(app.paths)
    props = [{"proposal_id": it.get("proposal_id"), "name": it.get("label"), "domain_guess": it.get("domain_guess"),
              "units": len(it.get("groups") or ()), "first": it.get("first"), "last": it.get("last"),
              "src": (it.get("sources") or [""])[0] if isinstance(it.get("sources"), list) else "",
              "state": it.get("status")} for it in q.items]
    lr = load_learned(app.paths)
    rules = [{"rule_id": r.get("id"), "kind": r.get("kind"), "state": r.get("status"), "hits": r.get("hits", 0),
              "agree": r.get("agree", 0), "disagree": r.get("disagree", 0)} for r in lr["rules"]]
    cur = current(app)
    unapplied, ai_share = [], None
    if cur:
        m = model_or_none(app, cur["run_id"], "full") or {}
        h = (m.get("flags") or {}).get("hier") if isinstance(m.get("flags"), dict) else None
        if isinstance(h, dict):
            ai_share = h.get("ai_share")
    ncor = len(load_corrections(app.paths))
    cn = (reg.codename_review if reg is not None else None) or {}
    return {"registry": regv, "ai_share": ai_share,
            "codename": {"show": bool(cn.get("cands")) and not cn.get("done_at") and not cn.get("skipped"),
                         "skipped": bool(cn.get("skipped")), "cands": list(cn.get("cands") or ())[:30]},
            "proposals": props, "rules": rules, "unapplied": unapplied, "corrections": ncor, "notices": [],
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
