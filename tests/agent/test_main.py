# -*- coding: utf-8 -*-
"""WP-13 감독 루프 시험 — ``lm27.agent.main``(TAB §1.6.3 · §1.6.7 · CP §3 · §8 · P §3.6 · §9.4).

가짜 Win32·가상 시계·가짜 뮤텍스·가짜 수확 자식으로 루프를 돌려(실 PC 수집 0) 다음을 확인한다:
  · CP-7 간격 30·60·120초 — 행의 ``ts_end − ts_utc`` = 실제 간격(설정 간격 가정 결함 회귀), 절전 뒤 틈은 명목 간격만.
  · CP-1(수집 측) — 모든 행에 pc_id·간격·유휴 원값, 고착 판정은 하지 않음.
  · 플러시: 첫 표본 즉시 · 행 수 상한 · 세션 잠금 · 종료(남은 버퍼 0) · heartbeat 필드(TAB §1.6.3).
  · 수확 자식: 로그온 직후 · 주기 · harvest_now.flag(요청 뒤 깃발 삭제).
  · P-T34 사본 규칙 해시 불일치 → 수집 중지 + heartbeat R-RULESMISMATCH · P-T29 하위 키 없음 → 행은 저장(doc_key 없음 ·
    flags.no_key · ``[사람#`` 0) + heartbeat R-NOKEY · TAB-B26 pc_id 변동 → agent.json 갱신·새 pc_id 의 store.
  · 연산 구간 → pc_compute 행 · 미지 exe → exe_meta.json(정제 통과값) · T-07 카나리아 0(store·감사·exe_meta·heartbeat·로그).
"""
import io
import json
import unittest
from datetime import timedelta

from lm27.agent import main as M
from lm27.privacy import keys as K
from lm27.store import read_store_since
from tests.fixtures.canary import canaries, find_canaries
from tests.fixtures.wp13 import helpers as H


