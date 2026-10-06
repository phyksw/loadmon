# -*- coding: utf-8 -*-
r"""보고서 모델 `report_model.json`(스키마 `lm27.report` 1.0 — R §9.2 · 부록 A, 계약 §3.16 · §3.23 · X-281 · G-R1 · G-R2 · G-R8).

    model = build_model(inp, cfg)          # inp = lm27.report.inputs.load_inputs(run_id)
    problems = check_model(model)          # 모델 등식(G-R2) 위반 목록 — 빈 목록 = 통과(build_model 은 위반이면 ModelCheckError)
    red = redact_model(model, person_dir=…)  # 가림판 — 허용 목록으로 **새로 만든다**(R §9.2.4)
    bad = redaction_violations(red, person_dir)   # G-R8: 이름·로컬 키·(시험) 카나리아 0 — 있으면 필드 경로 목록

만드는 순서(R §9.2.3): 입력 → 분석 문맥(`lm27.report.analysis.make_context` — `ai_items.context_from_inputs`) → 분석층
`analyze(ctx)`(워크플로우·리뷰·동료·온톨로지·agentic·서브에이전트·측정 품질 — WP-30) → 달·날짜 행(정수 분 표 + 월 결과) →
과제·역할·단위업무·트리 → 키를 정수 참조(`refs`)로 바꿔 싣기 → 크기 상한(X-281) → 등식 검사.

- **숫자의 출처는 하나**(RP1): 분 = 시간 코어 정수 분 표(`team_tables.json`)·월 결과(`mm_month.json`). 이 모듈은 분을 더하기만
  하고 나눗셈·반올림은 `lm27.report.fmt` 로만 한다(G-R11 · L-19).
- **키는 정수 참조로**(R §9.2.2): who_key → `refs.people[k]`, 문서군 키 → `refs.docs[k]`(번호표 k = 공유 투입 ↓ → 공동 단위업무
  수 ↓ → 키 사전순). 가림판은 `refs` 만 바꾸면 이름이 사라진다(키 없음).
- **결정성**(G-R1): 같은 입력이면 같은 바이트 — 모든 목록은 명시 정렬, 시각은 근무 시간대 로컬 `YYYY-MM-DDTHH:MM`,
  `built_at` 은 모델 안에 넣지 않는다(meta 에만).
- 팀 묶음 빌더(WP-34)가 허용 목록으로 고를 재료도 싣는다(RP15): `tables`(envelope_daily·alloc_daily 정수 분) · `team`
  (agentic_matches·subagents) · `units[].start/end`(W §4.11 코드 대응) · `units[].spans` · `proposals`.

표준 라이브러리만 쓴다. 이 모듈은 파일을 쓰지 않는다(쓰기는 `lm27.report.build_report` · `lm27.report.export`).
"""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import date, timedelta

from lm27.report import fmt as F
from lm27.report import vocab as V
from lm27.report.resolve import KEY_RX, Resolver, person_names
from lm27.util.fsx import canon_bytes

__all__ = [
    "BUCKETS",
    "REPORT_VERSION",
    "SCHEMA",
    "SCHEMA_VERSION",
    "ModelCheckError",
    "Refs",
    "build_model",
    "bucket_daily",
    "check_model",
    "fit_size",
    "model_bytes",
    "redact_model",
    "redaction_violations",
]

SCHEMA = "lm27.report"
SCHEMA_VERSION = "1.0"
REPORT_VERSION = "report/1"
TAGS = ("regular", "extended", "night", "holiday")
BUCKETS = ("B_GENERIC", "B_COMM", "B_MEET", "B_OFFPC", "B_UNKNOWN")
EXTERNAL = frozenset({"customer", "partner", "other"})
UNKNOWN_PREFIX = "unknown:"
MB = 1048576
# W §4.11 — 시간 코어 경계 코드 → 팀 묶음 근거 종류·정밀도
START_KIND = {"S1": ("S1i", "minute"), "S1d": ("S1i", "date"), "S1o": ("S1o", "minute"), "S2a": ("S2", "exact"),
              "S2m": ("S2", "exact"), "S2p": ("S2", "none"), "S2M": ("M", "exact")}
END_KIND = {"E1": ("E1o", "minute"), "E1d": ("E1o", "date"), "E1i": ("E1i", "minute"), "E2h": ("E2", "exact"),
            "E2l": ("E2", "exact"), "E3c": ("E3c", "exact"), "E3M": ("M", "exact"), "E3i": ("E3i", "none"),
            "NEXT_REQ": ("E3i", "none")}
DENOM_TEXT = {"workdays": "1MM = {h}시간 × 그 달 근무일(주말·공휴일·회사 휴무 제외)",
              "weekdays": "1MM = {h}시간 × 그 달 평일(공휴일 포함 — 개인 표시 전용)"}
_PEER_TOKEN = re.compile(r"동료(\d+)(?![\d#])")
_QUEUE_PROP = ("title", "ask", "options", "answer", "answer_kinds", "area", "date", "cands", "note")


