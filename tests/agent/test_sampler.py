# -*- coding: utf-8 -*-
"""WP-13 샘플러 시험 — ``lm27.agent.sampler``(CP §3 · §8 · X-073 · X-079 · X-080 · C15).

유휴 2^32 모듈로(이전 판 32비트 음수 결함 회귀) · WTS 세션 대응 · 원시 레코드 모양(P §10.2 원시 이름 — 제목 원문은 정제기만) ·
layer(X-079) · 잡음 프로세스 · 연산 구간(솔버 CPU 차분, 연속 틱, 진행 중 판) · 합성 바로가기(.lnk) 대상 · 문서 경로 색인(C15).
실 Win32·실 Recent 폴더는 읽지 않는다(가짜 API·합성 .lnk 만).
"""
import unittest
from datetime import UTC, datetime, timedelta

from lm27 import catalog
from lm27.agent import sampler as S
from lm27.privacy.records import SCHEMAS
from tests.fixtures.wp13 import helpers as H

T = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)


class IdleTest(unittest.TestCase):
    def test_modulo_and_wrap(self):
        self.assertEqual(S.idle_sec(10_000, 7_000), 3)
        # GetTickCount64 가 2^32 를 넘은 뒤(가동 49.7일+) — dwTime 은 하위 32비트
        self.assertEqual(S.idle_sec((1 << 32) + 5_000, 2_000), 3)
        # dwTime 이 랩어라운드 직전 값(가동 49.7일 경계) — 이전 판 Max(0, …) 는 0 이 되었다(A1)
        self.assertEqual(S.idle_sec((1 << 32) + 1_000, (1 << 32) - 2_000), 3)
        self.assertEqual(S.idle_sec(25 * 86400 * 1000, 25 * 86400 * 1000 - 600_000), 600)

    def test_rounding_and_cap(self):
        self.assertEqual(S.idle_sec(2_500, 0), 2)          # 반올림(짝수 쪽) — ps 구현과 같은 규칙
        self.assertEqual(S.idle_sec(3_500, 0), 4)
        self.assertLessEqual(S.idle_sec((1 << 40), 1), S.IDLE_MAX)


class SessionTest(unittest.TestCase):
    def test_mapping(self):
        cases = [((0, 1, 0), ("active", False)), ((0, 0, 0), ("locked", False)), ((4, 1, 0), ("disconnected", False)),
                 ((0, 1, 2), ("remote", True)), ((0, 0, 2), ("locked", True)), ((4, 0, 2), ("disconnected", True)),
                 ((None, None, None), ("active", False))]
        for args, want in cases:
            self.assertEqual(S.map_session(*args), want, args)

    def test_session_state_with_fake(self):
        self.assertEqual(S.session_state(H.FakeApi(wts=(0, 0, 0))), "locked")


class TickRecordTest(unittest.TestCase):
    def tick(self, **kw):
        d = {"ts": T, "off_min": 540, "fg_exe": "excel.exe", "fg_title": "견적_v2.xlsx - Excel", "session_state": "active",
             "remote": False, "idle_sec": 12}
        d.update(kw)
        return S.RawTick(**d)

    def test_office_window(self):
        r = S.tick_record(self.tick(), 60)
        self.assertEqual((r["fg_exe"], r["app_id"], r["app_class"], r["layer"]), ("excel.exe", "excel", "office", "L3"))
        self.assertEqual((r["ts_utc"], r["observed_at"], r["ts_local_offset"], r["ts_precision"]),
                         ("2026-10-05T01:00:00Z", "2026-10-05T01:00:00Z", "+09:00", "exact"))
        self.assertEqual((r["interval_sec"], r["idle_sec"], r["session_state"], r["confidence"]), (60, 12, "active", 1.0))
        self.assertNotIn("flags", r)
        self.assertNotIn("stuck", r.get("flags", {}))            # 고착은 판정하지 않는다(CP §3.7)

    def test_no_foreground_and_noise(self):
        r = S.tick_record(self.tick(fg_exe="", fg_title=""), 60)
        self.assertEqual((r["fg_exe"], r["app_id"], r["app_class"], r["layer"]), (None, None, "idle", "L2"))
        r = S.tick_record(self.tick(fg_exe="lockapp.exe", fg_title=""), 60)
        self.assertEqual((r["fg_exe"], r["app_id"], r["app_class"], r["layer"]), (None, None, "system", "L2"))

    def test_unknown_exe_and_odd_names(self):
        r = S.tick_record(self.tick(fg_exe=catalog.exe_name("사내 해석기.EXE")), 60)
        self.assertRegex(r["fg_exe"], r"^[a-z0-9_.\-]{1,64}\.exe$")
        self.assertTrue(r["app_id"].startswith("unknown:"))
        self.assertEqual(r["app_class"], "other")

    def test_flags_remote_utc_and_doc(self):
        r = S.tick_record(self.tick(remote=True, off_min=0), 0, doc_path=r"C:\work\과제A\견적_v2.xlsx")
        self.assertEqual(r["flags"], {"remote": True, "utc_suspect": True})
        self.assertEqual(r["interval_sec"], 1)                   # 0 이하 간격은 1초
        self.assertEqual((r["fg_doc_path"], r["fg_doc_name"]), (r"C:\work\과제A\견적_v2.xlsx", "견적_v2.xlsx"))

    def test_raw_names_are_known_to_sanitizer(self):
        """원시 이름이 정제기 pc_session 이 아는 이름과 원시 공통 이름뿐(금지 원시 필드 user·message·computer 없음)."""
        r = S.tick_record(self.tick(remote=True), 60, doc_path=r"C:\a\b.xlsx")
        allowed = {"ts_utc", "ts_local_offset", "ts_precision", "observed_at", "confidence", "fg_exe", "app_id", "app_class",
                   "fg_title", "fg_doc_name", "fg_doc_path", "session_state", "idle_sec", "layer", "interval_sec", "flags"}
        self.assertEqual(set(r) - allowed, set())
        self.assertFalse(set(r) & {"user", "message", "computer", "username", "computername", "machine_guid"})
        self.assertTrue(set(r["flags"]) <= SCHEMAS["pc_session"].flag_keys)


