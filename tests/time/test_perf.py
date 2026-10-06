# -*- coding: utf-8 -*-
"""WP-20 성능(T-19 · W-G9): 사람 1명 × 3개월(신호 약 4.3만 — 참조 gates.perf 분포) 시간 코어 ≤ 60초 · ≤ 500MB.

자식 파이썬 하나에서 합성 세계 → 저장 행 → `analyze_time` → 결과 파일 바이트까지 돌리고, 분석 시간과 그 프로세스의
최대 작업 집합(Windows `GetProcessMemoryInfo` 의 PeakWorkingSetSize — 인터프리터·입력 행 포함)을 잰다.
보존(T-01)·월 항등식도 같은 실행에서 확인한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIMIT_S = 60.0
LIMIT_MB = 500.0
CHILD = r"""
import ctypes, json, sys, time
from ctypes import wintypes
sys.path.insert(0, sys.argv[1])
from collections import Counter
from tests.time import scenarios as X
from tests.fixtures.wp20 import harness as H
from lm27.time import analyze_time

class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]

cfg = X.base_cfg()
w, n = H.gen_months(3, 26)
recs, profile, as_of, tags, _over = X.to_inputs(w, cfg)
t0 = time.perf_counter()
r = analyze_time(H.TEST_KEY, recs, profile, X.calendar(), as_of, cfg=cfg, tags=tags)
files = r.files()
el = time.perf_counter() - t0
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD)
pmc = PMC()
pmc.cb = ctypes.sizeof(PMC)
ok = k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
env_day, att_day = Counter(), Counter()
for s in r.env.slots:
    env_day[s * 300 // 86400] += 300
    att_day[s * 300 // 86400] += sum(r.assign[s].values())
ident = all(m["attributed_min"] + m["unattributed_min"] == m["env_min"] for m in r.months.values())
print(json.dumps({"signals": n, "seconds": el, "peak_mb": (pmc.PeakWorkingSetSize / 1e6) if ok else None,
                  "conserve": env_day == att_day, "ident": ident, "files": len(files), "months": len(r.months),
                  "tasks": len(r.tasks)}))
"""


class PerfTest(unittest.TestCase):
    def test_three_months_time_and_memory(self):
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", CHILD, str(ROOT)], capture_output=True,
                            timeout=600, cwd=str(ROOT), env=dict(os.environ),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-2000:])
        out = json.loads(cp.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertGreater(out["signals"], 40000)
        self.assertLessEqual(out["seconds"], LIMIT_S, out)
        self.assertIsNotNone(out["peak_mb"])
        self.assertLessEqual(out["peak_mb"], LIMIT_MB, out)
        self.assertTrue(out["conserve"])                                       # T-01
        self.assertTrue(out["ident"])                                          # 월 항등식
        self.assertEqual((out["files"], out["months"]), (9, 3))


if __name__ == "__main__":
    unittest.main()
