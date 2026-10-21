# -*- coding: utf-8 -*-
"""외주 0 조건의 사내 조달안 찾기 — 역할별로 가능한 조합을 모두 따져 '새로 들이는 사람이 가장 적은 안'을 고른다.

입력: model27.py 를 빈 조달로 돌린 결과(역할·월 수요: 기준·보수) + method.json(램프·시민개발 비율)
조건(모델 점검과 같은 식):
  - 역할·월마다 수요(기준·보수 둘 다) ≤ 공급 × 1.1 + 0.05
  - AX·경력 채용이 있는 역할은 연간 가동률(기준 수요 ÷ 공급) ≥ 70%
  - 착수 기한(투입 월 − 리드) ≥ 오늘(2026-10 = −2)
  - 사내 한도: 공모 + 전환 ≤ 5명 · 겸직 동시 ≤ 2.0 FTE(줄마다 ≤ 1.0, ≤ 6개월) · 전사 지원 조직 동시 ≤ 1.0 FTE(≤ 6개월)
    · 일정 조정(AX) ≤ 0.4 FTE·4개월 · DRI 시민개발 ≤ CAE 수요의 35%
우선순위(비용): 새로 들이는 사람 100/명 · 경력 채용 현금 +10/명 · 겸직·전사 지원 조직 3/FTE·월 · '이번 달(10월) 착수' 필요 +40/줄 · 남는 공급 0.5/FTE·월
출력: design/final/sourcing_C.json (모델에 그대로 넣는 형식) — 검증은 model27.py 로."""
import argparse
import io
import itertools
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True, help="빈 조달로 돌린 model27 결과 JSON")
ap.add_argument("--out", default=os.path.join(HERE, "design", "final", "sourcing_C.json"))
ap.add_argument("--max-internal", type=int, default=5)
ap.add_argument("--kyum-cap", type=float, default=2.0)
ap.add_argument("--axt-cap", type=float, default=1.0)
ap.add_argument("--max-heads", type=int, default=99, help="새로 들이는 사람 합계(경력 채용 + 공모 + 전환) 한도")
ap.add_argument("--base-only", action="store_true", help="보수 수요 대신 기준 수요로만 맞춤 (비교용)")
ap.add_argument("--slack-w", type=float, default=0.5, help="남는 공급(FTE·월)에 매기는 비용")
A = ap.parse_args()

M = json.load(io.open(A.model, encoding="utf-8"))
METH = M["method"]
RAMP = {k: v["base"] for k, v in METH["hire_ramp"].items() if not k.startswith("_")}
LEAD = {"채용(경력)": 6, "사내 공모": 3, "사내 전환배치": 2, "사내 지원(겸직)": 1, "DRI 시민개발": 1, "DRI 팀 직접": 1, "전사 지원": 1, "일정 조정": 0,
        "A·B 개발 투입": 0}
SYS_CAP = M["dom_cap"]["DOM_SYS"]["people"] * 0.3  # 시스템 엔지니어 P0 30% — DRI 팀 직접 수행도 이 안에서
CZ = METH["citizen_dev_share"]["base"]
TODAY = -2
BASE = {r: [v["fte"] * v["avail"]] * 12 for r, v in M["supply"].items()}
DEM = M["demand"]
HI = M["hi_demand"]
HIRE_ROLES_UTIL = set()
AB_MAX = None  # AX 를 먼저 풀고 채운다

K2 = "사내 지원(겸직)#2"  # 같은 역할의 두 번째 겸직 구간 (다른 시기·다른 사람)
ROLE_KINDS = {
    "AI": ["채용(경력)", "사내 공모", "사내 전환배치", "사내 지원(겸직)", "A·B 개발 투입"],
    "DATA": ["채용(경력)", "사내 공모", "사내 전환배치", "사내 지원(겸직)", K2],
    "OPS": ["채용(경력)", "사내 공모", "사내 전환배치", "전사 지원", "사내 지원(겸직)"],
    "CAE": ["채용(경력)", "사내 전환배치", "DRI 시민개발"],
    "ML": ["채용(경력)", "사내 공모", "사내 지원(겸직)", "DRI 팀 직접"],
    "SIM": ["채용(경력)", "사내 전환배치", "사내 지원(겸직)", "DRI 팀 직접"],
    "MBSE": ["사내 전환배치", "사내 지원(겸직)", "DRI 팀 직접"],
    "AX": ["일정 조정", "전사 지원"],
}


def prof(kind, fte, s, e):
    r = RAMP.get(kind, [])
    v = [0.0] * 12
    for m in range(s, e + 1):
        k = m - s
        v[m - 1] = fte * (r[k] if k < len(r) else 1.0)
    return v


