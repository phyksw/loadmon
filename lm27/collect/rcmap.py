# -*- coding: utf-8 -*-
r"""수집기 rc · 정제 파이프 종료 코드 → 커버리지 셀 상태 · 단계 결과 번역(계약 §8.1 · §8.2 · §8.3 · §6.1).

이 모듈은 표준 라이브러리만 쓰고 부작용이 없다(순수 함수 + 표). 쓰는 곳: 원장 재생성(`lm27.collect.ledger`),
수집 흐름(`lm27.collect.run`), 단계 결과(`lm27.collect.stage_result`).

수집기 rc(계약 §8.1, C §8.4): 0 저장(신규 있음) · 1 대상 없음 · 2 로그인 필요 · 3 드라이버 불가·불완전(사유 필수) ·
4 읽었지만 신규 0. 예산·상한 소진은 rc 0 + partial(rc 2 아님). 감시가 끊은 수집기(정체·무진전)는 rc 3 + R-TRANSPORT
(CP §12 의 '타임아웃 → 3·R-TRANSPORT' 대응)이고 단계 결과의 stop_kind 가 `stall`·`no_progress` 다.
돌지 않은 단계는 rc 가 없다 — 단계 결과 파일에는 정수 자리표 ``RC_NOT_RUN``(-1)을 남긴다.

셀 상태 판정(`translate_cell`) — 계약 §8.1 표 + X-120('막힌 사유가 있으면 rc 3'):
  · rc 없음(None·RC_NOT_RUN)                      → not_attempted
  · 감시 종료(stop_kind stall·no_progress)·모르는 rc → transport_fail + R-TRANSPORT
  · rc 2                                           → blocked + R-LOGIN(사람) 또는 R-CA(구조)
  · rc 3                                           → 구조·사람 사유가 있으면 blocked, R-HORIZON 뿐이면 out_of_horizon,
                                                     그 밖은 transport_fail(수송·일시 사유가 없으면 R-TRANSPORT 를 붙인다)
  · rc 0 · 1 · 4 — 상한·예산에 닿았으면 partial(+ R-CAP/R-BUDGET, cap_hit/budget_hit) — T-10, rc 는 바꾸지 않는다
                 — rc 0·4 + R-RECURINC(반복 일정 일부만 펼침 — 계약 v1.2 §0.7 C4 '부분 결과')    → partial
                 — 그 셀 건수 n > 0(또는 rc 0·4 인데 n 을 모름)                 → ok('이미 덮인 날은 ok 유지')
                 — 0건: 구조·사람 사유 → blocked, 수송·일시 사유 → transport_fail
                         (rc 1 의 '막는 사유가 있으면 zero_ok 아님'을 X-120 에 따라 rc 3 과 같게 읽는다 — C 페르소나 12),
                         지평선 밖 → out_of_horizon + R-HORIZON, 그 밖 → zero_ok
미관측 4종(not_attempted · blocked · transport_fail · out_of_horizon)은 0h 가 아니다(T-09) — 그래서 의심스러우면
zero_ok 대신 미관측 쪽으로 판정한다(fail-visible).

``counts`` 로 받는 셀·단계 값(모두 선택):
  ``n``(그 셀 레코드 수) · ``in_horizon``(bool) 또는 ``date`` + ``horizon_oldest``/``horizon_newest``(YYYY-MM-DD…) ·
  ``cap_hit``·``caps_hit``·``budget_hit``(bool) · ``stop_kind``(단계 결과 값 — budget·stall·no_progress·cancelled).
단계 결과(`lm27.stage/1`) dict 를 그대로 ``counts`` 에 넣고 셀 건수만 덧붙여도 된다.
"""
import re

