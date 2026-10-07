# -*- coding: utf-8 -*-
r"""WP8 — 근무시간 꼬리표·퇴근 후 인정·사적 차감·솔버 확인·과제 몫(timeshare)·미관측·공휴일 / 영역·키워드·단위업무.

가짜 data 폴더(tempfile)에 pc_spans·activity·coverage_ledger 를 쓰고 core\extract.day_work_hours 를 같은 프로세스에서 부른다.
실 Outlook·Edge 는 쓰지 않는다. 날짜: 2026-09-01(화)~09-04(금)·09-05(토)."""
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

import _boot  # noqa: F401

import details  # noqa: E402
import extract  # noqa: E402
import projmap  # noqa: E402
import timeshare  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0)
TUE = date(2026, 9, 1)
FRI = date(2026, 9, 4)
SAT = date(2026, 9, 5)
ACT_HDR = ["time", "process", "title", "idle_sec", "solvers_running", "user", "host", "gap_s", "sess", "solver_cpu_s"]


def _dt(d, hh, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm)


class _Data:
    """가짜 data 폴더 — with 블록이 끝나면 지워진다."""

    def __enter__(self):
        self._t = tempfile.TemporaryDirectory(prefix="lm28_p8_")
        self.dir = self._t.name
        return self

    def __exit__(self, *a):
        self._t.cleanup()

    def pc_spans(self, spans):
        os.makedirs(os.path.join(self.dir, "pc"), exist_ok=True)
        with open(os.path.join(self.dir, "pc", "pc_spans.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["start", "end", "src"])
            for a, b in spans:
                w.writerow([a.strftime("%Y-%m-%d %H:%M:%S"), b.strftime("%Y-%m-%d %H:%M:%S"), "event"])

    def activity(self, ticks):
        """ticks = [(datetime, process, title, idle, sess, cpu)] — 날짜별 파일."""
        os.makedirs(os.path.join(self.dir, "activity"), exist_ok=True)
        by = {}
        for t in ticks:
            by.setdefault(t[0].date(), []).append(t)
        for d, lst in by.items():
            with open(os.path.join(self.dir, "activity", f"activity_{d:%Y%m%d}.csv"), "w", encoding="utf-8",
                      newline="") as f:
                w = csv.writer(f)
                w.writerow(ACT_HDR)
                for t, proc, title, idle, sess, cpu in lst:
                    w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), proc, title, idle, "", "", "", "", sess, cpu])

    def ledger(self, days, na=None):
        with open(os.path.join(self.dir, "coverage_ledger.json"), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "ver": "", "host": "", "days": days, "suspect": {}, "na": na or {}, "last": {}}, f)


def _ticks(d, h0, m0, n, proc="excel.exe", title="보고서.xlsx - Excel", idle=0, sess="", cpu=""):
    t0 = _dt(d, h0, m0)
    return [(t0 + timedelta(minutes=i), proc, title, idle, sess, cpu) for i in range(n)]


def _dwh(data, sig, d0, d1, mm=None, cfg=None):
    c = dict(cfg or {})
    if mm is not None:
        c["mm"] = mm
    return extract.day_work_hours(data, sig, d0, d1, c, now=NOW, file_times={})


