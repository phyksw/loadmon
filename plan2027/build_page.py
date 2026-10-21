# -*- coding: utf-8 -*-
"""리소스 플랜 HTML 빌드 (v4, 새 인원 3명 계획).
- 본안: 혼합안(C) + design/final/sourcing_3p.json(scope_fit.py 결과: 조달 + 2028 로 넘긴 작업) + method_3p.json
- 비교: 운영안 1안·2안은 같은 범위로(options_3p.py), 사람 수는 4명(scope_fit --heads 4)·10명(전체 범위, scenarios.json)과 비교
- 마지막에 가운뎃점·줄표를 걸러 낸다(사용자 요청: 읽기 쉬운 문장)."""
import io
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FIN = os.path.join(HERE, "design", "final")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
REPORTS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "reports")  # 프로젝트 reports 폴더 (없으면 건너뜀)


def pick_file(*names):
    for n in names:
        p = os.path.join(FIN, n)
        if os.path.isfile(p):
            return p
    return None


METH_FILE = pick_file("method_3p.json", "method_C.json") or os.path.join(HERE, "method.json")
METH = json.load(io.open(METH_FILE, encoding="utf-8"))
PICK = METH["pick"]
SRC = {"C": pick_file("sourcing_3p.json", "sourcing_C.json"), "A": pick_file("sourcing_A_3p.json"), "B": pick_file("sourcing_B_3p.json")}
for _k in ("A", "B"):  # 1안, 2안 조달안(options_3p.py)이 아직 없으면 같은 범위에 빈 조달로 (표의 인원은 0 으로 보임)
    if not SRC[_k]:
        print(f"주의: sourcing_{_k}_3p.json 없음, options_3p.py 를 먼저 돌릴 것")
        SRC[_k] = os.path.join(OUT, f"tmp_src_{_k}.json")
        io.open(SRC[_k], "w", encoding="utf-8").write(json.dumps({"sourcing": [], "defer": json.load(io.open(SRC["C"], encoding="utf-8")).get("defer", [])}, ensure_ascii=False))


def run(opt, level="base", src=None, tag=None, cost=True):
    tag = tag or f"{opt}_{level}"
    mo, co = os.path.join(OUT, f"model27_{tag}.json"), os.path.join(OUT, f"cost27_{tag}.json")
    a = [PY, "model27.py", "--option", opt, "--vibe", level, "--method", METH_FILE, "--out", mo, "--quiet"]
    src = src if src is not None else SRC.get(opt)
    if src:
        a += ["--sourcing", src]
    subprocess.run(a, cwd=HERE, check=True, env=ENV, capture_output=True)
    m = json.load(io.open(mo, encoding="utf-8"))
    if not cost:
        return m, None
    subprocess.run([PY, "infra_cost27.py", "--model", mo, "--out", co, "--quiet"], cwd=HERE, check=True, env=ENV, capture_output=True)
    return m, json.load(io.open(co, encoding="utf-8"))


PURPOSE = {"C4": ["V4", "V5"]}  # 이 작업들만을 위한 준비 작업 — 모두 넘겼으면 함께 넘긴다 (scope_fit.py 와 같은 규칙)


def with_purpose(path, tag):
    j = json.load(io.open(path, encoding="utf-8"))
    d = list(j.get("defer", []))
    add = [k for k, ps in PURPOSE.items() if d and all(p in d for p in ps) and k not in d]
    if not add:
        return path
    j["defer"] = d + add
    p2 = os.path.join(OUT, f"src_{tag}.json")
    io.open(p2, "w", encoding="utf-8").write(json.dumps(j, ensure_ascii=False))
    return p2


OPT_INF = {k: json.load(io.open(SRC[k], encoding="utf-8")).get("infeasible") for k in ("A", "B")}
SRC = {k: with_purpose(v, k) for k, v in SRC.items()}  # 8명까지 해가 없으면 표에 그렇게 적는다
RUNS = {k: run(k) for k in ("A", "B", "C")}
M, IC = RUNS[PICK]
shutil.copyfile(os.path.join(OUT, f"model27_{PICK}_base.json"), os.path.join(HERE, "model27.json"))
shutil.copyfile(os.path.join(OUT, f"cost27_{PICK}_base.json"), os.path.join(HERE, "infra_cost27.json"))
_empty = os.path.join(OUT, "empty_src.json")
io.open(_empty, "w", encoding="utf-8").write(json.dumps({"sourcing": []}))
M_FULL, _ = run(PICK, src=_empty, tag="full_scope", cost=False)  # 넘기기 전 전체 범위 — 넘긴 작업의 마일스톤·Agent 찾기용
EOK = 1e8
f1 = lambda v: f"{v:.1f}"
DEV = [r["id"] for r in M["roles"] if r["id"] != "AX" and not r["id"].startswith("DOM_")]
ROLE_NAME = {r["id"]: r["name"] for r in M["roles"]}
ROLE_SHORT = {"AI": "AI 엔지니어", "CAE": "CAE 자동화 엔지니어", "ML": "ML 엔지니어", "SIM": "시뮬레이션 엔지니어", "DATA": "데이터 엔지니어", "OPS": "MLOps 엔지니어", "MBSE": "MBSE 엔지니어", "AX": "AX"}
ROLE_TINY = {"AI": "AI", "CAE": "CAE", "ML": "ML", "SIM": "시뮬레이션", "DATA": "데이터", "OPS": "MLOps", "MBSE": "MBSE", "AX": "A와 B",
             "DOM_ANA": "해석", "DOM_CIR": "회로", "DOM_MEC": "기구", "DOM_OPT": "광학", "DOM_SYS": "시스템"}  # 작업 표 아래 줄용
NEW_KINDS = ("채용(경력)", "사내 공모", "사내 전환배치")
BORROW_KINDS = ("사내 지원(겸직)", "전사 지원", "DRI 시민개발", "DRI 팀 직접", "A·B 개발 투입")


def mlabel(m):
    return f"'27.{m}" if m >= 1 else f"'26.{12 + m}"


def mtext(m):  # 문장 안에서는 풀어 쓴다
    return f"2027년 {m}월" if m >= 1 else f"2026년 {12 + m}월"


def eul(x):  # 을/를 — 끝 글자 받침, 숫자는 읽는 소리로
    c = x.strip()[-1]
    if "가" <= c <= "힣":
        return "을" if (ord(c) - 0xAC00) % 28 else "를"
    return "를" if c in "2459" else "을"


def ym(lbl):  # '2026-11' → "'26.11"
    y, m = lbl.split("-")
    return f"'{y[2:]}.{int(m)}"


def heads(src, kinds):
    return sum(math.ceil(x["fte"] - 1e-9) for x in src if x["kind"] in kinds)


def fte_months(src, kinds):
    return sum(x["fte"] * (x["e"] - max(1, x["s"]) + 1) for x in src if x["kind"] in kinds)


def new_heads(m):
    s = m["sourcing"]
    return heads(s, ("채용(경력)",)), heads(s, ("사내 공모",)), heads(s, ("사내 전환배치",))


tot = M["totals"]
src = M["sourcing"]
NOTE_TXT = {
    ("AI", "사내 전환배치"): "사내 SW 인력 전환", ("AI", "사내 지원(겸직)"): "사내 SW 인력 겸직", ("AI", "A·B 개발 투입"): "A와 B 가 본업 뒤 남는 시간에",
    ("CAE", "사내 전환배치"): "해석 스크립트 경험자 전환", ("CAE", "DRI 시민개발"): "현업 회로 엔지니어가 SI/PI, EMC 후처리 스크립트를 바이브 코딩으로",
    ("ML", "사내 지원(겸직)"): "사내 인지 SW 경험자 겸직 (GT 규격)", ("ML", "DRI 팀 직접"): "VV-1 DRI 팀이 학습과 검증을 직접 (업무 시간 30% 안)",
    ("SIM", "DRI 팀 직접"): "VV-1 DRI 팀이 센서모델과 ODD 를 직접 (업무 시간 30% 안)", ("SIM", "사내 지원(겸직)"): "VV-1 플랫폼 개발자 추가 투입",
    ("OPS", "사내 전환배치"): "사내 인프라 경험자 전환 (브리지, 게이트웨이, 온프렘)", ("OPS", "전사 지원"): "전사 지원 조직 (브리지와 게이트웨이 구성)",
    ("OPS", "사내 지원(겸직)"): "사내 인프라 경험자 겸직 (온프렘 이관)",
    ("MBSE", "사내 지원(겸직)"): "시스템 엔지니어 겸직 (RVTM, Capella)", ("MBSE", "DRI 팀 직접"): "시스템 엔지니어가 RVTM 을 직접 (업무 시간 30% 안)",
    ("AX", "일정 조정"): "CO-1, P1, P2, CT 업무를 뒤로 미룸", ("AX", "전사 지원"): "전사 지원 조직 (거버넌스와 보안 승인 일부)",
}
for x in src:
    x["start_txt"] = ym(x["start_by_label"])
    x["note"] = NOTE_TXT.get((x["role"], x["kind"]), x.get("note", "").split(" — ")[0])
    if x["kind"] in ("채용(경력)", "사내 공모", "사내 전환배치"):
        x["note"] += f". {x['start_txt']} 협의, {mlabel(x['s'])} 투입"
H, P_, T_ = new_heads(M)
NEW = H + P_ + T_
dem_ax_dev = [sum(M["demand"][r][i] for r in DEV + ["AX"]) for i in range(12)]
dem_dom = [sum(v[i] for k, v in M["demand"].items() if k.startswith("DOM_")) for i in range(12)]
peak_total = max(sum(M["demand"][r][i] for r in M["demand"]) for i in range(12))
dom_mm = sum(dem_dom)
ax_mm = tot["role"]["AX"]
axs = M["axs"]
parts = M["parts"]
borrow = fte_months(src, BORROW_KINDS)
AX_DEV = [round(sum(x["fte"] for x in src if x["kind"] == "A·B 개발 투입" and x["s"] <= m <= x["e"]), 3) for m in range(1, 13)]
_adj = [x for x in src if x["kind"] == "일정 조정"]
AX_FULL = [min(x["s"] for x in _adj), max(x["e"] for x in _adj)] if _adj else None  # A와 B 가 100% 투입하는 달
AXF = f"{AX_FULL[0]}~{AX_FULL[1]}월 100%" if AX_FULL else "100% 투입 없음"