class TakeSampleTest(unittest.TestCase):
    def test_fake_api(self):
        api = H.FakeApi(idle_ms=7000, wts=(0, 0, 2))
        t = S.take_sample(None, api=api, now=T + timedelta(microseconds=900))
        self.assertEqual(t.ts, T)                                # 초 단위로 자른다
        self.assertEqual((t.fg_exe, t.fg_title, t.session_state, t.remote, t.idle_sec), ("excel.exe", "견적_v2.xlsx - Excel",
                                                                                         "locked", True, 7))
        self.assertTrue(t.ok["fg"] and t.ok["idle"] and t.ok["session"])
        self.assertEqual(t.cpu, {})

    def test_solver_cpu_only_for_solvers(self):
        api = H.FakeApi(procs=[(10, "fluent.exe"), (11, "excel.exe"), (12, "ansysli_server.exe"), (13, "mapdl.exe")],
                        cpu={10: 30.0, 11: 99.0, 12: 50.0, 13: 4.0})
        t = S.take_sample(None, api=api, now=T, solvers=catalog.solver_set(None))
        self.assertEqual(t.cpu, {10: ("fluent", 30.0), 13: ("mapdl", 4.0)})

    def test_api_failure_is_recorded_not_raised(self):
        class Bad(H.FakeApi):
            def wts(self):
                raise OSError("x")
        t = S.take_sample(None, api=Bad(), now=T)
        self.assertEqual(t.session_state, "active")
        self.assertIn("OSError", t.errors)
        self.assertFalse(t.ok["session"])


