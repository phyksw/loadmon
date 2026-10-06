# -*- coding: utf-8 -*-
r"""주간·월간 리뷰 — 기간 사실 · 리드타임 초과 원인 · 초과 근무 원인 · 리뷰 사실(R §4.4 · §4.10.1 · §6.4 · 부록 A).

- 기간: 주 = ISO 주(월요일 시작, 근무 시간대 날짜), 월 = 달력 달. 분석 기간과 겹치는 것만, 경계에 걸리면 `partial`
  {from, to, workdays, of}(부분 주 n/5 · 부분월 c/W).
- 기간 사실(R §4.4.2): env·꼬리표·귀속·미귀속·관측·추정 분(정수 분 표 합) · top_projects(5) · active · started(추정 시작 표식) ·
  finished(closed·estimated, 추정 종료 표식) · continuing · unstarted · lead_table(초과 판정·원인) · ot_units(초과 근무 원인) ·
  peers_top(5) · facts(코파일럿 리뷰 입력 — 완료 → 시작 → 진행 → 보류, 같은 상태 안은 기간 분 ↓ → unit_id, 상한 maxFacts).
- `overrun_causes(unit, baseline, cfg)`(R §4.4.3): baseline = (같은 역할 완료 업무의 영업 리드 중앙 L₀, 투입 중앙 E₀) 또는 None
  (NO_BASELINE). 초과 = 영업 리드 > leadOverrunRatio × L₀. 원인(해당 모두, 이 순서): WAIT · REWORK · PARALLEL · SCOPE ·
  LATE_START · DATA, 없으면 UNEXPLAINED.
- `baseline_of(u, units, ...)`: u 를 뺀 같은 역할 완료 단위업무 중 끝이 u 의 끝 이전 baselineMonths 개월 안인 것 —
  표본이 baselineMinUnits 미만이면 같은 업무 영역·같은 기능으로 넓히고, 그래도 모자라면 None.
- 초과 근무 원인(R §4.4.4): 기준 `mm.overtimeBasis` — window = 연장·야간·휴일 꼬리표 분, daily8h = 일 std 초과분을 그날
  단위업무·미귀속 분 비율로 최대잉여(정수 분).

설정(R §10.2): `report.review.leadOverrunRatio` · `baselineMonths` · `baselineMinUnits` · `lateStartWd` · `parallelHigh` ·
`scopeRatio` · `maxFacts`(+ `mm.overtimeBasis`). 표준 라이브러리만 쓴다. 나눗셈은 `fmt` 로만. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.report.analysis.activity import EST_START, Unit, date_lmin, lmin_date, lmin_iso
from lm27.time.calendar import TAGS

__all__ = ["BAD_COV", "OT_TAGS", "Baselines", "attach_ai", "baseline_of", "overrun_causes", "overtime", "period_facts",
           "period_peers", "review_periods", "scrub_time", "unit_overrun"]

OT_TAGS = ("extended", "night", "holiday")
BAD_COV = frozenset({"blocked", "transport_fail", "out_of_horizon", "not_attempted"})
EST_FINISH = frozenset({"E3i", "NEXT_REQ"})              # '추정 종료'(R §4.4.2)
HOLD_WD = 20                                              # 보류 = OPEN · 기간 분 0 · 20근무일 넘게 열림(R §4.10.1)
WAIT_SHARE = "0.7"                                        # WAIT: (리드 − 투입)/리드 ≥ 0.7(R §4.4.3)
TOP_PROJECTS = 5
TOP_OT = 5
TOP_PEERS = 5
PEERS_Q = 8                                               # 코파일럿 리뷰 입력 동료 상한(R §4.10.1)
_TIME_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:MM|M/M|시간|h|분)", re.IGNORECASE)


def review_cfg(cfg) -> dict:
    return {"ratio": F.dec(cfg["report.review.leadOverrunRatio"]), "months": int(cfg["report.review.baselineMonths"]),
            "min_units": int(cfg["report.review.baselineMinUnits"]), "late_wd": int(cfg["report.review.lateStartWd"]),
            "par_high": F.dec(cfg["report.review.parallelHigh"]), "scope": F.dec(cfg["report.review.scopeRatio"]),
            "max_facts": int(cfg["report.review.maxFacts"])}


def scrub_time(text: str) -> str:
    """제목 안 시간·공수 숫자 표현을 지운다(코파일럿 입력 시간 미전송 — B1 · L-18 · RPT-28)."""
    return " ".join(_TIME_RE.sub(" ", str(text or "")).split())


# ───────────────────────────── 리드타임 초과(R §4.4.3) ─────────────────────────────
def overrun_causes(unit: Mapping, baseline: tuple[int, int] | None, cfg, *, wait_min: int = 480) -> dict:
    """unit = {biz_lead_min, effort_min, max_wait_biz_min, cycles, parallel, start_to_first_wd, grade, coverage_gap}.
    baseline = (L₀, E₀) 또는 None. 반환 {overrun(True|False|None), causes[], baseline_biz_min, baseline_effort_min, ratio}."""
    c = review_cfg(cfg)
    if baseline is None or baseline[0] is None:
        return {"overrun": None, "causes": ["NO_BASELINE"], "baseline_biz_min": None, "baseline_effort_min": None,
                "ratio": None}
    l0, e0 = baseline
    lead = int(unit.get("biz_lead_min") or 0)
    ratio = F.ratio(lead, l0, 2) if l0 else None
    base = {"baseline_biz_min": int(l0), "baseline_effort_min": None if e0 is None else int(e0), "ratio": ratio}
    over = F.dec(lead) > c["ratio"] * F.dec(l0)
    if not over:
        return {"overrun": False, "causes": [], **base}
    eff = int(unit.get("effort_min") or 0)
    out = []
    if lead > 0 and F.ge(lead - eff, lead, WAIT_SHARE) and int(unit.get("max_wait_biz_min") or 0) >= wait_min:
        out.append("WAIT")
    if int(unit.get("cycles") or 0) >= 2:
        out.append("REWORK")
    if F.dec(unit.get("parallel") or 0) >= c["par_high"]:
        out.append("PARALLEL")
    if e0 and F.dec(eff) >= c["scope"] * F.dec(e0):
        out.append("SCOPE")
    if int(unit.get("start_to_first_wd") or 0) >= c["late_wd"]:
        out.append("LATE_START")
    if str(unit.get("grade") or "") in ("D", "E") or bool(unit.get("coverage_gap")):
        out.append("DATA")
    return {"overrun": True, "causes": out or ["UNEXPLAINED"], **base}


def _months_back(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


class Baselines:
    """기준 표본 색인 — 완료 단위업무를 (역할) · (영역, 기능) 묶음별 끝 시각순으로 두고 창을 이분 탐색한다(큰 표본 성능)."""

    def __init__(self, units: Iterable[Unit], cfg):
        self.c = review_cfg(cfg)
        done = sorted((v for v in units if v.closed and v.end is not None and v.biz_lead_min is not None),
                      key=lambda v: (v.end, v.unit_id))
        self.groups: dict[tuple, tuple[list, list]] = {}
        for v in done:
            for key in (("r", v.role_id), ("df", v.domain, v.func)):
                g = self.groups.setdefault(key, ([], []))
                g[0].append(v.end)
                g[1].append(v)

    def of(self, u: Unit) -> tuple[int, int] | None:
        if u.end is None:
            return None
        lo = date_lmin(_months_back(u.end_date, self.c["months"]))
        for key in (("r", u.role_id), ("df", u.domain, u.func)):
            ends, items = self.groups.get(key, ([], []))
            sample = [v for v in items[bisect.bisect_left(ends, lo):bisect.bisect_right(ends, u.end)]
                      if v.unit_id != u.unit_id]
            if len(sample) >= self.c["min_units"]:
                return F.median_int(v.biz_lead_min for v in sample), F.median_int(v.effort_min for v in sample)
        return None


def baseline_of(u: Unit, units: Iterable[Unit], cfg) -> tuple[int, int] | None:
    """(영업 리드 중앙 L₀, 투입 중앙 E₀) — u 를 뺀 완료 단위업무 중 끝이 u 의 끝 이전 baselineMonths 개월 안인 것.
    같은 역할 → 같은 영역·같은 기능 순으로 넓힌다. 표본 부족이면 None(R §4.4.3)."""
    return Baselines(units, cfg).of(u)


def _coverage_gap(ctx, u: Unit) -> bool:
    if u.start is None:
        return False
    d, e = u.start_date, (u.end_date or ctx.as_of_date())
    while d <= e:
        df = ctx.days.get(d.isoformat())
        if df is not None and ctx.bc.is_workday(d):
            for ax in ("mail_out", "teams"):
                if df.coverage.get(ax) in BAD_COV:
                    return True
        d += timedelta(days=1)
    return False


def unit_overrun(ctx, u: Unit, uwf: Mapping | None, base: Baselines | None = None) -> dict:
    """단위업무 하나의 초과 판정(완료 업무만 의미 있음) + 원인 문장."""
    lw = (uwf or {}).get("longest_wait") or {}
    first = min(u.by_date) if u.by_date else None
    s2f = ctx.bc.wd_between(u.start_date, date.fromisoformat(first)) if (first and u.start_date) else 0
    fact = {"biz_lead_min": u.biz_lead_min, "effort_min": u.effort_min, "max_wait_biz_min": lw.get("biz_min", 0),
            "cycles": u.n_cycles, "parallel": u.parallel, "start_to_first_wd": s2f, "grade": u.grade,
            "coverage_gap": _coverage_gap(ctx, u)}
    bl = (base or Baselines(ctx.units.values(), ctx.cfg)).of(u)
    res = overrun_causes(fact, bl, ctx.cfg, wait_min=ctx.bc.std_day_min)
    res["texts"] = [_cause_text(code, fact, res, lw, ctx) for code in res["causes"]]
    res["max_wait"] = {"after": lw.get("after"), "before": lw.get("before"), "biz_min": lw.get("biz_min")} if lw else None
    return res


def _cause_text(code: str, fact: Mapping, res: Mapping, lw: Mapping, ctx) -> str:
    tpl = V.CAUSES.get(code, (code, ""))[1]
    if code == "WAIT":
        return tpl.format(before=V.step_name(lw.get("after", ""), ctx.registry),
                          after=V.step_name(lw.get("before", ""), ctx.registry),
                          days=F.fmt_days(int(lw.get("biz_min") or 0), ctx.bc.std_day_min))
    if code == "REWORK":
        return tpl.format(n=max(1, int(fact["cycles"]) - 1))
    if code == "PARALLEL":
        return tpl.format(x=F.fmt_x(fact["parallel"]))
    if code == "SCOPE":
        e0 = int(res.get("baseline_effort_min") or 0)
        return tpl.format(r=F.fmt_ratio(int(fact["effort_min"]), e0, 1) if e0 else F.DASH,
                          h=F.fmt_h1(int(fact["effort_min"])), h0=F.fmt_h1(e0))
    if code == "LATE_START":
        return tpl.format(d=int(fact["start_to_first_wd"]))
    return tpl


# ───────────────────────────── 기간 ─────────────────────────────
def _periods(ctx) -> list[tuple[str, str, date, date]]:
    """(kind, key, 시작, 끝) — 분석 기간과 겹치는 ISO 주 → 달."""
    out = []
    mon = ctx.d0 - timedelta(days=ctx.d0.weekday())
    while mon <= ctx.d1:
        out.append(("week", F.iso_week(mon), mon, mon + timedelta(days=6)))
        mon += timedelta(days=7)
    for m in ctx.months():
        y, mo = int(m[:4]), int(m[5:7])
        first = date(y, mo, 1)
        last = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
        out.append(("month", m, first, last))
    return out


def _wd_in(ctx, a: date, b: date) -> int:
    return ctx.bc.wd_between(a - timedelta(days=1), b) if b >= a else 0


def overtime(ctx, dates: list[str], unit_min: Mapping[str, Mapping[str, int]]) -> dict:
    """초과 근무 원인(R §4.4.4) — {basis, total_min, units[{unit_id, min}](상위 5), unattributed_min}."""
    basis = str(ctx.cfg["mm.overtimeBasis"])
    per: Counter = Counter()
    unattr = 0
    if basis == "daily8h":
        std = ctx.bc.std_day_min
        for d in dates:
            env = sum((ctx.env.get(d) or {}).values())
            dd = date.fromisoformat(d)
            over = env if not ctx.bc.is_workday(dd) else max(0, env - std)
            if over <= 0:
                continue
            w = {u: m for u, m in unit_min.get(d, {}).items() if m > 0}
            ua = env - sum(w.values())
            if ua > 0:
                w["~unattr"] = ua
            sp = F.split_largest(over, w, sorted(k for k in w if k != "~unattr") + ["~unattr"])
            for k, v in sp.items():
                if k == "~unattr":
                    unattr += v
                else:
                    per[k] += v
    else:
        for d in dates:
            env = ctx.env.get(d) or {}
            att = Counter()
            for (_dd, u, tag), m in _alloc_on(ctx, d):
                if tag in OT_TAGS:
                    per[u] += m
                    att[tag] += m
            for tag in OT_TAGS:
                unattr += max(0, int(env.get(tag, 0)) - att[tag])
    units = [{"unit_id": u, "min": int(m)} for u, m in sorted(per.items(), key=lambda kv: (-kv[1], kv[0])) if m > 0]
    return {"basis": basis, "total_min": sum(per.values()) + unattr, "units": units[:TOP_OT],
            "unattributed_min": int(unattr)}


def _alloc_on(ctx, d: str):
    return ctx.alloc_on(d)


def _proj_field(u: Unit) -> str:
    """코파일럿 입력의 과제 칸: 레지스트리 ID 그대로 · 제안·개인 과제 NEW · 미분류 NONE(R §4.10.1)."""
    if u.project_id:
        return u.project_id
    if u.project_key and u.project_key != "UNC":
        return "NEW"
    return "NONE"


def period_facts(ctx, kind: str, key: str, p0: date, p1: date, *, pidx, rels: list[dict],
                 overruns: Mapping[str, dict]) -> dict:
    """기간 하나의 사실(R §4.4.2). 시간 분은 정수 분 표의 그 기간 날짜 합."""
    c = review_cfg(ctx.cfg)
    a, b = max(p0, ctx.d0), min(p1, ctx.d1)
    dates = []
    d = a
    while d <= b:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    dset = set(dates)
    by_tag = Counter()
    for ds in dates:
        for t, m in (ctx.env.get(ds) or {}).items():
            by_tag[t] += m
    env_min = sum(by_tag.values())
    unit_min: dict[str, Counter] = defaultdict(Counter)
    umin: Counter = Counter()
    obs = est = 0
    for ds in dates:
        for (dd, u, tag), m in _alloc_on(ctx, ds):
            unit_min[ds][u] += m
            umin[u] += m
            o, e = ctx.cells.get((dd, u, tag), (0, m))
            obs += o
            est += e
    attributed = sum(umin.values())
    proj = Counter()
    for u, m in umin.items():
        if u in ctx.units:
            proj[ctx.units[u].project_key] += m
    units = ctx.units

    def in_p(m):
        return m is not None and lmin_date(m).isoformat() in dset
    started = [u for u in ctx.unit_list() if u.status != "not_started" and in_p(u.start)]
    finished = [u for u in ctx.unit_list() if u.closed and in_p(u.end)]
    active = sorted((u for u in umin if umin[u] > 0 and u in units), key=lambda u: (-umin[u], u))
    fin_ids = {u.unit_id for u in finished}
    st_ids = {u.unit_id for u in started}
    continuing = [u for u in active if u not in fin_ids and u not in st_ids
                  and (units[u].start is None or lmin_date(units[u].start) < a)
                  and (units[u].end is None or lmin_date(units[u].end) > b)]
    unstarted = [u for u in ctx.unit_list() if u.status == "not_started" and in_p(u.start)]
    lead_table = []
    for u in finished:
        o = overruns.get(u.unit_id) or {}
        lead_table.append({"unit_id": u.unit_id, "role_id": u.role_id, "lead_min": u.lead_min,
                           "biz_lead_min": u.biz_lead_min, "effort_min": u.effort_min, "parallel": u.parallel,
                           "grade": u.grade, "overrun": o.get("overrun"), "causes": list(o.get("causes", ())),
                           "cause_names": [V.cause_name(x) for x in o.get("causes", ())],
                           "cause_texts": list(o.get("texts", ())), "baseline_biz_min": o.get("baseline_biz_min"),
                           "ratio": o.get("ratio"),
                           "est_end": bool(u.cycles and (u.cycles[-1].eb or "") in EST_FINISH)})
    pq = period_peers(pidx, {u: int(umin[u]) for u in active}, PEERS_Q)
    peers_top = pq[:TOP_PEERS]
    wd_in, wd_all = _wd_in(ctx, a, b), _wd_in(ctx, p0, p1)
    partial = None if (a == p0 and b == p1) else {"from": a.isoformat(), "to": b.isoformat(), "workdays": wd_in,
                                                  "of": wd_all}
    facts, fact_units = _facts(ctx, finished, started, continuing, umin, a, b, c["max_facts"])
    out = {"key": key, "from": p0.isoformat(), "to": p1.isoformat(), "partial": partial, "env_min": env_min,
           "by_tag": {t: int(by_tag.get(t, 0)) for t in TAGS}, "attributed_min": int(attributed),
           "unattr_min": int(env_min - attributed), "obs_min": int(obs), "est_min": int(est),
           "top_projects": [{"key": k, "min": int(v)} for k, v in sorted(proj.items(), key=lambda kv: (-kv[1], kv[0]))
                            ][:TOP_PROJECTS],
           "active": [{"unit_id": u, "min": int(umin[u])} for u in active],
           "started": [{"unit_id": u.unit_id, "est_start": bool(u.cycles and u.cycles[0].sb in EST_START)}
                       for u in started],
           "finished": [{"unit_id": u.unit_id, "est_end": bool(u.cycles and (u.cycles[-1].eb or "") in EST_FINISH)}
                        for u in finished],
           "continuing": [{"unit_id": u, "min": int(umin[u])} for u in continuing],
           "unstarted": [{"unit_id": u.unit_id, "t": lmin_iso(u.start)} for u in unstarted],
           "lead_table": lead_table, "ot_units": overtime(ctx, dates, unit_min),
           "peers_top": peers_top, "facts": facts, "fact_units": fact_units, "ai": None}
    if kind == "month":
        pnum = {"c:" + p["key"]: f"동료{i + 1}" for i, p in enumerate(pq)}      # 리뷰 질의 peers 와 같은 번호표
        out["edges"], out["edge_refs"] = _month_edges(ctx, set(active), rels, pnum)
    return out


def period_peers(pidx, umin: Mapping[str, int], cap: int) -> list[dict]:
    """그 기간 active 단위업무의 동료(사내·미확인 — 외부 계급 제외) {key, units, shared_effort_min}: 그 기간 분 ↓ → 단위업무 수 ↓
    → who_key, 상위 cap."""
    pe: dict[str, dict] = {}
    for u in sorted(umin):
        if umin[u] <= 0:
            continue
        for who in pidx.by_unit.get(u, {}):
            if pidx.cls.get(who) in ("customer", "partner", "other"):
                continue
            p = pe.setdefault(who, {"key": who, "units": 0, "shared_effort_min": 0})
            p["units"] += 1
            p["shared_effort_min"] += int(umin[u])
    return sorted(pe.values(), key=lambda p: (-p["shared_effort_min"], -p["units"], p["key"]))[:cap]


def _facts(ctx, finished, started, continuing, umin, a: date, b: date, cap: int) -> tuple[list, dict]:
    """코파일럿 리뷰 사실 `[F{n}, 상태, 제목, 과제 ID, 기능 한글명]`(R §4.10.1) + F 번호 → unit_id."""
    rows = []
    seen = set()

    def add(status, us):
        for u in sorted(us, key=lambda x: (-umin.get(x.unit_id, 0), x.unit_id)):
            if u.unit_id in seen:
                continue
            seen.add(u.unit_id)
            rows.append((status, u))
    add("완료", finished)
    add("시작", [u for u in started if u.unit_id not in {x.unit_id for x in finished}])
    add("진행", [ctx.units[x] for x in continuing])
    hold = []
    as_of_d = ctx.as_of_date()
    for u in ctx.unit_list():
        if u.status != "open" or umin.get(u.unit_id, 0) > 0 or u.start is None:
            continue
        end = min(b, as_of_d)
        if ctx.bc.wd_between(u.start_date, end) > HOLD_WD:
            hold.append(u)
    add("보류", hold)
    facts, refs = [], {}
    for i, (status, u) in enumerate(rows[:cap]):
        f = f"F{i + 1}"
        facts.append([f, status, scrub_time(u.title)[:40], _proj_field(u), V.func_name(u.func, ctx.registry)])
        refs[f] = u.unit_id
    return facts, refs


def _month_edges(ctx, active: set[str], rels: list[dict], pnum: Mapping[str, str]) -> tuple[list, dict]:
    """월간 리뷰 관계 `[E{n}, 출발, 관계, 도착]` ≤ 12(R §4.10.1) — 끝점이 그 달 활동 단위업무인 관계의 가중치 상위.
    라벨: 과제 ID · 역할 '분야·기능' · 단위업무 제목 · 문서 = 확장자군 이름 · 앱 = 범주 · 사람 = 동료k(그 질의의 peers 번호표,
    밖이면 '동료') · 외부 = 계급. 문서 이름·사람 이름은 싣지 않는다."""
    cand = [e for e in rels if (e["from"] in active or e["to"] in active)]
    cand.sort(key=lambda e: (-int(e.get("h", 0)), -int(e.get("w", 0)), V.ONTO_RELS.index(e["rel"]), e["from"], e["to"]))
    out, refs = [], {}
    for e in cand[:12]:
        n = f"E{len(out) + 1}"
        out.append([n, _node_label(ctx, e["from"], pnum), e["rel"], _node_label(ctx, e["to"], pnum)])
        refs[n] = {"from": e["from"], "to": e["to"], "rel": e["rel"]}
    return out, refs


def _node_label(ctx, nid: str, pnum: Mapping[str, str]) -> str:
    if nid.startswith("c:ext:"):
        return {"customer": "고객사", "partner": "협력사"}.get(nid[6:], "외부")
    if nid.startswith("c:"):
        return pnum.get(nid, "동료")
    if nid.startswith("d:"):
        return V.EXT_CLASS_NAMES.get(ctx.doc_class(nid[2:]), "문서")
    if nid.startswith("a:"):
        return _app_cat(nid[2:]) or "프로그램"
    u = ctx.units.get(nid)
    if u is not None:
        return scrub_time(u.title)[:40]
    return nid


def _app_cat(app: str) -> str:
    from lm27.catalog import cat_of           # 카탈로그 범주 단일원(계약 §2.8)
    return cat_of(app) or ""


def review_periods(ctx, *, wf: Mapping, pidx, rels: list[dict]) -> dict:
    """모델 `reviews{weeks, months}`(R §4.4.2) — 코파일럿 답(ai)은 `attach_ai` 가 붙인다."""
    overruns = {}
    base = Baselines(ctx.units.values(), ctx.cfg)
    for u in ctx.unit_list():
        if u.closed:
            overruns[u.unit_id] = unit_overrun(ctx, u, wf.get("units", {}).get(u.unit_id), base)
    out = {"weeks": [], "months": []}
    for kind, key, p0, p1 in _periods(ctx):
        f = period_facts(ctx, kind, key, p0, p1, pidx=pidx, rels=rels, overruns=overruns)
        out["weeks" if kind == "week" else "months"].append(f)
    out["weeks"].sort(key=lambda r: r["key"])
    out["months"].sort(key=lambda r: r["key"])
    return out


def attach_ai(reviews: Mapping, answers: Mapping[str, tuple]) -> dict[str, int]:
    """review_text 답 → 기간 `ai`{summary, highlights[{text, refs, units, effort_min}], relations, next, by, peers_map}.
    refs 의 F·E 번호를 사실 행으로 풀고, 하이라이트 옆 숫자(그 사실의 기간 투입 분)를 프로그램이 붙인다(R §4.10.2)."""
    cnt: Counter = Counter()
    for kind, rows in (("week", reviews.get("weeks", ())), ("month", reviews.get("months", ()))):
        for r in rows:
            got = answers.get(f"review:{kind}:{r['key']}")
            if not got or not isinstance(got[0], Mapping):
                r["ai"] = None
                continue
            ans, by = got
            umin = {a["unit_id"]: a["min"] for a in r.get("active", ())}
            hl = []
            for h in ans.get("highlights") or ():
                if not isinstance(h, Mapping):
                    continue
                refs = [str(x) for x in (h.get("refs") or ()) if str(x) in r.get("fact_units", {})]
                us = [r["fact_units"][x] for x in refs]
                leads = {x["unit_id"]: x["biz_lead_min"] for x in r.get("lead_table", ())}
                hl.append({"text": str(h.get("text") or ""), "refs": refs, "units": us,
                           "effort_min": sum(int(umin.get(u, 0)) for u in us),
                           "biz_lead_min": leads.get(us[0]) if len(us) == 1 else None})
            rel = []
            for h in ans.get("relations") or ():
                if isinstance(h, Mapping):
                    refs = [str(x) for x in (h.get("refs") or ()) if str(x) in (r.get("edge_refs") or {})]
                    rel.append({"text": str(h.get("text") or ""), "refs": refs})
            r["ai"] = {"summary": str(ans.get("summary") or ""), "highlights": hl, "relations": rel,
                       "next": [str(x) for x in (ans.get("next") or ()) if isinstance(x, str)], "by": str(by or "rule"),
                       "peers_map": dict(ans.get("peers_map") or {})}
            cnt[str(by or "rule")] += 1
    return dict(sorted(cnt.items()))
