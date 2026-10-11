# -*- coding: utf-8 -*-
r"""tests\test_p14_mm_time.py — LM28 E: 투입 MM 이 낮고 야근·밤샘·주말이 덜 잡히던 것.

  · 재산정: AI 가 비업무(n)로 거른 본인 발신은 시간 근거로 남는다(화면 '내 업무 아님'·AI-n 파일은 예전처럼 빠진다)
  · 날짜만 아는 발신(메일·팀즈 웹): 정오 자리표가 창·흔적 창의 기준점이 되지 않고, 하한 없는 날은 '시각 미상 발신' 으로 인정
  · 브라우저 기록(hint)만 있는 날: 흔적 창 하한(trace_hint)·저녁은 PC 야간 캡 없이 · 항상 켜진 PC 의 흔적 창에 방문 구간
  · PC 기록 없는 달의 평일: 표준일 추정(mm.noPcMonthDay=standard · trace 면 예전)
  · 밤샘 다음 날 새벽은 마지막 새벽 산출물 +30분에서 멈춤(이른 출근은 LM24 그대로)
  · day_basis 는 0h 평일에도 · 퇴근 후 미인정 이유(why)
  · 수집기: OWA 병합 정밀도 래칫·지난 판 시각 재사용(run.known)·아바타 머리글자·부재중 표시 / 팀즈 웹 날짜만 보존·내 말풍선 진단·
    지난 판 행 바로잡기(Store) / 근태(열 없는 웹 일정은 내 부재중·내 이름만) / 사적 판정(본인 발신은 퇴근 후 +1점 없음)

가짜 data 폴더(tempfile)만 쓴다. 실 Outlook·Edge·네트워크는 쓰지 않는다. 날짜: 2026-08-31(월)~09-05(토)."""
import contextlib
import csv
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock

import _boot  # noqa: F401  — 경로 등록

import extract  # noqa: E402
import owa_parse as op  # noqa: E402
import privacy  # noqa: E402

sys.path.insert(0, os.path.join(_boot.TESTS, "fakes"))
import fake_browser as fb  # noqa: E402
import fake_teams as ft  # noqa: E402

COL = os.path.join(_boot.ROOT, "collect")


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, os.path.join(COL, fn))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


owa = _load("owa_web_p14", "Get-OutlookWeb.py")
owa._sleep = lambda s: None
owa.log = lambda msg: None
tw = _load("teams_web_p14", "Get-TeamsWeb.py")
tw.log = lambda msg: None

NOW = datetime(2026, 10, 7, 12, 0)
MON = date(2026, 8, 31)
TUE = date(2026, 9, 1)
WED = date(2026, 9, 2)
FRI = date(2026, 9, 4)
SAT = date(2026, 9, 5)
TODAY = date(2026, 10, 7)                          # 수요일
CAL_HDR = ["start", "end", "all_day", "busy_status", "subject", "categories", "location", "response", "meeting_status"]
TEAMS_HDR = ["time", "from", "chat", "kind", "replied_time", "summary", "time_precision"]


def _dt(d, hh, mm=0):
    return datetime(d.year, d.month, d.day, hh, mm)


def _csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


class _Data:
    """가짜 data 폴더 — with 블록이 끝나면 지워진다. 로그온 표시명은 비운다(개발 PC 의 레지스트리와 무관하게)."""

    def __enter__(self):
        self._t = tempfile.TemporaryDirectory(prefix="lm28_p14_")
        self.dir = self._t.name
        self._p = mock.patch.object(extract, "_logon_display_name", lambda: "")
        self._p.start()
        return self

    def __exit__(self, *a):
        self._p.stop()
        self._t.cleanup()

    def pc_spans(self, spans):
        """spans = [(시작, 끝[, src])] — src 기본 event"""
        rows = [[a.strftime("%Y-%m-%d %H:%M:%S"), b.strftime("%Y-%m-%d %H:%M:%S"), (x[0] if x else "event")]
                for a, b, *x in spans]
        _csv(os.path.join(self.dir, "pc", "pc_spans.csv"), ["start", "end", "src"], rows)

    def teams(self, rows, name="teams_web.csv"):
        _csv(os.path.join(self.dir, "m365", name), TEAMS_HDR, rows)

    def calendar(self, rows):
        _csv(os.path.join(self.dir, "outlook", "calendar.csv"), CAL_HDR, rows)