# ── 사유 코드 단일 표(계약 §6.1) ─────────────────────────────────────────────
STRUCTURAL = "structural"     # 구조 — 환경이 막음
HUMAN = "human"               # 사람 — 사람 조치 필요
TRANSIENT = "transient"       # 일시 — 다시 시도하면 될 수 있음
TRANSPORT = "transport"       # 수송 — 드라이버·네트워크·파이프
QUALITY = "quality"           # 품질 — 자료는 있으나 불완전
WARNING = "warning"           # 경고 — 막지 않음
CLASSES = (STRUCTURAL, HUMAN, TRANSIENT, TRANSPORT, QUALITY, WARNING)

REASON_RX = re.compile(r"^R-[A-Z]{2,}(-[A-Z0-9]+)*$")

# code → (분류, 확정 근거 가능). '확정' ✔ = 서로 다른 날 collect.confirmBlockedCount 회면 '불가(확정)' 근거(계약 §6.4).
REASONS = {
    "R-NEWOL": (STRUCTURAL, True),
    "R-NOPROF": (STRUCTURAL, True),
    "R-WIZARD": (STRUCTURAL, True),
    "R-DIALOG": (STRUCTURAL, True),
    "R-CLM": (STRUCTURAL, True),
    "R-APPLOCKER": (STRUCTURAL, True),
    "R-OMG": (STRUCTURAL, True),
    "R-ELEV": (STRUCTURAL, True),
    "R-ONLINE": (STRUCTURAL, True),
    "R-HORIZON": (STRUCTURAL, False),
    "R-SUBFOLDER": (WARNING, False),
    "R-STALE": (WARNING, False),
    "R-NOIDX": (STRUCTURAL, True),
    "R-IDXPOLICY": (STRUCTURAL, True),
    "R-IDXPAUSED": (TRANSIENT, False),
    "R-EDGEPOL": (STRUCTURAL, True),
    "R-LOGIN": (HUMAN, False),
    "R-CA": (STRUCTURAL, True),
    "R-NOLIC": (STRUCTURAL, True),
    "R-NOCONN": (STRUCTURAL, True),
    "R-TZ": (WARNING, False),
    "R-OFFICE": (WARNING, False),
    "R-UIAEMPTY": (STRUCTURAL, True),
    "R-UIAELEV": (STRUCTURAL, True),
    "R-NOADDR": (QUALITY, False),
    "R-NOEVT": (STRUCTURAL, True),
    "R-RECURINC": (QUALITY, False),      # 계약 v1.2 §0.7 C4 — 반복 일정 일부만 펼침
    "R-NOAPP": (WARNING, False),         # 계약 v1.2 §0.7 C4 — 대상 프로그램 미설치
    "R-CAP": (QUALITY, False),
    "R-BUDGET": (TRANSIENT, False),
    "R-TRANSPORT": (TRANSPORT, False),
    "R-COM-BUSY": (TRANSIENT, False),
    "R-COMGAP": (WARNING, False),
    "R-WEBSEL": (STRUCTURAL, True),
    "R-LISTVIRT": (QUALITY, False),
    "R-ROOMGONE": (QUALITY, False),
    "R-NOGIT": (STRUCTURAL, True),
    "R-MRUEMPTY": (WARNING, False),
    "R-RECENTPOLICY": (STRUCTURAL, True),
    "R-NOMACHGUID": (WARNING, False),
    "R-STUCK": (QUALITY, False),
    "R-SAMPLER-ZOMBIE": (QUALITY, False),
    "R-RULESMISMATCH": (TRANSIENT, False),
    "R-NOKEY": (TRANSIENT, False),
    "R-BUNDLE-NETWORK": (WARNING, False),
    "R-BUNDLE-ONEDRIVE": (WARNING, False),
    "R-BUNDLE-REDIRECT": (WARNING, False),
    "R-BUNDLE-LOWSPACE": (WARNING, False),
    "R-BUNDLE-LONGPATH": (WARNING, False),
    "R-BUNDLE-READONLY": (STRUCTURAL, False),
    "R-TEAM-TIMEOUT": (TRANSPORT, False),
    "R-TEAM-REFUSED": (TRANSPORT, False),
    "R-TEAM-DNS": (TRANSPORT, False),
    "R-TEAM-PROXY": (TRANSPORT, False),
    "R-TEAM-LM24": (STRUCTURAL, False),
    "R-TEAM-OTHERAPP": (STRUCTURAL, False),
    "R-TEAM-VERSION": (STRUCTURAL, False),
}
CONFIRMABLE = frozenset(k for k, (_c, ok) in REASONS.items() if ok)

