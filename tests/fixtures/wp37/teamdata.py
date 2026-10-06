# -*- coding: utf-8 -*-
r"""WP-37 합성 팀 데이터(``lm27.teamdata/1`` · 계약 §3.22 · R §7.8.1 · TAB §4.9) — 시험 전용, 결정적.

    from tests.fixtures.wp37 import teamdata as T
    td, details = T.team8()             # 8명(측정 불충분 1명 · 9월 개발 비중 +8%p) — RPT-44 · RPT-45
    T.fixture_bytes()                   # tests\fixtures\wp37\team8.json 의 바이트(node 시험 자료) — 시험이 같은지 대조
    python -X utf8 -B tests\fixtures\wp37\teamdata.py --write   # team8.json 다시 쓰기(이 폴더 안에만)

취합기(``lm27\team\aggregate.py``)가 만드는 모양을 흉내 낸다 — 정수 분에서 계산해 마지막에 한 번 나눈 원값(반올림 없음).
라벨은 자리표시자(팀원A~H · 과제A~E)뿐이고 원문·실명·주소가 없다. 달력은 이 트리의 ``config\calendar.json``.
"""
from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from lm27.paths import Paths
from lm27.team import aggregate as A
from lm27.team import schema
from lm27.time.calendar import Calendar
from lm27.util import fsx

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[2]
FIXTURE = HERE / "team8.json"
MONTHS = ("2026-07", "2026-08", "2026-09")
D = 480
TAGS = ("regular", "extended", "night", "holiday")
# 비교 대상 사람의 귀속분 영역 비율(%) — 9월에 개발이 8%p 늘었다(RPT-44)
DOMAIN_SPLIT = {
    "2026-07": {"DEV": 55, "MP": 25, "EXT": 10, "COM": 10},
    "2026-08": {"DEV": 54, "MP": 26, "EXT": 10, "COM": 10},
    "2026-09": {"DEV": 62, "MP": 20, "EXT": 8, "COM": 10},
}
# 역할 키 → (과제 키, 영역, 분야, 기능, 업무 유형, 단위업무를 나누는 날)
ROLES = {
    "A": ("P-0007", "DEV", "ELEC", "DESIGN", "DEV", "2026-08-15"),
    "B": ("P-0007", "DEV", "MECH", "DESIGN", "DEV", "2026-08-10"),
    "C": ("P-0007", "DEV", "SW", "IMPL", "DEV", "2026-08-20"),
    "E": ("P-0011", "DEV", "ELEC", "DESIGN", "DEV", "2026-08-15"),
    "P": ("pr_1", "DEV", "ELEC", "DESIGN", "DEV", "2026-08-15"),
    "M": ("P-0008", "MP", "ELEC", "TEST", "FIELD", "2026-08-01"),
    "X": ("P-0009", "EXT", "MECH", "ANALYSIS", "DEV", "2026-09-01"),
    "O": ("P-0010", "COM", "ETC", "ADMIN", "OFFICE", "2026-08-05"),
}
PROJECT_LABEL = {"P-0007": "과제A", "P-0008": "과제B", "P-0009": "과제C", "P-0010": "과제D", "P-0011": "과제E"}
STD = {"MP": [("M", 1)], "EXT": [("X", 1)], "COM": [("O", 1)]}
# (라벨, 등급, 근무일당 정규 분, (연장, 야간, 휴일) 달 분, 영역 → [(역할 키, 가중)], 영역 비율 덮어쓰기)
PEOPLE = (
    ("팀원A", "reliable", 470, (600, 60, 0), {"DEV": [("A", 85), ("P", 15)], **STD}, None),
    ("팀원B", "reliable", 465, (540, 0, 120), {"DEV": [("A", 1)], **STD}, None),
    ("팀원C", "reliable", 460, (300, 0, 0), {"DEV": [("B", 95), ("E", 5)], **STD}, None),
    ("팀원D", "caution", 455, (240, 30, 0), {"DEV": [("B", 1)], **STD}, None),
    ("팀원E", "reliable", 450, (180, 0, 0), {"DEV": [("C", 1)], **STD}, None),
    ("팀원F", "reliable", 445, (120, 0, 0), {"DEV": [("C", 1)], **STD}, None),
    ("팀원G", "reliable", 440, (60, 0, 0), {"DEV": [("C", 1)], **STD}, None),
    ("팀원H", "unreliable", 200, (0, 0, 0), {"MP": [("M", 1)]}, {"MP": 100}),
)
AGENTS = {"AG003": "문서 초안 작성", "AG005": "사양 비교 도우미"}


