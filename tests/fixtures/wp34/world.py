# -*- coding: utf-8 -*-
r"""WP-34 합성 자료 — 보고서 모델 전체판(R §9.2.1 · WP-31 ``report_model.json`` 모양 중 팀 묶음 빌더가 읽는 필드)과
임시 ROOT(번들 정보·키링·사람 사전·팀 레지스트리 캐시). 값은 모두 합성이다(자리표시자 홍길동·김철수·과제A, example 도메인).

    w = World()                    # %TEMP%\lm27t_wp34_*\ — TPaths(outbox_file 흉내 — 계약 C19 CR) + 번들·키링·사람 사전·캐시
    m = model()                    # 2026-08-01 ~ 09-30, 단위업무 7개(진행 중·미착수·제안·미분류·수동 포함)
    env = w.env(cfg())             # BuildEnv — 게이트 카나리아는 고정 환경(실제 PC 이름·계정을 읽지 않는다)
    w.cleanup()

정수 분 표는 시간 코어 성질을 지킨다: (날짜, 꼬리표) 칸마다 Σalloc ≤ 봉투, 단위업무 투입 = Σ alloc, 달 합 = 날짜 합.
"""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from lm27.paths import Paths
from lm27.time.calendar import Calendar
from lm27.util import fsx

TREE = Path(__file__).resolve().parents[3]
RUN_ID = "20261001-180000-a1b2"
D0, D1 = "2026-08-01", "2026-09-30"
AS_OF = "2026-09-30T18:00"
INTERNAL = "corp.example"
TAGS = ("regular", "extended", "night", "holiday")
STD = 480
_CAL: list = []


def cal() -> Calendar:
    if not _CAL:
        _CAL.append(Calendar(TREE / "config" / "calendar.json"))
    return _CAL[0]


def key(prefix: str, name: str, n: int = 16) -> str:
    return prefix + hashlib.sha256(("lm27t-wp34|" + name).encode("utf-8")).hexdigest()[:n]


def uid(n: int) -> str:
    return "u_" + hashlib.sha256(f"lm27t-wp34-unit|{n}".encode()).hexdigest()[:10]


def nid(name: str) -> str:
    return "n_" + hashlib.sha1(("lm27t-wp34-need|" + name).encode("utf-8")).hexdigest()[:6]


def role_id(scope, field, func) -> str:
    from lm27.team.schema import role_id_of
    return role_id_of(scope, field, func)


PERSON_KEY = "p_" + hashlib.sha256(b"lm27t-wp34-person").hexdigest()[:12]
PC_ID = "pc_" + hashlib.sha256(b"lm27t-wp34-pc").hexdigest()[:16]
PEPPER = hashlib.sha256(b"lm27t-wp34-pepper").hexdigest()
PEPPER_ID = hashlib.sha256(bytes.fromhex(PEPPER)).hexdigest()[:8]
KIM, PEER2, NOADDR, CUST, ME = (key("w", n) for n in ("kim", "peer2", "noaddr", "cust", "me"))
GATE_ENV = {"COMPUTERNAME": "WP34-TESTPC", "USERNAME": "tester34", "USERDOMAIN": "WORKGRP34"}
MACHINE_GUID = "0f1e2d3c-4b5a-4978-8796-a5b4c3d2e1f0"
RA = role_id("P-0007", "ELEC", "ANALYSIS")
RB = role_id("P-0007", "ELEC", "DESIGN")
RC = role_id("pr_1", "MECH", "DESIGN")
RD = role_id(None, "ETC", "ADMIN")
U = {n: uid(n) for n in range(1, 8)}

PERSON_DIR = {"format": "lm27-persondir/1", "people": {
    KIM: {"names": ["김철수", "김철수 책임"], "smtp": ["user01@" + INTERNAL], "self": False, "internal": True,
          "first": "2026-08-03", "last": "2026-09-18"},
    PEER2: {"names": ["동료 둘"], "smtp": ["user02@" + INTERNAL], "self": False, "internal": True,
            "first": "2026-08-18", "last": "2026-09-18"},
    NOADDR: {"names": ["동료 셋"], "smtp": [], "self": False, "internal": True, "first": "2026-09-01", "last": "2026-09-18"},
    CUST: {"names": ["고객 담당"], "smtp": ["buyer@cust-a.example"], "self": False, "internal": False,
           "first": "2026-08-03", "last": "2026-08-14"},
    ME: {"names": ["홍길동"], "smtp": ["me@" + INTERNAL], "self": True, "internal": True, "first": "2026-08-01",
         "last": "2026-09-30"}}}

