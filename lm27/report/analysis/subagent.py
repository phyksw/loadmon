# -*- coding: utf-8 -*-
r"""서브에이전트 도입 적합성 — 5기준(R §4.8 · §6.8 · 부록 A, 결정 §10.5 · 계약 §3.16 서브에이전트 절 · D-19).

**판정 수치는 규칙이 원장(정수 분 표·흔적)에서 계산한다**(D-19). 코파일럿 의견(subagent_review)은 최종 판정을 더 보수적으로만
바꿀 수 있다(규칙의 하드 조건을 넘지 못한다).

단계 통계(R §4.8.1) — 역할 업무의 단계 c 마다 그 역할 단위업무들의 정리된 흔적에서:
weeks_active(역할 투입이 있는 ISO 주 수) · occ(정리된 흔적 항목 수) · digital_share(L3·L4 귀속 분 비율, 점은 오프라인 아님 비율) ·
structured_share(다룬 문서군 중 정형 확장자군 xls·txt·code 비율 — 같은 문서군이 역할 단위업무 3개 이상에 반복되면 정형) ·
tool_class_min(Run 분을 앱 분류의 도구 접근 점수별로) · rework_rate(차수 ≥ 2 또는 c 로 되돌림) · external_share(외부 상대가
의뢰·보고 상대인 비율) · money_hit(단위업무 정제 제목에 `[금액]` 토큰).

점수(R §4.8.2, 각 0~2): REP(주 1회 이상 2 · 월 1회 이상 1) · IO = D + S · TOOL(분이 가장 큰 도구 점수, 동률은 작은 쪽) ·
VER(유형 기본값을 되돌림 비율로 깎음) · RISK(외부 상대 · 금액 · 보고/지시/검토 단계). 점수 = REP + IO + TOOL + VER + (2 − RISK).
판정(R §4.8.3): D = 0 · TOOL = 0 · RISK = 2 → 부적합, 점수 ≥ fitScore ∧ TOOL = 2 ∧ RISK = 0 → 적합, 점수 ≥ condScore → 조건부.
역할 판정 = 구간 단계 분 가중(적합 분 비율 ≥ roleFitShare → 적합, 적합·조건부 단계 있음 → 조건부). 최종 = 규칙과 코파일럿
(적합·부분·부적합 → 적합·조건부·부적합) 중 더 보수적인 쪽 — 단계 최종도 같은 규칙(그 역할의 코파일럿 의견과 단계 규칙 판정).

설정(R §10.2): `report.subagent.fitScore` · `condScore` · `roleFitShare`. 표준 라이브러리만 쓴다. 나눗셈은 `fmt` 로만.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from lm27.report import fmt as F
from lm27.report.analysis.activity import Unit
from lm27.vocab import steps as S

__all__ = ["AI_MAP", "LEVEL", "final_verdict", "flags_text", "role_verdict", "step_stats", "subagent_layer",
           "subagent_step"]

LEVEL = {"부적합": 0, "조건부": 1, "적합": 2}
AI_MAP = {"적합": "적합", "부분": "조건부", "부적합": "부적합"}
STRUCT_EXT = frozenset({"xls", "txt", "code"})
STRUCT_TYPES = {"DOC_XLS": "xls", "DOC_ETC": "txt", "APP_IDE": "code", "COMMIT": "code"}
RISK_TYPES = frozenset({"REPORT_OUT", "REQ_OUT", "REVIEW"})
EXTERNAL = frozenset({"customer", "partner", "other"})
WEEKS_PER_MONTH = "4.345"
REPEAT_UNITS = 3                         # 같은 문서군이 역할 단위업무 3개 이상에 → 반복 양식(정형)
MONEY_TOKEN = "[금액"
_APP_STEP = {"cad": "APP_CAD", "sim": "APP_SIM", "eda": "APP_EDA", "ide": "APP_IDE", "browser": "WEB",
             "chat_work": "COMM", "mail_work": "COMM", "meeting": "MEET"}
FLAG_ORDER = ("D", "R", "B", "L", "S", "T")


def subagent_cfg(cfg) -> dict:
    return {"fit": int(cfg["report.subagent.fitScore"]), "cond": int(cfg["report.subagent.condScore"]),
            "role_fit": F.dec(cfg["report.subagent.roleFitShare"])}


# ───────────────────────────── 점수·판정(R §4.8.2·§4.8.3) ─────────────────────────────
def subagent_step(stat: Mapping, cfg, registry=None) -> dict:
    """단계 통계 하나 → 5기준 점수·규칙 판정·플래그(D R B L S T)·why."""
    c = subagent_cfg(cfg)
    code = str(stat["type"])
    weeks = max(1, int(stat.get("weeks_active") or 0))
    occ = int(stat.get("occ") or 0)
    if F.dec(occ) >= F.dec(weeks):
        rep = 2
    elif F.dec(occ) * F.dec(WEEKS_PER_MONTH) >= F.dec(weeks):
        rep = 1
    else:
        rep = 0
    d = 1 if F.dec(stat.get("digital_share") or 0) >= F.dec("0.8") else 0
    s = 1 if F.dec(stat.get("structured_share") or 0) >= F.dec("0.5") else 0
    tc = {int(k): int(v) for k, v in (stat.get("tool_class_min") or {}).items()}
    if tc:
        top = max(tc.values())
        tool = min(k for k, v in tc.items() if v == top)
    else:
        tool = S.tool_access(code, registry)
    base_ver = S.verifiable(code, registry)
    rr = F.dec(stat.get("rework_rate") or 0)
    ver = base_ver if rr < F.dec("0.3") else (min(base_ver, 1) if rr < F.dec("0.6") else 0)
    risk = min(2, (1 if F.dec(stat.get("external_share") or 0) >= F.dec("0.3") else 0)
               + (1 if stat.get("money_hit") else 0) + (1 if code in RISK_TYPES else 0))
    score = rep + d + s + tool + ver + (2 - risk)
    if d == 0 or tool == 0 or risk == 2:
        verdict = "부적합"
    elif score >= c["fit"] and tool == 2 and risk == 0:
        verdict = "적합"
    elif score >= c["cond"]:
        verdict = "조건부"
    else:
        verdict = "부적합"
    flags = {"D": d, "R": int(rep == 2), "B": int(ver == 2), "L": int(risk == 0), "S": s, "T": int(tool == 2)}
    why = [w for w, ok in (("digital_io", d), ("repeat_weekly", rep == 2), ("repeat_monthly", rep == 1),
                           ("structured_input", s), ("low_accountability", risk == 0), ("verifiable", ver == 2),
                           ("tool_access", tool == 2)) if ok]
    return {"type": code, "REP": rep, "IO": d + s, "TOOL": tool, "VER": ver, "RISK": risk, "score": score,
            "verdict": verdict, "flags": flags, "why": why}


def role_verdict(rows: Iterable[Mapping], minutes_by_type: Mapping[str, int], cfg) -> tuple[str, float]:
    """역할 판정(규칙) — 구간 단계의 단계 판정을 그 단계 Run 분으로 가중. 반환 (판정, 적합 분 비율)."""
    c = subagent_cfg(cfg)
    rows = list(rows)
    act = {r["type"]: int(minutes_by_type.get(r["type"], 0)) for r in rows if S.STEP_TYPES.get(r["type"]) and
           S.STEP_TYPES[r["type"]].kind == "A"}
    tot = sum(act.values())
    fit = sum(m for k, m in act.items() if next(r for r in rows if r["type"] == k)["verdict"] == "적합")
    share = F.per(fit, tot)
    if tot and share >= c["role_fit"]:
        v = "적합"
    elif any(r["verdict"] in ("적합", "조건부") for r in rows):
        v = "조건부"
    else:
        v = "부적합"
    return v, F.half_up(share, 3)


def final_verdict(rule: str, ai: str | None) -> str:
    """규칙 판정과 코파일럿 의견(적합·부분·부적합) 중 더 보수적인 쪽(R §4.8.3). ai 가 없거나 모르는 값이면 규칙."""
    if ai is None:
        return rule
    a = AI_MAP.get(str(ai))
    if a is None:
        return rule
    return a if LEVEL[a] <= LEVEL.get(rule, 0) else rule


def flags_text(flags: Mapping[str, int]) -> str:
    """코파일럿 입력 플래그 글자 `D1 R1 B0 L1 S1 T1`(R §4.10.1 · B-1 → subagent_review/1.1)."""
    return " ".join(f"{k}{int(flags.get(k, 0))}" for k in FLAG_ORDER)


# ───────────────────────────── 단계 통계(R §4.8.1) ─────────────────────────────
def _app_score(app: str, code: str, registry) -> int:
    """앱 분류의 도구 접근 점수 — 카탈로그 app_class → 단계 → 점수(문서 앱·미상은 그 단계 유형 점수)."""
    if not app:
        return S.tool_access(code, registry)
    from lm27.catalog import app_class_of     # 카탈로그 단일원(계약 §2.8)
    step = _APP_STEP.get(app_class_of(app) or "")
    return S.tool_access(step or code, registry)


def _fam_class(fam: str, code: str, fam_ext: Mapping[str, str]) -> str:
    return fam_ext.get(fam) or STRUCT_TYPES.get(code, "")


def step_stats(code: str, units_tr: list[tuple[Unit, list]], *, registry=None, pidx=None, fam_ext=None,
               weeks_active: int = 0, no_of: Mapping[str, int] | None = None) -> dict:
    """단계 c 의 통계(R §4.8.1). units_tr = [(Unit, 정리된 흔적[Tr])] — 역할(또는 사람 전체)의 단위업무."""
    fx = fam_ext or {}
    kind = S.STEP_TYPES[code].kind if code in S.STEP_TYPES else "A"
    occ = 0
    sec = dig = 0
    ms_n = ms_dig = 0
    tool_sec: Counter = Counter()
    fams: set[str] = set()
    with_c = []
    for u, tr in units_tr:
        items = [x for x in tr if x.code == code]
        if not items:
            continue
        with_c.append((u, tr))
        occ += len(items)
        for x in items:
            for it in x.items:
                if kind == "M":
                    ms_n += 1
                    ms_dig += 0 if "offline" in getattr(it, "flags", ()) else 1
                    continue
                sec += it.sec
                dig += sum(s for lv, s in getattr(it, "level_sec", ()) if str(lv)[:2] in ("L3", "L4"))
                apps = list(getattr(it, "apps", ()))
                rest = it.sec - sum(s for _a, s in apps)
                for a, s in apps:
                    tool_sec[_app_score(a, code, registry)] += s
                if rest > 0:
                    tool_sec[S.tool_access(code, registry)] += rest
                fams |= {f for f, _s in getattr(it, "fams", ())}
    # 반복 양식: 같은 문서군이 그 단위업무 묶음 3개 이상에 나옴(Run·문서 연결 어느 쪽이든)
    seen_in: Counter = Counter()
    for u, tr in units_tr:
        fs = set(u.docs)
        for x in tr:
            for it in x.items:
                fs |= {f for f, _s in getattr(it, "fams", ())}
        for f in fs:
            seen_in[f] += 1
    if kind == "M":
        att = set()
        for u, _tr in with_c:
            att |= {f for f, v in u.docs.items() if int(v["ops"].get("attach", 0)) > 0}
        pool = att
        digital = F.per(ms_dig, ms_n) if ms_n else F.dec(0)
        structured = F.per(sum(1 for f in pool if _fam_class(f, code, fx) in STRUCT_EXT or seen_in[f] >= REPEAT_UNITS),
                           len(pool)) if pool else F.dec(0)
    else:
        digital = F.per(dig, sec)
        if fams:
            structured = F.per(sum(1 for f in fams if _fam_class(f, code, fx) in STRUCT_EXT
                                   or seen_in[f] >= REPEAT_UNITS), len(fams))
        else:
            structured = F.dec(1) if STRUCT_TYPES.get(code) in STRUCT_EXT else F.dec(0)
    nc = (no_of or {}).get(code)
    rw = 0
    ext = 0
    money = False
    for u, tr in with_c:
        back = False
        if no_of is not None and nc is not None:
            for x, y in zip(tr, tr[1:], strict=False):
                if y.code == code and no_of.get(x.code, 0) > nc:
                    back = True
        if u.n_cycles >= 2 or back:
            rw += 1
        if pidx is not None:
            rels = pidx.by_unit.get(u.unit_id, {})
            if any(pidx.cls.get(w) in EXTERNAL and (("requester" in r) or ("reporter" in r)) for w, r in rels.items()):
                ext += 1
        if MONEY_TOKEN in (u.title or ""):
            money = True
    n = len(with_c)
    return {"type": code, "weeks_active": int(weeks_active), "occ": occ,
            "digital_share": F.half_up(digital, 3), "structured_share": F.half_up(structured, 3),
            "tool_class_min": {k: F.sec_min(v) for k, v in sorted(tool_sec.items())} if kind == "A" else {},
            "rework_rate": F.half_up(F.per(rw, n), 3) if n else 0.0,
            "external_share": F.half_up(F.per(ext, n), 3) if n else 0.0, "money_hit": money,
            "minutes": F.sec_min(sec), "units": sorted(u.unit_id for u, _t in with_c)}


def weeks_active(units: Iterable[Unit]) -> int:
    """투입이 있는 ISO 주 수."""
    return len({F.iso_week(d) for u in units for d, m in u.by_date.items() if m > 0})


# ───────────────────────────── 역할별 검토(R §4.8 · §4.8.5) ─────────────────────────────
def _ai_view(ans, by, steps: list[dict], rows: Mapping[int, dict]) -> dict | None:
    if not isinstance(ans, Mapping):
        return None
    n_steps = {s["no"] for s in steps}
    subs = []
    for sub in ans.get("subs") or ():
        if not isinstance(sub, Mapping):
            continue
        nos = []
        for sc in sub.get("steps") or ():
            t = str(sc)
            if t[:1] == "S" and t[1:].isdigit() and int(t[1:]) in n_steps:
                nos.append(int(t[1:]))
        if not nos:
            continue
        subs.append({"steps": nos, "role": str(sub.get("role") or "")[:40], "io": str(sub.get("io") or "")[:60],
                     "check": str(sub.get("check") or "")[:40],
                     "human_check": [n for n in nos if rows.get(n, {}).get("rule") == "부적합"]})
    v = str(ans.get("verdict") or "")
    return {"verdict": v if v in AI_MAP else "", "orch": str(ans.get("orch") or "")[:60], "subs": subs,
            "risk": str(ans.get("risk") or "")[:80], "by": str(by or "ai")}


def subagent_layer(ctx, roles_wf: Mapping[str, dict], traces: Mapping[str, Mapping[str, list]], pidx,
                   answers: Mapping[str, tuple] | None = None) -> dict:
    """모델 `subagent{roles[…]}` — 역할 투입 내림차순. RoleWorkflow 의 Step.subagent·why 도 채운다(단계 최종 판정)."""
    out = []
    for rid in sorted(roles_wf, key=lambda r: (-int(roles_wf[r].get("effort_min", 0)), r)):
        rw = roles_wf[rid]
        tr = traces.get(rid, {})
        units = [ctx.units[u] for u in rw["units"] if u in ctx.units]
        utr = [(u, tr.get(u.unit_id, [])) for u in units]
        wa = weeks_active(units)
        no_of = {s["code"]: s["no"] for s in rw["steps"]}
        rows = []
        mins = {}
        for s in rw["steps"]:
            st = step_stats(s["code"], utr, registry=ctx.registry, pidx=pidx, fam_ext=ctx.fam_ext, weeks_active=wa,
                            no_of=no_of)
            sc = subagent_step(st, ctx.cfg, ctx.registry)
            mins[s["code"]] = st["minutes"]
            rows.append({"no": s["no"], "code": s["code"], "label": s["label"], "REP": sc["REP"], "IO": sc["IO"],
                         "TOOL": sc["TOOL"], "VER": sc["VER"], "RISK": sc["RISK"], "score": sc["score"],
                         "rule": sc["verdict"], "final": sc["verdict"], "flags": sc["flags"], "why": sc["why"],
                         "stats": {k: st[k] for k in ("weeks_active", "occ", "digital_share", "structured_share",
                                                      "tool_class_min", "rework_rate", "external_share", "money_hit")}})
        rule, fit_share = role_verdict([{"type": r["code"], "verdict": r["rule"]} for r in rows], mins, ctx.cfg)
        got = (answers or {}).get("sa:" + rid)
        ai = _ai_view(got[0], got[1], rw["steps"], {r["no"]: r for r in rows}) if got else None
        # 최종 판정에 드는 것은 코파일럿 의견(ai·manual)뿐 — 규칙 답(브리지 폴백)은 보여만 준다(규칙 판정이 정본, D-19)
        ai_v = ai["verdict"] if ai and ai["verdict"] and ai["by"] in ("ai", "manual") else None
        final = final_verdict(rule, ai_v)
        for r in rows:
            r["final"] = final_verdict(r["rule"], ai_v)
        by_no = {r["no"]: r for r in rows}
        for s in rw["steps"]:
            r = by_no.get(s["no"])
            if r is not None:
                s["subagent"] = r["final"]
                s["why"] = list(r["why"])
        chain = []
        # 체인 제안도 코파일럿 의견(ai·manual)의 구성안일 때만 그것을 쓴다 — 규칙 답(브리지 폴백)의 subs 는 보여 주기만 하고
        # 체인은 규칙 판정(적합·조건부 단계)에서 만든다(W2 통합: 폴백 단계 모듈이 생긴 뒤 규칙 답이 체인을 덮던 문제)
        if ai_v is not None and ai and ai["subs"]:
            seen = set()
            for sub in ai["subs"]:
                for n in sub["steps"]:
                    if n not in seen and sub["role"]:
                        seen.add(n)
                        chain.append({"step_no": n, "proposal": sub["role"][:40]})
        else:
            for r in rows:
                if r["final"] in ("적합", "조건부"):
                    chain.append({"step_no": r["no"], "proposal": f"{r['label']} 단계 보조"[:40]})
        out.append({"role_id": rid, "steps": rows, "rule": rule, "ai": ai, "final": final, "fit_share": fit_share,
                    "chain": sorted(chain, key=lambda x: x["step_no"]),
                    "basis": _basis_text(rows, fit_share)})
    return {"roles": out}


def _basis_text(rows: list[dict], fit_share: float) -> str:
    """판정 근거 한 줄(R §6.8): '적합 단계 분 비율 32% — 적합 단계 표 계산'."""
    fit = [r["label"] for r in rows if r["rule"] == "적합"]
    head = f"적합 단계 분 비율 {F.share_text(fit_share)}"
    return head + (f" — 적합 단계 {', '.join(fit)}" if fit else "")


def person_step_rows(ctx, roles_wf: Mapping[str, dict], traces: Mapping[str, Mapping[str, list]], pidx) -> dict:
    """사람 전체(모든 역할)의 단계 유형별 규칙 판정·플래그 — agentic 항목의 입출력 성격·새 니즈 조건(R §4.7.2 · §4.7.5)."""
    utr: dict[str, list] = {}
    for rid, rw in roles_wf.items():
        for uid in rw["units"]:
            if uid in ctx.units:
                utr.setdefault(uid, [])
                utr[uid] = utr[uid] + list(traces.get(rid, {}).get(uid, []))
    pairs = [(ctx.units[u], utr[u]) for u in sorted(utr)]
    wa = weeks_active(ctx.units.values())
    codes = sorted({s["code"] for rw in roles_wf.values() for s in rw["steps"]},
                   key=lambda k: (S.STEP_TYPES[k].order if k in S.STEP_TYPES else 99, k))
    out = {}
    for code in codes:
        st = step_stats(code, pairs, registry=ctx.registry, pidx=pidx, fam_ext=ctx.fam_ext, weeks_active=wa)
        sc = subagent_step(st, ctx.cfg, ctx.registry)
        out[code] = {"stats": st, "score": sc}
    return out
