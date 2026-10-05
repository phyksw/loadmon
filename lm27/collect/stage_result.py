# -*- coding: utf-8 -*-
r"""단계 결과 공통 스키마 ``lm27.stage/1`` 과 수집 단계 결과 파일의 원자 기록(계약 §8.5 · §8.4 · X-122 · X-123).

모든 장기 단계(수집·브리지·분석)는 아래 **공통 필드**를 갖는다. 각 명세의 추가 필드는 그 뒤에 붙인다::

    {schema:"lm27.stage/1", run_id, stage, state:"done|partial|failed|skipped",
     items_total, items_ok, items_failed, items_pending,
     stop_kind:"budget|fatal|circuit|refused|manual_wait|header|gate|cancelled|login|stall|no_progress"|null,
     resumable:bool, reason:"<R-* 또는 단계 사유>"|null, hint:"<한국어 한 줄>", caps_hit:bool|{키:수},
     rc:int, updated:UTC, counts:{...}}

* 수집 단계 결과 파일 = ``data\derived\collect\<run_id>\stage_result_<stage>.json`` — `write_stage_result` 가
  ``fsx.atomic_write`` 로 쓴다. 단계 본문은 `stage_scope` 로 감싸 **finally 에서도 파일이 남게** 한다.
  ``rc`` = 수집기 원 rc(X-122. 돌지 않음 = ``rcmap.RC_NOT_RUN``, 감시 종료 = 3). 추가 필드: ``src`` ·
  ``subfolder_ratio`` · ``recurrence_incomplete`` · ``skipped_msg`` · ``reasons``(셀 요약 사유 목록) · ``input_sig`` 등.
  수집 단계의 ``items_total`` = 읽은 원시 행, ``items_ok`` = **새로 저장한 레코드**(collect rc 0/4 판정에 쓴다),
  ``items_failed`` = 버린·오류 행, ``items_pending`` = 예산·상한으로 남은 것(모르면 0).
* 브리지(``data\ai\runs\<run_id>\<stage>.result.json``)·분석(``run_status.json`` 의 ``stages[]``)은 자기 위치에
  같은 공통 필드를 쓴다 — `build_stage_result` 로 만들고 `validate_stage_result` 로 검사할 수 있다.
  단계 rc 는 state 에서 기계적으로(`state_rc`: done·skipped 0 · partial 2 · failed 1, 계약 §8.4), 여러 단계의
  rc 는 `worst_rc`(failed 1 > partial 2 > 0).
* 규칙(계약 §8.5): 성공 전 무효화 금지(`may_replace`), 빈 값으로 덮지 않음(`keep_nonempty`), 재개는 입력 서명
  기준(`input_sig` · `resume_decision`). 별도 하트비트 파일은 두지 않는다 — 하트비트는 §8.6 progress 이벤트다.
* 원문 0: 결과에는 숫자·열거·사유 코드·짧은 한국어 안내만 둔다. ``counts`` 에는 수만, 추가 필드의 문자열은
  256자 이하만 받는다(원문을 실수로 담는 길을 좁힌다). 예외는 유형 이름(``error_type``)만 남긴다.
"""
import math
import os
import re

from lm27.collect import rcmap
from lm27.util import fsx

SCHEMA = "lm27.stage/1"
STATES = ("done", "partial", "failed", "skipped")
STOP_KINDS = ("budget", "fatal", "circuit", "refused", "manual_wait", "header", "gate", "cancelled", "login",
              "stall", "no_progress")
COMMON_FIELDS = ("schema", "run_id", "stage", "state", "items_total", "items_ok", "items_failed", "items_pending",
                 "stop_kind", "resumable", "reason", "hint", "caps_hit", "rc", "updated", "counts")
ITEM_FIELDS = ("items_total", "items_ok", "items_failed", "items_pending")
# 수집 단계(계약 §8.5 표) — 결과 파일 이름 stage_result_<stage>.json 의 stage 는 이 중 하나
COLLECT_STAGES = ("probe", "pc_bundle", "mail_local", "cal_local", "teams_uia_check", "backfill_owa",
                  "backfill_teams_web", "copilot_lookup", "import", "export", "derive", "upload")
STATE_RC = {"done": 0, "skipped": 0, "partial": 2, "failed": 1}      # 계약 §8.4
_RC_RANK = {1: 2, 2: 1, 0: 0}                                         # 최악값 순서 failed 1 > partial 2 > 0