class ComputeTest(unittest.TestCase):
    def feed(self, tr, seconds, cores_by_tick, pid=10, exe="fluent"):
        out, total = [], 0.0
        t = T
        out += tr.observe(t, {pid: (exe, total)})
        for c in cores_by_tick:
            t += timedelta(seconds=seconds)
            total += c * seconds
            out += tr.observe(t, {pid: (exe, total)})
        return out, t

    def test_interval_needs_consecutive_ticks(self):
        tr = S.ComputeTracker(0.5, 3)
        closed, t_end = self.feed(tr, 60, [2.0, 2.0, 2.0, 2.0, 0.0])
        self.assertEqual(len(closed), 1)
        run = closed[0]
        self.assertEqual((run.app_id, run.start, run.ticks), (catalog.app_id_for("fluent"), T, 4))
        self.assertEqual(run.last, T + timedelta(seconds=240))
        rec = S.compute_record(run, 540, t_end, final=True)
        self.assertEqual((rec["ts_utc"], rec["ts_end"], rec["app_id"], rec["fg_exe"], rec["cpu_core"], rec["flags"]),
                         ("2026-10-05T01:00:00Z", "2026-10-05T01:04:00Z", catalog.app_id_for("fluent"), "fluent.exe", 2.0,
                          {"solver": True}))

    def test_short_burst_is_not_an_interval(self):
        tr = S.ComputeTracker(0.5, 3)
        closed, _t = self.feed(tr, 60, [2.0, 2.0, 0.1, 2.0])
        self.assertEqual(closed, [])
        self.assertEqual(tr.open_intervals(), [])

    def test_below_threshold_and_open_progress(self):
        tr = S.ComputeTracker(1.0, 2)
        closed, _t = self.feed(tr, 60, [0.9, 0.9])
        self.assertEqual((closed, tr.open_intervals()), ([], []))
        tr = S.ComputeTracker(1.0, 2)
        _c, t = self.feed(tr, 60, [1.5, 1.5, 1.5])
        op = tr.open_intervals()
        self.assertEqual(len(op), 1)
        rec = S.compute_record(op[0], 540, t, final=False)
        self.assertEqual(rec["flags"], {"solver": True, "end_uncertain": True})
        self.assertEqual(rec["observed_at"], S.fmt_utc(t))
        self.assertEqual(len(tr.close_all()), 1)
        self.assertEqual(tr.runs, {})

    def test_two_processes_same_app_add_up(self):
        tr = S.ComputeTracker(1.0, 1)
        tr.observe(T, {1: ("fluent", 0.0), 2: ("fl_mpi", 0.0)})
        tr.observe(T + timedelta(seconds=60), {1: ("fluent", 36.0), 2: ("fluent", 36.0)})   # pid 2 이름이 바뀜 → 그 틱은 빠진다
        self.assertEqual(tr.open_intervals(), [])
        tr2 = S.ComputeTracker(1.0, 1)
        tr2.observe(T, {1: ("fluent", 0.0), 2: ("fluent", 0.0)})
        tr2.observe(T + timedelta(seconds=60), {1: ("fluent", 36.0), 2: ("fluent", 36.0)})   # 0.6 + 0.6 코어 = 1.2
        self.assertEqual(len(tr2.open_intervals()), 1)

    def test_restarted_process_resets_delta(self):
        tr = S.ComputeTracker(0.5, 1)
        tr.observe(T, {7: ("fluent", 500.0)})
        tr.observe(T + timedelta(seconds=60), {7: ("fluent", 1.0)})                  # 누계가 줄었다 = 다른 프로세스
        self.assertEqual(tr.open_intervals(), [])


class LnkTest(unittest.TestCase):
    def test_local_ansi_and_unicode(self):
        p = r"C:\work\과제A\견적_v2.xlsx"
        self.assertEqual(S.lnk_target(H.lnk_bytes(p)), p)
        self.assertEqual(S.lnk_target(H.lnk_bytes(p, unicode=True)), p)

    def test_network_and_garbage(self):
        self.assertEqual(S.lnk_target(H.lnk_network(r"\\fileserver\share", r"docs\a.xlsx")), r"\\fileserver\share\docs\a.xlsx")
        for junk in (b"", b"\x00" * 10, b"L\x00\x00\x00" + b"\x00" * 100, H.lnk_bytes("C:\\a.txt")[:80]):
            self.assertIsInstance(S.lnk_target(junk), str)


class DocIndexTest(unittest.TestCase):
    def setUp(self):
        self.sb = H.Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.rec = self.sb.dir / "recent"
        self.rec.mkdir()

    def test_title_absolute_path_wins(self):
        di = S.DocIndex(str(self.rec))
        self.assertEqual(di.path_for(r"C:\cad\과제A\bracket.prt - Creo Parametric", "cad"), r"C:\cad\과제A\bracket.prt")
        self.assertIsNone(di.path_for("받은 편지함 - Outlook", "mail_work"))       # 문서 창이 아니면 찾지 않는다
        self.assertIsNone(di.path_for("", "office"))

    def test_recent_lookup_by_name_and_stem(self):
        (self.rec / "견적_v2.xlsx.lnk").write_bytes(H.lnk_bytes(r"C:\work\과제A\견적_v2.xlsx", unicode=True))
        (self.rec / "회의록.docx.lnk").write_bytes(H.lnk_bytes(r"C:\work\회의록.docx"))
        (self.rec / "web.lnk").write_bytes(H.lnk_bytes("https://example.com/x"))
        clock = [0.0]
        di = S.DocIndex(str(self.rec), clock=lambda: clock[0])
        self.assertEqual(di.path_for("견적_v2.xlsx - Excel", "office"), r"C:\work\과제A\견적_v2.xlsx")
        self.assertEqual(di.path_for("*회의록 - Word", "office"), r"C:\work\회의록.docx")    # 확장자 없는 제목 → 줄기
        self.assertIsNone(di.path_for("없는문서.pptx - PowerPoint", "office"))
        (self.rec / "새문서.pptx.lnk").write_bytes(H.lnk_bytes(r"C:\work\새문서.pptx"))
        self.assertIsNone(di.path_for("새문서.pptx - PowerPoint", "office"))           # 아직 다시 읽지 않음
        clock[0] = S.DOC_REFRESH_S + 1
        self.assertEqual(di.path_for("새문서.pptx - PowerPoint", "office"), r"C:\work\새문서.pptx")


if __name__ == "__main__":
    unittest.main()
