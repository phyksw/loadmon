# -*- coding: utf-8 -*-
"""새 인원 한도(기본 3명) 안에서 2027 에 할 수 있는 범위 찾기.
우선순위가 낮은 작업부터 '28 로 넘기며(아래 순서) 사내 조달 최적화(sourcing_opt)가 해를 찾는 가장 짧은 지점을 찾고,
그 다음 넘긴 작업을 우선순위 높은 것부터 다시 넣어 보아 들어가는 것은 살린다.
선후 관계를 지킨다: 넘긴 작업의 뒤 작업(after)은 함께 넘기고, 다시 넣을 때는 넘겨 둔 선행 작업까지 묶어서 넣는다.
출력: design/final/sourcing_{N}p.json (조달 + 넘긴 작업) · design/final/scope_{N}p.json (과정 기록)"""
import argparse
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(HERE, "design", "final")
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
ap = argparse.ArgumentParser()
ap.add_argument("--heads", type=int, default=3)
ap.add_argument("--method", default=os.path.join(FIN, "method_3p.json"))
A = ap.parse_args()
WORK = os.path.join(HERE, "out", f"scope_h{A.heads}")  # 인원 한도마다 따로 (동시에 돌려도 섞이지 않게)
os.makedirs(WORK, exist_ok=True)

# 넘기는 순서, 위가 먼저(우선순위 낮음). 끝까지 남기는 것: EM 운영(A1), 구조(A3, A4), 열(A5), SI/PI(H4), EMC(H5), 센서모델과 GT(V1, V2), 운영, 공통
ORDER = [
    ("A9", "최적화 탐색 Agent", "마일스톤 없음. 2028년 광학 확장 전에만 있으면 됨"),
    ("H12", "재설계안 후보 Agent", "마일스톤 없음"),
    ("H8", "설계자료 구성 Agent", "마일스톤 없음"),
    ("A11", "'28 광학 확장 선행", "2028년 1분기에 시작해도 됨"),
    ("H14", "'28 Virtual Prototype 선행", "2028년 2분기 전에만 있으면 됨"),
    ("V11", "'28 HIL 벤치 선행", "2028년 1분기에 시작해도 됨"),
    ("H7", "요구 추적 Agent", "마일스톤 없음"),
    ("H3", "선검증 Agent", "마일스톤 없음"),
    ("A6", "해석 창구 확장", "마일스톤 없음. 다른 과제의 해석 의뢰는 2028년부터"),
    ("V6", "검증 조율, 시나리오 생성 Agent", "마일스톤 없음"),
    ("H1", "도면, BOM 정합성 운영 전환", "마일스톤 없음. 지금 방식으로 1년 더"),
    ("H2", "PLM 조회 창구", "마일스톤 없음. 필요한 자료는 사람이 조회"),
    ("A2", "설계지식DB", "구조 해석 착수 마일스톤은 A3 만으로 지킴"),
    ("V3", "시뮬레이터 연동", "마일스톤 없음"),
    ("H11", "AFM, 수율 선예측 PoC", "새 인원 한도에 들어가지 않음"),
    ("V9", "ODD 커버리지 40%", "새 인원 한도에 들어가지 않음"),
    ("V7", "인지모델 검증", "새 인원 한도에 들어가지 않음"),
    ("V8", "ODD 시나리오 확충", "새 인원 한도에 들어가지 않음"),
    ("A8", "야간 무인해석 시범", "새 인원 한도에 들어가지 않음"),
    ("A7", "야간 무인해석 구축", "새 인원 한도에 들어가지 않음"),
    ("V5", "합성데이터 인지모델 학습", "새 인원 한도에 들어가지 않음"),
    ("V4", "합성데이터 생성", "새 인원 한도에 들어가지 않음"),
    ("H10", "회로, 기구 1차 통합", "새 인원 한도에 들어가지 않음"),
    ("H9", "기구 열, 공차", "새 인원 한도에 들어가지 않음"),
    ("H6", "RVTM 추적체계", "새 인원 한도에 들어가지 않음"),
]
ids = [x[0] for x in ORDER]

# 선후 관계 (전체 범위 모델에서)
_src = os.path.join(WORK, "full_src.json")
io.open(_src, "w", encoding="utf-8").write(json.dumps({"sourcing": []}))
_full = os.path.join(WORK, "full_model.json")
subprocess.run([PY, "model27.py", "--option", "C", "--sourcing", _src, "--method", A.method, "--out", _full, "--quiet"], cwd=HERE, env=ENV, capture_output=True, check=True)
AFTER = {w["id"]: list(w.get("after") or []) for w in json.load(io.open(_full, encoding="utf-8"))["wp"]}
SUCC = {k: [y for y, ps in AFTER.items() if k in ps] for k in AFTER}
PURPOSE = {"C4": ["V4", "V5"]}  # 이 작업들만을 위한 준비 작업 — 모두 넘기면 함께 넘기고, 하나라도 다시 넣으면 함께 넣는다


