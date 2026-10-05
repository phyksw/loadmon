# -*- coding: utf-8 -*-
r"""WP-27 합성 팀 묶음 생성기(TAB §2.3 · 계약 §3.18 형식) — 시험 전용, 결정적(같은 인자 → 같은 바이트).

    from tests.fixtures.wp27.bundles import make_bundle, canon, person_key, test_cfg, new_store
    obj = make_bundle(person_key(1), "2026-07-01", "2026-07-31", built_at="2026-08-03T09:12:00+09:00")
    raw = canon(obj)

값은 모두 합성이다(자리표시자 라벨 · example 도메인만 · 사설 IP 리터럴 없음). 달력은 이 트리의 ``config\calendar.json``.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import random
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from lm27.paths import Paths
from lm27.team import schema
from lm27.time.calendar import Calendar
from lm27.util import fsx

TREE = Path(__file__).resolve().parents[3]
TAGS = schema.TAGS
_CAL = []


def calendar() -> Calendar:
    if not _CAL:
        _CAL.append(Calendar(Paths(TREE).calendar_json()))
    return _CAL[0]


def person_key(n: int) -> str:
    return "p_" + hashlib.sha256(f"wp27-person|{n}".encode()).hexdigest()[:12]


def peer_key(n: int) -> str:
    return "c_" + hashlib.sha256(f"wp27-peer|{n}".encode()).hexdigest()[:12]


def unit_id(seed, n: int) -> str:
    return "u_" + hashlib.sha256(f"wp27-unit|{seed}|{n}".encode()).hexdigest()[:10]


def need_id(step_type: str, label: str) -> str:
    return "n_" + hashlib.sha1(f"{step_type}|{label}".encode()).hexdigest()[:6]


def canon(obj) -> bytes:
    return fsx.canon_bytes(obj)


def sha(raw: bytes) -> str:
    return fsx.sha256_hex(raw)


def largest_remainder(total: int, weights: dict) -> dict:
    """정수 분 최대 잔여법 — 합 = total, 동률은 (u_ 먼저, 키) 순(계약 §5.3)."""
    s = sum(weights.values())
    if s <= 0 or total <= 0:
        return dict.fromkeys(weights, 0)
    raw = {k: total * w / s for k, w in weights.items()}
    base = {k: int(v) for k, v in raw.items()}
    left = total - sum(base.values())
    order = sorted(weights, key=lambda k: (-(raw[k] - base[k]), 0 if k.startswith("u_") else 1, k))
    for k in order[:left]:
        base[k] += 1
    return base


def _days(d0: date, d1: date):
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


def make_bundle(pk: str, d0: str, d1: str, *, built_at: str, until: str | None = None, seed=1, n_units: int = 3,
                project: str | None = "P-0007", proposal: str | None = None, domain: str = "DEV", field: str = "ELEC",
                func: str = "DESIGN", absence_days: float = 0.0, grade: str = "reliable", self_label: str = "팀원A",
                member_id: str | None = None, self_peer_key: str | None = None, pepper_id: str | None = None,
                peers=(), unit_ids=None, activity_type: str = "DEV", title: str = "전원부 검증", dense: bool = False,
                calendar_version: str | None = None, workdays_override: dict | None = None,
                agent_id: str = "AG003") -> dict:
    """유효한 팀 묶음 하나. ``until`` = 분석 끝 날짜(부분월), ``dense=True`` 면 단위업무가 매 근무일 일한다."""
    cal = calendar()
    rnd = random.Random(f"wp27|{pk}|{d0}|{d1}|{seed}")
    a, b = date.fromisoformat(d0), date.fromisoformat(d1)
    end = date.fromisoformat(until) if until else b
    uids = list(unit_ids) if unit_ids else [unit_id((pk, seed), k) for k in range(n_units)]
    scope = project if project else proposal
    rid = schema.role_id_of(scope, field, func)
    env_rows, alloc_rows = [], []
    for d in _days(a, min(end, b)):
        hol = cal.is_holiday(d)
        if hol and rnd.random() < 0.85:
            continue
        if hol:
            row = [d.isoformat(), 0, 0, 0, rnd.choice([120, 240])]
        else:
            row = [d.isoformat(), rnd.choice([420, 450, 480]), rnd.choice([0, 30, 60]), rnd.choice([0, 0, 25]), 0]
        env_rows.append(row)
        for t, mins in zip(TAGS, row[1:], strict=True):
            if not mins:
                continue
            ws = {}
            for k, u in enumerate(uids):
                if dense or rnd.random() < 0.6 or k == 0:
                    ws[u] = rnd.random() + 0.05
            ws["_un"] = rnd.random() * 0.3
            for u, v in sorted(largest_remainder(mins, ws).items()):
                if u != "_un" and v > 0:
                    alloc_rows.append([d.isoformat(), u, t, v])
    months = schema.months_between(a, b)
    units, by_unit_days = [], {}
    for _d, u, _t, mins in alloc_rows:
        by_unit_days.setdefault(u, {}).setdefault(_d, 0)
        by_unit_days[u][_d] += mins
    used = [u for u in uids if u in by_unit_days]
    for k, u in enumerate(used):
        ds = sorted(by_unit_days[u])
        first, last = ds[0], ds[-1]
        acts = schema.active_spans([date.fromisoformat(x) for x in ds], 2)
        st = f"{first}T09:10:00+09:00"
        en = f"{last}T17:40:00+09:00"
        lead_h = (datetime.fromisoformat(en) - datetime.fromisoformat(st)).total_seconds() / 3600
        units.append({
            "unit_id": u, "role_id": rid, "title": f"{title} {k + 1}", "title_mode": "label",
            "activity_type": activity_type, "ax_link": False,
            "start": {"kind": "S1i", "at": st, "precision": "exact"},
            "end": {"kind": "E1o", "at": en, "precision": "exact"},
            "grade": "B", "status": "closed", "first_evidence": first, "last_evidence": last,
            "lead_time_h": lead_h, "effort_min": sum(by_unit_days[u].values()),
            "spans": [[first, last, "lead"]] + [[x.isoformat(), y.isoformat(), "active"] for x, y in acts],
            "peers": list(peers), "apps": ["excel"], "apps_unknown_min": 0, "evidence_n": {"mail": 2, "file": 3}})
    obj = {
        "schema": schema.SCHEMA_NAME, "schema_version": "1.0",
        "generator": {"app": "LM27", "app_version": "0.1.0", "core_version": "timecore/1.1", "rules_ver": "2026.10.0",
                      "rules_hash": "4a684ebdcf99f956", "registry_version": 0,
                      "calendar_version": calendar_version or cal.version, "catalog_version": "ag-1"},
        "built_at": built_at,
        "person": {"person_key": pk, "member_id": member_id, "self_label": self_label, "self_peer_key": self_peer_key,
                   "pepper_id": pepper_id, "field": field, "work_tz_offset_min": 540,
                   "peer_scope": "team" if pepper_id else "personal"},
        "period": {"from": d0, "to": d1, "analyzed_until": f"{min(end, b).isoformat()}T23:59:59+09:00", "months": months},
        "summary": {"std_day_min": 480, "months": []},
        "envelope_daily": {"cols": ["date", *TAGS], "rows": env_rows},
        "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": alloc_rows},
        "projects": [{"project_id": project, "domain": domain}] if project else [],
        "proposals": [{"proposal_id": proposal, "kind": "project", "label": "과제A 후속", "domain_guess": domain}]
        if proposal else [],
        "roles": [{"role_id": rid, "project_id": project, "proposal_id": None if project else proposal,
                   "field": field, "function": func}],
        "units": units,
        "workflows": [{"role_id": rid, "units": [u["unit_id"] for u in units],
                       "steps": [{"no": 1, "type": "REQ_IN", "label": "요청 접수", "n": 3, "median_min": 20,
                                  "agent_grade": "상", "subagent": "적합", "why": ["digital_io"]},
                                 {"no": 2, "type": "DOC_XLS", "label": "표 정리", "n": 3, "median_min": 60,
                                  "agent_grade": "중", "subagent": "조건부", "why": ["repeat_weekly", "tool_access"],
                                  "wait_in_median_min": 30, "work_share": 0.5, "bottleneck": "", "sample": "thin"}],
                       "edges": [[1, 2, 3]]}] if units else [],
        "agentic": {"catalog_version": "ag-1",
                    "matches": [{"agent_id": agent_id, "role_id": rid, "step_type": "DOC_XLS", "grade": "상",
                                 "units": [units[0]["unit_id"]]}] if units else [],
                    "needs": [{"need_id": need_id("DOC_XLS", "사양 비교표 자동 작성"), "step_type": "DOC_XLS",
                               "label": "사양 비교표 자동 작성", "grade": "중", "freq_per_month": 2.0,
                               "units": [units[0]["unit_id"]], "src": "rule"}] if units else [],
                    "subagents": [{"role_id": rid, "fit": "조건부",
                                   "chain": [{"step_no": 2, "proposal": "결과 정리 서브에이전트"}]}] if units else []},
        "peers": [{"peer_key": p, "scope": "team" if pepper_id else "personal", "units": 1, "shared_effort_min": 60}
                  for p in peers],
        "peers_external": {"customer": 1, "partner": 0, "other": 0},
        "privacy_counts": {"phone": 1, "person": 3},
        "catalog_proposals": [],
        "quality": {"grade": grade, "reasons": [],
                    "pcs": [{"ord": 1, "label_auto": "PC1", "kind": "desktop", "agent_impl": "py",
                             "observed_days": 10, "event_days": 10, "stuck_days": 0, "probe": {"mail.com": "가능"}}],
                    "coverage": [{"axis": "mail_out", "days": {"ok": 18, "zero_ok": 2, "partial": 0},
                                  "srcs": ["mail.com", "mail.index"], "exact_ratio": 0.9}],
                    "days": {"weekdays": 20, "no_evidence_weekdays": 0, "long_days_16h": 0, "anomaly_days": 0},
                    "confirm_queue": {"open": 0, "resolved": 1}, "estimated_min_ratio": 0.05,
                    "team_text_rejected": 0, "copilot": {"used": False, "items": 0, "failed_items": 0}},
        "integrity": {},
    }
    finalize(obj, absence_days=absence_days, workdays_override=workdays_override)
    return obj


def finalize(obj: dict, *, absence_days: float = 0.0, workdays_override: dict | None = None) -> dict:
    """요약(summary.months)·integrity 를 일자 표에서 다시 계산한다(시험이 표를 고친 뒤 부른다)."""
    cal = calendar()
    a, b = date.fromisoformat(obj["period"]["from"]), date.fromisoformat(obj["period"]["to"])
    end = datetime.fromisoformat(obj["period"]["analyzed_until"]).date()
    old = {m.get("month"): m for m in obj["summary"].get("months") or ()}
    months = []
    for k, m in enumerate(obj["period"]["months"]):
        y, mo = int(m[:4]), int(m[5:])
        wd = (workdays_override or {}).get(m, cal.month_workdays(y, mo))
        first = date(y, mo, 1)
        last = (date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)) - timedelta(days=1)
        lo, hi = max(a, first), min(end, b, last)
        cov = sum(1 for d in _days(lo, hi) if not cal.is_holiday(d)) if lo <= hi else 0
        absn = old.get(m, {}).get("absence_days", absence_days if k == 0 else 0.0)
        bt = dict.fromkeys(TAGS, 0)
        for r in obj["envelope_daily"]["rows"]:
            if r[0][:7] == m:
                for t, v in zip(TAGS, r[1:], strict=True):
                    bt[t] += v
        e = sum(bt.values())
        at = sum(r[3] for r in obj["alloc_daily"]["rows"] if r[0][:7] == m)
        avail = cov - absn
        months.append({"month": m, "workdays": wd, "covered_workdays": cov, "absence_days": absn, "avail_days": avail,
                       "envelope_min": e, "by_tag": bt, "attributed_min": at, "unattributed_min": e - at,
                       "mm": e / (480 * wd), "load_pct": e / (480 * avail) * 100 if avail > 0 else None})
    obj["summary"] = {"std_day_min": 480, "months": months}
    env = sum(sum(r[1:]) for r in obj["envelope_daily"]["rows"])
    al = sum(r[3] for r in obj["alloc_daily"]["rows"])
    obj["integrity"] = {"envelope_min": env, "alloc_min": al, "unattributed_min": env - al,
                        "rows_env": len(obj["envelope_daily"]["rows"]), "rows_alloc": len(obj["alloc_daily"]["rows"]),
                        "units": len(obj["units"])}
    for u in obj["units"]:
        u["effort_min"] = sum(r[3] for r in obj["alloc_daily"]["rows"] if r[1] == u["unit_id"])
        ds = sorted({date.fromisoformat(r[0]) for r in obj["alloc_daily"]["rows"] if r[1] == u["unit_id"]})
        if ds:
            lead = [s for s in u["spans"] if s[2] == "lead"][:1] or [[ds[0].isoformat(), ds[-1].isoformat(), "lead"]]
            u["spans"] = lead + [[x.isoformat(), y.isoformat(), "active"] for x, y in schema.active_spans(ds, 2)]
    return obj


def registry(version: int = 1, *, projects=None, members=None, agents=None, calendar_obj=None) -> dict:
    """합성 팀 레지스트리(lm27.registry/1) — 자리표시자 과제A·홍길동만."""
    reg = {"schema": "lm27.registry/1", "version": version, "updated_at": "2026-10-05T09:00:00+09:00",
           "team": {"label": "팀A"}, "domains": list(schema.DOMAINS_ALL),
           "projects": projects if projects is not None else [
               {"id": "P-0007", "name": "과제A", "domain": "DEV", "aliases": [], "keywords": [], "codenames": [],
                "status": "active", "merged_into": None}],
           "members": members if members is not None else [{"id": "M003", "label": "홍길동"}],
           "vocab": {}, "agents": agents if agents is not None else [{"id": "AG003", "name": "문서 초안 작성"}],
           "internal_domains": ["example.com"], "customers": [], "partners": []}
    if calendar_obj is not None:
        reg["calendar"] = calendar_obj
    return reg


# ── 저장소·설정 ────────────────────────────────────────────────────────────
def test_cfg(store_dir, **over):
    """이 트리 레지스트리 기본값 + 저장소 경로(임시 폴더) 덮어쓰기."""
    from lm27.config import load_config
    ov = {"teamServer.storeDir": str(store_dir)}
    ov.update(over)
    return load_config(Paths(TREE), overrides=ov)


def pass_check(_obj):
    """정제 재검사 가짜(통과) — 카나리아·금지 값 판정은 WP-11 실물로 통합 창에서 다시 돈다."""
    return []


@contextlib.contextmanager
def temp_dir(prefix="lm27t_wp27_"):
    d = tempfile.mkdtemp(prefix=prefix)
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def new_store(root, *, validator=None, **over):
    """임시 폴더에 저장소를 연다(정제 재검사 = 통과 가짜, 레지스트리 의미 검증 = 주입)."""
    from lm27.team.store import open_store
    cfg = test_cfg(root, **over)
    return open_store(cfg, payload_check=pass_check, registry_validator=validator or (lambda _o, side: []),
                      paths=Paths(TREE))


def put_bundle(store, obj, **kw):
    from lm27.team.store import ingest_bytes
    raw = canon(obj)
    return ingest_bytes(store, raw, source=kw.pop("source", "http"), claimed_sha=kw.pop("claimed_sha", sha(raw)), **kw)


def ensure_parent(p) -> None:
    os.makedirs(os.path.dirname(os.fspath(p)), exist_ok=True)