def _dwh(data, sig, d0, d1, mm=None, cfg=None):
    c = dict(cfg or {})
    if mm is not None:
        c["mm"] = mm
    return extract.day_work_hours(data, sig, d0, d1, c, now=NOW, file_times={})


def _row(t, src, text, w="1.5", judge="AI", who="나"):
    return {"time": t.strftime("%Y-%m-%d %H:%M"), "source": src, "who": who, "text": text, "weight": w, "judge": judge}


# ════════════════════════════════ 재산정(AI 비업무 발신) ════════════════════════════════
class RehoursKeep(unittest.TestCase):
    """PC 가 밤까지 켜진 평일 — 21:30 본인 팀즈 답장이 AI 비업무(AI-n)면 시간 근거로 남고(저녁 인정 유지), 화면 '내 업무 아님'(AI)·
    AI-n 파일은 예전처럼 빠진다."""

    def _run(self, dropped):
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 8, 30), _dt(TUE, 23, 0))])
            kept = [_row(_dt(TUE, 10), "파일", "설계안.dwg", "3")]
            # 시차 근무 창 밖 인정(flexEdgeH)은 끈다 — 저녁 인정만 본다
            return extract.rehours_after_judge(D.dir, kept, dropped, TUE, TUE, {"mm": {"flexEdgeH": 0}})

    def test_ai_n_send_kept_as_time(self):
        r = self._run([_row(_dt(TUE, 21, 30), "팀즈(발신)", "네 확인", judge="AI-n")])
        db = r["info"]["day_basis"][TUE.isoformat()]
        self.assertEqual(r["time_kept_n"], 1)
        self.assertEqual(r["info"]["ai_n_time_kept"], 1)
        self.assertEqual(db["ai_n_kept"], 1)
        self.assertEqual(db["evening"], [["19:00", "21:30"]])
        self.assertEqual(db["ev"]["why"], "credited")
        self.assertEqual(r["dropped_h"], 0.0)                      # 버린 행이 시간을 빼지 않았다

    def test_ui_excluded_and_ai_n_file_dropped(self):
        keep = self._run([_row(_dt(TUE, 21, 30), "팀즈(발신)", "네 확인", judge="AI-n")])
        for dropped in ([_row(_dt(TUE, 21, 30), "팀즈(발신)", "네 확인", judge="AI")],          # 화면 '내 업무 아님'
                        [_row(_dt(TUE, 21, 30), "파일", "개인메모.txt", "3", judge="AI-n")]):   # AI 비업무 파일
            r = self._run(dropped)
            db = r["info"]["day_basis"][TUE.isoformat()]
            self.assertEqual(r["time_kept_n"], 0)
            self.assertNotIn("evening", db)
            self.assertEqual(db["ev"]["why"], "no_active_after")    # 19시 이후 PC 는 켜져 있었는데 내 흔적 0
            self.assertGreater(r["dropped_h"], 2.0)
            self.assertLess(sum(r["day_hours"].values()), sum(keep["day_hours"].values()) - 2.0)
            self.assertEqual(r["info"]["evening_missed_days"], 1)


