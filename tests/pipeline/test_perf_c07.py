# -*- coding: utf-8 -*-
"""W2 검토 C07 · L11 — 분석 파이프라인 성능·메모리 회귀(결과 숫자·분류는 그대로).

사용자 지시 '작업 완료 후 메모리를 계속 잡지 않도록' · 계약 T-19 · R RPT-46(report build ≤ 10초).

전후 측정(이 PC · `PYTHONHASHSEED=0` · 다른 작업과 함께 돈 값이라 시간은 ±30% 흔들림 · 합성
`stored_rows(density='perf', seed=7)` · `analyze --no-ai`(team_client 없음) · 최고 작업 집합 = 프로세스 PeakWorkingSet):

| 항목 | 3개월 전 | 3개월 후 | 9개월 전 | 9개월 후 |
|---|---|---|---|---|
| 입력 | 행 47,481 · 단위업무 2,736 | 같음 | 행 140,283 · 단위업무 8,091 | 같음 |
| `analyze` 전체 | 148~162초 | 76~80초 | 1,095초(검토 1,527초) | 534초 |
| `hier.classify_all` 호출 | 2회(45~59초씩) | **1회** | 2회(403~434초씩) | **1회**(422초) |
| 번들 증거 적재 `load_evidence`(분석 1회) | 3회(4.3~6.1초씩) | **1회** | 3회(15~16초씩) | **1회** |
| `time.analyze_time` | 7.0~7.8초 | 6.6~7.0초 | 54.2초(검토 67.6초) | 45.4초 |
| 파이프라인 안 report 단계 | 20.0~24.3초 | 4.6~7.3초 | 142초 | 30.7초 |
| cli `report build`(새 프로세스) | 21.3~30.6초 | 10.2~16.1초 | 145.9초(검토 152.9초) | 52.7초 |
| 그중 `ontology.recommendations` | 11~13초 | 1.5초 | 116초 | 15~18초 |
| 최고 작업 집합 | 1,066~1,090MB | **723MB** | 4,811MB(검토 4,788MB) | **3,688MB** |
| report_model.json | 13,047,165B | 같음(run_id 뺀 바이트 동일) | 34,327,453B(상한 33,554,432 초과 — 3단계 줄여도) | 32,172,955B(④까지) |
| time·hier 결과 파일 15종 | — | 바이트 동일 | — | 바이트 동일 |

측정 스크립트·합성 세계는 %TEMP% 에서 만들고 지웠다 — 같은 측정을 이 파일 `PerfTest` 가 3개월로 되풀이한다. 남은 큰 몫:
`hier.classify_all` 1회(3개월 45~58초 · 9개월 400초대, 분류 단계 최고 메모리 — 분류 패키지 몫: 이름 접기 `names.ukey`·
규칙 점수 메모 없음) · 번들 적재(합성 자료는 규칙 판이 낮아 행마다 재정제가 돈다 — 실제 자료는 덜하다).

시험:
- 분류 한 번(`--no-ai` 등 task_label 을 묻지 않는 실행) — 로컬 상태 저장은 그 한 번에서, 예전 경로(분류 두 번)와 결과·로컬
  상태 바이트가 같다. 묻는 실행은 예전처럼 두 번(답 반영).
- 번들 증거 적재 한 번(AI 실행·재분석 포함) — 파이프라인이 만든 모델 = 새로 읽은 cli `report build` 모델(바이트·입력 다이제스트).
- 메모리 사슬 놓기(time 뒤 시간·분류 결과·특징·꼬리표·증거 행 없음) · 묻지 않는 실행은 mining·review 가 보고서 입력을 읽지 않음.
- 성능(자식 프로세스 · 3개월 perf 밀도): 분류 1회 · 적재 1회 · report 단계 ≤ 10초 · cli report build ≤ 20초 · 모델 ≤ 32MB ·
  최고 작업 집합 ≤ 950MB.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import lm27.hier as H
import lm27.normalize.load as NL
from lm27.pipeline import analyze as A
from lm27.pipeline import stages as S
from lm27.report import build_report
from lm27.report import inputs as RI
from lm27.util import events
from tests.fixtures.wp32 import world as W

ROOT = Path(__file__).resolve().parents[2]
OPEN = {"hier.copilot.requireCodenameReview": False}


def _norm(data: bytes, run_id: str) -> bytes:
    return data.replace(run_id.encode("ascii"), b"RUNID")


class _Base(unittest.TestCase):
    def setUp(self):
        events.configure(mode="off")
        self.addCleanup(events.configure, mode="text")
        self.w = self.world()

    def world(self, same_as=None) -> W.World:
        w = W.World(prefix="lm27t_c07_")
        self.addCleanup(w.remove)
        w.put(W.rows())
        w.keyring(same_as)
        return w

    def by(self, w=None) -> dict:
        return {s["id"]: s for s in (w or self.w).status()["stages"]}


class ClassifyOnceTest(_Base):
    def spy(self, calls, *, old_flow=False):
        orig = H.classify_all

        def fn(ctx):
            calls.append((bool(ctx.get("persist")), bool(ctx.get("write_ai_in"))))
            if old_flow and len(calls) == 1:                 # 예전 classify 단계: 저장하지 않는 첫 계산
                ctx = dict(ctx, persist=False)
            return orig(ctx)
        return fn

    def test_no_ai_classifies_once_and_persists(self):
        calls = []
        with mock.patch.object(H, "classify_all", self.spy(calls)):
            self.assertEqual(self.w.analyze(ai=False), 0)
        self.assertEqual(calls, [(True, False)], "task_label 을 묻지 않으면 분류 한 번 — 저장도 그 한 번에서")
        self.assertTrue(self.w.paths.hier_local_file("title_cache.json").is_file(), "로컬 상태(제목 캐시)를 저장했다")
        self.assertEqual(self.by()["time"]["state"], "done")
        self.assertEqual(self.by()["classify"]["counts"]["task_label_items"], 0)

    def test_ai_asked_classifies_twice(self):
        calls = []
        fb = W.FakeBridge()
        with mock.patch.object(H, "classify_all", self.spy(calls)):
            self.assertEqual(self.w.analyze(self.w.cfg(OPEN), ai=True, bridge=fb), 0)
        self.assertIn("ai:task_label", fb.stages())
        self.assertEqual(calls, [(False, True), (True, False)], "물은 실행은 답을 받은 뒤 한 번 더(저장 포함)")

    def test_same_outputs_as_old_two_pass_flow(self):
        """새 경로(분류 1회 · 그때 저장) = 예전 경로(저장 없는 1회 → time 에서 저장하며 다시)의 결과 파일·모델·로컬 상태."""
        old = self.world(same_as=self.w)
        self.assertEqual(self.w.analyze(ai=False), 0)
        calls = []
        orig_time = A._STAGE_FN["time"]

        def old_time(run, sd, act):
            run.hres = None                                  # 예전처럼 time 단계가 다시 분류한다
            return orig_time(run, sd, act)
        with mock.patch.object(H, "classify_all", self.spy(calls, old_flow=True)), \
                mock.patch.dict(A._STAGE_FN, {"time": old_time}):
            self.assertEqual(old.analyze(ai=False), 0)
        self.assertEqual(len(calls), 2)
        for name in W.TIME_FILES:
            self.assertEqual(_norm(self.w.time_bytes(name), self.w.last), _norm(old.time_bytes(name), old.last), name)
        for name in W.HIER_FILES:
            self.assertEqual(_norm(self.w.hier_bytes(name), self.w.last), _norm(old.hier_bytes(name), old.last), name)
        self.assertEqual(_norm(self.w.model_bytes(), self.w.last), _norm(old.model_bytes(), old.last))
        for name in ("title_cache.json", "proposals.json", "rules_learned.json"):
            a, b = self.w.paths.hier_local_file(name), old.paths.hier_local_file(name)
            self.assertEqual(a.is_file(), b.is_file(), name)
            if a.is_file():
                self.assertEqual(a.read_bytes(), b.read_bytes(), name)


class EvidenceOnceTest(_Base):
    def count_loads(self):
        n = [0]
        orig = NL.load_evidence

        def fn(*a, **k):
            n[0] += 1
            return orig(*a, **k)
        return n, mock.patch.object(NL, "load_evidence", fn)

    def assert_cli_same(self):
        cfg = self.w.cfg()
        mine = self.w.model_bytes()
        r = build_report(self.w.last, paths=self.w.paths, cfg=cfg)
        self.assertEqual(r.rc, 4, "입력 다이제스트(증거 포함)가 같아 cli report build 는 건너뛴다")
        r = build_report(self.w.last, paths=self.w.paths, cfg=cfg, force=True)
        self.assertEqual(r.rc, 0)
        self.assertEqual(self.w.model_bytes(), mine, "번들에서 새로 읽은 모델 = 파이프라인 모델(바이트)")

    def test_no_ai_reads_bundle_once(self):
        n, patch = self.count_loads()
        with patch:
            self.assertEqual(self.w.analyze(ai=False), 0)
        self.assertEqual(n[0], 1, "적재 단계 한 번 — mining·review·report 는 다시 읽지 않는다(L11)")
        self.assert_cli_same()

    def test_ai_run_reads_bundle_once(self):
        n, patch = self.count_loads()
        with patch:
            self.assertEqual(self.w.analyze(self.w.cfg(OPEN), ai=True, bridge=W.FakeBridge()), 0)
        self.assertEqual(n[0], 1)
        self.assertEqual(self.by()["mining"]["counts"]["written"], 1)
        self.assert_cli_same()

    def test_reruns_read_bundle_once(self):
        self.assertEqual(self.w.analyze(ai=False), 0)
        first = self.w.last
        for stages in (list(S.QUICK_RERUN), ["report"]):
            with self.subTest(stages=stages):
                n, patch = self.count_loads()
                with patch:
                    self.assertEqual(self.w.analyze(rerun=first, stages=stages, ai=False), 0)
                self.assertEqual(n[0], 1, "재분석도 번들 한 번(시간 결과를 다시 쓰는 경로는 report 가 한 번)")
                self.assert_cli_same()

    def test_evidence_rows_must_match_period(self):
        """적재 행은 같은 기간일 때만 쓴다 — 기간이 다르면 번들에서(앞뒤 하루 여유까지 같아야 같은 증거)."""
        self.assertEqual(self.w.analyze(ai=False), 0)
        n, patch = self.count_loads()
        with patch:
            inp = RI.load_inputs(self.w.last, paths=self.w.paths, cfg=self.w.cfg(),
                                 evidence_rows=("2026-08-01", "2026-08-02", []))
        self.assertEqual(n[0], 1)
        self.assertIsNotNone(inp.evidence_index)
        with patch:
            inp2 = RI.load_inputs(self.w.last, paths=self.w.paths, cfg=self.w.cfg(),
                                  evidence_rows=(W.D0, W.D1, NL.load_evidence(
                                      self.w.paths, self.w.cfg(), "2026-08-31", "2026-09-12", audit=False)))
        self.assertEqual(n[0], 2, "같은 기간이면 넘긴 행으로(번들을 다시 읽지 않음)")
        self.assertEqual(inp2.digests["evidence"], inp.digests["evidence"])


class ReleaseAndSkipTest(_Base):
    def test_chain_released_before_mining(self):
        seen = {}
        orig = A._STAGE_FN["mining"]

        def spy(run, sd, act):
            seen.update(tres=run.tres, hres=run.hres, final=run.hier_final, feats=run.feats, tags=run.tags,
                        ctx=run.hier_ctx, profile=run.profile, rows=run.rows, ev=run.ev_index)
            return orig(run, sd, act)
        with mock.patch.dict(A._STAGE_FN, {"mining": spy}):
            self.assertEqual(self.w.analyze(ai=False), 0)
        for k in ("tres", "hres", "final", "feats", "tags", "profile", "rows"):
            self.assertIsNone(seen[k], k)
        self.assertEqual(seen["ctx"], {})
        self.assertIsInstance(seen["ev"], RI.EvidenceIndex, "증거 보기는 한 번 만들어 report 까지 넘긴다")

    def test_items_not_built_when_not_asked(self):
        n = [0]
        orig = RI.load_inputs

        def fn(*a, **k):
            n[0] += 1
            return orig(*a, **k)
        with mock.patch.object(RI, "load_inputs", fn):
            self.assertEqual(self.w.analyze(ai=False), 0)
        self.assertEqual(n[0], 1, "묻지 않는 실행은 report 만 보고서 입력을 읽는다")
        by = self.by()
        for sid in ("mining", "review"):
            self.assertEqual((by[sid]["state"], by[sid]["counts"]), ("done", {"ai_in": {}, "written": 0}), sid)
            self.assertEqual(by[sid]["items"], "not_asked")
        self.assertFalse(self.w.paths.ai_in("workflow_label").exists())


CHILD = r"""
import ctypes, json, sys, time
from ctypes import wintypes
sys.path.insert(0, sys.argv[1])
from datetime import UTC, date, datetime
from unittest import mock
from lm27.util import events
events.configure(mode="off")

