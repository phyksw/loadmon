"""Read-only projections of one saved measurement ledger into review periods.

Signal weights describe evidence distribution, not hours. This module never runs
collectors or estimates new time and never converts a project's weight to MM.
"""
from copy import deepcopy
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re


def tag_period(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"\d{8}-\d{8}", tag):
        return None
    try:
        lo, hi = (date.fromisoformat(s) for s in tag.split("-"))
        return (lo, hi) if lo <= hi else None
    except ValueError:
        return None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def periods(tag, gran):
    bounds = tag_period(tag)
    if not bounds:
        return []
    lo, hi = bounds
    cursor = lo.replace(day=1) if gran == "month" else lo - timedelta(days=lo.weekday()) if gran == "week" else lo
    result = []
    while cursor <= hi:
        if gran == "month":
            following = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
            key, label = f"{cursor:%Y-%m}", f"{cursor:%Y년 %m월}"
        elif gran == "week":
            following, key, label = cursor + timedelta(days=7), cursor.isoformat(), f"{cursor:%m/%d} 주"
        else:
            following, key, label = hi + timedelta(days=1), "all", "전체 기간"
        result.append((key, label, max(lo, cursor), min(hi, following - timedelta(days=1))))
        cursor = following
    return result


def daily_ledger(meta, tag):
    """Validate saved monthly totals and distribute their rounding over saved days.

    Each month's projected sums equal the saved totals, including a partial month.
    Unknown/corrupt/inconsistent ledgers stay unknown, never calendar-derived 1 MM.
    """
    bounds = tag_period(tag)
    if not bounds or not isinstance(meta, dict) or meta.get("period") != [d.isoformat() for d in bounds]:
        return None, "같은 분석 기간의 시간 산정 자료가 없습니다"
    days, months = meta.get("day_hours"), meta.get("mm_months")
    if not isinstance(days, dict) or not isinstance(months, dict) or not months:
        return None, "일별 시간 또는 월별 MM 산정 자료가 없습니다"
    lo, hi = bounds
    parsed = {}
    for key, value in days.items():
        try:
            dt = date.fromisoformat(key)
        except (TypeError, ValueError):
            return None, "일별 시간의 날짜 형식을 확인할 수 없습니다"
        if not lo <= dt <= hi:
            return None, "일별 시간에 분석 기간 밖 날짜가 있습니다"
        hours = number(value)
        if hours is None or hours > 24:
            return None, "일별 시간에 유효하지 않은 값이 있습니다"
        parsed[dt] = hours
    ledger, monthly_mm = {}, 0.0
    for key, _label, a, b in periods(tag, "month"):
        month = months.get(key)
        if not isinstance(month, dict):
            return None, f"{key}의 월별 산정 자료가 없습니다"
        mm, worked, capacity = (number(month.get(k)) for k in ("mm", "worked", "capacity_h"))
        if mm is None or worked is None or capacity is None or capacity <= 0:
            return None, f"{key}의 시간·MM·분모를 확인할 수 없습니다"
        if abs(mm * capacity - worked) > 0.101 + capacity * 0.00051:
            return None, f"{key}의 시간과 MM 산정값이 일치하지 않습니다"
        items = {dt: h for dt, h in parsed.items() if a <= dt <= b}
        total = sum(items.values())
        if abs(total - worked) > 0.101 + len(items) * 0.0051 or (total == 0 and (worked > 0 or mm > 0)):
            return None, f"{key}의 일별 시간 합계가 월별 산정값과 다릅니다"
        for dt, hours in items.items():
            share = hours / total if total else 0.0
            ledger[dt] = {"hours": worked * share, "mm": mm * share}
        monthly_mm += mm
    total_mm = number(meta.get("total_mm"))
    if "total_mm" in meta and total_mm is None:
        return None, "분석 전체 MM 산정값이 유효하지 않습니다"
    if total_mm is not None and abs(total_mm - monthly_mm) > 0.005:
        return None, "월별 MM 합계가 분석 전체 산정값과 다릅니다"
    return ledger, ""


def project(groups, meta, tag, gran):
    """Attach measurements without mutating source groups or inventing project MM."""
    ledger, reason = daily_ledger(meta, tag)
    windows = periods(tag, gran)
    by_key = {g["key"]: deepcopy(g) for g in groups}
    result = []
    for key, label, lo, hi in windows:
        group = by_key.get(key)
        if group is None and ledger is None:
            continue
        if group is None:
            group = {"key": key, "label": label, "signals": 0, "days": 0, "months": 0,
                     "projects": [], "wt": [], "timeline": [], "p_edges": [], "a_edges": []}
        for item in group.get("projects", []):
            item["mm"] = None
            item["share_basis"] = "signal_weight"
        group.update(period=[lo.isoformat(), hi.isoformat()])
        values = [v for d, v in (ledger or {}).items() if lo <= d <= hi]
        group["measurement"] = {"available": ledger is not None, "basis": "saved_daily_hours",
                                "worked_h": round(sum(v["hours"] for v in values), 3) if ledger is not None else None,
                                "mm": round(sum(v["mm"] for v in values), 6) if ledger is not None else None,
                                "reason": reason}
        result.append(group)
    if not windows:
        result = list(by_key.values())
        for group in result:
            for item in group.get("projects", []):
                item["mm"] = None
            group["measurement"] = {"available": False, "reason": reason, "worked_h": None, "mm": None}
    return sorted(result, key=lambda g: g["key"], reverse=True)


def load_projection(report_dir, groups, tag, gran):
    meta = None
    if tag_period(tag):
        try:
            meta = json.loads((Path(report_dir) / f"mm_meta_{tag}.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
    return project(groups, meta, tag, gran)