# ---------------------------------------------------------------- 넘긴 작업 (2028)
SCOPE = json.load(io.open(pick_file("scope_3p.json"), encoding="utf-8")) if pick_file("scope_3p.json") else dict(order=[], defer=[])
RANK = {x["id"]: (i + 1, x["why"]) for i, x in enumerate(SCOPE.get("order", []))}
WPF = {w["id"]: w for w in M_FULL["wp"]}
MSL = {m["ref"]: m["label"] for m in M_FULL["ms27"]}
KEPT = {w["id"] for w in M["wp"]}
DEF_IDS = {d["id"] for d in M.get("deferred", [])}
# 마일스톤: 걸린 작업이 모두 남으면 지킴, 일부만 남으면 일부, 하나도 없으면 2028년으로
MS_WPS = {}
for w in M_FULL["wp"]:
    for r in w["ms"]:
        MS_WPS.setdefault(r, []).append(w["id"])
MS_STATE = {}
for m in M_FULL["ms27"]:
    ws = MS_WPS.get(m["ref"], [])
    k = [x for x in ws if x in KEPT]
    MS_STATE[m["ref"]] = "kept" if ws and len(k) == len(ws) else ("part" if k else "gone")
n_ms = len(M_FULL["ms27"])
n_kept = sum(1 for v in MS_STATE.values() if v == "kept")
n_part = sum(1 for v in MS_STATE.values() if v == "part")
n_gone = n_ms - n_kept - n_part
AG_WPS = {}
for w in M_FULL["wp"]:
    for a in w["ag"]:
        AG_WPS.setdefault(a, []).append(w["id"])
AG_GONE = {a for a, ws in AG_WPS.items() if not any(x in KEPT for x in ws)}


def ms_txt(r):
    return MSL[r] + (" (일부)" if MS_STATE[r] == "part" else "")


def why_txt(wid):
    if wid in PURPOSE:
        return ", ".join(PURPOSE[wid]) + eul(PURPOSE[wid][-1]) + " 넘겨서 함께 (그 준비 작업)"
    gone_pred = [p for p in WPF.get(wid, {}).get("after", []) if p in DEF_IDS]
    if gone_pred:
        return "선행 작업 " + ", ".join(gone_pred) + eul(gone_pred[-1]) + " 넘겨서 함께"
    return RANK.get(wid, (0, ""))[1]


defer_rows = []
for d in sorted(M.get("deferred", []), key=lambda d: RANK.get(d["id"], (99, ""))[0]):
    w = WPF.get(d["id"], {})
    defer_rows.append(dict(rank=RANK.get(d["id"], ("", ""))[0], id=d["id"], name=d["name"], task=d["task"], mm=sum(w.get("eff", {}).values()) or d["mm"],
                           ms=", ".join(ms_txt(r) for r in w.get("ms", []) if r in MSL),
                           ag=", ".join(a + ("" if a in AG_GONE else " (확장만)") for a in w.get("ag", [])), why=why_txt(d["id"])))
defer_mm = sum(r["mm"] for r in defer_rows)
_agc = next((c for c in M["checks"] if c["id"] == "ag"), dict(detail=[], of=0))
defer_ag = [d.split(" ")[0] for d in _agc["detail"]]
n_ag = _agc["of"]

# 4명이면
M4 = IC4 = None
if pick_file("sourcing_4p.json") and not os.environ.get("SKIP_4P"):  # 4명 계산이 아직이면 SKIP_4P=1 로 빼고 만든다
    M4, IC4 = run(PICK, src=with_purpose(pick_file("sourcing_4p.json"), "h4"), tag="h4")


def ms_quarters(task):
    q = ["", "", "", ""]
    for m in M_FULL["ms27"]:
        if m["task"] != task:
            continue
        lab = m["label"] + {"kept": "", "part": " (일부는 2028년으로)", "gone": " (2028년으로)"}[MS_STATE[m["ref"]]]
        d = m["date"]
        if "-Q" in d:
            i = int(d[-1]) - 1
            q[i] = (q[i] + ", " if q[i] else "") + lab
        elif d.endswith("H1"):
            q[1] = (q[1] + ", " if q[1] else "") + "(상반기) " + lab
        elif d.endswith("H2"):
            q[3] = (q[3] + ", " if q[3] else "") + "(하반기) " + lab
    return q


task_order = [
    dict(code="AL-1", title="AL-1 자율 설계와 해석 (해석 자동화 플랫폼)", sub="DRI C엔지니어. 3과제가 함께 쓰는 해석 창구. 목표: 해석 L/T 4시간을 0.1시간으로('28 전 도메인)", quarters=ms_quarters("AL-1")),
    dict(code="VV-1", title="VV-1 LiDAR 가상검증 플랫폼", sub="DRI D엔지니어. LLM 보다 시뮬레이션과 ML 이 중심. 목표: ODD 커버리지 40%('27), 70%('28)", quarters=ms_quarters("VV-1")),
    dict(code="VV-3", title="VV-3 MBSE 하드웨어 선검증 (회로와 기구)", sub="DRI C엔지니어. 해석은 AL-1 플랫폼의 플러그인으로, 추적은 MBSE 로. 목표: 시제품 3차를 1~2차로('28)", quarters=ms_quarters("VV-3")),
    dict(code="공통", title="공통 기반 (플랫폼, 개발 방법, 운영)", sub="온프렘 LLM 과 런타임, 바이브 코딩 도입, 외부 MCP 검증, 이식 계층, 학습, 거버넌스, 투자심의 (CO-1 은 이 계획 밖)", quarters=None),
]

# ---------------------------------------------------------------- 결정 기한
def who_list(kinds):
    out = []
    for x in src:
        if x["kind"] in kinds:
            out.append(f"{ROLE_SHORT.get(x['role'], x['role'])} {math.ceil(x['fte'] - 1e-9)}명" if x["kind"] in NEW_KINDS else
                       f"{ROLE_SHORT.get(x['role'], x['role'])} {x['fte']:g}명분({x['s']}~{x['e']}월)")
    return ", ".join(out)


KIND_LIST = {"사내 지원(겸직)": "겸직", "DRI 팀 직접": "DRI 팀 직접 수행", "DRI 시민개발": "현업 시민개발", "전사 지원": "전사 지원"}
KIND_SAY = {"사내 지원(겸직)": "겸직", "전사 지원": "전사 지원", "DRI 시민개발": "현업 시민개발", "DRI 팀 직접": "DRI 팀 직접 수행", "A·B 개발 투입": "A와 B 의 개발 참여", "일정 조정": "A와 B 100% 투입",
            "사내 전환배치": "사내 전환", "사내 공모": "사내 공모", "채용(경력)": "경력 채용"}
_bl = {}
for x in src:
    if x["kind"] in KIND_LIST:
        _bl.setdefault(KIND_LIST[x["kind"]], []).append(ROLE_TINY.get(x["role"], x["role"]))
borrow_say = ", ".join(f"{k}({', '.join(dict.fromkeys(v))})" for k, v in _bl.items())
if AX_FULL:
    borrow_say += f", A와 B 의 {AX_FULL[0]}~{AX_FULL[1]}월 100% 투입"
if any(AX_DEV):
    borrow_say += ", A와 B 의 개발 참여"
first_new = min([x["s"] for x in src if x["kind"] in NEW_KINDS] or [1])
_nk = {x["kind"] for x in src if x["kind"] in NEW_KINDS}
_how = " (모두 사내 전환)" if _nk == {"사내 전환배치"} else ""
_slips = (M.get("scen") or {}).get("nobridge", {}).get("slips", [])
_bridge_why = ("자체 온프렘 서버는 2027년 7월에 가동합니다. 그 전에 도면과 BOM 같은 반출 금지 자료(C3)를 다룰 임시 GPU 가 없으면 "
               + (", ".join(x["label"] for x in _slips) + f" 마일스톤이 {min(x['slip'] for x in _slips)}~{max(x['slip'] for x in _slips)}개월 늦어집니다." if _slips
                  else "C3 자료를 쓰는 작업이 자체 서버 가동까지 멈춥니다."))
decisions = [
    dict(when="~ 2026-11-15", what=f"새 인원 {NEW}명 확정{_how}: {who_list(NEW_KINDS)}",
         why=f"사내 전환은 부서 협의 뒤 약 2개월이 걸립니다. 11월 중순에 정해야 {mtext(first_new)}부터 일할 수 있습니다. 이 {NEW}명이 전부라 한 명이라도 늦으면 1분기 작업이 그만큼 밀립니다."),
    dict(when="~ 2026-11-15", what="LLM 브리지 확보 (전사 공용 GPU 또는 빅플랜 GPU 먼저 배정)", why=_bridge_why),
    dict(when="~ 2026-11-30", what="온프렘 투자심의 기안, 운영 방식(혼합안) 결정, 바이브 코딩 도구 보안 승인 신청",
         why="투자심의가 3개월 넘게 걸려 11월에 올려야 7월에 가동합니다. 바이브 코딩 승인은 보통 3개월이라 2월부터 효과가 납니다. LG CNS 와 Anthropic 의 그룹 계약을 쓸 수 있는지도 함께 확인합니다."),
    dict(when="~ 2026-12-15", what="빌려 쓰는 시간 확약 (겸직, DRI 팀 직접 수행, 전사 지원, A와 B)",
         why=borrow_say + ". 시작 한 달 전까지 정해야 1월에 투입됩니다. 달과 양은 '누가 언제 일하는가' 표에 있습니다."),
    dict(when="~ 2026-12-31", what=f"2028년으로 넘기는 작업 {len(defer_rows)}개 확정, 원장과 로스터 고치기 (Gate 1)",
         why=f"새 인원 {NEW}명 안에 들어가지 않는 일 {defer_mm:.0f} MM 을 2028년으로 넘깁니다. 2027 마일스톤 {n_gone}개가 통째로, {n_part}개가 일부 넘어가고 '27 Agent {len(defer_ag)}개도 함께 넘어가므로 12월 Gate 1 에서 원장을 고쳐야 합니다."),
]

# ---------------------------------------------------------------- 머리 문장, 한눈에
lead = (f"AL-1, VV-1, VV-3 를 새 인원 {NEW}명으로 2027년에 어디까지 할 수 있는지 정리했습니다. "
        f"누가 언제 어떤 일을 하고, 무엇을 들여와야 하며, 얼마가 드는지와 2028년으로 넘기는 일을 함께 봅니다.")
