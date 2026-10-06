# -*- coding: utf-8 -*-
"""WP-33 [수집] 통합 — %TEMP% 복제 트리에서 진짜 색인 수집기(Get-OutlookIndex.ps1, LM_INDEX_FAKE 합성 행) → 진짜 정제 파이프
(lm27_pipe.py --mode append → 복제 안 로컬 원장) → 내보내기(세그먼트) → 커버리지 원장·빈칸 계획(계약 §7.3 · §8.2 · TAB §1.7).

실 색인·실 Outlook·실 %LOCALAPPDATA% 접근 0: 수집기는 LM_INDEX_FAKE 만 읽고, LOCALAPPDATA 는 복제 안 샌드박스다.
탐침·에이전트는 가짜(작업 등록 0). 원문(제목·주소)은 파이프 메모리에서만 — 세그먼트·원장·단계 결과에 없어야 한다.
"""
from __future__ import annotations

import json
import unittest

from lm27.bundle import loader
from lm27.collect import ledger
from lm27.collect import run as R
from lm27.collect import stage_result as sr
from lm27.paths import APP_DIR, Paths
from lm27.store import load_raw_cursor
from lm27.util import events, fsx
from tests.fixtures import synth
from tests.fixtures.synth.inject import index_fake
from tests.fixtures.tree import guard_write, make_clone
from tests.fixtures.wp33.helpers import FakeDeps, cfg_of, ident, probe_result

CAPS = {"env": {"status": "ok"}, "mail.index": {"status": "ok"}, "cal.index": {"status": "ok"}}


class _Sb:
    """FakeDeps 가 쓰는 샌드박스 모양(paths·work) — 복제 트리 위."""

    def __init__(self, clone):
        self.paths = Paths(clone.root, lad=clone.lad / APP_DIR)
        self.work = clone.sandbox / "wp33work"
        self.work.mkdir(parents=True, exist_ok=True)

    def write_json(self, name, obj):
        p = guard_write(self.work / name)
        p.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return p


class RealPipeIndexCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clone = make_clone(parts=("lm27", "collect", "config"))
        (cls.clone.root / "data").mkdir(exist_ok=True)
        plan = synth.plan_month(2026, 9)
        cls.fake = guard_write(cls.clone.sandbox / "index_fake.json")
        cls.fake.write_bytes(json.dumps(index_fake(plan), ensure_ascii=False).encode("utf-8"))
        cls.n_mail = sum(1 for _ in index_fake(plan)["mail"])

    @classmethod
    def tearDownClass(cls):
        cls.clone.remove()

    def setUp(self):
        events.configure("off")
        self.addCleanup(events.configure, "text")

    def test_index_to_segments_and_ledger(self):
        c = self.clone
        sb = _Sb(c)
        cfg = cfg_of(c.sandbox)
        d = FakeDeps(sb, cfg, ident_=ident("REAL"), probe=probe_result(CAPS), real_pipe=True,
                     real_collectors=("mail.index",), env=c.env({"LM_INDEX_FAKE": str(self.fake)}))
        # 일정 색인(cal.index)은 반복 마스터를 rc 3 으로 낸다 — 상태 줄 형(C1)·R-RECURINC(C4) 정렬은 W1 통합 창 몫이라 메일만
        res = R.collect_here(sb.paths, cfg, deps=d, since="2026-09-01", until="2026-09-30", only=["mail.index"])
        st = sr.read_stage_result(sb.paths, res.run_id, "mail_local")
        self.assertEqual(sr.validate_stage_result(st, collect=True), [])
        self.assertEqual(st["state"], "done", st)
        self.assertGreater(st["items_ok"], 0)
        self.assertEqual(st["srcs"]["mail.index"]["ranges"], [["2026-09-01", "2026-09-30"]])
        self.assertEqual(res.rc, 0)
        # 파이프가 출력 기록 성공 뒤에만 커서를 저장했다(계약 §7.3)
        self.assertIn("mail.index", load_raw_cursor(sb.paths, res.pc_id))
        # 로컬 원장 → 번들 세그먼트
        ex = sr.read_stage_result(sb.paths, res.run_id, "export")
        self.assertGreater(ex["counts"]["new"].get("mail", 0), 0)
        rows = list(loader.iter_records(sb.paths, "mail", "2026-09-01", "2026-09-30", cfg=cfg))
        self.assertEqual(len(rows), ex["counts"]["new"]["mail"])
        self.assertTrue(all(r["src"] == "mail.index" and r["pc_id"] == res.pc_id for r in rows))
        # 원장: 레코드가 있는 날 ok, 읽었지만 없는 날 zero_ok(창 안) — 미관측과 구분
        cells = [x for x in ledger.load_cells(sb.paths) if x["src"] == "mail.index" and x["kind_axis"] == "mail_in"]
        sept = [x for x in cells if "2026-09-01" <= x["date"] <= "2026-09-30"]
        self.assertTrue(any(x["status"] == "ok" for x in sept))
        self.assertTrue(all(x["status"] in ("ok", "zero_ok") for x in sept))
        octo = [x for x in cells if x["date"] > "2026-09-30"]
        self.assertTrue(octo and all(x["status"] == "not_attempted" for x in octo))
        # 원문 0: 원장·빈칸 계획·단계 결과에는 제목·주소가 없고, 세그먼트에는 주소 평문이 없다(키·정제문만)
        raw = json.loads(self.fake.read_bytes())["mail"]
        subjects = {r["System.Subject"] for r in raw[:20]}
        addrs = {a for r in raw[:20] for a in r["System.Message.FromAddress"] + r["System.Message.ToAddress"]}
        meta = [fsx.read_bytes(sb.paths.coverage_ledger()), fsx.read_bytes(sb.paths.todo()),
                fsx.read_bytes(sb.paths.stage_result_file(res.run_id, "mail_local"))]
        seg = json.dumps(rows, ensure_ascii=False).encode("utf-8")
        for n in subjects | addrs:
            for b in meta:
                self.assertNotIn(n.encode("utf-8"), b)
        for n in addrs:
            self.assertNotIn(n.encode("utf-8"), seg)
        # 다시 [수집]: 커서 이후 새것 없음 → 같은 레코드를 두 번 내보내지 않는다(CM-19 — 덧붙이기만, 중복 0)
        res2 = R.collect_here(sb.paths, cfg, deps=d, only=["mail.index"])
        rows2 = list(loader.iter_records(sb.paths, "mail", "2026-09-01", "2026-09-30", cfg=cfg))
        self.assertEqual(len(rows2), len(rows))
        self.assertIn(res2.rc, (0, 4))


if __name__ == "__main__":
    unittest.main()
