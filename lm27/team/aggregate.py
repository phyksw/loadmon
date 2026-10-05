# -*- coding: utf-8 -*-
r"""팀 취합(TAB §4 · R §7.8 · 계약 §3.22) — 현재 묶음들 → ``out\gen_N\{team_data.json, details.json, result.json}``.

    res = aggregate(store, gen)        # 서버 하위 프로세스(lm27 team-aggregate --store D --gen N) · 반입 CLI 가 부른다

산식 요지(TAB §4)
  · 사람 = 연결된 person_key 묶음(roster.links · 같은 member_id · 같은 self_peer_key + 서버 pepper_id).
  · 사람·달마다 **묶음 하나**(더 많이 덮는 묶음 → 나중 빌드(UTC) → sha 큰 쪽). 다른 묶음의 같은 달을 섞지 않는다.
  · 모든 합은 **정수 분**, MM·비율은 마지막에 한 번 나눈다. 분모 = 서버 달력 ``std_day_min × W(m)``(근무일).
    **반올림하지 않은 원값**을 싣는다(반올림은 표시 때만 — 계약 §3.22).
  · 측정 불충분(unreliable) 사람은 합계에 넣고(빗금은 화면), 분포·비교(``quality.excluded_from_comparison``)에서 뺀다.
  · 불변식 I1~I7 위반은 ``warnings`` 에 남기고 산출은 계속한다(TAB §4.8). 한 묶음·한 사람이 깨져도 나머지는 계속.
  · 산출 문서: ``team_data.json``(사람은 정수 i 로만 참조) · ``details.json``(키 ``"<i>|<role_id>"`` — ``/api/team/detail``
    과 자기완결 보고서 데이터 섬) · 보고서 HTML 은 ``lm27.team.report``(WP-37)가 있으면 그것으로 · 마지막에 ``result.json``.
"""
from __future__ import annotations

import importlib
import importlib.util
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from lm27.team import schema
from lm27.team.store import display_label
from lm27.util import fsx

TD_SCHEMA = "lm27.teamdata/1"
GANTT_MAX_MONTHS = 24
DENSITY_STEPS = (0, 120, 360, 720, 1200)             # 주당 분 — 고정 5단계(TAB §4.6), 화면이 쓴다
GRADE_ORDER = {"unreliable": 2, "caution": 1, "reliable": 0}
CFG_SIG_KEYS = ("core_version", "rules_ver", "calendar_version", "registry_version")


@dataclass
class AggResult:
    ok: bool
    rc: int
    gen: int
    members: int = 0
    warnings: list = field(default_factory=list)
    sec: float = 0.0
    td: dict | None = None
    details: dict | None = None

    def as_result_json(self) -> dict:
        return {"ok": self.ok, "gen": self.gen, "members": self.members, "warnings": list(self.warnings)[:200],
                "sec": self.sec}


@dataclass
class Person:
    key: str
    keys: list = field(default_factory=list)
    bundles: dict = field(default_factory=dict)       # sha → 묶음 객체
    entries: dict = field(default_factory=dict)       # sha → current.json 항목


# ───────────────────────────── 읽기 ─────────────────────────────
def read_v1(raw: bytes) -> dict:
    """주판 1 읽기 — 저장 때 검증을 통과한 바이트다. 구조만 다시 확인(깨졌으면 ValueError)."""
    obj = schema.loads_bundle(raw)
    if not isinstance(obj, dict):
        raise ValueError("not_object")
    for k in ("person", "period", "summary", "envelope_daily", "alloc_daily", "units", "roles", "built_at"):
        if k not in obj:
            raise ValueError("missing:" + k)
    return obj


READERS = {1: read_v1}


def load_people(store, warnings: list) -> dict[str, Person]:
    """사람 폴더(``^p_[0-9a-f]{12}$``)마다 현재 묶음 — 묶음·사람 단위로 격리(하나가 깨져도 나머지 계속)."""
    out: dict[str, Person] = {}
    for pk in store.member_keys():
        try:
            cur = store.read_current(pk, warnings)
        except (OSError, ValueError) as e:
            warnings.append(f"{pk}: 색인을 읽지 못해 이 사람을 뺐습니다({type(e).__name__})")
            continue
        p = Person(pk, [pk])
        for per, ent in sorted(cur.items()):
            try:
                raw = store.bundle_bytes(pk, ent.get("file", ""))
            except (OSError, ValueError) as e:
                warnings.append(f"{pk} {per}: 저장 묶음을 읽지 못해 제외({type(e).__name__})")
                continue
            if fsx.sha256_hex(raw) != ent.get("sha256"):
                warnings.append(f"{pk} {per}: 저장본 sha 불일치 — 이 묶음 제외")
                continue
            try:
                obj = READERS[schema.major_of(raw)](raw)
            except Exception as e:                       # 한 묶음 때문에 팀 취합을 잃지 않는다(TAB §4.2)
                warnings.append(f"{pk} {per}: 해석 실패({type(e).__name__}) — 이 묶음 제외")
                continue
            p.bundles[ent["sha256"]] = obj
            p.entries[ent["sha256"]] = ent
        if p.bundles:
            out[pk] = p
    return out


def _first_received(p: Person) -> str:
    return min((e.get("received_at") or "9999" for e in p.entries.values()), default="9999")


def merge_links(by_key: dict[str, Person], roster: dict, pepper_id: str | None) -> dict[str, Person]:
    """roster.links · 같은 member_id · 같은 self_peer_key(같은 pepper_id 일 때만) → 대표 키(가장 먼저 받은 키)."""
    parent = {k: k for k in by_key}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    for a, b in (roster.get("links") or {}).items():
        union(a, b)
    mid_of, spk_of = defaultdict(list), defaultdict(list)
    for k, p in by_key.items():
        mid = (roster.get("member_of") or {}).get(k)
        for b in p.bundles.values():
            pe = b.get("person") or {}
            mid = mid or pe.get("member_id")
            if pe.get("self_peer_key") and pepper_id and pe.get("pepper_id") == pepper_id:
                spk_of[pe["self_peer_key"]].append(k)
        if mid:
            mid_of[mid].append(k)
    for grp in list(mid_of.values()) + list(spk_of.values()):
        for k in grp[1:]:
            union(grp[0], k)
    groups = defaultdict(list)
    for k in by_key:
        groups[find(k)].append(k)
    out = {}
    for ks in groups.values():
        ks.sort(key=lambda k: (_first_received(by_key[k]), k))
        rep = Person(ks[0], ks)
        for k in ks:
            rep.bundles.update(by_key[k].bundles)
            rep.entries.update(by_key[k].entries)
        out[ks[0]] = rep
    return out