def person_key(n: int) -> str:
    return "p_" + hashlib.sha256(f"wp37-person|{n}".encode()).hexdigest()[:12]


def unit_id(i: int, rk: str, k: int) -> str:
    return "u_" + hashlib.sha256(f"wp37-unit|{i}|{rk}|{k}".encode()).hexdigest()[:10]


def calendar() -> Calendar:
    return Calendar(Paths(TREE).calendar_json())


def largest_remainder(total: int, weights: list[tuple[str, int]]) -> dict:
    """정수 분을 가중대로 — 합 = total, 동률은 (잔여 큰 것, 키) 순."""
    s = sum(w for _k, w in weights)
    raw = {k: total * w / s for k, w in weights}
    base = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - base[k]), k))[:total - sum(base.values())]:
        base[k] += 1
    return base


def _days(m: str):
    y, mo = int(m[:4]), int(m[5:])
    d = date(y, mo, 1)
    while d.month == mo:
        yield d
        d += timedelta(days=1)


def _scope(rk: str, i: int) -> tuple[str | None, str | None, str]:
    """역할 키 → (과제 ID, 제안 ID, 과제 표 키)."""
    pk = ROLES[rk][0]
    if pk.startswith("pr_"):
        return None, pk, f"{i}|{pk}"
    return pk, None, pk


def _role_id(rk: str) -> str:
    pk, _dom, f, fn, _t, _cut = ROLES[rk]
    return schema.role_id_of(pk, f, fn)