RUN_ID_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")                 # 계약 §9.4 · CR-01
STAGE_RX = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)?$")       # 분석 단계 id 는 'ai:task_label' 꼴
STAGE_REASON_RX = re.compile(r"^[a-z][a-z0-9_]*(:[a-z0-9_.-]+)?$")   # 단계 사유(web_exposed · gated:<사유> 등)
EXTRA_KEY_RX = re.compile(r"^[a-z][a-z0-9_]*$")
UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CTRL_RX = re.compile(r"[\x00-\x1f\x7f]")
HINT_MAX = 200
REASON_MAX = 80
EXTRA_STR_MAX = 256
_MAX_DEPTH = 6

EXC_RC = rcmap.RC_KILLED            # 예외로 끝난 수집 단계의 rc — 원장은 transport_fail(다음 실행에서 다시)
EXC_REASON = "R-TRANSPORT"
HINT_EXC = "내부 오류로 단계를 끝내지 못했습니다 — 다음 실행에서 다시 시도합니다"
INVALID_REASON = "stage_result_invalid"


# ── rc 도구(계약 §8.4) ─────────────────────────────────────────────────────
def state_rc(state) -> int:
    """단계 state → rc(done·skipped 0 · partial 2 · failed 1). 모르는 state 는 ValueError."""
    if state not in STATE_RC:
        raise ValueError(f"모르는 단계 state: {state!r}")
    return STATE_RC[state]


def worst_rc(rcs) -> int:
    """여러 단계 rc 의 최악값(failed 1 > partial 2 > done·skipped 0). 빈 목록 → 0. 0·1·2 밖의 값은 ValueError."""
    best, rank = 0, 0
    for rc in rcs:
        if isinstance(rc, bool) or rc not in _RC_RANK:
            raise ValueError(f"단계 rc 는 0·1·2 만: {rc!r}")
        if _RC_RANK[rc] > rank:
            best, rank = rc, _RC_RANK[rc]
    return best


# ── 검사 ───────────────────────────────────────────────────────────────────
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _echo(v) -> str:
    """오류 문구에 되비추는 값은 짧게(원문이 섞여 들어와도 길게 퍼지지 않게)."""
    r = repr(v)
    return r if len(r) <= 40 else r[:37] + "..."


def _num_tree(v, depth=0) -> bool:
    """counts 값: 수(int·float·bool) 또는 수의 사전(중첩 허용). 문자열·목록 금지 — 원문이 들어갈 자리를 두지 않는다."""
    if isinstance(v, bool) or _is_int(v):
        return True
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, dict) and depth < _MAX_DEPTH:
        return all(isinstance(k, str) and _num_tree(x, depth + 1) for k, x in v.items())
    return False


def _short_tree(v, depth=0) -> bool:
    """추가 필드 값: JSON 형이고 모든 문자열이 EXTRA_STR_MAX 이하·제어문자 없음."""
    if v is None or isinstance(v, bool) or _is_int(v):
        return True
    if isinstance(v, float):
        return math.isfinite(v)
    if isinstance(v, str):
        return len(v) <= EXTRA_STR_MAX and not _CTRL_RX.search(v)
    if depth >= _MAX_DEPTH:
        return False
    if isinstance(v, (list, tuple)):
        return all(_short_tree(x, depth + 1) for x in v)
    if isinstance(v, dict):
        return all(isinstance(k, str) and len(k) <= EXTRA_STR_MAX and _short_tree(x, depth + 1) for k, x in v.items())
    return False


def _reason_ok(r) -> bool:
    if r is None:
        return True
    if not isinstance(r, str) or not r or len(r) > REASON_MAX:
        return False
    if r.startswith("R-"):
        return rcmap.is_reason(r)          # 사유 코드는 계약 §6.1 표에 있는 것만(L-13)
    return bool(STAGE_REASON_RX.match(r))


def _caps_ok(v) -> bool:
    if isinstance(v, bool):
        return True
    return isinstance(v, dict) and all(isinstance(k, str) and EXTRA_KEY_RX.match(k) and _is_int(x) and x >= 0
                                       for k, x in v.items())