class ModelCheckError(ValueError):
    """모델 등식(G-R2) 위반 — 보고서를 만들지 않고 이전 보고서를 유지한다(R §11). `.problems` = 위반 목록."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("보고서 검사 실패: " + "; ".join(self.problems[:5]))


def _g(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def model_bytes(model: Mapping) -> bytes:
    """모델 정규 바이트(`canon_bytes` — 같은 값이면 같은 바이트, NaN 금지)."""
    return canon_bytes(model)


# ───────────────────────────── 정수 참조(R §9.2.2) ─────────────────────────────
class Refs:
    """who_key·문서군 키 → 정수 번호표. people = 사내·미확인 동료(외부 계급은 사람 수로만), docs = 다룬 문서군."""

    def __init__(self, people: dict[str, int], docs: dict[str, int], doc_min: dict[str, int], apps: list[str]):
        self.people = people
        self.docs = docs
        self.doc_min = doc_min
        self.apps = apps
        unknown = sorted(a for a in apps if a.startswith(UNKNOWN_PREFIX))
        self.unknown_n = {a: i + 1 for i, a in enumerate(unknown)}

    @classmethod
    def build(cls, ctx, pidx, docsets: Mapping[str, set]) -> Refs:
        agg: dict[str, list[int]] = {}
        for uid, whos in pidx.by_unit.items():
            u = ctx.units.get(uid)
            if u is None:
                continue
            for who in whos:
                if pidx.cls.get(who) in EXTERNAL:
                    continue
                a = agg.setdefault(who, [0, 0])
                a[0] += u.effort_min
                a[1] += 1
        ranked = sorted(agg, key=lambda w: (-agg[w][0], -agg[w][1], w))
        people = {w: i + 1 for i, w in enumerate(ranked)}
        dsec: Counter = Counter()
        dn: Counter = Counter()
        apps: set[str] = set()
        for items in ctx.log.values():
            for x in items:
                if x.kind != "A":
                    continue
                for f, s in x.fams:
                    dsec[f] += s
                for a, _s in x.apps:
                    apps.add(a)
        for fs in docsets.values():
            for f in fs:
                dn[f] += 1
        fams = set(dn) | set(dsec)
        dmin = {f: F.sec_min(dsec.get(f, 0)) for f in fams}
        rd = sorted(fams, key=lambda f: (-dmin[f], -dn.get(f, 0), f))
        return cls(people, {f: i + 1 for i, f in enumerate(rd)}, dmin, sorted(apps))

    def node(self, nid: str, *, redacted: bool = False) -> str:
        """온톨로지 노드 id: 'c:<who>' → 'c:<k>', 'd:<fam>' → 'd:<k>', 가림판의 미상 앱 → 'a:unknown-<n>'."""
        if nid.startswith("c:ext:") or nid.startswith("etc:"):
            return nid
        if nid.startswith("c:"):
            r = self.people.get(nid[2:])
            return f"c:{r}" if r is not None else "c:?"
        if nid.startswith("d:"):
            r = self.docs.get(nid[2:])
            return f"d:{r}" if r is not None else "d:?"
        if nid.startswith("a:") and redacted:
            return "a:" + self.app_id(nid[2:], redacted=True)
        return nid

    def app_id(self, app: str, *, redacted: bool = False) -> str:
        if redacted and app.startswith(UNKNOWN_PREFIX):
            return f"unknown-{self.unknown_n.get(app, 0)}"
        return app


# ───────────────────────────── 정수 분 표 · 미귀속 버킷(R §3.4 · §9.3.2 buckets_daily) ─────────────────────────────
def bucket_daily(ctx, attrib, env_slots) -> tuple[dict[tuple[str, str, str], int], bool]:
    """(날짜, 버킷, 꼬리표) → 미귀속 분. 칸마다 귀속 초를 시간 코어와 같은 최대잉여 함수(`lm27.time.intervals.lr_minutes`)로
    나눠 단위업무 몫이 정수 분 표와 같으면 그 버킷 몫을, 아니면 남는 분(봉투 − Σalloc)을 버킷 초 비례로 나눈다. Σ = 미귀속 분이
    칸마다 정확하다. 반환 (표, 모든 칸이 시간 코어와 같은가)."""
    from lm27.time.calendar import SLOT, d_of
    from lm27.time.intervals import lr_minutes
    tag_of = {}
    for r in env_slots or ():
        try:
            tag_of[int(_g(r, "slot"))] = str(_g(r, "tag", "") or "")
        except (TypeError, ValueError):
            continue
    secs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for r in attrib or ():
        try:
            slot = int(_g(r, "slot"))
        except (TypeError, ValueError):
            continue
        tag = tag_of.get(slot)
        if not tag:
            continue
        secs[(d_of(slot * SLOT).isoformat(), tag)][str(_g(r, "target", ""))] += int(_g(r, "sec", 0) or 0)
    cell_alloc: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for (d, u, tag), m in ctx.alloc.items():
        cell_alloc[(d, tag)][u] = cell_alloc[(d, tag)].get(u, 0) + m
    out: dict[tuple[str, str, str], int] = {}
    exact = True
    for d in sorted(ctx.env):
        for tag, em in sorted((ctx.env.get(d) or {}).items()):
            al = cell_alloc.get((d, tag), {})
            rem = int(em) - sum(al.values())
            if rem <= 0:
                continue
            sc = secs.get((d, tag), Counter())
            mins = lr_minutes(dict(sc), int(em)) if sc else {}
            units = {k: v for k, v in mins.items() if not k.startswith("B_")}
            bk = {k: v for k, v in mins.items() if k.startswith("B_")}
            if units != {u: m for u, m in al.items() if m > 0} or sum(bk.values()) != rem:
                exact = False
                w = {k: v for k, v in sc.items() if k.startswith("B_") and v > 0}
                bk = F.split_largest(rem, w, BUCKETS) if w else {"B_UNKNOWN": rem}
            for b, v in bk.items():
                if v > 0:
                    key = (d, b if b in BUCKETS else "B_UNKNOWN", tag)
                    out[key] = out.get(key, 0) + int(v)
    return out, exact


# ───────────────────────────── 달·날짜(R §9.2.1 months · days) ─────────────────────────────
def _iso_month_end(m: str) -> date:
    y, mo = int(m[:4]), int(m[5:7])
    return date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)


def _leave_val(v) -> float:
    if isinstance(v, str):
        return {"full": 1.0, "am": 0.5, "pm": 0.5}.get(v, 0.0)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return 0.0


def _days(ctx, inp) -> list[dict]:
    flags = {str(r.get("date")): [str(x) for x in (r.get("flags") or ())] for r in (inp.time.day_ledger or ())
             if isinstance(r, Mapping)}
    out = []
    for d in ctx.dates():
        ds = d.isoformat()
        sp = ctx.day_split(ds)
        e = ctx.env.get(ds) or {}
        df = ctx.days.get(ds)
        conf = {k: int((df.conf_min if df is not None else {}).get(k, 0) or 0) for k in ("high", "mid", "low")}
        out.append({"d": ds, "hol": not ctx.bc.is_workday(d),
                    "by_tag": {t: int(e[t]) for t in TAGS if int(e.get(t, 0) or 0)},
                    "env_min": int(sp["env_min"]), "conf_min": conf, "obs_min": int(sp["obs_min"]),
                    "est_min": int(sp["est_min"]), "unattr_min": int(sp["unattr_min"]),
                    "leave": _leave_val(inp.leaves.get(ds)) if inp.leaves else (df.leave if df is not None else 0.0),
                    "flags": flags.get(ds, [])})
    return out


def _months(ctx, inp, days: list[dict], sec: Mapping, bdaily: Mapping, cal, warnings: list) -> list[dict]:
    mm = {str(r.get("month")): r for r in (inp.time.mm_month or ()) if isinstance(r, Mapping)}
    bd_m: dict[str, Counter] = defaultdict(Counter)
    for (d, b, _t), v in bdaily.items():
        bd_m[d[:7]][b] += v
    rv = {r["key"]: r for r in (sec.get("reviews") or {}).get("months", ())}
    qm = (sec.get("quality") or {}).get("months") or {}
    by_month: dict[str, list[dict]] = defaultdict(list)
    for x in days:
        by_month[x["d"][:7]].append(x)
    out = []
    for m in ctx.months():
        rows = by_month.get(m, [])
        row = mm.get(m, {})
        env_min = sum(x["env_min"] for x in rows)
        by_tag = {t: sum(int(x["by_tag"].get(t, 0)) for x in rows) for t in TAGS}
        attributed = sum(x["obs_min"] + x["est_min"] for x in rows)
        unattr = env_min - attributed
        buckets = {b: int(_g(row.get("buckets_min"), b, 0) or 0) for b in BUCKETS}
        if sum(buckets.values()) != unattr:
            if row:
                warnings.append({"code": "mm_month_mismatch", "month": m,
                                 "text_ko": "월 결과의 미귀속 버킷이 정수 분 표와 달라 날짜 표로 다시 셌습니다"})
            buckets = {b: int(bd_m[m].get(b, 0)) for b in BUCKETS}
        y, mo = int(m[:4]), int(m[5:7])
        std = int(row.get("std_day_min") or getattr(cal, "std_day_min", 0) or 480)
        workdays = int(row.get("workdays") if row.get("workdays") is not None else cal.month_workdays(y, mo))
        denom_days = int(row.get("denom_days") if row.get("denom_days") is not None else workdays)
        covered = int(row.get("covered_workdays") if row.get("covered_workdays") is not None else workdays)
        avail_days = row.get("avail_days")
        avail_days = float(avail_days) if isinstance(avail_days, (int, float)) and not isinstance(avail_days, bool) \
            else float(covered)
        absence = row.get("absence_days")
        absence = float(absence) if isinstance(absence, (int, float)) and not isinstance(absence, bool) else 0.0
        avail_min = max(0, F.half_up(F.dec(std) * F.dec(avail_days)))
        daily8 = 0
        for x in rows:
            daily8 += x["env_min"] if x["hol"] else max(0, x["env_min"] - std)
        first = max(date(y, mo, 1), ctx.d0)
        last = min(_iso_month_end(m), ctx.d1)
        partial = None
        if first != date(y, mo, 1) or last != _iso_month_end(m) or covered < workdays:
            partial = {"from": first.isoformat(), "to": last.isoformat(), "workdays": covered, "of": workdays}
        rvm = rv.get(m) or {}
        q = dict(qm.get(m) or {})
        mmv = row.get("mm")
        out.append({
            "m": m, "workdays": workdays, "covered_workdays": covered, "denom_days": denom_days,
            "denom_min": std * denom_days, "std_day_min": std, "partial": partial, "env_min": env_min,
            "by_tag": by_tag, "attributed_min": attributed, "unattr_min": unattr, "buckets": buckets,
            "obs_min": sum(x["obs_min"] for x in rows), "est_min": sum(x["est_min"] for x in rows),
            "conf_min": {k: sum(x["conf_min"].get(k, 0) for x in rows) for k in ("high", "mid", "low")},
            "avail_days": avail_days, "avail_min": avail_min, "absence_days": absence,
            "load_pct": F.ratio(env_min * 100, avail_min, 2) if avail_min > 0 else None,
            "overtime_window_min": env_min - by_tag["regular"], "overtime_daily8h_min": daily8,
            "holiday_night_min": int(row.get("holiday_night_min") or 0), "on_leave_min": int(row.get("on_leave_min") or 0),
            "machine_min": int(row.get("machine_min") or 0),
            "mm": float(mmv) if isinstance(mmv, (int, float)) and not isinstance(mmv, bool) else None,
            "units": {"started": len(rvm.get("started") or ()), "finished": len(rvm.get("finished") or ()),
                      "continuing": len(rvm.get("continuing") or ()), "unstarted": len(rvm.get("unstarted") or ())},
            "quality": q})
    return out


# ───────────────────────────── 과제·역할·단위업무 ─────────────────────────────
def _majority_domain(units) -> str:
    c: Counter = Counter()
    for u in units:
        c[u.domain] += max(1, u.effort_min)
    return sorted(c, key=lambda d: (-c[d], V.domain_order(d), d))[0] if c else "UNC"


def _reg_projects(reg) -> list:
    """레지스트리 과제 목록 — 유효 레지스트리(EffectiveRegistry.projects 사전) 또는 원본 dict(`projects` 목록)."""
    ps = _g(reg, "projects", None)
    if isinstance(ps, Mapping):
        return list(ps.values())
    return [p for p in (ps or ()) if isinstance(p, Mapping)]


def _reg_project(reg, key: str):
    if reg is not None and hasattr(reg, "project"):
        return reg.project(key)
    return next((p for p in _reg_projects(reg) if _g(p, "id") == key), None)


def _projects(ctx, reg, proposals, res: Resolver) -> list[dict]:
    by_p: dict[str, list] = defaultdict(list)
    for u in ctx.unit_list():
        by_p[u.project_key].append(u)
    merged: dict[str, list[str]] = defaultdict(list)
    for pv in _reg_projects(reg):
        tgt = _g(pv, "merged_into")
        if tgt:
            merged[str(tgt)].append(str(_g(pv, "id", "")))
    props = {str(_g(p, "proposal_id", "")): p for p in proposals or ()}
    out = []
    for k, us in by_p.items():
        u0 = us[0]
        pv = _reg_project(reg, k)
        if k == "UNC":
            src = "none"
        elif pv is not None:
            src = "registry"
        elif k in props:
            src = "proposal"
        else:
            src = "id"
        out.append({"key": k, "project_id": u0.project_id, "proposal_id": u0.proposal_id, "label": res.project(k),
                    "label_src": src, "domain": _majority_domain(us),
                    "mask_name": bool(_g(pv, "mask_name", False)) if pv is not None else False,
                    "ax_link": bool(_g(pv, "ax_link", False)) if pv is not None else False,
                    "merged_from": sorted(merged.get(k, [])), "effort_min": sum(u.effort_min for u in us)})
    out.sort(key=lambda p: (V.domain_order(p["domain"]), -p["effort_min"], p["key"]))
    return out


def _roles(ctx, registry) -> list[dict]:
    seen: dict[str, object] = {}
    for u in ctx.unit_list():
        seen.setdefault(u.role_id, u)
    out = []
    for rid in sorted(seen):
        u = seen[rid]
        fn, cn = V.field_name(u.field, registry), V.func_name(u.func, registry)
        out.append({"role_id": rid, "project_key": u.project_key, "project_id": u.project_id,
                    "proposal_id": u.proposal_id, "field": u.field, "field_name": fn, "function": u.func,
                    "function_name": cn, "label": f"{fn} · {cn}"})
    return out


def _spans(u, ctx) -> list[list[str]]:
    """W §4.11 · 계약 §3.18 spans: lead 정확히 1개 = [첫 차수 시작, 마지막 차수 끝(진행 중이면 분석 시각)] + active(투입이 있는
    날을 이어 붙인 묶음)."""
    ds = sorted(d for d, m in u.by_date.items() if m > 0)
    if u.start is not None:
        a = u.start_date
        sp = u.span(ctx.as_of_min)
        b = (u.end_date or (ctx.as_of_date() if sp is None else _lmd(sp[1])))
    elif ds:
        a, b = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    else:
        return []
    if ds:
        a = min(a, date.fromisoformat(ds[0]))
        b = max(b, date.fromisoformat(ds[-1]))
    out = [[a.isoformat(), max(a, b).isoformat(), "lead"]]
    run0 = prev = None
    for s in ds:
        d = date.fromisoformat(s)
        if prev is not None and d == prev + timedelta(days=1):
            prev = d
            continue
        if run0 is not None:
            out.append([run0.isoformat(), prev.isoformat(), "active"])
        run0 = prev = d
    if run0 is not None:
        out.append([run0.isoformat(), prev.isoformat(), "active"])
    return out


def _lmd(m: int) -> date:
    from lm27.report.analysis.activity import lmin_date
    return lmin_date(m)


def _bound(cy, side: str, lines: Mapping) -> dict | None:
    from lm27.report.analysis.activity import lmin_iso
    if side == "start":
        if cy is None or cy.s is None:
            return None
        kind, prec = START_KIND.get(cy.sb, ("S2", "none"))
        ref, t = cy.s_ref, cy.s
    else:
        if cy is None or cy.e is None or not cy.eb:
            return None
        kind, prec = END_KIND.get(cy.eb, ("E2", "exact"))
        ref, t = cy.e_ref, cy.e
    line = lines.get(str(ref or "")) if lines else None
    if line and prec == "minute" and line.get("prec") in ("exact", "minute"):
        prec = str(line["prec"])
    return {"kind": kind, "at": lmin_iso(t), "precision": prec}


def _units(ctx, wf: Mapping, refs: Refs, pidx, docsets: Mapping, inp, queue_by_unit: Mapping) -> list[dict]:
    from lm27.report.analysis.activity import lmin_iso
    lines = _g(inp.evidence, "lines", {}) or {}
    labels = inp.labels or {}
    out = []
    for u in ctx.unit_list():
        uw = wf.get("units", {}).get(u.unit_id, {})
        app_sec: Counter = Counter()
        for x in ctx.log.get(u.unit_id, ()):
            if x.kind == "A":
                for a, s in x.apps:
                    app_sec[a] += s
        apps = sorted(([a, F.sec_min(s)] for a, s in app_sec.items() if F.sec_min(s) > 0), key=lambda p: (-p[1], p[0]))
        peers = sorted(refs.people[w] for w in pidx.by_unit.get(u.unit_id, {}) if w in refs.people)
        docs = sorted(refs.docs[f] for f in docsets.get(u.unit_id, ()) if f in refs.docs)
        dates = sorted(d for d, m in u.by_date.items() if m > 0)
        ev_dates = [x for x in (u.start_date, u.end_date) if x is not None] + [date.fromisoformat(d) for d in dates]
        lab = labels.get(u.unit_id) or {}
        cyc = list(u.cycles)
        st = next((c for c in cyc if c.s is not None), None)
        en = cyc[-1] if cyc else None
        out.append({
            "unit_id": u.unit_id, "title": u.title, "title_by": u.title_by, "role_id": u.role_id,
            "project_key": u.project_key, "project_id": u.project_id, "proposal_id": u.proposal_id,
            "domain": u.domain, "field": u.field, "function": u.func, "activity_type": u.wtype, "stance": u.stance,
            "ax_link": bool(u.ax_link), "label_level": u.label_level, "kind": u.kind,
            "cycles": [{"s": lmin_iso(c.s), "sb": c.sb, "e": lmin_iso(c.e), "eb": c.eb,
                        "interim": [[lmin_iso(t), code] for t, code in c.interim], "unstarted": bool(c.unstarted),
                        "s_key": str(c.s_ref or ""), "e_key": str(c.e_ref or "")} for c in cyc],
            "start": _bound(st, "start", lines), "end": _bound(en, "end", lines) if u.status != "open" else None,
            "grade": u.grade, "status": u.status, "lead_min": u.lead_min, "biz_lead_min": u.biz_lead_min,
            "effort_min": u.effort_min, "obs_min": u.obs_min, "est_min": u.est_min,
            "levels_min": {k: int(v) for k, v in u.levels_min.items() if int(v)},
            "parallel": u.parallel, "machine_min": u.machine_min, "pre_request_min": u.pre_request_min,
            "flags": list(u.flags),
            "first_evidence": min(ev_dates).isoformat() if ev_dates else None,
            "last_evidence": max(ev_dates).isoformat() if ev_dates else None,
            "spans": _spans(u, ctx), "density": ctx.density(u.unit_id),
            "by_month": {m: int(v) for m, v in u.by_month.items() if int(v)},
            "by_tag": {t: int(v) for t, v in u.by_tag.items() if int(v)},
            "steps": list(uw.get("steps", ())), "step_min": dict(uw.get("step_min", {})),
            "peers": peers, "apps": apps,
            "apps_unknown_min": sum(m for a, m in apps if a.startswith(UNKNOWN_PREFIX)),
            "docs": docs, "queue": sorted(queue_by_unit.get(u.unit_id, ())),
            "label_src": dict(_g(lab, "src", {}) or {}), "label_conf": dict(_g(lab, "conf", {}) or {}),
            "why": [str(x) for x in (_g(lab, "why", ()) or ())], "cands": _cands(lab)})
    return out


def _cands(lab) -> list[list]:
    """[왜?] 과제 후보(R §6.11 ⑦) — 분류 규칙 점수 상위 3 `[[과제 키, 점수]]`(labels.json `cands`). 로컬 전용(가림판 허용
    목록 밖)."""
    out = []
    for c in list(_g(lab, "cands", ()) or ())[:3]:
        if isinstance(c, (list, tuple)) and len(c) >= 2 and isinstance(c[0], str) and c[0] \
                and isinstance(c[1], (int, float)) and not isinstance(c[1], bool):
            out.append([c[0], F.half_up(c[1], 3)])
    return out


def _unattr_meet(inp, reg) -> dict[str, int]:
    """과제 키 → 관련 미귀속 회의 분(R §6.3.1 업무 트리 주석 'MM 미포함'): 분류 규칙이 그 과제로 꼬리표를 붙인 회의
    (`inputs.meet_tags` — 회의 제목·시리즈가 레지스트리 과제 키워드와 맞음)의 슬롯 중 미귀속 회의 버킷(B_MEET)으로 간 초를
    분으로. 시간 코어 귀속 행을 읽기만 한다 — MM·과제 투입에는 더하지 않는다. 예약 과제(영역 일반)는 주석을 달지 않는다."""
    tags = (inp.hier or {}).get("meet_tags") or {}
    ev = inp.evidence
    if not tags or ev is None:
        return {}
    from lm27.hier.vocab import is_reserved_id
    from lm27.time.calendar import SLOT
    meet_sec: dict[int, int] = defaultdict(int)
    for r in inp.time.attrib or ():
        if str(_g(r, "target", "")) != "B_MEET":
            continue
        try:
            slot, sec = int(_g(r, "slot")), int(_g(r, "sec", 0) or 0)
        except (TypeError, ValueError):
            continue
        if sec > 0:
            meet_sec[slot] += sec
    if not meet_sec:
        return {}
    slots: dict[str, set] = defaultdict(set)
    for mt in ev.meets or ():
        p = tags.get(str(_g(mt, "id", "") or ""))
        a, b = _g(mt, "a"), _g(mt, "b")
        if not p or is_reserved_id(p) or not isinstance(a, int) or not isinstance(b, int) or b <= a:
            continue
        if p.startswith("L-"):                       # 개인 과제는 트리에서 그 제안 ID 자리(H §12.3 role_slot)
            p = str(_g(_reg_project(reg, p), "proposal_id", "") or p)
        for k in range(a // SLOT, (b - 1) // SLOT + 1):
            if k in meet_sec:
                slots[p].add(k)
    return {p: F.sec_min(sum(meet_sec[k] for k in ks)) for p, ks in sorted(slots.items()) if ks}


def _bottleneck_text(rw) -> str:
    """역할 병목 한 줄 코드(R §9.2.1 tree `bottleneck` — 'wait:3|work:2', 표본 부족 'thin', 없으면 '')."""
    if not rw:
        return ""
    if rw.get("sample") == "thin":
        return "thin"
    return "|".join(f"{b['kind']}:{b['no']}" for b in rw.get("bottlenecks", ()))


def _tree(ctx, wf: Mapping, months: list[dict], units: list[dict], unattr_meet: Mapping | None = None) -> dict:
    """업무 트리 보조 정보(R §9.2.1 tree — 영역 → 과제 → 역할, 근무 중 미분류 + 버킷 5종). 과제 없음 = 노드 키 '-'.
    과제 노드의 `unattr_meet_min` = 관련 미귀속 회의 분(MM 미포함 주석 — `_unattr_meet`, 있을 때만)."""
    ms = [m["m"] for m in months]
    meet = unattr_meet or {}

    def stat(us):
        bm = {m: sum(int(u["by_month"].get(m, 0)) for u in us) for m in ms}
        leads = [u["biz_lead_min"] for u in us if u["status"] in ("closed", "estimated") and u["biz_lead_min"] is not None]
        return {"min_by_month": {m: v for m, v in bm.items() if v}, "min_total": sum(u["effort_min"] for u in us),
                "units": {"done": sum(1 for u in us if u["status"] in ("closed", "estimated")),
                          "open": sum(1 for u in us if u["status"] == "open"),
                          "unstarted": sum(1 for u in us if u["status"] == "not_started")},
                "lead_biz_median_min": F.median_int(leads)}
    by_d: dict[str, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for u in units:
        by_d[u["domain"]][u["project_key"]][u["role_id"]].append(u)
    nodes: dict[str, dict] = {}
    order = [d["code"] for d in V.domains()]
    for dc in order:
        projs = by_d.get(dc, {})
        if not projs and dc != "UNC":
            continue
        pkeys = []
        for pk, roles in projs.items():
            pn = "-" if pk == "UNC" else pk
            pus = [u for us in roles.values() for u in us]
            rids = sorted(roles, key=lambda r: (-sum(u["effort_min"] for u in roles[r]), r))
            for rid in rids:
                rus = roles[rid]
                nodes[rid] = {"level": "role", "parent": pn, "children": [u["unit_id"] for u in rus],
                              "bottleneck": _bottleneck_text(wf.get("roles", {}).get(rid)), **stat(rus)}
            nodes[pn] = {"level": "project", "parent": dc, "children": rids, **stat(pus)}
            if int(meet.get(pk, 0) or 0) > 0:
                nodes[pn]["unattr_meet_min"] = int(meet[pk])
            pkeys.append((pn, nodes[pn]["min_total"]))
        dus = [u for roles in projs.values() for us in roles.values() for u in us]
        nodes[dc] = {"level": "domain", "children": [k for k, _m in sorted(pkeys, key=lambda p: (-p[1], p[0]))], **stat(dus)}
    un = {m["m"]: m["unattr_min"] for m in months}
    nodes["UNATTR"] = {"level": "unattributed", "children": list(BUCKETS),
                       "min_by_month": {m: v for m, v in un.items() if v}, "min_total": sum(un.values())}
    for b in BUCKETS:
        bm = {m["m"]: int(m["buckets"].get(b, 0)) for m in months}
        nodes[b] = {"level": "bucket", "parent": "UNATTR", "min_by_month": {m: v for m, v in bm.items() if v},
                    "min_total": sum(bm.values())}
    return {"order": [d for d in order if d in nodes] + ["UNATTR"], "nodes": nodes}


# ───────────────────────────── 분석 절의 키 → 참조 ─────────────────────────────
def _workflows(wf: Mapping, refs: Refs, registry) -> dict:
    out = copy.deepcopy(dict(wf))
    for uw in out.get("units", {}).values():
        for r in uw.get("runs", ()):
            r["docs"] = [[refs.docs[f], m] for f, m in r.pop("fams", ()) if f in refs.docs]
        lw = uw.get("longest_wait")
        if isinstance(lw, dict):
            lw["after_name"] = V.step_name(lw.get("after"), registry) if lw.get("after") else ""
            lw["before_name"] = V.step_name(lw.get("before"), registry) if lw.get("before") else ""
    return out


def _review_rows(rows, refs: Refs, rank_of: Mapping, res: Resolver) -> list[dict]:
    out = []
    for r in rows:
        x = copy.deepcopy(dict(r))
        x["peers_top"] = [{"k": rank_of.get(p["key"]), "ref": refs.people.get(p["key"]), "name": res.person(p["key"]),
                           "units": p["units"], "shared_effort_min": p["shared_effort_min"]}
                          for p in r.get("peers_top", ()) if p.get("key") in refs.people]
        if isinstance(r.get("edge_refs"), Mapping):
            x["edge_refs"] = {n: {"from": refs.node(e["from"]), "to": refs.node(e["to"]), "rel": e["rel"]}
                              for n, e in r["edge_refs"].items()}
        ai = r.get("ai")
        if isinstance(ai, Mapping):
            x["ai"] = dict(ai)
            x["ai"]["peers_map"] = {t: refs.people.get(w) for t, w in (ai.get("peers_map") or {}).items()
                                    if w in refs.people}
        out.append(x)
    return out


def _peers(pe: Mapping, refs: Refs, res: Resolver) -> dict:
    internal = []
    for p in pe.get("internal", ()):
        ref = refs.people.get(p["key"])
        internal.append({"k": p["k"], "ref": ref, "name": res.person(p["key"]), "internal": p["internal"],
                         "units": p["units"], "unit_ids": list(p["unit_ids"]), "shared_effort_min": p["shared_effort_min"],
                         "roles": dict(p["roles"]), "projects": list(p["projects"]), "first": p["first"],
                         "last": p["last"]})
    return {"internal": internal, "others": dict(pe.get("others") or {}), "external": dict(pe.get("external") or {}),
            "unresolved": int(pe.get("unresolved") or 0), "verified": bool(pe.get("verified"))}


def _onto_label(n: Mapping, refs: Refs, res: Resolver, units: Mapping, redacted: bool) -> str:
    t = n.get("type")
    key = str(n.get("key") or "")
    if str(n.get("id", "")).startswith("etc:"):
        return f"기타 {n.get('etc', 0)}"
    if t == "P":
        return res.project(key)
    if t == "U":
        u = units.get(key)
        return (u["title"] if u else key) if not redacted else (u.get("title_red") if u else key)
    if t == "D":
        return res.doc(key) or "문서"
    if t == "A":
        return res.app(key)
    if t == "C":
        if key.startswith("ext:"):
            return V.EXT_CLASS_NAMES.get(key[4:], {"customer": "고객사", "partner": "협력사"}.get(key[4:], "외부"))
        return res.person(key)
    return str(n.get("label") or key)


def _graph(g: Mapping, refs: Refs, res: Resolver, units: Mapping, redacted: bool = False) -> dict:
    nodes = []
    for n in g.get("nodes", ()):
        x = {k: v for k, v in n.items() if k != "key"}
        x["id"] = refs.node(str(n.get("id", "")), redacted=redacted)
        x["label"] = _onto_label(n, refs, res, units, redacted)
        key = str(n.get("key") or "")
        if n.get("type") == "C" and not key.startswith("ext:") and key:
            x["ref"] = refs.people.get(key)
        elif n.get("type") == "D" and key:
            x["ref"] = refs.docs.get(key)
        elif n.get("type") == "A" and key:
            x["app"] = refs.app_id(key, redacted=redacted)
        nodes.append(x)
    edges = [{**dict(e), "from": refs.node(str(e["from"]), redacted=redacted),
              "to": refs.node(str(e["to"]), redacted=redacted)} for e in g.get("edges", ())]
    return {"nodes": nodes, "edges": edges}


def _ontology(onto: Mapping, refs: Refs, res: Resolver, units: Mapping, redacted: bool = False) -> dict:
    g = _graph(onto, refs, res, units, redacted)
    recs = {}
    for uid, rs in (onto.get("recs") or {}).items():
        recs[uid] = [{"unit_id": r["unit_id"], "rel": r["rel"], "seq": r.get("seq"), "kind": r["kind"],
                      "docs": int((r.get("shared") or {}).get("docs", 0)),
                      "peers": int((r.get("shared") or {}).get("peers", 0)),
                      "apps": int((r.get("shared") or {}).get("apps", 0)), "handoff": r.get("seq") == 1.0}
                     for r in rs]
    graphs = {}
    for k, gk in (onto.get("graphs") or {}).items():
        gg = _graph(gk, refs, res, units, redacted)
        gg["related_projects"] = [dict(p) for p in gk.get("related_projects", ())]
        graphs[k] = gg
    return {"center": onto.get("center"), "nodes": g["nodes"], "edges": g["edges"], "recs": recs,
            "related_projects": [dict(p) for p in onto.get("related_projects", ())],
            "centers": list(onto.get("centers", ())), "graphs": graphs}


def local_catalog_notes(hier_meta) -> list[str]:
    """분류 결과 ``hier_meta.warnings`` 의 로컬 카탈로그 경고(``local_catalog_*`` — 계약 v1.3 §0.8 V13) → 화면 문구
    (``lm27.hier.registry.LOCAL_CATALOG_WARNS``, 같은 문구는 한 번). 로컬 카탈로그를 못 쓴 까닭을 '팀 레지스트리를 받으면
    채워집니다' 대신 알린다(W2 검토 L04 — 통합)."""
    from lm27.hier.registry import LOCAL_CATALOG_WARNS
    out: list[str] = []
    for w in _g(hier_meta, "warnings", ()) or ():
        t = LOCAL_CATALOG_WARNS.get(w) if isinstance(w, str) else None
        if t and t not in out:
            out.append(t)
    return out