# 0건을 믿지 못하게 하는 사유에서 뺄 것: R-OMG 는 B단(보호 열)만 막고 A단 건수는 믿을 수 있다,
# R-BUDGET 은 partial 로, R-HORIZON 은 out_of_horizon 으로 따로 다룬다.
_ZERO_OK_DESPITE = frozenset({"R-OMG", "R-BUDGET", "R-HORIZON"})
# collect 명령 rc 3(환경 실패, 계약 §8.3): 번들 쓰기 불가는 언제나, 실행 차단은 단계가 failed 일 때만.
ENV_FAIL_ALWAYS = frozenset({"R-BUNDLE-READONLY"})
ENV_FAIL_IF_FAILED = frozenset({"R-CLM", "R-APPLOCKER"})

# ── 상태 열거(계약 §6.4) ───────────────────────────────────────────────────
CELL_STATUSES = ("ok", "zero_ok", "partial", "out_of_horizon", "blocked", "transport_fail", "not_attempted")
UNOBSERVED = frozenset({"not_attempted", "blocked", "transport_fail", "out_of_horizon"})   # 0h 가 아님(T-09)
COLLECTOR_RCS = (0, 1, 2, 3, 4)
RC_NOT_RUN = -1               # 단계 결과 rc 자리표: 수집기가 돌지 않음(§8.1 '돌지 않음')
RC_KILLED = 3                 # 감시가 끊은 수집기의 단계 rc(정체·무진전·취소 후 강제 종료)
WATCH_STOPS = frozenset({"stall", "no_progress"})

# ── 정제 파이프 종료 코드(계약 §8.2, P §3.5) ─────────────────────────────────
PIPE_OK = (0, 2)              # 출력 기록 성공 — 커서 진전 허용(그 밖은 커서 그대로)
PIPE_WAIT_KILLED = 99         # 연결자가 privacy.pipe.waitSec 초과로 kill_tree
_PIPE = {
    3: ("R-TRANSPORT", "정제기 실패 — 다음 수집 주기에 다시 읽습니다"),
    5: ("R-TRANSPORT", "정제기 호출 오류 — 다음 수집 주기에 다시 읽습니다"),
    6: ("R-NOKEY", "정제 키가 없어 자동 복구합니다 — 다음 수집 주기에 다시 읽습니다"),
    99: ("R-TRANSPORT", "정제기 응답 시간이 지나 중단했습니다 — 다음 수집 주기에 다시 읽습니다"),
}
_PIPE_UNKNOWN = ("R-TRANSPORT", "정제기가 알 수 없는 코드로 끝났습니다 — 다음 수집 주기에 다시 읽습니다")

# 단계 결과 hint(한국어 한 줄, 원문·경로 없음)
HINTS = {
    "not_run": "이 PC 에서는 이 단계를 돌리지 않았습니다",
    "done": "",
    "cap": "상한에 닿아 일부만 읽었습니다 — 상한을 넘는 부분은 다른 경로·다음 실행이 채웁니다",
    "budget": "시간 예산에 닿아 일부만 읽었습니다 — 다음 실행이 이어서 읽습니다",
    "login": "로그인이 필요합니다 — 로그인한 뒤 다시 수집하면 이어서 읽습니다",
    "structural": "이 PC 에서는 이 경로를 쓸 수 없습니다 — 다른 경로가 빈칸을 채웁니다",
    "transport": "일시적인 실행·연결 문제로 끝내지 못했습니다 — 다음 실행에서 다시 시도합니다",
    "stall": "응답이 없어 단계를 멈췄습니다 — 다음 실행에서 다시 시도합니다",
    "no_progress": "진행이 늘지 않아 단계를 멈췄습니다 — 다음 실행에서 다시 시도합니다",
    "cancelled": "취소했습니다 — 다음 실행이 이어서 읽습니다",
    "recurinc": "반복 일정의 회차를 일부만 펼쳤습니다 — 다른 경로(웹·반입)가 빠진 회차를 채웁니다",
}
# 상한·예산 밖에서 셀을 partial 로 만드는 품질 사유(계약 v1.2 §0.7 C4 — rc 0·4 의 부분 결과)
PARTIAL_QUALITY = frozenset({"R-RECURINC"})