# ───────────────────────────── 달력 ─────────────────────────────
def _month_bounds(m: str) -> tuple[date, date]:
    y, mo = int(m[:4]), int(m[5:7])
    first = date(y, mo, 1)
    nxt = date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)
    return first, nxt - timedelta(days=1)


def _workdays_in(cal, lo: date, hi: date) -> int:
    return cal.wd_between(lo - timedelta(days=1), hi) if lo <= hi else 0


def covered_workdays(b: dict, m: str, cal) -> int:
    """그 묶음이 그 달을 덮는 근무일(서버 달력) — [max(from, 월초), min(분석 끝 날짜, to, 월말)]."""
    per = b["period"]
    first, last = _month_bounds(m)
    au = schema.parse_dt(per.get("analyzed_until"))
    lo = max(date.fromisoformat(per["from"]), first)
    hi = min(au.date() if au else date.fromisoformat(per["to"]), date.fromisoformat(per["to"]), last)
    return _workdays_in(cal, lo, hi)


def _built_utc(b: dict) -> datetime:
    d = schema.parse_dt(b.get("built_at"))
    return d.astimezone(UTC) if d else datetime(1970, 1, 1, tzinfo=UTC)


def pick_month_sources(bundles: dict, cal=None, warnings: list | None = None) -> dict[str, str]:
    """m → sha: 그 달을 더 많이 덮는 묶음 → 나중 빌드(UTC) → sha 큰 쪽(결정적, TAB §4.3).
    ``cal`` 이 없으면 이 프로그램의 내장 달력(서버 달력은 호출자가 넘긴다)."""
    if cal is None:
        from lm27.paths import Paths
        from lm27.time.calendar import load_calendar
        cal = load_calendar(Paths(), None)
    cand = defaultdict(list)
    for sha, b in bundles.items():
        au = schema.parse_dt(b["period"].get("analyzed_until"))
        for m in b["period"].get("months") or ():
            if au is not None and _month_bounds(m)[0] > au.date():
                continue                                 # 분석 끝 뒤의 달 = 자료 없음(0 이 아니다, TAB §4.4)
            cand[m].append(sha)
    out = {}
    for m, shas in sorted(cand.items()):
        def key(h, m=m):
            try:
                cov = covered_workdays(bundles[h], m, cal)
            except ValueError:                          # 달력 미확인 연도 — 묶음 요약 값으로
                cov = _summary_month(bundles[h], m).get("covered_workdays") or 0
            return (cov, _built_utc(bundles[h]), h)
        out[m] = max(shas, key=key)
    return out


def _summary_month(b: dict, m: str) -> dict:
    for s in (b.get("summary") or {}).get("months") or ():
        if isinstance(s, dict) and s.get("month") == m:
            return s
    return {}


def resolve_project(reg, pid: str | None, votes: dict | None = None) -> str | None:
    """레지스트리 ``merged_into`` 사슬을 끝까지(TAB §3.10). 순환이면 사슬 안에서 묶음 수(votes)가 가장 많은 ID,
    동률은 사전순(LM24 resolve_chain 계승). 레지스트리에 없거나 None 이면 그대로."""
    if pid is None or not isinstance(reg, dict):
        return pid
    proj = {x.get("id"): x for x in reg.get("projects") or () if isinstance(x, dict)}
    seen, order, cur = set(), [], pid
    while cur in proj and cur not in seen:
        seen.add(cur)
        order.append(cur)
        nxt = proj[cur].get("merged_into")
        if nxt in (None, "") or nxt not in proj:
            return cur
        cur = nxt
    if cur in seen:                                    # 순환
        cyc = order[order.index(cur):]
        votes = votes or {}
        return sorted(cyc, key=lambda x: (-votes.get(x, 0), x))[0]
    return cur