def validate_stage_result(obj, *, collect=False) -> list:
    """공통 필드 검사 → 문제 목록(빈 목록이면 통과). ``collect=True`` 면 수집 단계 이름(COLLECT_STAGES)도 본다."""
    if not isinstance(obj, dict):
        return ["단계 결과가 dict 가 아닙니다"]
    probs = [f"공통 필드 없음: {k}" for k in COMMON_FIELDS if k not in obj]
    if probs:
        return probs
    if obj["schema"] != SCHEMA:
        probs.append(f"schema 는 {SCHEMA}")
    if not isinstance(obj["run_id"], str) or not RUN_ID_RX.match(obj["run_id"]):
        probs.append("run_id 형식(YYYYMMDD-HHMMSS-xxxx) 아님")
    st = obj["stage"]
    if not isinstance(st, str) or not STAGE_RX.match(st) or (collect and st not in COLLECT_STAGES):
        probs.append(f"stage 이름이 틀립니다: {_echo(st)}")
    if obj["state"] not in STATES:
        probs.append(f"state 는 {'·'.join(STATES)} 중 하나")
    for k in ITEM_FIELDS:
        if not _is_int(obj[k]) or obj[k] < 0:
            probs.append(f"{k} 는 0 이상 정수")
    if obj["stop_kind"] is not None and obj["stop_kind"] not in STOP_KINDS:
        probs.append(f"stop_kind 가 열거 밖: {_echo(obj['stop_kind'])}")
    if obj["state"] == "done" and obj["stop_kind"] is not None:
        probs.append("state=done 인데 stop_kind 가 있습니다")
    if not isinstance(obj["resumable"], bool):
        probs.append("resumable 은 bool")
    if not _reason_ok(obj["reason"]):
        probs.append("reason 은 null·계약 §6.1 사유 코드·단계 사유(영문 소문자) 중 하나")
    h = obj["hint"]
    if not isinstance(h, str) or len(h) > HINT_MAX or _CTRL_RX.search(h):
        probs.append(f"hint 는 {HINT_MAX}자 이하 한 줄")
    if not _caps_ok(obj["caps_hit"]):
        probs.append("caps_hit 는 bool 또는 {키: 0 이상 정수}")
    if not _is_int(obj["rc"]):
        probs.append("rc 는 정수")
    if not isinstance(obj["updated"], str) or not UTC_RX.match(obj["updated"]):
        probs.append("updated 는 YYYY-MM-DDTHH:MM:SSZ")
    if not isinstance(obj["counts"], dict) or not _num_tree(obj["counts"]):
        probs.append("counts 는 수(또는 수의 사전)만")
    for k, v in obj.items():
        if k in COMMON_FIELDS:
            continue
        if not isinstance(k, str) or not EXTRA_KEY_RX.match(k):
            probs.append(f"추가 필드 이름이 틀립니다: {_echo(k)}")
        elif not _short_tree(v):
            probs.append(f"추가 필드 {k}: JSON 형·문자열 {EXTRA_STR_MAX}자 이하만")
        elif k == "reasons" and not (isinstance(v, (list, tuple)) and all(rcmap.is_reason(r) for r in v)):
            probs.append("reasons 는 계약 §6.1 사유 코드 목록")
    return probs


# ── 만들기 ─────────────────────────────────────────────────────────────────
def build_stage_result(run_id, stage, **fields) -> dict:
    """공통 필드를 채운 단계 결과 dict. ``state`` 필수, 나머지 기본값: items_* 0 · stop_kind None ·
    resumable(state=partial 이면 True) · reason None('' 도 None) · hint '' · caps_hit False ·
    rc ``state_rc(state)`` · updated 지금 UTC · counts {}. 공통 필드가 아닌 키는 추가 필드로 그대로 싣는다.
    검사(`validate_stage_result`)에 걸리면 ValueError."""
    if "state" not in fields:
        raise ValueError("단계 결과에 state 가 없습니다")
    if "schema" in fields and fields["schema"] != SCHEMA:
        raise ValueError(f"schema 는 {SCHEMA} 만")
    obj = {"schema": SCHEMA, "run_id": run_id, "stage": stage}
    state = fields["state"]
    obj.update(dict.fromkeys(ITEM_FIELDS, 0))
    obj.update(stop_kind=None, resumable=state == "partial", reason=None, hint="", caps_hit=False,
               rc=STATE_RC.get(state, 1), counts={})
    for k, v in fields.items():
        if k in ("schema", "run_id", "stage"):
            continue
        obj[k] = v
    if obj["reason"] == "":
        obj["reason"] = None
    if "updated" not in fields or fields["updated"] is None:
        obj["updated"] = fsx.utcnow_iso()
    probs = validate_stage_result(obj)
    if probs:
        raise ValueError("단계 결과 형식 오류: " + "; ".join(probs))
    return obj


def _check_run_id(run_id):
    if not isinstance(run_id, str) or not RUN_ID_RX.match(run_id):
        raise ValueError(f"run_id 형식(YYYYMMDD-HHMMSS-xxxx) 아님: {_echo(run_id)}")


def _check_collect_stage(stage):
    if stage not in COLLECT_STAGES:
        raise ValueError(f"수집 단계 이름이 아닙니다(계약 §8.5): {_echo(stage)}")


