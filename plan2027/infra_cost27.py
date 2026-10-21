# -*- coding: utf-8 -*-
"""2027 인프라·비용 모델 — model27.json(인력·조달) + RATES(단가 조사) → infra_cost27.json.
단가는 보수(hi)·기준(base)·낙관(lo) 3값. 계산은 base, 시나리오 합계는 hi·lo 로 같이 낸다."""
import argparse
import io
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--model", default=os.path.join(HERE, "model27.json"))
ap.add_argument("--out", default=os.path.join(HERE, "infra_cost27.json"))
ap.add_argument("--quiet", action="store_true")
ARGS = ap.parse_args()
M = json.load(io.open(ARGS.model, encoding="utf-8"))
R = json.load(io.open(os.path.join(HERE, "rates.json"), encoding="utf-8"))  # 단가 조사 결과를 옮긴 파일
OPT = M.get("option", "A")
EOK = 1e8


def rate(k, which="base"):
    return R[k][which]


# ---------------------------------------------------------------- 인건비 — 증분(새로 나가는 돈) vs 기존 인력(기회비용)
def mm_by_q(fte, s, e):
    q = [0.0] * 4
    for m in range(max(1, s), e + 1):
        q[(m - 1) // 3] += fte
    return q


lines = []
KIND_RATE = {"채용(경력)": "hire_senior_mm"}  # 새로 나가는 인건비는 경력 채용뿐 — 외주 없음, 나머지 조달은 사내 인력(기회비용)
ROLE_NAME = {r["id"]: r["name"] for r in M["roles"]}


def heads(x):
    # 채용은 사람 단위로 돈이 나간다 — 3과제 배분이 0.6 이어도 1명분 급여
    return math.ceil(x["fte"] - 1e-9)


def people_lines(which="base"):
    out = []
    for x in M["sourcing"]:
        k = KIND_RATE.get(x["kind"])
        if not k:
            continue
        n = heads(x)
        q = mm_by_q(n, x["s"], x["e"])
        unit = rate(k, which)
        months = x["e"] - max(1, x["s"]) + 1
        who = f"{n}명"
        basis = f"{n}명 × {months}개월 × {unit/1e4:,.0f}만원 ({R[k]['label']})"
        if n > x["fte"]:
            basis += f" · 3과제 몫 {x['fte']} FTE, 나머지는 P1·P2"
        out.append(dict(cat="인건비 · 증분", item=f"{ROLE_NAME[x['role']]} — {x['kind']} {who}",
                        q=[round(v * unit) for v in q], basis=basis))
    for it in R.get("people_extra", []):
        cnt = [0, 0, 0, 0]
        for x in M["sourcing"]:
            if KIND_RATE.get(x["kind"]):
                cnt[(max(1, x["s"]) - 1) // 3] += heads(x)
        if sum(cnt):
            out.append(dict(cat="인건비 · 증분", item=it["item"], q=[round(c * it[which]) for c in cnt], basis=f"{sum(cnt)}명 × {it[which]/1e4:,.0f}만원 — {it['basis']}"))
    return out


# 기존 인력 투입(기회비용) — AX A·B·DRI 도메인·DRI 개발자·사내 전환·공모·겸직·시민개발·전사 지원
def internal_mm():
    q = [0.0] * 4
    for r, rows in M["demand"].items():
        if r.startswith("DOM_"):
            for i, v in enumerate(rows):
                q[i // 3] += v
    dom = q[:]
    sup = M["supply"]
    base = [0.0] * 4
    for r in ("AX", "CAE", "SIM"):
        s = sup.get(r)
        if s:
            for i in range(12):
                base[i // 3] += s["fte"] * s["avail"]
    tr = [0.0] * 4
    for x in M["sourcing"]:
        if x["kind"] not in KIND_RATE:
            qq = mm_by_q(x["fte"], x["s"], x["e"])
            tr = [a + b for a, b in zip(tr, qq)]
    return dom, base, tr


# ---------------------------------------------------------------- 인프라 — 수요에서 규모 산정
TOK = R["token_demand"]  # 빅플랜 p.24 기반 월 토큰
INF = R["infra"]
# 남긴 작업이 쓰지 않는 장비는 2027 에 사지 않는다 (범위를 줄여 '28 로 넘긴 작업만 쓰는 장비 → '28 증설과 함께 기안)
KEPT = {w["id"] for w in M["wp"]}
MOVED = [it["item"] for it in INF["capex"] if it.get("needs_wp") and not KEPT & set(it["needs_wp"])]
SERVERS = 2 - sum(1 for it in INF["capex"] if it["item"] in MOVED and "서버" in it["item"])


def build(which="base"):
    L = people_lines(which)
    dom, base, tr = internal_mm()
    im = rate("internal_mm", which)
    internal = [dict(cat="기존 인력 · 기회비용", item="도메인 전문가 시간 (DRI 팀)", q=[round(v * im) for v in dom], basis=f"{sum(dom):.1f} MM × 내부 단가"),
                dict(cat="기존 인력 · 기회비용", item="AX A·B · DRI 개발자 (기본 공급)", q=[round(v * im) for v in base], basis=f"{sum(base):.1f} MM × 내부 단가"),
                dict(cat="기존 인력 · 기회비용", item="사내 전환·공모·겸직·시민개발·전사 지원", q=[round(v * im) for v in tr], basis=f"{sum(tr):.1f} MM × 내부 단가")]
    # 인프라 capex — 납품 분기에 집행
    capex = []
    for it in INF["capex"]:
        if it["item"] in MOVED:
            continue
        v = it[which] * (SERVERS / 2 if it.get("per_server") else 1)
        q = [0, 0, 0, 0]
        q[it["q"] - 1] = v
        capex.append(dict(cat="인프라 · 투자(CAPEX)", item=it["item"], q=q, basis=it["basis"]))
    for it in R.get("method_capex", {}).get(OPT, []):
        q = [0, 0, 0, 0]
        q[it["q"] - 1] = it[which]
        capex.append(dict(cat="인프라 · 투자(CAPEX)", item=it["item"], q=q, basis=it["basis"]))
    opex = []
    for it in INF["opex"]:
        if (it.get("opt") and it["opt"] != OPT) or OPT in it.get("opt_not", []):
            continue
        q = [round(it[which] * (SERVERS / 2 if it.get("per_server") else 1) * n) for n in it["months_by_q"]]
        opex.append(dict(cat="인프라 · 운영(OPEX)", item=it["item"].replace("서버 2대", f"서버 {SERVERS}대"), q=q, basis=it["basis"]))
    for it in R.get("method_opex", {}).get(OPT, []):
        if it.get("per_dev"):
            dev = dev_heads()
            q = [0.0] * 4
            for i in range(12):
                if i + 1 >= it.get("from", 1):
                    q[i // 3] += dev[i] * it[which]
            n0, n1 = min(v for v in dev if v), max(dev)
            opex.append(dict(cat="개발 도구 · 운영(OPEX)", item=it["item"], q=[round(v) for v in q],
                             basis=f"개발 인원 {n0}~{n1}명 × 월 {it[which]/1e4:,.0f}만원 — {it['basis']}"))
        else:
            opex.append(dict(cat="개발 도구 · 운영(OPEX)", item=it["item"], q=[round(it[which] * n) for n in it["months_by_q"]], basis=it["basis"]))
    return L, internal, capex, opex


def dev_heads():
    """월별 코딩 도구 사용 인원 — A·B 2명 + DRI 개발자(CAE·시뮬레이션 각 1명) + 조달 인원(머릿수)."""
    n = [2 + 2] * 12
    for x in M["sourcing"]:
        if x["kind"] == "일정 조정":
            continue
        for m in range(max(1, x["s"]), x["e"] + 1):
            n[m - 1] += math.ceil(x["fte"] - 1e-9)
    return n


def qsum(rows):
    return [sum(r["q"][i] for r in rows) for i in range(4)]


base = build("base")
hi = build("hi")
lo = build("lo")
L, internal, capex, opex = base
cash = L + capex + opex
lines = []
for grp in (L, capex, opex):
    lines += grp
    lines.append(dict(cat="", item="소계", q=qsum(grp), tot=True))
lines.append(dict(cat="증분 현금 합계", item="새로 나가는 돈 (인건비 증분 + 투자 + 운영)", q=qsum(cash), tot=True))
lines += internal
lines.append(dict(cat="", item="기존 인력 투입 합계 (현금 아님)", q=qsum(internal), tot=True))

tot_cash = {k: sum(qsum(b[0] + b[2] + b[3])) for k, b in (("base", base), ("hi", hi), ("lo", lo))}
tot_people = {k: sum(qsum(b[0])) for k, b in (("base", base), ("hi", hi), ("lo", lo))}
tot_capex = {k: sum(qsum(b[2])) for k, b in (("base", base), ("hi", hi), ("lo", lo))}
tot_opex = {k: sum(qsum(b[3])) for k, b in (("base", base), ("hi", hi), ("lo", lo))}
tot_int = sum(qsum(internal))

eok = lambda v: f"{v/EOK:.1f}"
cost = dict(
    tiles=[dict(k="증분 현금 (기준)", v=eok(tot_cash["base"]), u="억", d=f"보수 {eok(tot_cash['hi'])} · 낙관 {eok(tot_cash['lo'])}억"),
           dict(k="인건비 증분", v=eok(tot_people["base"]), u="억", d="경력 채용 · 수수료 (외주 없음)"),
           dict(k="인프라 투자", v=eok(tot_capex["base"]), u="억", d="온프렘 추론 · 스토리지 · 네트워크"),
           dict(k="인프라 운영", v=eok(tot_opex["base"]), u="억", d="전력 · 라이선스 · API · 개발 도구"),
           dict(k="기존 인력 투입", v=eok(tot_int), u="억", d="현금 아님 — 내부 단가 환산")],
    lines=lines, rates=R["rate_table"], points=R["cost_points"])

# 인프라 표·비용 메모의 빈칸 — 계산값으로 채운다 (손으로 쓴 합계가 계산과 어긋나지 않게)
capex_tot = tot_capex["base"]
opex_run = sum(it["base"] * 12 * (SERVERS / 2 if it.get("per_server") else 1) for it in INF["opex"]
               if (not it.get("opt") or it["opt"] == OPT) and OPT not in it.get("opt_not", []))  # 가동 후 1년치 (개발 도구 제외)
depr = capex_tot / 5
people_cash = tot_people["base"]
hire_lines = [x for x in M["sourcing"] if x["kind"] == "채용(경력)"]
hire_heads = sum(math.ceil(x["fte"] - 1e-9) for x in hire_lines)
tools_cash = sum(sum(r["q"]) for r in opex if r["cat"].startswith("개발 도구"))
fill = {"{CAPEX}": f"{capex_tot/EOK:.1f}억", "{OPEX_RUN}": f"연 {opex_run/EOK:.1f}억 ('27 {tot_opex['base']/EOK:.1f}억)", "{DEPR}": f"{depr/EOK:.2f}억",
        "{DEPR27}": f"{depr/2/EOK:.2f}억", "{PEOPLE_SHARE}": f"{people_cash/tot_cash['base']*100:.0f}%",
        "{HIRES}": f"{hire_heads}명", "{TOOLS}": f"{tools_cash/EOK:.2f}억"}


def fill_s(t):
    for k, v in fill.items():
        t = t.replace(k, v)
    return t


infra = json.loads(fill_s(json.dumps(R["infra_page"], ensure_ascii=False)))
cost["points"] = [fill_s(p) for p in cost["points"]]
summary_tiles = [dict(k="2027 증분 현금", v=eok(tot_cash["base"]), u="억", d=f"인건비 {eok(tot_people['base'])} · 투자 {eok(tot_capex['base'])} · 운영 {eok(tot_opex['base'])}억")]
out = dict(cost=cost, infra=infra, summary_tiles=summary_tiles, assumptions=R.get("assumptions", []), checks=R.get("checks", []), moved=MOVED, servers=SERVERS,
           totals=dict(cash=tot_cash, people=tot_people, capex=tot_capex, opex=tot_opex, internal=tot_int, tools=tools_cash,
                       opex_run=opex_run, depr=depr, hires=hire_heads, option=OPT))
io.open(ARGS.out, "w", encoding="utf-8").write(json.dumps(out, ensure_ascii=False, indent=1))
if ARGS.quiet:
    print(json.dumps({k: round(v / EOK, 2) for k, v in tot_cash.items()}))
    raise SystemExit
print("cash", {k: eok(v) for k, v in tot_cash.items()}, "people", {k: eok(v) for k, v in tot_people.items()},
      "capex", {k: eok(v) for k, v in tot_capex.items()}, "opex", {k: eok(v) for k, v in tot_opex.items()}, "internal", eok(tot_int))
print({k: v for k, v in fill.items()})
