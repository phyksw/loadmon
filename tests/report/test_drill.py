# -*- coding: utf-8 -*-
"""WP-31 근거 드릴다운(R §6.10 · 부록 A `day_drill`·`unit_drill`).

- 날짜(§6.10.2): 날짜 원장(구성요소·차감·제외·꼬리표·신뢰·커버리지·표식) + 구간 원장(시각 HH:MM · 근거 · 대상[[id, 분, O/I/X]] ·
  kind — WP-28 CH-P16 표지) + 단위업무 제목.
- 단위업무(§6.10.3): 차수 경계(코드·시각·추정 여부·증거 번호) · 투입 내역 · 구간 · 증거 줄(전체판만 — 상한 넘으면 '그 밖 n건')
  · 규칙 설명. 가림판은 증거 줄·근거 키 없이.
"""
from __future__ import annotations

import os
import threading
import time
import unittest
from datetime import UTC, datetime

import lm27.report as RP
from lm27.report import drill as D
from lm27.report import model as M
from lm27.report.resolve import Resolver
from tests.fixtures.wp30 import world as W
from tests.fixtures.wp31 import runs as R


def no_fallback(*_a):
    return None


class DrillViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)          # setUpClass 가 중간에 실패해도 임시 ROOT 를 지운다(W2 검토 L12)
        cls.cfg = W.cfg()
        cls.srun = R.rich_run()
        cls.srun.write(cls.t.paths)
        cls.inp = cls.srun.inputs(cls.t.paths, cls.cfg)
        cls.m = M.build_model(cls.inp, cls.cfg, fallback=no_fallback)
        refs = cls.m["refs"]
        cls.res = Resolver("full", cls.inp.person_dir, cls.inp.registry, cls.inp.evidence,
                           people_ref={v["key"]: int(k) for k, v in refs["people"].items()},
                           doc_ref={v["key"]: int(k) for k, v in refs["docs"].items()})
        cls.red = M.redact_model(cls.m, cls.inp.registry, person_dir=cls.inp.person_dir)

    def test_day(self):
        v = D.day_view(self.inp, self.m, "2026-09-02", "full", cfg=self.cfg)
        self.assertEqual(v["s_eff"], ["09:00", "18:00"])
        self.assertFalse(v["hol"])
        led = v["ledger"]
        self.assertEqual(led["deductions"], [["사적차감", 15, 1]])
        self.assertEqual(led["flags"], ["Q08"])
        self.assertEqual(led["total_min"], sum(led["by_tag"].values()))
        self.assertEqual(led["coverage"]["mail_out"], "ok")
        iv = v["intervals"]
        self.assertEqual(iv[0]["a"], "09:00")
        self.assertEqual(iv[0]["b"], "09:05")
        self.assertEqual(iv[0]["kind"], "env")
        self.assertEqual(iv[0]["targets"][0][:3], ["u_a1", 5, "O"])
        self.assertEqual(v["labels"]["u_a1"], "전원부 해석 1")
        self.assertEqual(sum(t[1] for x in iv for t in x["targets"]), led["total_min"])
        self.assertIsNone(D.day_view(self.inp, self.m, "2026-12-01", "full"))
        rv = D.day_view(self.inp, self.red, "2026-09-02", "redacted", cfg=self.cfg)
        self.assertEqual(rv["variant"], "redacted")

    def test_unit_full(self):
        v = D.unit_view(self.inp, self.m, "u_a1", "full", res=self.res)
        self.assertEqual(v["title"], "전원부 해석 1")
        c0 = v["cycles"][0]
        self.assertEqual(c0["start"], {"code": "S1", "t": "2026-09-01 09:30", "estimated": False, "evidence": "e1"})
        self.assertEqual(c0["end"]["code"], "E1")
        self.assertEqual(c0["end"]["evidence"], "e2")
        ev = v["evidence"]
        self.assertEqual(ev[0]["id"], "e1")
        self.assertTrue(ev[0]["role"].startswith("시작 근거(S1 디지털 의뢰)"))
        self.assertEqual(ev[0]["who"], "김철수")
        roles = [e["role"] for e in ev]
        self.assertIn("같은 대화", roles)
        self.assertIn("연결된 회의", roles)
        self.assertIn("다룬 문서", roles)
        docs = [e for e in ev if e["kind"] == "file"]
        self.assertTrue(all(e.get("doc") for e in docs))
        self.assertEqual(v["levels_min"]["L3"], v["effort_min"])
        self.assertEqual(v["obs_min"] + v["est_min"], v["effort_min"])
        self.assertTrue(v["runs"][0]["a"].startswith("2026-09-01 "))
        self.assertEqual(v["explain"], "의뢰 메시지로 시작해 보고를 보낸 시각을 끝으로 봤습니다(등급 A).")
        capped = D.unit_view(self.inp, self.m, "u_a1", "full", res=self.res, cap=2)
        self.assertEqual(len(capped["evidence"]), 2)
        self.assertEqual(capped["evidence_more"], len(ev) - 2)
        self.assertIsNone(D.unit_view(self.inp, self.m, "u_none", "full", res=self.res))

    def test_unit_redacted(self):
        v = D.unit_view(self.inp, self.red, "u_a1", "redacted", res=self.res)
        self.assertNotIn("evidence", v)
        self.assertNotIn("evidence", v["cycles"][0]["start"])
        self.assertTrue(all("docs" not in r for r in v["runs"]))
        self.assertEqual(v["cycles"][0]["start"]["code"], "S1")

    def test_explain_estimated(self):
        t = D.explain_text("S2p", "E3i", "E")
        self.assertIn("추정해", t)
        self.assertTrue(t.endswith("확인 질문으로 바로잡을 수 있습니다."))
        self.assertEqual(D.explain_text("S1", None, "O"), "의뢰 메시지로 시작해 아직 진행 중입니다(등급 O).")

    def test_evidence_cap_setting(self):
        """`report.drill.maxEvidencePerUnit`(G-R9 — 섭동하면 결과가 바뀐다)."""
        import copy
        inp = copy.copy(self.inp)
        ev = copy.deepcopy(self.inp.evidence)
        for i in range(15):
            mid = f"extra{i:02d}"
            ev.msgs.append({"id": mid, "conv": "c1", "peer": R.PEER2, "flags": [], "dir": "in",
                            "t": W.lsec("2026-09-03", "10:00") + i * 60})
            ev.lines[mid] = {"kind": "teams", "t": f"2026-09-03 10:{i:02d}", "dir": "in", "prec": "minute",
                             "who": R.PEER2, "title": "대화"}
        inp.evidence = ev
        lo = D.drill_island(inp, self.m, "full", self.cfg.derive({"report.drill.maxEvidencePerUnit": 10}), res=self.res)
        hi = D.drill_island(inp, self.m, "full", self.cfg, res=self.res)
        self.assertEqual(len(lo["units"]["u_a1"]["evidence"]), 10)
        self.assertGreater(lo["units"]["u_a1"]["evidence_more"], 0)
        self.assertGreater(len(hi["units"]["u_a1"]["evidence"]), 10)
        self.assertEqual(hi["units"]["u_a1"]["evidence_more"], 0)

    def test_island(self):
        isl = D.drill_island(self.inp, self.m, "full", self.cfg, res=self.res)
        self.assertEqual(set(isl), {"units", "days", "trimmed"})
        self.assertEqual(set(isl["units"]), {u["unit_id"] for u in self.m["units"]})
        self.assertIn("2026-09-02", isl["days"])
        self.assertNotIn("2026-09-05", isl["days"])                  # 구간 없는 날은 화면이 모델 days 로
        red = D.drill_island(self.inp, self.red, "redacted", self.cfg)
        self.assertEqual(M.redaction_violations(red, self.inp.person_dir), [])