# ════════════════════════════════ 8a 시간 ════════════════════════════════
class Tags(unittest.TestCase):
    """꼬리표 — 휴일 > 야간 > 정규 > 연장, 자정을 넘으면 그 분의 날짜"""

    def test_fri_23_to_sat_01(self):
        with _Data() as D:
            D.activity(_ticks(FRI, 23, 0, 60) + _ticks(SAT, 0, 0, 60))
            h, info = _dwh(D.dir, [], FRI, SAT)
        self.assertAlmostEqual(h[FRI], 1.0, places=2)
        self.assertAlmostEqual(h[SAT], 1.0, places=2)
        fri, sat = info["day_basis"][FRI.isoformat()]["tags"], info["day_basis"][SAT.isoformat()]["tags"]
        self.assertEqual(fri, {"night": 1.0})
        self.assertEqual(sat, {"holiday": 1.0, "holiday_night": 1.0})
        self.assertAlmostEqual(info["night_h"], 1.0, places=2)
        self.assertAlmostEqual(info["holiday_h"], 1.0, places=2)
        self.assertAlmostEqual(info["holiday_night_h"], 1.0, places=2)
        self.assertIn("overtime_h", info)              # LM24 키 유지
        self.assertIn("night_days", info)

    def test_tag_minutes_pure(self):
        reg = extract._subtract_spans([(480.0, 1140.0)], [(720.0, 780.0)])
        night = extract._night_win_spans(1320.0, 360.0)
        t = extract.tag_minutes([(600, 660), (750, 760), (1150, 1170), (1330, 1340)], False, reg, night)
        self.assertEqual((t["regular"], t["extended"], t["night"], t["holiday"]), (60.0, 30.0, 10.0, 0.0))


class Evening(unittest.TestCase):
    """★ 사용자 지시 2026-10-07 — 퇴근 경계 ~ 마지막 저녁 산출물 시각 전체(+30 꼬리 없음).
    trimIdleEdgesMin=0 — PC 가동 창 다듬기(LM24 A33)를 빼고 저녁 규칙만 본다."""

    MM = {"trimIdleEdgesMin": 0}

    def _run(self, pc_end, sig, mm_extra=None):
        mm = dict(self.MM, **(mm_extra or {}))
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 8, 30), pc_end)])
            return _dwh(D.dir, sig, TUE, TUE, mm=mm)

    def test_full_evening_until_product(self):
        h, info = self._run(_dt(TUE, 23, 30), [(_dt(TUE, 22, 50), "파일", "설계안.dwg", 3.0, "나")])
        db = info["day_basis"][TUE.isoformat()]
        self.assertEqual(db["evening"], [["19:00", "22:50"]])
        self.assertAlmostEqual(info["evening_window_h"], 3.83, places=2)
        self.assertEqual(info["remote_send"], 0)

    def test_evening_credit_off(self):
        h, info = self._run(_dt(TUE, 23, 30), [(_dt(TUE, 22, 50), "파일", "설계안.dwg", 3.0, "나")],
                            {"eveningCredit": False})
        self.assertNotIn("evening", info["day_basis"][TUE.isoformat()])
        self.assertEqual((info["evening_credit_h"], info["evening_window_h"]), (0.0, 0.0))

    def test_pc_off_then_mobile_send(self):
        h, info = self._run(_dt(TUE, 21, 0), [(_dt(TUE, 22, 50), "메일(발신)", "자료 회신", 1.5, "나")])
        db = info["day_basis"][TUE.isoformat()]
        self.assertEqual(db["evening"], [["19:00", "21:00"]])
        self.assertEqual(info["remote_send"], 1)
        self.assertEqual(db["remote_send"], 1)
        self.assertAlmostEqual(db["tags"]["night"], 20 / 60, places=2)    # 발신 세션 22:40~23:00(LM24 20분)

    def test_floor_window_9_18_boundary(self):
        h, info = self._run(_dt(TUE, 23, 30), [(_dt(TUE, 22, 50), "파일", "설계안.dwg", 3.0, "나")],
                            {"pcFloorWindow": [9, 18]})
        self.assertEqual(info["day_basis"][TUE.isoformat()]["evening"], [["18:00", "22:50"]])
        self.assertEqual(info["cfg_used"]["pcFloorWindow"], ["09:00", "18:00"])