WIN6 = [(s, e) for s in range(1, 12) for e in range(s + 1, min(12, s + 5) + 1)]  # 2~6개월
WIN4 = [(s, e) for s in range(1, 10) for e in range(s + 1, min(12, s + 3) + 1)]


def options(role, kind):
    """(라인 목록, 공급 벡터, 비용 성분) 후보 — 라인이 없는 '안 씀'도 포함."""
    kind = kind.split("#")[0]
    out = [([], [0.0] * 12)]
    if kind in ("채용(경력)", "사내 공모", "사내 전환배치"):
        starts = [s for s in range(1, 7) if s - LEAD[kind] >= TODAY]
        ftes = [1.0] if role != "MBSE" else [0.6, 0.8, 1.0]
        for n in (1, 2, 3):
            for s in starts:
                for f in ftes:
                    if n > 1 and f < 1.0:
                        continue
                    line = dict(role=role, kind=kind, fte=float(n) * f if n == 1 else float(n), s=s, e=12)
                    out.append(([line], prof(kind, line["fte"], s, 12)))
    elif kind in ("사내 지원(겸직)", "전사 지원"):
        for f in (0.3, 0.5, 0.8, 1.0):
            for s, e in WIN6:
                out.append(([dict(role=role, kind=kind, fte=f, s=s, e=e)], prof(kind, f, s, e)))
    elif kind == "DRI 시민개발":
        for f in (0.2, 0.3, 0.4, 0.5):
            for s in range(1, 8):
                for e in range(s + 2, 13):
                    if all(f <= CZ * DEM["CAE"][m - 1] + 1e-9 for m in range(s, e + 1)):
                        out.append(([dict(role=role, kind=kind, fte=f, s=s, e=e, dom="DOM_CIR")], prof(kind, f, s, e)))
    elif kind == "DRI 팀 직접":
        for f in (0.3, 0.5, 0.8, 1.0, 1.5):
            for s_ in range(1, 12):
                for e in range(s_ + 1, 13):
                    if all(f + DEM["DOM_SYS"][m - 1] <= SYS_CAP + 1e-9 for m in range(s_, e + 1)):
                        out.append(([dict(role=role, kind=kind, fte=f, s=s_, e=e, dom="DOM_SYS")], prof(kind, f, s_, e)))
    elif kind == "A·B 개발 투입":  # 한 구간 또는 두 구간(앞, 뒤 양이 다름). A와 B 본업(AX)에 맞지 않는 모양은 뺀다
        shapes = [[(f, s_, e)] for f in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8) for s_ in range(1, 12) for e in range(s_ + 1, 13)]
        shapes += [[(f1, 1, m), (f2, m + 1, 12)] for f1 in (0.2, 0.3, 0.4, 0.5, 0.6) for f2 in (0.2, 0.3, 0.4, 0.5, 0.6, 0.8) for m in range(2, 12) if f1 != f2]
        for sh in shapes:
            v = [0.0] * 12
            for f, s_, e in sh:
                for m in range(s_, e + 1):
                    v[m - 1] += f
            if AB_MAX is not None and not any(all(v[m] <= sl[m] + 1e-9 for m in range(12)) for sl in AB_MAX):
                continue
            out.append(([dict(role=role, kind=kind, fte=f, s=s_, e=e) for f, s_, e in sh], v))
    elif kind == "일정 조정":
        for s, e in WIN4:
            out.append(([dict(role=role, kind=kind, fte=0.4, s=s, e=e)], prof(kind, 0.4, s, e)))
    return out


def heads(lines):
    return sum(int(round(x["fte"] + 0.499)) if x["kind"] in ("채용(경력)", "사내 공모", "사내 전환배치") else 0 for x in lines)


def usage(lines):
    k, a = [0.0] * 12, [0.0] * 12
    for x in lines:
        if x["kind"] == "사내 지원(겸직)":
            for m in range(x["s"], x["e"] + 1):
                k[m - 1] += x["fte"]
        if x["kind"] == "전사 지원":
            for m in range(x["s"], x["e"] + 1):
                a[m - 1] += x["fte"]
    return k, a


def internal(lines):
    return sum(int(round(x["fte"] + 0.499)) for x in lines if x["kind"] in ("사내 공모", "사내 전환배치"))