def close_succ(defer):  # 넘긴 작업의 뒤 작업도 함께 넘김 (준비 작업은 쓰는 작업이 모두 넘어가면 함께)
    out, todo = set(defer), list(defer)
    while todo:
        for y in SUCC.get(todo.pop(), []):
            if y not in out:
                out.add(y)
                todo.append(y)
    out |= {k for k, ps in PURPOSE.items() if all(p in out for p in ps)}
    return out


def preds_in(w, defer):  # 넘겨 둔 선행 작업 (거슬러 올라가며), 그리고 넘겨 둔 준비 작업
    out, todo = set(), [w]
    while todo:
        x = todo.pop()
        for p in AFTER.get(x, []) + [k for k, ps in PURPOSE.items() if x in ps]:
            if p in defer and p not in out:
                out.add(p)
                todo.append(p)
    return out


cache = {}


def feasible(defer, tag):
    defer = sorted(close_succ(defer), key=lambda x: ids.index(x) if x in ids else 99)
    key = tuple(sorted(defer))
    if key in cache:
        return cache[key]
    src = os.path.join(WORK, tag + "_src.json")
    io.open(src, "w", encoding="utf-8").write(json.dumps({"sourcing": [], "defer": list(defer)}, ensure_ascii=False))
    me = os.path.join(WORK, tag + "_model.json")
    subprocess.run([PY, "model27.py", "--option", "C", "--sourcing", src, "--method", A.method, "--out", me, "--quiet"], cwd=HERE, env=ENV, capture_output=True)
    so = os.path.join(WORK, tag + "_opt.json")
    if os.path.isfile(so):
        os.remove(so)
    r = subprocess.run([PY, "sourcing_opt.py", "--model", me, "--out", so, "--max-heads", str(A.heads), "--max-internal", str(A.heads), "--slack-w", "2"],
                       cwd=HERE, env=ENV, capture_output=True, text=True, encoding="utf-8")
    ok = r.returncode == 0 and os.path.isfile(so)
    res = json.load(io.open(so, encoding="utf-8"))["sourcing"] if ok else None
    cache[key] = (ok, res, defer)
    print(("가능 " if ok else "불가 ") + f"{len(defer)}개 넘김: " + ",".join(defer), flush=True)
    return ok, res, defer


ok_hi, _, _ = feasible(ids, "k%d" % len(ids))
if not ok_hi:
    raise SystemExit(f"순서의 작업을 모두 넘겨도 {A.heads}명으로 불가")
lo, hi = 0, len(ids)
while lo < hi:  # 가장 짧은 접두어
    mid = (lo + hi) // 2
    ok, _, _ = feasible(ids[:mid], "k%d" % mid)
    if ok:
        hi = mid
    else:
        lo = mid + 1
defer = set(close_succ(ids[:lo]))
added = []
for wid in reversed(ids):  # 넘긴 것 가운데 우선순위 높은 것부터, 넘겨 둔 선행 작업과 묶어서 다시 넣어 보기
    if wid not in defer:
        continue
    group = {wid} | preds_in(wid, defer)
    ok, _, _ = feasible(defer - group, "back_" + wid)
    if ok:
        defer -= group
        added.append(sorted(group))
ok, src, defer = feasible(defer, "final")
assert ok
io.open(os.path.join(FIN, f"sourcing_{A.heads}p.json"), "w", encoding="utf-8", newline="\n").write(
    json.dumps({"sourcing": src, "defer": defer}, ensure_ascii=False, indent=1))
io.open(os.path.join(FIN, f"scope_{A.heads}p.json"), "w", encoding="utf-8", newline="\n").write(json.dumps(dict(
    heads=A.heads, order=[dict(id=i, name=n, why=w) for i, n, w in ORDER], defer=defer, added_back=added, after={k: v for k, v in AFTER.items() if v}, purpose=PURPOSE),
    ensure_ascii=False, indent=1))
print("넘김", defer)
for x in src:
    print(f"  {x['role']:5} {x['kind']:10} {x['fte']:.1f} {x['s']:>2}~{x['e']:<2} {x.get('note', '')}")