class Private(unittest.TestCase):
    """사적 차감 — 창 샘플러가 사적·미디어 창을 privateRunMin(30) 이상 연속 실측한 구간만"""

    def _run(self, n_priv):
        ticks = (_ticks(TUE, 9, 0, 60) + _ticks(TUE, 10, 0, n_priv, "msedge.exe", "YouTube - Microsoft Edge")
                 + _ticks(TUE, 10, n_priv, 120 - n_priv))
        with _Data() as D:
            D.activity(ticks)
            return _dwh(D.dir, [], TUE, TUE)

    def test_40min_deducted(self):
        h, info = self._run(40)
        self.assertAlmostEqual(info["private_deducted_h"], 40 / 60, places=2)
        self.assertAlmostEqual(h[TUE], 2.33, places=2)
        self.assertEqual(info["day_basis"][TUE.isoformat()]["private_min"], 40)

    def test_20min_kept(self):
        h, info = self._run(20)
        self.assertEqual(info["private_deducted_h"], 0.0)
        self.assertAlmostEqual(h[TUE], 3.0, places=2)

    def test_locked_ticks_not_activity(self):
        with _Data() as D:
            D.activity(_ticks(TUE, 9, 0, 60) + _ticks(TUE, 10, 0, 60, sess="locked"))
            h, _info = _dwh(D.dir, [], TUE, TUE)
        self.assertAlmostEqual(h[TUE], 1.0, places=2)


class Solver(unittest.TestCase):
    """솔버 확인(UD-13) — 그 밤 샘플러 solver_cpu_s 가 0 이면 야간 해석 인정 0, 열이 없으면 LM24"""
    WED = date(2026, 9, 2)
    SIG = [(datetime(2026, 9, 1, 20, 0), "파일", "모델.inp", 3.0, "나"),
           (datetime(2026, 9, 2, 2, 0), "파일(해석출력)", "결과.dat | 폴더:해석 (해석 출력 900건)", 1.5, "나")]

    def _run(self, cpu):
        with _Data() as D:
            if cpu is not None:
                D.activity(_ticks(TUE, 23, 0, 10, "solver.exe", "solver", idle=3600, cpu=cpu))
            return _dwh(D.dir, self.SIG, TUE, self.WED)

    def test_cpu_zero_denies(self):
        _h, info = self._run("0")
        self.assertEqual(info["sim_night_h"], 0.0)
        self.assertGreaterEqual(info["sim_night_cpu_denied"], 1)

    def test_cpu_busy_allows(self):
        _h, info = self._run("60")
        self.assertGreater(info["sim_night_h"], 0.0)
        self.assertEqual(info["sim_night_cpu_denied"], 0)

    def test_no_column_lm24(self):
        _h, info = self._run(None)
        self.assertGreater(info["sim_night_h"], 0.0)