# ───────────────────────────── 영업 리드 ─────────────────────────────
def _hm(s: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        a, b = s.split("-")
        return int(a[:2]) * 60 + int(a[3:5]), int(b[:2]) * 60 + int(b[3:5])
    except (AttributeError, ValueError, IndexError):
        return default


def biz_minutes(start_at, end_at, off_min: int, cal, std=(540, 1080), lunch=(720, 780)) -> int | None:
    """[시작, 끝] 안 정규 구역(근무일 표준창 − 점심) 분(W §1 '영업 리드'). 근무 시간대 오프셋 기준. 못 구하면 None."""
    a, b = schema.parse_dt(start_at), schema.parse_dt(end_at)
    if a is None or b is None or b < a:
        return None
    from datetime import timezone
    tz = timezone(timedelta(minutes=off_min))
    a, b = a.astimezone(tz), b.astimezone(tz)
    total = 0
    d = a.date()
    while d <= b.date():
        try:
            off = cal.is_holiday(d)
        except ValueError:
            return None
        if not off:
            day0 = datetime(d.year, d.month, d.day, tzinfo=tz)
            for s, e, sign in ((std[0], std[1], 1), (lunch[0], lunch[1], -1)):
                lo, hi = max(a, day0 + timedelta(minutes=s)), min(b, day0 + timedelta(minutes=e))
                if hi > lo:
                    total += sign * int((hi - lo).total_seconds() // 60)
        d += timedelta(days=1)
    return max(total, 0)


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y:04d}-W{w:02d}"


# ───────────────────────────── 취합 본체 ─────────────────────────────
class _Acc:
    """정수 분 누적기 — 키별 분 합."""

    def __init__(self):
        self.v = defaultdict(int)

    def add(self, k, n):
        self.v[k] += n


def _worst_grade(grades) -> str:
    gs = [g for g in grades if g in GRADE_ORDER]
    return max(gs, key=lambda g: GRADE_ORDER[g]) if gs else ""


def _cfg_mismatch(sigs: dict[str, tuple]) -> set[str]:
    """산식 설정 서명이 팀 '과반' 과 다른 사람(2명 미만·동수면 아무도 표시하지 않음 — LM24 cfg_mismatch 계승)."""
    if len(sigs) < 2:
        return set()
    votes = defaultdict(int)
    for s in sigs.values():
        votes[s] += 1
    top, n = max(votes.items(), key=lambda kv: (kv[1], kv[0]))
    if n * 2 <= len(sigs) or list(votes.values()).count(n) > 1:
        return set()
    return {k for k, s in sigs.items() if s != top}


def _resolve_ukey(ukey, warnings):
    from lm27.team.store import resolve_ukey
    fn, w = resolve_ukey(ukey)
    if w:
        warnings.append(w)
    return fn


def _mm(mins: int, denom: int) -> float:
    return mins / denom if denom else 0.0


def build_team_data(store, people: dict[str, Person], cal, gen: int, *, ukey=None, now=None,
                    warnings: list | None = None) -> tuple[dict, dict]:
    """사람 묶음 → (team_data, details). 반올림 없음(원값)."""
    warnings = warnings if warnings is not None else []
    reg = store.registry() or {}
    roster = store.roster()
    reg_proj = {x.get("id"): x for x in reg.get("projects") or () if isinstance(x, dict)}
    reg_labels = {m.get("id"): m.get("label") for m in reg.get("members") or () if isinstance(m, dict)}
    agent_names = {a.get("id"): a.get("name") for a in reg.get("agents") or () if isinstance(a, dict)}
    gap = store.c("teamServer.ganttMergeGapDays")
    std_win = _hm(store.c("time.window.std"), (540, 1080))
    lunch_win = _hm(store.c("time.window.lunch"), (720, 780))
    D = cal.std_day_min
    ukey_fn = None

    # ── 사람·달 출처 선택, 달 창 ──
    picks = {pk: pick_month_sources(p.bundles, cal, warnings) for pk, p in people.items()}
    all_months = sorted({m for pk in picks for m in picks[pk]})
    omitted = max(0, len(all_months) - GANTT_MAX_MONTHS)
    months = all_months[omitted:]
    W = {}
    for m in months:
        try:
            W[m] = cal.month_workdays(int(m[:4]), int(m[5:7]))
        except ValueError:
            W[m] = None
            warnings.append(f"{m}: 서버 달력에 없는 해(달력 미확인 연도) — 묶음의 근무일로 계산")
    cal_ver = cal.version

    # ── 사람별 월 수치·단위업무 수집 ──
    P = {}                                            # pk → 계산 결과
    project_votes = defaultdict(int)
    for p in people.values():
        for b in p.bundles.values():
            for r in b.get("roles") or ():
                if r.get("project_id"):
                    project_votes[r["project_id"]] += 1
    for pk, p in sorted(people.items()):
        rec = {"months": {}, "units": {}, "roles": {}, "flags": set(), "grades": [], "self_label": "", "member_id": None,
               "minutes_by": defaultdict(_Acc), "used": set(), "day_units": defaultdict(set)}
        latest = max(p.bundles.values(), key=_built_utc)
        pe = latest.get("person") or {}
        rec["self_label"] = pe.get("self_label") or ""
        rec["member_id"] = (roster.get("member_of") or {}).get(pk) or next(
            (b["person"].get("member_id") for b in p.bundles.values() if b["person"].get("member_id")), None)
        rec["off"] = pe.get("work_tz_offset_min") if isinstance(pe.get("work_tz_offset_min"), int) else 540
        for m in months:
            sha = picks[pk].get(m)
            if sha is None:
                continue
            b = p.bundles[sha]
            rec["used"].add(sha)
            env_tag = dict.fromkeys(schema.TAGS, 0)
            for row in b["envelope_daily"]["rows"]:
                if row[0][:7] == m:
                    for t, v in zip(schema.TAGS, row[1:], strict=True):
                        env_tag[t] += v
            E = sum(env_tag.values())
            A = 0
            for d, uid, _tag, mins in b["alloc_daily"]["rows"]:
                if d[:7] != m:
                    continue
                A += mins
                u = rec["units"].setdefault(uid, {"days": defaultdict(int), "src": {}})
                u["days"][d] += mins
                u["src"][m] = sha
                rec["day_units"][d].add(uid)
            sm = _summary_month(b, m)
            Wm = W[m] if W[m] is not None else sm.get("workdays")
            try:
                cov = covered_workdays(b, m, cal)
            except ValueError:
                cov = sm.get("covered_workdays") or 0
            absence = sm.get("absence_days") or 0
            avail = cov - absence
            mm = _mm(E, D * Wm) if Wm else 0.0
            ent = {"m": m, "mm": mm, "env_min": E, "by_tag": env_tag, "attributed_min": A, "unattributed_min": E - A,
                   "avail_days": avail, "load_pct": (E / (D * avail) * 100) if avail > 0 and D else None,
                   "partial": {"covered_workdays": cov, "workdays": Wm} if Wm and cov < Wm else None,
                   "src12": sha[:12], "workdays": Wm}
            bmm = sm.get("mm")
            if isinstance(bmm, (int, float)) and abs(bmm - mm) > 1e-9:
                if (b.get("generator") or {}).get("calendar_version") != cal_ver:
                    rec["flags"].add("calendar_mismatch")
                    ent["mm_bundle"] = bmm
                else:
                    warnings.append(f"I2 개인=팀 불일치: {pk} {m}")
                    ent["mm_bundle"] = bmm
            rec["months"][m] = ent
        for sha in rec["used"]:
            b = p.bundles[sha]
            rec["grades"].append((b.get("quality") or {}).get("grade") or "")
            if b["person"].get("pepper_id") and b["person"]["pepper_id"] != store.pepper_id:
                rec["flags"].add("pepper_mismatch")
            if (b.get("generator") or {}).get("calendar_version") not in (None, cal_ver):
                rec["flags"].add("calendar_mismatch")
            for s in (b.get("summary") or {}).get("months") or ():
                if s.get("month") in W and W[s["month"]] is not None and s.get("workdays") != W[s["month"]]:
                    rec["flags"].add("calendar_mismatch")
        if pk in set(roster.get("retired") or ()):
            rec["flags"].add("retired")
        unused = [p.entries[s] for s in p.bundles if s not in rec["used"]]
        if unused:
            rec["unused"] = len(unused)
        P[pk] = rec

    # 산식 설정 상이(과반 규칙)
    sigs = {}
    for pk, p in people.items():
        latest = max(p.bundles.values(), key=_built_utc)
        g = latest.get("generator") or {}
        sigs[pk] = tuple(str(g.get(k)) for k in CFG_SIG_KEYS)
    for pk in _cfg_mismatch(sigs):
        P[pk]["flags"].add("cfg_mismatch")

    # ── 사람 순서(i) = 기간 MM 내림차순 → person_key ──
    order = sorted(P, key=lambda k: (-sum(e["mm"] for e in P[k]["months"].values()), k))
    idx = {pk: i for i, pk in enumerate(order)}
    grade_of = {pk: _worst_grade(P[pk]["grades"]) for pk in order}
    excluded = [idx[pk] for pk in order if grade_of[pk] == "unreliable"]
    excl_set = set(excluded)

    # ── 단위업무 메타(가장 늦은 달 묶음 값) · 역할·과제 해석 ──
    UN = {}                                           # (pk, uid) → 단위업무 정리
    role_keys = {}
    for pk in order:
        p, rec = people[pk], P[pk]
        for uid, u in rec["units"].items():
            last_m = max(u["src"])
            b = p.bundles[u["src"][last_m]]
            meta = next((x for x in b["units"] if x.get("unit_id") == uid), None)
            if meta is None:
                continue
            role = next((r for r in b["roles"] if r.get("role_id") == meta.get("role_id")), {})
            props = {x.get("proposal_id"): x for x in b.get("proposals") or ()}
            bproj = {x.get("project_id"): x for x in b.get("projects") or ()}
            pid0, ppid = role.get("project_id"), role.get("proposal_id")
            if pid0:
                pid = resolve_project(reg, pid0, project_votes)
                if pid in reg_proj:
                    dom = reg_proj[pid].get("domain")
                elif pid in schema.RESERVED_PROJECTS:
                    dom = schema.RESERVED_PROJECTS[pid]
                else:
                    dom = (bproj.get(pid0) or {}).get("domain")
                proj_key, proposal = pid, False
            elif ppid:
                dom = (props.get(ppid) or {}).get("domain_guess") or "UNC"
                proj_key, proposal, pid = f"{idx[pk]}|{ppid}", True, None
            else:
                dom, proj_key, proposal, pid = "UNC", "UNC", False, None
            dom = dom if dom in schema.DOMAINS_ALL else "UNC"
            triple = (pid0 or ppid or "UNC", role.get("field") or "", role.get("function") or "")
            rid = meta.get("role_id")
            base = rid if not proposal else f"{rid}@{idx[pk]}"
            if (base, triple) not in role_keys:                   # R-8: 24비트 충돌이면 경고 후 따로 센다
                n = sum(1 for b0, _t in role_keys if b0 == base)
                if n:
                    warnings.append(f"role_id_collision: {rid} — 다른 (과제·분야·기능)이 같은 역할 ID, 따로 셉니다")
                role_keys[(base, triple)] = base if not n else f"{base}#{n}"
            rkey = role_keys[(base, triple)]
            # lead 띠: 이 단위업무가 나온 모든 선택 묶음의 lead 합집합(가장 이른 시작 ~ 가장 늦은 끝)
            leads = []
            for sha in set(u["src"].values()):
                mu = next((x for x in p.bundles[sha]["units"] if x.get("unit_id") == uid), None)
                for s in (mu or {}).get("spans") or ():
                    if s[2] == "lead":
                        leads.append((s[0], s[1]))
            days = sorted(date.fromisoformat(d) for d in u["days"])
            lead = (min(x[0] for x in leads), max(x[1] for x in leads)) if leads else (days[0].isoformat(),
                                                                                       days[-1].isoformat())
            acts = schema.active_spans(days, gap)
            effort = sum(u["days"].values())
            density = defaultdict(int)
            for d, mins in u["days"].items():
                density[iso_week(date.fromisoformat(d))] += mins
            par = [len(rec["day_units"][d]) for d in u["days"]]
            UN[(pk, uid)] = {
                "pk": pk, "i": idx[pk], "unit_id": uid, "rkey": rkey, "role_id": rid, "proj_key": proj_key,
                "project_id": pid, "proposal": proposal, "proposal_id": ppid, "domain": dom,
                "field": role.get("field") or "", "function": role.get("function") or "",
                "title": meta.get("title") or "", "grade": meta.get("grade"), "status": meta.get("status"),
                "start": {"kind": (meta.get("start") or {}).get("kind"), "at": (meta.get("start") or {}).get("at")},
                "end": {"kind": (meta.get("end") or {}).get("kind"), "at": (meta.get("end") or {}).get("at")},
                "lead_time_h": meta.get("lead_time_h"), "activity_type": meta.get("activity_type"),
                "ax_link": bool(meta.get("ax_link")), "days": dict(u["days"]), "effort_min": effort,
                "spans": [[lead[0], lead[1], "lead"]] + [[a.isoformat(), b2.isoformat(), "active"] for a, b2 in acts],
                "density": dict(sorted(density.items())), "parallel": (sum(par) / len(par)) if par else 0.0,
                "src_sha": u["src"][last_m]}
            if proposal:
                UN[(pk, uid)]["proposal_label"] = (props.get(ppid) or {}).get("label") or ""

    # R-4 가 깨진 경우(같은 사람·같은 역할·같은 제목·겹치는 lead 띠의 다른 unit_id)는 두 막대로 두고 경고만(자동 병합 없음)
    same = defaultdict(list)
    for un in UN.values():
        same[(un["pk"], un["rkey"], un["title"])].append(un)
    for (pk, _rk, title), lst in sorted(same.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        lst.sort(key=lambda u: u["spans"][0][0])
        if title and any(a["spans"][0][1] >= b["spans"][0][0] for a, b in zip(lst, lst[1:], strict=False)):
            warnings.append(f"단위업무 ID 불안정 의심: {pk} — 같은 역할·같은 제목·겹치는 기간의 단위업무가 둘 이상(자동 병합 안 함)")

    # ── 월·영역·과제·역할·유형 누적(정수 분) ──
    def month_of_day(d: str) -> str:
        return d[:7]
    dom_m = defaultdict(lambda: defaultdict(int))          # (dom, m) → {pk: min}
    proj_m = defaultdict(lambda: defaultdict(int))         # proj_key → {(pk, m): min}
    role_m = defaultdict(lambda: defaultdict(int))
    wtype_m = defaultdict(lambda: defaultdict(int))        # (dom, type) → {(pk, m): min}
    unattr = defaultdict(int)                              # (pk, m) → min
    for un in UN.values():
        for d, mins in un["days"].items():
            m = month_of_day(d)
            if m not in W:
                continue
            dom_m[(un["domain"], m)][un["pk"]] += mins
            proj_m[un["proj_key"]][(un["pk"], m)] += mins
            role_m[un["rkey"]][(un["pk"], m)] += mins
            wtype_m[(un["domain"], un["activity_type"] or "")][(un["pk"], m)] += mins
    for pk in order:
        for m, e in P[pk]["months"].items():
            unattr[(pk, m)] = e["unattributed_min"]

    def denom(m):
        return D * W[m] if W.get(m) else 0

    def mm_of(cells: dict) -> tuple[float, list]:
        """{(pk, m): 분} → (총 MM, [[i, MM]]) — 사람·달마다 한 번 나눔."""
        by_p = defaultdict(float)
        for (pk, m), mins in cells.items():
            by_p[pk] += _mm(mins, denom(m))
        tot = 0.0
        for m in {m for (_pk, m) in cells}:
            tot += _mm(sum(v for (_pk, mm2), v in cells.items() if mm2 == m), denom(m))
        return tot, [[idx[pk], by_p[pk]] for pk in order if by_p.get(pk)]

    # people
    people_out = []
    for pk in order:
        rec = P[pk]
        label, src = display_label(pk, rec["member_id"], rec["self_label"], roster, reg_labels)
        people_out.append({
            "i": idx[pk], "person_key": pk, "label": label, "label_source": src, "member_id": rec["member_id"],
            "linked": [k for k in people[pk].keys if k != pk], "quality": grade_of[pk],
            "flags": sorted(rec["flags"]), "unused_bundles": rec.get("unused", 0),
            "months": [dict(rec["months"][m]) for m in months if m in rec["months"]]})

    # domains · unattributed
    domains_out = []
    for code in schema.DOMAINS_ALL:
        by_month, tot = {}, 0.0
        for m in months:
            cells = dom_m.get((code, m)) or {}
            if not cells:
                continue
            mm = _mm(sum(cells.values()), denom(m))
            tot += mm
            by_month[m] = {"mm": mm, "by_person": [[idx[pk], _mm(cells[pk], denom(m))] for pk in order if cells.get(pk)]}
        domains_out.append({"code": code, "by_month": by_month, "total_mm": tot})
    un_by_month = {m: _mm(sum(v for (pk, mm2), v in unattr.items() if mm2 == m), denom(m)) for m in months}
    un_by_person = defaultdict(float)
    for (pk, m), v in unattr.items():
        un_by_person[pk] += _mm(v, denom(m))
    unattributed = {"by_month": un_by_month, "total_mm": sum(un_by_month.values()),
                    "by_person": [[idx[pk], un_by_person[pk]] for pk in order if un_by_person.get(pk)]}

    # projects
    projects_out = []
    for key, cells in proj_m.items():
        units_in = [u for u in UN.values() if u["proj_key"] == key]
        u0 = units_in[0]
        tot, by_person = mm_of(cells)
        merged = sorted({x.get("project_id") for pk2 in people for b in people[pk2].bundles.values()
                         for x in b.get("roles") or () if x.get("project_id")
                         and x.get("project_id") != key and resolve_project(reg, x["project_id"], project_votes) == key})
        projects_out.append({
            "key": key, "project_id": u0["project_id"], "proposal_id": u0["proposal_id"] if u0["proposal"] else None,
            "proposal": u0["proposal"], "domain": u0["domain"],
            "label": (reg_proj.get(key) or {}).get("name") if not u0["proposal"] else u0.get("proposal_label"),
            "reserved": key in schema.RESERVED_PROJECTS, "merged": merged, "total_mm": tot, "by_person": by_person,
            "units": len(units_in), "roles": len({u["rkey"] for u in units_in})})
    projects_out.sort(key=lambda x: (-x["total_mm"], x["key"]))

    # roles · subagent fit
    fit_of = defaultdict(lambda: defaultdict(set))     # rkey → fit → {pk}
    for pk in order:
        for sha in P[pk]["used"]:
            for sa in (people[pk].bundles[sha].get("agentic") or {}).get("subagents") or ():
                for un in UN.values():
                    if un["pk"] == pk and un["role_id"] == sa.get("role_id"):
                        fit_of[un["rkey"]][sa.get("fit")].add(pk)
                        break
    roles_out = []
    for rkey, cells in role_m.items():
        units_in = [u for u in UN.values() if u["rkey"] == rkey]
        u0 = units_in[0]
        tot, by_person = mm_of(cells)
        lead_b = [x for x in (_unit_biz(u, people, cal, std_win, lunch_win) for u in units_in
                              if u["status"] == "closed" and u["i"] not in excl_set) if x is not None]
        efforts = [u["effort_min"] for u in units_in if u["i"] not in excl_set]
        roles_out.append({
            "key": rkey, "role_id": u0["role_id"], "project_id": u0["project_id"], "proposal": u0["proposal"],
            "proposal_key": u0["proj_key"] if u0["proposal"] else None, "domain": u0["domain"],
            "field": u0["field"], "function": u0["function"], "total_mm": tot, "by_person": by_person,
            "units": len(units_in), "lead_biz_median_min": statistics.median(lead_b) if lead_b else None,
            "effort_median_min": statistics.median(efforts) if efforts else None,
            "subagent": {f: len(fit_of[rkey].get(f, ())) for f in schema.FITS}})
    roles_out.sort(key=lambda x: (-x["total_mm"], x["key"]))

    # role_matrix(분포 비율 = 귀속분 기준, 측정 불충분 제외)
    cell_min = defaultdict(lambda: defaultdict(int))     # (field, func) → {(pk, m): min}
    for un in UN.values():
        for d, mins in un["days"].items():
            if d[:7] in W:
                cell_min[(un["field"], un["function"])][(un["pk"], d[:7])] += mins
    cmp_total = sum(v for cells in cell_min.values() for (pk, _m), v in cells.items() if idx[pk] not in excl_set)
    cells_out = []
    for (fd, fn), cells in sorted(cell_min.items()):
        tot, _bp = mm_of(cells)
        part = sum(v for (pk, _m), v in cells.items() if idx[pk] not in excl_set)
        cells_out.append([fd, fn, tot, (part / cmp_total) if cmp_total else None])
    role_matrix = {"fields": sorted({c[0] for c in cells_out}), "functions": sorted({c[1] for c in cells_out}),
                   "cells": cells_out}

    # vocab_names(레지스트리 어휘 이름 — 없으면 화면이 코드로)
    voc = reg.get("vocab") if isinstance(reg.get("vocab"), dict) else {}

    def names(kind):
        return {x["code"]: x.get("name") or x["code"] for x in voc.get(kind) or ()
                if isinstance(x, dict) and isinstance(x.get("code"), str)}
    vocab_names = {"field": names("fields"), "func": names("functions"), "wtype": names("activity_types")}

    # activity_types
    types = list(schema.ACTIVITY_TYPES) + sorted({t for (_d, t) in wtype_m if t and t not in schema.ACTIVITY_TYPES})
    by_domain, total_t, by_person_t = defaultdict(dict), {}, defaultdict(dict)
    for (dom, t), cells in sorted(wtype_m.items()):
        tot, bp = mm_of(cells)
        by_domain[dom][t] = tot
        total_t[t] = total_t.get(t, 0.0) + tot
        for i, v in bp:
            by_person_t[i][t] = by_person_t[i].get(t, 0.0) + v
    activity_types = {"types": types, "by_domain": dict(by_domain), "total": total_t,
                      "by_person": [[i, by_person_t[i]] for i in sorted(by_person_t)]}

    # units_stats(분포 — 측정 불충분 제외)
    st_c, gr_c, lead_points = defaultdict(int), defaultdict(int), []
    lead_by_dom = defaultdict(list)
    for un in UN.values():
        if un["i"] in excl_set:
            continue
        st_c[un["status"]] += 1
        gr_c[un["grade"]] += 1
        if un["status"] == "closed":
            bl = _unit_biz(un, people, cal, std_win, lunch_win)
            if bl is not None:
                lead_points.append({"domain": un["domain"], "biz_lead_min": bl, "effort_min": un["effort_min"],
                                    "project_id": un["project_id"], "role_id": un["role_id"], "i": un["i"]})
                lead_by_dom[un["domain"]].append(bl)
    lead_points.sort(key=lambda x: (x["domain"], x["i"], x["role_id"], x["biz_lead_min"]))
    units_stats = {"by_status": dict(sorted(st_c.items())), "by_grade": dict(sorted(gr_c.items())),
                   "lead_points": lead_points,
                   "lead_median_by_domain": {k: statistics.median(v) for k, v in sorted(lead_by_dom.items())}}

    # agentic
    ukey_fn = ukey_fn or _resolve_ukey(ukey, warnings) if any(
        (people[pk].bundles[s].get("agentic") or {}).get("needs") for pk in order for s in P[pk]["used"]) else None
    agentic = _agentic(people, P, UN, order, idx, agent_names, ukey_fn, denom, W)

    # quality
    matrix = []
    for pk in order:
        used = [people[pk].bundles[s] for s in sorted(P[pk]["used"])]
        latest = max(used, key=_built_utc) if used else None
        axes_days = defaultdict(lambda: defaultdict(int))
        reasons, pcs, cp_used, cp_fail = set(), 0, False, 0
        for b in used:
            q = b.get("quality") or {}
            reasons.update(x for x in q.get("reasons") or () if isinstance(x, str))
            pcs = max(pcs, len(q.get("pcs") or ()))
            cov = q.get("coverage") or ()
            for c in cov:
                for st, n in (c.get("days") or {}).items():
                    axes_days[c.get("axis")][st] += n
            cp = q.get("copilot") or {}
            cp_used = cp_used or bool(cp.get("used"))
            cp_fail += cp.get("failed_items") or 0
        axes = {}
        for ax, days_ in axes_days.items():
            tot = sum(days_.values())
            axes[ax] = (days_.get("ok", 0) + days_.get("zero_ok", 0) + 0.5 * days_.get("partial", 0)) / tot if tot else None
        lq = (latest or {}).get("quality") or {}
        matrix.append({"i": idx[pk], "grade": grade_of[pk], "reasons": sorted(reasons), "axes": axes, "pcs": pcs,
                       "flags": sorted(P[pk]["flags"]), "copilot": {"used": cp_used, "failed_items": cp_fail},
                       "queue": dict(lq.get("confirm_queue") or {}),
                       "estimated_min_ratio": lq.get("estimated_min_ratio")})

    # gantt · details
    gantt, details = _gantt(UN, order, idx, people, P, reg_proj, agent_names, store, roster, reg_labels)

    td = {
        "schema": TD_SCHEMA, "gen": int(gen), "built_at": (now or store.clock()).isoformat(),
        "registry_version": store.registry_version(), "calendar_version": cal_ver,
        "team_label": ((reg.get("team") or {}).get("label") if isinstance(reg.get("team"), dict) else None),
        "months": months, "omitted_months": omitted, "workdays": {m: W[m] for m in months},
        "std_day_min": D, "density_steps": list(DENSITY_STEPS),
        "people": people_out, "domains": domains_out, "projects": projects_out, "roles": roles_out,
        "role_matrix": role_matrix, "vocab_names": vocab_names, "activity_types": activity_types,
        "unattributed": unattributed, "units_stats": units_stats, "gantt": gantt, "agentic": agentic,
        "quality": {"excluded_from_comparison": excluded, "matrix": matrix}, "interpretation": [],
        "warnings": warnings}
    warnings.extend(check_invariants(td, people=people, used={pk: P[pk]["used"] for pk in order}, picks=picks, gap=gap))
    return td, details


def _unit_biz(un, people, cal, std_win, lunch_win):
    off = 540
    b = people[un["pk"]].bundles.get(un["src_sha"]) or {}
    o = (b.get("person") or {}).get("work_tz_offset_min")
    if isinstance(o, int):
        off = o
    v = biz_minutes(un["start"]["at"], un["end"]["at"], off, cal, std_win, lunch_win)
    if v is not None:
        return v
    s = un["spans"][0]
    try:
        n = _workdays_in(cal, date.fromisoformat(s[0]), date.fromisoformat(s[1]))
    except ValueError:
        return None
    return n * ((std_win[1] - std_win[0]) - (lunch_win[1] - lunch_win[0]))


def _agentic(people, P, UN, order, idx, agent_names, ukey_fn, denom, W) -> dict:
    """에이전트 매칭·새 니즈·서브에이전트 취합(TAB §4.7 · R §7.8.1). 관련 투입은 서버가 alloc 에서 다시 합친다."""
    def unit_mm(keys):
        cells = defaultdict(int)
        for k in keys:
            un = UN.get(k)
            if un is None:
                continue
            for d, mins in un["days"].items():
                if d[:7] in W:
                    cells[d[:7]] += mins
        return sum(_mm(v, denom(m)) for m, v in cells.items())
    grade_rank = {"상": 2, "중": 1, "하": 0}
    mt = defaultdict(lambda: {"people": set(), "roles": set(), "units": set(), "dom": defaultdict(
        lambda: {"people": set(), "units": set(), "best": None})})
    needs = {}
    sub = defaultdict(lambda: {"fit": defaultdict(set), "chains": defaultdict(lambda: {"people": set(), "types": set()})})
    for pk in order:
        seen_need = set()
        for sha in sorted(P[pk]["used"]):
            b = people[pk].bundles[sha]
            ag = b.get("agentic") or {}
            wf_types = {}
            for w in b.get("workflows") or ():
                for s in w.get("steps") or ():
                    wf_types[(w.get("role_id"), s.get("no"))] = s.get("type")
            for x in ag.get("matches") or ():
                aid = x.get("agent_id")
                rec = mt[aid]
                for uid in x.get("units") or ():
                    un = UN.get((pk, uid))
                    if un is None:
                        continue
                    rec["people"].add(pk)
                    rec["roles"].add(un["rkey"])
                    rec["units"].add((pk, uid))
                    dd = rec["dom"][un["domain"]]
                    dd["people"].add(pk)
                    dd["units"].add((pk, uid))
                    if dd["best"] is None or grade_rank.get(x.get("grade"), -1) > grade_rank.get(dd["best"], -1):
                        dd["best"] = x.get("grade")
            for x in ag.get("needs") or ():
                key = (x.get("step_type"), ukey_fn(x.get("label") or "") if ukey_fn else x.get("label"))
                rec = needs.setdefault(key, {"step_type": x.get("step_type"), "label": x.get("label"), "people": set(),
                                             "freq": 0.0, "units": set(), "grades": defaultdict(int),
                                             "src": defaultdict(set)})
                if (pk, x.get("need_id")) in seen_need:
                    continue
                seen_need.add((pk, x.get("need_id")))
                rec["people"].add(pk)
                rec["freq"] += x.get("freq_per_month") or 0
                rec["units"].update((pk, u) for u in x.get("units") or ())
                rec["grades"][x.get("grade")] += 1
                if x.get("src") in ("ai", "rule"):
                    rec["src"][x["src"]].add(pk)
            for x in ag.get("subagents") or ():
                role = next((r for r in b.get("roles") or () if r.get("role_id") == x.get("role_id")), {})
                k2 = (role.get("field") or "", role.get("function") or "")
                sub[k2]["fit"][x.get("fit")].add(pk)
                for c in x.get("chain") or ():
                    ch = sub[k2]["chains"][c.get("proposal") or ""]
                    ch["people"].add(pk)
                    t = wf_types.get((x.get("role_id"), c.get("step_no")))
                    if t:
                        ch["types"].add(t)
    all_units = set()
    overlap_units = defaultdict(int)
    for rec in mt.values():
        for k in rec["units"]:
            overlap_units[k] += 1
    matches = []
    for aid, rec in sorted(mt.items()):
        if not rec["units"]:
            continue
        all_units |= rec["units"]
        matches.append({
            "agent_id": aid, "name": agent_names.get(aid), "people": len(rec["people"]), "roles": len(rec["roles"]),
            "units": len(rec["units"]), "related_mm": unit_mm(rec["units"]),
            "overlap": any(overlap_units[k] > 1 for k in rec["units"]),
            "by_domain": {d: {"people": len(v["people"]), "units": len(v["units"]), "related_mm": unit_mm(v["units"]),
                              "best": v["best"]} for d, v in sorted(rec["dom"].items())}})
    needs_out = [{"step_type": v["step_type"], "label": v["label"], "people": len(v["people"]), "freq_per_month": v["freq"],
                  "related_mm": unit_mm(v["units"]), "grades": {g: v["grades"].get(g, 0) for g in schema.AGENT_GRADES},
                  "src": {"ai": len(v["src"].get("ai", ())), "rule": len(v["src"].get("rule", ()))}}
                 for _k, v in sorted(needs.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))]
    subs = [{"field": f, "function": fn, "fit": {x: len(v["fit"].get(x, ())) for x in schema.FITS},
             "chains": [{"proposal": pr, "people": len(c["people"]), "step_types": sorted(c["types"])}
                        for pr, c in sorted(v["chains"].items()) if pr]}
            for (f, fn), v in sorted(sub.items())]
    return {"matches": matches, "needs": needs_out, "subagents": subs, "related_mm_total": unit_mm(all_units)}


def _gantt(UN, order, idx, people, P, reg_proj, agent_names, store, roster, reg_labels):
    """간트 행(기본 계층 담당자 → 영역 → 과제 → 역할) + 드릴다운 사전(키 ``"<i>|<role_id>"``)."""
    rows = defaultdict(list)
    for un in UN.values():
        rows[(un["pk"], un["domain"], un["proj_key"], un["rkey"])].append(un)
    dom_rank = {d: k for k, d in enumerate(schema.DOMAINS_ALL)}
    proj_tot = defaultdict(int)
    role_tot = defaultdict(int)
    for un in UN.values():
        proj_tot[(un["pk"], un["proj_key"])] += un["effort_min"]
        role_tot[(un["pk"], un["rkey"])] += un["effort_min"]
    keys = sorted(rows, key=lambda k: (idx[k[0]], dom_rank.get(k[1], 99), -proj_tot[(k[0], k[2])], k[2],
                                       -role_tot[(k[0], k[3])], k[3]))
    gantt, details = [], {}
    for k in keys:
        units = sorted(rows[k], key=lambda u: (u["spans"][0][0], u["unit_id"]))
        u0 = units[0]
        day_par = []
        for u in units:
            day_par += [len(P[u["pk"]]["day_units"][d]) for d in u["days"]]
        lead_days = set()
        for u in units:
            a, b = date.fromisoformat(u["spans"][0][0]), date.fromisoformat(u["spans"][0][1])
            lead_days.update(a + timedelta(days=n) for n in range((b - a).days + 1))
        row_end = {"effort_h": sum(u["effort_min"] for u in units) / 60,
                   "parallel": (sum(day_par) / len(day_par)) if day_par else 0.0, "lead_days": len(lead_days)}
        uo = [{"unit_id": u["unit_id"], "title": u["title"], "spans": u["spans"], "density": u["density"],
               "effort_min": u["effort_min"], "parallel": u["parallel"], "grade": u["grade"], "status": u["status"],
               "start": u["start"], "end": u["end"], "lead_time_h": u["lead_time_h"]} for u in units]
        gantt.append({"person": idx[k[0]], "domain": k[1], "project_id": u0["project_id"],
                      "proposal_id": u0["proposal_id"] if u0["proposal"] else None, "role_id": u0["role_id"],
                      "role_key": k[3], "row_end": row_end, "units": uo})
        pk = k[0]
        b = people[pk].bundles[u0["src_sha"]]
        wf = next((w for w in b.get("workflows") or () if w.get("role_id") == u0["role_id"]), None)
        ms = []
        for sha in sorted(P[pk]["used"]):
            for x in (people[pk].bundles[sha].get("agentic") or {}).get("matches") or ():
                if x.get("role_id") == u0["role_id"]:
                    item = {"agent_id": x.get("agent_id"), "name": agent_names.get(x.get("agent_id")),
                            "step_type": x.get("step_type"), "grade": x.get("grade")}
                    if item not in ms:
                        ms.append(item)
        rec = P[pk]
        label, _src = display_label(pk, rec["member_id"], rec["self_label"], roster, reg_labels)
        details[f"{idx[pk]}|{u0['role_id']}"] = {
            "person": {"i": idx[pk], "label": label},
            "role": {"role_id": u0["role_id"], "project_id": u0["project_id"],
                     "project_label": (reg_proj.get(u0["project_id"]) or {}).get("name") if u0["project_id"]
                     else u0.get("proposal_label"), "domain": u0["domain"], "field": u0["field"],
                     "function": u0["function"], "proposal": u0["proposal"]},
            "workflow": {"steps": list((wf or {}).get("steps") or []), "edges": list((wf or {}).get("edges") or [])},
            "units": uo, "agentic": {"matches": ms}}
    return gantt, details


def check_invariants(td, *, people=None, used=None, picks=None, gap: int = 2) -> list[str]:
    """TAB §4.8 I1~I7 — 위반은 경고 문자열(산출은 계속). ``td`` 만 주면 I3(계층 보존)·I4(팀 합)를,
    ``people``(사람 → 묶음)·``used``(사람 → 선택된 sha)·``picks``(사람 → 달 → sha)를 함께 주면 I1(일 보존)·I5(월 단일 출처)·
    I6(effort)·I7(간트)까지. I2(개인=팀)는 계산 중에 대조한다(calendar_mismatch 배지 · mm_bundle 병기)."""
    out = []
    D = td.get("std_day_min") or 480
    for pk in sorted(used or {}):
        for sha in sorted(used[pk]):
            b = people[pk].bundles[sha]
            env = {r[0]: dict(zip(schema.TAGS, r[1:], strict=True)) for r in b["envelope_daily"]["rows"]}
            acc, per_unit = defaultdict(int), defaultdict(int)
            for d, u, t, mins in b["alloc_daily"]["rows"]:
                acc[(d, t)] += mins
                per_unit[u] += mins
            if any(v > env.get(d, {}).get(t, 0) for (d, t), v in acc.items()):
                out.append(f"I1 일 보존 위반: {pk}")
            if any(x.get("effort_min") != per_unit.get(x.get("unit_id"), 0) for x in b.get("units") or ()):
                out.append(f"I6 effort 불일치: {pk}")
            udays = defaultdict(set)
            for d, u, _t, _m in b["alloc_daily"]["rows"]:
                udays[u].add(date.fromisoformat(d))
            for x in b.get("units") or ():
                acts = sorted((date.fromisoformat(s[0]), date.fromisoformat(s[1]))
                              for s in x.get("spans") or () if s[2] == "active")
                if acts != schema.active_spans(udays.get(x.get("unit_id"), ()), gap):
                    out.append(f"I7 gantt_mismatch: {pk} {x.get('unit_id')} — 서버가 귀속 일자에서 다시 만든 구간을 씁니다")
        srcs = defaultdict(set)
        for m, sha in (picks or {}).get(pk, {}).items():
            srcs[m].add(sha)
        if any(len(v) != 1 for v in srcs.values()):
            out.append(f"I5 월 단일 출처 위반: {pk}")
    dom_pm = defaultdict(float)
    for x in td["domains"]:
        for m, v in x["by_month"].items():
            for i, mm in v["by_person"]:
                dom_pm[(i, m)] += mm
    for p in td["people"]:
        for e in p["months"]:
            if not e["workdays"]:
                continue
            got = dom_pm.get((p["i"], e["m"]), 0.0) + _mm(e["unattributed_min"], D * e["workdays"])
            if abs(got - e["mm"]) > 1e-9:
                out.append(f"I3 계층 보존 위반: i={p['i']} {e['m']}")
    for m in td["months"]:
        team = sum(e["mm"] for p in td["people"] for e in p["months"] if e["m"] == m)
        tree = sum(x["by_month"].get(m, {}).get("mm", 0.0) for x in td["domains"]) + td["unattributed"]["by_month"].get(m, 0.0)
        if abs(tree - team) > 1e-9:
            out.append(f"I4 팀 합 불일치: {m}")
    return out


# ───────────────────────────── 실행 ─────────────────────────────
def aggregate(store, gen: int, *, ukey=None, now=None, write: bool = True) -> AggResult:
    """재취합 1회 → ``out\\gen_<gen>\\`` 에 산출(team_data.json · details.json · 보고서 HTML · 마지막에 result.json).
    현재 세대 전환(``out\\current.json``)은 호출자(서버 워커·반입 CLI)가 ``store.publish_gen`` 으로 한다."""
    t0 = time.monotonic()
    warnings: list[str] = []
    gen = int(gen)
    try:
        cal = store.calendar()
        warnings.extend(getattr(cal, "warnings", ()) or ())
        people = merge_links(load_people(store, warnings), store.roster(), store.pepper_id)
        td, details = build_team_data(store, people, cal, gen, ukey=ukey, now=now, warnings=warnings)
    except Exception as e:                                   # 취합 실패 — 이전 세대를 그대로 서빙(TAB §3.9)
        res = AggResult(ok=False, rc=1, gen=gen, warnings=warnings + [f"취합 실패({type(e).__name__})"],
                        sec=time.monotonic() - t0)
        if write:
            fsx.atomic_write(store.gen_dir(gen) / "result.json", fsx.canon_bytes(res.as_result_json()))
        store.log_aggregate(f"gen {gen} 실패 {type(e).__name__}")
        return res
    _interpret(td, store, warnings)
    res = AggResult(ok=True, rc=0, gen=gen, members=len(td["people"]), warnings=warnings, td=td, details=details)
    if write:
        gd = store.gen_dir(gen)
        fsx.atomic_write(gd / "team_data.json", fsx.canon_bytes(td))
        fsx.atomic_write(gd / "details.json", fsx.canon_bytes(details))
        _render(td, details, gd, warnings)
        res.sec = time.monotonic() - t0
        fsx.atomic_write(gd / "result.json", fsx.canon_bytes(res.as_result_json()))
    res.sec = time.monotonic() - t0
    store.log_aggregate(f"gen {gen} 완료 {res.members}명 경고 {len(warnings)} {res.sec:.1f}s")
    return res


def _report_module():
    """``lm27.team.report``(WP-37) — 아직 없으면 None(보고서 HTML 없이 경고만, 조용히 넘기지 않는다)."""
    if importlib.util.find_spec("lm27.team.report") is None:
        return None
    return importlib.import_module("lm27.team.report")


def _interpret(td, store, warnings) -> None:
    mod = _report_module()
    fn = getattr(mod, "interpret", None) if mod else None
    if fn is None:
        warnings.append("해석 문장 모듈(lm27.team.report.interpret)이 아직 없어 interpretation 을 비웠습니다")
        return
    td["interpretation"] = list(fn(td, store.cfg) or [])


def _render(td, details, gd, warnings) -> None:
    mod = _report_module()
    fn = getattr(mod, "render_team_report", None) if mod else None
    if fn is None:
        warnings.append("팀 보고서 렌더러(lm27.team.report)가 아직 없어 team_report.html 을 만들지 않았습니다")
        return
    island = dict(td)
    island["details"] = details                       # 자기완결 보고서 데이터 섬 = team_data + details(R §7.8.2)
    for share, name in ((False, "team_report.html"), (True, "team_report_share.html")):
        fsx.atomic_write(gd / name, str(fn(island, share=share)).encode("utf-8"))