# n, 과제, 제안, 분야, 기능, 유형, 제목, 시작일, 끝일, 상태, 등급, 시작 근거, 끝 근거, 동료(참조), 앱, 문서(참조), 하루 분
SPEC = (
    (1, "P-0007", None, "ELEC", "ANALYSIS", "DEV", "전원부 검증", "2026-08-03", "2026-08-14", "closed", "A", "S1", "E1",
     (1,), (("excel", 300), ("unknown:solverx.exe", 60)), (1, 2), 240),
    (2, "P-0007", None, "ELEC", "ANALYSIS", "DEV", "전원부 재검증", "2026-08-18", "2026-09-04", "closed", "B", "S1", "E2h",
     (1, 2), (("excel", 200), ("ansys_electronics_desktop", 100)), (2,), 180),
    (3, "P-0007", None, "ELEC", "DESIGN", "DEV", "회로 수정", "2026-09-01", "2026-09-18", "estimated", "D", "S1o", "E3i",
     (2, 3), (("kicad", 400), ("x.inhouse_tool", 50)), (3,), 200),
    (4, "P-0007", None, "ELEC", "ANALYSIS", "DEV", "열 해석", "2026-09-21", "2026-09-30", "open", "O", "S2p", None,
     (), (("excel", 30),), (), 240),
    (5, None, "pr_1", "MECH", "DESIGN", "DEV", "방열 모듈 설계", "2026-08-24", "2026-09-11", "closed", "B", "S2a", "E2h",
     (1,), (("solidworks", 300),), (4,), 120),
    (6, None, None, "ETC", "ADMIN", "OFFICE", "월간 정산", "2026-08-03", "2026-09-30", "closed", "M", "S2M", "E3M",
     (), (("excel", 30),), (), 30),
    (7, "P-0007", None, "ELEC", "ANALYSIS", "DEV", "미착수 요청", "2026-09-25", "2026-09-25", "not_started", "Z", "S1", None,
     (1,), (), (), 0),
)
LEAVE = {"2026-08-07": 1.0}
NO_EVIDENCE = {"2026-09-09"}
EXTENDED = {"2026-08-12": 60}
HOLIDAY_WORK = {"2026-08-22": (120, 2, 90)}           # 날짜 → (봉투 holiday 분, 단위업무 번호, 귀속 분)
START = {"S1": ("S1i", "minute"), "S1o": ("S1o", "minute"), "S2a": ("S2", "exact"), "S2p": ("S2", "none"),
         "S2M": ("M", "exact")}
END = {"E1": ("E1o", "minute"), "E2h": ("E2", "exact"), "E3i": ("E3i", "none"), "E3M": ("M", "exact")}