class TimeShare(unittest.TestCase):
    """과제 몫 시간화(옵션) — 합계 정확·상한·미분류 · 기본 weight 는 LM24"""

    def test_total_exact(self):
        cov = [(540, 600, "A", 3.0), (560, 640, "B", 1.0), (900, 960, "C", 0.25), (905, 915, "A", 1.5)]
        out = timeshare.allocate_day(480, cov)
        self.assertEqual(sum(out.values()), 480)
        self.assertEqual(timeshare.split_int(7, {"x": 1.0, "y": 1.0, "z": 1.0}),
                         {"x": 3, "y": 2, "z": 2})

    def test_cap_and_unclassified(self):
        out = timeshare.allocate_day(480, [(540, 600, "A", 1.0)])
        self.assertEqual(out["A"], 120)                       # 직접 60 + 직접 × 1.0
        self.assertEqual(out[timeshare.UNCLASSIFIED], 360)

    def test_overlap_split(self):
        out = timeshare.allocate_day(100, [(0, 60, "A", 1.0), (30, 90, "B", 1.0)])
        self.assertEqual(out, {"A": 50, "B": 50})

    def test_weight_default_is_lm24(self):
        sig = [(_dt(TUE, 9), "파일", "lidarx 설계.dwg", 3.0, "나"), (_dt(TUE, 10), "파일", "lidarx 설계.dwg", 3.0, "나"),
               (_dt(TUE, 11), "메일(수신)", "optix 회의 안내", 1.0, "x"), (_dt(TUE, 12), "메일(수신)", "optix 회의", 1.0, "x")]
        items = extract.build_items(sig, None, min_w=0.0)
        rows = extract.to_rows(items, 2.0)
        tot = sum(v["w"] for v in items.values())
        want = {(p, extract._one_line(a)): round(v["w"] / tot, 4) for (p, a), v in items.items()}
        self.assertEqual({(r["Level 2"], r["Level 3"]): r["share"] for r in rows}, want)   # LM24 가중치 비율 그대로
        self.assertEqual(extract.norm_cfg({})[0]["shareBasis"], "weight")
        self.assertIn("ax", rows[0])
        self.assertIn("field", rows[0])

    def test_time_shares_sum(self):
        sig = [(_dt(TUE, 9), "파일", "lidarx 설계.dwg", 3.0, "나"), (_dt(TUE, 10), "파일", "lidarx 설계.dwg", 3.0, "나"),
               (_dt(TUE, 14), "파일", "optix 계산.xlsx", 3.0, "나"), (_dt(TUE, 15), "파일", "optix 계산.xlsx", 3.0, "나")]
        items, assigns = extract.build_items2(sig, None, min_w=0.0)
        sh, st = extract.time_shares(assigns, {TUE: 8.0}, {})
        self.assertAlmostEqual(sum(sh.values()), 1.0, places=9)
        self.assertEqual(st["total_min"], 480)
        rows = extract.to_rows(items, 1.0, shares=sh)
        self.assertAlmostEqual(sum(r["share"] for r in rows), 1.0, places=3)


class FloorWindow(unittest.TestCase):
    """PC 하한 창 — 기본은 LM24 와 같고 [9,18] 이면 줄어든다 · 날짜별 근거"""
    SIG = [(_dt(TUE, 10), "파일", "설계안.dwg", 3.0, "나")]

    def _run(self, mm):
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 8), _dt(TUE, 19))])
            return _dwh(D.dir, self.SIG, TUE, TUE, mm=mm)

    def test_default_equals_lm24_and_narrow_reduces(self):
        h0, i0 = self._run(None)
        h1, _i1 = self._run({"pcFloorWindow": [8, 19]})
        h2, _i2 = self._run({"pcFloorWindow": [9, 18]})
        self.assertAlmostEqual(h0[TUE], 9.67, places=2)            # 08:10~18:50(창 다듬기) − 점심 1h — LM24 산식
        self.assertEqual(h0[TUE], h1[TUE])
        self.assertAlmostEqual(h2[TUE], 8.0, places=2)
        self.assertLess(h2[TUE], h0[TUE])
        fl = i0["day_basis"][TUE.isoformat()]["floor"]
        self.assertIn("파일", fl["open"])
        self.assertAlmostEqual(fl["cut"]["lunch_h"], 1.0, places=2)
        self.assertEqual(i0["cfg_used"]["pcFloorWindow"], ["08:00", "19:00"])
        self.assertIn("09~18", i0["cfg_used"]["floorBasis"])
        self.assertIn("근거", i0["basis"])