summary = [
    dict(k="새로 들이는 사람", v=f"{NEW}", u="명", d=f"{who_list(NEW_KINDS)}. 외주 없음"),
    dict(k="2027년에 하는 일", v=f"{tot['wp']:.0f}", u="MM", d=f"월평균 {tot['wp']/12:.1f}명분, 가장 많은 달 {peak_total:.1f}명분 (기존 인력 시간 포함)"),
    dict(k="2028년으로 넘기는 일", v=f"{defer_mm:.0f}", u="MM", d=f"작업 {len(defer_rows)}개, '27 Agent {n_ag}개 가운데 {len(defer_ag)}개"),
    dict(k="2027 마일스톤", v=f"{n_kept}/{n_ms}", u="", d=f"모두 지키는 것 {n_kept}개, 일부만 지키는 것 {n_part}개, 2028년으로 넘기는 것 {n_gone}개"),
    dict(k="빌려 쓰는 시간", v=f"{borrow:.1f}", u="MM", d="겸직, DRI 팀 직접 수행, 전사 지원, A와 B 의 개발 참여"),
]
for _t in IC.get("summary_tiles", []):  # 0 인 항목은 빼고, 나쁘게 잡은 값을 붙인다
    _t = dict(_t, d=_t["d"].replace("인건비 0.0 · ", "") + f". 나쁘게 잡으면 {IC['totals']['cash']['hi'] / EOK:.1f}억")
    summary.append(_t)

# ---------------------------------------------------------------- 누가, 언제
GROUPS = [("A와 B (기존)", ["AX A·B"], "var(--s1)"), ("DRI 개발자 (기존)", ["DRI 개발자"], "var(--s2)"),
          ("새 인원", ["사내 전환배치", "사내 공모", "채용(경력)"], "var(--s3)"), ("겸직과 전사 지원", ["사내 지원(겸직)", "전사 지원"], "var(--s4)"),
          ("DRI 팀 직접, 시민개발", ["DRI 시민개발", "DRI 팀 직접"], "var(--s5)")]
SS = M["supply_src"]
ppl_src = [dict(label=g, c=c, data=[round(sum(SS.get(k, [0] * 12)[i] for k in ks), 3) for i in range(12)]) for g, ks, c in GROUPS]
ptable = [dict(who="A와 B (기존)", n="2명", when="1~12월", mm=f1(sum(SS["AX A·B"])), note="본업(거버넌스, 평가, 투자심의) 뒤 남는 시간은 Agent 개발에"),
          dict(who="DRI 개발자 (기존)", n="", when="1~12월", mm=f1(sum(SS["DRI 개발자"])), note="AL-1 툴 개발 0.5명분, VV-1 플랫폼 0.5명분")]
for x in src:
    if x["kind"] == "일정 조정":
        continue
    supply = sum((M["ramp"].get(x["kind"], []) + [1.0] * 12)[m - x["s"]] * x["fte"] for m in range(max(1, x["s"]), x["e"] + 1))
    n = f"{math.ceil(x['fte'] - 1e-9)}명" if x["kind"] in NEW_KINDS else f"{x['fte']:g}명분"
    ptable.append(dict(who=f"{KIND_SAY.get(x['kind'], x['kind'])}: {ROLE_SHORT.get(x['role'], x['role'])}", n=n,
                       when=f"{mlabel(x['s'])}~{mlabel(x['e'])} (착수 {x['start_txt']})", mm=f1(supply), note=x.get("note", "")))
ptable.append(dict(who="도메인 판정 (DRI 팀 시간)", n="여러 명", when="1~12월", mm=f1(dom_mm), note="해석, 회로, 기구, 광학, 시스템 엔지니어가 각자 업무 시간의 30% 안에서"))
ptable.append(dict(tot=True, who=f"새로 들이는 사람 {NEW}명", n=f"{NEW}명", when="", mm="", note=f"{who_list(NEW_KINDS)}. 외주 없음"))
# 하반기에 시간이 남는 역할 (사람은 역할에 묶여 있어 다른 역할의 모자람을 바로 메우지 못한다)
_h2 = []
for r in DEV + ["AX"]:
    sl = [M["supply_m"].get(r, [0] * 12)[i] - M["demand"][r][i] for i in range(6, 12)]
    if sum(sl) / 6 >= 0.3:
        _h2.append(f"{ROLE_TINY.get(r, r)} 월 {min(sl):.1f}~{max(sl):.1f}명분")
people = dict(src=ppl_src, demand=[round(v, 3) for v in dem_ax_dev], domain=[round(v, 3) for v in dem_dom], table=ptable,
              cap=f"막대는 그 달에 일할 수 있는 양(새로 온 사람의 적응 기간 반영), 선은 개발과 AX 에 필요한 양입니다. "
                  f"도메인 판정 {dom_mm:.0f} MM 은 DRI 팀 시간이라 따로 셉니다. 월평균 {tot['wp']/12:.1f}명분은 이것을 모두 더한 일의 양이고, 새로 들이는 사람은 {NEW}명입니다."
                  + (f" 하반기에 남는 시간({', '.join(_h2)})은 역할이 맞지 않아 넘긴 일에 바로 쓰지 못합니다. 6월 중간 점검에서 이 시간으로 2028 일을 당겨올 수 있는지 다시 봅니다." if _h2 else ""))

# ---------------------------------------------------------------- 개발 방법
V = METH["vibe"]["ext"]
mcp_role = {r: 0.0 for r in DEV}
for w in M["wp"]:
    sv = METH["mcp"]["wp"].get(w["id"])
    if sv:
        for r in DEV:
            mcp_role[r] += w["eff0"].get(r, 0) * sv["saving_base"]
roles_eff = [dict(id=r, name=ROLE_NAME[r], raw=M["raw_role"][r], base=tot["role"][r], hi=M["sens"]["hi"][r], lo=M["sens"]["lo"][r],
                  f=V.get(r), mcp=round(mcp_role.get(r, 0), 2)) for r in DEV + ["AX"] if M["raw_role"][r] >= 0.05]
added = sorted(parts["added"].items(), key=lambda kv: -kv[1])
wf, acc = [], parts["task_raw"]
wf.append(dict(label="과제 작업 (기존 방식으로 추정)", a=0, b=acc, k="base"))
for k, v in added:
    wf.append(dict(label="+ " + parts["labels"][k], a=acc, b=acc + v, k="add"))
    acc += v
wf.append(dict(label="- 외부 MCP 재사용", a=acc, b=acc - parts["mcp"], k="cut"))
acc -= parts["mcp"]
wf.append(dict(label="- 바이브 코딩 (리뷰와 재작업을 뺀 효과)", a=acc, b=acc - parts["vibe"], k="cut"))
acc -= parts["vibe"]
wf.append(dict(label="2027년에 하는 일", a=0, b=acc, k="tot"))
add_sum = sum(parts["added"].values())
_rr = [r for r in DEV + ["AX"] if r in V]
STEADY = sum(M["raw_role"][r] * (1 - V[r]["base"]) for r in _rr) / sum(M["raw_role"][r] for r in _rr) * 100
EFF27 = parts["vibe"] / max(1, sum(M["raw_role"][r] for r in DEV + ["AX"])) * 100
mcp_rows = []
wpn = {w["id"]: w["name"] for w in M["wp"]}
for k, v in sorted(METH["mcp"]["wp"].items(), key=lambda kv: -kv[1]["saving_base"]):
    if k in wpn and v["saving_base"] >= 0.02:
        mcp_rows.append(dict(wp=k, wpname=wpn[k], mcp=v["mcp"], hi=v["saving_hi"], base=v["saving_base"], lo=v["saving_lo"], note=""))

B = lambda x, y, w, h, t, s, k, **kw: dict(x=x, y=y, w=w, h=h, t=t, s=s, k=k, **kw)
flow = dict(w=1160, h=330, boxes=[
    B(10, 105, 170, 120, "사람 (사내만)", ["A와 B, DRI 개발자", f"새 인원 {NEW}명", "겸직, DRI 팀 직접 수행", "전사 지원"], "ppl"),
    dict(x=205, y=12, w=280, h=310, t="바이브 코딩 도구 (Claude Code)", k="grp"),
    B(220, 36, 250, 58, "lead: 계획, 나누기, 검토", ["공통 CLAUDE.md, Skills 템플릿"], "harness", fill=True, bold=True),
    B(220, 108, 250, 58, "sub: 구현", ["C0~C2 코드, C3 는 합성 자료로"], "harness"),
    B(220, 180, 250, 58, "sub: 시험과 평가", ["골든셋 회귀, 재작업률"], "harness"),
    B(220, 252, 250, 58, "sub: 리뷰와 보안", ["정적 분석, 비밀, 의존성 검사"], "harness"),
    B(510, 30, 225, 120, "외부 MCP (검증 후 사내 미러)", ["Ansys AEDT, Mechanical 공식", "버전과 해시 고정", "허용 목록에 있는 것만"], "tool"),
    B(510, 180, 225, 120, "사내 MCP (직접 개발)", ["PLM 읽기, 시뮬레이터 엔진", "HPC 큐, Agent 등록", "C3 도구는 온프렘에서만"], "tool"),
    B(760, 105, 185, 120, "Agent 정의 (공통 자산)", ["SKILL.md, 서브에이전트", "MCP 도구, A2A 카드", "평가셋, 모델 등급표"], "asset", bold=True),
    B(970, 40, 180, 70, "운영 런타임", ["LangGraph 하나"], "rt"),
    B(970, 190, 85, 70, "외부 API", ["C0~C1"], "ext"),
    B(1065, 190, 85, 70, "온프렘", ["C3 는 여기만"], "loc"),
], arrows=[
    dict(pts=[[180, 165], [196, 165], [196, 65], [220, 65]]),
    dict(pts=[[485, 90], [510, 90]], label="도구 호출", lp=[478, 76]),
    dict(pts=[[485, 240], [510, 240]]),
    dict(pts=[[735, 90], [748, 90], [748, 145], [760, 145]]),
    dict(pts=[[735, 240], [748, 240], [748, 185], [760, 185]]),
    dict(pts=[[945, 165], [958, 165], [958, 75], [970, 75]], label="같은 정의", lp=[880, 248]),
    dict(pts=[[1012, 110], [1012, 190]], k="ext"),
    dict(pts=[[1107, 110], [1107, 190]], k="loc", label="게이트웨이", lp=[1040, 150]),
])
method = dict(
    flow=flow,
    points=[
        f"2027년에는 개발 방법이 새로 더하는 일({add_sum:.1f} MM)이 줄여 주는 일(바이브 코딩 {parts['vibe']:.1f} MM, 외부 MCP {parts['mcp']:.1f} MM)보다 큽니다. 도입과 학습이 한 해에 몰리기 때문이고, 효과는 2028년부터 커집니다.",
        f"바이브 코딩은 2027년에 개발 공수를 약 {EFF27:.0f}% 줄이고, 자리를 잡은 뒤에는 약 {STEADY:.0f}% 줄입니다. 공개된 통제 실험 12건을 이 팀 조건(새로 만드는 개발, 도메인 라이브러리, C3 자료 금지)에 맞춰 다시 계산하고 리뷰와 재작업 시간을 뺀 값입니다. 3월, 6월, 9월에 실제 공수로 다시 맞춥니다.",
        f"외부 MCP 는 Ansys 공식 서버 {METH['mcp']['servers']['base']}개(AEDT, Mechanical)만 씁니다. 나머지는 검증 비용이 줄여 주는 공수보다 커서 2028년에 다시 봅니다. 쓰는 서버도 사내 미러, 버전 고정, 허용 목록을 거칩니다.",
        "Agent 정의(Skills, 서브에이전트, MCP 도구, 평가셋)는 특정 도구에 묶지 않습니다. 개발은 Claude Code 로 하고 운영은 LangGraph 로 같은 정의를 돌리므로, 외부 API 든 사내 로컬 LLM 이든 게이트웨이 설정만 바꾸면 됩니다.",
        "도면, BOM, STP 같은 C3 자료는 외부 코딩 도구에 넣지 않습니다. 구조만 남긴 합성 자료로 개발하고, 실제 자료 검증은 온프렘에서 합니다.",
    ],
    wf=wf,
    wfCap=f"주황은 개발 방법이 새로 더하는 일 {add_sum:.1f} MM, 초록은 줄여 주는 일 {parts['vibe'] + parts['mcp']:.1f} MM 입니다. 효과를 나쁘게 잡으면 {sum(M['sens']['hi'].values()):.0f} MM, 좋게 잡으면 {sum(M['sens']['lo'].values()):.0f} MM 입니다.",
    roles=roles_eff,
    cap=f"빈 점은 기존 방식으로 추정한 공수, 채운 점은 바이브 코딩과 외부 MCP 를 반영한 공수, 막대는 나쁘게 잡은 값과 좋게 잡은 값 사이입니다. 숙련 {METH['vibe']['ramp_months']['base']}개월 동안은 효과가 절반이고, 정보보안 승인({mlabel(METH['options'][PICK]['vibe_start']['base'])}) 전에는 효과가 없습니다.",
    mcp=mcp_rows,
)