def _agentic(ag: Mapping, ctx, overrides, notes=()) -> dict:
    out = copy.deepcopy(dict(ag))
    out["catalog"] = [{"id": a["id"], "name": a["name"], "axis": a.get("axis", "")} for a in ctx.catalog]
    drops = (_g(overrides, "needs", {}) or {}) if isinstance(overrides, Mapping) else {}
    for n in out.get("needs", ()):
        n["dropped"] = str(drops.get(n["need_id"], "")) == "drop"
    if notes:
        out["catalog_note"] = " · ".join(notes)                # 로컬 카탈로그 경고(있을 때만 — 화면 Agentic 안내)
    return out


def _queue(inp, as_of_d: date) -> list[dict]:
    rows = []
    for kind, src in (("time", inp.time.queue or ()), ("hier", (inp.hier or {}).get("queue") or ())):
        for q in src:
            if not isinstance(q, Mapping) or not q.get("qid"):
                continue
            prop = q.get("proposal") if isinstance(q.get("proposal"), Mapping) else {}
            d = str(prop.get("date") or "")
            try:
                wk = F.iso_week(date.fromisoformat(d[:10])) if d else F.iso_week(as_of_d)
            except ValueError:
                wk = F.iso_week(as_of_d)
            rows.append({"qid": str(q["qid"]), "code": str(q.get("code") or ""), "kind": kind,
                         "target": str(q.get("target") or ""), "impact_min": int(q.get("impact_min") or 0),
                         "status": str(q.get("status") or "open"), "date": d[:10] or None, "week": wk,
                         "proposal": {k: copy.deepcopy(prop[k]) for k in _QUEUE_PROP if k in prop},
                         "evidence_keys": [str(x) for x in (q.get("evidence_keys") or ())]})
    rows.sort(key=lambda r: (r["status"] != "open", -r["impact_min"], r["code"], r["qid"]))
    return rows