# ── 사유 코드 도구 ─────────────────────────────────────────────────────────
def is_reason(code) -> bool:
    """계약 §6.1 표에 있는 사유 코드인가."""
    return isinstance(code, str) and code in REASONS


def reason_class(code) -> str:
    """분류(CLASSES 중 하나). 표에 없는 코드는 '수송'으로 본다 — 확정 근거가 못 되고 0건도 믿지 않는다(fail-visible)."""
    ent = REASONS.get(code)
    return ent[0] if ent else TRANSPORT


def confirmable(code) -> bool:
    """'불가(확정)' 근거가 될 수 있는 사유인가(계약 §6.1 '확정' ✔)."""
    return code in CONFIRMABLE


def norm_reasons(reasons) -> list:
    """사유 목록 정리 — 문자열 하나도 받고, 형식(REASON_RX)에 맞는 것만 처음 나온 순서로 중복 없이."""
    if reasons is None:
        return []
    if isinstance(reasons, str):
        reasons = [reasons]
    out = []
    for r in reasons:
        if isinstance(r, str) and REASON_RX.match(r) and r not in out:
            out.append(r)
    return out


def _structural_block(code) -> bool:
    """rc 3·0건 셀을 blocked 로 만드는 사유(구조·사람, 지평선 제외)."""
    return code != "R-HORIZON" and reason_class(code) in (STRUCTURAL, HUMAN)


def _blocks_zero(code) -> bool:
    """0건을 '정상 0건(zero_ok)'으로 믿지 못하게 하는 사유."""
    return code not in _ZERO_OK_DESPITE and reason_class(code) in (STRUCTURAL, HUMAN, TRANSIENT, TRANSPORT)


def _int_or_none(v):
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v


def _in_horizon(c, rs):
    """셀 날짜가 그 경로의 지평선 안인가. 모르면 안으로 본다(지평선 개념이 없는 PC 경로 등)."""
    if "in_horizon" in c and c["in_horizon"] is not None:
        return bool(c["in_horizon"])
    d = c.get("date")
    lo, hi = c.get("horizon_oldest"), c.get("horizon_newest")
    if isinstance(d, str) and len(d) >= 10 and (isinstance(lo, str) or isinstance(hi, str)):
        d = d[:10]
        if isinstance(lo, str) and len(lo) >= 10 and d < lo[:10]:
            return False
        if isinstance(hi, str) and len(hi) >= 10 and d > hi[:10]:
            return False
        return True
    return "R-HORIZON" not in rs           # 셀 지평선 정보가 없으면 실행 사유 R-HORIZON 으로만 판단


def _flags(c, rs):
    cap = bool(c.get("cap_hit")) or bool(c.get("caps_hit")) or "R-CAP" in rs
    budget = bool(c.get("budget_hit")) or c.get("stop_kind") == "budget" or "R-BUDGET" in rs
    return cap, budget


def _add(rs, code):
    if code not in rs:
        rs.append(code)


