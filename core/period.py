# -*- coding: utf-8 -*-
r"""
period.py — 분석 기간 단일원(spec §6.5 · D2). run.py · mine.py · ui(서버 쪽 + GET /api/period) · AgentFinder32.bat 이 쓴다.

규칙(D2)
  · 끝날 d1 = 어제. 오늘은 넣지 않는다(오늘 이후로 끝나는 요청은 어제로 옮긴다).
  · 기본 = 3개월 = 92일(양 끝 포함) [어제−91, 어제]. 1개월 = 30일 [어제−29, 어제]. (2개월 = 61일)
  · period.maxDays(≤ 92 — 코드 하한, core\afcfg)보다 긴 요청은 d1 을 두고 d0 을 뒤로 민다.
  · 시작이 끝보다 늦으면(예: 오늘 하루만 요청) 끝날 하루로 줄인다.

API
  default(cfg, months=3, *, today=None) -> (d0, d1)          datetime.date 두 개
  clamp(d0, d1, cfg, *, today=None) -> (d0, d1, info)       d0·d1 은 date | 'YYYY-MM-DD' | 'YYYYMMDD' | None(없으면 기본)
      info = {"clamped": bool, "requested": {"from": 'YYYY-MM-DD'|None, "to": 'YYYY-MM-DD'|None}}
      — 잘랐으면 화면·리포트가 notice_text(info, d0, d1) 로 사람에게 알린다. 형식이 틀린 날짜 글자는 ValueError(한국어 문장).
  notice_text(info, d0, d1, cfg=None) -> str                 잘리지 않았으면 ""
  max_days(cfg) -> int · yesterday(today=None) -> date · tag_of(d0, d1) -> 'YYYYMMDD-YYYYMMDD'(산출물 파일 꼬리)
CLI  python core\period.py [--months 1|3] [--from D --to D] [--json]
     --json 이 없으면 'YYYY-MM-DD YYYY-MM-DD' 한 줄(bat 의 for /f 용), 있으면 {"from","to","tag","clamped","requested","notice"}.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402

MONTH_DAYS = {1: 30, 2: 61, 3: 92}     # 개월 → 일수(양 끝 포함) — 3개월 이상은 92(상한)


def _as_date(v, what="날짜"):
    """date | datetime | 'YYYY-MM-DD' | 'YYYYMMDD' | None/'' → date | None. 형식 오류는 ValueError."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y.%m.%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{what} '{s}' 를 읽지 못했습니다 — YYYY-MM-DD 로 적으세요")


def _today(today=None):
    return _as_date(today, "오늘") or date.today()


def yesterday(today=None):
    """어제(분석 끝날의 최댓값)."""
    return _today(today) - timedelta(days=1)


def max_days(cfg=None):
    """분석 기간 상한(일) — period.maxDays(afcfg 하한 적용, 1~92)."""
    return int(afcfg.get(cfg, "period.maxDays"))


def default(cfg=None, months=3, *, today=None):
    """기본 기간 → (d0, d1). d1 = 어제, 길이 = months 개월의 일수(1→30, 2→61, 3 이상→92)와 maxDays 중 짧은 쪽."""
    try:
        m = int(months)
    except (TypeError, ValueError):
        m = 3
    days = MONTH_DAYS.get(m, MONTH_DAYS[3] if m > 3 else MONTH_DAYS[1])
    days = max(1, min(days, max_days(cfg)))
    d1 = yesterday(today)
    return d1 - timedelta(days=days - 1), d1


def clamp(d0, d1, cfg=None, *, today=None):
    """요청 기간 → 규칙에 맞춘 (d0, d1, info). 요청이 없으면 기본(92일·maxDays) — 이것은 '잘림' 이 아니다.
    잘리는 경우: 끝이 오늘 이후 → 어제 · 시작이 끝보다 늦음 → 끝날 하루 · 길이 > maxDays → 시작을 뒤로."""
    r0, r1 = _as_date(d0, "시작일"), _as_date(d1, "끝날")
    info = {"clamped": False, "requested": {"from": r0.isoformat() if r0 else None,
                                           "to": r1.isoformat() if r1 else None}}
    y = yesterday(today)
    mx = max_days(cfg)
    e = r1 or y
    if e > y:
        e = y
        info["clamped"] = True
    if r0 is None:
        s = e - timedelta(days=min(MONTH_DAYS[3], mx) - 1)
    else:
        s = r0
        if s > e:
            s = e
            info["clamped"] = True
    if (e - s).days + 1 > mx:
        s = e - timedelta(days=mx - 1)
        info["clamped"] = True
    return s, e, info


def notice_text(info, d0, d1, cfg=None):
    """잘림 알림 한 문장(한국어) — 잘리지 않았으면 ""."""
    if not isinstance(info, dict) or not info.get("clamped"):
        return ""
    rq = info.get("requested") or {}
    a, b = rq.get("from") or "처음", rq.get("to") or "어제"
    s0 = d0.isoformat() if isinstance(d0, date) else str(d0)
    s1 = d1.isoformat() if isinstance(d1, date) else str(d1)
    return (f"요청한 기간({a}~{b})을 {s0}~{s1} 로 바꿨습니다 — 오늘은 넣지 않고 어제까지, "
            f"최대 {max_days(cfg)}일만 분석합니다")


def tag_of(d0, d1):
    """산출물 파일 꼬리 'YYYYMMDD-YYYYMMDD'."""
    a, b = _as_date(d0), _as_date(d1)
    return f"{a:%Y%m%d}-{b:%Y%m%d}"


def _main(argv):
    def arg(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None
    root = arg("--root") or os.path.dirname(_HERE)
    cfg, _w = afcfg.load_effective(root)
    try:
        if arg("--from") or arg("--to"):
            d0, d1, info = clamp(arg("--from"), arg("--to"), cfg)
        else:
            d0, d1 = default(cfg, arg("--months") or 3)
            info = {"clamped": False, "requested": {"from": None, "to": None}}
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False) if "--json" in argv else str(e))
        return 1
    if "--json" in argv:
        print(json.dumps({"ok": True, "from": d0.isoformat(), "to": d1.isoformat(), "tag": tag_of(d0, d1),
                          "clamped": info["clamped"], "requested": info["requested"],
                          "notice": notice_text(info, d0, d1, cfg)}, ensure_ascii=False))
    else:
        print(f"{d0.isoformat()} {d1.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