# ---------------------------------------------------------------- 운영안 3개
def opt_dia(k):
    if k == "A":
        return dict(title="1안: 코딩 도구가 주, LangGraph 가 보조", sub="사용자 원안. C3 자료를 외부로 못 보내 실행 경로가 3개가 됩니다", w=560, h=300, boxes=[
            B(10, 110, 120, 80, "Agent 정의", ["공통 자산"], "asset"),
            B(160, 18, 200, 62, "경로 1: 코딩 도구", ["Claude Code, Agent SDK"], "harness"),
            B(160, 118, 200, 62, "경로 2: LangGraph", ["연결이 끊기면 다시 실행"], "rt"),
            B(160, 218, 200, 62, "경로 3: C3 용 LangGraph", ["도면, BOM, STP"], "rt"),
            B(395, 18, 155, 62, "외부 API", ["C0~C2"], "ext"),
            B(395, 118, 155, 62, "다른 API", ["다른 공급자나 온프렘"], "ext"),
            B(395, 218, 155, 62, "온프렘 로컬 LLM", ["C3 전용"], "loc")],
            arrows=[dict(pts=[[130, 140], [145, 140], [145, 49], [160, 49]]), dict(pts=[[130, 150], [160, 150]]), dict(pts=[[130, 160], [145, 160], [145, 249], [160, 249]]),
                    dict(pts=[[360, 49], [395, 49]]), dict(pts=[[360, 149], [395, 149]]), dict(pts=[[360, 249], [395, 249]], k="loc"),
                    dict(pts=[[300, 80], [300, 118]], dash=True, label="장애 때", lp=[306, 103])])
    if k == "B":
        return dict(title="2안: 전부 온프렘 로컬 LLM", sub="외부 연결이 없습니다. 개발(바이브 코딩)도 로컬 모델로 합니다", w=560, h=300, boxes=[
            B(10, 110, 120, 80, "Agent 정의", ["공통 자산"], "asset"),
            B(160, 60, 200, 62, "런타임: LangGraph", ["모든 Agent, 모든 등급"], "rt"),
            B(160, 180, 200, 62, "바이브 코딩: 로컬", ["공개 도구와 vLLM"], "harness"),
            B(395, 100, 155, 100, "온프렘 로컬 LLM", ["C0~C3 전부", "외부 대체 없음", "서버를 둘로 대비"], "loc", bold=True)],
            arrows=[dict(pts=[[130, 140], [145, 140], [145, 91], [160, 91]]), dict(pts=[[360, 91], [378, 91], [378, 130], [395, 130]], k="loc"),
                    dict(pts=[[360, 211], [378, 211], [378, 170], [395, 170]], k="loc")])
    return dict(title="혼합안: 개발은 바이브 코딩, 운영은 LangGraph 하나", sub="1안을 다듬은 것. 보조 경로 대신 자료 등급에 따라 자동으로 나누고 공급자를 둘로 둡니다", w=560, h=300, boxes=[
        B(10, 18, 165, 62, "개발: 바이브 코딩", ["Claude Code (C0~C2 코드)"], "harness"),
        B(205, 18, 150, 62, "Agent 정의", ["공통 자산"], "asset"),
        B(205, 130, 150, 80, "런타임: LangGraph", ["하나, 게이트웨이가", "등급별로 보냄"], "rt", bold=True),
        B(395, 92, 155, 62, "외부 API", ["C0~C1, 공급자 둘"], "ext"),
        B(395, 196, 155, 62, "온프렘 로컬 LLM", ["C3 는 여기만"], "loc")],
        arrows=[dict(pts=[[175, 49], [205, 49]]), dict(pts=[[280, 80], [280, 130]]),
                dict(pts=[[355, 160], [375, 160], [375, 123], [395, 123]], k="ext"), dict(pts=[[355, 180], [375, 180], [375, 227], [395, 227]], k="loc")])


def opt_vals(fn):
    return {k: fn(k, *RUNS[k]) for k in ("A", "B", "C")}


def cash(k, m, ic):
    if OPT_INF.get(k):
        return "-"
    t = ic["totals"]["cash"]
    return f"{t['base']/EOK:.1f}억 (나쁘게 잡으면 {t['hi']/EOK:.1f}억)"


opt_rows = [
    dict(k="실행 경로", v=dict(A="3개 (코딩 도구, LangGraph, C3 온프렘)", B="1개 (온프렘)", C="런타임 1개에 모델 2종 (게이트웨이)"), win="C"),
    dict(k="C3 자료 (도면, BOM, STP)", v=dict(A="별도 온프렘 경로", B="전부 온프렘", C="게이트웨이가 온프렘으로만 보냄"), win="C"),
    dict(k="연결이 안 될 때", v=dict(A="경로 2 에서 다시 실행. 두 런타임을 늘 시험해 둬야 함", B="외부 대체 없음. 서버를 둘로", C="Claude 공급자를 둘로(API, Bedrock 서울). 흐름은 그대로"), win="C"),
    dict(k="바이브 코딩 효과", v=opt_vals(lambda k, m, ic: f"{m['parts']['vibe']:.1f} MM 줄임" + (" (로컬 코딩은 효과가 작음)" if k == "B" else "")), win="C"),
    dict(k="플랫폼 운영 인력", v=dict(A="1.8명분. A와 B 가 플랫폼에 묶임", B="1.5명분, Agent 유지보수는 1.3배", C="1.15명분"), win="C"),
    dict(k="2027년에 하는 일 (같은 범위)", v=opt_vals(lambda k, m, ic: f"{m['totals']['wp']:.0f} MM"), win="C"),
    dict(k="같은 범위에 필요한 새 인원", v=opt_vals(lambda k, m, ic: f"{OPT_INF[k]} 늘려도 안 됨" if OPT_INF.get(k) else f"{sum(new_heads(m))}명"), win=None),
    dict(k="2027 증분 현금", v=opt_vals(cash), win=None),
    dict(k="품질", v=dict(A="C0~C2 는 가장 좋음, C3 는 로컬 수준", B="모두 로컬 수준. 긴 작업에서 약 28%p 낮음", C="C0~C1 은 Claude, C3 는 로컬"), win="A"),
    dict(k="자료가 밖으로 나갈 위험", v=dict(A="C0~C2 는 외부로 (승인 범위 안)", B="구조적으로 없음", C="C0~C1 만 외부로 (게이트웨이가 막음)"), win="B"),
    dict(k="특정 회사 의존", v=dict(A="높음 (도구와 모델 모두)", B="낮음", C="중간 (모델만)"), win="B"),
    dict(k="맞는 상황", v=dict(A="C3 Agent 가 적고, AX 가 3명 넘고, API 예산이 있을 때", B="외부 API 가 전면 금지이거나 로컬 모델이 사내 평가를 통과할 때", C="C3 Agent 가 많고 AX 가 2명인 지금"), win="C"),
]
NAMES = {"A": "1안 (두 갈래)", "B": "2안 (로컬만)", "C": "혼합안"}
options = dict(order=["A", "B", "C"], pick=PICK, names=NAMES, dia={k: opt_dia(k) for k in ("A", "B", "C")}, rows=opt_rows, points=[
    "1안은 C3 자료를 외부 API 로 보낼 수 없어 결국 온프렘 경로를 하나 더 둡니다. 실행 경로가 3개가 되고 플랫폼 운영에만 1.8명분이 들어, A와 B 가 플랫폼에 묶입니다.",
    "2안은 자료가 밖으로 나갈 위험과 API 비용이 없습니다. 대신 길고 여러 단계인 작업에서 로컬 모델 성능이 크게 떨어지고(최신 공개 평가에서 약 28%p), 로컬 모델로 하는 바이브 코딩은 효과가 거의 없습니다.",
    "혼합안은 1안의 생각(바이브 코딩으로 관리하고 LangGraph 로 운영하며 API 를 연결)을 그대로 살립니다. 보조 경로를 따로 두는 대신 자료 등급에 따라 자동으로 나눠 보내고(C3 는 온프렘), 연결 장애는 Claude 공급자를 둘로 두어 대비합니다.",
    "정해야 할 전제가 하나 있습니다. 정보보안이 C0~C2 코드를 외부 코딩 도구로 다루는 것을 허용하는지입니다. 허용하지 않으면 2안이 되고, "
    + (f"같은 범위에 새 인원이 {sum(new_heads(RUNS['B'][0]))}명 필요합니다(혼합안은 {sum(new_heads(RUNS['C'][0]))}명)."
       if not OPT_INF.get("B") and sum(new_heads(RUNS["B"][0])) > sum(new_heads(RUNS["C"][0])) else "새 인원 수는 같아도 품질과 바이브 코딩 효과가 떨어집니다."),
])

