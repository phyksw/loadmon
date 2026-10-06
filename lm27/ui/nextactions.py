# -*- coding: utf-8 -*-
r"""다음 할 일 카탈로그(R §5.7 — N01~N19) — ``next_actions(state) -> list[NextAction]``.

    state = gather(app)           # 파일·모듈에서 UiState 를 모은다(조각마다 따로 실패 — 한 조각이 깨져도 나머지는 보인다)
    acts = next_actions(state)    # 순수 함수: 등급 순(막힘 → 위험 → 향상 → 정보) · 같은 등급은 코드 순 · 같은 코드는 대상 순

- 같은 (코드, 대상)은 한 번만(RPT-41). 행동은 화면 이동(``goto``)이나 화면 API(``api`` — ``POST /api/…``)뿐이다.
- 문구는 '무엇이 됐고 → 무엇이 남았고 → 프로그램이 무엇을 하는지' 순서. 사용자에게 시키는 일은 로그인·붙여넣기·확인 질문
  응답·버튼 누르기뿐(R §5.0.4) — 파일 압축 풀기·폴더 지우기를 요구하지 않는다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

__all__ = ["LEVELS", "NextAction", "UiState", "gather", "next_actions"]

LEVELS = ("block", "risk", "improve", "info")
_RANK = {lv: i for i, lv in enumerate(LEVELS)}
# N17 번들 위치 주의 사유(계약 §6.1 — 쓰기 불가 READONLY 는 N02 막힘)
BUNDLE_WARN = frozenset({"R-BUNDLE-ONEDRIVE", "R-BUNDLE-NETWORK", "R-BUNDLE-LONGPATH", "R-BUNDLE-LOWSPACE",
                         "R-BUNDLE-REDIRECT"})


@dataclass
class NextAction:
    code: str
    level: str
    title_ko: str
    why_ko: str
    action: dict | None
    target: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class UiState:
    """다음 할 일 판정 입력(R §5.7 표의 조건 — 이름·원문 없음, PC 는 라벨로)."""
    this_pc: str = "이 PC"
    calendar_years: list = field(default_factory=list)          # N01 분석이 '달력 미확인 연도'로 거부됨
    bundle_readonly: bool = False                               # N02
    outbox_blocked: list = field(default_factory=list)          # N03 [(대상 기간, 상태 한국어)]
    agent: str = "ok"                                           # N04 ok · stale · missing
    agent_why: str = ""
    arrival_missing: dict = field(default_factory=dict)         # N05 {PC 라벨: 개수}
    stale_pcs: dict = field(default_factory=dict)               # N06 {PC 라벨: 일수}
    login_needed: bool = False                                  # N07
    confirmed_blocked: list = field(default_factory=list)       # N08 [출처 이름]
    todo_mine: int = 0                                          # N09
    manual_batches: int = 0                                     # N10
    questions_open: int = 0                                     # N11
    questions_week: str = ""
    analysis_behind: bool = False                               # N12
    answers_pending: int = 0                                    # N13
    registry_missing: bool = False                              # N14
    registry_old: bool = False
    approvals: list = field(default_factory=list)               # N15 [대상 기간]
    config_warnings: int = 0                                    # N16
    location_warn: list = field(default_factory=list)           # N17 [사유 코드]
    profile_trace: bool = False                                 # N18
    collect_days_ago: int | None = None                         # N19


def _act(label, goto=None, api=None, body=None) -> dict:
    a = {"label": label}
    if goto:
        a["goto"] = goto
    if api:
        a["api"] = api
        a["body"] = body or {}
    return a


def next_actions(s: UiState) -> list:
    """R §5.7 표 그대로(조건 → 코드·등급·제목·행동). 결정적 정렬·중복 제거."""
    out: list[NextAction] = []

    def add(code, level, title, why, action, target):
        out.append(NextAction(code, level, title, why, action, str(target)))

    for y in sorted(set(s.calendar_years)):
        add("N01", "block", f"{y}년 공휴일 달력이 필요합니다", "달력이 확인되지 않은 해가 있어 분석하지 않았습니다(MM 분모가 틀어질 수 "
            "있음) — 레지스트리를 받으면 다시 시도합니다", _act("[레지스트리 받기]", "#team", "POST /api/team/registry/fetch"), y)
    if s.bundle_readonly:
        add("N02", "block", "이 폴더에 쓸 수 없습니다", "번들 폴더가 읽기 전용이라 수집 결과를 남기지 못합니다 — 쓰기 가능한 위치로 "
            "폴더를 옮기면 이어서 기록합니다", _act("[수집 화면]", "#collect"), s.this_pc)
    for per, st in sorted(set(s.outbox_blocked)):
        add("N03", "block", "팀 묶음을 보내지 못했습니다", f"{per} 묶음: {st} — 팀 화면에서 확인하면 이어서 보냅니다",
            _act("[팀 화면]", "#team"), per)
    if s.agent in ("stale", "missing"):
        why = s.agent_why or ("사용 기록기가 설치되어 있지 않습니다" if s.agent == "missing" else "사용 기록기의 마지막 기록이 오래되었습니다")
        add("N04", "risk", "이 PC 의 사용 기록기가 멈췄습니다", why + " — [에이전트 복구]를 누르면 다시 띄웁니다",
            _act("[에이전트 복구]", "#collect", "POST /api/agent/repair"), s.this_pc)
    for pc, n in sorted(s.arrival_missing.items()):
        if n > 0:
            add("N05", "risk", f"{pc} 의 기록 {n}개가 복사되지 않았습니다", "원래 PC 에서 폴더를 다시 복사하면 빠진 기록만 합칩니다",
                _act("[수집 화면]", "#collect"), pc)
    for pc, d in sorted(s.stale_pcs.items()):
        add("N06", "risk", f"{pc} 기록이 {d}일째 들어오지 않았습니다", "그 PC 에서 [수집]하면 그 뒤 기록이 들어옵니다",
            _act("[수집 화면]", "#collect"), pc)
    if s.login_needed:
        add("N07", "risk", "Outlook 웹·팀즈 웹 로그인이 필요합니다",
            "전용 Edge 창에서 회사 계정으로 한 번 로그인하면 Outlook·팀즈 버전과 상관없이 메일·일정·대화를 이어서 읽습니다",
            _act("[분석용 Edge 창 앞으로]", "#analysis", "POST /api/bridge/front"), s.this_pc)
    for src in sorted(set(s.confirmed_blocked)):
        add("N08", "risk", f"{src} 를 이 계정에서 쓸 수 없습니다", "다른 경로(반입 폴더 등)가 그 기간을 채웁니다",
            _act("[수집 화면]", "#collect"), src)
    if s.todo_mine > 0:
        add("N09", "improve", f"백필 할 일 {s.todo_mine}건", "이 PC 에 배정된 빈 기간이 있습니다 — [수집]을 누르면 채웁니다",
            _act("[수집]", "#collect", "POST /api/collect/run", {"mode": "auto"}), s.this_pc)
    if s.manual_batches > 0:
        add("N10", "improve", f"Copilot 붙여넣기 {s.manual_batches}묶음 남음", "분석 화면에서 묶음을 복사해 답을 붙여넣으면 이어서 합니다",
            _act("[분석 화면]", "#analysis"), "manual")
    if s.questions_open > 0:
        add("N11", "improve", f"확인 질문 {s.questions_open}건", "답하면 업무 시작·끝과 분류가 더 정확해집니다",
            _act("[개인 보고서 › 확인 질문]", "#report/queue"), s.questions_week or "queue")
    if s.analysis_behind:
        add("N12", "improve", "분석이 최근 수집보다 오래되었습니다", "새로 모은 기록이 아직 보고서에 반영되지 않았습니다",
            _act("[분석 실행]", "#analysis"), "analysis")
    if s.answers_pending > 0:
        add("N13", "improve", f"응답 {s.answers_pending}건이 아직 반영되지 않았습니다", "빠른 재분석을 하면 반영됩니다(자동 재분석이 켜져 "
            "있으면 잠시 뒤 스스로 합니다)", _act("[빠른 재분석]", "#analysis"), "answers")
    if s.registry_missing or s.registry_old:
        add("N14", "improve", "팀 레지스트리를 받지 못했습니다", "과제 이름·에이전트 목록이 비어 있거나 오래되었습니다 — [지금 받기]를 "
            "누르면 받습니다", _act("[지금 받기]", "#team", "POST /api/team/registry/fetch"), "registry")
    for per in sorted(set(s.approvals)):
        add("N15", "improve", "팀 묶음이 승인을 기다립니다", f"{per} 묶음 — 미리보기에서 [보내기]를 누르면 보냅니다",
            _act("[미리보기]", "#team"), per)
    if s.config_warnings > 0:
        add("N16", "info", f"설정 {s.config_warnings}개가 잘못되어 기본값을 씁니다", "설정 화면 위 목록에서 고칠 수 있습니다",
            _act("[설정]", "#settings"), "config")
    for r in sorted(set(s.location_warn)):
        add("N17", "info", "번들 위치 주의", _location_text(r), _act("[수집 화면]", "#collect"), r)
    if s.profile_trace:
        add("N18", "info", "폴더 안에 브라우저 프로필이 있습니다", "브라우저 프로필은 이 폴더 밖(PC 에 남는 곳)에 둡니다 — 폴더를 옮길 때 "
            "함께 가지 않습니다", _act("[수집 화면]", "#collect"), "profile")
    if s.collect_days_ago is not None and s.collect_days_ago >= 1:
        add("N19", "info", f"최근 수집이 {s.collect_days_ago}일 전입니다", "[수집]을 누르면 그 뒤 기록을 모읍니다",
            _act("[수집]", "#collect", "POST /api/collect/run", {"mode": "auto"}), s.this_pc)
    seen, uniq = set(), []
    for a in sorted(out, key=lambda a: (_RANK.get(a.level, 9), a.code, a.target)):
        k = (a.code, a.target)
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return uniq


def _location_text(code: str) -> str:
    from lm27.report.vocab import reason_text
    return reason_text(code)[1]


# ───────────────────────────── 상태 모으기 ─────────────────────────────
def _workdays_between(d0: date, d1: date) -> int:
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def gather(app) -> UiState:
    """화면 서버의 파일·모듈에서 UiState 를 모은다. 조각마다 따로 실패(그 조건만 빠진다 — R §11)."""
    s = UiState()
    steps = (_g_pc, _g_weblogin, _g_agent, _g_analysis, _g_bundle, _g_todo, _g_outbox, _g_registry, _g_manual, _g_misc)
    for fn in steps:
        try:
            fn(app, s)
        except Exception:                               # 그 조각을 읽지 못함 — 다른 조건은 그대로 판정
            continue
    return s


def _g_pc(app, s: UiState) -> None:
    from lm27.ui.api_home import pc_label, this_pc
    pc = this_pc(app)[1]
    if pc:
        s.this_pc = pc_label(pc)
    caps = pc.get("capabilities") or {}
    bl = caps.get("bundle_location") or {}
    rs = [r for r in bl.get("reasons") or () if isinstance(r, str)]
    s.bundle_readonly = "R-BUNDLE-READONLY" in rs
    s.location_warn = [r for r in rs if r in BUNDLE_WARN]
    roles = set(pc.get("roles") or ())
    try:                                            # 계약 v1.3 §0.8 V5 — 웹 경로가 모든 PC 에서 돌면 로그인 안내도 모든 PC 에
        from lm27.collect import plan
        if plan.web_everywhere(app.cfg()):
            roles.add(plan.ROLE_BACKFILL)
    except Exception:
        pass
    wl = caps.get("web_login") or {}
    if roles & {"account_backfill", "copilot"} and str(wl.get("verdict") or "").startswith("불가") and \
            "R-LOGIN" in (wl.get("reasons") or ()):
        s.login_needed = True
    s.profile_trace = "browser_profile_in_root" in (pc.get("flags") or ())


def _g_agent(app, s: UiState) -> None:
    from lm27.ui.api_collect import agent_state
    a = agent_state(app)
    s.agent = a["state"]
    if a["state"] == "stale" and isinstance(a.get("age_s"), int):
        s.agent_why = f"마지막 틱이 {a['age_s'] // 60}분 전입니다"


def _g_analysis(app, s: UiState) -> None:
    from lm27.pipeline.retention import list_runs
    from lm27.ui.api_analysis import _status
    from lm27.ui.api_report import current, model_or_none
    runs = sorted(list_runs(app.paths))
    if runs:
        st = _status(app, runs[-1]) or {}
        if st.get("state") == "failed" and st.get("reason") == "calendar_unknown_year":
            ys = st.get("years") or ([st.get("year")] if st.get("year") else [])
            s.calendar_years = [str(y) for y in ys if y]
    cur = current(app)
    if cur:
        m = model_or_none(app, cur["run_id"], "full") or {}
        answered = app.scratch.get("answered", {})
        open_q = [q for q in m.get("queue") or () if isinstance(q, dict) and q.get("status") != "answered"
                  and q.get("qid") not in answered]
        s.questions_open = len(open_q)
        weeks = sorted({str(q.get("week")) for q in open_q if q.get("week")})
        s.questions_week = weeks[-1] if weeks else ""
        from lm27.ui.api_collect import last_collect
        last = last_collect(app)
        as_of = str(cur.get("as_of") or "")
        if last and last.get("run_id") and as_of:
            from datetime import datetime
            try:
                t_col = datetime.strptime(last["run_id"][:15], "%Y%m%d-%H%M%S")        # run_id 시각 = 로컬(계약 §4.1)
                t_ana = datetime.fromisoformat(as_of[:16])
                s.analysis_behind = (t_col - t_ana.replace(tzinfo=None)).total_seconds() > 24 * 3600
            except ValueError:
                pass
    s.answers_pending = int(app.scratch.get("answers_pending", 0))


def _g_bundle(app, s: UiState) -> None:
    from lm27.ui.api_collect import last_collect, pc_stale
    from lm27.ui.api_home import all_pcs, pc_label, this_pc
    me, _pc = this_pc(app)
    now = app.deps.now()
    for p in all_pcs(app):
        if p.get("pc_id") == me:
            continue
        if pc_stale(app, p):
            from lm27.ui.api_collect import _parse_utc
            t = _parse_utc(p.get("last_seen"))
            if t is not None:
                s.stale_pcs[pc_label(p)] = (now - t).days
    from lm27.bundle.loader import arrival_missing
    labels = {p.get("pc_id"): pc_label(p) for p in all_pcs(app)}
    for x in arrival_missing(app.paths):
        k = labels.get(x.get("pc_id"), "다른 PC")
        s.arrival_missing[k] = s.arrival_missing.get(k, 0) + 1
    last = last_collect(app)
    if last and last.get("run_id"):
        d = date(int(last["run_id"][:4]), int(last["run_id"][4:6]), int(last["run_id"][6:8]))
        today = now.date()
        if d < today and _workdays_between(d, today) > 2:
            s.collect_days_ago = (today - d).days


def _g_todo(app, s: UiState) -> None:
    from lm27.collect import todo as T
    from lm27.ui.api_home import SRC_NAMES, this_pc
    me, _pc = this_pc(app)
    for t in T.load_todo(app.paths):
        d = t if isinstance(t, dict) else getattr(t, "__dict__", {})
        st = d.get("state")
        if st in ("open", "assigned") and me and d.get("want_pc") == me:
            s.todo_mine += 1
        elif st == "blocked_confirmed":
            s.confirmed_blocked.append(SRC_NAMES.get(d.get("want_src"), str(d.get("want_src") or "출처")))


def _g_outbox(app, s: UiState) -> None:
    from lm27.team import queue
    from lm27.ui.api_team import STATE_KO
    for it in queue.list_items(paths=app.paths):
        st = it.state
        if st in ("wrong_server", "auth_needed", "failed"):
            s.outbox_blocked.append((it.period_key or it.name, STATE_KO.get(st, st)))
        elif st == "pending" and not (it.meta or {}).get("approved") and not (it.meta or {}).get("blockers"):
            s.approvals.append(it.period_key or it.name)


def _g_registry(app, s: UiState) -> None:
    from lm27.ui.api_team import registry_view
    _reg, st = registry_view(app)
    if st is None or getattr(st, "source", "builtin") == "builtin":
        s.registry_missing = True
        return
    s.registry_old = bool(getattr(st, "stale", False))


def _g_manual(app, s: UiState) -> None:
    from lm27.ui.api_analysis import get_manual
    s.manual_batches = int(get_manual(app, None).get("open") or 0)


def _g_weblogin(app, s: UiState) -> None:
    """이 PC 의 최근 수집에서 버전 무관 웹 경로(Outlook 웹·팀즈 웹)가 로그인 때문에 못 돌았나(계약 v1.3 §0.8 V5).
    웹 수집기의 R-LOGIN·R-CA 는 pc.json 능력이 아니라 수집 실행의 단계 결과에 남는다 — 그것을 본다."""
    import json
    from lm27.ui.api_home import this_pc
    pc_id = (this_pc(app)[1] or {}).get("pc_id")
    root = app.paths.collect_runs()
    if not root.is_dir():
        return
    for d in sorted((x for x in root.iterdir() if x.is_dir()), key=lambda x: x.name, reverse=True)[:20]:
        seen = hit = False
        for st in ("backfill_owa", "backfill_teams_web"):
            f = d / f"stage_result_{st}.json"
            if not f.is_file():
                continue
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if pc_id and r.get("pc_id") not in (None, pc_id):
                continue
            seen = True
            hit = hit or bool({"R-LOGIN", "R-CA"} & set(r.get("reasons") or ()))
        if seen:                                    # 웹 단계가 돈 가장 최근 실행만 본다(그 뒤 로그인했으면 사라진다)
            s.login_needed = s.login_needed or hit
            return


def _g_misc(app, s: UiState) -> None:
    s.config_warnings = len(app.cfg().config_warnings)