class _Base(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.agent_files()

    def rows(self, ag, kind="pc_session", src="pc.sampler"):
        recs, _c, _g = read_store_since(self.sb.paths, ag.pc_id, kind, src, None)
        return recs

    def hb(self):
        return self.sb.read_json(self.sb.paths.heartbeat())


class LoopTest(_Base):
    def test_intervals_30_60_120(self):
        """CP-7 — 행 간격은 레코드 값(ts_end − ts_utc)이 정본이다(설정 간격 가정 회귀)."""
        for nominal in (30, 60, 120):
            sb = H.Sandbox()
            self.addCleanup(sb.cleanup)
            sb.agent_files(cfg=sb.cfg(**{"agent.sampleIntervalSec": nominal}))
            ag, _clk = H.make_agent(sb)
            self.assertEqual(ag.run(max_ticks=6), 0)
            recs, _c, _g = read_store_since(sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
            self.assertEqual(len(recs), 6, nominal)
            spans = [(M._parse_utc(r["ts_end"]) - M._parse_utc(r["ts_utc"])).total_seconds() for r in recs]
            self.assertEqual(spans[:-1], [nominal] * 5, nominal)
            self.assertTrue(1 <= spans[-1] <= nominal)                     # 마지막 표본 = 종료까지
            for r in recs:
                self.assertEqual(r["pc_id"], ag.pc_id)
                self.assertIn("idle_sec", r)
                self.assertNotIn("stuck", r.get("flags") or {})          # CP-1 수집 측: 고착 판정 없음

    def test_sleep_gap_uses_nominal_only(self):
        ag, clk = H.make_agent(self.sb)
        orig = ag._tick
        calls = []

        def tick(now):
            calls.append(now)
            if len(calls) == 3:
                clk.t += timedelta(hours=3)                              # 절전 — 다음 틱이 3시간 뒤
            orig(now)
        ag._tick = tick
        ag.run(max_ticks=5)
        spans = [(M._parse_utc(r["ts_end"]) - M._parse_utc(r["ts_utc"])).total_seconds() for r in self.rows(ag)]
        self.assertEqual(len(spans), 5)
        self.assertTrue(all(s == 60 for s in spans[:-1]), spans)         # 3시간이 활동으로 새지 않는다
        self.assertLessEqual(spans[-1], 60)

    def test_wall_clock_step_back_does_not_stall(self):
        """W1b 회귀: 벽시계가 뒤로 2시간 보정돼도(NTP 역보정·수동 변경) 틱·heartbeat·표본·teams.uia 일정이 멈추지 않는다 —
        일정은 단조 시계로 잰다. 주입 단조 시계(실행의 time.monotonic 대역)와, 벽시계만 줄 때의 WallMono 둘 다."""
        for explicit in (True, False):
            sb = H.Sandbox()
            self.addCleanup(sb.cleanup)
            sb.agent_files()
            calls = []
            ag, clk = H.make_agent(sb, run_conn=lambda paths, pc_id, src, **kw: calls.append(src))
            mono = [0.0]

            def wait(s, clk=clk, mono=mono):
                mono[0] += max(float(s), 0.001)
                clk.wait(s)
            ag.wait = wait
            if explicit:
                ag.mono = lambda mono=mono: mono[0]
            seen = []
            orig = ag._tick

            def tick(now, ag=ag, orig=orig, clk=clk, seen=seen, mono=mono):
                seen.append(mono[0])
                orig(now)
                if ag.ticks == 2:
                    clk.t -= timedelta(hours=2)
            ag._tick = tick
            ag.run(max_ticks=6)
            gaps = [round(b - a) for a, b in zip(seen, seen[1:], strict=False)]
            self.assertEqual(gaps, [60] * 5, explicit)                        # 예전: [60, 60, 7260, 60, 60]
            self.assertLess(max(gaps), 600)                                   # agent.heartbeatStaleSec 안
            recs, _c, _g = read_store_since(sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
            self.assertEqual(len(recs), 6, explicit)
            for t, _box in list(ag.jobs.values()):
                t.join(5)
            # teams.uia·열린 문서 폴링(기본 300초 주기) — 0초·300초 두 번(예전: 역행 뒤 2시간 동안 0번)
            self.assertEqual((calls.count("teams.uia"), calls.count("pc.files")), (2, 2), (explicit, calls))

    def test_first_flush_immediate_and_heartbeat_fields(self):
        ag, _clk = H.make_agent(self.sb)
        ag.run(max_ticks=1)
        self.assertEqual(len(self.rows(ag)), 1)
        hb = self.hb()
        for k in ("schema", "install_id", "pc_id", "pid", "agent_ver", "impl", "started_at", "last_tick", "interval_s",
                  "samples_today", "harvest", "last_error"):
            self.assertIn(k, hb)
        self.assertEqual((hb["schema"], hb["install_id"], hb["impl"], hb["interval_s"], hb["buffered"], hb["state"]),
                         ("lm27.hb/1", H.IID, "py", 60, 0, "stopped"))
        self.assertEqual(set(hb["harvest"]), {"last_at", "last_rc", "next_at"})
        self.assertLessEqual(len(hb["last_error"]), 200)

    def test_flush_policy_rows_and_session_lock(self):
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        sb.agent_files(cfg=sb.cfg(**{"agent.flushMaxRows": 3, "agent.flushIntervalSec": 3600}))
        api = H.FakeApi()
        ag, _clk = H.make_agent(sb, api=api)
        flushes = []
        orig = ag._flush

        def fl(now, final=False):
            flushes.append((len(ag.buf_s), final))
            return orig(now, final=final)
        ag._flush = fl
        orig_tick = ag._tick

        def tick(now):
            if ag.ticks == 5:
                api.wts_v = (0, 0, 0)                                    # 6번째 틱에 잠김
            orig_tick(now)
        ag._tick = tick
        ag.run(max_ticks=8)
        self.assertEqual(flushes[0], (1, False))                         # 첫 표본
        self.assertIn((3, False), flushes)                               # 행 수 상한
        self.assertEqual(flushes[-1][1], True)                           # 종료 플러시
        recs, _c, _g = read_store_since(sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 8)
        self.assertIn("locked", {r["session_state"] for r in recs})

    def test_stop_flag(self):
        ag, clk = H.make_agent(self.sb)
        orig = ag._tick

        def tick(now):
            orig(now)
            if ag.ticks == 2:
                self.sb.paths.stop_flag().parent.mkdir(parents=True, exist_ok=True)
                self.sb.paths.stop_flag().write_bytes(b"")
        ag._tick = tick
        self.assertEqual(ag.run(max_ticks=50), 0)
        self.assertEqual(len(self.rows(ag)), 3)                           # 남은 표본도 종료 때 확정·저장
        self.assertEqual((self.hb()["state"], self.hb()["buffered"]), ("stopped", 0))

    def test_existing_stop_flag_and_mutex(self):
        self.sb.paths.stop_flag().parent.mkdir(parents=True, exist_ok=True)
        self.sb.paths.stop_flag().write_bytes(b"")
        ag, _clk = H.make_agent(self.sb)
        self.assertEqual(ag.run(max_ticks=3), 0)
        self.assertFalse(self.sb.paths.heartbeat().exists())
        self.sb.paths.stop_flag().unlink()
        ag, _clk = H.make_agent(self.sb, mutex=lambda n: (None, True))   # 이미 실행 중
        self.assertEqual(ag.run(max_ticks=3), 0)
        self.assertFalse(self.sb.paths.heartbeat().exists())

    def test_other_install_folder_untouched(self):
        self.sb.write_json(self.sb.paths.agent_json(), {"install_id": H.IID2, "pc_id": "pc_0000000000000001"})
        ag, _clk = H.make_agent(self.sb)
        self.assertEqual(ag.run(max_ticks=2), 0)
        self.assertFalse(self.sb.paths.heartbeat().exists())


class HarvestScheduleTest(_Base):
    def test_logon_then_interval_and_flag(self):
        sb = self.sb
        ag, clk = H.make_agent(sb)
        orig = ag._tick

        def tick(now):
            if ag.ticks == 3:
                sb.paths.harvest_now_flag().parent.mkdir(parents=True, exist_ok=True)
                sb.paths.harvest_now_flag().write_bytes(b"{}")
            orig(now)
        ag._tick = tick
        ag.run(max_ticks=6)
        self.assertEqual(len(ag.spawned), 2)
        self.assertEqual(ag.spawned[0][1], M.HARVEST_STREAMS)
        self.assertEqual((ag.spawned[0][2], ag.spawned[1][2]), (False, True))
        self.assertEqual(ag.spawned[0][0].install_id, H.IID)
        self.assertFalse(sb.paths.harvest_now_flag().exists())            # 요청 깃발은 자식을 띄운 뒤 지운다

    def test_stop_kills_running_harvest_child(self):
        """W1b 회귀: 정상 정지(stop.flag)에도 살아 있는 수확 자식을 끈다(수확은 커서로 다음 기동이 이어 한다) — 정지·제거 뒤
        고아 수집 0. 자식 pid 는 run\\harvest.pid 에 있다가(감독 루프가 먼저 죽었을 때 stop_agent·uninstall 용) 정리된다."""
        import sys

        from lm27.util import proc
        kids = []

        def spawn(ident, streams, requested):
            ch = proc.spawn([sys.executable, "-X", "utf8", "-I", "-B", "-c", "import time; time.sleep(60)"],
                            stdout=proc.DEVNULL)
            kids.append(ch)
            return ch

        def cleanup():
            for k in kids:
                k.kill_tree()
                k.close()
        self.addCleanup(cleanup)
        sb = self.sb
        ag, _clk = H.make_agent(sb, spawn=spawn)
        orig = ag._tick
        seen = {}

        def tick(now):
            orig(now)
            if ag.ticks == 0:
                rec = sb.read_json(sb.paths.harvest_pid())
                seen["pid"] = (rec.get("pid"), rec.get("install_id"))
                sb.paths.stop_flag().write_bytes(b"")
        ag._tick = tick
        self.assertEqual(ag.run(max_ticks=10), 0)
        self.assertEqual(len(kids), 1)
        self.assertEqual(seen["pid"], (kids[0].pid, H.IID))
        self.assertFalse(kids[0].alive())
        self.assertFalse(sb.paths.harvest_pid().exists())

    def test_recent_harvest_not_repeated_at_start(self):
        sb = self.sb
        sb.write_json(sb.paths.harvest_done(), {"install_id": H.IID, "finished_at": "2026-10-05T00:30:00Z",
                                                "started_at": "2026-10-05T00:29:00Z", "rc": 0})
        ag, clk = H.make_agent(sb)
        ag.run(max_ticks=3)
        self.assertEqual(ag.spawned, [])
        self.assertEqual(self.hb()["harvest"]["last_at"], "2026-10-05T00:30:00Z")
        self.assertEqual(self.hb()["harvest"]["next_at"], "2026-10-05T06:30:00Z")

    def test_jobs_skip_when_locked(self):
        calls = []

        def conn(paths, pc_id, src, **kw):
            calls.append((src, kw.get("poll"), kw.get("settings", {}).get("teams.uia.budgetSec")))
        ag, _clk = H.make_agent(self.sb, api=H.FakeApi(wts=(0, 0, 0)), run_conn=conn)
        ag.run(max_ticks=2)
        self.assertEqual(calls, [])
        ag, _clk = H.make_agent(self.sb, run_conn=conn)
        ag.run(max_ticks=2)
        self.assertEqual(sorted(c[:2] for c in calls), [("pc.files", True), ("teams.uia", False)])
        self.assertTrue(all(c[2] == 60 for c in calls))                   # agent_config 값을 넘긴다


class StateTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_rules_mismatch_stops_collection(self):
        """P-T34 — 사본 규칙 해시가 잠금과 다르면 수집을 멈추고 heartbeat 에 R-RULESMISMATCH."""
        self.sb.agent_files()
        ag, _clk = H.make_agent(self.sb, rules_ok=False)
        ag.run(max_ticks=4)
        recs, _c, _g = read_store_since(self.sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
        self.assertEqual(recs, [])
        hb = self.sb.read_json(self.sb.paths.heartbeat())
        self.assertEqual(hb["last_error"], "R-RULESMISMATCH")
        self.assertEqual(ag.spawned, [])

    def test_no_key_mode(self):
        """P-T29 — 하위 키 없음: 샘플러 행은 저장(doc_key 없음 · flags.no_key), 사람 태그 0, heartbeat R-NOKEY."""
        self.sb.agent_files(keys=False)
        api = H.FakeApi(title="김철수 님 견적_v2.xlsx - Excel")
        ag, _clk = H.make_agent(self.sb, api=api)
        ag.run(max_ticks=3)
        recs, _c, _g = read_store_since(self.sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 3)
        for r in recs:
            self.assertIsNone(r.get("doc_key"))
            self.assertTrue((r.get("flags") or {}).get("no_key"))
            self.assertEqual(r["kid"], K.NO_KID)
            self.assertNotIn("[사람#", json.dumps(r, ensure_ascii=False))
        self.assertEqual(self.sb.read_json(self.sb.paths.heartbeat())["last_error"], "R-NOKEY")

    def test_pc_id_change_vdi(self):
        """TAB-B26 — 같은 agent\\ 에서 MachineGuid 만 바뀌면 agent.json.pc_id 갱신, 이후 기록은 새 pc_id store, install_id 유지."""
        self.sb.agent_files()
        ag, _clk = H.make_agent(self.sb, probe=H.FakeProbe(H.GUID1))
        ag.run(max_ticks=1)
        pc1 = ag.pc_id
        self.sb.write_json(self.sb.paths.agent_json(), {"schema": "lm27.agent/1", "install_id": H.IID, "pc_id": pc1})
        ag2, _clk = H.make_agent(self.sb, probe=H.FakeProbe(H.GUID2))
        ag2.run(max_ticks=2)
        self.assertNotEqual(ag2.pc_id, pc1)
        aj = self.sb.read_json(self.sb.paths.agent_json())
        self.assertEqual((aj["pc_id"], aj["install_id"]), (ag2.pc_id, H.IID))
        for pc, n in ((pc1, 1), (ag2.pc_id, 2)):
            recs, _c, _g = read_store_since(self.sb.paths, pc, "pc_session", "pc.sampler", None)
            self.assertEqual(len(recs), n)
        self.assertEqual(self.sb.read_json(self.sb.paths.heartbeat())["pc_id"], ag2.pc_id)

    def test_unflushed_lost_after_crash(self):
        self.sb.agent_files()
        self.sb.write_json(self.sb.paths.heartbeat(), {"install_id": H.IID, "pid": 1, "buffered": 4})
        ag, _clk = H.make_agent(self.sb)
        ag.run(max_ticks=1)
        self.assertEqual(self.sb.read_json(self.sb.paths.heartbeat())["last_error"], "unflushed_lost")


class ComputeAndMetaTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.sb.agent_files()

    def test_compute_rows(self):
        cpu = {"t": 0.0}

        def burn():
            cpu["t"] += 120.0                                             # 틱(60초)마다 2코어
            return cpu["t"]
        api = H.FakeApi(procs=[(77, "fluent.exe")], cpu={77: burn})
        ag, _clk = H.make_agent(self.sb, api=api)
        ag.run(max_ticks=6)
        recs, _c, _g = read_store_since(self.sb.paths, ag.pc_id, "pc_compute", "pc.compute", None)
        self.assertTrue(recs)
        final = [r for r in recs if not (r.get("flags") or {}).get("end_uncertain")]
        self.assertEqual(len({r["id"] for r in recs}), 1)                 # 진행 중 판과 확정 판은 같은 id(X-032)
        self.assertEqual(len(final), 1)
        r = final[0]
        self.assertEqual((r["flags"]["solver"], r["cpu_core"]), (True, 2.0))
        self.assertLess(r["ts_utc"], r["ts_end"])

    def test_unknown_exe_meta(self):
        class Reader:
            def version_info(self, path):
                return {"company": "고객사A Co., Ltd.", "product": "과제A 해석 도구", "desc": "내부 해석기", "ver": "1.2.3"}

            def signer(self, path):
                return ""
        api = H.FakeApi(image=r"C:\Tools\inhouse_solver.exe", title="과제A - 해석")
        ag, _clk = H.make_agent(self.sb, api=api, exe_reader=Reader())
        ag.run(max_ticks=2)
        meta = self.sb.read_json(self.sb.paths.exe_meta(ag.pc_id))
        self.assertEqual(meta["schema"], "lm27.exemeta/1")
        e = meta["inhouse_solver.exe"]
        self.assertEqual(set(e), {"company", "product", "desc", "ver", "signer", "first_seen", "guess_cat", "guess_kind",
                                  "source"})
        self.assertNotIn("과제A", e["product"])                          # 사전 가명화(정제 통과값)
        self.assertNotIn("고객사A", e["company"])
        self.assertEqual(e["ver"], "1.2.3")
        self.assertNotIn("Tools", json.dumps(meta, ensure_ascii=False))    # 경로 원문 없음
        api2 = H.FakeApi(image=H.EXCEL)
        ag2, _clk = H.make_agent(self.sb, api=api2, exe_reader=Reader())
        ag2.run(max_ticks=1)
        self.assertNotIn("excel.exe", self.sb.read_json(self.sb.paths.exe_meta(ag2.pc_id)))   # 카탈로그 프로그램은 조회 안 함


class CanaryTest(unittest.TestCase):
    def test_t07_no_canaries_on_disk(self):
        """T-07 — 창 제목·exe 메타에 심은 카나리아가 store·감사·exe_meta·heartbeat·로그 어디에도 없다."""
        sb = H.Sandbox()
        self.addCleanup(sb.cleanup)
        sb.agent_files()
        cs = [c for c in canaries(groups=("pii",), weak=False) if c.slot in ("text", "title", "path", "name")][:12]
        titles = [f"{c.sentence}.docx - Word" for c in cs] + [f"{c.sentence} - Microsoft Edge" for c in cs]
        state = {"i": 0}

        class Api(H.FakeApi):
            def window_text(self, h):
                t = titles[state["i"] % len(titles)]
                state["i"] += 1
                return t

        class Reader:
            def version_info(self, path):
                return {"product": cs[0].sentence, "desc": cs[1].sentence, "company": cs[2].sentence}

            def signer(self, path):
                return cs[3].sentence
        api = Api(image=r"C:\Tools\unknown_tool.exe")
        ag, _clk = H.make_agent(sb, api=api, exe_reader=Reader())
        ag.run(max_ticks=len(titles))
        api.image = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
        ag2, _clk = H.make_agent(sb, api=api, exe_reader=Reader())
        ag2.run(max_ticks=len(titles))
        recs, _c, _g = read_store_since(sb.paths, ag.pc_id, "pc_session", "pc.sampler", None)
        self.assertEqual(len(recs), 2 * len(titles))
        self.assertEqual(find_canaries(sb.all_bytes(sb.lad), cs), [])


class HelperCmdTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)

    def test_classify_lines(self):
        out = M.classify_lines(["EXCEL.EXE", "fluent.exe", "svchost.exe", "사내 도구.exe", ""], {})
        by = {o["exe"]: o for o in out}
        self.assertEqual((by["excel.exe"]["app_id"], by["excel.exe"]["app_class"], by["excel.exe"]["solver"]),
                         ("excel", "office", False))
        self.assertTrue(by["fluent.exe"]["solver"])
        self.assertEqual((by["svchost.exe"]["fg_exe"], by["svchost.exe"]["app_class"]), (None, "system"))
        self.assertTrue(by["사내 도구.exe"]["app_id"].startswith("unknown:"))

    def test_start_check_updates_pc_id(self):
        self.sb.write_json(self.sb.paths.agent_json(), {"install_id": H.IID, "pc_id": "pc_0000000000000001"})
        r = M.start_check(self.sb.paths, H.IID, probe=H.FakeProbe(H.GUID2), rules_ok=lambda: True)
        self.assertTrue(r["rules_ok"] and r["pc_id_changed"])
        self.assertEqual(self.sb.read_json(self.sb.paths.agent_json())["pc_id"], r["pc_id"])

    def test_self_test_output_has_no_text(self):
        out = io.StringIO()
        rc = M.self_test(2, api=H.FakeApi(title="김철수 견적.xlsx - Excel"), gap=0, sleep=lambda s: None, out=out)
        line = json.loads(out.getvalue())
        self.assertEqual(set(line), {"_selftest"})
        st = line["_selftest"]
        self.assertEqual((st["samples"], st["fg"], st["idle"], st["session"]), (2, 2, 2, 2))
        self.assertGreaterEqual(st["corpus"], 5)
        self.assertNotIn("김철수", out.getvalue())
        self.assertEqual(rc, 0 if st["rules"] else 1)

    def test_cli_rejects_bad_install_id(self):
        self.assertEqual(M._cli(["--install-id", "XYZ"]), 5)

    def test_prune_logs(self):
        d = self.sb.paths.agent_logs()
        d.mkdir(parents=True)
        for name in ("agent_20260801.log", "agent_20261004.log", "other.log"):
            (d / name).write_text("x", encoding="utf-8")
        self.assertEqual(M.prune_logs(self.sb.paths, H.T0), 1)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["agent_20261004.log", "other.log"])

    def test_real_mutex_single_instance(self):
        name = "Local\\LM27T-" + H.IID + "-agent"
        h1, e1 = M.win_mutex(name)
        h2, e2 = M.win_mutex(name)
        try:
            self.assertTrue(h1 and not e1)
            self.assertTrue(e2)
        finally:
            M._close_handle(h2)
            M._close_handle(h1)


if __name__ == "__main__":
    unittest.main()