# ════════════════════════════════ 날짜만 아는 발신 ════════════════════════════════
class Untimed(unittest.TestCase):
    def test_saturday_date_only_send(self):
        """날짜만 발신 하나뿐인 토요일(PC 14~18시): 11:30~12:30 주말 창이 생기지 않고 20분이 휴일 꼬리표로."""
        with _Data() as D:
            D.pc_spans([(_dt(SAT, 14), _dt(SAT, 18))])
            h, info = _dwh(D.dir, [(_dt(SAT, 12), "메일(발신·일자)", "자료 회신", 1.5, "나")], SAT, SAT)
        db = info["day_basis"][SAT.isoformat()]
        self.assertAlmostEqual(h[SAT], 0.33, places=2)
        self.assertEqual(info["weekend_window_h"], 0.0)
        self.assertEqual(db["tags"], {"holiday": 0.33})
        self.assertEqual(db["untimed"], {"n": 1, "credit_min": 20})
        self.assertEqual(db["floor"]["kind"], "untimed")
        self.assertEqual((info["untimed_sends"], info["untimed_days"]), (1, 1))
        self.assertAlmostEqual(info["untimed_credit_h"], 0.33, places=2)

    def test_always_on_window_from_hints_not_noon(self):
        """항상 켜진 평일 — 시각 있는 능동 흔적 없이 날짜만 발신 2건 + 브라우저 방문 09:00-09:40·17:30-17:50: 하한 창은 08:30~18:20
        (점심·저녁 식사 차감)이고 정오 1h 창이 아니다."""
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 0), _dt(WED, 0)), (_dt(TUE, 9), _dt(TUE, 9, 40), "hint"),
                        (_dt(TUE, 17, 30), _dt(TUE, 17, 50), "hint")])
            sig = [(_dt(TUE, 12), "메일(발신·일자)", "회신 1", 1.5, "나"), (_dt(TUE, 12), "메일(발신·일자)", "회신 2", 1.5, "나")]
            h, info = _dwh(D.dir, sig, TUE, TUE)
        db = info["day_basis"][TUE.isoformat()]
        self.assertEqual(db["floor"]["kind"], "always_on")
        self.assertTrue(db["pc"]["always_on"])
        self.assertAlmostEqual(h[TUE], 8.5, places=2)              # 08:30~18:20 − 점심 1h − 저녁 식사 20분
        self.assertEqual(db["untimed"]["credit_min"], 0)            # 하한이 놓인 날은 시각 미상 인정을 따로 더하지 않는다

    def test_teams_date_only_rows(self):
        """팀즈 웹 날짜만 행 — 내 글은 '팀즈(발신·일자)'(시각 미상 10분), 남의 글은 '팀즈(수신·일자)'(시간 없음), 같은 글의 분 단위
        사본이 있으면 날짜만 행은 버린다."""
        with _Data() as D:
            D.teams([["2026-09-01 12:00", "나", "설계방", "sent", "", "설계 검토 회신 드립니다", "date"],
                     ["2026-09-01 12:00", "김철수", "설계방", "msg", "", "자료 공유드립니다", "date"],
                     ["2026-09-02 12:00", "나", "설계방", "sent", "", "보고서 송부합니다", "date"],
                     ["2026-09-02 15:10", "나", "설계방", "sent", "", "보고서 송부합니다", "minute"]])
            cfg = {"owner": "홍길동", "mm": {"noPcMonthDay": "trace"}}
            with contextlib.redirect_stdout(io.StringIO()):
                sig, meta = extract.load_signals(D.dir, TUE, WED, [], cfg)
            h, info = _dwh(D.dir, sig, TUE, WED, cfg=cfg)
        self.assertEqual(meta["counted"], {"팀즈(발신·일자)": 1, "팀즈(수신·일자)": 1, "팀즈(발신)": 1})
        self.assertEqual(meta["excluded"].get("중복(같은 팀즈 글의 정확한 시각 사본 있음)"), 1)
        self.assertEqual({s[0] for s in sig if s[1] == "팀즈(발신)"}, {_dt(WED, 15, 10)})
        db = info["day_basis"][TUE.isoformat()]
        self.assertEqual(db["untimed"], {"n": 1, "credit_min": 10})
        self.assertAlmostEqual(h[TUE], 0.17, places=2)
        self.assertEqual(info["untimed_sends"], 1)