def _label_sources(sec_sources: Mapping, labels: Mapping | None) -> dict:
    out = {k: dict(v) for k, v in (sec_sources or {}).items()}
    c = {"ai": 0, "manual": 0, "rule": 0, "user": 0}
    for lab in (labels or {}).values():
        s = str(_g(lab, "title_src", "") or "")
        c["ai" if s == "ai" else ("user" if s == "user" else "rule")] += 1
    out["task_label"] = c
    return out


# ───────────────────────────── 만들기 ─────────────────────────────
def build_model(inp, cfg, *, cal=None, ctx=None, fallback=None) -> dict:
    """R §9.2.3 `model.build_model(inputs, cfg) -> dict` — 등식(G-R2)을 어기면 `ModelCheckError`."""
    from lm27 import LM27_VERSION
    from lm27.report.analysis import analyze
    from lm27.report.analysis import peers as PE
    from lm27.report.analysis.ai_items import context_from_inputs
    from lm27.report.analysis.mining import doc_sets
    if inp.refused:
        raise ModelCheckError([f"필수 시간 결과 없음: {', '.join(sorted(inp.refused))}"])
    cal = cal or inp.calendar
    if cal is None:
        raise ValueError("build_model: 달력이 필요합니다(load_inputs 가 채운다)")
    ctx = ctx or context_from_inputs(inp, cfg, cal, fallback=fallback)
    sec = analyze(ctx)
    pidx = PE.peer_index(ctx.units.values(), ctx.evidence, ctx.person_dir, ctx.cfg, registry=ctx.registry)
    docsets = doc_sets(ctx.units.values(), ctx.log)
    refs = Refs.build(ctx, pidx, docsets)
    reg = inp.registry
    proposals = (inp.hier or {}).get("proposals") or []
    res = Resolver("full", inp.person_dir, reg, inp.evidence, people_ref=refs.people, doc_ref=refs.docs,
                   proposals=proposals)
    warnings: list = []
    days = _days(ctx, inp)
    bd, exact = bucket_daily(ctx, inp.time.attrib, inp.time.env_slots)
    months = _months(ctx, inp, days, sec, bd, cal, warnings)
    queue = _queue(inp, ctx.as_of_date())
    q_by_u: dict[str, list] = defaultdict(list)
    for q in queue:
        if q["target"].startswith("u_"):
            q_by_u[q["target"]].append(q["qid"])
        for k in q["evidence_keys"]:                 # 왜 묻는지 — 근거 키를 로컬 해석한 정제 제목(전체판만, R §6.9)
            why = res.msg(k) or res.fam_names.get(k)
            if why:
                q["why_ko"] = str(why)
                break
    units = _units(ctx, sec["workflows"], refs, pidx, docsets, inp, q_by_u)
    meta = (inp.hier or {}).get("meta") or {}
    run_meta = inp.time.run_meta or {}
    mm0 = next((r for r in (inp.time.mm_month or ()) if isinstance(r, Mapping)), {})
    std = int(mm0.get("std_day_min") or getattr(cal, "std_day_min", 0) or 480)
    basis = str(mm0.get("denominator") or (run_meta.get("cfg_used") or {}).get("mm.denominator") or "workdays")
    ot_basis = str(mm0.get("overtime_basis") or (run_meta.get("cfg_used") or {}).get("mm.overtimeBasis") or "window")
    from lm27.privacy import RULES_VERSION
    from lm27.report.inputs import tz_offset_of
    stage_versions = {st: (str(_g(obj, "stage_ver", "")) or None) if isinstance(obj, Mapping) else None
                      for st, obj in sorted((inp.ai or {}).items())}
    all_warn = []
    seen = set()
    for w in list(inp.warnings) + list(sec["flags"]["warnings"]) + warnings:
        if w.get("code") not in seen:
            seen.add(w.get("code"))
            all_warn.append(dict(w))
    lc_notes = local_catalog_notes(meta)
    if lc_notes:                                       # 로컬 카탈로그를 못 썼거나 고쳐 읽음 — 그 까닭을 그대로(V13 · L04)
        lc_text = " · ".join(lc_notes)
        empty = [w for w in all_warn if w.get("code") == "catalog_empty"]
        for w in empty:
            w["text_ko"] = "에이전트 목록이 없습니다 — " + lc_text
        if not empty:
            all_warn.append({"code": "local_catalog", "text_ko": lc_text})
    reg_st = inp.registry_status or {}
    rank = {p["key"]: p["k"] for p in sec["peers"].get("internal", ())}
    rank.update({w: r for w, r in refs.people.items() if w not in rank})
    unit_map = {u["unit_id"]: u for u in units}
    pdir_people = _g(inp.person_dir, "people", {}) or {}
    model = {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "generator": {"app_version": LM27_VERSION, "report_version": REPORT_VERSION,
                      "core_version": str(run_meta.get("core_version") or ""), "rules_ver": str(RULES_VERSION),
                      "registry_version": int(_g(reg, "version", 0) or 0),
                      "calendar_version": str(run_meta.get("calendar_version") or getattr(cal, "version", "") or ""),
                      "catalog_version": str(_g(reg, "catalog_version", "") or ""), "stage_versions": stage_versions},
        "variant": "full",
        "run": {**{k: v for k, v in (inp.run or {}).items() if v is not None},
                "tz_offset_min": tz_offset_of(inp, cfg)},
        "flags": {"copilot": sec["flags"]["copilot"],
                  "registry": {"version": int(reg_st.get("version") or 0), "fetched_at": reg_st.get("fetched_at"),
                               "source": reg_st.get("source")},
                  "warnings": all_warn, "label_sources": _label_sources(sec["flags"]["label_sources"], inp.labels),
                  "hier": {"ai_share": meta.get("ai_share"), "unclassified_share": meta.get("unclassified_share"),
                           "registry_ko": reg_st.get("label_ko")},
                  "mining_coarse": bool(sec["flags"].get("mining_coarse")), "buckets_exact": bool(exact),
                  "missing": sorted(inp.missing), "trimmed": []},
        "denominator": {"basis": basis, "std_day_min": std, "overtime_basis": ot_basis,
                        "text_ko": DENOM_TEXT.get(basis, DENOM_TEXT["workdays"]).format(h=F.fmt_ratio(std, 60, 0))},
        "domains": V.domains(),
        "months": months,
        "days": days,
        "projects": _projects(ctx, reg, proposals, res),
        "proposals": [{"proposal_id": str(p.get("proposal_id")), "kind": str(p.get("kind") or "project"),
                       "label": str(p.get("label") or ""), "domain_guess": str(p.get("domain_guess") or "UNC"),
                       "status": str(p.get("status") or "")}
                      for p in sorted(proposals, key=lambda p: str(p.get("proposal_id")))
                      if str(p.get("proposal_id")) in {u.proposal_id for u in ctx.units.values()}],
        "roles": _roles(ctx, reg),
        "units": units,
        "tree": _tree(ctx, sec["workflows"], months, units, _unattr_meet(inp, reg)),
        "workflows": _workflows(sec["workflows"], refs, reg),
        "reviews": {"weeks": _review_rows(sec["reviews"].get("weeks", ()), refs, rank, res),
                    "months": _review_rows(sec["reviews"].get("months", ()), refs, rank, res)},
        "peers": _peers(sec["peers"], refs, res),
        "ontology": _ontology(sec["ontology"], refs, res, unit_map),
        "agentic": _agentic(sec["agentic"], ctx, inp.overrides, lc_notes),
        "subagent": copy.deepcopy(dict(sec["subagent"])),
        "team": copy.deepcopy(dict(sec["team"])),
        "queue": queue,
        "quality": {k: copy.deepcopy(v) for k, v in sec["quality"].items() if k != "months"},
        "tables": {"envelope_daily": copy.deepcopy(dict((inp.time.team_tables or {}).get("envelope_daily") or {})),
                   "alloc_daily": copy.deepcopy(dict((inp.time.team_tables or {}).get("alloc_daily") or {})),
                   "buckets_daily": {"cols": ["date", "bucket", "tag", "min"],
                                     "rows": [[d, b, t, v] for (d, b, t), v in sorted(
                                         bd.items(), key=lambda kv: (kv[0][0], BUCKETS.index(kv[0][1]),
                                                                     TAGS.index(kv[0][2]) if kv[0][2] in TAGS else 9))]}},
        "refs": {"people": {str(r): {"key": w, "name": res.person(w),
                                     "internal": True if bool(_g(pdir_people.get(w), "internal", False)) else None}
                            for w, r in sorted(refs.people.items(), key=lambda kv: kv[1])},
                 "docs": {str(r): _doc_ref(f, res, ctx, refs) for f, r in sorted(refs.docs.items(), key=lambda kv: kv[1])},
                 "apps": {a: _app_ref(a, res) for a in refs.apps}},
    }
    cap_mb = int(cfg["report.export.maxModelMb"])
    model, trimmed, size = _fit(model, cap_mb * MB)
    if trimmed:
        before = _size(model["flags"])
        model["flags"]["trimmed"] = trimmed
        model["flags"]["warnings"].append({"code": "model_trimmed", "text_ko": "보고서 모델이 크기 상한을 넘어 일부 상세를 "
                                           "요약했습니다: " + ", ".join(trimmed)})
        size += _size(model["flags"]) - before
    if size > cap_mb * MB:                           # 다 줄여도 넘으면 숨기지 않고 알린다(X-281 — 보고서는 그대로 만든다)
        w = V.warn("model_over_cap", bytes=size, cap_mb=cap_mb)
        w["text_ko"] = w["text_ko"].format(mb=F.fmt_ratio(size, MB, 1), cap=cap_mb)
        model["flags"]["warnings"].append(w)
    problems = check_model(model)
    if problems:
        raise ModelCheckError(problems)
    return model