# ---------------------------------------------------------------- 계산 로직
logic = dict(
    boxes=[
        dict(step="1 원장 마일스톤", num=f"{n_ms}", lines=["'27 분기 목표 (빅플랜 p.15)", f"모두 지키는 것 {n_kept}개"]),
        dict(step="2 작업", num=f"{len(M['wp'])}", lines=[f"2027 에 남긴 작업", f"2028 로 넘긴 것 {len(defer_rows)}개"]),
        dict(step="3 방법 반영", num=f"{tot['wp']:.0f} MM", lines=[f"기존 방식 추정 {sum(M['raw_role'].values()):.0f} MM 에서", "바이브 코딩, MCP 효과"]),
        dict(step="4 월별 필요량", num=f"최대 {peak_total:.1f}", lines=["역할별, 달별 명분", "운영은 릴리즈 뒤 늘어남"]),
        dict(step="5 사내 공급", num=f"{NEW}명 더", lines=["새로 온 사람 적응 기간 반영", "전환 2개월, 채용 6개월"]),
        dict(step="6 점검과 비용", num=f"{sum(1 for c in M['checks'] if c['ok'])}/{len(M['checks'])}", lines=["나쁘게 잡아도 공급되는지", "운영안 3개를 같은 방식으로"], hot=True),
    ],
    infra=dict(title="인프라: 온프렘 LLM 이 먼저 있어야 합니다", line="C3(도면, STP, BOM) 처리는 '27.2 부터 필요한데 자체 서버는 '27.7 가동입니다. 그 사이는 브리지로 메웁니다. 투자심의가 3개월 넘게 걸려 11월 기안이 마지노선입니다."),
    points=[
        "공수는 '도메인 하나를 늘리는 데 CAE 2.5, AI 1.8, 도메인 1.6, 평가 0.6 MM' 같은 표준 단위로 먼저 기존 방식대로 추정하고, 그 위에 바이브 코딩과 외부 MCP 효과를 역할별로 곱했습니다. 효과는 리뷰, 보안, 재작업 시간을 뺀 값입니다.",
        "개발 방법 때문에 새로 생기는 일(플랫폼 운영, 이식 계층, 학습, MCP 검증, 합성 자료)도 작업으로 넣었습니다. 빼면 사람이 남아 보입니다.",
        f"새 인원은 {NEW}명이 한도입니다. 그래서 A와 B 도 본업 뒤 남는 시간에 개발에 참여하고, VV-1 센서모델과 학습은 VV-1 DRI 팀이 P0 30% 시간 안에서 직접 맡고, 데이터 일은 AI 엔지니어가 함께 맡습니다.",
        "그래도 남는 일은 우선순위가 낮은 것부터 2028년으로 넘겼습니다. 마일스톤이 없는 Agent 와 '28 준비 작업을 먼저 넘기고, 3과제가 함께 쓰는 해석 자동화 플랫폼은 끝까지 남겼습니다.",
        "모든 점검(마일스톤, 작업 순서, 선행 조건, 공급, 나쁘게 잡은 경우, 외주 0)은 '로직 점검'에서 다시 계산합니다.",
    ],
)

# ---------------------------------------------------------------- 점검
LABEL = {
    "deps": ("선행 조건이 필요한 달까지 확보되는가 (자체 투자 기준)", "자체 온프렘만으로는 늦는 작업이 있어 브리지('27.2)로 메웁니다. 결정 기한 11/15."),
    "ms": ("2027 마일스톤 가운데 2027년에 작업이 남은 것", f"작업이 모두 넘어간 마일스톤 {n_gone}개는 2028년으로 갑니다(일부만 남은 것 {n_part}개). 12월 Gate 1 에서 원장을 고칩니다."),
    "ag": ("'27 Agent 가운데 2027년에 만드는 것", f"2028년으로 넘긴 Agent {len(defer_ag)}개는 로스터의 단계를 '28 로 고칩니다."),
    "sum": ("합계가 맞는가 (작업 합 = 역할 합 = 과제 합)", ""),
    "dom": ("도메인 팀 시간이 업무 시간의 30% 안인가", ""),
    "seq": ("작업 순서가 맞는가 (선행 작업이 끝난 뒤 시작)", ""),
    "supply": ("역할마다 달마다 필요한 양이 공급 안에 드는가 (10% 여유)", ""),
    "lead": ("착수 기한이 오늘(2026년 10월) 뒤인가", ""),
    "citizen": ("현업 시민개발이 CAE 스크립트 일의 35% 안인가 (R6)", ""),
    "inhouse": ("외주 없이 모두 사내에서 구하는가", ""),
    "vibe_hi": ("바이브 코딩 효과를 나쁘게 잡아도 공급이 충분한가", "새 인원과 빌려 쓰는 시간을 고를 때 이미 나쁘게 잡은 수요에 맞췄습니다."),
    "bridge": ("브리지를 확보하면 마일스톤이 늦지 않는가", ""),
}
checks = []
for c in M["checks"]:
    if c["of"] == 0:  # 해당 없음(예: 경력 채용이 없으면 가동률 점검)
        continue
    cc = dict(c)
    if c["id"] in LABEL:
        cc["label"], cc["note"] = LABEL[c["id"]]
    if c["id"] == "ms_sched":  # 넘긴 마일스톤은 빼고, 남긴 것만 기한을 본다
        live = [r for r, v in MS_STATE.items() if v != "gone"]
        late = [x for x in c.get("detail", []) if x.split(" ")[0] in live]
        cc.update(label="남긴 마일스톤이 기한 안에 끝나는가 (작업 일정 기준)", ok=not late, n=len(live) - len(late), of=len(live), detail=late,
                  note="2028년으로 넘긴 마일스톤은 빼고 셉니다.")
    checks.append(cc)
checks.append(dict(id="after", label="남긴 작업의 선행 작업도 모두 2027년에 남아 있는가", ok=not M.get("dropped_after"),
                   n=sum(len(WPF[w]["after"]) for w in KEPT if w in WPF) - sum(len(x["pred"]) for x in M.get("dropped_after", [])),
                   of=sum(len(WPF[w]["after"]) for w in KEPT if w in WPF), detail=[f"{x['wp']} {x['name']}: 선행 {', '.join(x['pred'])} 없음" for x in M.get("dropped_after", [])]))
Mhi, ICh = run(PICK, "hi")
hi_fail = [c for c in Mhi["checks"] if not c["ok"] and c["id"] not in ("deps", "ms", "ag", "ms_sched")]
_cells = 12 * len([r for r in Mhi["roles"] if not r["id"].startswith("DOM_")])
checks_extra = [dict(id="hi_all", label="모든 전제를 나쁘게 잡아도(채용 9개월, 이식 계층 6 MM 등) 같은 조달로 충분한가", ok=not hi_fail,
                     n=sum(c["n"] for c in Mhi["checks"] if c["id"] == "supply"), of=_cells,
                     note=f"모자라면 6월 중간 점검에서 작업을 더 넘기거나 겸직을 늘립니다. 이 경우 증분 현금 {ICh['totals']['cash']['base']/EOK:.1f}억.",
                     detail=[f"{c['label']} {c['n']}/{c['of']}" for c in hi_fail])]

# ---------------------------------------------------------------- 가정
assumptions = [
    dict(k="새 인원 한도", v=f"{NEW}명", src="사용자 결정 (2026-10-22)", st="확정"),
    dict(k="외주", v="없음", src="사용자 결정 (2026-10-21). LG CNS 용역도 별도 법인이라 외주로 봄", st="확정"),
    dict(k="공수 단위", v="1 MM 은 1명이 1개월 일한 양", src="FTE(명분)는 달마다의 MM. 휴가와 교육은 가용률로 반영", st="확정"),
    dict(k="A와 B 가용률", v=f"각 80% ({AXF})", src="나머지 20% 는 CO-1, P1과 P2 과제, CT, 교육. 100% 투입하는 달에는 이것을 뒤로 미룸", st="확인 필요"),
    dict(k="A와 B 의 개발 참여", v=f"상반기 월 {sum(AX_DEV[:6]) / 6:.1f}명분, 하반기 월 {sum(AX_DEV[6:]) / 6:.1f}명분",
         src=f"거버넌스, 평가, 투자심의를 하고 남는 시간을 Agent 개발에 씁니다. 하반기에는 A와 B 시간의 {sum(AX_DEV[6:]) / 6 / 1.6 * 100:.0f}% 가 개발이라, 본업이 늘면 개발 참여를 줄이고 그만큼 일을 넘깁니다.",
         st="확인 필요"),
    dict(k="AI 와 데이터 겸용", v="한 사람이 두 역할", src="작은 팀에서 바이브 코딩으로 Agent 와 데이터 파이프라인을 함께 만듦", st="확인 필요"),
    dict(k="DRI 팀 직접 수행", v="VV-1 센서모델, GT, 학습", src="VV-1 DRI 팀이 업무 시간 30% 안에서 직접. 같은 사람들의 판정 시간과 합쳐 30% 를 넘지 않게 점검", st="확인 필요"),
    dict(k="DRI 팀 개발 인력", v="CAE 0.5, 시뮬레이션 0.5 명분", src="AL-1 툴 개발자와 VV-1 플랫폼 개발자", st="확인 필요"),
    dict(k="도메인 확장 표준 공수", v="CAE 2.5, AI 1.8, 도메인 1.6, 평가 0.6 MM", src="EM 1차 구축보다 기존 틀을 다시 써서 줄임. DRI 검토 필요", st="확인 필요"),
    dict(k="바이브 코딩 효과 (기준)", v="AI 13%, MLOps 5%, CAE 2%, ML 6%, 시뮬레이션 2%, MBSE 1%, AX 8% 감소", src="R1. 통제 실험 12건을 가중하고 리뷰와 재작업을 뺌. 숙련 3개월 동안 효과 절반", st="확인 필요"),
    dict(k="바이브 코딩 승인", v=mlabel(METH["options"][PICK]["vibe_start"]["base"]), src="R2. 정보보안 승인 보통 3개월(늦으면 6개월). 그룹 계약을 쓰면 짧아질 수 있음", st="확인 필요"),
    dict(k="외부 MCP", v=f"{METH['mcp']['servers']['base']}개 (Ansys)", src="R3. 나머지는 검증 비용이 절감보다 커서 2028년에 다시 봄", st="확인 필요"),
    dict(k="이식 계층", v=f"{METH['portability_build_mm']['base']} MM", src="R4 의 7 MM 가운데 게이트웨이, 등급별 라우팅, 평가 하네스만 2027년에", st="확인 필요"),
    dict(k="플랫폼 운영", v="1.15명분 (3~6월은 절반)", src="R4. 서빙 0.5, 런타임과 게이트웨이와 관측 0.5, 평가 0.15 (운영 Agent 수에 맞춤)", st="확인 필요"),
    dict(k="사내 전환 리드타임", v="2개월, 적응 2개월", src="R6. 회사 안 사람이라 경력 채용보다 짧음. 사내 공모 제도는 원문 확인 필요", st="확인 필요"),
    dict(k="학습 GPU 배정", v="'27.4", src="원장 D-VV1-02 (전사 지원 조직, '27.3.31 추정)", st="확인 필요"),
    dict(k="P0 투입률 상한", v="관련 인원의 30%", src="빅플랜 p.16", st="확정"),
]
assumptions += [a for a in IC.get("assumptions", []) if a["k"] != "외주 단가"]  # 외주는 없음