# ════════════════════════════════ 브라우저 기록만 있는 날 ════════════════════════════════
class HintOnly(unittest.TestCase):
    def test_trace_hint_floor_and_evening(self):
        """브라우저 방문(1.3h)만 있는 평일에 능동 흔적 09:10·17:40 — 하한은 흔적 창(표준일 상한 8h), 예전 방문 합 1.3h 가 아니다.
        21:00 산출물이 있으면 저녁은 PC 야간 캡 없이 [20:30 방문 −30, 21:00]."""
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 9), _dt(TUE, 9, 40), "hint"), (_dt(TUE, 13), _dt(TUE, 13, 20), "hint"),
                        (_dt(TUE, 17, 30), _dt(TUE, 17, 50), "hint"), (_dt(WED, 9), _dt(WED, 9, 40), "hint"),
                        (_dt(WED, 20, 30), _dt(WED, 21, 10), "hint")])
            sig = [(_dt(TUE, 9, 10), "파일", "a.dwg", 3.0, "나"), (_dt(TUE, 17, 40), "파일", "b.dwg", 3.0, "나"),
                   (_dt(WED, 9, 10), "파일", "c.dwg", 3.0, "나"), (_dt(WED, 21), "파일", "d.dwg", 3.0, "나")]
            kinds = {}
            extract.pc_daily(D.dir, TUE, WED, kinds=kinds)
            h, info = _dwh(D.dir, sig, TUE, WED)
        self.assertEqual(kinds["evt_days"], set())
        self.assertEqual(sorted(kinds["hint_sp"]), [TUE, WED])
        tue = info["day_basis"][TUE.isoformat()]
        self.assertEqual(tue["floor"]["kind"], "trace_hint")
        self.assertEqual(tue["pc"]["rec"], "hint")
        self.assertAlmostEqual(h[TUE], 8.0, places=2)
        wed = info["day_basis"][WED.isoformat()]
        self.assertEqual(wed["evening"], [["20:00", "21:00"]])
        self.assertEqual(wed["ev"]["why"], "credited")
        self.assertEqual(info["hint_only_days"], 2)


# ════════════════════════════════ PC 기록 없는 달 ════════════════════════════════
class NoPcMonth(unittest.TestCase):
    SIG = [(_dt(TUE, 10), "팀즈(발신)", "검토 회신", 0.9, "나"), (_dt(TUE, 21), "파일", "보고서.pptx", 3.0, "나"),
           (_dt(SAT, 10), "팀즈(발신)", "주말 확인", 0.9, "나")]

    def test_standard_adds_evening_and_skips_holiday(self):
        with _Data() as D:
            h, info = _dwh(D.dir, self.SIG, TUE, SAT)
        db = info["day_basis"][TUE.isoformat()]
        self.assertAlmostEqual(h[TUE], 9.0, places=2)              # 표준일 8h + 저녁 세션 1h
        self.assertEqual((db["floor"]["kind"], db["floor"]["est"]), ("std_nopc", True))
        self.assertAlmostEqual(h[SAT], 0.17, places=2)             # 휴일은 표준일 추정 없음
        self.assertEqual(info["std_nopc_days"], 1)
        self.assertEqual(info["cfg_used"]["noPcMonthDay"], "standard")
        self.assertEqual(info["measure"]["std_nopc_days"], 1)
        self.assertEqual(db["pc"]["rec"], "none")

    def test_trace_is_old_behavior(self):
        sig = [self.SIG[0]]
        with _Data() as D:
            h_t, info_t = _dwh(D.dir, sig, TUE, FRI, mm={"noPcMonthDay": "trace"})
            h_s, info_s = _dwh(D.dir, sig, TUE, FRI)
        self.assertAlmostEqual(h_t[TUE], 1.0, places=2)            # 흔적 창 09:30~10:30
        self.assertEqual(info_t["day_basis"][TUE.isoformat()]["floor"]["kind"], "trace")
        self.assertEqual(info_t["std_nopc_days"], 0)
        self.assertAlmostEqual(h_s[TUE], 8.0, places=2)
        self.assertEqual(extract.norm_cfg({})[0]["noPcMonthDay"], "standard")
        n, warns = extract.norm_cfg({"mm": {"noPcMonthDay": "always"}})
        self.assertEqual(n["noPcMonthDay"], "standard")
        self.assertTrue(any("noPcMonthDay" in w for w in warns))
        with open(os.path.join(_boot.ROOT, "config", "config.default.json"), encoding="utf-8-sig") as f:
            c = json.load(f)
        self.assertEqual(c["mm"]["noPcMonthDay"], "standard")
        self.assertIn("추정", c["_mm_옵션_설명"]["noPcMonthDay"])


