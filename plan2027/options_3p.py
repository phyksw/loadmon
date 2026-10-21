# -*- coding: utf-8 -*-
"""운영안 1안(A), 2안(B)을 3명 계획과 같은 범위('28 로 넘긴 작업 동일)로 돌려, 새 인원이 몇 명 필요한지 찾는다.
혼합안(C)은 scope_fit.py 결과(sourcing_3p.json)를 그대로 쓴다. 출력: design/final/sourcing_{A,B}_3p.json
쓰는 법: python options_3p.py A   (B 와 따로 돌려도 섞이지 않음)"""
import io
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIN = os.path.join(HERE, "design", "final")
WORK = os.path.join(HERE, "out", "options_3p")
os.makedirs(WORK, exist_ok=True)
PY = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")
METH = os.path.join(FIN, "method_3p.json")
defer = json.load(io.open(os.path.join(FIN, "sourcing_3p.json"), encoding="utf-8"))["defer"]

for opt in sys.argv[1:] or ["A", "B"]:
    src = os.path.join(WORK, f"{opt}_empty.json")
    io.open(src, "w", encoding="utf-8").write(json.dumps({"sourcing": [], "defer": defer}, ensure_ascii=False))
    me = os.path.join(WORK, f"{opt}_model.json")
    subprocess.run([PY, "model27.py", "--option", opt, "--sourcing", src, "--method", METH, "--out", me, "--quiet"], cwd=HERE, env=ENV, capture_output=True, check=True)
    for h in range(3, 9):
        so = os.path.join(WORK, f"{opt}_{h}.json")
        if os.path.isfile(so):
            os.remove(so)
        r = subprocess.run([PY, "sourcing_opt.py", "--model", me, "--out", so, "--max-heads", str(h), "--max-internal", str(h), "--slack-w", "2"],
                           cwd=HERE, env=ENV, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and os.path.isfile(so):
            lines = json.load(io.open(so, encoding="utf-8"))["sourcing"]
            io.open(os.path.join(FIN, f"sourcing_{opt}_3p.json"), "w", encoding="utf-8", newline="\n").write(
                json.dumps({"sourcing": lines, "defer": defer, "heads": h}, ensure_ascii=False, indent=1))
            print(opt, "새 인원", h, "명이면 같은 범위가 됨", flush=True)
            break
        print(opt, h, "명으로는 안 됨", flush=True)
    else:
        io.open(os.path.join(FIN, f"sourcing_{opt}_3p.json"), "w", encoding="utf-8", newline="\n").write(
            json.dumps({"sourcing": [], "defer": defer, "heads": None, "infeasible": "8명까지"}, ensure_ascii=False, indent=1))
        print(opt, "8명까지 늘려도 같은 범위가 안 됨", flush=True)