nxt = [
    dict(t="2 다음: 2028년 (반기 단위)", d=f"2027년에서 넘긴 {len(defer_rows)}개 작업과 Gate 2('28말) 목표를 함께 놓고 다시 짭니다. 도입과 학습이 끝나 바이브 코딩 효과가 커지는 해라, 같은 인원으로 더 많은 일을 할 수 있는지 2027년 실측으로 다시 계산합니다."),
    dict(t="3 그다음: 2029~2030년 (연 단위)", d="자율 운영 단계. 야간 무인해석 채택률 30% 에서 50%, 모든 기종 가상 선검증, 수율 선예측 90%. 운영 인력 비중과 온프렘 증설만 연 단위로 봅니다."),
    dict(t="이 문서를 고치는 법", d="'확인 필요' 전제를 바꾸면 계산 모델을 다시 돌려 모든 표가 함께 바뀝니다. 3월, 6월, 9월 실측으로 다시 맞춥니다."),
]

# ---------------------------------------------------------------- 용어
GLOSSARY = [
    dict(g="숫자 단위", items=[
        dict(t="FTE (명분)", d="한 사람이 한 달 내내 그 일만 하는 양을 1 로 센 것입니다(Full-Time Equivalent). 0.5 는 한 사람 시간의 절반입니다. '11명분' 은 일의 양이지 실제 사람 수가 아닙니다."),
        dict(t="MM (인월)", d="사람 수와 개월 수를 곱한 일의 양입니다(Man-Month). 1명이 12개월 일하면 12 MM 이고, 연평균 1명분과 같습니다."),
        dict(t="증분 현금", d="이 계획 때문에 새로 나가는 돈입니다. 장비 투자, 운영비, 채용 인건비가 들어가고 이미 있는 사람의 시간은 넣지 않습니다."),
        dict(t="보수, 기준, 낙관", d="불확실한 값을 셋으로 봅니다. 보수는 나쁘게 잡은 값, 기준은 가장 그럴듯한 값, 낙관은 좋게 잡은 값입니다."),
    ]),
    dict(g="사람을 구하는 방법", items=[
        dict(t="사내 전환배치, 사내 공모", d="회사 안 다른 부서 사람을 데려오는 것입니다. 전환은 부서 협의 뒤 약 2개월, 공모는 공고 뒤 약 3개월이 걸립니다."),
        dict(t="경력 채용", d="회사 밖에서 경력자를 뽑는 것입니다. 품의부터 입사까지 약 6개월이 걸립니다."),
        dict(t="겸직", d="다른 팀 사람이 원래 일을 하면서 몇 달 동안 시간 일부(예: 0.5명분)를 보태는 것입니다."),
        dict(t="DRI 팀 직접 수행", d="과제를 책임지는 현업 팀(DRI 팀)이 그 과제의 개발을 직접 하는 것입니다. 예: VV-1 DRI 팀이 센서모델과 학습을 맡음. 팀 시간 30% 안에서만."),
        dict(t="DRI 시민개발", d="현업 엔지니어가 바이브 코딩으로 해석 후처리 같은 스크립트를 직접 만드는 것입니다."),
        dict(t="A와 B 의 개발 참여", d="AX 담당 A와 B 가 본업(거버넌스, 평가, 투자심의) 뒤 남는 시간에 Agent 개발을 함께 하는 것입니다."),
        dict(t="리드타임, 적응 기간", d="리드타임은 착수(품의, 협의)부터 실제 투입까지 걸리는 기간입니다. 적응 기간은 새로 온 사람이 처음 몇 달 일의 속도가 느린 것을 말합니다."),
        dict(t="P0 투입률 30%", d="빅플랜 원칙입니다. 우선과제(P0)에 관련 팀원 시간의 30% 까지 씁니다."),
        dict(t="2028년으로 넘기기", d="새 인원 한도 안에 들어가지 않는 작업을 2028년 계획으로 옮기는 것입니다. 우선순위가 낮은 것부터 넘겼습니다."),
    ]),
    dict(g="개발 방법", items=[
        dict(t="바이브 코딩", d="AI 코딩 도구(Claude Code 등)에 말로 시켜 코드를 짜게 하고, 사람은 방향을 정하고 검토와 시험을 하는 개발 방식입니다."),
        dict(t="lead 와 서브에이전트", d="큰 Agent(lead)가 일을 나눠 작은 Agent(서브에이전트)에게 맡기는 구조입니다."),
        dict(t="MCP", d="Agent 가 PLM, Ansys, DB 같은 도구와 자료를 부르는 표준 연결 방식입니다(Model Context Protocol). 외부 MCP 는 남이 만들어 공개한 연결 부품입니다."),
        dict(t="A2A", d="과제가 다른 Agent 끼리 일을 맡기고 결과를 주고받는 표준입니다(Agent-to-Agent)."),
        dict(t="LangGraph", d="Agent 의 작업 흐름을 짜는 공개 도구입니다. 같은 Agent 를 외부 API 에도, 사내 로컬 LLM 에도 붙일 수 있습니다."),
        dict(t="골든셋, RAG", d="골든셋은 정답이 정해진 평가용 예제 묶음입니다. RAG 는 사내 문서를 찾아 AI 답변의 근거로 쓰는 방식입니다."),
        dict(t="작업(WP), 마일스톤", d="작업은 계획의 일 단위입니다(예: A3 구조 해석 자동화 개발). 마일스톤은 원장에 정한 분기 목표 14개입니다."),
    ]),
    dict(g="운영과 인프라", items=[
        dict(t="온프렘, 로컬 LLM", d="회사 안 서버에서 돌리는 AI 모델입니다. 자료가 밖으로 나가지 않습니다. 자체 서버는 2027년 7월 가동 예정입니다."),
        dict(t="C0 ~ C3 자료 등급", d="C3 는 도면, BOM, STP 원본처럼 밖으로 내보낼 수 없는 자료로, 온프렘에서만 다룹니다. C0~C1 은 외부 API 를 써도 됩니다."),
        dict(t="브리지", d="자체 서버가 가동되기 전(2~6월)에 C3 자료를 다루려고 임시로 빌려 쓰는 사내 GPU 입니다."),
        dict(t="게이트웨이, 등급별 라우팅", d="자료 등급을 보고 외부 API 와 온프렘 모델 가운데 어디로 보낼지 자동으로 정하는 관문입니다. C3 는 항상 온프렘으로 갑니다."),
        dict(t="1안, 2안, 혼합안", d="1안은 코딩 도구가 주고 LangGraph 가 보조, 2안은 모두 온프렘 로컬, 혼합안(권장)은 개발은 바이브 코딩, 운영은 LangGraph 하나로 등급별로 나눠 보내는 방식입니다."),
        dict(t="투자심의", d="회사 설비 투자 승인 절차입니다. 3개월 넘게 걸려 11월 기안이 7월 가동의 마지노선입니다."),
    ]),
]