# ════════════════════════════════ 밤샘 다음 날 새벽 ════════════════════════════════
class Dawn(unittest.TestCase):
    def test_after_all_nighter_stops_at_last_dawn_product(self):
        """밤샘(월 22:00 → 화 02:10, 켜 둔 PC) 다음 날 새벽 인정은 00:00~02:40 에서 멈춘다. 수요일 06:30 첫 산출물(이른 출근)은
        LM24 그대로 06:00~08:00."""
        with _Data() as D:
            D.pc_spans([(_dt(MON, 8), _dt(WED, 0)), (_dt(WED, 6), _dt(WED, 18))])
            sig = [(_dt(MON, 22), "파일", "a.dwg", 3.0, "나"), (_dt(TUE, 2, 10), "파일", "b.dwg", 3.0, "나"),
                   (_dt(TUE, 10), "파일", "c.dwg", 3.0, "나"), (_dt(WED, 6, 30), "파일", "d.dwg", 3.0, "나"),
                   (_dt(WED, 10), "파일", "e.dwg", 3.0, "나")]
            _h, info = _dwh(D.dir, sig, MON, WED, mm={"trimIdleEdgesMin": 0})
        self.assertEqual(info["day_basis"][TUE.isoformat()]["dawn"], [["00:00", "02:40"]])
        self.assertEqual(info["day_basis"][WED.isoformat()]["dawn"], [["06:00", "08:00"]])


# ════════════════════════════════ 날짜별 근거 ════════════════════════════════
class DayBasis(unittest.TestCase):
    def test_zero_hour_weekdays_recorded(self):
        with _Data() as D:
            D.pc_spans([(_dt(TUE, 8, 30), _dt(TUE, 22))])
            h, info = _dwh(D.dir, [], TUE, SAT)
        tue, wed = info["day_basis"][TUE.isoformat()], info["day_basis"][WED.isoformat()]
        self.assertEqual(h, {})
        self.assertEqual((tue["h"], tue["pc"]["rec"], tue["ev"]["why"]), (0.0, "event", "no_active_after"))
        self.assertAlmostEqual(tue["ev"]["pc_after_h"], 3.0, places=2)
        self.assertEqual((wed["h"], wed["pc"]["rec"]), (0.0, "none"))
        self.assertNotIn(SAT.isoformat(), info["day_basis"])        # 흔적 없는 휴일은 남기지 않는다
        self.assertEqual((info["evening_missed_days"], info["evening_missed_pc_h"]), (1, 3.0))
        json.dumps(info["day_basis"], ensure_ascii=False)