def team8() -> tuple[dict, dict]:
    """(team_data, details) — 8명, 3개월. 사람 순서 i = 기간 MM 내림차순(취합기와 같음)."""
    cal = calendar()
    W = {m: cal.month_workdays(int(m[:4]), int(m[5:])) for m in MONTHS}
    wdays = {m: [d for d in _days(m) if not cal.is_holiday(d)] for m in MONTHS}
    people, day_min = [], {}                       # day_min[(i, rk, date)] = 분
    role_min = defaultdict(lambda: defaultdict(int))   # (i, rk) → m → 분
    for i, (label, grade, reg_wd, ot, roles, split) in enumerate(PEOPLE):
        months = []
        for m in MONTHS:
            regular = reg_wd * W[m]
            env_tag = {"regular": regular, "extended": ot[0], "night": ot[1], "holiday": ot[2]}
            env = sum(env_tag.values())
            un = env * 5 // 100
            att = env - un
            dsplit = split or DOMAIN_SPLIT[m]
            dmin = largest_remainder(att, sorted(dsplit.items()))
            for dom, mins in sorted(dmin.items()):
                for rk, v in largest_remainder(mins, roles[dom]).items():
                    role_min[(i, rk)][m] += v
                    per_day = largest_remainder(v, [(d.isoformat(), 1) for d in wdays[m]])
                    for ds, dv in per_day.items():
                        if dv:
                            day_min[(i, rk, ds)] = dv
            absence = 1.0 if (i == 1 and m == "2026-07") else 0.0
            avail = W[m] - absence
            months.append({"m": m, "mm": env / (D * W[m]), "env_min": env, "by_tag": env_tag, "attributed_min": att,
                           "unattributed_min": un, "avail_days": avail, "load_pct": env / (D * avail) * 100,
                           "partial": None, "src12": hashlib.sha256(f"{i}|{m}".encode()).hexdigest()[:12],
                           "workdays": W[m]})
        flags = ["calendar_mismatch"] if i == 2 else []
        people.append({"i": i, "person_key": person_key(i), "label": label, "label_source": "self", "member_id": None,
                       "linked": [], "quality": grade, "flags": flags, "unused_bundles": 0, "months": months})
    weak = {p["i"] for p in people if p["quality"] == "unreliable"}

    def mm_cells(cells):                           # {(i, m): 분} → (합 MM, [[i, MM]])
        by_p = defaultdict(float)
        for (i, m), v in cells.items():
            by_p[i] += v / (D * W[m])
        tot = sum(sum(v for (_i, m2), v in cells.items() if m2 == m) / (D * W[m]) for m in MONTHS
                  if any(m2 == m for (_i, m2) in cells))
        return tot, [[i, by_p[i]] for i in sorted(by_p) if by_p[i]]

    # ── 단위업무(역할마다 2개 — 나누는 날 앞·뒤) ──
    units = {}                                     # (i, rk) → [unit]
    day_units = defaultdict(set)
    for (i, rk) in sorted(role_min):
        cut = ROLES[rk][5]
        ds = sorted(d for (i2, rk2, d) in day_min if i2 == i and rk2 == rk)
        parts = ([d for d in ds if d < cut], [d for d in ds if d >= cut])
        lst = []
        for k, days in enumerate(parts):
            if not days:
                continue
            uid = unit_id(i, rk, k)
            for d in days:
                day_units[(i, d)].add(uid)
            lst.append((k, uid, days))
        units[(i, rk)] = lst
    gantt_units = {}
    for (i, rk), lst in units.items():
        out = []
        for k, uid, days in lst:
            effort = sum(day_min[(i, rk, d)] for d in days)
            dens = defaultdict(int)
            for d in days:
                dens[A.iso_week(date.fromisoformat(d))] += day_min[(i, rk, d)]
            acts = schema.active_spans([date.fromisoformat(d) for d in days], 2)
            if k == 1 and i == 0 and rk == "A":
                status, grade = "open", "C"
            elif k == 1 and i == 2:
                status, grade = "estimated", "D"
            else:
                status, grade = "closed", ("B" if k == 0 else "A")
            st, en = f"{days[0]}T09:10:00+09:00", f"{days[-1]}T17:40:00+09:00"
            lead_days = (date.fromisoformat(days[-1]) - date.fromisoformat(days[0])).days
            par = [len(day_units[(i, d)]) for d in days]
            out.append({
                "unit_id": uid, "title": f"{PROJECT_LABEL.get(ROLES[rk][0], '과제A 후속')} {rk}{k + 1} 업무",
                "spans": [[days[0], days[-1], "lead"]] + [[a.isoformat(), b.isoformat(), "active"] for a, b in acts],
                "density": dict(sorted(dens.items())), "effort_min": effort, "parallel": sum(par) / len(par),
                "grade": grade, "status": status, "start": {"kind": "S1i", "at": st},
                "end": {"kind": None if status == "open" else "E1o", "at": None if status == "open" else en},
                "lead_time_h": lead_days * 24 + 8.5, "ax_link": (i == 4 and rk == "C" and k == 1)})
        gantt_units[(i, rk)] = out

    # ── 영역·미귀속·과제·역할 ──
    dom_cells = defaultdict(lambda: defaultdict(int))
    proj_cells = defaultdict(lambda: defaultdict(int))
    role_cells = defaultdict(lambda: defaultdict(int))
    for (i, rk), byM in role_min.items():
        pid, ppid, pkey = _scope(rk, i)
        for m, v in byM.items():
            dom_cells[ROLES[rk][1]][(i, m)] += v
            proj_cells[pkey][(i, m)] += v
            role_cells[(rk, i if ppid else None)][(i, m)] += v
    domains = []
    for code in schema.DOMAINS_ALL:
        cells = dom_cells.get(code) or {}
        by_month, tot = {}, 0.0
        for m in MONTHS:
            mc = {i: v for (i, m2), v in cells.items() if m2 == m}
            if not mc:
                continue
            mm = sum(mc.values()) / (D * W[m])
            tot += mm
            by_month[m] = {"mm": mm, "by_person": [[i, mc[i] / (D * W[m])] for i in sorted(mc)]}
        domains.append({"code": code, "by_month": by_month, "total_mm": tot})
    un_by_month = {m: sum(e["unattributed_min"] for p in people for e in p["months"] if e["m"] == m) / (D * W[m])
                   for m in MONTHS}
    un_by_person = [[p["i"], sum(e["unattributed_min"] / (D * W[e["m"]]) for e in p["months"])] for p in people]
    unattributed = {"by_month": un_by_month, "total_mm": sum(un_by_month.values()), "by_person": un_by_person}

    projects = []
    for key, cells in proj_cells.items():
        tot, bp = mm_cells(cells)
        rks = sorted({rk for (_i, rk) in role_min if _scope(rk, _i)[2] == key})
        n_units = sum(len(gantt_units[(i, rk)]) for (i, rk) in role_min if _scope(rk, i)[2] == key)
        is_prop = key.endswith("|pr_1")
        projects.append({"key": key, "project_id": None if is_prop else key, "proposal_id": "pr_1" if is_prop else None,
                         "proposal": is_prop, "domain": "DEV" if key in ("P-0007", "P-0011") or is_prop else
                         ROLES[next(rk for rk in ROLES if ROLES[rk][0] == key)][1],
                         "label": "과제A 후속" if is_prop else PROJECT_LABEL[key], "reserved": False,
                         "merged": ["P-0012"] if key == "P-0007" else [], "total_mm": tot, "by_person": bp,
                         "units": n_units, "roles": len(rks)})
    projects.sort(key=lambda x: (-x["total_mm"], x["key"]))

    roles_out = []
    fit = {"A": {"적합": 1, "조건부": 1, "부적합": 0}, "C": {"적합": 0, "조건부": 2, "부적합": 1}}
    for (rk, owner), cells in role_cells.items():
        pid, ppid, pkey = _scope(rk, owner if owner is not None else 0)
        rid = _role_id(rk)
        tot, bp = mm_cells(cells)
        mine = [u for (i, rk2), lst in gantt_units.items() if rk2 == rk and (owner is None or i == owner)
                for u in lst if i not in weak]
        leads = [_biz(u, cal) for u in mine if u["status"] == "closed"]
        roles_out.append({"key": rid if owner is None else f"{rid}@{owner}", "role_id": rid, "project_id": pid,
                          "proposal": ppid is not None, "proposal_key": pkey if ppid else None,
                          "domain": ROLES[rk][1], "field": ROLES[rk][2], "function": ROLES[rk][3], "total_mm": tot,
                          "by_person": bp, "units": sum(len(gantt_units[(i, rk2)]) for (i, rk2) in gantt_units
                                                         if rk2 == rk and (owner is None or i == owner)),
                          "lead_biz_median_min": statistics.median(leads) if leads else None,
                          "effort_median_min": statistics.median([u["effort_min"] for u in mine]) if mine else None,
                          "subagent": fit.get(rk, {"적합": 0, "조건부": 0, "부적합": 0})})
    roles_out.sort(key=lambda x: (-x["total_mm"], x["key"]))

    cell_min = defaultdict(lambda: defaultdict(int))
    for (i, rk), byM in role_min.items():
        for m, v in byM.items():
            cell_min[(ROLES[rk][2], ROLES[rk][3])][(i, m)] += v
    cmp_total = sum(v for c in cell_min.values() for (i, _m), v in c.items() if i not in weak)
    cells_out = []
    for (f, fn), cells in sorted(cell_min.items()):
        tot, _bp = mm_cells(cells)
        part = sum(v for (i, _m), v in cells.items() if i not in weak)
        cells_out.append([f, fn, tot, part / cmp_total])
    role_matrix = {"fields": sorted({c[0] for c in cells_out}), "functions": sorted({c[1] for c in cells_out}),
                   "cells": cells_out}

    wt_cells = defaultdict(lambda: defaultdict(int))
    for (i, rk), byM in role_min.items():
        for m, v in byM.items():
            wt_cells[(ROLES[rk][1], ROLES[rk][4])][(i, m)] += v
    by_domain, total_t, by_person_t = defaultdict(dict), {}, defaultdict(dict)
    for (dom, t), cells in sorted(wt_cells.items()):
        tot, bp = mm_cells(cells)
        by_domain[dom][t] = tot
        total_t[t] = total_t.get(t, 0.0) + tot
        for i, v in bp:
            by_person_t[i][t] = by_person_t[i].get(t, 0.0) + v
    activity_types = {"types": list(schema.ACTIVITY_TYPES), "by_domain": dict(by_domain), "total": total_t,
                      "by_person": [[i, by_person_t[i]] for i in sorted(by_person_t)]}

    # ── 단위업무 통계(측정 불충분 제외) ──
    st_c, gr_c, lead_points, lead_by_dom = defaultdict(int), defaultdict(int), [], defaultdict(list)
    for (i, rk), lst in sorted(gantt_units.items()):
        if i in weak:
            continue
        pid, _ppid, _key = _scope(rk, i)
        for u in lst:
            st_c[u["status"]] += 1
            gr_c[u["grade"]] += 1
            if u["status"] == "closed":
                bl = _biz(u, cal)
                lead_points.append({"domain": ROLES[rk][1], "biz_lead_min": bl, "effort_min": u["effort_min"],
                                    "project_id": pid, "role_id": _role_id(rk), "i": i})
                lead_by_dom[ROLES[rk][1]].append(bl)
    lead_points.sort(key=lambda x: (x["domain"], x["i"], x["role_id"], x["biz_lead_min"]))
    units_stats = {"by_status": dict(sorted(st_c.items())), "by_grade": dict(sorted(gr_c.items())),
                   "lead_points": lead_points,
                   "lead_median_by_domain": {k: statistics.median(v) for k, v in sorted(lead_by_dom.items())}}

    # ── 간트 행·드릴다운 ──
    dom_rank = {d: k for k, d in enumerate(schema.DOMAINS_ALL)}
    proj_eff, role_eff = defaultdict(int), defaultdict(int)
    for (i, rk), lst in gantt_units.items():
        proj_eff[(i, _scope(rk, i)[2])] += sum(u["effort_min"] for u in lst)
        role_eff[(i, rk)] += sum(u["effort_min"] for u in lst)
    keys = sorted(gantt_units, key=lambda k: (k[0], dom_rank[ROLES[k[1]][1]], -proj_eff[(k[0], _scope(k[1], k[0])[2])],
                                              _scope(k[1], k[0])[2], -role_eff[k], _role_id(k[1])))
    gantt, details = [], {}
    for (i, rk) in keys:
        lst = gantt_units[(i, rk)]
        pid, ppid, _key = _scope(rk, i)
        rid = _role_id(rk)
        lead_set = set()
        for u in lst:
            a, b = date.fromisoformat(u["spans"][0][0]), date.fromisoformat(u["spans"][0][1])
            lead_set.update(a + timedelta(days=n) for n in range((b - a).days + 1))
        par = [len(day_units[(i, d)]) for (i2, rk2, d) in sorted(day_min) if i2 == i and rk2 == rk]
        row_end = {"effort_h": sum(u["effort_min"] for u in lst) / 60, "parallel": sum(par) / len(par),
                   "lead_days": len(lead_set)}
        gantt.append({"person": i, "domain": ROLES[rk][1], "project_id": pid, "proposal_id": ppid, "role_id": rid,
                      "role_key": rid if ppid is None else f"{rid}@{i}", "row_end": row_end, "units": lst})
        details[f"{i}|{rid}"] = {
            "person": {"i": i, "label": PEOPLE[i][0]},
            "role": {"role_id": rid, "project_id": pid,
                     "project_label": PROJECT_LABEL.get(pid) if pid else "과제A 후속", "domain": ROLES[rk][1],
                     "field": ROLES[rk][2], "function": ROLES[rk][3], "proposal": ppid is not None},
            "workflow": _workflow(i, rk), "units": lst,
            "agentic": {"matches": [{"agent_id": "AG003", "name": AGENTS["AG003"], "step_type": "DOC_DOC", "grade": "상"}]
                        if rk == "A" else []}}

    # ── agentic ──
    def unit_mm(keys_):
        cells = defaultdict(int)
        for (i, rk, k) in keys_:
            uid = unit_id(i, rk, k)
            for (i2, rk2, d), v in day_min.items():
                if i2 == i and rk2 == rk and uid in day_units[(i, d)]:
                    cells[d[:7]] += v
        return sum(v / (D * W[m]) for m, v in cells.items())
    m3 = [(0, "A", 0), (1, "A", 0)]
    m3_mp = [(4, "M", 0)]
    m5 = [(2, "B", 0), (0, "A", 0)]
    agentic = {
        "matches": [
            {"agent_id": "AG003", "name": AGENTS["AG003"], "people": 3, "roles": 2, "units": 3,
             "related_mm": unit_mm(m3 + m3_mp), "overlap": True,
             "by_domain": {"DEV": {"people": 2, "units": 2, "related_mm": unit_mm(m3), "best": "상"},
                           "MP": {"people": 1, "units": 1, "related_mm": unit_mm(m3_mp), "best": "중"}}},
            {"agent_id": "AG005", "name": AGENTS["AG005"], "people": 2, "roles": 2, "units": 2,
             "related_mm": unit_mm(m5), "overlap": True,
             "by_domain": {"DEV": {"people": 2, "units": 2, "related_mm": unit_mm(m5), "best": "하"}}}],
        "needs": [
            {"step_type": "COMM", "label": "주간 보고 메일 초안", "people": 3, "freq_per_month": 12.0,
             "related_mm": unit_mm([(4, "C", 0), (5, "C", 0)]), "grades": {"상": 2, "중": 1, "하": 0},
             "src": {"ai": 2, "rule": 1}},
            {"step_type": "DOC_XLS", "label": "사양 비교표 자동 작성", "people": 2, "freq_per_month": 7.0,
             "related_mm": unit_mm(m3), "grades": {"상": 1, "중": 1, "하": 0}, "src": {"ai": 1, "rule": 1}},
            {"step_type": "DOC_XLS", "label": "사양비교표 작성", "people": 1, "freq_per_month": 2.0,
             "related_mm": unit_mm([(2, "B", 0)]), "grades": {"상": 0, "중": 0, "하": 1}, "src": {"ai": 0, "rule": 1}}],
        "subagents": [
            {"field": "ELEC", "function": "DESIGN", "fit": {"적합": 1, "조건부": 1, "부적합": 0},
             "chains": [{"proposal": "결과 정리 서브에이전트", "people": 2, "step_types": ["DOC_XLS"]}]},
            {"field": "SW", "function": "IMPL", "fit": {"적합": 0, "조건부": 2, "부적합": 1}, "chains": []}],
        "related_mm_total": unit_mm(sorted(set(m3 + m3_mp + m5)))}

    matrix = []
    for p in people:
        i = p["i"]
        axes = {"mail_in": 0.97, "mail_out": 0.95, "cal": 1.0, "teams": 0.9, "pc": 1.0}
        reasons = []
        if i == 3:
            axes["teams"], reasons = 0.6, ["teams_cov_low"]
        if i == 7:
            axes.update({"pc": 0.3, "mail_out": 0.4, "teams": 0.35})
            reasons = ["pc_cov_bad", "comms_cov_bad"]
        matrix.append({"i": i, "grade": p["quality"], "reasons": reasons, "axes": axes, "pcs": 2 if i < 2 else 1,
                       "flags": list(p["flags"]), "copilot": {"used": i < 4, "failed_items": 1 if i == 0 else 0},
                       "queue": {"open": i % 3, "resolved": 5 + i}, "estimated_min_ratio": 0.05 + i / 100})

    td = {
        "schema": A.TD_SCHEMA, "gen": 12, "built_at": "2026-10-05T10:21:44+09:00", "registry_version": 7,
        "calendar_version": cal.version, "team_label": "팀A", "months": list(MONTHS), "omitted_months": 0,
        "workdays": dict(W), "std_day_min": D, "density_steps": list(A.DENSITY_STEPS),
        "people": people, "domains": domains, "projects": projects, "roles": roles_out, "role_matrix": role_matrix,
        "vocab_names": {"field": {"ELEC": "회로", "MECH": "기구"}, "func": {"DESIGN": "설계"}, "wtype": {}},
        "activity_types": activity_types, "unattributed": unattributed, "units_stats": units_stats,
        "gantt": gantt, "agentic": agentic,
        "quality": {"excluded_from_comparison": sorted(weak), "matrix": matrix},
        "interpretation": [],
        "warnings": [f"단위업무 ID 불안정 의심: {person_key(5)} — 같은 역할·같은 제목·겹치는 기간의 단위업무가 둘 이상(자동 병합 안 함)"]}
    return td, details