class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]

def peak_mb():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD)
    p = PMC()
    p.cb = ctypes.sizeof(PMC)
    return p.PeakWorkingSetSize / 1048576 if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(p), p.cb) else None

from tests.fixtures.wp32 import world as W
mode, root = sys.argv[2], sys.argv[3]
if mode == "analyze":
    import lm27.hier as H
    import lm27.normalize.load as NL
    import lm27.report as RP
    from tests.fixtures.synth import stored_rows
    w = W.World.__new__(W.World)
    from pathlib import Path
    w.root, w.lad, w.runs = Path(root), Path(root) / "_lad", []
    (w.root / "data").mkdir()
    w.paths = W.TPaths(w.root, lad=w.lad)
    w.put(stored_rows(d0=date(2026, 7, 1), d1=date(2026, 9, 30), density="perf", seed=7))
    w.keyring()
    n = {"classify": 0, "load": 0, "report": []}
    oc, ol, ob = H.classify_all, NL.load_evidence, RP.build_report
    def c(ctx):
        n["classify"] += 1
        return oc(ctx)
    def l(*a, **k):
        n["load"] += 1
        return ol(*a, **k)
    def b(*a, **k):
        t0 = time.perf_counter()
        try:
            return ob(*a, **k)
        finally:
            n["report"].append(time.perf_counter() - t0)
    with mock.patch.object(H, "classify_all", c), mock.patch.object(NL, "load_evidence", l), \
            mock.patch.object(RP, "build_report", b):
        t0 = time.perf_counter()
        rc = w.analyze(from_="2026-07-01", to="2026-09-30", as_of="2026-10-01T09:00:00+09:00", ai=False,
                       now=datetime(2026, 10, 2, tzinfo=UTC))
        el = time.perf_counter() - t0
    m = json.loads(w.model_bytes())
    print(json.dumps({"rc": rc, "seconds": el, "peak_mb": peak_mb(), "classify": n["classify"], "load": n["load"],
                      "report_s": n["report"], "model_bytes": len(w.model_bytes()), "units": len(m["units"]),
                      "trimmed": m["flags"]["trimmed"], "run_id": w.last}))