def cost(lines, supply_total, dem_total):
    c = 0.0
    for x in lines:
        n = int(round(x["fte"] + 0.499)) if x["kind"] in ("채용(경력)", "사내 공모", "사내 전환배치") else 0
        c += 100 * n
        if x["kind"] == "채용(경력)":
            c += 10 * n
        if x["kind"] in ("사내 지원(겸직)", "전사 지원", "DRI 시민개발", "DRI 팀 직접"):
            c += 3 * x["fte"] * (x["e"] - x["s"] + 1)
        if x["kind"] == "A·B 개발 투입":  # 이미 있는 사람 — 다른 팀에서 빌리는 겸직보다 먼저
            c += 1 * x["fte"] * (x["e"] - x["s"] + 1)
        if x["s"] - LEAD[x["kind"]] == TODAY:
            c += 40
    c += A.slack_w * max(0.0, supply_total - dem_total)
    return c


def need(role):
    if A.base_only:
        return list(DEM[role])
    return [max(DEM[role][i], HI[role][i]) for i in range(12)]


def feasible(role, sup):
    nd = need(role)
    for i in range(12):
        if nd[i] > sup[i] * 1.1 + 0.05 + 1e-9:
            return False
    return True


def line_cost(L):
    return cost(L, 0.0, 0.0)  # 줄 비용만 (남는 공급 항은 따로)


def solve_role(role, keep=400):
    import numpy as np
    kinds = ROLE_KINDS[role]
    base = np.array(BASE.get(role, [0.0] * 12))
    opts = [options(role, k) for k in kinds]
    # 큰 덩어리(채용·공모·전환)는 모두 펼치고, 시간 단위(겸직·전사 지원 조직·시민개발·일정 조정)는 행렬로 한 번에 검사
    big = [i for i, k in enumerate(kinds) if k in ("채용(경력)", "사내 공모", "사내 전환배치")]
    small = [i for i in range(len(kinds)) if i not in big]
    assert len(small) <= 2
    S = [np.array([o[1] for o in opts[i]]) for i in small]           # (n, 12)
    SC = [np.array([line_cost(o[0]) for o in opts[i]]) for i in small]
    res = []
    dem_total = sum(DEM[role])
    target0 = (np.array(need(role)) - 0.05) / 1.1 - 1e-9
    for combo in itertools.product(*[opts[i] for i in big]):
        lines = [l for o in combo for l in o[0]]
        if heads(lines) > A.max_heads or internal(lines) > A.max_internal:  # 한도를 넘는 조합은 어차피 못 씀 — 미리 빼야 남길 후보 자리를 차지하지 않는다
            continue
        sup = base + sum((np.array(o[1]) for o in combo), np.zeros(12))
        has_hire = any(x["kind"] == "채용(경력)" for x in lines)
        tgt = target0 - sup
        c0 = line_cost(lines)
        if not small:
            if (tgt <= 0).all():
                tot = sup.sum()
                if not (has_hire and dem_total / tot < 0.7):
                    res.append((c0 + A.slack_w * max(0.0, tot - dem_total), lines, list(sup)))
            continue
        util_cap = dem_total / 0.7 if has_hire else np.inf  # 가동률 70% → 공급 상한
        if len(small) == 1:
            ok = (S[0] >= tgt).all(axis=1)
            tot = sup.sum() + S[0].sum(axis=1)
            cm = c0 + SC[0] + A.slack_w * np.maximum(0.0, tot - dem_total)
            cm = np.where(ok & (tot <= util_cap), cm, np.inf)
            flat = cm
        else:
            ok = ((S[0][:, None, :] + S[1][None, :, :]) >= tgt).all(axis=2)
            if kinds[small[1]] == K2:  # 두 번째 겸직은 첫 번째가 끝난 뒤 시작 (중복 조합 제거)
                e1 = np.array([o[0][0]["e"] if o[0] else 99 for o in opts[small[0]]])
                s2 = np.array([o[0][0]["s"] if o[0] else 99 for o in opts[small[1]]])
                used2 = np.array([bool(o[0]) for o in opts[small[1]]])
                ok &= ~(used2[None, :] & (s2[None, :] <= e1[:, None]))
            tot = sup.sum() + S[0].sum(axis=1)[:, None] + S[1].sum(axis=1)[None, :]
            cm = c0 + SC[0][:, None] + SC[1][None, :] + A.slack_w * np.maximum(0.0, tot - dem_total)
            cm = np.where(ok & (tot <= util_cap), cm, np.inf)
            flat = cm.ravel()
        if not np.isfinite(flat).any():
            continue
        top = np.argsort(flat)[:16 if "A·B 개발 투입" in kinds else 8]  # 큰 덩어리 조합마다 가장 싼 것만 (A와 B 몫은 AX 와 맞물려 더 남김)
        idx = [np.unravel_index(t, cm.shape) for t in top if np.isfinite(flat[t])]
        for ij in idx:
            sm = sum(S[k][ij[k]] for k in range(len(small)))
            tot = float(sup.sum() + sm.sum())
            if has_hire and dem_total / tot < 0.7:
                continue
            c = c0 + sum(float(SC[k][ij[k]]) for k in range(len(small))) + A.slack_w * max(0.0, tot - dem_total)
            L = lines + [l for k in range(len(small)) for l in opts[small[k]][ij[k]][0]]
            res.append((c, L, list(sup + sm)))
    res.sort(key=lambda t: t[0])
    if role == "AX":  # A·B 몫은 다른 역할의 'A·B 개발 투입'과 맞물리므로 줄이지 않고 모두 남긴다
        return res
    # 역할 사이 한도 때문에 '사내 인원·채용 인원·겸직·전사 지원 조직 쓰는 양'별 최선안을 남긴다
    seen, out = {}, []
    for c, L, sup in res:
        k_, a_ = usage(L)
        ab_ = tuple((x["fte"], x["s"], x["e"]) for x in L if x["kind"] == "A·B 개발 투입")  # 모양이 다르면 AX 와 맞는지가 달라서 따로 남긴다
        key = (internal(L), heads(L) - internal(L), round(max(k_), 1), round(max(a_), 1), ab_)
        if seen.get(key, 0) >= 2:
            continue
        seen[key] = seen.get(key, 0) + 1
        out.append((c, L, sup))
    return out[:keep]