class DrillApiTest(unittest.TestCase):
    def test_day_unit_drill_from_files(self):
        t = R.TmpRoot()
        self.addCleanup(t.cleanup)
        cfg = W.cfg()
        srun = R.rich_run()
        srun.write(t.paths)
        r = RP.build_report(R.RUN_ID, paths=t.paths, cfg=cfg, fallback=no_fallback,
                            now=datetime(2026, 10, 5, tzinfo=UTC))
        self.assertIn(r.rc, (0, 2))
        d = D.day_drill(R.RUN_ID, "2026-09-02", paths=t.paths, cfg=cfg)
        self.assertEqual(d["d"], "2026-09-02")
        u = D.unit_drill(R.RUN_ID, "u_a2", "redacted", paths=t.paths, cfg=cfg)
        self.assertEqual(u["unit_id"], "u_a2")
        self.assertNotIn("evidence", u)
        s1 = D.DrillSource.load(R.RUN_ID, paths=t.paths, cfg=cfg)
        self.assertIs(D.DrillSource.load(R.RUN_ID, paths=t.paths, cfg=cfg), s1)       # 같은 파일 = 다시 읽지 않음
        mp = t.paths.analysis_report_file(R.RUN_ID, "report_model.json")
        st = os.stat(mp)
        os.utime(mp, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
        self.assertIsNot(D.DrillSource.load(R.RUN_ID, paths=t.paths, cfg=cfg), s1)
        with self.assertRaises(ValueError):
            D.day_drill(R.RUN_ID, "2026-09-02", "team", paths=t.paths, cfg=cfg)
        D.forget()


class DrillCacheLifetimeTest(unittest.TestCase):
    """W2 검토 C18: 드릴다운 캐시가 보고서 입력 전체를 무기한 붙잡던 것 — 유휴 만료·즉시 비우기·적재 직렬화."""

    @classmethod
    def setUpClass(cls):
        cls.t = R.TmpRoot()
        cls.addClassCleanup(cls.t.cleanup)
        cls.cfg = W.cfg()
        R.rich_run().write(cls.t.paths)
        r = RP.build_report(R.RUN_ID, paths=cls.t.paths, cfg=cls.cfg, fallback=no_fallback,
                            now=datetime(2026, 10, 5, tzinfo=UTC))
        assert r.rc in (0, 2), r.message

    def setUp(self):
        D.forget()
        self.addCleanup(D.forget)
        old = D.DrillSource.idle_s
        self.addCleanup(setattr, D.DrillSource, "idle_s", old)

    def test_forget_releases(self):
        D.unit_drill(R.RUN_ID, "u_a2", paths=self.t.paths, cfg=self.cfg)
        self.assertEqual(D.DrillSource.cached(), 1)
        D.forget()
        self.assertEqual(D.DrillSource.cached(), 0)
        self.assertIsNone(D.DrillSource._timer)

    def test_idle_expiry_by_timer(self):
        D.DrillSource.idle_s = 0.3
        D.day_drill(R.RUN_ID, "2026-09-02", paths=self.t.paths, cfg=self.cfg)
        self.assertEqual(D.DrillSource.cached(), 1)
        deadline = time.monotonic() + 10
        while D.DrillSource.cached() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(D.DrillSource.cached(), 0)                  # 아무도 안 쓰면 스스로 놓는다
        self.assertIsNone(D.DrillSource._timer)

    def test_use_keeps_alive_and_stale_hit_reloads(self):
        D.DrillSource.idle_s = 600
        s1 = D.DrillSource.load(R.RUN_ID, paths=self.t.paths, cfg=self.cfg)
        self.assertIs(D.DrillSource.load(R.RUN_ID, paths=self.t.paths, cfg=self.cfg), s1)
        key = next(iter(D.DrillSource._cache))
        sig, src, _ts = D.DrillSource._cache[key]
        D.DrillSource._cache[key] = (sig, src, time.monotonic() - 601)   # 타이머보다 먼저 온 호출 — 만료로 본다
        self.assertIsNot(D.DrillSource.load(R.RUN_ID, paths=self.t.paths, cfg=self.cfg), s1)

    def test_concurrent_cold_loads_read_once(self):
        calls = []
        real = D.DrillSource.__init__

        def counting(this, *a, **kw):
            calls.append(1)
            time.sleep(0.2)                                      # 적재가 느린 동안 두 번째 요청이 온다
            real(this, *a, **kw)
        D.DrillSource.__init__ = counting
        self.addCleanup(setattr, D.DrillSource, "__init__", real)
        got = []
        ths = [threading.Thread(target=lambda: got.append(D.DrillSource.load(R.RUN_ID, paths=self.t.paths,
                                                                            cfg=self.cfg))) for _ in range(2)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(30)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(got), 2)
        self.assertIs(got[0], got[1])


if __name__ == "__main__":
    unittest.main()