def _doc_ref(fam: str, res: Resolver, ctx, refs: Refs) -> dict:
    name = res.fam_names.get(fam)
    ext = ""
    if isinstance(name, str) and "." in name:
        ext = name.rsplit(".", 1)[-1].lower()[:8]
    return {"key": fam, "name": res.doc(fam), "ext": ext, "cls": ctx.doc_class(fam), "min": int(refs.doc_min.get(fam, 0))}


def _app_ref(app: str, res: Resolver) -> dict:
    from lm27.catalog import app_class_of, cat_of
    return {"name": res.app(app), "cls": app_class_of(app), "cat": cat_of(app)}


# ───────────────────────────── 크기 상한(X-281 · R §9.2.2) ─────────────────────────────
def _runs_summary(runs) -> list[dict]:
    agg: dict[str, dict] = {}
    for r in runs or ():
        a = agg.setdefault(r.get("type", ""), {"type": r.get("type", ""), "class": r.get("class", ""), "min": 0,
                                               "obs_min": 0, "n": 0})
        a["min"] += int(r.get("min") or 0)
        a["obs_min"] += int(r.get("obs_min") or 0)
        a["n"] += 1
    return [agg[k] for k in sorted(agg)]


REC_KEEP_TRIMMED = 3      # 크기 상한 5단계 — 단위업무별 연관 업무 추천을 이만큼만 남긴다
_LEAD_SLIM = ("unit_id", "overrun", "causes", "cause_names")   # 4단계 — 주간 '끝낸 일' 표에 남기는 열(나머지는 단위업무·월간 표에)


def _size(o) -> int:
    return len(canon_bytes(o))