# ── 셀 상태(계약 §8.1) ─────────────────────────────────────────────────────
def translate_cell(rc, reasons=(), counts=None) -> dict:
    """수집기 rc + 사유 + 셀 건수 → ``{status, reasons, cap_hit, budget_hit}``.
    ``reasons`` 는 정렬된 고유 목록이고, 판정에 함축된 사유(R-CAP·R-BUDGET·R-LOGIN·R-TRANSPORT·R-HORIZON)를 덧붙인다.
    규칙은 모듈 머리말 참조."""
    c = counts if isinstance(counts, dict) else {}
    rs = norm_reasons(reasons)
    cap, budget = _flags(c, rs)
    n = _int_or_none(c.get("n"))
    stop = c.get("stop_kind")
    code = _int_or_none(rc)

    if rc is None or code == RC_NOT_RUN:
        status = "not_attempted"
    elif stop in WATCH_STOPS or code not in COLLECTOR_RCS:
        status = "transport_fail"
        _add(rs, "R-TRANSPORT")
    elif code == 2:
        status = "blocked"
        if "R-LOGIN" not in rs and "R-CA" not in rs:
            _add(rs, "R-LOGIN")
    elif code == 3:
        status = _failed_status(rs)
    elif cap or budget:
        status = "partial"                       # T-10 — 상한·예산이면 반드시 partial, rc 는 그대로
        if cap:
            _add(rs, "R-CAP")
        if budget:
            _add(rs, "R-BUDGET")
    elif code in (0, 4) and any(r in PARTIAL_QUALITY for r in rs):
        status = "partial"                       # C4 — 반복 일정 일부만 펼침: 셀을 '덮였음'으로 두지 않는다
    elif (n is not None and n > 0) or (n is None and code in (0, 4)):
        status = "ok"
    elif any(_structural_block(r) and _blocks_zero(r) for r in rs):
        status = "blocked"
    elif any(_blocks_zero(r) for r in rs):
        status = "transport_fail"
    elif not _in_horizon(c, rs):
        status = "out_of_horizon"
        _add(rs, "R-HORIZON")
    else:
        status = "zero_ok"
    return {"status": status, "reasons": sorted(rs), "cap_hit": bool(cap and status == "partial"),
            "budget_hit": bool(budget and status == "partial")}


def _failed_status(rs):
    """rc 3: 구조·사람 사유 → blocked, 사유가 R-HORIZON 뿐(수송·일시 없음) → out_of_horizon, 그 밖 → transport_fail."""
    if any(_structural_block(r) for r in rs):
        return "blocked"
    transportish = any(reason_class(r) in (TRANSPORT, TRANSIENT) for r in rs)
    if "R-HORIZON" in rs and not transportish:
        return "out_of_horizon"
    if not transportish:
        _add(rs, "R-TRANSPORT")                  # rc 3 은 사유 필수 — 없으면 수송 실패로 본다
    return "transport_fail"


def cell_status(rc, reasons=(), counts=None) -> str:
    """계약 함수: 수집기 rc → 커버리지 셀 상태(§6.4 CELL_STATUSES 중 하나)."""
    return translate_cell(rc, reasons, counts)["status"]


# ── 정제 파이프(계약 §8.2) ─────────────────────────────────────────────────
def pipe_failure(code):
    """계약 함수: 정제 파이프 종료 코드 → ``(rc, reason)``.
    0·2 → ``(None, None)``(수집기 rc 그대로 — 2 는 감사 bad_raw 건수 + 경고), 3·5·99 → ``(3, "R-TRANSPORT")``,
    6 → ``(3, "R-NOKEY")``. 표에 없는 코드(파이썬 기동 실패 등)도 ``(3, "R-TRANSPORT")`` — 출력이 기록됐다고 믿지 않는다."""
    c = _int_or_none(code)
    if c in PIPE_OK:
        return None, None
    return 3, _PIPE.get(c, _PIPE_UNKNOWN)[0]


def pipe_hint(code) -> str:
    """파이프 실패의 한국어 한 줄(성공이면 빈 문자열)."""
    c = _int_or_none(code)
    if c in PIPE_OK:
        return ""
    return _PIPE.get(c, _PIPE_UNKNOWN)[1]


