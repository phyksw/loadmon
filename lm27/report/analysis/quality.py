# -*- coding: utf-8 -*-
r"""측정 품질 등급(R §4.9 · 부록 A `quality_month`, 계약 §3.16 측정 품질 절 · §3.18 quality · T-9).

개인 보고서의 '신뢰도' 카드와 팀 묶음 `quality.grade`·`reasons` 는 **이 함수 하나**(`quality_month`)로 계산한다
(팀 서버는 값을 바꾸지 않고 사람의 선택된 달 중 가장 나쁜 등급을 쓴다 — TAB §4.5).

    quality_month(m) — m 안의 분석 기간 근무일 W(분석 시각 이전), 0 이면 grade = ""(판단 안 함)
      cov(axis) = (ok·zero_ok 근무일 + 0.5 × partial 근무일) / W   axis ∈ mail_out·mail_in·cal·teams·pc
      sampler_ratio = 샘플러(C1) 근거 슬롯이 있는 근무일 / W
      est_ratio = 신뢰 low 슬롯 분 / 봉투 분(봉투 0 이면 1.0) · unattr_ratio = 미귀속 분 / 봉투 분
      no_ev = 봉투 0 이고 연차·확인된 부재가 아닌 근무일 수
      unreliable: pc_cov_bad · comms_cov_bad · estimated_bad · no_envelope
      caution:    pc_cov_low · mail_cov_low · teams_cov_low · cal_cov_low · estimated_high · unattributed_high ·
                  no_evidence_days · sampler_absent

같은 측정의 '낮음' 사유는 '나쁨' 사유가 서면 싣지 않는다(pc_cov_low ⊂ pc_cov_bad, mail·teams_cov_low ⊂ comms_cov_bad,
estimated_high ⊂ estimated_bad). 봉투가 0 인 달은 no_envelope 하나가 결과(추정·미귀속·근거 없는 날·샘플러 사유는 그
결과일 뿐이라 싣지 않는다). 커버리지 정보가 그 달에 한 번도 없는 축은 '모름'(None)으로 두고 판정하지 않는다
(원장이 없다고 '측정 불충분'으로 몰지 않는다). `mining_coarse`(R §4.1.4)는 표시만 하고 등급에 영향이 없다.
기간 등급 = 달 등급 중 가장 나쁜 것, reasons = 그 달들의 reasons 합집합(코드 순).

설정(R §10.2): `report.quality.covLow` · `covBad` · `estLow` · `estBad` · `unattrHigh` · `noEvidenceDays` · `samplerLow`.
표준 라이브러리만 쓴다. 나눗셈은 `fmt` 로만. 파일을 쓰지 않는다.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from lm27.report import fmt as F
from lm27.report import vocab as V

__all__ = ["AXES", "REASONS", "month_ctx", "period_quality", "quality_layer", "quality_month", "quality_texts"]

AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
OK_STATES = frozenset({"ok", "zero_ok"})
REASONS = ("pc_cov_bad", "comms_cov_bad", "estimated_bad", "no_envelope", "pc_cov_low", "mail_cov_low",
           "teams_cov_low", "cal_cov_low", "estimated_high", "unattributed_high", "no_evidence_days", "sampler_absent",
           "mining_coarse")
RANK = {"": -1, "reliable": 0, "caution": 1, "unreliable": 2}
_BAD = frozenset({"pc_cov_bad", "comms_cov_bad", "estimated_bad", "no_envelope"})


def quality_cfg(cfg) -> dict:
    return {"covLow": F.dec(cfg["report.quality.covLow"]), "covBad": F.dec(cfg["report.quality.covBad"]),
            "estLow": F.dec(cfg["report.quality.estLow"]), "estBad": F.dec(cfg["report.quality.estBad"]),
            "unattrHigh": F.dec(cfg["report.quality.unattrHigh"]),
            "samplerLow": F.dec(cfg["report.quality.samplerLow"]),
            "noEvidenceDays": int(cfg["report.quality.noEvidenceDays"])}


def quality_month(month_ctx: Mapping, cfg) -> dict:
    """한 달의 측정 품질. month_ctx = {W, cov{축: (온전한 근무일, partial 근무일) | None}, sampler_days, env_min,
    low_min, unattr_min, no_ev, coarse}. 반환 {grade, reasons, cov{축: 비율|None}, est_ratio, unattr_ratio, no_ev,
    sampler_ratio, W}."""
    c = quality_cfg(cfg)
    W = int(month_ctx.get("W") or 0)
    coarse = bool(month_ctx.get("coarse"))
    if W <= 0:
        return {"grade": "", "reasons": ["mining_coarse"] if coarse else [], "cov": dict.fromkeys(AXES),
                "est_ratio": None, "unattr_ratio": None, "no_ev": 0, "sampler_ratio": None, "W": 0}
    cov: dict[str, object] = {}
    for ax in AXES:
        v = (month_ctx.get("cov") or {}).get(ax)
        cov[ax] = None if v is None else (F.dec(int(v[0])) + F.dec(int(v[1])) * F.dec("0.5")) * F.per(1, W)
    env = int(month_ctx.get("env_min") or 0)
    est = F.per(int(month_ctx.get("low_min") or 0), env) if env > 0 else F.dec(1)
    unattr = F.per(int(month_ctx.get("unattr_min") or 0), env) if env > 0 else F.dec(0)
    sampler = F.per(int(month_ctx.get("sampler_days") or 0), W)
    no_ev = int(month_ctx.get("no_ev") or 0)
    r: list[str] = []

    def lt(ax, thr):
        return cov[ax] is not None and cov[ax] < thr
    if lt("pc", c["covBad"]):
        r.append("pc_cov_bad")
    if lt("mail_out", c["covBad"]) and lt("teams", c["covBad"]):
        r.append("comms_cov_bad")
    if env == 0:
        r.append("no_envelope")
    elif est > c["estBad"]:
        r.append("estimated_bad")
    if lt("pc", c["covLow"]) and "pc_cov_bad" not in r:
        r.append("pc_cov_low")
    if "comms_cov_bad" not in r:
        if lt("mail_out", c["covLow"]):
            r.append("mail_cov_low")
        if lt("teams", c["covLow"]):
            r.append("teams_cov_low")
    if lt("cal", c["covLow"]):
        r.append("cal_cov_low")
    if env > 0:
        if est > c["estLow"] and "estimated_bad" not in r:
            r.append("estimated_high")
        if unattr > c["unattrHigh"]:
            r.append("unattributed_high")
        if no_ev > c["noEvidenceDays"]:
            r.append("no_evidence_days")
        if sampler < c["samplerLow"]:
            r.append("sampler_absent")
    if coarse:
        r.append("mining_coarse")
    grade = "unreliable" if any(x in _BAD for x in r) else ("caution" if any(x != "mining_coarse" for x in r)
                                                             else "reliable")
    return {"grade": grade, "reasons": sorted(r, key=REASONS.index),
            "cov": {ax: (None if cov[ax] is None else F.half_up(cov[ax], 3)) for ax in AXES},
            "est_ratio": F.half_up(est, 3), "unattr_ratio": F.half_up(unattr, 3), "no_ev": no_ev,
            "sampler_ratio": F.half_up(sampler, 3), "W": W}


def _covered(ctx, d: date, std_end: int) -> bool:
    """분석 시각 이전 근무일: 지난 날은 모두, 오늘은 기준 시각이 그날 표준창 끝을 지났을 때만(X-210 과 같은 규칙)."""
    a = ctx.as_of_date()
    if d < a:
        return True
    if d > a:
        return False
    return (ctx.as_of_min % F.DAY_MIN) >= std_end


def month_ctx(ctx, m: str) -> dict:
    """분석 문맥의 날짜 사실 → quality_month 입력(달 'YYYY-MM')."""
    win = F.window_from_cfg(ctx.cfg)
    std_end = max(b for _a, b in win.zones) if win.zones else F.DAY_MIN
    y, mo = int(m[:4]), int(m[5:7])
    d = max(date(y, mo, 1), ctx.d0)
    last = min(date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1), ctx.d1)
    W = sampler = no_ev = 0
    full = dict.fromkeys(AXES, 0)
    part = dict.fromkeys(AXES, 0)
    seen = dict.fromkeys(AXES, False)
    env = low = att = 0
    while d <= last:
        ds = d.isoformat()
        df = ctx.days.get(ds)
        e = sum((ctx.env.get(ds) or {}).values())
        env += e
        att += sum(v for _k, v in ctx.alloc_on(ds))
        if df is not None:
            low += int(df.conf_min.get("low", 0) or 0)
        if ctx.bc.is_workday(d) and _covered(ctx, d, std_end):
            W += 1
            cov = df.coverage if df is not None else {}
            for ax in AXES:
                st = cov.get(ax)
                if ax == "pc" and st is None and df is not None and df.pc_basis:
                    st = "ok"
                if st is not None:
                    seen[ax] = True
                if st in OK_STATES:
                    full[ax] += 1
                elif st == "partial":
                    part[ax] += 1
            if df is not None and df.sampler:
                sampler += 1
            leave = df.leave if df is not None else 0.0
            absent = df.absence if df is not None else False
            if e == 0 and leave < 1.0 and not absent:
                no_ev += 1
        d += timedelta(days=1)
    any_pc = any(df.pc_basis for df in ctx.days.values())
    if any_pc:
        seen["pc"] = True
    return {"W": W, "cov": {ax: ((full[ax], part[ax]) if seen[ax] else None) for ax in AXES}, "sampler_days": sampler,
            "env_min": env, "low_min": low, "unattr_min": max(0, env - att), "no_ev": no_ev, "coarse": ctx.log.coarse}


def period_quality(months: Mapping[str, Mapping]) -> dict:
    """기간 등급 = 달 등급 중 가장 나쁜 것(판단 안 함 '' 은 빼고), reasons = 합집합(코드 순)."""
    grades = [q["grade"] for q in months.values() if q.get("grade")]
    grade = max(grades, key=lambda g: RANK[g]) if grades else ""
    rs = sorted({r for q in months.values() for r in q.get("reasons", ())}, key=REASONS.index)
    return {"grade": grade, "reasons": rs, "by_month": {m: q.get("grade", "") for m, q in sorted(months.items())}}


def quality_texts(q: Mapping) -> list[dict]:
    """사유 코드 → 화면 문구(R §4.9 표 — 숫자 채움). [{code, text}]."""
    out = []
    cov = q.get("cov") or {}
    for code in q.get("reasons", ()):
        tpl = V.QUALITY_TEXT.get(code, code)
        ax = {"pc_cov_bad": "pc", "pc_cov_low": "pc", "mail_cov_low": "mail_out", "teams_cov_low": "teams",
              "cal_cov_low": "cal"}.get(code)
        if ax:
            p = F.half_up(F.dec(cov.get(ax) or 0) * 100)
            text = tpl.format(p=p, axis=V.AXIS_NAMES[ax])
        elif code in ("estimated_bad", "estimated_high"):
            text = tpl.format(p=F.half_up(F.dec(q.get("est_ratio") or 0) * 100))
        elif code == "unattributed_high":
            text = tpl.format(p=F.half_up(F.dec(q.get("unattr_ratio") or 0) * 100))
        elif code == "no_evidence_days":
            text = tpl.format(n=int(q.get("no_ev") or 0))
        else:
            text = tpl
        out.append({"code": code, "text": text})
    return out


def quality_layer(ctx) -> dict:
    """모델 `quality{grade, reasons, by_month}` + 달별 상세(months[].quality 재료)."""
    months = {m: quality_month(month_ctx(ctx, m), ctx.cfg) for m in ctx.months()}
    for q in months.values():
        q["texts"] = quality_texts(q)
    out = period_quality(months)
    out["months"] = months
    out["texts"] = quality_texts({"reasons": out["reasons"], **_worst(months)})
    return out


def _worst(months: Mapping[str, Mapping]) -> dict:
    """기간 문구의 숫자 = 가장 나쁜 달의 값."""
    best = None
    for _m, q in sorted(months.items()):
        if best is None or RANK.get(q.get("grade", ""), -1) > RANK.get(best.get("grade", ""), -1):
            best = q
    return dict(best or {})