# ════════════════════════════════ 근태·사적 판정 ════════════════════════════════
class Absence(unittest.TestCase):
    def test_web_rows_need_oof_or_my_name(self):
        r = {"meeting_status": "", "response": "", "busy_status": "2", "subject": "[휴가] 홍길동"}
        self.assertTrue(extract._absence_skip(r, {"김철수"}))         # 동료 휴가 초대(바쁨으로 읽힘) — 내 근태 아님
        self.assertFalse(extract._absence_skip(r, {"홍길동"}))        # 제목에 내 이름
        self.assertFalse(extract._absence_skip(dict(r, busy_status="3", subject="휴가"), {"김철수"}))   # 내가 부재중으로 표시
        self.assertTrue(extract._absence_skip(dict(r, meeting_status="3", busy_status="2"), {"홍길동"}))  # COM 받은 초대(예전 규칙)
        self.assertFalse(extract._absence_skip(dict(r, meeting_status="1", busy_status="2"), set()))    # COM 행은 예전 규칙
        with _Data() as D:
            D.calendar([["2026-09-01 00:00", "2026-09-02 00:00", "True", "2", "[휴가] 홍길동", "", "", "", ""],
                        ["2026-09-03 00:00", "2026-09-04 00:00", "True", "3", "여름휴가", "", "", "", ""]])
            ab = extract.absence_days(D.dir, TUE, FRI, cfg={"owner": "김철수"})
            ab2 = extract.absence_days(D.dir, TUE, FRI, cfg={"owner": "홍길동"})
        self.assertEqual(ab, {date(2026, 9, 3): 1.0})
        self.assertEqual(ab2, {TUE: 1.0, date(2026, 9, 3): 1.0})

    def test_owa_show_as_mapping(self):
        d0, d1 = date(2026, 10, 1), date(2026, 10, 31)
        oof = owa.parse_event({"label": "휴가, 2026년 10월 5일 월요일, 종일, 부재중", "texts": ["휴가"]}, d0, d1)
        self.assertEqual((oof[2], oof[3]), ("True", "3"))
        else_ = owa.parse_event({"label": "현장 지원, 2026년 10월 6일 오후 2:00 ~ 오후 3:00, 다른 곳에서 작업 중",
                                 "texts": ["현장 지원"]}, d0, d1)
        self.assertEqual(else_[3], "4")
        free = owa.parse_event({"label": "팀 회의, 2026년 10월 6일 오후 2:00 ~ 오후 3:00, 한가함", "texts": ["팀 회의"]}, d0, d1)
        self.assertEqual(free[3], "0")
        subj = owa.parse_event({"label": "[부재중 안내] 공유, 2026년 10월 6일 오후 4:00 ~ 오후 5:00, 바쁨",
                                "texts": ["[부재중 안내] 공유"]}, d0, d1)
        self.assertEqual(subj[3], "2")                               # 제목 속 낱말은 표시 상태가 아니다


class PrivateOffhours(unittest.TestCase):
    def test_own_evening_reply_kept_received_dropped(self):
        """21시 본인 팀즈 '네 ㅎㅎ' 는 '팀즈(발신)' 으로 남고, 같은 글이 받은 글이면 지금처럼 사적 제외(퇴근 후 +1점)."""
        with _Data() as D:
            D.teams([["2026-10-05 21:00", "나", "갑돌", "sent", "", "네 ㅎㅎ", "minute"],
                     ["2026-10-05 21:05", "갑돌", "갑돌", "msg", "", "네 ㅎㅎ", "minute"]])
            with contextlib.redirect_stdout(io.StringIO()):
                sig, meta = extract.load_signals(D.dir, date(2026, 10, 1), date(2026, 10, 7), [], {"owner": "홍길동"})
        self.assertEqual([(s[0], s[1]) for s in sig], [(datetime(2026, 10, 5, 21, 0), "팀즈(발신)")])
        self.assertEqual(meta["excluded"].get("사적 대화(제외)"), 1)
        self.assertEqual(privacy.private_score("네 ㅎㅎ", None, True), "private")

    def test_logon_display_name_is_self(self):
        with _Data() as D, mock.patch.object(extract, "_logon_display_name", lambda: "홍길동"):
            names = extract._self_names(D.dir, {}, file_rows=[])
        self.assertIn("홍길동", names)
        with mock.patch.object(tw, "logon_display_name", lambda: "홍길동"):
            self.assertIn("홍길동", tw.self_names({}))