ROLES = [r for r in ["AX", "AI", "CAE", "ML", "SIM", "DATA", "OPS", "MBSE"] if r in DEM]  # 합쳐진 역할(예: DATA → AI)은 빠짐
cands = {}
for r in ROLES:
    cands[r] = solve_role(r)
    if r == "AX" and cands[r]:  # AX 후보마다 A와 B 가 달마다 개발에 내줄 수 있는 시간 — A와 B 개발 참여 모양은 이 가운데 하나에 맞아야 한다
        _t = [(n - 0.05) / 1.1 for n in need("AX")]
        AB_MAX = [[sup[m] - _t[m] for m in range(12)] for _, _, sup in cands[r]]
    print(r, "후보", len(cands[r]), "최소 비용", round(cands[r][0][0], 1) if cands[r] else None,
          [(x["kind"], x["fte"], x["s"], x["e"]) for x in cands[r][0][1]] if cands[r] else "불가")
    if not cands[r]:
        raise SystemExit(f"{r}: 사내 한도 안에서 불가")


# 역할 사이 한도(공모+전환 인원·겸직 동시·전사 지원 조직 동시)를 지키며 비용 최소 조합 — 분기 한정
order = sorted([r for r in ROLES if r != "AX"], key=lambda r: len(cands[r])) + (["AX"] if "AX" in ROLES else [])
AX_TGT = [(n - 0.05) / 1.1 for n in need("AX")] if "AX" in ROLES else None
minc = {r: cands[r][0][0] for r in ROLES}
best = [float("inf"), None]


def sys_use(lines):
    u = [0.0] * 12
    for x in lines:
        if x["kind"] == "DRI 팀 직접":
            for m in range(x["s"], x["e"] + 1):
                u[m - 1] += x["fte"]
    return u


def dfs(i, chosen, c, kyum, axt, inh, hd, sy):
    if c + sum(minc[r] for r in order[i:]) >= best[0]:
        return
    if i == len(order):
        best[0], best[1] = c, list(chosen)
        return
    r = order[i]
    ab = [0.0] * 12
    if r == "AX":
        for _, L0 in chosen:
            for x in L0:
                if x["kind"] == "A·B 개발 투입":
                    for m in range(x["s"], x["e"] + 1):
                        ab[m - 1] += x["fte"]
    for cc, L, sup in cands[r]:
        if r == "AX" and any(sup[m] - ab[m] < AX_TGT[m] - 1e-9 for m in range(12)):
            continue
        k, a = usage(L)
        k2 = [x + y for x, y in zip(kyum, k)]
        a2 = [x + y for x, y in zip(axt, a)]
        y2 = [x + y for x, y in zip(sy, sys_use(L))]
        n2 = inh + internal(L)
        h2 = hd + heads(L)
        if max(k2) > A.kyum_cap + 1e-9 or max(a2) > A.axt_cap + 1e-9 or n2 > A.max_internal or h2 > A.max_heads:
            continue
        if any(y2[m] + DEM["DOM_SYS"][m] > SYS_CAP + 1e-9 for m in range(12)):
            continue
        chosen.append((r, L))
        dfs(i + 1, chosen, c + cc, k2, a2, n2, h2, y2)
        chosen.pop()