class Unobserved(unittest.TestCase):
    """미관측 — 메일 축이 미관측인 날은 부재 추정 안 함, 팀즈 na 는 무시"""
    D1, D2, D3, D4 = (date(2026, 9, d) for d in (1, 2, 3, 4))

    def _run(self, days, na=None):
        with _Data() as D:
            D.pc_spans([(_dt(self.D1, 9), _dt(self.D1, 9, 10)), (_dt(self.D2, 9), _dt(self.D2, 9, 10))])
            if days is not None:
                D.ledger(days, na)
            return _dwh(D.dir, [], self.D1, self.D4)

    def test_lm24_without_ledger(self):
        _h, info = self._run(None)
        self.assertEqual(info["inferred_absence_days"], 4)
        self.assertFalse(info["coverage_ledger"])

    def test_mail_unobserved_blocks(self):
        ok = {"com": "ok"}
        days = {self.D1.isoformat(): {"mail_in": ok, "mail_out": ok, "teams": ok},
                self.D3.isoformat(): {"mail_in": ok, "mail_out": ok, "teams": {"web": "partial"}},
                self.D4.isoformat(): {"mail_in": ok, "mail_out": ok, "teams": ok}}
        _h, info = self._run(days)
        self.assertEqual(info["inferred_absence_dates"], [self.D1.isoformat(), self.D3.isoformat(), self.D4.isoformat()])
        self.assertEqual(info["inferred_absence_blocked_unobserved"], 1)
        self.assertEqual(info["unobserved_days"], [self.D2.isoformat(), self.D3.isoformat()])
        self.assertEqual(info["evidence_none_observed"], 2)

    def test_teams_na_ignored(self):
        ok = {"com": "ok"}
        days = {d.isoformat(): {"mail_in": ok, "mail_out": ok} for d in (self.D1, self.D2, self.D3, self.D4)}
        _h, info = self._run(days, na={"teams": True})
        self.assertEqual(info["unobserved_days"], [])
        self.assertEqual(info["inferred_absence_days"], 4)


class Holidays(unittest.TestCase):
    def test_2028_and_2029_warning(self):
        self.assertTrue(extract._is_off_day(date(2028, 1, 1), set()))
        self.assertTrue(extract._is_off_day(date(2028, 1, 26), set()))        # 설(수)
        self.assertFalse(extract._is_off_day(date(2028, 1, 28), set()))       # 금요일 근무일
        self.assertEqual(extract.holiday_table_warnings(date(2028, 1, 1), date(2028, 12, 31)), [])
        w = extract.holiday_table_warnings(date(2029, 1, 1), date(2029, 1, 31))
        self.assertTrue(w and "2029" in w[0])
        self.assertEqual(extract.holiday_table_warnings(date(2029, 1, 1), date(2029, 1, 31),
                                                        {"holidays": ["2029-02-12"]}), [])
        with _Data() as D:
            _h, info = extract.day_work_hours(D.dir, [], date(2029, 1, 1), date(2029, 1, 3), {}, now=NOW, file_times={})
        self.assertTrue(any("2029" in x for x in info["config_warnings"]))