def _days(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def tables(spec=SPEC) -> tuple[dict, dict]:
    """(봉투 {날짜: {꼬리표: 분}}, 귀속 {(날짜, unit, 꼬리표): 분})."""
    c = cal()
    env, alloc = {}, defaultdict(int)
    for d in _days(date.fromisoformat(D0), date.fromisoformat(D1)):
        ds = d.isoformat()
        e = dict.fromkeys(TAGS, 0)
        if not c.is_holiday(d) and ds not in LEAVE and ds not in NO_EVIDENCE:
            e["regular"] = STD
            e["extended"] = EXTENDED.get(ds, 0)
            room = STD - 30
            for s in spec:
                n, a, b, daily = s[0], s[7], s[8], s[16]
                if daily and a <= ds <= b and room > 0:
                    take = min(daily, room)
                    alloc[(ds, uid(n), "regular")] += take
                    room -= take
            if e["extended"]:
                alloc[(ds, uid(1), "extended")] += e["extended"] - 10
        if ds in HOLIDAY_WORK:
            hm, n, am = HOLIDAY_WORK[ds]
            e["holiday"] = hm
            alloc[(ds, uid(n), "holiday")] += am
        if sum(e.values()):
            env[ds] = e
    return env, dict(alloc)


def _step(no, code, name, kind, n, med, label, by, ag, sub, why, wait=None, share=None):
    return {"no": no, "code": code, "name": name, "kind": kind, "n": n, "freq_month": 1.5, "median_min": med,
            "p75_min": med, "obs_share": None if kind == "M" else 0.8, "wait_in_median_min": wait, "work_share": share,
            "label": label, "desc": "", "label_by": by, "agent_grade": ag, "subagent": sub, "why": list(why)}


def workflows() -> dict:
    return {
        RA: {"role_id": RA, "units": [U[1], U[2], U[4]], "units_n": 3, "support_threshold": 1, "sample": "ok",
             "steps": [_step(1, "REQ_IN", "의뢰 수신", "M", 3, 0, "의뢰 수신", "rule", "하", "조건부",
                             ("digital_io", "repeat_monthly")),
                       _step(2, "APP_CAE", "해석 프로그램", "A", 3, 210, "전원 해석 수행", "ai", "중", "조건부",
                             ("digital_io", "repeat_weekly", "verifiable"), 120, 0.6),
                       _step(3, "DOC_XLS", "표 계산", "A", 3, 105, "결과 표 정리", "ai", "상", "적합",
                             ("digital_io", "structured_input", "tool_access"), 720, 0.4),
                       _step(4, "REPORT_OUT", "보고 발신", "M", 2, 0, "김철수 책임께 보고", "ai", "하", "부적합",
                             ("low_accountability", "made_up_why"), 270)],
             "edges": [[1, 2, 3], [2, 3, 3]], "edges_rest": [[3, 4, 2], [3, 2, 1]], "rework": [[3, 2, 1]],
             "bottlenecks": [{"no": 3, "kind": "wait", "value_min": 720}, {"no": 2, "kind": "work", "share": 0.6}],
             "dropped": [], "lead_biz_median_min": 2360, "effort_median_min": 455, "parallel_median": 1.0,
             "done_ratio": 0.67, "ai_role": "", "ai_summary": "", "ai_by": "rule"},
        RB: {"role_id": RB, "units": [U[3]], "units_n": 1, "support_threshold": 1, "sample": "thin",
             "steps": [_step(1, "REQ_OUT", "지시 발신", "M", 1, 0, "지시 발신", "rule", "", "조건부", ("digital_io",)),
                       _step(2, "APP_EDA", "회로 설계 도구", "A", 1, 400, "회로 설계 도구", "rule", "중", "조건부",
                             ("digital_io", "repeat_weekly"), 60, 1.0)],
             "edges": [[1, 2, 1]], "edges_rest": [], "bottlenecks": [], "dropped": []},
        RC: {"role_id": RC, "units": [U[5]], "units_n": 1, "support_threshold": 1, "sample": "thin",
             "steps": [_step(1, "APP_CAD", "설계 프로그램", "A", 1, 300, "방열판 모델링", "ai", "", "부적합",
                             ("repeat_weekly",), None, 1.0)],
             "edges": [], "edges_rest": [], "bottlenecks": [], "dropped": []},
        RD: {"role_id": RD, "units": [U[6]], "units_n": 1, "support_threshold": 1, "sample": "thin",
             "steps": [_step(1, "DOC_XLS", "표 계산", "A", 1, 30, "정산표 작성", "ai", "상", "적합",
                             ("digital_io", "structured_input"), None, 1.0)],
             "edges": [], "edges_rest": [], "bottlenecks": [], "dropped": []},
    }


def model(*, spec=SPEC) -> dict:
    """합성 보고서 모델(전체판). 단위업무 7 = 마감 A·B·추정 D·진행 중 O·제안 과제·미분류 수동 M·미착수 Z."""
    c = cal()
    env, alloc = tables(spec)
    eff = defaultdict(int)
    udays = defaultdict(set)
    by_month = defaultdict(lambda: defaultdict(int))
    by_tag = defaultdict(lambda: defaultdict(int))
    for (ds, u, t), m in alloc.items():
        eff[u] += m
        udays[u].add(ds)
        by_month[u][ds[:7]] += m
        by_tag[u][t] += m
    day_alloc = defaultdict(int)
    for (ds, _u, _t), m in alloc.items():
        day_alloc[ds] += m
    days = []
    for d in _days(date.fromisoformat(D0), date.fromisoformat(D1)):
        ds = d.isoformat()
        e = env.get(ds, dict.fromkeys(TAGS, 0))
        tot, a = sum(e.values()), day_alloc.get(ds, 0)
        est = a // 4
        days.append({"d": ds, "hol": c.is_holiday(d), "by_tag": {t: v for t, v in e.items() if v}, "env_min": tot,
                     "conf_min": {"high": tot - est, "mid": est, "low": 0}, "obs_min": a - est, "est_min": est,
                     "unattr_min": tot - a, "leave": LEAVE.get(ds, 0.0), "flags": ["Q08"] if ds == "2026-09-02" else []})
    months = []
    quality = {"2026-08": {"grade": "caution", "reasons": ["mail_cov_low"], "W": 20,
                           "cov": {"mail_in": 0.9, "mail_out": 0.7, "cal": 1.0, "teams": 0.85, "pc": 0.95},
                           "est_ratio": 0.0, "unattr_ratio": 0.2, "no_ev": 0, "sampler_ratio": 0.9},
               "2026-09": {"grade": "reliable", "reasons": [], "W": 20,
                           "cov": {"mail_in": 0.95, "mail_out": 0.9, "cal": 1.0, "teams": 0.9, "pc": 1.0},
                           "est_ratio": 0.0, "unattr_ratio": 0.2, "no_ev": 1, "sampler_ratio": 0.95}}
    for m in ("2026-08", "2026-09"):
        rows = [x for x in days if x["d"][:7] == m]
        y, mo = int(m[:4]), int(m[5:7])
        wd = c.month_workdays(y, mo)
        cov = sum(1 for x in rows if not x["hol"])
        absence = sum(v for k, v in LEAVE.items() if k[:7] == m)
        env_m = sum(x["env_min"] for x in rows)
        bt = {t: sum(env.get(x["d"], {}).get(t, 0) for x in rows) for t in TAGS}
        att = sum(x["obs_min"] + x["est_min"] for x in rows)
        months.append({"m": m, "workdays": wd, "covered_workdays": cov, "denom_days": wd, "denom_min": STD * wd,
                       "std_day_min": STD, "partial": None, "env_min": env_m, "by_tag": bt, "attributed_min": att,
                       "unattr_min": env_m - att, "buckets": {"B_GENERIC": 0, "B_COMM": 0, "B_MEET": 0, "B_OFFPC": 0,
                                                              "B_UNKNOWN": env_m - att},
                       "obs_min": sum(x["obs_min"] for x in rows), "est_min": sum(x["est_min"] for x in rows),
                       "conf_min": {"high": 0, "mid": 0, "low": 0}, "avail_days": cov - absence + 0.25,
                       "avail_min": int(STD * (cov - absence)), "absence_days": absence, "load_pct": 99.99,
                       "overtime_window_min": env_m - bt["regular"], "overtime_daily8h_min": 0, "holiday_night_min": 0,
                       "on_leave_min": 0, "machine_min": 0, "mm": env_m / (STD * wd),
                       "units": {"started": 0, "finished": 0, "continuing": 0, "unstarted": 0}, "quality": quality[m]})
    units = []
    for s in spec:
        n, proj, prop, fld, fn, wt, title, a, b, st, gr, sb, eb, peers, apps, docs, _daily = s
        u = uid(n)
        s_at = f"{a}T09:00"
        e_at = f"{b}T17:00" if eb else None
        ds = sorted(udays.get(u, ()))
        lead = None
        if st in ("closed", "estimated") and e_at:
            lead = int((datetime.fromisoformat(e_at) - datetime.fromisoformat(s_at)).total_seconds() // 60)
        spans = []
        if st != "not_started" or ds:
            last = b if eb else AS_OF[:10]
            spans = [[a, max(last, ds[-1]) if ds else last, "lead"]]
            run0 = prev = None
            for x in ds:
                xd = date.fromisoformat(x)
                if prev is not None and xd == prev + timedelta(days=1):
                    prev = xd
                    continue
                if run0 is not None:
                    spans.append([run0.isoformat(), prev.isoformat(), "active"])
                run0 = prev = xd
            if run0 is not None:
                spans.append([run0.isoformat(), prev.isoformat(), "active"])
        units.append({
            "unit_id": u, "title": title, "title_by": "ai", "role_id": role_id(proj or prop, fld, fn),
            "project_key": proj or prop or "UNC", "project_id": proj, "proposal_id": prop,
            "domain": "DEV" if (proj or prop) else "UNC", "field": fld, "function": fn, "activity_type": wt,
            "stance": "DO", "ax_link": n == 5, "label_level": "high", "kind": "S1",
            "cycles": [{"s": s_at, "sb": sb, "e": e_at, "eb": eb or "OPEN", "interim": [], "unstarted": st == "not_started",
                        "s_key": key("m", f"s{n}", 24), "e_key": key("m", f"e{n}", 24) if eb else ""}],
            "start": {"kind": START[sb][0], "at": s_at, "precision": START[sb][1]},
            "end": {"kind": END[eb][0], "at": e_at, "precision": END[eb][1]} if eb and st != "open" else None,
            "grade": gr, "status": st, "lead_min": lead, "biz_lead_min": lead, "effort_min": eff.get(u, 0),
            "obs_min": eff.get(u, 0) - eff.get(u, 0) // 4, "est_min": eff.get(u, 0) // 4, "levels_min": {},
            "parallel": 1.5, "machine_min": 0, "pre_request_min": 0, "flags": [],
            "first_evidence": a, "last_evidence": (ds[-1] if ds else a), "spans": spans, "density": {},
            "by_month": dict(by_month.get(u, {})), "by_tag": dict(by_tag.get(u, {})), "steps": [], "step_min": {},
            "peers": list(peers), "apps": [list(x) for x in apps],
            "apps_unknown_min": sum(m for x, m in apps if x.startswith("unknown:")), "docs": list(docs),
            "queue": [], "label_src": {}, "label_conf": {}, "why": ["근거 문장(전체판 전용)"]})
    refs_people = {"1": {"key": KIM, "name": "김철수", "internal": True},
                   "2": {"key": PEER2, "name": "동료 둘", "internal": True},
                   "3": {"key": NOADDR, "name": "동료 셋", "internal": None}}
    internal = []
    for r, v in refs_people.items():
        us = [x for x in units if int(r) in x["peers"]]
        internal.append({"k": int(r), "ref": int(r), "name": v["name"], "internal": v["internal"], "units": len(us),
                         "unit_ids": sorted(x["unit_id"] for x in us),
                         "shared_effort_min": sum(x["effort_min"] for x in us),
                         "roles": {"requester": 1, "reporter": 0, "thread": 0, "meeting": 0}, "projects": ["P-0007"],
                         "first": "2026-08-03", "last": "2026-09-18"})
    internal.sort(key=lambda p: (-p["shared_effort_min"], -p["units"], p["ref"]))
    env_rows = [[ds] + [env[ds][t] for t in TAGS] for ds in sorted(env)]
    order = {t: i for i, t in enumerate(TAGS)}
    alloc_rows = [[ds, u, t, m] for (ds, u, t), m in sorted(alloc.items(), key=lambda kv: (kv[0][0], kv[0][1],
                                                                                            order[kv[0][2]]))]
    from lm27.report.analysis.quality import period_quality
    pq = period_quality({m["m"]: m["quality"] for m in months})
    return {
        "schema": "lm27.report", "schema_version": "1.0", "variant": "full",
        "generator": {"app_version": "0.1.0", "report_version": "report/1", "core_version": "timecore/1.1",
                      "rules_ver": "2026.10.0", "registry_version": 3, "calendar_version": c.version,
                      "catalog_version": "ag-1", "stage_versions": {}},
        "run": {"run_id": RUN_ID, "from": D0, "to": D1, "as_of": AS_OF, "tz_offset_min": 540, "chosen": "auto"},
        "flags": {"copilot": "partial", "warnings": [], "mining_coarse": False, "missing": [], "trimmed": [],
                  "label_sources": {"task_label": {"ai": 4, "manual": 0, "rule": 3, "user": 0},
                                    "workflow_label": {"ai": 2, "manual": 1, "rule": 6}}},
        "denominator": {"basis": "workdays", "std_day_min": STD, "overtime_basis": "window", "text_ko": ""},
        "domains": [], "months": months, "days": days,
        "projects": [{"key": "P-0007", "project_id": "P-0007", "proposal_id": None, "label": "과제A", "label_src": "registry",
                      "domain": "DEV", "mask_name": False, "ax_link": False, "merged_from": [], "effort_min": 0},
                     {"key": "pr_1", "project_id": None, "proposal_id": "pr_1", "label": "방열 모듈 후속",
                      "label_src": "proposal", "domain": "DEV", "mask_name": False, "ax_link": False, "merged_from": [],
                      "effort_min": 0}],
        "proposals": [{"proposal_id": "pr_1", "kind": "project", "label": "방열 모듈 후속", "domain_guess": "DEV",
                       "status": "pending"}],
        "roles": [{"role_id": r, "project_id": p, "proposal_id": q, "field": f, "function": g}
                  for r, p, q, f, g in ((RA, "P-0007", None, "ELEC", "ANALYSIS"), (RB, "P-0007", None, "ELEC", "DESIGN"),
                                        (RC, None, "pr_1", "MECH", "DESIGN"), (RD, None, None, "ETC", "ADMIN"))],
        "units": units, "tree": {},
        "workflows": {"roles": workflows(), "units": {}, "projects": {}, "domains": {}, "person": {}},
        "reviews": {"weeks": [], "months": []},
        "peers": {"internal": internal, "others": {"n": 0, "units": 0, "shared_effort_min": 0},
                  "external": {"customer": 1, "partner": 0, "other": 0}, "unresolved": 1, "verified": True},
        "ontology": {}, "subagent": {"roles": []},
        "agentic": {"catalog_version": "ag-1", "catalog_n": 2, "items": [], "matches": [],
                    "needs": [{"need_id": nid("sheet"), "step_type": "DOC_XLS", "label": "사양 비교표 자동 작성",
                               "name": "사양 비교표 자동 작성", "grade": "중", "freq_per_month": 4.3,
                               "units": [U[1], U[2]], "by": "ai", "dropped": False},
                              {"need_id": nid("cae"), "step_type": "APP_CAE", "label": "해석 프로그램 자동화",
                               "name": "해석 프로그램 자동화", "grade": "하", "freq_per_month": 2.0, "units": [U[2]],
                               "by": "rule", "dropped": False},
                              {"need_id": nid("gone"), "step_type": "REQ_IN", "label": "의뢰 수신 자동화",
                               "name": "의뢰 수신 자동화", "grade": "하", "freq_per_month": 1.0, "units": [U[1]],
                               "by": "rule", "dropped": True}]},
        "team": {"agentic_matches": [
            {"agent_id": "AG01", "grade": "상", "role_id": RA, "step_type": "DOC_XLS", "units": [U[1], U[2], U[4]]},
            {"agent_id": "AG01", "grade": "하", "role_id": RA, "step_type": "REPORT_OUT", "units": [U[1], U[2], U[7]]},
            {"agent_id": "AG03", "grade": "중", "role_id": RB, "step_type": "APP_EDA", "units": [U[3]]},
            {"agent_id": "XX9", "grade": "중", "role_id": RB, "step_type": "APP_EDA", "units": [U[3]]}],
            "subagents": [{"role_id": RA, "fit": "조건부",
                           "chain": [{"step_no": 3, "proposal": "결과 표 정리 단계 보조"},
                                     {"step_no": 4, "proposal": "김철수 책임 보고 대행"},
                                     {"step_no": 9, "proposal": "없는 단계"}]},
                          {"role_id": RB, "fit": "부적합", "chain": []}]},
        "queue": [{"qid": "9f2c01ab3e4d", "code": "Q01", "kind": "time", "target": U[2], "impact_min": 300,
                   "status": "open", "date": "2026-08-20", "week": "2026-W34", "proposal": {},
                   "evidence_keys": [key("m", "q1", 24)], "why_ko": "[과제:P-0007] 김철수 책임 요청"},
                  {"qid": "aa11bb22cc33", "code": "H05", "kind": "hier", "target": "grp:0123456789ab", "impact_min": 60,
                   "status": "answered", "date": "2026-09-10", "week": "2026-W37", "proposal": {}, "evidence_keys": []}],
        "quality": {"grade": pq["grade"], "reasons": pq["reasons"], "by_month": pq["by_month"], "texts": []},
        "tables": {"envelope_daily": {"cols": ["date", *TAGS], "rows": env_rows},
                   "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": alloc_rows},
                   "buckets_daily": {"cols": ["date", "bucket", "tag", "min"], "rows": []}},
        "refs": {"people": refs_people,
                 "docs": {str(i): {"key": key("d", f"doc{i}"), "name": f"자료{i}.xlsx", "ext": "xlsx", "cls": "xls",
                                   "min": 60} for i in range(1, 5)},
                 "apps": {}},
    }


def registry(*, pepper: bool = True, version: int = 3) -> dict:
    """합성 팀 레지스트리 캐시(``lm27.registry/1`` — pepper 포함)."""
    reg = {"schema": "lm27.registry/1", "version": version, "updated_at": "2026-09-01T09:00:00+09:00",
           "team": {"label": "팀A"},
           "projects": [{"id": "P-0007", "name": "과제A", "domain": "DEV", "aliases": [], "keywords": [], "codenames": [],
                         "status": "active", "merged_into": None}],
           "members": [{"id": "M003", "label": "홍길동"}],
           "agents": [{"id": "AG01", "name": "표 정리 도우미", "step_types": ["DOC_XLS"]},
                      {"id": "AG03", "name": "회로 검토 도우미", "step_types": ["APP_EDA"]}],
           "internal_domains": [INTERNAL], "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["cust-a.example"]}],
           "partners": []}
    if pepper:
        reg["pepper"], reg["pepper_id"] = PEPPER, PEPPER_ID
    return reg


class TPaths(Paths):
    """시험용 Paths — ``outbox_file``(계약 v1.2 C19 — WP-00 이 W1 통합 창에서 더한다)과 저장소 원본 달력·설정 선언(읽기만)."""

    def outbox_file(self, state, name):
        return self.outbox(state) / name

    def calendar_json(self):
        return TREE / "config" / "calendar.json"

    def settings_registry(self):
        return TREE / "config" / "settings_registry.json"


def cfg(**over):
    """시험 설정 — 저장소 레지스트리 기본값(개인 config.json 은 읽지 않는다) + 덮어쓰기."""
    from lm27.config import load_config
    none = os.path.join(tempfile.gettempdir(), "lm27t_wp34_none_config.json")
    c = load_config(registry_path=str(TREE / "config" / "settings_registry.json"), config_path=none)
    return c.derive(over) if over else c


class World:
    """%TEMP% 아래 임시 ROOT — 번들 정보(person_key)·키링·사람 사전·팀 레지스트리 캐시."""

    def __init__(self, *, pepper: bool = True, with_registry: bool = True, person_dir=True, keyring: bool = True):
        from lm27 import privacy
        self.root = tempfile.mkdtemp(prefix="lm27t_wp34_")
        os.makedirs(os.path.join(self.root, "data"), exist_ok=True)
        self.paths = TPaths(self.root, lad=os.path.join(self.root, "lad"))
        fsx.atomic_write(self.paths.bundle_json(), fsx.canon_bytes(
            {"schema": "lm27.bundle/1", "bundle_id": "0" * 32, "person_key": PERSON_KEY,
             "created_at": "2026-08-01T00:00:00Z", "created_on_pc": PC_ID, "lm27_version": "0.1.0"}))
        if keyring:
            privacy.load_keyring(self.paths.data(), None, create=True, now="2026-08-01T00:00:00Z")
        if person_dir:
            pd = PERSON_DIR if person_dir is True else person_dir
            fsx.atomic_write(self.paths.local_only_file("person_dir.json"), fsx.canon_bytes(pd))
        if with_registry:
            fsx.atomic_write(self.paths.registry_cache(), fsx.canon_bytes(registry(pepper=pepper)))

    def env(self, c, period=None, **kw):
        from lm27.team.build import load_env
        args = {"period": period or {"from": D0, "to": D1}, "environ": GATE_ENV, "machine_guid": MACHINE_GUID,
                "pc_id": PC_ID}
        args.update(kw)
        return load_env(self.paths, c, **args)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def deep(o):
    return copy.deepcopy(o)


# ───────────────────────────── 번들 쪽 자료(pc.json · 정제 감사 세그먼트 · 커버리지 원장) ─────────────────────────────
INSTALL_ID = "a" * 32


def ident(pc_id: str = PC_ID):
    from lm27.bundle.ids import PcIdentity
    return PcIdentity(pc_id=pc_id, id_source="machineguid", install_id=INSTALL_ID, agent_ver="0.1.0",
                      kind_guess="desktop", tz={"utc_offset_min": 540, "windows_tz": "Korea Standard Time"})


def put_pc(paths, *, pc_id: str = PC_ID, impl: str = "py", caps=None, label_user: str = ""):
    r"""``data\pcs\<pc_id>\pc.json`` — 번들 모듈 함수로(호스트 표시명은 비운다)."""
    from lm27.bundle import pcreg
    d = pcreg.ensure_pc_dir(paths, ident(pc_id), host="", now="2026-08-01T00:00:00Z")
    pc = pcreg.load_pc(d)
    pc["installs"] = [{"install_id": INSTALL_ID, "created": "2026-08-01T00:00:00Z", "task": "", "impl": impl}]
    pc["capabilities"] = caps if caps is not None else {
        "mail.com": {"ok": True, "value": None, "reasons": [], "history": [], "verdict": "가능"},
        "teams.uia": {"ok": False, "value": None, "reasons": [], "history": [], "verdict": "불가(확정)"},
        "bundle_location": {"ok": True, "value": None, "reasons": [], "verdict": "가능"}}
    pc["label_user"] = label_user
    pcreg.save_pc(d, pc)
    return d


def put_audit(paths, rows, *, pc_id: str = PC_ID) -> None:
    """정제 감사 세그먼트(``privacy_audit``) — rows = [(ts_utc, masked{}, dropped{})]."""
    from lm27.bundle import manifest as mf
    from lm27.bundle import segment as seg
    put_pc(paths, pc_id=pc_id)
    d = paths.pc_dir(pc_id)
    m = mf.load_manifest(d)
    recs = [{"id": hashlib.sha256(f"lm27t-wp34-audit|{i}".encode()).hexdigest()[:16], "kind": "privacy_audit",
             "src": "collect", "pc_id": pc_id, "ts_utc": ts, "ev": "collect_batch", "stage": "collect",
             "path_id": "mail.com", "rules_ver": "2026.10.0", "masked": dict(mk), "dropped": dict(dr), "priv": {},
             "ad": {}, "err": {}, "rows_in": 10, "rows_out": 9} for i, (ts, mk, dr) in enumerate(rows)]
    info = seg.write_segment(d, "privacy_audit", ident(pc_id), recs, rules_ver="2026.10.0", kid="k0000000a",
                             created="2026-10-01T00:00:00Z", manifest=m)
    m["segments"].append(info)
    mf.save_manifest(d, m, now="2026-10-01T00:00:00Z")


def cell(d: str, axis: str, src: str, status: str, *, n: int = 3, n_minute: int = 3, n_date: int = 0,
         pc_id: str = PC_ID) -> dict:
    return {"account": "self", "date": d, "kind_axis": axis, "src": src, "pc_id": pc_id, "status": status, "n": n,
            "n_minute": n_minute, "n_date": n_date, "n_unknown": 0, "reasons": [], "budget_hit": False,
            "cap_hit": False, "probe_sig": "", "run_id": RUN_ID, "observed_at": "2026-10-01T00:00:00Z"}


def put_ledger(paths, cells) -> None:
    r"""커버리지 원장(파생물 ``data\derived\coverage_ledger.jsonl``) — 셀 줄들."""
    fsx.atomic_write(paths.coverage_ledger(), b"".join(fsx.canon_bytes(c) + b"\n" for c in cells))


def workdays(d0: str, d1: str) -> list[str]:
    c = cal()
    return [d.isoformat() for d in _days(date.fromisoformat(d0), date.fromisoformat(d1)) if not c.is_holiday(d)]