def _fit(model: dict, max_bytes: int) -> tuple[dict, list[str], int]:
    """`fit_size` 본체 — (모델, 줄인 것 이름 목록, 줄인 뒤 모델 바이트 수). 바이트 수는 처음에 한 번만 직렬화하고, 단계마다
    바뀐 절만 다시 재어 더한다(정규 JSON 은 값 하나를 바꾸면 전체 길이가 그 값 길이 차만큼 바뀐다 — 9개월 모델 34MB 를
    단계마다 통째로 다시 직렬화하지 않는다, W2 검토 C07)."""
    trimmed: list[str] = []
    size = len(model_bytes(model))
    if size <= max_bytes:
        return model, trimmed, size

    def step(key: str, sub: str | None, fn) -> None:
        nonlocal size
        box = model.get(key) if sub is None else (model.get(key) or {}).get(sub)
        before = _size(box)
        fn()
        box = model.get(key) if sub is None else (model.get(key) or {}).get(sub)
        size += _size(box) - before

    wu = (model.get("workflows") or {}).get("units", {})

    def runs():
        for uw in wu.values():
            uw["runs"] = _runs_summary(uw.get("runs"))
            uw["runs_summarized"] = True
    step("workflows", None, runs)
    trimmed.append("단위업무 구간(runs) 요약")
    if size > max_bytes and (model.get("ontology") or {}).get("graphs"):
        step("ontology", None, lambda: model["ontology"].__setitem__("graphs", {}))
        trimmed.append("다른 과제 연관 그래프")
    if size > max_bytes:
        def waits():
            for uw in wu.values():
                uw["waits"] = []
                uw["milestones"] = []
        step("workflows", None, waits)
        trimmed.append("단위업무 대기·점 목록")
    weeks = (model.get("reviews") or {}).get("weeks") or []
    if size > max_bytes and any(r.get("lead_table") for r in weeks):
        def slim():                    # 같은 단위업무의 리드·투입·병행도·등급은 units[], 원인 설명은 월간 리뷰 표에 그대로 있다
            for r in weeks:
                r["lead_table"] = [{k: x[k] for k in _LEAD_SLIM if k in x} for x in r.get("lead_table") or ()]
        step("reviews", "weeks", slim)
        trimmed.append("주간 리뷰 끝낸 일 표 상세(월간 리뷰에 남김)")
    recs = (model.get("ontology") or {}).get("recs") or {}
    if size > max_bytes and any(len(v) > REC_KEEP_TRIMMED for v in recs.values()):
        def top3():
            for k in recs:
                recs[k] = recs[k][:REC_KEEP_TRIMMED]
        step("ontology", None, top3)
        trimmed.append(f"연관 업무 추천(상위 {REC_KEEP_TRIMMED}개만)")
    if size > max_bytes and any(r.get("lead_table") for r in weeks):
        def drop_weeks():
            for r in weeks:
                r["lead_table"] = []
        step("reviews", "weeks", drop_weeks)
        trimmed.append("주간 리뷰 끝낸 일 표(끝낸 일 목록만)")
    return model, trimmed, size


def fit_size(model: dict, max_bytes: int) -> tuple[dict, list[str]]:
    """모델 바이트가 상한을 넘으면 차례로 줄인다(X-281 · R §9.2.2 — 앞 단계로 상한 안에 들면 멈춘다):
    ① 단위업무 수준 `runs` 를 단계 유형별 요약으로 ② 다른 과제 그래프(`ontology.graphs`)를 뺀다 ③ 단위업무 대기·점 목록을
    뺀다 ④ 주간 리뷰 '끝낸 일' 표를 원인 코드만 남긴 얇은 행으로(같은 행이 월간 리뷰에 그대로 있다) ⑤ 연관 업무 추천을
    단위업무마다 상위 3개로 ⑥ 주간 리뷰 '끝낸 일' 표를 비운다(화면은 `finished` 목록과 단위업무 값으로 그린다).
    `days`·등식 재료(정수 분 표·단위업무 분)는 남긴다. 그래도 넘으면 `build_model` 이 `model_over_cap` 경고를 단다.
    반환 (모델, 줄인 것 이름 목록)."""
    model, trimmed, _n = _fit(model, max_bytes)
    return model, trimmed