class MetaKeys(unittest.TestCase):
    """mm_meta 에 measure·coverage·cfg_used·unobserved_days — mine.meta_doc"""

    def test_meta_doc(self):
        old = sys.stdout
        import mine
        self.assertIs(sys.stdout, old)                      # 임포트만으로 stdout 을 바꿔 끼우지 않는다
        with _Data() as D:
            D.ledger({TUE.isoformat(): {"mail_in": {"com": "ok"}}})
            h, info = _dwh(D.dir, [], TUE, TUE)
        info.pop("inferred_absence", None)                  # mine 도 저장 전에 뺀다(날짜 키)
        doc = mine.meta_doc(TUE, TUE, 0.03, [], {"counted": {}, "excluded": {}, "weights": {}}, 0.0, 1.0, 0.0, {},
                            [], h, info)
        for k in ("measure", "coverage", "cfg_used", "unobserved_days", "mm_basis"):
            self.assertIn(k, doc)
        self.assertEqual(doc["unobserved_days"], [TUE.isoformat()])
        json.dumps(doc, ensure_ascii=False)                 # 직렬화 가능(날짜 키 없음)

    def test_mine_main_time_basis(self):
        """mine.main 한 바퀴(임시 ROOT) — shareBasis=time · mm_rows 끝 열 · mm_meta 키"""
        import mine
        with tempfile.TemporaryDirectory(prefix="lm28_p8_root_") as root, _Data() as D:
            os.makedirs(os.path.join(root, "report"))
            os.makedirs(os.path.join(D.dir, "files"))
            fol = os.path.join(D.dir, "work", "lidarx")
            with open(os.path.join(D.dir, "files", "files.csv"), "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["mtime", "ext", "size_kb", "folder", "name", "author"])
                for hh in (9, 10, 14, 15):
                    w.writerow([f"2026-09-01 {hh:02d}:00:00", ".dwg", "10", fol, f"lidarx_{hh}.dwg", ""])
            D.pc_spans([(_dt(TUE, 8), _dt(TUE, 19))])
            cfg = {"mm": {"shareBasis": "time"}}
            saved = (mine.ROOT, extract.load_cfg, sys.argv, sys.stdout)
            try:
                mine.ROOT, extract.load_cfg = root, (lambda: cfg)
                sys.argv = ["mine.py", D.dir, "--from", "2026-09-01", "--to", "2026-09-01"]
                sys.stdout = io.StringIO()
                rc = mine.main()
            finally:
                mine.ROOT, extract.load_cfg, sys.argv, sys.stdout = saved
            self.assertEqual(rc, 0)
            tag = "20260901-20260901"
            with open(os.path.join(root, "report", f"mm_meta_{tag}.json"), encoding="utf-8") as f:
                meta = json.load(f)
            for k in ("measure", "coverage", "cfg_used", "unobserved_days", "time_share"):
                self.assertIn(k, meta)
            self.assertEqual(meta["cfg_used"]["shareBasis"], "time")
            with open(os.path.join(root, "report", f"mm_rows_{tag}.csv"), encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(list(rows[0].keys())[-2:], ["ax", "field"])
            self.assertAlmostEqual(sum(float(r["share"]) for r in rows), 1.0, places=3)

    def test_template_has_no_skeleton_keys(self):
        with open(os.path.join(_boot.ROOT, "config", "config.default.json"), encoding="utf-8-sig") as f:
            mm = json.load(f)["mm"]
        self.assertNotIn("eveningMode", mm)
        self.assertNotIn("offhoursSkeletonPadMin", mm)
        self.assertEqual((mm["shareBasis"], mm["pcFloorWindow"]), ("weight", [8, 19]))


# ════════════════════════════════ 8b 계층 ════════════════════════════════
CFG_L1 = ({}, list(details._L1_AX_DEFAULT), list(details._L1_COMMON_DEFAULT))


class Domains(unittest.TestCase):
    def test_ext_and_synonyms(self):
        ext = details.EXT_L1
        self.assertEqual(details.snap1("외부지원"), ext)
        self.assertEqual(details.snap1("국책"), ext)
        self.assertEqual(details.snap1("지원"), "")                         # LM24 '지원 → 공통' 폐기
        self.assertEqual(details.l1_color(ext), "#0e8c7a")
        self.assertIn(ext, details.LEVEL1_SET)

    def test_keyword_table(self):
        lv = details.level1_of
        self.assertEqual(lv("산학협력 과제 회의", "", cfg=CFG_L1), details.EXT_L1)
        self.assertEqual(lv("보안교육 이수 안내", "", cfg=CFG_L1), "공통")       # 긴 키워드가 '교육'을 덮는다
        self.assertEqual(lv("신입 사원 교육 자료", "", cfg=CFG_L1), details.EXT_L1)
        self.assertEqual(lv("LLM 활용 산학 과제", "", cfg=CFG_L1), details.EXT_L1)  # 우선순위 EXT > AX
        self.assertEqual(lv("실험실 자동화", "", cfg=CFG_L1), "AX")              # AX > 공통
        self.assertEqual(lv("온라인 가이드라인 정리", "", cfg=CFG_L1), "")       # '라인' 오인 없음
        self.assertEqual(lv("email 정리", "", cfg=CFG_L1), "")                  # 'ai' ⊄ 'email'

    def test_ax_flag_and_field(self):
        self.assertEqual(details.ax_flag("LLM 요약 도구"), 1)
        self.assertEqual(details.ax_flag("자동화 프롬프트 정리"), 1)
        self.assertEqual(details.ax_flag("자동화 검토"), 0)
        self.assertEqual(details.field_of("PCB 아트웍 검토"), "회로")
        self.assertEqual(details.field_of(""), "")

    def test_explain_failure_reason(self):
        why, _how, fatal = details.explain_failure({"phase": "login_required", "reason": "R-PERSONAL"})
        self.assertIn("개인", why)
        self.assertTrue(fatal)
        why, _how, fatal = details.explain_failure({"phase": "blocked", "reason": "R-GATE"})
        self.assertIn("관문", why)
        self.assertFalse(fatal)


class KwHit(unittest.TestCase):
    def test_boundaries(self):
        kh = projmap._kw_hit
        self.assertFalse(kh("정렬", {"재정렬"}))                      # 부분 문자열 금지
        self.assertFalse(kh("ai", {"email", "detail"}))
        self.assertTrue(kh("ai", {"ai기반"}))
        self.assertTrue(kh("과제a", {"과제a의"}))                      # 한글 앞 경계(조사)
        self.assertTrue(kh("해석", {"열해석"}, mode="head"))           # head 접두 ≤3
        self.assertFalse(kh("해석", {"열해석"}))
        self.assertFalse(kh("해석", {"구조열유동해석"}, mode="head"))   # 접두 4자 이상은 아니다

    def test_retag_tie_kept(self):
        rows = [{"model": "공통", "text": "alpha beta 공용 검토"}]
        n, _by, _ev = projmap.retag_rows(rows, [{"name": "alpha", "match": []}, {"name": "beta", "match": []}])
        self.assertEqual(n, 0)


class RuleNames(unittest.TestCase):
    def test_noise_filtered(self):
        sig = []
        for i in range(3):
            sig.append((_dt(TUE, 9 + i), "파일", "untitled_1 copy rev3 20260105 lidarx.docx", 3.0, "나"))
        for i in range(6):
            sig.append((_dt(TUE, 13, i), "파일", f"memo{i}x.txt", 3.0, "나"))
        items = extract.build_items(sig, None, min_w=0.0)
        projs = {p for p, _a in items}
        self.assertIn("lidarx", projs)
        for bad in ("untitled", "copy", "rev3", "20260105"):
            self.assertNotIn(bad, projs)
        self.assertFalse(extract.rule_name_ok("v2"))
        self.assertFalse(extract.rule_name_ok("260105"))
        self.assertTrue(extract.rule_name_ok("lidarx"))

    def test_rule_model_skips_noise_keys(self):
        import judge
        models = [{"name": "프로젝트x", "match": ["untitled"]}, {"name": "공통", "match": []}]
        self.assertEqual(judge.rule_model({"text": "untitled 문서"}, models), "공통")


class Episodes(unittest.TestCase):
    def _units(self, rows, cfg=None):
        import judge
        return judge.build_units(rows, cfg)

    @staticmethod
    def _r(t, src, text, model, detail):
        return {"time": t.strftime("%Y-%m-%d %H:%M"), "source": src, "text": text, "model": model, "detail": detail,
                "weight": "1"}

    def test_grades(self):
        r = self._r
        rows = [r(_dt(TUE, 9), "메일(수신)", "[요청] 시험 자료 작성 부탁드립니다", "과제A", "시험 자료"),
                r(_dt(TUE, 14), "파일", "시험자료_초안.xlsx | 폴더:시험", "과제A", "시험 자료"),
                r(_dt(date(2026, 9, 2), 10), "메일(발신)", "RE: 시험 자료 결과 송부드립니다", "과제A", "시험 자료"),
                r(_dt(TUE, 10), "파일", "a.dwg", "과제B", "설계"),
                r(_dt(date(2026, 9, 2), 11), "파일", "b.dwg", "과제B", "설계"),
                r(_dt(date(2026, 9, 3), 15), "파일", "c.dwg", "과제B", "설계"),
                r(_dt(date(2026, 9, 14), 9), "파일", "z.txt", "과제C", "기타")]
        res = self._units(rows)
        by = {u["model"]: u for u in res["units"]}
        a, b = by["과제A"], by["과제B"]
        self.assertEqual((a["start_cue"], a["end_cue"], a["grade"], a["status"]), ("S1", "E1", "확정", "closed"))
        self.assertEqual((b["start_cue"], b["end_cue"], b["grade"]), ("S2p", "E3i", "추정"))
        self.assertEqual(b["start"], "2026-09-01 09:30")                  # 첫 진행 −30
        self.assertEqual(b["end"], "2026-09-03 15:30")                    # 마지막 진행 +30
        self.assertEqual(self._units(rows, {"episodeTop": 1})["units"].__len__(), 1)

    def test_final_name_and_pdf(self):
        r = self._r
        rows = [r(_dt(TUE, 8), "메일(수신)", "[검토 요청] 제안서 작성 부탁드립니다", "과제D", "제안"),
                r(_dt(TUE, 9), "파일", "제안서.pptx", "과제D", "제안"),
                r(_dt(TUE, 11), "파일", "제안서_v2.pptx", "과제D", "제안"),
                r(_dt(TUE, 12), "파일", "제안서_v2.pdf", "과제D", "제안"),      # 같은 줄기 PDF → 작성 완료
                r(_dt(TUE, 15), "파일", "보고서_최종.docx", "과제E", "보고")]    # 최종 이름(오프라인 시작)
        by = {u["model"]: u for u in self._units(rows)["units"]}
        self.assertEqual((by["과제D"]["start_cue"], by["과제D"]["end_cue"], by["과제D"]["grade"]), ("S1", "E2h", "근거"))
        self.assertEqual((by["과제E"]["end_cue"], by["과제E"]["grade"]), ("E2h", "추정"))


class WriteOutputs(unittest.TestCase):
    """judge.write_outputs — mm_rows 끝 열 ax·field, shareBasis=time 이면 시간 몫(합 1)·미분류 행"""

    def _write(self, cfg):
        import judge
        with tempfile.TemporaryDirectory(prefix="lm28_p8_rep_") as rep:
            tag = "20260901-20260901"
            with open(os.path.join(rep, f"mm_meta_{tag}.json"), "w", encoding="utf-8") as f:
                json.dump({"total_mm": 0.05, "day_hours": {"2026-09-01": 8.0}}, f)
            kept = [{"time": "2026-09-01 09:00", "source": "파일", "text": "a.dwg", "weight": "3", "model": "과제A",
                     "detail": "설계", "worktype": "개발"},
                    {"time": "2026-09-01 15:00", "source": "메일(수신)", "text": "LLM 문의", "weight": "1",
                     "model": "과제B", "detail": "LLM 검토", "worktype": "사무"}]
            buf, old = io.StringIO(), sys.stdout
            sys.stdout = buf
            try:
                judge.write_outputs(kept, tag, cfg, rep)
            finally:
                sys.stdout = old
            with open(os.path.join(rep, f"mm_rows_{tag}.csv"), encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            with open(os.path.join(rep, f"pivots_{tag}.json"), encoding="utf-8") as f:
                pv = json.load(f)
        return rows, pv

    def test_weight_default(self):
        rows, pv = self._write({})
        self.assertEqual(list(rows[0].keys())[-2:], ["ax", "field"])
        self.assertEqual({r["Level 2"]: float(r["share"]) for r in rows}, {"과제A": 0.75, "과제B": 0.25})
        self.assertEqual({r["Level 2"]: r["ax"] for r in rows}["과제B"], "1")
        self.assertIn("units", pv["episodes"])
        self.assertIn("orders", pv["episodes"])

    def test_time_basis(self):
        rows, _pv = self._write({"mm": {"shareBasis": "time"}})
        names = {r["Level 2"] for r in rows}
        self.assertIn(timeshare.UNCLASSIFIED, names)
        self.assertAlmostEqual(sum(float(r["share"]) for r in rows), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
