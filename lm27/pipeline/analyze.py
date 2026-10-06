# -*- coding: utf-8 -*-
r"""분석 파이프라인 실행기(계약 §2.13 · §3.23 · §7.1 · §8.3 · §8.5 · O-1 · X-178, R §2.4 · §5.3 · §13 A-1, B §2.3).

    analyze(paths, cfg, *, from_, to, as_of=None, ai=True, rerun=None, stages=None) -> int      (cli 어댑터 형)

한 번의 분석 = 새 실행 ``run_id``(``lm27.util.tz.new_run_id``) 하나. 단계 10종(``lm27.pipeline.stages.STAGES``)을 차례로 돌며
단계마다 ``lm27.stage/1`` 공통 필드 + ``id``·``name_ko``(계약 §8.5 분석 행)를 ``run_status.json``(``lm27.runstatus/1``)에
원자 기록한다. 파이프라인은 **계산하지 않는다** — 순서·재개·결과 선택만 맡고 계산은 계약 함수가 한다:

| 단계 | 부르는 계약 함수 |
|---|---|
| 사전 점검 | ``lm27.team.client.refresh_registry``(분석 전 받기 — TAB §3.10, 주기 안이면 네트워크 없음, 재분석은 건너뜀) ·
  ``lm27.hier.registry.load_effective`` · ``lm27.time.calendar.load_calendar`` → 기간에 달력 없는 해가 섞이면 **분석 거부** |
| load | ``lm27.normalize.load.load_evidence``(기간 앞뒤 하루 여유 — 자정 연속성) |
| normalize | ``lm27.normalize.absence.leaves`` · 커버리지 원장 → 시간 코어 프로필 · 화행 회색 지대
  (``write_speech_act_in`` → 브리지 ``speech_act`` → ``apply_acts``) |
| classify | ``lm27.hier.prepare``(HierTags) → ``lm27.time.analyze_time`` → ``lm27.hier.classify_all``(규칙 라벨, task_label ai_in) |
| ai:task_label · ai:workflow · ai:review_text | 브리지 프로세스 ``lm27_cli.py bridge run --run-id <run_id> --stages …
  --events jsonl``(B §2.3 — 호출 1회 = 프로세스 1개, ``lm27.collect.watch`` 감시) |
| time | ``lm27.hier.classify_all``(AI 답 반영·로컬 상태 저장) → ``lm27.time.mm.rollup`` → ``write_time_files`` ·
  ``lm27.hier.write_result`` |
| mining · review | ``lm27.report.inputs.load_inputs`` → ``lm27.report.analysis.ai_items``(ai_in) |
| report | ``lm27.report.build_report`` |

규칙:
- **시간 보존은 fail-closed**(T-01): 시간 코어의 ``ConservationError`` 와 파이프라인 자체 재검사(날마다 Σ귀속 초 =
  300 × 봉투 슬롯) 중 하나라도 어기면 그 단계 failed(``conservation``) → 결과 파일·current.json 없음 → rc 1.
- **분류는 시간 값을 바꾸지 않는다**(T-06): 분류 전후 정수 분 표(team_tables) 바이트가 다르면 failed(``classify_changed_time``).
- **AI 단계는 fail-soft**: 브리지 실패·일부·감시 종료는 그 단계 ``partial``(재개 가능) — 규칙 라벨로 끝까지 가고 실행은 rc 2.
  ``--no-ai``·브리지 꺼짐·Copilot 역할 아님·단계 스위치 꺼짐·물을 항목 없음은 ``skipped``(사유). ``--no-ai`` 면 분류도
  저장된 AI 답을 쓰지 않는다(규칙 라벨로 완주 — T-H16).
- **성공 전 무효화 금지**: ``current.json`` 은 보고서까지 만든 실행만 원자 교체한다(``chosen = auto``). 실패·거부·중단이면
  이전 결과를 그대로 둔다. 실행 폴더는 실행마다 새로 만든다(이전 실행을 덮지 않는다).
- 재분석(``--rerun <run_id> --stages …``): 원본 실행의 기간·기준 시각으로 새 실행을 만든다(``stages.plan_run``).
  메모리 사슬(load → normalize → classify → time)을 하나라도 고르면 넷 다 돈다 — 확인 질문 응답(수동 행)을 다시 읽어야
  하므로. 사슬을 고르지 않으면 원본의 ``time``·``hier`` 결과 파일을 새 실행으로 옮겨 쓴다.
- 결과 rc(계약 §8.3): 0 성공 · 2 부분(AI 일부 미완·보고서 입력 일부 없음·사용자 중단 — 재개 가능) · 1 실패(보존·분류 불변
  위반, 달력 미확인 연도, 키링 없음, 내부 오류, 보고서 실패, 인자 오류) · 4 할 일 없음(기간에 기록 0건).
- 끝에 ``report.analysisKeep`` 보관 정리(``lm27.pipeline.retention``). 진행은 표준 출력 이벤트(계약 §8.6 —
  ``stage_start``·30초 ``progress``·``stage_end``·``result``)로 낸다. 브리지 자식의 이벤트는 이 단계 이름으로 다시 낸다.
- 원문 0: 실행 상태에는 수·열거·사유 코드·고정 한국어 안내만 둔다. 예외는 유형 이름만 남긴다.

경로(L-08)는 ``lm27.paths`` 메서드로만: ``Paths.run_status_file(run_id)`` · ``analysis_time_file`` · ``analysis_hier`` ·
``analysis_report_file``(분석 폴더 하위 경로 — CR) · ``analysis_current()`` · ``ai_in``·``ai_out`` · ``coverage_ledger()`` ·
``python_exe()``·``cli_script()``. 하위 경로 메서드가 없으면 실행을 만들지 않고 rc 1(한국어 한 줄).
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import re
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dtime, timedelta, timezone

from lm27.collect import rcmap
from lm27.collect import stage_result as SR
from lm27.pipeline import stages as S
from lm27.pipeline.retention import keep_of, prune_analysis
from lm27.util import events, fsx
from lm27.util.tz import fmt_offset, new_run_id

__all__ = [
    "AUTO", "CURRENT_SCHEMA", "REASONS_KO", "REQUIRED_PATH_METHODS", "SCHEMA", "BridgeRun", "analyze",
    "choose_current", "last_result", "process_bridge", "read_current", "read_run_status",
]

SCHEMA = "lm27.runstatus/1"
CURRENT_SCHEMA = "lm27.current/1"
RC_OK, RC_FAIL, RC_PARTIAL, RC_NOOP = 0, 1, 2, 4                    # 계약 §8.3
AS_OF_SLACK_S = 300                                                 # 기준 시각 '지금' 허용 여유(초)
HINT_MAX = 200
WARN_MAX = 50
AUTO = object()                                                     # team_client 기본값 표지(lm27.team.client 모듈)
# 분석 폴더 하위 경로(L-08 — paths.py CR). 보고서 폴더는 analysis_report_file 또는 analysis_report(WP-31 이 둘 다 받는다).
REQUIRED_PATH_METHODS = ("run_status_file", "analysis_time_file", "analysis_hier", "analysis_report_file")
_PATH_ALT = {"analysis_report_file": "analysis_report"}
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CTRL_RX = re.compile(r"[\x00-\x1f\x7f]")
_LOCK = threading.Lock()
_LAST: dict = {}

# 사유 → (짧은 이름, 안내 한 줄). 사유는 단계 사유(영문 소문자 — 계약 §8.5 reason) — 화면 문구는 R §5.3.3 과 같은 뜻.
REASONS_KO = {
    "no_records": ("기록 없음", "이 기간에 읽을 기록이 없습니다 — [수집]을 먼저 하거나 기간을 바꾸세요"),
    "calendar_unknown_year": ("달력 미확인 연도", "{years}년 공휴일 달력이 확인되지 않아 분석하지 않았습니다(MM 분모가 "
                              "틀어질 수 있음) — 팀 레지스트리를 받으면 다시 시도합니다"),
    "conservation": ("근무시간 보존 검사 실패", "계산 검사(근무시간 보존)에 실패해 결과를 만들지 않았습니다 — 이전 결과를 "
                     "그대로 보여 줍니다"),
    "classify_changed_time": ("분류 불변 위반", "분류 뒤 시간 결과가 달라져 결과를 만들지 않았습니다 — 이전 결과를 그대로 "
                              "보여 줍니다"),
    "hier_invariant": ("분류 검사 실패", "분류 검사(계층 불변식)에 실패해 결과를 만들지 않았습니다 — 이전 결과를 그대로 보여 "
                       "줍니다"),
    "no_keyring": ("키링 없음", "키링이 없어 단위업무 식별자를 만들 수 없습니다 — 번들 폴더의 키 파일이 함께 있어야 합니다"),
    "paths_method_missing": ("경로 메서드 없음", "이 판의 경로 로더에 분석 결과 경로가 없습니다 — 프로그램을 최신으로 바꾼 뒤 "
                             "다시 실행하세요"),
    "internal_error": ("내부 오류", "내부 오류로 이 단계를 끝내지 못했습니다 — 이전 결과를 그대로 보여 줍니다"),
    "inputs_missing": ("시간 결과 없음", "시간 결과 파일을 읽지 못해 이 단계를 건너뛰었습니다"),
    "report_failed": ("보고서 실패", "보고서를 만들지 못해 이전 보고서를 그대로 둡니다"),
    "report_partial": ("보고서 입력 일부 없음", "보고서를 만들었지만 일부 입력이 없어 그 절은 비어 있습니다"),
    "upstream_failed": ("앞 단계 실패", "앞 단계가 끝나지 않아 건너뛰었습니다"),
    "cancelled": ("사용자 중단", "사용자가 중단했습니다 — 다음 분석이 남은 것부터 이어 합니다"),
    "ai_off": ("AI 끔", "AI 분석을 쓰지 않았습니다 — 규칙 라벨로 분석했습니다"),
    "no_copilot_role": ("Copilot 역할 아님", "이 PC 는 Copilot 역할이 아닙니다 — 규칙 분류로 분석했습니다"),
    "bridge_off": ("브리지 꺼짐", "Copilot 브리지가 설정에서 꺼져 있습니다 — 규칙 라벨로 분석했습니다"),
    "stage_off": ("단계 꺼짐", "이 AI 단계가 설정에서 꺼져 있습니다"),
    "no_items": ("물을 항목 없음", "AI 에 물을 항목이 없습니다"),
    "not_selected": ("고르지 않음", "이번 재분석에서 고르지 않은 단계입니다"),
    "reused": ("이전 결과 사용", "이전 분석 결과를 그대로 썼습니다"),
    "reuse_missing": ("이전 결과 없음", "다시 쓸 이전 실행의 시간·분류 결과가 없습니다"),
    "bridge_partial": ("AI 일부 미완", "AI 단계를 일부만 마쳤습니다 — 규칙 이름으로 임시 표시하고 다음 분석에서 이어 묻습니다"),
    "bridge_failed": ("AI 실패", "AI 단계를 마치지 못했습니다 — 규칙 이름으로 표시하고 다음 분석에서 다시 묻습니다"),
}
_DONE_HINT = {"load": "기록을 읽었습니다", "normalize": "정리했습니다", "classify": "규칙으로 분류했습니다",
              "time": "시간·분류 결과를 썼습니다", "mining": "워크플로우를 계산했습니다", "review": "리뷰 사실을 모았습니다",
              "report": "보고서를 만들었습니다"}
_CHAIN_FATAL = frozenset(S.CHAIN) | {"report"}           # 이 단계의 실패는 실행 실패(그 뒤 단계는 앞 단계 실패로 건너뜀)


# ───────────────────────────── 작은 도구 ─────────────────────────────
def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_iso(dt: datetime, off_min: int) -> str:
    """근무 시간대 ISO 8601 + 오프셋(사람에게 보이는 시각 — 계약 §9.4)."""
    loc = dt.astimezone(timezone(timedelta(minutes=int(off_min))))
    return loc.strftime("%Y-%m-%dT%H:%M:%S") + fmt_offset(int(off_min))


def _clip(text, n: int = HINT_MAX) -> str:
    s = _CTRL_RX.sub(" ", str(text or ""))
    return s if len(s) <= n else s[: n - 1] + "…"


def _sha(obj) -> str:
    return hashlib.sha256(fsx.canon_bytes(obj)).hexdigest()


def _hint(reason: str | None, years: str = "") -> str:
    """사유의 안내 한 줄(고정 문구 — 원문 없음). 연도 자리는 값이 있을 때만 채운다."""
    if not reason:
        return ""
    txt = REASONS_KO.get(reason, ("", ""))[1]
    if "{years}" in txt:
        txt = txt.replace("{years}", years) if years else txt.replace("{years}년 ", "")
    return _clip(txt)


def _reason_ko(reason: str | None) -> str | None:
    return REASONS_KO.get(reason, (None, None))[0] if reason else None


def _int(v, default: int = 0) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else default


class _Fail(Exception):
    """단계 실패(유형 있는 사유 — 원문 없음). ``fatal`` = 실행 실패(그 뒤 단계는 건너뜀)."""

    def __init__(self, reason: str, *, fatal: bool | None = None, hint: str | None = None, **extra):
        super().__init__(reason)
        self.reason, self.fatal, self.hint, self.extra = reason, fatal, hint, extra


class _Refuse(Exception):
    """사전 점검 거부(달력 미확인 연도 — 실행 전체 failed, 단계는 모두 건너뜀)."""

    def __init__(self, reason: str, **extra):
        super().__init__(reason)
        self.reason, self.extra = reason, extra


@dataclass
class _Out:
    """단계 결과(공통 필드 재료)."""
    state: str = "done"
    counts: dict = field(default_factory=dict)
    items_total: int = 0
    items_ok: int = 0
    items_failed: int = 0
    items_pending: int = 0
    reason: str | None = None
    hint: str = ""
    stop_kind: str | None = None
    resumable: bool | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class BridgeRun:
    """브리지 호출 1회 결과 — ``rc``(단계 rc 최악값 1 > 2 > 0, 감시가 끊었으면 3) · ``stages``({브리지 단계: 요약}) ·
    ``stop_kind``(감시 종료 stall·no_progress·cancelled) · ``reason``(감시 종료 사유 코드)."""
    rc: int | None
    stages: dict = field(default_factory=dict)
    stop_kind: str | None = None
    reason: str | None = None
    killed: bool = False


def _as_bridge_run(v) -> BridgeRun:
    if isinstance(v, BridgeRun):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return BridgeRun(rc=v)
    if isinstance(v, dict):
        st = v.get("stages")
        return BridgeRun(rc=v.get("rc") if isinstance(v.get("rc"), int) else None,
                         stages=dict(st) if isinstance(st, dict) else {}, stop_kind=v.get("stop_kind"),
                         reason=v.get("reason"), killed=bool(v.get("killed")))
    return BridgeRun(rc=None)


# ───────────────────────────── 브리지 프로세스(B §2.3) ─────────────────────────────
class _Forward:
    """브리지 자식의 표준 출력 이벤트를 이 분석 단계 이름으로 다시 낸다(화면 진행 카드 — R §5.3.1). ``progress`` 의 done 은
    자식 단계별 최댓값의 증가분을 더한 단조 누계(감시 ``lm27.collect.watch`` 와 같은 셈). ``stage_start``·``stage_end``·
    ``result``·``run_end`` 는 다시 내지 않는다(분석 단계 목록과 섞이지 않게)."""

    PASS = ("notice", "warn", "msg")

    def __init__(self, stage: str, emit=None):
        self.stage, self.emit = stage, emit or events.emit
        self.max: dict = {}
        self.done = 0

    def __call__(self, ev) -> None:
        if not isinstance(ev, dict):
            return
        name = ev.get("ev")
        sub = ev.get("stage") if isinstance(ev.get("stage"), str) else ""
        if name == "progress":
            d = ev.get("done")
            if isinstance(d, int) and not isinstance(d, bool) and d > self.max.get(sub, 0):
                self.done += d - self.max.get(sub, 0)
                self.max[sub] = d
            self.emit("progress", stage=self.stage, done=self.done, sub=sub or None)
        elif name in self.PASS:
            rest = {k: v for k, v in ev.items() if k not in ("seq", "ts", "ev", "stage", "sub")}
            self.emit(name, stage=self.stage, sub=sub or None, **rest)


def _parse_watch(wr) -> BridgeRun:
    """감시 결과(``WatchResult``) → BridgeRun. 브리지 cli 의 마지막 ``result`` 이벤트에서 단계 요약을 읽는다."""
    res = (wr.last_result or {}).get("result") if isinstance(wr.last_result, dict) else None
    stages = res.get("stages") if isinstance(res, dict) and isinstance(res.get("stages"), dict) else {}
    return BridgeRun(rc=wr.rc, stages=dict(stages), stop_kind=wr.stop_kind, reason=wr.reason, killed=bool(wr.killed))


def process_bridge(paths, cfg, run_id: str, stage: str, names, *, cancel=None, spawn=None, clock=None,
                   emit=None) -> BridgeRun:
    """기본 브리지 호출(B §2.3): ``<python> -X utf8 -B lm27_cli.py bridge run --run-id <run_id> --stages a,b --events jsonl``
    를 띄우고 ``lm27.collect.watch.watch`` 로 생존·진전을 본다(정체·무진전이면 kill_tree — ``collect.watch.*``). 자식 이벤트는
    ``_Forward`` 로 이 단계 이름으로 다시 낸다. ``spawn``·``clock``·``emit`` 은 시험 주입점."""
    from lm27.collect.watch import WatchPolicy, watch
    from lm27.util import proc
    exe = os.fspath(paths.python_exe())
    if not os.path.isfile(exe):
        exe = sys.executable                                   # 개발 실행(동봉 파이썬 밖) — 같은 인터프리터
    argv = [exe, "-X", "utf8", "-B", os.fspath(paths.cli_script()), "bridge", "run", "--run-id", run_id,
            "--stages", ",".join(names), "--events", "jsonl"]
    child = (spawn or proc.spawn)(argv)
    try:
        wr = watch(child, WatchPolicy.from_cfg(cfg, stage=stage), clock=clock, emit=emit,
                   on_event=_Forward(stage, emit), cancel=cancel)
    finally:
        close = getattr(child, "close", None)
        if close is not None:
            close()
    return _parse_watch(wr)


# ───────────────────────────── 실행 상태 ─────────────────────────────
@dataclass
class _Run:
    paths: object
    cfg: object
    run_id: str
    d0: date
    d1: date
    as_of: datetime
    off_min: int
    ai: bool
    plan: dict
    now: object
    bridge: object
    team_client: object = None
    copilot_role: bool | None = None
    cancel: object = None
    rerun_of: str | None = None
    selected: list | None = None
    period_source: str | None = None
    period_months: int | None = None
    status: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    available: set = field(default_factory=set)
    warnings: list = field(default_factory=list)
    reg: object = None
    reg_status: object = None
    cal: object = None
    kr: object = None
    rows: list | None = None
    load_rep: dict = field(default_factory=dict)
    profile: dict | None = None
    feats: list | None = None
    tags: object = None
    tres: object = None
    tables_sig: str = ""
    hier_ctx: dict = field(default_factory=dict)
    hier_final: object = None
    task_items: int = 0
    ai_in: dict = field(default_factory=dict)
    ev_index: object = None
    report: object = None
    fatal: str | None = None
    refused: str | None = None
    cancelled: bool = False
    no_records: bool = False
    hb: object = None

    @property
    def as_of_iso(self) -> str:
        return _local_iso(self.as_of, self.off_min)

    def warn(self, code: str, text_ko: str) -> None:
        if len(self.warnings) < WARN_MAX and not any(w["code"] == code and w["text_ko"] == text_ko
                                                     for w in self.warnings):
            self.warnings.append({"code": code, "text_ko": _clip(text_ko)})

    def gate(self, names) -> tuple[list, str | None]:
        """AI 호출 가능한 브리지 단계(설정 스위치 켜짐)와 막는 사유(``ai_off``·``bridge_off``·``no_copilot_role``·``stage_off``)."""
        if not self.ai:
            return [], "ai_off"
        if str(self.cfg["bridge.mode"]) == "off":
            return [], "bridge_off"
        if not self.copilot_ok():
            return [], "no_copilot_role"
        sw = self.cfg["bridge.stages"]
        sw = sw if isinstance(sw, dict) else {}
        en = [n for n in names if bool(sw.get(n, True))]
        return (en, None) if en else ([], "stage_off")

    def stored_ai_ok(self, names) -> bool:
        """저장된 AI 답을 써도 되는가 — 이번 실행이 AI 를 부르는지와 별개(--no-ai·빠른 재분석이어도 참, 계약 v1.3 §0.8 V14).
        브리지를 끈 설정(``bridge.mode=off``)·AI 가 허용되지 않는 PC·그 단계를 끈 설정이면 거짓."""
        if str(self.cfg["bridge.mode"]) == "off" or not self.copilot_ok():
            return False
        sw = self.cfg["bridge.stages"]
        sw = sw if isinstance(sw, dict) else {}
        return any(bool(sw.get(n, True)) for n in names)

    def copilot_ok(self) -> bool:
        if self.copilot_role is None:
            self.copilot_role = ai_any_pc(self.cfg) or _detect_copilot_role(self.paths)
        return bool(self.copilot_role)


def ai_any_pc(cfg) -> bool:
    """AI 판정을 모든 PC 에서 하는가(``report.aiAnyPc`` — 기본 켜짐, LM24 와 같음 · 계약 v1.3 §0.8 V11). 끄면 클라우드PC 만."""
    try:
        return bool(cfg["report.aiAnyPc"])
    except KeyError:
        return True


def _detect_copilot_role(paths) -> bool:
    """이 PC 의 역할에 ``copilot`` 이 있는가 — pc.json ``roles``(TAB §1.5), pc.json 이 없으면 PC 종류가 클라우드PC 인지."""
    from lm27.bundle import pcreg
    from lm27.bundle.ids import identify_pc
    try:
        ident = identify_pc(paths)
        pc = pcreg.load_pc(paths.pc_dir(ident.pc_id))
    except (OSError, ValueError):
        return False
    roles = pc.get("roles") if isinstance(pc, dict) else None
    if isinstance(roles, list):
        return "copilot" in roles
    return getattr(ident, "kind_guess", "") == "cloud"


# ───────────────────────────── 인자 해석 ─────────────────────────────
def _as_date(v, what: str) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and _DATE_RX.match(v.strip()):
        try:
            return date.fromisoformat(v.strip())
        except ValueError:
            pass
    raise ValueError(f"{what} 날짜는 YYYY-MM-DD 입니다")


def _now_fn(now):
    if now is None:
        return lambda: datetime.now(UTC)
    if callable(now):
        return lambda: _aware(now())
    fixed = _aware(now)
    return lambda: fixed


def _aware(dt) -> datetime:
    if not isinstance(dt, datetime):
        raise TypeError("now 는 datetime 입니다")
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _parse_as_of(v, now_utc: datetime, off_min: int) -> datetime:
    """기준 시각 → aware UTC. None = 지금 · 날짜만이면 그날 끝(근무 시간대, 지금보다 늦으면 지금) · 시각대 없는 ISO 는
    근무 시간대로 본다. 지금 + 여유보다 늦으면 ValueError('미래 불가' — R §5.3.1)."""
    tz = timezone(timedelta(minutes=int(off_min)))
    if v is None:
        return now_utc
    if isinstance(v, str):
        s = v.strip()
        if _DATE_RX.match(s):
            v = date.fromisoformat(s)
        else:
            try:
                v = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
            except ValueError:
                raise ValueError("기준 시각은 ISO 8601 입니다(예 2026-10-05T18:00:00+09:00)") from None
    if isinstance(v, datetime):
        dt = (v.replace(tzinfo=tz) if v.tzinfo is None else v).astimezone(UTC)
    elif isinstance(v, date):
        dt = min(datetime.combine(v, dtime(23, 59, 59), tzinfo=tz).astimezone(UTC), now_utc)
    else:
        raise ValueError("기준 시각 형식이 아닙니다")
    if dt > now_utc + timedelta(seconds=AS_OF_SLACK_S):
        raise ValueError("기준 시각은 지금보다 늦을 수 없습니다")
    return dt


def _missing_methods(paths) -> list[str]:
    return [m for m in REQUIRED_PATH_METHODS if not callable(getattr(paths, m, None))
            and not (m in _PATH_ALT and callable(getattr(paths, _PATH_ALT[m], None)))]


def read_run_status(paths, run_id: str) -> dict | None:
    """그 실행의 ``run_status.json``(없거나 깨졌거나 형식이 아니면 None). ``Paths.run_status_file`` 이 없으면 None."""
    fn = getattr(paths, "run_status_file", None)
    if fn is None or not isinstance(run_id, str) or not _RUN_RX.match(run_id):
        return None
    obj = fsx.read_json(fn(run_id), None, want=dict)
    return obj if isinstance(obj, dict) and obj.get("schema") == SCHEMA else None


def read_current(paths) -> dict | None:
    """``current.json``(지금 화면이 보는 실행 — R §2.4.3). 없거나 형식이 아니면 None."""
    obj = fsx.read_json(paths.analysis_current(), None, want=dict)
    if not isinstance(obj, dict) or not _RUN_RX.match(str(obj.get("run_id") or "")):
        return None
    return obj


def _write_current(paths, run_id: str, *, d0: str, d1: str, as_of: str, chosen: str, at: str,
                   period_source=None, period_months=None) -> dict:
    from lm27.report import REPORT_VERSION
    obj = {"schema": CURRENT_SCHEMA, "run_id": run_id, "from": d0, "to": d1, "as_of": as_of, "built_at": at,
           "report_version": REPORT_VERSION, "chosen": chosen, "chosen_at": at, "period_source": period_source,
           "period_months": period_months}
    fsx.atomic_write(paths.analysis_current(), fsx.canon_bytes(obj))
    return obj


def choose_current(paths, cfg, run_id: str, *, now=None) -> dict:
    """사용자가 분석 이력에서 [이 결과 보기]를 누름 — ``current.json`` 을 그 실행으로(``chosen = explicit``, R §2.4.3).
    그 실행의 run_status 가 없거나 보고서까지 끝나지 않았으면 ValueError(한국어)."""
    st = read_run_status(paths, run_id)
    if st is None:
        raise ValueError("그 분석 실행 기록이 없습니다")
    rep = next((s for s in st.get("stages") or () if isinstance(s, dict) and s.get("id") == "report"), None)
    if not rep or rep.get("state") not in ("done", "partial"):
        raise ValueError("그 실행은 보고서까지 끝나지 않아 고를 수 없습니다")
    off = int(cfg["time.tzOffsetMin"])
    at = _local_iso(_now_fn(now)(), off)
    return _write_current(paths, run_id, d0=str(st.get("from")), d1=str(st.get("to")), as_of=str(st.get("as_of")),
                          chosen="explicit", at=at, period_source=st.get("period_source"),
                          period_months=st.get("period_months"))


def last_result() -> dict:
    """마지막 ``analyze`` 의 요약(run_id·state·rc·reason·current 교체 여부·단계 상태) — 화면·시험용."""
    with _LOCK:
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in _LAST.items()}


def _set_last(**kw) -> None:
    with _LOCK:
        _LAST.clear()
        _LAST.update(kw)


# ───────────────────────────── 공개 함수 ─────────────────────────────
def analyze(paths, cfg, *, from_=None, to=None, as_of=None, ai=True, rerun=None, stages=None,
            period_source=None, period_months=None, now=None, run_id=None, bridge=None, team_client=AUTO,
            copilot_role=None, cancel=None) -> int:
    """분석 실행(계약 §2.13 · §7.1) → rc(0·1·2·4 — 계약 §8.3).

    cli 어댑터 형은 ``analyze(paths, cfg, from_=, to=, as_of=, ai=, rerun=, stages=list|None)``. 나머지 키워드는 화면·시험
    주입점: ``period_source``·``period_months``(기간 출처 — R RP8, 화면이 넘긴다) · ``now``(시계: datetime 또는 호출 가능) ·
    ``run_id``(새 실행 id 고정) · ``bridge``(브리지 호출 ``fn(paths, cfg, run_id, 단계 id, [브리지 단계], cancel=) ->
    BridgeRun|int``, 기본 `process_bridge`) · ``team_client``(레지스트리 받기 모듈 — 기본 ``lm27.team.client``, None = 받지
    않음) · ``copilot_role``(None = pc.json 역할로 판정) · ``cancel``(참이면 다음 단계부터 중단)."""
    now_fn = _now_fn(now)
    t_now = now_fn()
    off = int(cfg["time.tzOffsetMin"])
    rerun_of = rerun or None
    try:
        missing = _missing_methods(paths)
        if missing:
            raise _ArgError(f"경로 로더에 분석 결과 경로 메서드가 없습니다({', '.join(missing)}) — "
                            "프로그램을 최신으로 바꾼 뒤 다시 실행하세요", reason="paths_method_missing")
        sel = S.check_ids(stages) if stages is not None else None
        if rerun_of is not None:
            src = read_run_status(paths, rerun_of) if _RUN_RX.match(str(rerun_of)) else None
            if src is None:
                raise _ArgError("다시 분석할 실행 기록이 없습니다", reason="rerun_missing")
            if from_ is not None or to is not None:
                raise _ArgError("--rerun 과 --from/--to 는 함께 쓸 수 없습니다")
            d0, d1 = _as_date(src.get("from"), "원본 실행 시작"), _as_date(src.get("to"), "원본 실행 끝")
            as_of = src.get("as_of") if as_of is None else as_of
            period_source = period_source or "rerun"
        else:
            if from_ is None or to is None:
                raise _ArgError("분석 기간(--from·--to)이 필요합니다")
            d0, d1 = _as_date(from_, "시작"), _as_date(to, "끝")
            period_source = period_source or "user"
        if d0 > d1:
            raise _ArgError("시작 날짜가 끝 날짜보다 늦습니다")
        t_as_of = _parse_as_of(as_of, t_now, off)
        if t_as_of.astimezone(timezone(timedelta(minutes=off))).date() < d0:
            raise _ArgError("기준 시각이 분석 시작일보다 앞섭니다")
        plan = S.plan_run(sel, ai=bool(ai), rerun=rerun_of is not None)
        rid = _new_run(paths, run_id, t_now)
    except _ArgError as e:
        return _arg_fail(str(e), e.reason)
    except ValueError as e:
        return _arg_fail(str(e), "bad_args")
    tc = _team_client(team_client)
    run = _Run(paths=paths, cfg=cfg, run_id=rid, d0=d0, d1=d1, as_of=t_as_of, off_min=off, ai=bool(ai), plan=plan,
               now=now_fn, bridge=bridge or process_bridge, team_client=tc,
               copilot_role=copilot_role if copilot_role is None else bool(copilot_role), cancel=cancel,
               rerun_of=rerun_of, selected=sel, period_source=period_source,
               period_months=period_months if isinstance(period_months, int) else None)
    return _execute(run)


class _ArgError(ValueError):
    def __init__(self, msg: str, reason: str = "bad_args"):
        super().__init__(msg)
        self.reason = reason


def _arg_fail(msg: str, reason: str) -> int:
    events.emit("warn", text_ko=_clip(msg))
    _set_last(run_id=None, state="failed", rc=RC_FAIL, reason=reason, current=False, stages={})
    return RC_FAIL


def _new_run(paths, run_id, t_now) -> str:
    if run_id is not None:
        if not _RUN_RX.match(str(run_id)):
            raise ValueError("run_id 형식이 아닙니다(YYYYMMDD-HHMMSS-xxxx)")
        if os.path.exists(fsx.longp(paths.analysis(str(run_id)))):
            raise ValueError("그 run_id 의 실행 폴더가 이미 있습니다 — 이전 실행을 덮지 않습니다")
        return str(run_id)
    for _ in range(8):
        rid = new_run_id(t_now)
        if not os.path.exists(fsx.longp(paths.analysis(rid))):
            return rid
    return new_run_id(t_now)


def _team_client(v):
    if v is not AUTO:
        return v
    if importlib.util.find_spec("lm27.team.client") is None:
        return None
    return importlib.import_module("lm27.team.client")


# ───────────────────────────── 실행 ─────────────────────────────
def _skeleton(run: _Run) -> dict:
    from lm27 import LM27_VERSION
    return {"schema": SCHEMA, "run_id": run.run_id, "from": run.d0.isoformat(), "to": run.d1.isoformat(),
            "as_of": run.as_of_iso, "started": _utc_iso(run.now()), "ended": None, "state": "running", "rc": None,
            "reason": None, "hint": "", "ai": run.ai, "rerun_of": run.rerun_of, "stages_selected": run.selected,
            "period_source": run.period_source, "period_months": run.period_months, "pid": os.getpid(),
            "job_id": events.job_id(), "lm27_version": LM27_VERSION, "calendar": None, "registry": None,
            "warnings": [], "ai_pending": 0, "current": False, "pruned": 0,
            "stages": [{"id": s.id, "name_ko": s.name_ko, "state": "pending"} for s in S.STAGES]}


def _save(run: _Run) -> None:
    st = run.status
    st["warnings"] = list(run.warnings)
    st["stages"] = [run.results.get(s.id) or next((x for x in st["stages"] if x.get("id") == s.id),
                                                  {"id": s.id, "name_ko": s.name_ko, "state": "pending"})
                    for s in S.STAGES]
    fsx.atomic_write(run.paths.run_status_file(run.run_id), fsx.canon_bytes(st))


def _record(run: _Run, sd: S.StageDef, out: _Out, *, auto: bool = False) -> dict:
    fields = {"state": out.state, "items_total": max(0, _int(out.items_total)), "items_ok": max(0, _int(out.items_ok)),
              "items_failed": max(0, _int(out.items_failed)), "items_pending": max(0, _int(out.items_pending)),
              "stop_kind": out.stop_kind if out.state != "done" else None, "reason": out.reason,
              "hint": _clip(out.hint), "counts": dict(out.counts), "updated": _utc_iso(run.now())}
    if out.resumable is not None:
        fields["resumable"] = bool(out.resumable)
    elif out.state == "partial":
        fields["resumable"] = True
    extra = {"id": sd.id, "name_ko": sd.name_ko}
    rk = _reason_ko(out.reason)
    if rk:
        extra["reason_ko"] = rk
    if auto:
        extra["auto"] = True
    extra.update(out.extra)
    try:
        obj = SR.build_stage_result(run.run_id, sd.id, **fields, **extra)
    except ValueError:
        obj = SR.build_stage_result(run.run_id, sd.id, state="failed", stop_kind="fatal", resumable=True,
                                    reason=SR.INVALID_REASON, hint=_hint("internal_error"), id=sd.id,
                                    name_ko=sd.name_ko, updated=_utc_iso(run.now()))
    run.results[sd.id] = obj
    if obj["state"] in ("done", "partial") or obj.get("reused_from"):
        run.available.add(sd.id)                  # 산출이 있다(재분석 원본에서 옮겨 쓴 time 포함)
    return obj


def _blocked(run: _Run, sd: S.StageDef) -> str | None:
    """이 단계를 건너뛸 사유(없으면 None): 사전 거부 · 중단 · 기록 없음 · 앞 단계 실패 · 입력 단계 산출 없음.
    재분석에서 원본 결과를 다시 쓰는 사슬 단계(``skip:reused``)는 산출이 없어도 막지 않는다(time 이 옮겨 쓴다)."""
    if run.refused:
        return run.refused
    if run.cancelled:
        return "cancelled"
    if run.no_records and sd.id != "load":
        return "no_records"
    if run.fatal:
        return "upstream_failed"
    for n in sd.needs:
        if n not in run.available and run.plan.get(n, "") != "skip:reused":
            return "upstream_failed"
    return None


def _execute(run: _Run) -> int:
    run.status = _skeleton(run)
    _save(run)
    events.emit("msg", text_ko=f"분석을 시작합니다({run.d0.isoformat()} ~ {run.d1.isoformat()})")
    try:
        _preflight(run)
    except _Refuse as e:
        run.refused = e.reason
        run.status.update(e.extra)
    except KeyboardInterrupt:
        run.cancelled = True
        for sd in S.STAGES:
            _record(run, sd, _Out(state="skipped", reason="cancelled", hint=_hint("cancelled")))
        _finish(run)
        raise
    except Exception as e:                       # 사전 점검 내부 오류 — 유형 이름만
        run.refused = "internal_error"
        run.status["error_type"] = type(e).__name__
    try:
        for sd in S.STAGES:
            if not run.cancelled and run.cancel is not None and run.cancel():
                run.cancelled = True
            act = run.plan.get(sd.id, "skip:not_selected")
            if act.startswith("skip:") and not (run.refused or run.cancelled):
                why = act[len("skip:"):]                      # 계획상 건너뜀(ai_off · not_selected · reused)
            else:
                why = _blocked(run, sd)
            if why is not None:
                _record(run, sd, _Out(state="skipped", reason=why, hint=_hint(why, _years_text(run))))
                _save(run)
                continue
            _run_one(run, sd, act)
    except KeyboardInterrupt:
        run.cancelled = True
        for sd in S.STAGES:
            if sd.id not in run.results:
                _record(run, sd, _Out(state="skipped", reason="cancelled", hint=_hint("cancelled")))
        _finish(run)
        raise
    return _finish(run)


def _years_text(run: _Run) -> str:
    ys = run.status.get("years") or ()
    return ", ".join(str(y) for y in ys)


def _run_one(run: _Run, sd: S.StageDef, act: str) -> None:
    run.results.pop(sd.id, None)
    run.status["stages"] = [({"id": sd.id, "name_ko": sd.name_ko, "state": "running", "started": _utc_iso(run.now())}
                             if x.get("id") == sd.id else x) for x in run.status["stages"]]
    _save(run)
    events.emit("stage_start", stage=sd.id, name_ko=sd.name_ko)
    fn = _STAGE_FN[sd.id]
    run.hb = events.Heartbeat(events.HEARTBEAT_SEC, stage=sd.id)       # 30초 생존 신호(계약 §8.6)
    try:
        with run.hb:
            out = fn(run, sd, act)
    except _Fail as e:
        fatal = e.fatal if e.fatal is not None else sd.id in _CHAIN_FATAL
        out = _Out(state="failed", stop_kind="fatal", resumable=not fatal, reason=e.reason,
                   hint=e.hint or _hint(e.reason, ", ".join(str(y) for y in e.extra.get("years", ()))),
                   extra=dict(e.extra))
        if fatal:
            run.fatal = e.reason
    except KeyboardInterrupt:
        _record(run, sd, _Out(state="partial", stop_kind="cancelled", resumable=True, reason="cancelled",
                              hint=_hint("cancelled")))
        events.emit("stage_end", stage=sd.id, name_ko=sd.name_ko, state="partial", text_ko=_hint("cancelled"))
        raise
    except Exception as e:                       # 내부 오류 — 유형 이름만(메시지에 원문이 섞일 수 있다)
        fatal = sd.id in _CHAIN_FATAL
        out = _Out(state="failed", stop_kind="fatal", resumable=True, reason="internal_error",
                   hint=_hint("internal_error"), extra={"error_type": type(e).__name__})
        if fatal:
            run.fatal = "internal_error"
    obj = _record(run, sd, out, auto=act == "auto")
    _save(run)
    events.emit("stage_end", stage=sd.id, name_ko=sd.name_ko, state=obj["state"], done=obj["items_ok"],
                total=obj["items_total"] or None,
                text_ko=obj["hint"] or (_DONE_HINT.get(sd.id) if obj["state"] == "done" else None))


# ───────────────────────────── 사전 점검 ─────────────────────────────
def _keyring(paths):
    """주 키링(만들지 않는다 — 분석은 수집이 만든 키로만). 없거나 깨졌으면 None(깨진 파일은 키링 모듈이 옆으로 옮긴다)."""
    from lm27.privacy import NoKeyringError, load_keyring
    try:
        return load_keyring(paths.data(), None, create=False)
    except (NoKeyringError, OSError, ValueError):
        return None


def _preflight(run: _Run) -> None:
    """레지스트리 받기(주기 안이면 네트워크 없음) → 유효 레지스트리 → 달력 → 달력 미확인 연도면 거부."""
    from lm27.hier.registry import builtin_registry, load_effective
    from lm27.time.calendar import load_calendar
    tc = run.team_client
    info = {"source": None, "version": None, "refresh_rc": None}
    if tc is not None and hasattr(tc, "refresh_registry") and run.rerun_of is None:   # 재분석은 원본이 받은 캐시로(빠르게)
        try:
            rr = tc.refresh_registry(run.paths, run.cfg)
            info["refresh_rc"] = _int(getattr(rr, "rc", None), None)
        except Exception as e:                   # 받기는 덤이다 — 실패해도 가진 레지스트리로 분석한다(유형만 남김)
            run.warn("registry_refresh", f"팀 레지스트리를 받지 못해 가진 레지스트리로 분석합니다({type(e).__name__})")
    run.kr = _keyring(run.paths)
    reg = st = None
    for persist in (True, False):                # 개인 과제 대응 저장이 막혀도(읽기 전용 폴더) 읽기는 계속
        try:
            reg, st = load_effective(run.paths, run.cfg, run.now(), kr=run.kr, persist=persist)
            break
        except OSError as e:
            run.warn("registry_persist", f"개인 레지스트리를 저장하지 못했습니다({type(e).__name__})")
        except (ValueError, KeyError) as e:
            run.warn("registry_unreadable", f"레지스트리를 읽지 못해 내장 어휘로 분석합니다({type(e).__name__})")
            break
    if reg is None:
        reg, st = builtin_registry(run.cfg), None
    if st is not None and getattr(st, "adopt_offline", False) and tc is not None and hasattr(tc, "adopt_offline"):
        try:
            tc.adopt_offline(run.paths, run.cfg)                     # 오프라인 사본 → 캐시(TAB §5.3 — 팀 클라이언트 몫)
        except Exception as e:
            run.warn("registry_offline", f"오프라인 레지스트리 사본을 캐시로 옮기지 못했습니다({type(e).__name__})")
    run.reg, run.reg_status = reg, st
    info["source"] = str(getattr(st, "source", None) or getattr(reg, "source", "builtin"))
    info["version"] = _int(getattr(st, "version", None), _int(getattr(reg, "version", None), 0))
    for w in (getattr(st, "warnings", ()) or ())[:10]:
        run.warn("registry", f"레지스트리 확인 메모: {w}")
    run.status["registry"] = info
    cal = load_calendar(run.paths, reg)
    run.cal = cal
    run.status["calendar"] = {"version": str(getattr(cal, "version", "")), "source": str(getattr(cal, "source", "")),
                              "warnings": [_clip(w) for w in (getattr(cal, "warnings", ()) or ())][:10]}
    for w in getattr(cal, "warnings", ()) or ():
        run.warn("calendar", str(w))
    miss = cal.missing_years(run.d0, run.d1)
    if miss:
        ys = sorted(int(y) for y in miss)
        raise _Refuse("calendar_unknown_year", years=ys, year=ys[0])


# ───────────────────────────── 단계 본문 ─────────────────────────────
def _local_date(ts: str, off_min: int) -> date | None:
    try:
        dt = datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (dt + timedelta(minutes=off_min)).date()


def _st_load(run: _Run, sd, act) -> _Out:
    from lm27.normalize.load import load_evidence, load_report
    rows = load_evidence(run.paths, run.cfg, run.d0 - timedelta(days=1), run.d1 + timedelta(days=1))
    rep = load_report()
    run.rows, run.load_rep = rows, rep
    kinds = rep.get("kinds") or {}
    in_period = sum(1 for r in rows if (d := _local_date(r.get("ts_utc"), run.off_min)) is not None
                    and run.d0 <= d <= run.d1)
    counts = {"records": len(rows), "in_period": in_period, "rows_in": _int(rep.get("rows_in")),
              "by_kind": {k: _int(v.get("records")) for k, v in sorted(kinds.items()) if isinstance(v, dict)},
              "segments_read": sum(_int(v.get("segments_read")) for v in kinds.values() if isinstance(v, dict)),
              "duplicates": sum(_int(v.get("duplicates")) for v in kinds.values() if isinstance(v, dict)),
              "skipped": sum(_int(v.get("skipped")) for v in kinds.values() if isinstance(v, dict)),
              "missing": sum(_int(v.get("missing")) for v in kinds.values() if isinstance(v, dict)),
              "resanitized": _int(rep.get("resanitized")), "overlay_rows": _int(rep.get("overlay_rows"))}
    if in_period == 0:
        run.no_records = True
        return _Out(state="done", counts=counts, items_total=counts["rows_in"], items_ok=len(rows),
                    reason="no_records", hint=_hint("no_records"))
    return _Out(counts=counts, items_total=counts["rows_in"], items_ok=len(rows))


def _coverage(run: _Run) -> list[dict]:
    """커버리지 원장(파생 — 계약 §3.11)의 기간 셀 → 시간 코어 프로필 ``coverage``(E3i 보류 판정 재료)."""
    try:
        raw = fsx.read_bytes(run.paths.coverage_ledger())
    except FileNotFoundError:
        return []
    except OSError as e:
        run.warn("coverage_unreadable", f"커버리지 원장을 읽지 못했습니다({type(e).__name__})")
        return []
    lo, hi = (run.d0 - timedelta(days=1)).isoformat(), (run.d1 + timedelta(days=1)).isoformat()
    out, bad = [], 0
    for ln in raw.decode("utf-8-sig", "replace").splitlines():
        if not ln.strip():
            continue
        try:
            r = fsx.loads_strict(ln)
        except ValueError:
            bad += 1
            continue
        d = str(r.get("date") or "") if isinstance(r, dict) else ""
        if _DATE_RX.match(d) and lo <= d <= hi:
            out.append({"date": d, "kind_axis": r.get("kind_axis"), "status": r.get("status")})
    if bad:
        run.warn("coverage_broken", f"커버리지 원장의 깨진 줄 {bad}개를 건너뛰었습니다")
    return out


def _st_normalize(run: _Run, sd, act) -> _Out:
    from lm27.normalize.absence import leaves
    rep = run.load_rep                                   # 적재 단계가 받아 둔 병합·화행 건수(load_report)
    lv = leaves(run.rows, run.cal, off_min=run.off_min)
    cov = _coverage(run)
    run.profile = {"d0": run.d0, "d1": run.d1, "leaves": lv, "coverage": cov}
    merge = rep.get("merge") or {}
    counts = {"merged_exact": _int(merge.get("exact_merged")), "merged_fuzzy": _int(merge.get("fuzzy_merged")),
              "date_absorbed": _int(merge.get("date_absorbed")), "copilot_dups": _int(merge.get("copilot_dups")),
              "room_private": _int(rep.get("room_private")), "leave_days": len(lv), "coverage_cells": len(cov),
              "acts": {k: _int(rep.get(k)) for k in ("act_rule", "act_ai", "act_manual", "presence")}}
    out = _Out(counts=counts, items_total=len(run.rows), items_ok=len(run.rows))
    names, why = run.gate(sd.bridge)
    if why is not None:
        out.extra["speech_act"] = why
        return out
    try:
        _speech_act(run, sd, names, out)
    except Exception as e:                       # AI 보조 단계는 fail-soft — 규칙 화행으로 계속(유형만 남김)
        out.state, out.reason, out.hint = "partial", "bridge_failed", _hint("bridge_failed")
        out.stop_kind, out.resumable = "fatal", True
        out.extra.update(speech_act="error", error_type=type(e).__name__)
    return out


def _speech_act(run: _Run, sd, names, out: _Out) -> None:
    """B §2.3 호출 지점 2 — 화행 회색 지대 → 브리지 speech_act → 화행 다시 붙이기(번들을 다시 읽지 않는다)."""
    from lm27.normalize.act import write_speech_act_in
    from lm27.normalize.load import apply_acts
    n = write_speech_act_in(run.paths, run.rows, run.cfg)
    out.counts["speech_act_items"] = n
    if n <= 0:
        out.extra["speech_act"] = "no_items"
        return
    sub = _bridge_out(_call_bridge(run, sd.id, names))
    acts = apply_acts(run.rows, run.paths, run.cfg)
    out.counts["acts"] = {k: _int(v) for k, v in sorted(acts.items())}
    out.counts["speech_act_ok"] = sub.items_ok
    out.counts["speech_act_pending"] = sub.items_pending
    out.extra["speech_act"] = sub.state
    out.extra["bridge_rc"] = sub.extra.get("bridge_rc")
    if sub.state != "done":
        out.state, out.reason, out.hint = "partial", sub.reason, sub.hint
        out.stop_kind, out.resumable, out.items_pending = sub.stop_kind, True, sub.items_pending


def _check_conservation(res) -> None:
    """T-01 파이프라인 재검사: 날마다 Σ귀속 초 = 300 × 봉투 슬롯(정수), 귀속 슬롯 = 봉투 슬롯."""
    from lm27.time.calendar import SLOT, d_of
    env_day: Counter = Counter()
    att_day: Counter = Counter()
    slots = set(res.env.slots)
    for s in slots:
        env_day[d_of(s * SLOT)] += SLOT
    bad_type = 0
    for s, dist in res.assign.items():
        tot = 0
        for v in dist.values():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                bad_type += 1
                continue
            tot += v
        att_day[d_of(s * SLOT)] += tot
    days = sorted(set(env_day) | set(att_day))
    viol = [[d.isoformat(), int(env_day[d]), int(att_day[d])] for d in days if env_day[d] != att_day[d]]
    if viol or bad_type or set(res.assign) != slots:
        raise _Fail("conservation", fatal=True, violations=viol[:10], violation_days=len(viol),
                    slot_mismatch=len(set(res.assign) ^ slots), bad_values=bad_type)


def _hier_ctx(run: _Run, **kw) -> dict:
    from lm27.privacy import RULES_VERSION
    ctx = dict(run.hier_ctx)
    ctx.update(kw)
    ctx.update(paths=run.paths, cfg=run.cfg, reg=run.reg, reg_status=run.reg_status, kr=run.kr, now=run.now(),
               as_of=run.as_of.astimezone(timezone(timedelta(minutes=run.off_min))).date(), rules_ver=RULES_VERSION)
    return ctx


def _st_classify(run: _Run, sd, act) -> _Out:
    if run.kr is None:
        raise _Fail("no_keyring")
    import lm27.hier as H
    from lm27.time.attribute import ConservationError
    from lm27.time.calendar import UnknownYearError
    from lm27.time.ledger import task_rows
    pdir = fsx.read_json(run.paths.local_only_file("person_dir.json"), None, want=dict)   # classify_all 과 같은 사람 사전
    feats, tags, tag_rows = H.prepare(run.rows, run.reg, run.cfg, person_dir=pdir, kr=run.kr)
    run.feats, run.tags = feats, tags
    tc = importlib.import_module("lm27.time")
    try:
        res = tc.analyze_time(run.kr, run.rows, run.profile, run.cal, run.as_of, tags=tags, cfg=run.cfg)
    except ConservationError as e:
        raise _Fail("conservation", fatal=True, error_type=type(e).__name__) from None
    except UnknownYearError as e:
        ys = sorted(int(y) for y in getattr(e, "years", ()) or ())
        run.status.update(years=ys, year=ys[0] if ys else None)
        raise _Fail("calendar_unknown_year", fatal=True, years=ys) from None
    _check_conservation(res)
    run.tres = res
    tables = res.tables.as_json()
    run.tables_sig = _sha(tables)
    copilot = run.gate(("task_label",))[1] is None
    ask = copilot and run.plan.get("ai:task_label") == "run"
    # 이번 실행이 AI 를 부르지 않을 뿐이면(--no-ai · 빠른 재분석) 저장된 AI 판정은 그대로 쓴다 — 사람 답·분류 수정 뒤의 빠른
    # 재분석이 AI 과제·분야 판정을 규칙으로 되돌리지 않게(계약 v1.3 §0.8 V14 — LM24 처럼 다음 판정 전까지 결과 유지)
    use_ai = copilot or run.stored_ai_ok(("task_label",))
    run.hier_ctx = {"feats": feats, "tasks": task_rows(res), "attrib": res.attribution.rows(), "team_tables": tables,
                    "slot_basis": dict(res.env.basis), "copilot_enabled": use_ai, "person_dir": pdir}
    try:
        hres = H.classify_all(_hier_ctx(run, write_ai_in=ask, persist=False))
    except H.HierInvariantError as e:
        raise _Fail("hier_invariant", fatal=True, error_type=type(e).__name__) from None
    run.task_items = len(hres.ai_items) if ask else 0
    by_level = Counter(str(getattr(lb, "level", "")) for lb in hres.labels.values())
    counts = {"evidence_tags": len(tag_rows), "features": len(feats), "units": len(res.tasks),
              "env_slots": len(res.env.slots), "groups": len(hres.groups), "task_label_items": run.task_items,
              "by_level": {k: v for k, v in sorted(by_level.items()) if k}}
    for w in (getattr(res, "warnings", ()) or ())[:10]:
        run.warn("time", str(w))
    return _Out(counts=counts, items_total=len(res.tasks), items_ok=len(hres.labels),
                extra={"input_digest": str(res.input_digest)[:64]})


def _st_time(run: _Run, sd, act) -> _Out:
    if act == "reuse":
        return _reuse(run)
    import lm27.hier as H
    from lm27.time.mm import rollup
    res = run.tres
    try:
        hres = H.classify_all(_hier_ctx(run, write_ai_in=False, persist=True))
    except H.HierInvariantError as e:
        raise _Fail("hier_invariant", fatal=True, error_type=type(e).__name__) from None
    labels = hres.rollup_labels()
    for m in res.months.values():
        m["rollup"] = rollup(m, labels)
    res.labels = labels
    if _sha(res.tables.as_json()) != run.tables_sig:
        raise _Fail("classify_changed_time", fatal=True)          # T-06
    _check_conservation(res)                                       # T-01(쓰기 직전 다시)
    tc = importlib.import_module("lm27.time")
    tfiles = tc.write_time_files(run.paths, run.run_id, res)          # 경로 메서드는 실행 전에 확인했다
    hfiles = H.write_result(hres, paths=run.paths, run_id=run.run_id)
    run.hier_final = hres
    eff = res.effort()
    bucket = sum(int(v) for k, v in eff.items() if str(k).startswith("B_"))
    total = sum(int(v) for v in eff.values())
    src = Counter()
    for lb in hres.labels.values():
        for v in (getattr(lb, "src", None) or {}).values():
            src["ai" if str(v).startswith("ai") else ("user" if v == "user" else "rule")] += 1
    counts = {"units": len(res.tasks), "env_min": int(res.env_minutes()), "attributed_sec": total - bucket,
              "bucket_sec": bucket, "months": len(res.months), "queue": len(res.queue), "labels": len(labels),
              "label_src": dict(sorted(src.items())), "files": len(tfiles) + len(hfiles)}
    return _Out(counts=counts, items_total=len(res.tasks), items_ok=len(labels))


def _reuse(run: _Run) -> _Out:
    """재분석 원본 실행의 ``time``·``hier`` 결과 파일을 새 실행으로 옮겨 쓴다(읽고 원자 쓰기 — 원본은 그대로)."""
    import lm27.hier as H
    from lm27.report import inputs as I
    from lm27.time.ledger import FILES
    src, dst = run.rerun_of, run.run_id
    n, missing = 0, []
    try:
        for name in FILES:
            try:
                data = fsx.read_bytes(I.time_file(run.paths, src, name))
            except FileNotFoundError:
                missing.append(name)
                continue
            fsx.atomic_write(I.time_file(run.paths, dst, name), data)
            n += 1
        for name in H.RESULT_FILES:
            try:
                data = fsx.read_bytes(I.hier_file(run.paths, src, name))
            except FileNotFoundError:
                continue
            fsx.atomic_write(I.hier_file(run.paths, dst, name), data)
            n += 1
    except I.PathsMethodMissing as e:
        raise _Fail("paths_method_missing", fatal=True, error_type=type(e).__name__) from None
    need = {I.TIME_FILES[k] for k in I.REQUIRED_TIME}
    if need & set(missing):
        raise _Fail("reuse_missing", fatal=True, missing=sorted(need & set(missing)))
    return _Out(state="skipped", reason="reused", hint=_hint("reused"), counts={"files": n},
                extra={"reused_from": src})


def _inputs(run: _Run, *, evidence=True):
    from lm27.report.inputs import load_inputs
    inp = load_inputs(run.run_id, paths=run.paths, cfg=run.cfg, registry=run.reg, cal=run.cal, evidence=evidence)
    if inp.refused:
        raise _Fail("inputs_missing", fatal=False, missing=sorted(inp.refused))
    return inp


def _ai_items(run: _Run, inp, stage_names, *, write: bool) -> dict:
    """분석층(R §4.10.1)으로 ai_in 항목을 만든다 — AI 를 부를 때만 파일로 쓴다(끔이면 세기만)."""
    from lm27.report.analysis import ai_items as AI
    if write:
        out = {}
        for st in stage_names:
            out.update(AI.write_ai_items(run.run_id, st, paths=run.paths, cfg=run.cfg, inputs=inp, cal=run.cal))
        return out
    ctx = AI.context_from_inputs(inp, run.cfg, run.cal)
    out = {}
    for st in stage_names:
        out.update({k: len(v) for k, v in AI.build_items(ctx, st).items()})
    return out


def _st_mining(run: _Run, sd, act) -> _Out:
    inp = _inputs(run)
    run.ev_index = inp.evidence
    names = S.get("ai:workflow").bridge
    ask = run.gate(names)[1] is None and run.plan.get("ai:workflow") == "run"
    counts = _ai_items(run, inp, names, write=ask)
    run.ai_in.update(counts)
    tot = sum(counts.values())
    return _Out(counts={"ai_in": dict(sorted(counts.items())), "written": int(ask)}, items_total=tot, items_ok=tot)


def _st_review(run: _Run, sd, act) -> _Out:
    inp = _inputs(run, evidence=run.ev_index if run.ev_index is not None else True)
    names = S.get("ai:review_text").bridge
    ask = run.gate(names)[1] is None and run.plan.get("ai:review_text") == "run"
    counts = _ai_items(run, inp, names, write=ask)
    run.ai_in.update(counts)
    tot = sum(counts.values())
    return _Out(counts={"ai_in": dict(sorted(counts.items())), "written": int(ask)}, items_total=tot, items_ok=tot)


def _call_bridge(run: _Run, stage: str, names) -> BridgeRun:
    """브리지 호출 — 어떤 예외든 AI 단계 실패로만 남긴다(fail-soft, 유형 이름만). 사용자 중단은 그대로 올린다.
    자식을 감시하는 동안은 감시(watch)가 30초 생존 신호와 진전(done)을 내므로 이 단계의 하트비트를 잠시 멈춘다."""
    hb = run.hb
    if hb is not None:
        hb.stop()
    try:
        v = run.bridge(run.paths, run.cfg, run.run_id, stage, list(names), cancel=run.cancel)
    except Exception as e:
        return BridgeRun(rc=None, reason=None, stages={"_error": {"error_type": type(e).__name__}})
    finally:
        if hb is not None:
            hb.start()
    return _as_bridge_run(v)


def _reason_ok(r) -> bool:
    if not isinstance(r, str) or not r or len(r) > SR.REASON_MAX:
        return False
    return rcmap.is_reason(r) if r.startswith("R-") else bool(SR.STAGE_REASON_RX.match(r))


def _bridge_out(br: BridgeRun) -> _Out:
    """브리지 결과 → 단계 결과(fail-soft — 실패도 partial, 재개 가능)."""
    tot = ok = failed = pending = 0
    subs = {}
    stop = None
    why = None
    for name, s in sorted((br.stages or {}).items()):
        if not isinstance(s, dict) or name.startswith("_"):
            continue
        tot += _int(s.get("items_total"))
        ok += _int(s.get("items_ok"))
        failed += _int(s.get("items_failed"))
        pending += _int(s.get("items_pending"))
        st = s.get("state") if s.get("state") in SR.STATES else None
        subs[name] = {"state": st, "items_ok": _int(s.get("items_ok")), "items_total": _int(s.get("items_total")),
                      "items_pending": _int(s.get("items_pending"))}
        if stop is None and s.get("stop_kind") in SR.STOP_KINDS:
            stop = s.get("stop_kind")
        if why is None and _reason_ok(s.get("reason")):
            why = s.get("reason")
    extra = {"bridge_rc": br.rc if isinstance(br.rc, int) else None, "bridge": subs}
    err = (br.stages or {}).get("_error")
    if isinstance(err, dict) and isinstance(err.get("error_type"), str):
        extra["error_type"] = err["error_type"][:80]
    counts = {"bridge_stages": len(subs)}
    if br.rc == 0 and not br.killed:
        return _Out(counts=counts, items_total=tot, items_ok=ok, items_failed=failed, items_pending=pending,
                    extra=extra)
    if br.killed or br.stop_kind in SR.STOP_KINDS:
        stop = br.stop_kind if br.stop_kind in SR.STOP_KINDS else stop
        why = br.reason if _reason_ok(br.reason) else why
    reason = why or ("bridge_partial" if br.rc == 2 else "bridge_failed")
    hint = _hint("bridge_partial" if br.rc == 2 else "bridge_failed")
    return _Out(state="partial", counts=counts, items_total=tot, items_ok=ok, items_failed=failed,
                items_pending=max(pending, tot - ok - failed, 0), reason=reason, hint=hint,
                stop_kind=stop or ("fatal" if br.rc != 2 else None), resumable=True, extra=extra)


def _st_ai(run: _Run, sd, act) -> _Out:
    names, why = run.gate(sd.bridge)
    if why is not None:
        return _Out(state="skipped", reason=why, hint=_hint(why))
    items = {"task_label": run.task_items}
    items.update(run.ai_in)
    names = [n for n in names if _int(items.get(n)) > 0]
    if not names:
        return _Out(state="skipped", reason="no_items", hint=_hint("no_items"))
    out = _bridge_out(_call_bridge(run, sd.id, names))
    out.counts["asked_stages"] = len(names)
    return out


def _st_report(run: _Run, sd, act) -> _Out:
    from lm27.report import build_report
    br = build_report(run.run_id, paths=run.paths, cfg=run.cfg, now=run.now())
    run.report = br
    rc = _int(getattr(br, "rc", None), RC_FAIL)
    from lm27.report import vocab as RV
    counts = {"missing": len(getattr(br, "missing", ()) or ()), "warnings": len(getattr(br, "warnings", ()) or ())}
    for w in (getattr(br, "warnings", ()) or ())[:10]:
        d = RV.warn(str(w))                                      # 보고서 경고 코드 → 화면 문구(R §5.8 단일원)
        run.warn("report:" + str(d.get("code"))[:60], str(d.get("text_ko") or ""))
    extra = {"report_rc": rc}
    if rc in (RC_OK, RC_NOOP):
        return _Out(counts=counts, items_total=1, items_ok=1, extra=extra)
    if rc == RC_PARTIAL:
        return _Out(state="partial", counts=counts, items_total=1, items_ok=1, reason="report_partial",
                    hint=_hint("report_partial"), resumable=True, extra=extra)
    raise _Fail("report_failed", fatal=True, hint=_clip(getattr(br, "message", "") or _hint("report_failed")),
                problems=len(getattr(br, "problems", ()) or ()), **extra)


_STAGE_FN = {"load": _st_load, "normalize": _st_normalize, "classify": _st_classify, "ai:task_label": _st_ai,
             "time": _st_time, "mining": _st_mining, "ai:workflow": _st_ai, "review": _st_review,
             "ai:review_text": _st_ai, "report": _st_report}


# ───────────────────────────── 마무리 ─────────────────────────────
def _overall(run: _Run) -> tuple[str, int, str | None]:
    res = run.results
    if run.refused:
        return "failed", RC_FAIL, run.refused
    if run.cancelled:
        return "partial", RC_PARTIAL, "cancelled"
    if run.fatal:
        return "failed", RC_FAIL, run.fatal
    if run.no_records:
        return "done", RC_NOOP, "no_records"
    soft = [r for r in (res.get(s.id) for s in S.STAGES) if r and r["state"] in ("partial", "failed")]
    if soft:
        return "partial", RC_PARTIAL, soft[0].get("reason") or "partial"
    return "done", RC_OK, None


def _finish(run: _Run) -> int:
    state, rc, reason = _overall(run)
    st = run.status
    rep = run.results.get("report")
    current = False
    if state in ("done", "partial") and not run.cancelled and rep is not None and rep["state"] in ("done", "partial"):
        at = _local_iso(run.now(), run.off_min)
        _write_current(run.paths, run.run_id, d0=run.d0.isoformat(), d1=run.d1.isoformat(), as_of=run.as_of_iso,
                       chosen="auto", at=at, period_source=run.period_source, period_months=run.period_months)
        current = True
    pending = sum(_int(r.get("items_pending")) for r in run.results.values()
                  if r.get("id") in S.AI_STAGES or r.get("id") == "normalize")
    try:
        pruned = prune_analysis(run.paths, keep_of(run.cfg), protect=[x for x in (run.run_id, run.rerun_of) if x])
    except OSError:
        pruned = []
    st.update(state=state, rc=rc, reason=reason, hint=_hint(reason, _years_text(run)) if reason else "",
              ended=_utc_iso(run.now()), ai_pending=pending, current=current, pruned=len(pruned))
    rk = _reason_ko(reason)
    if rk:
        st["reason_ko"] = rk
    _save(run)
    summary = {s: (run.results.get(s) or {}).get("state", "pending") for s in S.STAGE_IDS}
    _set_last(run_id=run.run_id, state=state, rc=rc, reason=reason, current=current, stages=summary,
              ai_pending=pending, pruned=list(pruned))
    if current:
        events.emit("notice", text_ko="개인 보고서를 이 분석 결과로 바꿨습니다")
    elif state == "failed":
        events.emit("warn", text_ko=st["hint"] or "분석을 끝내지 못했습니다 — 이전 결과를 그대로 보여 줍니다")
    events.emit("result", run_id=run.run_id, state=state, rc=rc, reason=reason, current=current,
                period={"from": run.d0.isoformat(), "to": run.d1.isoformat()}, ai_pending=pending)
    return rc
