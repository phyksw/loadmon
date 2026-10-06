# -*- coding: utf-8 -*-
"""WP-13 연결자·수확 시험 — ``lm27.agent.harvest``(계약 §7.3 · §8.2 · X-300 · X-303 · X-306 · C1 · TAB §1.6.1 ②).

  · ``_in`` 제어 줄: 커서(raw_cursor 의 그 경로 칸) · cfg(그 수집기가 쓰는 §5.2 키만 — agent_config 값 + 정제 문맥의 사적 폴더
    낱말·최종 이름 낱말) · self_names(팀즈 수집기만 — context_cache.self_names 전체). 필요한 키가 없으면 그 흐름을 돌리지 않는다.
  · 가짜 수집기·가짜 파이프(합성 스크립트)로: 바이트 그대로 넘김 · 상태 줄(C1 — stderr 마지막 _status, 모르는 칸 무시) ·
    파이프 waitSec 초과 → kill_tree + 코드 99 · 수집기 상한 초과 → kill_tree + R-TRANSPORT · 파이프 6 → R-NOKEY.
  · 수확 1회: .harvest.lock(이미 수확 중이면 rc 4, 파일 안 씀) · harvest_done.json(lm27.harvest_done/1 — 원문 없음).
  · 실물 이음(복제 트리): 진짜 Get-EventActivity.ps1(시험 주입 -EventsCsv) → 진짜 정제 파이프 → 샌드박스 store · 커서 저장 ·
    다음 회 커서 이후 0(중복 0). 실제 이벤트 로그는 읽지 않는다.
"""
import json
import threading
import time
import unittest
from datetime import UTC, datetime

from lm27.agent import harvest as HV
from lm27.store import file_lock, load_raw_cursor, read_store_since, save_raw_cursor
from tests.fixtures.tree import CloneTestCase
from tests.fixtures.wp13 import helpers as H


class InLineTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.agent_files()
        self.st = HV.load_settings(self.sb.paths)
        self.cc = HV.load_ctxcache(self.sb.paths)

    def test_settings_and_cache_loaded(self):
        self.assertIn("pc.watchExtensions", self.st)
        self.assertNotIn("schema", self.st)
        self.assertEqual(self.cc.get("schema"), "lm27.ctxcache/1")

    def test_teams_line(self):
        line = HV.in_line(HV.COLLECTORS["teams.uia"], self.st, self.cc, {"last_ts_utc": "2026-10-05T00:00:00Z"})
        body = line["_in"]
        self.assertEqual(body["cursor"], {"last_ts_utc": "2026-10-05T00:00:00Z"})
        self.assertEqual(set(body["cfg"]), {"teams.timeRegex", "teams.uia.visibleOnly", "teams.uia.maxElements",
                                            "teams.uia.windowWatchdogSec", "teams.uia.budgetSec"})
        self.assertEqual(body["self_names"], self.cc["self_names"])          # X-306 — 결과 하나를 그대로
        self.assertIn("홍길동", body["self_names"])

    def test_file_lines_carry_ctx_values(self):
        for src, spec in (("pc.files", HV.COLLECTORS["pc.files"]), ("poll", HV.POLL)):
            body = HV.in_line(spec, self.st, self.cc, None)["_in"]
            self.assertIn("pc.watchExtensions", body["cfg"], src)
            self.assertEqual(body["cfg"]["privacy.path.excludeKeywords"], self.cc["path_exclude"])
            self.assertIn("episode.finalWords", body["cfg"])
            self.assertNotIn("self_names", body)
            self.assertIsNone(body["cursor"])
        self.assertIn("agent.filePoll.topN", HV.in_line(HV.POLL, self.st, self.cc, None)["_in"]["cfg"])
        ev = HV.in_line(HV.COLLECTORS["pc.events"], self.st, self.cc, None)["_in"]
        self.assertEqual(set(ev["cfg"]), {"collect.lookbackDays"})

    def test_missing_required_setting_skips(self):
        st = {k: v for k, v in self.st.items() if k != "pc.watchExtensions"}
        self.assertIsNone(HV.in_line(HV.COLLECTORS["pc.mru"], st, self.cc, None))
        self.assertIsNotNone(HV.in_line(HV.COLLECTORS["pc.events"], st, self.cc, None))

    def test_timeouts(self):
        self.assertEqual(HV.collector_timeout(HV.COLLECTORS["teams.uia"], {"teams.uia.budgetSec": 40}), 70)
        self.assertEqual(HV.collector_timeout(HV.COLLECTORS["pc.events"], {}), 90)
        self.assertEqual(HV.collector_timeout(HV.COLLECTORS["pc.files"], {"pc.files.budgetSec": 180}), 300)
        self.assertEqual(HV.collector_timeout(HV.POLL, {}), 150)
        self.assertEqual(HV.pipe_wait({"privacy.pipe.waitSec": 5}), 30.0)          # 하한
        self.assertEqual(HV.pipe_wait({}), 120.0)