# ---------------------------------------------------------------- 역할별 필요한 능력
ROLE_DETAIL = {
    "AX": dict(must=["3과제 일정과 의존 관계 관리, 월별 P0 투입률 점검", "Agent 구조 판단: Skills, 서브에이전트, MCP, A2A 중 무엇으로 만들지", "자료 등급(C0~C3)과 승인 단계 설계, 정보보안 협의",
                     "투자심의 기안과 비용 산정, 사내 인력 협의", "평가셋(골든셋) 설계와 자동 채점 기준", "남는 시간에 바이브 코딩으로 Agent 개발 참여"],
               tools=["Claude Code 관리자 설정 (허용 MCP 목록, 외부 경로 차단)", "Langfuse 로 품질과 비용 보기", "AXBoard 로 마일스톤과 연결 관리"],
               plus=["LiDAR 개발 과정과 DRI 팀 업무 이해", "구매와 투자 절차 경험"],
               level="기존 A와 B 2명, 사람 구분 없이 나눠 맡음",
               first=f"바이브 코딩 승인과 규칙, 새 인원 온보딩, 투자심의 ({AXF} 투입)"),
    "AI": dict(must=["LangGraph 로 Agent 흐름과 서브에이전트 설계", "MCP 서버와 클라이언트 구현 (2026-07-28 스펙)", "도구 호출 신뢰성: 입력 검증, 재시도, 사람 승인 단계",
                     "RAG: 임베딩, 리랭커, 검색 평가", "PLM/PDM 연동과 도면, BOM 파싱 (C3 는 합성 자료로)", "Python 서비스와 시험 자동화"],
               tools=["Claude Code 로 개발: 서브에이전트, Skills, 검증 단계(시험, 정적 분석, 비밀 검사)", "로컬 모델(vLLM 위 공개 모델)의 도구 호출 특성",
                      "A2A 로 과제 사이 위임", "Langfuse 기록으로 회귀 분석"],
               plus=["도면, BOM, 해석 자료를 다뤄 본 경험", "한국어 기술문서 RAG 평가 경험"],
               check=["직접 만든 MCP 서버나 Agent 를 보여 주고 실패 사례를 설명하는가", "AI 가 짠 코드를 시험과 리뷰로 검증하는 습관이 있는가", "C3 자료를 외부 도구에 넣지 않는 규칙을 설계에 반영하는가"],
               level="선임 또는 책임, 3~7년. 데이터 일도 함께 맡는 겸용",
               first="공통 Agent 틀과 평가 하네스, 구조 해석(A3) 형상 추출"),
    "CAE": dict(must=["PyAEDT, PyMechanical, PyFluent 스크립트", "HFSS, SIwave, Maxwell, Mechanical, Icepak 해석 설정 이해 (판정은 도메인 전문가와)",
                      "무인 배치 실행, 라이선스 관리, HPC 작업 관리", "후처리와 리포트 자동화, 골든셋과의 오차 검증"],
                tools=["Ansys 공식 MCP (AEDT, Mechanical, 시험판) 를 격리된 환경에서", "PyAnsys 문서를 코딩 도구에 붙이는 문서 MCP",
                       "바이브 코딩 효과가 작은 분야라 예제와 템플릿 저장소로 보완"],
                plus=["LiDAR 모듈(광학, 회로, 기구) 해석 경험"],
                check=["사내 AEDT, Mechanical 버전에서 스크립트를 돌려 본 경험", "해석 결과의 물리적 타당성을 스스로 의심하는가"],
                level="선임 또는 책임, 3~8년",
                first="구조(A3)와 회로 SI/PI(H4) 플러그인, EM 틀 재사용"),
    "ML": dict(must=["3D 점구름 검출과 분할 모델 학습, 평가", "합성 자료에서 실측으로 옮기기(Sim2Real)와 상관 측정", "PyTorch 학습과 실험 관리(MLflow)", "데이터셋 버전과 GT 라벨 규격"],
               tools=["학습 GPU(RTX PRO 6000) 작업 관리", "바이브 코딩은 파이프라인 코드에만 (학습 시간은 그대로)"],
               plus=["표 자료 수율 예측 경험", "LiDAR 나 카메라 인지 경험"],
               check=["합성 자료만으로 학습한 모델이 실측에서 떨어지는 문제를 다뤄 본 경험", "평가 지표와 기준선을 스스로 정할 수 있는가"],
               level="선임 또는 책임, 3~7년. 2027년은 VV-1 DRI 팀이 직접 맡음"),
    "SIM": dict(must=["LiDAR 물리 모델 (ToF, FMCW 빔, 노이즈, 반사율)", "시뮬레이터 연동 API, RTX 센서(RT 코어) 이해", "OpenSCENARIO 와 ODD 분류, 커버리지 정의", "C++ 와 Python"],
                tools=["시뮬레이터 실행 MCP 는 사내에서 개발", "Isaac Sim, CARLA 류 MCP 는 참고만"],
                plus=["자율주행 인지 검증 경험"],
                check=["센서 모델 파라미터를 실측과 맞춰 본 경험"],
                level="선임 또는 책임, 3~8년. VV-1 플랫폼 개발자와 VV-1 DRI 팀이 직접"),
    "OPS": dict(must=["vLLM 서빙과 양자화, 도구 호출 파서 회귀 시험", "LLM 게이트웨이와 등급별 라우팅 (C3 는 온프렘으로만)", "관측(Langfuse 자체 호스팅), 감사 기록, 비용 관리",
                      "K8s, Slurm, 망분리와 보안 강화, 백업", "Claude 공급자 이중화 (API, Bedrock 서울)"],
                tools=["MCP 와 패키지를 사내 미러에서만, 버전과 해시 고정", "Claude Code 관리자 설정 배포 (WSL2 표준)"],
                plus=["NVLink 없는 8 GPU 서버 운영 경험", "투자심의용 용량 산정"],
                check=["모델이나 파서를 올리기 전에 회귀 시험부터 돌리는가", "밖으로 나가는 트래픽을 막고 그것을 증명할 수 있는가"],
                level="선임 또는 책임, 4~8년",
                first="브리지 환경, 학습 환경, 게이트웨이"),
    "MBSE": dict(must=["SysML v2, Capella 모델링", "요구에서 시스템 모델, 검증까지 RVTM 추적", "변경 영향 분석 규칙", "ISO 26262, ASPICE 이해"],
                 tools=["Capella(무료)로 시작", "SysML v2 는 검사기로 반복 생성"],
                 plus=["LiDAR 시스템 아키텍처"],
                 check=["1D Echo Gen2 요구를 직접 모델로 옮겨 볼 수 있는가"],
                 level="책임, 5년 이상. 2027년은 현업 시스템 엔지니어가 직접 맡음"),
    "DOM_ANA": dict(must=["EM, 구조, 열 해석 판정과 골든셋 정답 제공", "파일럿 사용자로 L/T 실측", "야간 무인해석 결과 아침 판정"], level="현업 해석 엔지니어. 업무 시간의 30% 안"),
    "DOM_CIR": dict(must=["SI/PI, EMC 판정 기준과 골든셋", "선검증 결과 판정"], tools=["시민개발: SI/PI, EMC 후처리 스크립트를 바이브 코딩으로 직접 (C3 는 온프렘에서만, AX 가 리뷰)"],
                    level="현업 회로 엔지니어. 시민개발까지 합쳐 업무 시간의 30% 안"),
    "DOM_MEC": dict(must=["구조, 열, 공차 판정과 파일럿 사용자", "수율 선예측 자료 제공"], level="현업 기구 엔지니어. 업무 시간의 30% 안"),
    "DOM_OPT": dict(must=["센서 광학 파라미터", "재설계안 판정"], level="현업 광학 엔지니어. 업무 시간의 30% 안"),
    "DOM_SYS": dict(must=["센서와 신호 파라미터", "ODD 와 Sim2Real 판정", "RVTM 요구 정의", "VV-1 센서모델, GT, 학습을 직접 수행 (DRI 팀 직접)"], level="현업 시스템 엔지니어 (VV-1 DRI 팀). 업무 시간의 30% 안"),
}
def short_name(n, lim=22):
    n = n.split(" (")[0].split(" — ")[0]
    if len(n) <= lim:
        return n
    cut = n[:lim].rsplit(" ", 1)[0]
    return cut.rstrip("·, ")


role_top = {}
for r in ROLE_NAME:
    ws = sorted([w for w in M["wp"] if w["eff"].get(r, 0) > 0.05], key=lambda w: -w["eff"][r])[:4]
    role_top[r] = [dict(id=w["id"], name=short_name(w["name"]), mm=round(w["eff"][r], 1)) for w in ws]

# ---------------------------------------------------------------- 사람 수 비교
rows = [dict(key="h3", label=f"새 인원 {NEW}명 (이 계획)", note=f"작업 {len(defer_rows)}개를 2028년으로" + (f". 마일스톤 {n_part}개는 일부만 지킴" if n_part else ""), heads=NEW, internal=P_ + T_, hires=H,
             total=round(tot["wp"], 1), ms=f"{n_kept}/{n_ms}", cash=round(IC["totals"]["cash"]["base"] / EOK, 1), result="")]
_more, _extra = [], []  # 4명이면 더 지키는 마일스톤, 더 하는 작업
if M4:
    h4 = sum(new_heads(M4))
    _k4 = {w["id"] for w in M4["wp"]}
    k4 = sum(1 for m in M_FULL["ms27"] if MS_WPS.get(m["ref"]) and all(x in _k4 for x in MS_WPS[m["ref"]]))
    _more = [m["label"] for m in M_FULL["ms27"] if MS_STATE[m["ref"]] != "kept" and MS_WPS.get(m["ref"]) and all(x in _k4 for x in MS_WPS[m["ref"]])]
    _who4 = ", ".join(f"{ROLE_SHORT.get(x['role'], x['role'])} {math.ceil(x['fte'] - 1e-9)}명" for x in M4["sourcing"] if x["kind"] in NEW_KINDS)
    _extra[:] = [d["id"] for d in M.get("deferred", []) if d["id"] in _k4]
    _ag4 = [a for a in defer_ag if any(a in WPF[w]["ag"] for w in _extra)]
    rows.append(dict(key="h4", label=f"새 인원 {h4}명이면", note=f"{_who4}. 더 하는 작업 {len(_extra)}개({', '.join(_extra)}), '27 Agent {len(_ag4)}개 더. "
                     + (f"더 지키는 마일스톤 {len(_more)}개: " + ", ".join(_more) if _more else "더 지키는 마일스톤 없음"),
                     heads=h4, internal=new_heads(M4)[1] + new_heads(M4)[2], hires=new_heads(M4)[0], total=round(M4["totals"]["wp"], 1),
                     ms=f"{k4}/{n_ms}", cash=round(IC4["totals"]["cash"]["base"] / EOK, 1), result=""))
SCEN_FILE = pick_file("scenarios.json")
if SCEN_FILE:
    full = json.load(io.open(SCEN_FILE, encoding="utf-8"))[0]
    rows.append(dict(key="h10", label=f"이전 안: 새 인원 {full['heads']}명", note="2027 마일스톤을 모두 지킴 (개발 방법 가정이 조금 다름)", heads=full["heads"], internal=full["internal"], hires=full["hires"],
                     total=full["total"], ms=full["ms"], cash=full["cash"], result=f"경력 채용 {full['hires']}명 포함"))
rows.append(dict(key="h2", label="새 인원 2명", note="핵심 작업만 남겨도 맞출 수 없음", heads="—", internal="—", hires="—", total=0, ms="", cash="—", result="해석 플랫폼, MLOps, AI 가 각각 1명씩은 필요"))
scen = dict(rows=rows, cap=f"사람 수는 일정이 아니라 2027년에 하는 일의 양이 정합니다. 일정을 미루면 같은 일이 남은 달에 몰려 오히려 사람이 더 필요합니다. 새 인원 1명은 1년에 약 11 MM 입니다.")

defT = dict(rows=defer_rows, total=defer_mm, msCount=f"통째로 {n_gone}개, 일부 {n_part}개", agCount=f"{len(defer_ag)}개",
            cap=f"작업이 모두 넘어간 2027 마일스톤 {n_gone}개와 '27 Agent {len(defer_ag)}개는 2028년 계획으로 옮깁니다. '(일부)'는 마일스톤의 다른 작업은 2027년에 남은 경우입니다."
                + (f" 새 인원이 1명 더 있으면 작업 {len(_extra)}개({', '.join(_extra)})를 더 할 수 있습니다('새 인원 수에 따라' 표)." if _extra else ""))