def pipe_cursor_ok(code) -> bool:
    """커서를 진전시켜도 되는가 — 출력 기록 성공(종료 0·2)일 때만(계약 §8.2·§7.3)."""
    return _int_or_none(code) in PIPE_OK


def apply_pipe(rc, reasons, code):
    """수집기 rc·사유에 파이프 결과를 합친다 → ``(rc, reasons)``. 파이프가 실패하면 rc 3 + 파이프 사유."""
    rs = norm_reasons(reasons)
    prc, why = pipe_failure(code)
    if prc is None:
        return rc, rs
    _add(rs, why)
    return prc, rs


# ── 단계 결과 번역(계약 §8.5 · X-122) ─────────────────────────────────────
def stage_outcome(rc, reasons=(), counts=None) -> dict:
    """수집기 결과 → 단계 결과 공통 필드 일부 ``{state, stop_kind, reason, resumable, caps_hit, rc, hint, reasons}``.
    ``rc`` 는 수집기 원 rc 를 그대로 둔다(X-122). 예외: 돌지 않음 → RC_NOT_RUN, 감시 종료 → RC_KILLED(3).
    셀 판정(`translate_cell`)과 같은 규칙을 써서 단계와 원장이 어긋나지 않게 한다.
      · 돌지 않음                               → skipped
      · rc 0·1·4                                → done(상한 → partial + caps_hit, 예산 → partial + stop_kind budget)
      · rc 2                                    → partial + stop_kind login(재개 가능)
      · rc 3 · 0건 + 구조·사람 사유(원장 blocked) → skipped + 그 사유(이 PC 에서 쓸 수 없는 경로 — 다른 경로가 채움)
      · rc 3 지평선 밖                          → skipped + R-HORIZON
      · rc 3 수송·일시 · 모르는 rc               → partial + stop_kind fatal(다음 실행에서 다시)
      · 감시 종료(stall·no_progress)·취소        → partial + 그 stop_kind
    수집기가 낸 사유는 바깥 입력이다(다른 판의 PS·PY 수집기). 계약 §6.1 표에 없는 코드(새 코드·폐지 코드)는 판정에서는
    '수송'으로 세지만(`reason_class`) 결과의 ``reason``·``reasons`` 에는 싣지 않는다 — 주 원인이었으면 R-TRANSPORT 로
    바꾸고, 버린 개수는 ``unknown_reasons``(정수, 있을 때만)로 남긴다. 그래서 단계 결과 검사(§6.1 코드만)를 늘 통과한다."""
    out = _stage_outcome(rc, reasons, counts)
    rs = out["reasons"]
    known = [r for r in rs if is_reason(r)]
    unknown_n = len(rs) - len(known)
    if unknown_n:
        if out["reason"] is not None and not is_reason(out["reason"]):
            out["reason"] = "R-TRANSPORT"
            _add(known, "R-TRANSPORT")
        out["reasons"] = sorted(known)
        out["unknown_reasons"] = unknown_n
    elif out["reason"] is not None and out["reason"].startswith("R-") and not is_reason(out["reason"]):
        out["reason"] = "R-TRANSPORT"
    return out