else:
    import lm27.report as RP
    w = W.World.__new__(W.World)
    from pathlib import Path
    w.root, w.lad, w.runs = Path(root), Path(root) / "_lad", []
    w.paths = W.TPaths(w.root, lad=w.lad)
    t0 = time.perf_counter()
    r = RP.build_report(sys.argv[4], paths=w.paths, cfg=w.cfg(), force=True)
    print(json.dumps({"rc": r.rc, "seconds": time.perf_counter() - t0, "peak_mb": peak_mb()}))
"""


class PerfTest(unittest.TestCase):
    """3개월 perf 밀도(T-19 기준 입력과 같은 밀도) 실제 파이프라인 — 자식 프로세스(최고 작업 집합을 따로 잰다)."""

    def child(self, *args) -> dict:
        cp = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", CHILD, str(ROOT), *args], capture_output=True,
                            timeout=1800, cwd=str(ROOT), env=dict(os.environ),
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(cp.returncode, 0, cp.stderr.decode("utf-8", "replace")[-3000:])
        return json.loads(cp.stdout.decode("utf-8").strip().splitlines()[-1])

    def test_three_months_perf_density(self):
        root = Path(tempfile.mkdtemp(prefix="lm27t_c07perf_"))     # %TEMP% 아래 임시 프로그램 폴더(자식이 data\ 를 만든다)
        self.addCleanup(shutil.rmtree, root, True)
        out = self.child("analyze", str(root))
        self.assertEqual(out["rc"], 0, out)
        self.assertGreater(out["units"], 2000, "T-19 기준 밀도 — 단위업무가 RPT-46 전제(300)보다 훨씬 많다")
        self.assertEqual(out["classify"], 1, out)
        self.assertEqual(out["load"], 1, out)
        self.assertEqual(len(out["report_s"]), 1)
        self.assertLessEqual(out["report_s"][0], 10.0, f"report 단계(RPT-46): {out}")
        self.assertLessEqual(out["model_bytes"], 32 * 1048576, out)
        self.assertEqual(out["trimmed"], [], out)
        self.assertIsNotNone(out["peak_mb"])
        self.assertLessEqual(out["peak_mb"], 950.0, f"최고 작업 집합(전 1,066~1,090MB): {out}")
        cli = self.child("build", str(root), out["run_id"])
        self.assertEqual(cli["rc"], 0, cli)
        self.assertLessEqual(cli["seconds"], 20.0, f"cli report build(전 21~31초): {cli}")


if __name__ == "__main__":
    unittest.main()