def stage_result_path(paths, run_id, stage) -> str:
    r"""수집 단계 결과 파일 경로 ``data\derived\collect\<run_id>\stage_result_<stage>.json`` — 조립은 경로 단일원
    ``lm27.paths.Paths.stage_result_file`` 이 한다(L-08). 여기서는 run_id·수집 단계 이름만 먼저 검사한다."""
    _check_run_id(run_id)
    _check_collect_stage(stage)
    return os.fspath(paths.stage_result_file(run_id, stage))


# ── 쓰기·읽기 ──────────────────────────────────────────────────────────────
def write_stage_result(paths, run_id, stage, **fields) -> dict:
    """계약 함수: 수집 단계 결과를 ``lm27.stage/1`` 공통 필드 전부와 함께 원자 기록하고 그 dict 를 돌려준다.
    ``state`` 와 수집기 원 ``rc`` 필수(``exit 0`` 고정 금지 — 돌지 않은 단계는 ``rcmap.RC_NOT_RUN``)."""
    _check_run_id(run_id)
    _check_collect_stage(stage)
    if "rc" not in fields:
        raise ValueError("수집 단계 결과에는 수집기 rc 가 필요합니다(돌지 않았으면 rcmap.RC_NOT_RUN)")
    obj = build_stage_result(run_id, stage, **fields)
    fsx.atomic_write(stage_result_path(paths, run_id, stage), fsx.canon_bytes(obj))
    return obj


def read_stage_result(paths, run_id, stage):
    """수집 단계 결과 읽기 — 없거나 깨졌거나 ``lm27.stage/1`` 이 아니면 None."""
    obj = fsx.read_json(stage_result_path(paths, run_id, stage), None, want=dict)
    if obj is None or obj.get("schema") != SCHEMA:
        return None
    return obj


def read_stage_results(paths, run_id) -> dict:
    """한 실행의 수집 단계 결과 전부 ``{stage: 결과}``(COLLECT_STAGES 순서, 있는 것만)."""
    out = {}
    for st in COLLECT_STAGES:
        obj = read_stage_result(paths, run_id, st)
        if obj is not None:
            out[st] = obj
    return out


# ── finally 기록 ───────────────────────────────────────────────────────────
class StageScope:
    """수집 단계 결과를 **finally 에서 반드시** 남기는 문맥 관리자(`stage_scope` 로 만든다).

        with stage_scope(paths, run_id, "mail_local", src="mail.com") as st:
            ... 수집기 실행 ...
            st.outcome(rc, reasons, counts)              # rcmap.stage_outcome 으로 state·stop_kind·reason·rc·hint
            st.set(items_total=rows_in, items_ok=stored)

    * 본문이 아무것도 정하지 않고 끝나면 '돌지 않음'(skipped · rc ``RC_NOT_RUN``)으로 남는다 — 원장은 not_attempted
      (미관측 ≠ 0h, 안전한 기본).
    * 예외로 끝나면 failed · stop_kind fatal · rc 3 · reason R-TRANSPORT · ``error_type``(예외 유형 이름만)으로,
      KeyboardInterrupt 는 partial · stop_kind cancelled 로 남기고 **예외는 그대로 올린다**(삼키지 않는다).
    * 결과 파일 쓰기가 실패해도 원래 예외를 가리지 않는다(``write_error`` 에 유형 이름). 정상 종료 때의 쓰기 실패는 올린다.
    * 본문이 공통 필드에 틀린 값을 넣었으면 형식 오류 사유(``stage_result_invalid``)의 failed 결과라도 남긴 뒤
      ValueError 를 올린다 — 파일은 언제나 남는다."""

    def __init__(self, paths, run_id, stage, fields):
        _check_run_id(run_id)
        _check_collect_stage(stage)
        self.paths, self.run_id, self.stage = paths, run_id, stage
        self.fields = {"state": "skipped", "rc": rcmap.RC_NOT_RUN, "hint": rcmap.HINTS["not_run"]}
        self.fields.update(fields)
        self.result = None
        self.write_error = None

    def set(self, **fields):
        """공통·추가 필드를 정한다(뒤에 정한 값이 이긴다)."""
        self.fields.update(fields)
        return self

    def outcome(self, rc, reasons=(), counts=None):
        """수집기 결과를 `rcmap.stage_outcome` 으로 번역해 state·stop_kind·reason·resumable·caps_hit·rc·hint·reasons 를 정한다.
        계약 §6.1 에 없는 사유 코드(바깥 수집기의 새·폐지 코드)는 예외 없이 R-TRANSPORT 로 접히고 ``unknown_reasons`` 로 센다."""
        self.fields.pop("unknown_reasons", None)
        self.fields.update(rcmap.stage_outcome(rc, reasons, counts))
        return self

    def bump(self, **deltas):
        """items_* 는 그 필드에, 그 밖의 이름은 ``counts`` 에 정수를 더한다."""
        counts = dict(self.fields.get("counts") or {})
        for k, n in deltas.items():
            if not _is_int(n):
                raise TypeError(f"{k}: 정수만 더합니다")
            if k in ITEM_FIELDS:
                self.fields[k] = int(self.fields.get(k) or 0) + n
            else:
                counts[k] = int(counts.get(k) or 0) + n
        self.fields["counts"] = counts
        return self

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        f = dict(self.fields)
        if et is not None:
            reasons = rcmap.norm_reasons(f.get("reasons"))
            if issubclass(et, KeyboardInterrupt):
                f.update(state="partial", stop_kind="cancelled", resumable=True, rc=rcmap.RC_KILLED, reason=None,
                         hint=rcmap.HINTS["cancelled"])
            else:
                if EXC_REASON not in reasons:
                    reasons.append(EXC_REASON)
                f.update(state="failed", stop_kind="fatal", resumable=True, rc=EXC_RC, reason=EXC_REASON,
                         hint=HINT_EXC, error_type=et.__name__)
            f["reasons"] = sorted(reasons)
        bad = None
        try:
            try:
                self.result = write_stage_result(self.paths, self.run_id, self.stage, **f)
            except (ValueError, TypeError) as e:
                bad = e
                self.result = write_stage_result(self.paths, self.run_id, self.stage, **_fallback(f, et))
        except (OSError, ValueError, TypeError) as e:
            self.write_error = type(e).__name__
            if et is None:
                raise
            return False
        if bad is not None and et is None:
            raise bad
        return False