# ════════════════════════════════ Outlook 웹 ════════════════════════════════
class OwaRatchet(unittest.TestCase):
    def test_merge_keeps_minute_precision(self):
        old = [["sent", "2026-03-06 15:20", "나", "보고", "보고", "", "minute"],
               ["sent", "2026-03-06 09:10", "나", "보고", "보고", "", "minute"],
               ["sent", "2026-03-07 11:00", "나", "회의록", "회의록", "", "minute"]]     # 03-07 은 이번에 검증 안 함
        new = [["sent", "2026-03-06 12:00", "나", "보고", "보고", "", "date"],
               ["sent", "2026-03-06 12:00", "나", "보고", "보고", "", "date"],
               ["sent", "2026-03-07 12:00", "나", "회의록", "회의록", "", "date"]]
        out = op.merge_slices(old, new, {"mail_out": [("2026-03-06", "2026-03-06")]}, "mail")
        self.assertEqual([(r[1], r[6]) for r in out], [("2026-03-06 09:10", "minute"), ("2026-03-06 15:20", "minute"),
                                                       ("2026-03-07 11:00", "minute")])

    def test_recover_from_known_without_opening(self):
        sent = [fb.msg("c", datetime(2026, 3, 20, 17, 3), "나", "회신", open=["2026-03-20 (금) 오후 5:03"])]
        d0, d1 = date(2026, 3, 1), date(2026, 3, 31)
        with tempfile.TemporaryDirectory(prefix="lm28_p14_") as tmp:
            p = os.path.join(tmp, "mail_owa.csv")
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write(owa.MAIL_HDR + "\nsent,2026-03-20 17:03,나,회신,회신,,minute\n")
            known = owa.known_times(p, True)
        self.assertEqual(known, {("sent", "2026-03-20", "나", "회신"): ["17:03"]})
        br = fb.FakeBrowser(TODAY, mail={"inbox": [], "sent": sent})
        run = owa.Run(d0, d1, today=TODAY, recover_max=5)
        run.known = known
        rows, _st, diag, _ds = owa.collect_mail(br, d0, d1, run=run)
        self.assertEqual(br.calls["open"], 0)                         # 열지 않았다(예산 소모 없음)
        self.assertEqual((run.c["recovered_known"], run.c["recovered"], diag["date_only"]), (1, 1, 0))
        self.assertIn("2026-03-20 17:03", {r[1] for r in rows})
        self.assertEqual(owa.COLLECTOR_VER, "LM28-OWA-4")

    def test_avatar_initials_skipped(self):
        it = {"label": "", "texts": ["JS", "John Smith", "Weekly report", "화 오후 3:12"]}
        r = owa.parse_mail_item(it, date(2026, 10, 1), date(2026, 10, 7), "inbox", TODAY, {})
        self.assertEqual((r[1], r[2], r[3]), ("2026-10-06 15:12", "John Smith", "Weekly report"))
        self.assertIn('[class*="vatar"]', owa.JS_MAIL)                # 화면 쪽도 아바타 칸의 잎 글을 빼고 낸다


# ════════════════════════════════ 팀즈 웹 ════════════════════════════════
class _NoneMine(ft.FakeTeams):
    """본문에 '[?]' 가 든 메시지는 화면이 내 것/남의 것을 말하지 않는다(mine None)."""

    def _msgs(self, js=""):
        out = super()._msgs(js)
        for it in out.get("items") or []:
            if it.get("t") == "msg" and "[?]" in str(it.get("body")):
                it["mine"] = None
        return out