dfs(0, [], 0.0, [0.0] * 12, [0.0] * 12, 0, 0, [0.0] * 12)
if not best[1]:
    raise SystemExit("한도 안의 조합이 없음 — 한도를 바꾸거나 일정·범위를 더 옮겨야 함")
lines = [x for r in ROLES for rr, L in best[1] if rr == r for x in L]
NOTE = {
    ("AI", "채용(경력)"): "LLM Agent·MCP 개발 경력", ("AI", "사내 공모"): "사내 SW 인력 공모(Python·서비스 개발)",
    ("AI", "사내 전환배치"): "사내 SW 인력 전환", ("AI", "사내 지원(겸직)"): "사내 SW 인력 겸직 — 6~8월 봉우리 전 보강",
    ("DATA", "사내 전환배치"): "IT·PLM 데이터 담당 전환 — PLM MCP·설계지식DB·GT", ("DATA", "채용(경력)"): "데이터 엔지니어 경력",
    ("DATA", "사내 공모"): "사내 데이터 인력 공모", ("DATA", "사내 지원(겸직)"): "IT·PLM 데이터 담당 겸직",
    ("OPS", "채용(경력)"): "LLM 서빙·MLOps 경력", ("OPS", "사내 전환배치"): "사내 인프라 경험자 전환 — 브리지·게이트웨이·온프렘",
    ("OPS", "사내 공모"): "사내 인프라 인력 공모", ("OPS", "전사 지원"): "전사 지원 조직 — 브리지·게이트웨이 구성", ("OPS", "사내 지원(겸직)"): "사내 인프라 경험자 겸직 — 온프렘 이관",
    ("CAE", "사내 전환배치"): "해석 스크립트 경험자 전환", ("CAE", "DRI 시민개발"): "현업 회로 엔지니어가 SI/PI·EMC 후처리 스크립트를 바이브 코딩으로",
    ("CAE", "채용(경력)"): "PyAnsys 자동화 경력",
    ("ML", "사내 공모"): "사내 비전·인지 ML 인력 공모", ("ML", "채용(경력)"): "3D 인지·Sim2Real 경력", ("ML", "사내 지원(겸직)"): "사내 인지 SW 경험자 겸직 — GT 규격",
    ("SIM", "사내 지원(겸직)"): "VV-1 플랫폼 개발자 추가 투입(VV-1 DRI 팀)", ("SIM", "사내 전환배치"): "시뮬레이션 경험자 전환", ("SIM", "채용(경력)"): "LiDAR 시뮬레이션 경력",
    ("MBSE", "사내 지원(겸직)"): "시스템 엔지니어 겸직 — RVTM(Capella)", ("MBSE", "사내 전환배치"): "시스템 엔지니어 MBSE 전환",
    ("SIM", "DRI 팀 직접"): "VV-1 DRI 팀이 센서모델·ODD 를 직접 — P0 30% 안", ("ML", "DRI 팀 직접"): "VV-1 DRI 팀이 학습·검증을 직접 — P0 30% 안",
    ("MBSE", "DRI 팀 직접"): "시스템 엔지니어가 RVTM 을 직접 — P0 30% 안",
    ("AX", "일정 조정"): "A·B 100% — CO-1·P1·P2·CT 업무를 뒤로", ("AX", "전사 지원"): "전사 지원 조직 — 거버넌스·보안 승인 패키지 일부",
}


def ym(m):
    return f"'{27 if m >= 1 else 26}.{m if m >= 1 else 12 + m}"


for x in lines:
    sb = x["s"] - LEAD[x["kind"]]
    n = NOTE.get((x["role"], x["kind"]), "")
    if x["kind"] in ("채용(경력)", "사내 공모", "사내 전환배치"):
        n += f" — {ym(sb)} " + {"채용(경력)": "품의", "사내 공모": "공고", "사내 전환배치": "협의"}[x["kind"]] + f" → {ym(x['s'])} 투입"
    if sb == TODAY:
        n += " · 이번 달(10월) 착수 필요"
    x["note"] = n
os.makedirs(os.path.dirname(A.out), exist_ok=True)
io.open(A.out, "w", encoding="utf-8", newline="\n").write(json.dumps(dict(sourcing=lines), ensure_ascii=False, indent=1))
print("비용", round(best[0], 1), "· 새로 들이는 사람", heads(lines), "· 공모+전환", internal(lines))
for x in lines:
    print(f"  {x['role']:5} {x['kind']:10} {x['fte']:.1f} {x['s']:>2}~{x['e']:<2} {x['note']}")