# ───────────────────────────── 등식 검사(G-R2 · R §9.2.2) ─────────────────────────────
def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_mins(o, path: str, out: list[str]) -> None:
    if isinstance(o, Mapping):
        for k, v in o.items():
            p = f"{path}.{k}" if path else str(k)
            if isinstance(k, str) and k.endswith("_min") and v is not None:
                vals = list(v.values()) if isinstance(v, Mapping) else [v]
                for x in vals:
                    if isinstance(x, (Mapping, list)):
                        continue
                    if x is not None and (not _is_int(x) or x < 0):
                        out.append(f"{p}: 정수 분(≥ 0)이 아닙니다({x!r})")
                        break
            _check_mins(v, p, out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _check_mins(v, f"{path}[{i}]", out)


def check_model(model: Mapping) -> list[str]:
    """R §9.2.2 모델 등식 — 위반 목록(빈 목록 = 통과). 경로·차이 분만(값의 원문 없음).

    날마다 obs + est + unattr = env · Σ by_tag = env · env = 봉투 표 그날 합 / 달마다 env = Σ 날짜 = 봉투 표 그달 합 ·
    attributed + unattr = env · obs + est = attributed · Σ buckets = unattr / 단위업무 effort = Σ alloc · obs + est = effort /
    (날짜, 꼬리표) 칸 Σ alloc ≤ envelope / 모든 *_min 은 정수 ≥ 0 / 참조 정수가 refs 에 있음."""
    out: list[str] = []
    _check_mins(model, "", out)
    tables = model.get("tables") or {}
    env_rows = (tables.get("envelope_daily") or {}).get("rows") or []
    env_cols = (tables.get("envelope_daily") or {}).get("cols") or ["date", *TAGS]
    env_day: Counter = Counter()
    env_cell: Counter = Counter()
    for row in env_rows:
        rec = dict(zip(env_cols, row, strict=False))
        for t in TAGS:
            v = int(rec.get(t, 0) or 0)
            env_day[str(rec.get("date"))] += v
            env_cell[(str(rec.get("date")), t)] += v
    a_rows = (tables.get("alloc_daily") or {}).get("rows") or []
    a_cols = (tables.get("alloc_daily") or {}).get("cols") or ["date", "unit_id", "tag", "min"]
    alloc_u: Counter = Counter()
    alloc_cell: Counter = Counter()
    for row in a_rows:
        rec = dict(zip(a_cols, row, strict=False))
        alloc_u[str(rec.get("unit_id"))] += int(rec.get("min", 0) or 0)
        alloc_cell[(str(rec.get("date")), str(rec.get("tag")))] += int(rec.get("min", 0) or 0)
    for k, v in sorted(alloc_cell.items()):
        if v > env_cell.get(k, 0):
            out.append(f"tables.alloc_daily[{k[0]} {k[1]}]: Σalloc {v} > envelope {env_cell.get(k, 0)}")
    b_tab = tables.get("buckets_daily")
    b_day: Counter = Counter()
    for row in (b_tab or {}).get("rows") or []:
        b_day[str(row[0])] += int(row[3] or 0)
    days = model.get("days") or []
    seen_days = set()
    for x in days:
        d = x["d"]
        seen_days.add(d)
        if b_tab is not None and b_day.get(d, 0) != x["unattr_min"]:
            out.append(f"days[{d}]: Σbuckets_daily {b_day.get(d, 0)} ≠ unattr {x['unattr_min']}")
        if x["obs_min"] + x["est_min"] + x["unattr_min"] != x["env_min"]:
            out.append(f"days[{d}]: obs+est+unattr {x['obs_min'] + x['est_min'] + x['unattr_min']} ≠ env {x['env_min']}")
        if sum(x["by_tag"].values()) != x["env_min"]:
            out.append(f"days[{d}]: Σby_tag {sum(x['by_tag'].values())} ≠ env {x['env_min']}")
        if env_day.get(d, 0) != x["env_min"]:
            out.append(f"days[{d}]: env {x['env_min']} ≠ 봉투 표 {env_day.get(d, 0)}")
    for d, v in sorted(env_day.items()):
        if v and d not in seen_days:
            out.append(f"tables.envelope_daily[{d}]: 기간 밖 봉투 {v}분")
    for m in model.get("months") or []:
        k = m["m"]
        ds = sum(x["env_min"] for x in days if x["d"][:7] == k)
        tab = sum(v for d, v in env_day.items() if d[:7] == k)
        if m["env_min"] != ds:
            out.append(f"months[{k}].env_min {m['env_min']} ≠ Σdays {ds}")
        if m["env_min"] != tab:
            out.append(f"months[{k}].env_min {m['env_min']} ≠ 봉투 표 {tab}")
        if m["attributed_min"] + m["unattr_min"] != m["env_min"]:
            out.append(f"months[{k}]: attributed+unattr {m['attributed_min'] + m['unattr_min']} ≠ env {m['env_min']}")
        if m["obs_min"] + m["est_min"] != m["attributed_min"]:
            out.append(f"months[{k}]: obs+est {m['obs_min'] + m['est_min']} ≠ attributed {m['attributed_min']}")
        if sum(m["buckets"].values()) != m["unattr_min"]:
            out.append(f"months[{k}]: Σbuckets {sum(m['buckets'].values())} ≠ unattr {m['unattr_min']}")
        if sum(m["by_tag"].values()) != m["env_min"]:
            out.append(f"months[{k}]: Σby_tag {sum(m['by_tag'].values())} ≠ env {m['env_min']}")
    refs = model.get("refs") or {}
    people = set((refs.get("people") or {}).keys())
    docs = set((refs.get("docs") or {}).keys())
    seen_u = set()
    for u in model.get("units") or []:
        uid = u["unit_id"]
        seen_u.add(uid)
        if u["effort_min"] != alloc_u.get(uid, 0):
            out.append(f"units[{uid}].effort_min {u['effort_min']} ≠ Σalloc {alloc_u.get(uid, 0)}")
        if u["obs_min"] + u["est_min"] != u["effort_min"]:
            out.append(f"units[{uid}]: obs+est {u['obs_min'] + u['est_min']} ≠ effort {u['effort_min']}")
        if sum(u["by_month"].values()) != u["effort_min"]:
            out.append(f"units[{uid}]: Σby_month ≠ effort")
        if sum(u["by_tag"].values()) != u["effort_min"]:
            out.append(f"units[{uid}]: Σby_tag ≠ effort")
        if any(str(r) not in people for r in u.get("peers", ())):
            out.append(f"units[{uid}].peers: refs.people 에 없는 참조")
        if any(str(r) not in docs for r in u.get("docs", ())):
            out.append(f"units[{uid}].docs: refs.docs 에 없는 참조")
    for uid in sorted(set(alloc_u) - seen_u):
        if alloc_u[uid]:
            out.append(f"tables.alloc_daily[{uid}]: units 에 없는 단위업무")
    return out


# ───────────────────────────── 가림판(R §9.2.4) — 허용 목록으로 다시 만들기 ─────────────────────────────
_UNIT_KEEP = ("unit_id", "title_by", "role_id", "project_key", "project_id", "proposal_id", "domain", "field",
              "function", "activity_type", "stance", "ax_link", "label_level", "kind", "start", "end", "grade", "status",
              "lead_min", "biz_lead_min", "effort_min", "obs_min", "est_min", "levels_min", "parallel", "machine_min",
              "pre_request_min", "first_evidence", "last_evidence", "spans", "density", "by_month", "by_tag", "steps",
              "step_min", "peers", "apps_unknown_min")
_SAFE_FLAG = re.compile(r"^[^\[\]]{0,40}$")
_HEXRUN = re.compile(r"[0-9a-f]{8,}")


def _safe_flag(s: str) -> bool:
    return bool(_SAFE_FLAG.match(s)) and not _HEXRUN.search(s) and not s.startswith("회의연결")


def _peer_text(text, ref_of: Mapping) -> str:
    def sub(m):
        r = ref_of.get(f"동료{m.group(1)}")
        return f"동료 #{r}" if r is not None else "동료"
    return _PEER_TOKEN.sub(sub, str(text or ""))


# 정제기의 사람 가명 토큰 `[사람#<who_key 앞 6hex>]`(person_tokens=keyed) — 가림판에는 남기지 않는다(W2 검토 C13)
PERSON_TOKEN_RX = re.compile(r"\[사람#[0-9a-f]{6}\]")
# 가림판 확인 질문 대상으로 낼 수 있는 모양(단위업무·군집·날짜·제안·레지스트리 ID) — 그 밖(H04 이름 쌍 등 제목 글)은 None(C14)
_SAFE_TARGET = re.compile(r"^(?:u_[0-9A-Za-z_]{1,40}|grp:[0-9a-f]{12}|\d{4}-\d{2}-\d{2}|pr_[0-9A-Za-z_]{1,40}|"
                          r"[PL]-[0-9A-Za-z-]{1,40}|-)$")
_FACT_DOING = "진행"


def _no_person_tokens(o):
    """가림판 객체의 모든 글자 값에서 사람 가명 토큰을 '동료' 로(키는 그대로 — 키에는 토큰이 오지 않는다)."""
    if isinstance(o, str):
        return PERSON_TOKEN_RX.sub("동료", o) if "[사람#" in o else o
    if isinstance(o, list):
        return [_no_person_tokens(v) for v in o]
    if isinstance(o, dict):
        return {k: _no_person_tokens(v) for k, v in o.items()}
    return o


def _safe_target(code: str, tgt: str) -> str | None:
    """가림판 질문 대상: 모양 허용 목록만(H04 = 단위업무 제목 쌍이라 늘 None — 공백을 지운 제목이 이름 검사를 피한다)."""
    if code == "H04" or not tgt or KEY_RX.search(tgt) or not _SAFE_TARGET.match(tgt):
        return None
    return tgt


def _review_ai_redacted(ai: Mapping, r: Mapping, x_facts: list, titles: Mapping, full_titles: Mapping) -> dict:
    """리뷰 AI 문장(가림판, W2 검토 C13). 문장은 코파일럿·폴백이 **전체판 사실 제목**으로 썼다 — 그대로 옮기면 가림 제목·
    일반 제목으로 바꾼 단위업무의 원래 제목이 남는다.
    - 규칙 폴백(by=rule): 하이라이트 = 그 사실(F 번호)의 가림 제목, 다음 = '진행' 사실의 가림 제목 — 베끼지 않고 다시 만든다.
    - AI·수동 답: 사실·관계에 실린 원래 제목 → 가림 제목(긴 것부터) 바꿔 쓰기.
    둘 다 동료 번호표(`동료k` → `동료 #k`)와 사람 가명 토큰 지우기를 거친다."""
    ref_of = dict(ai.get("peers_map") or {})
    fu = r.get("fact_units") or {}
    pairs: dict[str, str] = {}
    for f in r.get("facts", ()):
        if isinstance(f, list) and len(f) >= 5 and f[2]:
            red = titles.get(fu.get(f[0]))
            if red is not None and str(f[2]) != red:
                pairs[str(f[2])] = red
    er = r.get("edge_refs") or {}
    for e in r.get("edges", ()):
        ref = er.get(e[0]) if isinstance(e, list) and e else None
        for nid, lab in (((ref or {}).get("from"), e[1] if len(e) > 1 else ""), ((ref or {}).get("to"),
                                                                                e[3] if len(e) > 3 else "")):
            if isinstance(nid, str) and nid in titles and lab and str(lab) != titles[nid]:
                pairs.setdefault(str(lab), titles[nid])
    for uid, t in full_titles.items():
        if t and uid in titles and t != titles[uid]:
            pairs.setdefault(str(t), titles[uid])
    order = sorted((k for k in pairs if len(k.strip()) >= 2), key=lambda s: (-len(s), s))

    def clean(text) -> str:
        s = str(text or "")
        for k in order:
            if k in s:
                s = s.replace(k, pairs[k])
        return PERSON_TOKEN_RX.sub("동료", _peer_text(s, ref_of))
    red_fact = {f[0]: f[2] for f in x_facts}
    rule = ai.get("by") == "rule"
    hl = []
    for h in ai.get("highlights", ()):
        refs = list(h.get("refs", ()))
        text = red_fact.get(refs[0]) if (rule and refs and refs[0] in red_fact) else None
        hl.append({"text": clean(text if text is not None else h.get("text")), "refs": refs,
                   "units": list(h.get("units", ())), "effort_min": h.get("effort_min"),
                   "biz_lead_min": h.get("biz_lead_min")})
    nxt_full = list(ai.get("next", ()))
    if rule:
        nxt = [clean(f[2]) for f in x_facts if f[1] == _FACT_DOING and f[2]][:len(nxt_full)]
    else:
        nxt = [clean(t) for t in nxt_full]
    return {"summary": clean(ai.get("summary")), "highlights": hl,
            "relations": [{"text": clean(h.get("text")), "refs": list(h.get("refs", ()))}
                          for h in ai.get("relations", ())],
            "next": nxt, "by": ai.get("by")}


def _generic_titles(units, registry) -> dict[str, str]:
    """일반 제목 `<분야>·<기능> 단위업무 #n`(n = 같은 분야·기능 안 순번 — 단위업무 정렬 순, TAB §2.5)."""
    n: Counter = Counter()
    out = {}
    for u in units:
        k = (u["field"], u["function"])
        n[k] += 1
        out[u["unit_id"]] = f"{V.field_name(k[0], registry)}·{V.func_name(k[1], registry)} 단위업무 #{n[k]}"
    return out


def redact_model(full: Mapping, registry=None, *, person_dir=None, title_mode: str = "label") -> dict:
    """가림판 모델 — full 을 복사해서 지우지 않고 허용 목록 필드만 골라 **새 dict** 를 만든다(R §9.2.4 · TAB §2.4 와 같은 방식).
    사람 이름·문서 이름·메시지 제목·근거 키·로컬 키가 없다(번호표 `동료 #k`·`문서 #k` 만)."""
    res = Resolver("redacted", person_dir, registry, None, title_mode=title_mode)
    keep = copy.deepcopy
    units_full = full.get("units") or []
    generic = _generic_titles(units_full, registry)
    titles = {u["unit_id"]: res.unit_title(u.get("title"), generic[u["unit_id"]]) for u in units_full}
    full_titles = {u["unit_id"]: str(u.get("title") or "") for u in units_full}
    unknown = sorted({a for u in units_full for a, _m in u.get("apps", ()) if str(a).startswith(UNKNOWN_PREFIX)})
    refs = Refs({}, {}, {}, unknown)
    proj_label = {}
    out_projects = []
    for p in full.get("projects") or []:
        lab = p["key"] if (p.get("mask_name") or p.get("label_src") == "proposal") else p.get("label")
        if p["key"] == "UNC":
            lab = p.get("label")
        proj_label[p["key"]] = lab
        out_projects.append({"key": p["key"], "project_id": p.get("project_id"), "proposal_id": p.get("proposal_id"),
                             "domain": p.get("domain"), "label": lab, "label_src": p.get("label_src"),
                             "ax_link": bool(p.get("ax_link")), "effort_min": p.get("effort_min", 0)})
    units = []
    for u in units_full:
        x = {k: keep(u[k]) for k in _UNIT_KEEP if k in u}
        x["title"] = titles[u["unit_id"]]
        x["title_mode"] = "label" if titles[u["unit_id"]] == u.get("title") else "generic"
        x["cycles"] = [{k: keep(c[k]) for k in ("s", "sb", "e", "eb", "interim", "unstarted") if k in c}
                       for c in u.get("cycles", ())]
        x["apps"] = [[a, m] for a, m in u.get("apps", ()) if not str(a).startswith(UNKNOWN_PREFIX)]
        x["flags"] = [f for f in u.get("flags", ()) if _safe_flag(str(f))]
        units.append(x)
    wf = full.get("workflows") or {}
    wunits = {}
    for uid, uw in (wf.get("units") or {}).items():
        x = {k: keep(uw[k]) for k in ("unit_id", "lanes", "boundaries", "waits", "longest_wait", "explained_ratio",
                                      "cycles", "steps", "step_min", "runs_summarized") if k in uw}
        x["milestones"] = [{k: keep(m[k]) for k in ("type", "t", "cycle", "flags") if k in m} for m in uw.get("milestones", ())]
        x["runs"] = []
        for r in uw.get("runs", ()):
            y = {k: keep(r[k]) for k in ("type", "class", "a", "b", "min", "obs_min", "n") if k in r}
            cats = Counter()
            for a, m in r.get("apps", ()) or ():
                cats[_app_cat(a)] += int(m)
            y["apps"] = [[c, m] for c, m in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))]
            x["runs"].append(y)
        wunits[uid] = x
    reviews = {}
    for kind in ("weeks", "months"):
        rows = []
        for r in (full.get("reviews") or {}).get(kind, ()):
            x = {k: keep(r[k]) for k in ("key", "from", "to", "partial", "env_min", "by_tag", "attributed_min",
                                         "unattr_min", "obs_min", "est_min", "top_projects", "active", "started",
                                         "finished", "continuing", "unstarted", "lead_table", "ot_units",
                                         "fact_units") if k in r}
            x["peers_top"] = [{"k": p.get("k"), "ref": p.get("ref"), "name": res.numbered(p.get("ref")),
                               "units": p.get("units"), "shared_effort_min": p.get("shared_effort_min")}
                              for p in r.get("peers_top", ())]
            fu = r.get("fact_units") or {}
            # 단위업무에 이어지지 않는 사실의 제목은 가림 검사를 거치지 않았다 — 원래 제목을 내지 않는다(C13)
            x["facts"] = [[f[0], f[1], titles.get(fu.get(f[0])) or "단위업무", f[3], f[4]]
                          for f in r.get("facts", ()) if isinstance(f, list) and len(f) >= 5]
            er = r.get("edge_refs") or {}
            x["edges"] = []
            for e in r.get("edges", ()):
                ref = er.get(e[0]) or {}
                x["edges"].append([e[0], _edge_label(ref.get("from"), e[1], titles),
                                   e[2], _edge_label(ref.get("to"), e[3], titles)])
            x["edge_refs"] = {n: {"from": _red_id(v.get("from"), refs), "to": _red_id(v.get("to"), refs),
                                  "rel": v.get("rel")} for n, v in er.items()} if er else {}
            ai = r.get("ai")
            if isinstance(ai, Mapping):
                x["ai"] = _review_ai_redacted(ai, r, x["facts"], titles, full_titles)
            else:
                x["ai"] = None
            rows.append(x)
        reviews[kind] = rows
    pe = full.get("peers") or {}
    peers = {"internal": [{"k": p["k"], "ref": p["ref"], "name": res.numbered(p["ref"]), "internal": p.get("internal"),
                           "units": p["units"], "unit_ids": list(p.get("unit_ids", ())),
                           "shared_effort_min": p["shared_effort_min"], "roles": dict(p["roles"]),
                           "projects": list(p["projects"]), "first": p["first"], "last": p["last"]}
                          for p in pe.get("internal", ())],
             "others": keep(pe.get("others") or {}), "external": keep(pe.get("external") or {}),
             "unresolved": int(pe.get("unresolved") or 0), "verified": bool(pe.get("verified"))}
    onto = full.get("ontology") or {}
    o_out = {"center": onto.get("center"), "nodes": _red_nodes(onto.get("nodes", ()), proj_label, titles, refs),
             "edges": _red_edges(onto.get("edges", ()), refs), "recs": keep(onto.get("recs") or {}),
             "related_projects": keep(onto.get("related_projects") or []), "centers": keep(onto.get("centers") or []),
             "graphs": {k: {"nodes": _red_nodes(g.get("nodes", ()), proj_label, titles, refs),
                            "edges": _red_edges(g.get("edges", ()), refs),
                            "related_projects": keep(g.get("related_projects") or [])}
                        for k, g in (onto.get("graphs") or {}).items()}}
    queue = []
    for q in full.get("queue") or []:
        prop = {k: keep(v) for k, v in (q.get("proposal") or {}).items() if k in _QUEUE_PROP and k != "note"}
        if "cands" in prop:
            prop["cands"] = [c for c in prop["cands"] if isinstance(c, str) and not KEY_RX.search(c)]
        tgt = str(q.get("target") or "")
        queue.append({"qid": q["qid"], "code": q["code"], "kind": q.get("kind"),
                      "target": _safe_target(str(q.get("code") or ""), tgt), "impact_min": q["impact_min"],
                      "status": q["status"], "date": q.get("date"), "week": q.get("week"), "proposal": prop})
    refs_apps = {a: keep(v) for a, v in ((full.get("refs") or {}).get("apps") or {}).items()
                 if not str(a).startswith(UNKNOWN_PREFIX)}
    flags = full.get("flags") or {}
    out = {
        "schema": full.get("schema", SCHEMA), "schema_version": full.get("schema_version", SCHEMA_VERSION),
        "generator": keep(full.get("generator") or {}), "variant": "redacted", "run": keep(full.get("run") or {}),
        "flags": {"copilot": flags.get("copilot"),
                  "registry": {k: keep(v) for k, v in (flags.get("registry") or {}).items() if k in ("version",
                                                                                                    "fetched_at")},
                  "warnings": [{"code": w.get("code"), "text_ko": w.get("text_ko")} for w in flags.get("warnings", ())],
                  "label_sources": keep(flags.get("label_sources") or {}),
                  "hier": {k: (flags.get("hier") or {}).get(k) for k in ("ai_share", "unclassified_share")},
                  "mining_coarse": bool(flags.get("mining_coarse")), "trimmed": list(flags.get("trimmed") or [])},
        "denominator": keep(full.get("denominator") or {}), "domains": keep(full.get("domains") or []),
        "months": keep(full.get("months") or []), "days": keep(full.get("days") or []),
        "projects": out_projects, "roles": keep(full.get("roles") or []), "units": units,
        "tree": keep(full.get("tree") or {}),
        "workflows": {"roles": keep(wf.get("roles") or {}), "units": wunits, "projects": keep(wf.get("projects") or {}),
                      "domains": keep(wf.get("domains") or {}), "person": keep(wf.get("person") or {})},
        "reviews": reviews, "peers": peers, "ontology": o_out,
        "agentic": keep(full.get("agentic") or {}), "subagent": keep(full.get("subagent") or {}),
        "team": keep(full.get("team") or {}), "queue": queue, "quality": keep(full.get("quality") or {}),
        "tables": keep(full.get("tables") or {}),
        "refs": {"people": {str(r): {"name": res.numbered(r)} for r in sorted(
                     int(x) for x in ((full.get("refs") or {}).get("people") or {}))},
                 "docs": {str(r): {"name": f"문서 #{r}"} for r in sorted(
                     int(x) for x in ((full.get("refs") or {}).get("docs") or {}))},
                 "apps": refs_apps},
    }
    # 통째로 옮긴 절(agentic·subagent·workflows 라벨 등)의 글에도 사람 가명 토큰이 남지 않게(C13) — 없으면 걷지 않는다
    if "[사람#" in json.dumps(out, ensure_ascii=False, check_circular=False):
        out = _no_person_tokens(out)
    return out