class TeamsWeb(unittest.TestCase):
    def test_stamp_date_only(self):
        d0, d1 = date(2026, 6, 1), date(2026, 6, 30)
        self.assertEqual(tw.stamp(["2026년 6월 3일"], ["홍길동 오후 3:24"], None, d0, d1, TODAY),
                         (datetime(2026, 6, 3, 15, 24), "full"))
        self.assertEqual(tw.stamp(["2026년 6월 3일"], ["본문만 있습니다"], None, d0, d1, TODAY),
                         (datetime(2026, 6, 3, 12, 0), "date"))                  # 정오는 자리표(날짜만)
        self.assertEqual(tw.stamp([""], ["본문만 있습니다"], date(2026, 6, 4), d0, d1, TODAY),
                         (datetime(2026, 6, 4, 12, 0), "date"))                  # 구분선 날짜 — 버리지 않는다
        self.assertEqual(tw.stamp([""], ["본문만 있습니다"], None, d0, d1, TODAY), (None, "시각 없음"))

    def test_mine_counters_and_census(self):
        t = datetime(2026, 9, 30, 9, 0)
        msgs = [ft.msg(t, "갑돌", "첫 번째 요청 드립니다"), ft.msg(t + timedelta(minutes=2), "갑돌", "[?] 이어서 확인 부탁"),
                ft.msg(t + timedelta(minutes=5), "나", "확인했습니다 진행할게요", mine=True)]
        br = _NoneMine(TODAY, [ft.room("묶음방", msgs, key="19:grp")])
        with tempfile.TemporaryDirectory(prefix="lm28_p14_") as tmp:
            run = tw.Run(date(2026, 9, 1), TODAY, TODAY)
            store = tw.Store(os.path.join(tmp, "teams_web.csv"))
            with mock.patch.object(tw, "_mono", br.mono), mock.patch.object(tw, "_sleep", br.sleep):
                tw.collect(br, run, {}, store)
            with open(os.path.join(tmp, "teams_web.csv"), encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        c = run.c
        self.assertEqual((c["rows_read"], c["rows_sent"], c["mine_t"], c["mine_f"], c["mine_n"], c["au_inherit"]),
                         (3, 1, 1, 1, 1, 1))
        self.assertIn("내 메시지 1/3 · 판정불가 1 · 이어받음 1", tw.census_line(run))
        self.assertEqual(rows[0]["time_precision"], "minute")
        self.assertEqual(tw.COLLECTOR_VER, "LM28-TW-3")
        # 화면 쪽: 조상 표지(대화 칸 안쪽·다른 메시지를 품지 않은 조상)와 위치 규칙을 비GEN 경로에서도 본다
        self.assertIn("const myA = e.closest(MYQ);", tw.JS_MSGS)
        self.assertIn("!els.some(o => o !== e && myA.contains(o))", tw.JS_MSGS)

    def test_store_fixes_old_rows_in_place(self):
        """지난 판 행 바로잡기 — 남의 말로 적힌 내 메시지는 내 발신으로, 날짜만 행은 분 단위로(행은 늘지 않는다). 분 단위가 이미
        있으면 날짜만 사본은 적지 않는다."""
        with tempfile.TemporaryDirectory(prefix="lm28_p14_") as tmp:
            p = os.path.join(tmp, "teams_web.csv")
            _csv(p, TEAMS_HDR, [["2026-09-30 09:05", "갑돌", "묶음방", "msg", "", "확인했습니다 진행할게요", ""],
                                ["2026-09-30 12:00", "나", "묶음방", "sent", "", "날짜만 남은 글입니다", "date"],
                                ["2026-09-29 10:00", "나", "묶음방", "sent", "", "분 단위 글입니다", "minute"]])
            st = tw.Store(p)
            added, dup = st.add([
                {"time": "2026-09-30 09:05", "from": "나", "chat": "묶음방", "kind": "sent", "summary": "확인했습니다 진행할게요"},
                {"time": "2026-09-30 14:10", "from": "나", "chat": "묶음방", "kind": "sent", "summary": "날짜만 남은 글입니다"},
                {"time": "2026-09-29 12:00", "from": "나", "chat": "묶음방", "kind": "sent", "summary": "분 단위 글입니다",
                 "prec": "date"}])
            self.assertEqual((added, dup, st.mine_fixed, st.prec_up, st.dirty), (0, 0, 1, 1, True))
            self.assertEqual(st.flush(), 3)
            with open(p, encoding="utf-8-sig", newline="") as f:
                rows = sorted((r["time"], r["from"], r["kind"], r["time_precision"]) for r in csv.DictReader(f))
        self.assertEqual(rows, [("2026-09-29 10:00", "나", "sent", "minute"), ("2026-09-30 09:05", "나", "sent", "minute"),
                                ("2026-09-30 14:10", "나", "sent", "minute")])


class MineSummary(unittest.TestCase):
    def test_mine_prints_e_summary(self):
        src = _boot.read_text(os.path.join(_boot.ROOT, "mine.py"))
        for frag in ("퇴근 후 미인정", "시각 미상 발신", "표준일 추정", "AI 비업무 발신 시간 유지"):
            self.assertIn(frag, src)


if __name__ == "__main__":
    unittest.main()