class ParseTest(unittest.TestCase):
    def test_status_last_line_unknown_fields_ignored(self):
        err = 'x\n{"_status": {"rc": 1}}\n잡음\n{"_status": {"schema": "lm27.collector_status/1", "rc": 3, "reasons": ["R-UIAEMPTY"], "new_field": 1}}\n'
        st = HV.parse_status(err)
        self.assertEqual((st["rc"], st["reasons"]), (3, ["R-UIAEMPTY"]))
        self.assertIsNone(HV.parse_status("no json\n"))
        self.assertIsNone(HV.parse_status('{"_status": "bad"}'))

    def test_summary(self):
        self.assertEqual(HV.parse_summary('경고\n{"ok": true, "rows_in": 3, "stored": 2}\n')["stored"], 2)
        self.assertIsNone(HV.parse_summary(""))


class ConnectorTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.agent_files()
        self.pc = "pc_0a1b2c3d4e5f6a7b"
        save_raw_cursor(self.sb.paths, self.pc, "teams.uia", {"last_ts_utc": "2026-10-04T00:00:00Z"})

    def run_conn(self, rt, src="teams.uia", **kw):
        return HV.run_connector(self.sb.paths, self.pc, src, rt=rt, **kw)

    def test_bytes_forwarded_and_in_passed(self):
        r = self.run_conn(H.fake_runtime(self.sb, n=3))
        self.assertEqual((r.rc, r.pipe, r.stored, r.cursor_saved, r.timed_out, r.reasons), (0, 0, 3, True, False, []))
        echo = r.status["echo_in"]["_in"]
        self.assertEqual(echo["cursor"], {"last_ts_utc": "2026-10-04T00:00:00Z"})
        self.assertIn("teams.uia.budgetSec", echo["cfg"])
        self.assertIn("홍길동", echo["self_names"])
        d = r.as_dict()
        self.assertEqual(d["status"]["extra"], 1)                           # 모르는 칸은 그대로(해석은 쓰는 쪽)
        json.dumps(d)

    def test_collector_rc3_reason_passthrough(self):
        r = self.run_conn(H.fake_runtime(self.sb, n=0, rc=3))
        self.assertEqual((r.rc, r.pipe, r.reasons), (3, 0, ["R-UIAEMPTY"]))

    def test_pipe_wait_exceeded_kills_99(self):
        t0 = time.monotonic()
        r = self.run_conn(H.fake_runtime(self.sb, pipe_mode="sleep"), pipe_wait_s=2)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertEqual((r.rc, r.pipe, r.stored, r.cursor_saved), (0, 99, 0, False))
        self.assertIn("R-TRANSPORT", r.reasons)

    def test_collector_timeout_kills(self):
        t0 = time.monotonic()
        r = self.run_conn(H.fake_runtime(self.sb, col_mode="sleep"), collector_timeout_s=2, pipe_wait_s=20)
        self.assertLess(time.monotonic() - t0, 40)
        self.assertTrue(r.timed_out)
        self.assertIsNone(r.rc)
        self.assertEqual(r.pipe, 0)
        self.assertIn("R-TRANSPORT", r.reasons)

    def test_clm_status_via_pipe_summary(self):
        """CLM 모드 — 상태 줄이 stdout 제어 줄로 와 파이프 요약의 collector_status 로 돌아온다(C1). 사유도 그대로."""
        r = self.run_conn(H.fake_runtime(self.sb, col_mode="clm", n=0, rc=3))
        self.assertEqual((r.rc, r.pipe, r.stored, r.reasons), (3, 0, 0, ["R-UIAEMPTY"]))
        self.assertEqual((r.status["n"], r.status["extra"]), (0, 1))

    def test_pipe_nokey(self):
        r = self.run_conn(H.fake_runtime(self.sb, pipe_mode="nokey"))
        self.assertEqual((r.pipe, r.reasons), (6, ["R-NOKEY"]))

    def test_abort_event(self):
        ev = threading.Event()
        ev.set()
        t0 = time.monotonic()
        r = self.run_conn(H.fake_runtime(self.sb, col_mode="sleep"), abort=ev)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertTrue(r.timed_out)

    def test_skip_without_settings(self):
        self.sb.paths.agent_config().unlink()
        r = self.run_conn(H.fake_runtime(self.sb), src="pc.files")
        self.assertEqual((r.skipped, r.rc, r.pipe), ("settings_missing", None, None))


class HarvestRunTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.agent_files()
        self.pc = "pc_0a1b2c3d4e5f6a7b"

    def test_done_file(self):
        now = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)
        done = HV.run_harvest(self.sb.paths, H.IID, self.pc, HV.HARVEST_STREAMS, requested=True,
                              rt=H.fake_runtime(self.sb), now=lambda: now)
        f = self.sb.read_json(self.sb.paths.harvest_done())
        self.assertEqual(f, done)
        self.assertEqual((f["schema"], f["install_id"], f["pc_id"], f["requested"], f["rc"]),
                         ("lm27.harvest_done/1", H.IID, self.pc, True, 0))
        self.assertEqual(set(f["streams"]), {"pc.events", "pc.files", "pc.mru", "pc.recent"})
        self.assertEqual(f["started_at"], "2026-10-05T03:00:00Z")
        self.assertNotIn("합성 제목", json.dumps(f, ensure_ascii=False))      # 원문 없음

    def test_busy_lock(self):
        with file_lock(self.sb.paths.harvest_lock(), 1):
            out = {}
            t = threading.Thread(target=lambda: out.update(HV.run_harvest(self.sb.paths, H.IID, self.pc, rt=H.fake_runtime(self.sb))))
            t.start()
            t.join(30)
        self.assertEqual(out, {"rc": 4, "busy": True})
        self.assertFalse(self.sb.paths.harvest_done().exists())

    def test_bad_stream_rejected(self):
        with self.assertRaises(ValueError):
            HV.run_harvest(self.sb.paths, H.IID, self.pc, ["pc_file/pc.events"], rt=H.fake_runtime(self.sb))

    def test_start_child_argv(self):
        seen = []
        ident = type("I", (), {"install_id": H.IID, "pc_id": self.pc})()
        HV.start_harvest_child(ident, HV.HARVEST_STREAMS, paths=self.sb.paths, requested=True,
                               spawn=lambda argv, **kw: seen.append((argv, kw)))
        HV.start_harvest_child(ident, ["teams/teams.uia"], paths=self.sb.paths, impl="ps",
                               spawn=lambda argv, **kw: seen.append((argv, kw)))
        py, ps = seen[0][0], seen[1][0]
        self.assertEqual(py[1:5], ["-X", "utf8", "-I", "-B"])
        self.assertEqual(py[py.index("--harvest") + 1], ",".join(HV.HARVEST_STREAMS))
        self.assertIn("--requested", py)
        self.assertEqual(ps[ps.index("-Streams") + 1], "teams/teams.uia")
        self.assertTrue(ps[ps.index("-File") + 1].lower().endswith("harvest.ps1"))
        self.assertEqual(seen[0][1]["stdout"], HV.proc.DEVNULL)


class RealPipeTest(CloneTestCase):
    """실물 이음: 복제 트리의 Get-EventActivity.ps1(시험 주입) → 복제 트리 lm27_pipe.py(프로그램 폴더 모드) → 샌드박스 store."""

    def test_events_end_to_end(self):
        from lm27.paths import Paths
        c = self.clone
        paths = Paths(c.root, lad=c.lad / "LoadMonitor27")
        csv = c.temp / "wp13" / "ev.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        rows = ["t,kind,src", "2026-09-01 08:50,on,6005", "2026-09-01 12:00,off,42", "2026-09-01 13:00,on,1",
                "2026-09-01 18:10,off,6006"]
        csv.write_bytes(("\r\n".join(rows) + "\r\n").encode("ascii"))
        rt = HV.Runtime(paths=paths, python=str(c.python), pipe=str(c.path("lm27_pipe.py")), powershell=H.powershell(),
                        cwd=str(c.temp), env=c.env())
        pc = "pc_0a1b2c3d4e5f6a7b"
        args = ["-EventsCsv", str(csv), "-Now", "2026-09-02 09:00", "-Since", "2026-09-01", "-Until", "2026-09-30"]
        st = {"collect.lookbackDays": 120, "privacy.pipe.waitSec": 120}
        r = HV.run_connector(paths, pc, "pc.events", settings=st, ctxcache={}, rt=rt, extra_args=args)
        self.assertEqual((r.rc, r.pipe, r.timed_out), (0, 0, False), r.as_dict())
        self.assertEqual(r.stored, 2)
        self.assertTrue(r.cursor_saved)
        recs, _cur, _g = read_store_since(paths, pc, "pc_session", "pc.events", None)
        self.assertEqual(sorted(x["event_class"] for x in recs), ["boot", "wake"])
        self.assertTrue(load_raw_cursor(paths, pc)["pc.events"]["last_ts_utc"])
        r2 = HV.run_connector(paths, pc, "pc.events", settings=st, ctxcache={}, rt=rt, extra_args=args)
        self.assertEqual((r2.rc, r2.stored), (4, 0))                        # 커서 이후 신규 0
        self.assertEqual(r2.status.get("schema"), "lm27.collector_status/1")


if __name__ == "__main__":
    unittest.main()