def _fallback(f, et):
    """본문이 넣은 값이 형식에 맞지 않을 때 남기는 최소 결과(숫자 필드는 살릴 수 있는 것만)."""
    keep = {k: f[k] for k in ITEM_FIELDS if _is_int(f.get(k)) and f[k] >= 0}
    out = dict(keep, state="failed", stop_kind="fatal", resumable=True, rc=EXC_RC, reason=INVALID_REASON,
               hint=HINT_EXC, reasons=[EXC_REASON])
    if et is not None:
        out["error_type"] = et.__name__
    return out


def stage_scope(paths, run_id, stage, **initial) -> StageScope:
    """`StageScope` 를 만든다 — ``initial`` 은 처음 필드(예: ``src="mail.com"``). run_id·stage 가 틀리면 본문 전에 ValueError."""
    return StageScope(paths, run_id, stage, initial)


# ── 재개·교체 규칙(계약 §8.5) ──────────────────────────────────────────────
def input_sig(obj) -> str:
    """입력 서명 — 정규 JSON 바이트의 sha256 앞 16자. 재개·건너뛰기 판단의 유일한 근거(결과의 추가 필드 ``input_sig``)."""
    return fsx.sha256_hex(fsx.canon_bytes(obj))[:16]


def resume_decision(prev, sig) -> str:
    """이전 단계 결과와 지금 입력 서명으로: ``"skip"``(같은 입력으로 이미 done) · ``"resume"``(같은 입력으로
    partial·재개 가능) · ``"fresh"``(그 밖 — 처음부터). 서명이 다르면 언제나 fresh 다."""
    if not isinstance(prev, dict) or prev.get("schema") != SCHEMA or not sig or prev.get("input_sig") != sig:
        return "fresh"
    if prev.get("state") == "done":
        return "skip"
    if prev.get("state") == "partial" and prev.get("resumable") is True:
        return "resume"
    return "fresh"


def may_replace(prev, new) -> bool:
    """성공 전 무효화 금지 — 이전 결과(산출물)를 새 것으로 바꿔도 되는가: 이전 것이 없거나 새 결과가 done 일 때만."""
    if not prev:
        return True
    return isinstance(new, dict) and new.get("state") == "done"


def _empty(v) -> bool:
    return v is None or (isinstance(v, (str, list, tuple, dict)) and len(v) == 0)


def keep_nonempty(prev, new) -> dict:
    """빈 값으로 덮지 않음 — ``new`` 의 값이 None·''·[]·{} 이면 ``prev`` 의 값을 남기는 키 단위 병합(새 dict)."""
    out = dict(prev or {})
    for k, v in (new or {}).items():
        if not _empty(v) or k not in out:
            out[k] = v
    return out