def _app_cat(app) -> str:
    from lm27.catalog import cat_of
    a = str(app or "")
    if a.startswith(UNKNOWN_PREFIX):
        return "미상"
    return cat_of(a) or "기타"


def _app_node(nid, refs: Refs) -> str:
    return "a:" + refs.app_id(str(nid)[2:], redacted=True)


def _red_id(nid, refs: Refs) -> str:
    """전체판 노드 id(이미 'c:<k>'·'d:<k>' 로 바뀐 것) → 가림판 id: 미상 앱만 번호로."""
    s = str(nid or "")
    return _app_node(s, refs) if s.startswith("a:") else s


def _edge_label(nid, label, titles: Mapping) -> str:
    if isinstance(nid, str) and nid.startswith("u_"):
        return titles.get(nid, "단위업무")
    return str(label or "")


def _red_nodes(nodes, proj_label: Mapping, titles: Mapping, refs: Refs) -> list[dict]:
    out = []
    for n in nodes or ():
        x = {k: copy.deepcopy(v) for k, v in n.items() if k in ("id", "type", "group", "weight_min", "w", "etc", "start",
                                                               "ref")}
        t = n.get("type")
        nid = str(n.get("id", ""))
        if t == "P":
            x["label"] = proj_label.get(nid, nid)
        elif t == "R":
            x["label"] = n.get("label")
        elif t == "U":
            x["label"] = titles.get(nid, "기타" if nid.startswith("etc:") else "단위업무")
        elif t == "D":
            x["label"] = f"문서 #{n['ref']}" if n.get("ref") is not None else str(n.get("label") or "문서")
        elif t == "C":
            x["label"] = f"동료 #{n['ref']}" if n.get("ref") is not None else str(n.get("label") or "동료")
            if nid.startswith("c:ext:") or nid.startswith("etc:"):
                x["label"] = str(n.get("label") or "외부")
        elif t == "A":
            app = str(n.get("app") or "")
            x["id"] = _app_node("a:" + app, refs) if nid.startswith("a:") else nid
            x["app"] = refs.app_id(app, redacted=True) if app else ""
            x["label"] = "미상 프로그램" if app.startswith(UNKNOWN_PREFIX) else str(n.get("label") or "")
        if nid.startswith("etc:"):
            x["label"] = str(n.get("label") or "")
        out.append(x)
    return out


def _red_edges(edges, refs: Refs) -> list[dict]:
    out = []
    for e in edges or ():
        x = {k: copy.deepcopy(v) for k, v in e.items() if k in ("from", "to", "rel", "w", "h", "inferred")}
        for k in ("from", "to"):
            if str(x.get(k, "")).startswith("a:"):
                x[k] = _app_node(x[k], refs)
        out.append(x)
    return out


# ───────────────────────────── 가림판 검사(G-R8) ─────────────────────────────
def redaction_violations(model: Mapping, person_dir=None, *, extra=()) -> list[str]:
    """직렬화될 모든 글자(키 포함)에서 사람 사전 이름(한글 2자 이상·ASCII 4자 이상)·로컬 키 모양(who_key·m/e/t/h/d/r/f/s/g)·
    사람 가명 토큰 `[사람#hex]`·추가 값(시험 카나리아·가린 원래 제목)을 찾아 그 **필드 경로**만 돌려준다(값은 싣지 않는다 —
    R §11). 이름은 적힌 그대로 외에 NFKC 형과, 여러 낱말 이름이면 공백을 지운 형·그 소문자형도 찾는다 — 이름 병합 키
    (`ukey` — NFKC·소문자·공백 제거)를 거친 글이 검사를 피하지 않게(W2 검토 C14). 한 낱말 이름의 대소문자는 바꾸지 않는다
    (영역 코드 같은 대문자 어휘와 엇갈려 공유판을 막지 않게)."""
    names = person_names(person_dir)
    more = set()
    for nm in names:
        n = unicodedata.normalize("NFKC", nm)
        more.add(n)
        if " " in n:
            sq = n.replace(" ", "")
            more |= {sq, sq.casefold()}
    names = names + sorted(more - set(names), key=lambda s: (-len(s), s))
    extra = [str(x) for x in extra if str(x)]
    out: list[str] = []

    def bad(s: str) -> bool:
        return (bool(KEY_RX.search(s)) or ("[사람#" in s and bool(PERSON_TOKEN_RX.search(s)))
                or any(nm in s for nm in names) or any(x in s for x in extra))

    def walk(o, path):
        if isinstance(o, Mapping):
            for k, v in o.items():
                p = f"{path}.{k}" if path else str(k)
                if isinstance(k, str) and bad(k):
                    out.append(p + "(키)")
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
        elif isinstance(o, str) and bad(o):
            out.append(path)
    walk(model, "")
    return out
