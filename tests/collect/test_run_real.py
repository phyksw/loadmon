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


def _idx_row(subject: str, when: str) -> dict:
    """색인 메일 행(합성 — 자리표시자 이름·주소). ``when`` = 로컬 'yyyy-MM-dd HH:mm'."""
    return {"System.ItemUrl": f"mapi://lm27t/inbox/{subject}", "System.ItemFolderPathDisplay": "\\받은 편지함",
            "System.Subject": subject, "System.ItemDate": when, "System.Message.DateReceived": when,
            "System.Message.FromName": ["김철수"], "System.Message.FromAddress": ["Chulsoo.Kim@corp.example"],
            "System.Message.ToAddress": ["gildong.hong@corp.example"], "System.Message.ToName": ["홍길동"],
            "System.Message.CcAddress": [], "System.Message.CcName": [], "System.Kind": ["email"]}


class DefaultWindowRealCase(unittest.TestCase):
    """W2 검토 C03(V6) 재현 — 기본 [수집](since 없음)이 진짜 색인 수집기에 기본 시작일(1월 1일)을 넘긴다. 예전에는 아무것도
    넘기지 않아 수집기는 89일만 읽고 원장은 1월 1일부터 읽었다고 적어 2월·6월 메일이 있는 날이 zero_ok 였다."""

    @classmethod
    def setUpClass(cls):
        cls.clone = make_clone(parts=("lm27", "collect", "config"))
        (cls.clone.root / "data").mkdir(exist_ok=True)
        fake = {"mail": [_idx_row("WP33 2월 메일", "2026-02-02 10:00"), _idx_row("WP33 6월 메일", "2026-06-02 10:00"),
                         _idx_row("WP33 10월 메일", "2026-10-01 10:00")], "calendar": [],
                "_my_addrs": ["gildong.hong@corp.example"], "_classic": True}
        cls.fake = guard_write(cls.clone.sandbox / "index_fake_c03.json")
        cls.fake.write_bytes(json.dumps(fake, ensure_ascii=False).encode("utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.clone.remove()

    def setUp(self):
        events.configure("off")
        self.addCleanup(events.configure, "text")

    def test_default_run_reads_from_year_start(self):
        c = self.clone
        sb = _Sb(c)
        cfg = cfg_of(c.sandbox)                                     # 기본: lookbackDays 120 · sinceYearStart 켜짐
        d = FakeDeps(sb, cfg, ident_=ident("C03"), probe=probe_result(CAPS), real_pipe=True,
                     real_collectors=("mail.index",), env=c.env({"LM_INDEX_FAKE": str(self.fake)}))
        res = R.collect_here(sb.paths, cfg, deps=d, only=["mail.index"])
        argv = d.collector_calls("mail.index")[0][2]
        self.assertEqual(argv[argv.index("-Since") + 1], "2026-01-01")
        st = sr.read_stage_result(sb.paths, res.run_id, "mail_local")
        self.assertEqual(st["srcs"]["mail.index"]["ranges"], [["2026-01-01", "2026-10-05"]])
        self.assertEqual(st["items_ok"], 3, st)                      # 2월·6월·10월 메일 모두 읽음
        cells = {x["date"]: x["status"] for x in ledger.load_cells(sb.paths)
                 if x["src"] == "mail.index" and x["kind_axis"] == "mail_in"}
        for day in ("2026-02-02", "2026-06-02", "2026-10-01"):
            self.assertEqual(cells[day], "ok", day)                  # 예전: 2월·6월이 zero_ok(메일이 있는데 0건)
        self.assertEqual(cells["2026-03-02"], "zero_ok")             # 읽었고 없는 날
        self.assertEqual(cells["2026-01-15"], "out_of_horizon")      # 색인 지평선(가장 오래된 항목) 앞 — 0h 아님



class LoginPendingRealCase(unittest.TestCase):
    """v1.3 §0.8 V18 — 진짜 Get-OutlookWeb.py(LM_OWA_FAKE 화면: 로그인 보류 짧은 확인 · 개인 계정)가 상태 줄에 login_pending ·
    login_account 를 싣고, 연결자가 그 경로를 skipped=login_pending 으로 남기며 같은 프로필의 팀즈 웹은 띄우지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.clone = make_clone(parts=("lm27", "collect", "config"))
        (cls.clone.root / "data").mkdir(exist_ok=True)
        cls.fake = guard_write(cls.clone.sandbox / "owa_fake_v18.json")
        cls.fake.write_bytes(json.dumps({"login": True, "login_pending": True, "login_account": "personal"}).encode())

    @classmethod
    def tearDownClass(cls):
        cls.clone.remove()

    def test_web_collector_login_pending_end_to_end(self):
        import io
        out = io.StringIO()
        events.configure("jsonl", stream=out, reset_seq=True)
        self.addCleanup(events.configure, "text")
        c = self.clone
        sb = _Sb(c)
        cfg = cfg_of(c.sandbox, **{"collect.lookbackDays": 10, "collect.sinceYearStart": False})
        d = FakeDeps(sb, cfg, ident_=ident("V18"), probe=probe_result(CAPS), real_collectors=("cal.owa",),
                     env=c.env({"LM_OWA_FAKE": str(self.fake)}))
        res = R.collect_here(sb.paths, cfg, deps=d, only=["cal.owa", "teams.web"])
        bo = sr.read_stage_result(sb.paths, res.run_id, "backfill_owa")
        ob = bo["srcs"]["cal.owa"]
        self.assertEqual((ob["rc"], ob["reasons"], ob["skipped"]), (2, ["R-LOGIN"], "login_pending"))
        self.assertEqual(d.collector_calls("teams.web"), [])            # 같은 전용 프로필 — 다시 띄우지 않는다(V10)
        bt = sr.read_stage_result(sb.paths, res.run_id, "backfill_teams_web")
        self.assertEqual(bt["srcs"]["teams.web"]["skipped"], "login_pending")
        texts = [json.loads(x).get("text_ko") for x in out.getvalue().splitlines() if '"notice"' in x]
        self.assertIn(R.NOTICE_LOGIN_PENDING, texts)
        from lm27.bridge.session import LOGIN_PERSONAL_TEXT
        self.assertIn(LOGIN_PERSONAL_TEXT, texts)


if __name__ == "__main__":
    unittest.main()