def _biz(u: dict, cal) -> int:
    v = A.biz_minutes(u["start"]["at"], u["end"]["at"] or u["start"]["at"], 540, cal)
    return int(v or 0)


def _workflow(i: int, rk: str) -> dict:
    """사람·역할마다 다른 워크플로우 — RPT-45: 같은 역할 두 사람(팀원A·팀원B)의 단계 라벨·n 이 다르다."""
    if rk == "A" and i == 0:
        steps = [{"no": 1, "type": "REQ_IN", "label": "요청 접수", "n": 4, "median_min": 0, "agent_grade": "중",
                  "subagent": "부적합", "why": []},
                 {"no": 2, "type": "DOC_PDF", "label": "사양서 검토", "n": 4, "median_min": 95, "agent_grade": "상",
                  "subagent": "조건부", "why": ["digital_io", "verifiable"], "wait_in_median_min": 120,
                  "work_share": 0.3, "bottleneck": ""},
                 {"no": 3, "type": "APP_EDA", "label": "회로도 수정", "n": 3, "median_min": 210, "agent_grade": "하",
                  "subagent": "부적합", "why": ["tool_access"], "wait_in_median_min": 60, "work_share": 0.55,
                  "bottleneck": "work"},
                 {"no": 4, "type": "REPORT_OUT", "label": "결과 보고", "n": 4, "median_min": 0, "agent_grade": "상",
                  "subagent": "적합", "why": ["repeat_weekly"]}]
        return {"steps": steps, "edges": [[1, 2, 4], [2, 3, 3], [3, 4, 3], [3, 2, 1]], "sample": "ok"}
    if rk == "A" and i == 1:
        steps = [{"no": 1, "type": "REQ_IN", "label": "의뢰 확인", "n": 2, "median_min": 0, "agent_grade": "중",
                  "subagent": "부적합", "why": []},
                 {"no": 2, "type": "DOC_DOC", "label": "설계 메모", "n": 2, "median_min": 140, "agent_grade": "상",
                  "subagent": "적합", "why": ["structured_input"]},
                 {"no": 3, "type": "REPORT_OUT", "label": "회신", "n": 2, "median_min": 0, "agent_grade": "중",
                  "subagent": "조건부", "why": []}]
        return {"steps": steps, "edges": [[1, 2, 2], [2, 3, 2]], "sample": "thin"}
    steps = [{"no": 1, "type": "REQ_IN", "label": "요청 접수", "n": 2, "median_min": 0, "agent_grade": "중",
              "subagent": "부적합", "why": []},
             {"no": 2, "type": "DOC_XLS", "label": "표 정리", "n": 2, "median_min": 60, "agent_grade": "상",
              "subagent": "적합", "why": ["repeat_monthly"]}]
    return {"steps": steps, "edges": [[1, 2, 2]], "sample": "thin"}


def fixture_obj() -> dict:
    td, details = team8()
    return {"td": td, "details": details}


def fixture_bytes() -> bytes:
    """node 시험 자료 바이트(정규 JSON + 줄끝 LF 하나)."""
    return fsx.canon_bytes(fixture_obj()) + b"\n"


def write_fixture() -> Path:
    """team8.json 을 다시 쓴다(이 폴더 안에만) — 생성기를 바꾼 뒤 한 번."""
    fsx.atomic_write(FIXTURE, fixture_bytes())
    return FIXTURE