def _stage_outcome(rc, reasons=(), counts=None) -> dict:
    c = counts if isinstance(counts, dict) else {}
    rs = norm_reasons(reasons)
    stop = c.get("stop_kind")
    code = _int_or_none(rc)
    out = {"state": "done", "stop_kind": None, "reason": None, "resumable": False, "caps_hit": False,
           "rc": code if code is not None else RC_KILLED, "hint": HINTS["done"]}
    if rc is None or code == RC_NOT_RUN:
        out.update(state="skipped", rc=RC_NOT_RUN, reason=_first(rs), hint=HINTS["not_run"])
    elif stop in WATCH_STOPS:
        _add(rs, "R-TRANSPORT")
        out.update(state="partial", stop_kind=stop, resumable=True, rc=RC_KILLED, reason="R-TRANSPORT",
                   hint=HINTS[stop])
    elif stop == "cancelled":
        out.update(state="partial", stop_kind="cancelled", resumable=True, reason=_first(rs),
                   rc=code if code in COLLECTOR_RCS else RC_KILLED, hint=HINTS["cancelled"])
    else:
        cell = translate_cell(rc, rs, c)
        rs = list(cell["reasons"])
        st = cell["status"]
        if code == 2:
            out.update(state="partial", stop_kind="login", resumable=True, hint=HINTS["login"],
                       reason="R-LOGIN" if "R-LOGIN" in rs else "R-CA")
        elif st == "blocked" or (st == "out_of_horizon" and code == 3):
            main = next((r for r in rs if _structural_block(r)), "R-HORIZON")
            out.update(state="skipped", reason=main, hint=HINTS["structural"])
        elif st == "transport_fail":
            main = "R-TRANSPORT" if "R-TRANSPORT" in rs else next(
                (r for r in rs if reason_class(r) in (TRANSPORT, TRANSIENT)), "R-TRANSPORT")
            out.update(state="partial", stop_kind="fatal", resumable=True, reason=main, hint=HINTS["transport"])
        elif st == "partial" and cell["budget_hit"]:
            out.update(state="partial", stop_kind="budget", resumable=True, reason="R-BUDGET",
                       hint=HINTS["budget"], caps_hit=bool(cell["cap_hit"]))
        elif st == "partial" and cell["cap_hit"]:
            out.update(state="partial", resumable=True, reason="R-CAP", hint=HINTS["cap"], caps_hit=True)
        elif st == "partial":                    # C4 품질 부분 결과(R-RECURINC): 셀은 partial(다른 경로가 빈 회차를
            # 채우게), 단계는 done + 그 사유 — 같은 경로를 다시 돌려도 채워지지 않고 사람 조치도 아니므로 collect rc 2 로
            # 올리지 않는다(반복 회의가 있는 사람마다 매번 rc 2 가 되는 소음 방지)
            out.update(reason=next(r for r in rs if r in PARTIAL_QUALITY), hint=HINTS["recurinc"])
        else:                                    # ok · zero_ok · out_of_horizon(rc 0·1·4)
            out.update(reason="R-HORIZON" if "R-HORIZON" in rs else None)
    out["reasons"] = sorted(rs)
    return out


def _first(rs):
    return rs[0] if rs else None


# ── collect 명령 rc(계약 §8.3) ──────────────────────────────────────────────
def new_records(result) -> int:
    """단계 결과의 새 레코드 수 — 수집 단계는 ``items_ok`` 가 새로 저장한 레코드 수다."""
    v = _int_or_none(result.get("items_ok")) if isinstance(result, dict) else None
    return v if v is not None and v > 0 else 0


def collect_rc(results) -> int:
    """수집 단계 결과들 → ``lm27 collect`` rc(계약 §8.3).
    3 = 번들 쓰기 불가(R-BUNDLE-READONLY)이거나 실행 차단(R-CLM·R-APPLOCKER)으로 단계가 failed ·
    1 = failed 단계(내부 오류·치명) · 2 = partial 하나라도 · 0 = 모두 done/skipped 이고 새 레코드 ≥ 1 · 4 = 새 레코드 0.
    수집기 rc 3 의 구조적 막힘은 단계가 skipped 로 끝나 원장·todo 에 남으므로 0/4 로 흡수된다(C §8.4)."""
    rows = [r for r in (results or ()) if isinstance(r, dict)]
    for r in rows:
        rr = set(norm_reasons(r.get("reasons"))) | set(norm_reasons(r.get("reason")))
        if rr & ENV_FAIL_ALWAYS or (r.get("state") == "failed" and rr & ENV_FAIL_IF_FAILED):
            return 3
    states = [r.get("state") for r in rows]
    if "failed" in states:
        return 1
    if "partial" in states:
        return 2
    return 0 if sum(new_records(r) for r in rows) > 0 else 4
