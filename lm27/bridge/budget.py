# -*- coding: utf-8 -*-
r"""예산 한 벌(B §7.2 · §7.12, LM24 ``core/budget.stage_budget`` 이식) — 호출·단계 마감, 패킹 예산, 실행 중 적응.

    plan = call_plan(cfg, clock, n_stages)                 # 호출 1회(여러 단계)의 전체 마감 + 마지막 단계 몫
    dl = stage_deadline(plan, idx, n_stages, cfg, clock)   # 단계 자기 예산 ∧ 전체 마감(마지막 몫 제외), 최소 몫 보장
    pin, pout = initial_pack(cfg, calib, factor)           # 보정값(없으면 bridge.inputMaxChars·answerMaxChars) × 적응값

규칙(B §7.12): 질의 시작 조건 = 단계 마감까지 ``bridge.minAskSec`` 이상. 앞 단계가 전체 예산을 다 써도 각 단계에
``bridge.stageFloorMin`` 은 준다(뒤 단계 전멸 방지). 0 = 그 예산 끔.

패킹 예산의 범위(입력 2,000~20,000 · 답 1,500~12,000 — B §7.2)는 설정 레지스트리 선언의 ``range`` 가 원천이다
(``bridge.inputMaxChars``·``bridge.answerMaxChars`` — 숫자를 이 파일에 다시 쓰지 않는다, G-B2 · B10 '한 벌').

실행 중 적응(``runtime_adjust``): 한 단계에서 ``truncated(output)`` 가 ``TRUNC_SHRINK_EVERY`` 번 나면 답 예산 ×
``OUT_SHRINK``(하한 = 답 예산 범위 하한)로 낮추고 ``bridge_profile.runtime_adjust[단계]`` 에 저장(다음 실행 시작값).
``OK_RECOVER_STREAK`` 번 연속 ok 면 1.0 쪽으로 ``RECOVER_STEP`` 씩 회복.
"""
from __future__ import annotations

from dataclasses import dataclass

from lm27.bridge.clock import INF, iso_now

SEC_PER_MIN = 60.0
OUT_SHRINK = 0.8                 # truncated(output) 반복 → 답 예산 × 0.8(B §6.7·§7.12)
TRUNC_SHRINK_EVERY = 2           # 같은 단계에서 2회째마다
OK_RECOVER_STREAK = 5            # 5회 연속 ok → 회복
RECOVER_STEP = 0.1
FACTOR_MIN = 0.1
ROOM_COMPACT_RATIO = 0.25        # 머리말을 뺀 자리가 입력 예산의 1/4 미만이면 축약 머리말(B §7.3)
ENVELOPE_OVERHEAD = 80           # 답 봉투 고정 글자(B §7.3)
EST_ALPHA = 0.3                  # 답 길이 추정 지수 이동 평균(B §7.3)
EST_MIN_SCALE = 0.7
EST_MAX_SCALE = 2.0
ASK_MARGIN_S = 60.0              # 사다리 각 단 대기 = min(…, 질의 마감 − 60초)(B §6.7)


@dataclass(frozen=True)
class Plan:
    total_dl: float              # 전체 마감(clock.mono 기준, INF = 없음)
    reserve_last: float          # 마지막 단계 몫(초)
    start: float


def call_plan(cfg, clock, n_stages: int) -> Plan:
    now = clock.mono()
    total = now + cfg.total_budget_min * SEC_PER_MIN if cfg.total_budget_min > 0 else INF
    reserve = cfg.final_reserve_min * SEC_PER_MIN if n_stages > 1 else 0.0
    return Plan(total, reserve, now)


def stage_deadline(plan: Plan, idx: int, n_stages: int, cfg, clock) -> float:
    now = clock.mono()
    own = now + cfg.stage_budget_min * SEC_PER_MIN if cfg.stage_budget_min > 0 else INF
    cap = plan.total_dl - (plan.reserve_last if idx < n_stages - 1 else 0.0)
    dl = min(own, cap)
    return max(dl, now + cfg.stage_floor_min * SEC_PER_MIN)


def left(deadline: float, clock) -> float:
    return max(0.0, deadline - clock.mono())


def can_ask(deadline: float, cfg, clock) -> bool:
    """새 질의를 시작해도 되는가(단계 마감까지 minAskSec 이상)."""
    return left(deadline, clock) >= cfg.min_ask_sec


_BOUNDS: dict = {}


def pack_bounds() -> tuple[tuple[int, int], tuple[int, int]]:
    """((입력 하한, 상한), (답 하한, 상한)) — 설정 레지스트리 선언의 range(B §7.2 범위의 원천)."""
    if not _BOUNDS:
        from lm27.config import registry_meta
        out = []
        for key in ("bridge.inputMaxChars", "bridge.answerMaxChars"):
            rg = registry_meta(key).range or {}
            out.append((int(rg["min"]), int(rg["max"])))
        _BOUNDS["v"] = (out[0], out[1])
    return _BOUNDS["v"]


def clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(v))))


def initial_pack(cfg, calib: dict | None = None, factor: float = 1.0) -> tuple[int, int]:
    """(입력 예산, 답 예산) — 보정값(유효 기간 안 최신) 또는 설정값을 범위로 자르고 답 예산에 적응값을 곱한다."""
    (ilo, ihi), (olo, ohi) = pack_bounds()
    pin = clamp(calib.get("pack_in") if calib else cfg.input_max_chars, ilo, ihi)
    pout = clamp(calib.get("pack_out") if calib else cfg.answer_max_chars, olo, ohi)
    f = max(FACTOR_MIN, min(1.0, float(factor or 1.0)))
    return pin, max(olo, int(pout * f))


def shrink_in(injected_chars: int, cfg) -> int:
    """truncated(input): 입력 예산 = 편집기 확인 글자 × calibSafety(하한 = 입력 범위 하한)(B §6.7)."""
    (ilo, _ihi), _o = pack_bounds()
    return max(ilo, int(int(injected_chars) * cfg.calib_safety))


def shrink_out(pack_out: int) -> int:
    _i, (olo, _ohi) = pack_bounds()
    return max(olo, int(pack_out * OUT_SHRINK))


class Adjust:
    r"""``bridge_profile.runtime_adjust`` — 단계별 ``{pack_out_factor, at}``(B §4.10). ``profile`` = ``BridgeProfile``."""

    def __init__(self, profile, clock):
        self.profile = profile
        self.clock = clock

    def factor(self, stage: str) -> float:
        if self.profile is None:
            return 1.0
        d = (self.profile.load().get("runtime_adjust") or {}).get(stage) or {}
        try:
            f = float(d.get("pack_out_factor", 1.0))
        except (TypeError, ValueError):
            return 1.0
        return max(FACTOR_MIN, min(1.0, f))

    def save(self, stage: str, factor: float) -> float:
        f = round(max(FACTOR_MIN, min(1.0, float(factor))), 3)
        if self.profile is None:
            return f
        at = iso_now(self.clock)

        def put(d):
            ra = d.setdefault("runtime_adjust", {})
            ra[stage] = {"pack_out_factor": f, "at": at}
        self.profile.update(put)
        return f

    def shrink(self, stage: str) -> float:
        return self.save(stage, self.factor(stage) * OUT_SHRINK)

    def recover(self, stage: str) -> float:
        cur = self.factor(stage)
        if cur >= 1.0:
            return 1.0
        return self.save(stage, min(1.0, cur + RECOVER_STEP))