# ---------------------------------------------------------------- 인프라, 비용 설명 (범위에 맞춰)
INFRA, COST = IC.get("infra"), IC.get("cost")
MOVED = IC.get("moved", [])
inf2_moved = any(x.startswith("INF-2") for x in MOVED)
night = {"A7", "A8"} <= KEPT
T_ = IC["totals"]
if INFRA:
    for r in INFRA.get("rows", []):
        c = r["cells"]
        if c[0].startswith("INF-1"):  # 남긴 C3 Agent 만
            c3 = [a for a in ("al1-entity", "sh-design-kb", "vv3-diff-review", "sh-data-query", "ct-guard") if a in {g for w in M["wp"] for g in w["ag"]}]
            c[1] = f"C3 처리 Agent {len(c3)}개({', '.join(c3)}), 월 123~515M 토큰, 야간 배치"
        if c[0].startswith("INF-2") and inf2_moved:
            c[3], c[4], c[5], c[6] = "'28", "'28 (기안 '27.8)", "2028년으로", "합성데이터와 학습을 2028년으로 넘겨 '28 증설과 함께 기안"
        if inf2_moved and c[0].startswith(("INF-4", "INF-5")):
            c[1] = c[1].replace("서버 2대", "서버 1대").replace("약 20kW", "약 10kW")
        if inf2_moved and c[0].startswith("INF-5"):
            c[5] = f"{0.3 / 2:.2f}억"
    tl = INFRA.get("timeline")
    if tl:
        rows_ = []
        for r in tl["rows"]:
            if inf2_moved:
                r = dict(r, name=r["name"].replace("INF-1·2·4·5", "INF-1·4·5").replace("INF-1·INF-2", "INF-1"))
                if r["name"].startswith("브리지 — 학습 GPU"):
                    continue
                if r["name"].startswith("스토리지"):
                    r["note"] = "GT, 실행 기록"
            rows_.append(r)
        tl["rows"] = rows_
        tl["cap"] = ("가동 시점은 낙관 6개월(2027년 6월), 이 계획 7개월(7월), 조사 기준 9개월(9월, 납기 3개월), 보수 2027년 12월~2028년 2월(재심의와 납기 4~6개월)로 봅니다. "
                     "늦어지면 브리지를 그만큼 늘립니다." + (" 브리지 용량이 7월부터 야간 무인해석까지 감당하는지가 조건입니다." if night else ""))
    INFRA["points"] = [
        "온프렘이 필요한 이유는 하나입니다. 도면, STP, BOM 같은 C3 자료는 외부 API 로 보낼 수 없습니다. 비용만 보면 API(3과제 합쳐 연 0.1~0.7억)가 더 쌉니다. 같은 이유로 외부 GPU 클라우드도 브리지가 될 수 없습니다.",
        ("2027년에는 추론 서버(INF-1) 1대만 삽니다. 합성데이터 생성과 학습을 2028년으로 넘겨서, RT 코어가 필요한 시뮬레이션과 학습 서버(INF-2)는 2027년 8월에 2028년 증설과 함께 기안합니다. 이것으로 2027년 투자가 2.8억 줄어듭니다."
         if inf2_moved else
         "서버는 2대로 나눕니다. 추론(INF-1)은 어느 GPU 든 되지만, VV-1 센서 시뮬레이션은 RT 코어가 있어야 해서 INF-2 는 RTX PRO 6000 이어야 합니다. 같은 GPU 로 맞추면 예비 부품과 운영이 하나로 묶입니다."),
        "투자심의 3개월, 발주 1개월, 납기 2개월(표준 PCIe 구성 약 8주), 설치와 보안 1개월이 걸립니다. 11월에 기안하면 2027년 7월에 가동합니다. 그 전 2~6월은 브리지(빅플랜 GPU 먼저 배정 또는 전사 공용 GPU)로 C3 자료를 처리합니다.",
        "스토리지(INF-3)는 투자심의 묶음에서 빼고, 기존 NAS 증설을 IT 일반 구매로 12월에 발주합니다.",
        "2028년 증설과 HIL 벤치는 2027년 8월에 기안합니다. Gate 2 에서 400B급 모델, 야간 정규 운영, 월 30회 학습이 필요해지면 H200 서버와 학습 서버를 더합니다.",
    ]
IC_CHECKS = [c for c in IC.get("checks", []) if not (inf2_moved and c["id"] in ("rt", "train"))]  # INF-2 를 '28 로 옮기면 2027 에는 해당 없음
if COST:
    COST["lines"] = [r for r in COST.get("lines", []) if not (r.get("item") == "소계" and not any(r.get("q", [])))]
    for t in COST.get("tiles", []):
        if t.get("k") == "인건비 증분" and H == 0:
            t["d"] = "새 인원이 모두 사내 전환이라 없음"
    COST["points"] = [
        "증분 현금은 이 계획 때문에 새로 나가는 돈(투자, 운영, 개발 도구)입니다. A와 B, DRI 팀 시간, 사내 전환 인원은 이미 있는 사람이라 '기존 인력 투입'으로 따로 셉니다(현금 아님).",
        (f"새 인원 {NEW}명이 모두 사내 전환이라 인건비 증분은 없습니다. 대신 데려오는 부서의 일이 그만큼 빠지므로, 전환을 협의할 때 그 부서의 빈자리를 어떻게 메울지도 함께 정해야 합니다."
         if H == 0 else f"경력 채용 {H}명의 인건비가 증분 현금에 들어갑니다."),
        "API 는 3과제 합쳐 연 0.1~0.7억으로 작습니다. 온프렘의 이유는 비용이 아니라 반출 금지 자료(C3)이므로, 투자심의는 보안 논리로 올립니다.",
        "빅플랜 GPU 2.88억(RTX PRO 6000 9장)이 이미 집행됐다면 INF-1 2.8억은 그만큼 줄고, 그 장비가 2~6월 브리지가 됩니다.",
        f"투자 {T_['capex']['base'] / EOK:.1f}억을 5년에 나누면 연 {T_['depr'] / EOK:.2f}억 상각입니다(2027년은 7월 가동부터 반년). 유지보수는 3년 무상이 관행이라 2030년부터 구매가의 10% 가 듭니다.",
    ]

D = dict(basis="2026-10-22", lead=lead, decisions=decisions, summary=summary, people=people, method=method, options=options, logic=logic, taskOrder=task_order, model=M,
         roleDetail=ROLE_DETAIL, roleTop=role_top, scen=scen, deferT=defT, glossary=GLOSSARY, axDev=AX_DEV, axFull=AX_FULL, roleShort=ROLE_TINY,
         heatCap="개발 역할은 기존 공급이 거의 없어 조달 전에는 대부분의 칸이 모자랍니다. 붉은 테두리는 사내 조달을 반영한 뒤에도 남는 부족입니다.",
         infra=INFRA, cost=COST, checks=checks + checks_extra + IC_CHECKS, assumptions=assumptions, next=nxt,
         kindSay=KIND_SAY, newKinds=list(NEW_KINDS))


NAME_MAP = [  # 화면용 이름: 조달 방식, A와 B (사람 이름과 팀 이름은 소스와 데이터에서 이미 뺐다)
    ("A·B 개발 투입", "A와 B 개발 참여"), ("AX A·B", "A와 B"), ("A·B", "A와 B"), ("사내 전환배치", "사내 전환"),
    ("MLOps·인프라 엔지니어", "MLOps 인프라 엔지니어"), ("FTE·월", "MM"), ("명·월", "MM"),
]


def anon(t):
    for a, b in NAME_MAP:
        t = t.replace(a, b)
    return t


def _and(tok):  # '열·공차' → '열과 공차', '구조·열·광학' → '구조, 열, 광학'
    if tok.count("·") == 1:
        a, b = tok.split("·")
        if a and "가" <= a[-1] <= "힣" and b:
            return a + ("과 " if (ord(a[-1]) - 0xAC00) % 28 else "와 ") + b
    return tok.replace("·", ", ")


def plain(t):  # 가운뎃점과 줄표 걸러 내기 (사용자 요청)
    t = t.replace(" · ", ", ")
    t = " ".join(_and(w) if "·" in w else w for w in t.split(" "))
    return t.replace(" — ", ", ").replace(" —", ",").replace("— ", "")


tpl = io.open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
data = plain(anon(json.dumps(D, ensure_ascii=False))).replace("</", "<\\/")
frag = tpl.replace("/*__DATA__*/", data)
io.open(os.path.join(HERE, "AX_리소스플랜.html"), "w", encoding="utf-8", newline="\n").write(frag)
full_html = ('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
             '<style>:root{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>' + frag + '</body></html>')
io.open(os.path.join(HERE, "AX_리소스플랜_standalone.html"), "w", encoding="utf-8", newline="\n").write(full_html)
if "--draft" not in sys.argv and os.path.isdir(REPORTS):  # 초안 확인 때는 제출용 사본을 건드리지 않는다
    io.open(os.path.join(REPORTS, "AX_리소스플랜_2027.html"), "w", encoding="utf-8", newline="\n").write(full_html)  # 제출·보관용
io.open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8").write(json.dumps(dict(  # README 와 보고용 숫자
    new=NEW, who=who_list(NEW_KINDS), total_mm=round(tot["wp"], 1), avg=round(tot["wp"] / 12, 1), peak=round(peak_total, 1), borrow=round(borrow, 1),
    defer=[f"{r['id']} {r['name']}" for r in defer_rows], defer_mm=round(defer_mm, 1), ms=dict(kept=n_kept, part=n_part, gone=n_gone, of=n_ms),
    ag_gone=defer_ag, ag_of=n_ag, cash={k: round(v / EOK, 1) for k, v in IC["totals"]["cash"].items()},
    capex=round(IC["totals"]["capex"]["base"] / EOK, 1), opex=round(IC["totals"]["opex"]["base"] / EOK, 1),
    checks=[(c["id"], c["ok"], c["n"], c["of"]) for c in D["checks"]], decisions=[(d["when"], d["what"]) for d in decisions],
    scen=[(r["label"], r["heads"], r["ms"], r["cash"]) for r in rows], options={k: (sum(new_heads(RUNS[k][0])), OPT_INF.get(k)) for k in RUNS}),
    ensure_ascii=False, indent=1))
print("built", len(frag) // 1024, "KB · pick", PICK, "· new heads", NEW, "· deferred", len(defer_rows), "· checks", [c["id"] for c in M["checks"] if not c["ok"]])
