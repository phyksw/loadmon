# -*- coding: utf-8 -*-
r"""tests\test_p15_ui_reports.py — 화면(ui\app.py)·리포트(report_out.py)가 다섯 이슈(A~E)의 새 데이터를 그대로 말하는가.

  A  판정 기록(ai_judgments)의 중단 갈래·채움·규칙 행·재사용 → 배너 재료(_judged_info)와 갈래별 문구
  B  부분 판정 배너 — '규칙이 임시로 뽑은 토큰' 문구 폐기(규칙은 기존 과제·공통에 임시 배정)
  C  월별 코멘트 — /api/extra·리포트 5절 = core/narratives.load_merged(기간 필터) · [리셋](분석 결과만)은 코멘트 보존 ·
     [리뷰 코멘트 재생성]의 '모든 달' 선택(--all)
  D  Agentic 정제본↔원본 전환 안내(근거 키면 생략) · 워크플로우 상태 파일 사유 · 중단 갈래(throttle·gate)
  E  리포트 날짜표 최신순·0h 날·'퇴근 후·시각' 열·합계 줄 · 팀즈 날짜만 행의 12:00 자리표

화면 서버는 이 프로세스 안의 임시 포트로만 띄운다(ThreadingHTTPServer — 새 프로세스 없음). report\·data\ 는 임시 폴더로
바꿔 끼운다(app.REPORT·app.DATA·report_out.REP) — 실제 폴더를 읽거나 지우지 않는다. 이름은 합성(홍길동·김철수·Alpha-X)."""
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import _boot  # noqa: F401

import app  # noqa: E402  — ui\app.py (_boot 가 ui\ 를 sys.path 에 넣는다 · 임포트 부작용 없음)
import narratives  # noqa: E402
import report_out  # noqa: E402

TAG = "20260101-20261012"
TAG_Y = "20260101-20261011"          # 어제 기간 — 기본 기간 '올해' 는 tag 가 날마다 바뀐다
TAG_25 = "20250101-20251231"


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, ensure_ascii=False)


def _nar(summary, **kw):
    return dict({"summary": summary, "projects": [{"name": "Alpha-X", "story": "시험 진행", "worktypes": "개발"}]}, **kw)


class _Srv:
    """app.H 를 임시 포트에 띄운다(같은 프로세스의 스레드 — 새 프로세스 없음)."""

    def __init__(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            data = None if body is None else json.dumps(body).encode("utf-8")
            c.request(method, path, body=data, headers=({"Content-Type": "application/json"} if data else {}))
            r = c.getresponse()
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
        finally:
            c.close()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_p15_")
        self.rep = os.path.join(self._td.name, "report")
        self.data = os.path.join(self._td.name, "data")
        os.makedirs(self.rep)
        os.makedirs(self.data)
        self._pt = [mock.patch.object(app, "REPORT", self.rep), mock.patch.object(app, "DATA", self.data),
                    mock.patch.object(report_out, "REP", self.rep)]
        for p in self._pt:
            p.start()
        app.JOB.update(running=False, step="", pid=0)
        self.srv = None

    def tearDown(self):
        if self.srv:
            self.srv.close()
        for p in reversed(self._pt):
            p.stop()
        app.JOB.update(running=False, step="", pid=0)
        self._td.cleanup()

    def serve(self):
        self.srv = _Srv()
        return self.srv

    def signals(self, judged=True):
        """signals_<TAG>.csv — 화면의 기간 앵커(latest_signals). judged=False 면 규칙 축(재추출)."""
        _w(os.path.join(self.rep, f"signals_{TAG}.csv"),
           "time,source,who,project,activity,weight,text" + (",model,worktype,detail,judge" if judged else "") + "\n")


# ── C: 월별 코멘트 ───────────────────────────────────────────────────────────────────────────
class ExtraNarratives(_Base):
    """/api/extra 의 월별 코멘트 = narratives.load_merged(기간 필터) — 기간 밖 달 없음 · 이월한 달은 from_tag."""

    def _files(self, own=True):
        if own:
            _w(narratives.path_of(self.rep, TAG), {"2026-10": _nar("10월 코멘트", n=30, n_ai=25, made="2026-10-12 09:00")})
        _w(narratives.path_of(self.rep, TAG_Y), {f"2026-{m:02d}": _nar(f"{m}월 코멘트") for m in range(1, 10)})
        _w(narratives.path_of(self.rep, TAG_25), {"2025-12": _nar("작년 12월 코멘트")})
        now = time.time()
        os.utime(narratives.path_of(self.rep, TAG_25), (now - 86400 * 30, now - 86400 * 30))
        os.utime(narratives.path_of(self.rep, TAG_Y), (now - 86400, now - 86400))
        self.signals()

    def test_extra_equals_load_merged(self):
        self._files()
        st, out = self.serve().req("GET", "/api/extra")
        self.assertEqual(st, 200)
        nv = out.get("narratives") or {}
        self.assertEqual(sorted(nv), [f"2026-{m:02d}" for m in range(1, 11)])          # 2025-12(기간 밖) 없음
        self.assertEqual(nv, narratives.load_merged(self.rep, TAG, months=narratives.period_months(TAG)))
        self.assertEqual(nv["2026-03"]["from_tag"], TAG_Y)
        self.assertNotIn("from_tag", nv["2026-10"])
        self.assertNotIn("narratives_alt_tag", out)                                     # 자기 달이 있으면 대체 표시 없음

    def test_extra_all_carried(self):
        self._files(own=False)
        _st, out = self.serve().req("GET", "/api/extra")
        self.assertEqual(len(out.get("narratives") or {}), 9)
        self.assertEqual(out.get("narratives_alt_tag"), TAG_Y)


class ResetKeepsNarratives(_Base):
    """'분석 결과만 삭제' 는 report 최상위 ai_narratives_*.json 을 남기고, '모두 삭제' 는 지운다(업로드 대기 묶음은 늘 보존)."""

    def _seed(self):
        _w(narratives.path_of(self.rep, TAG), {"2026-10": _nar("10월")})
        _w(os.path.join(self.rep, f"mm_meta_{TAG}.json"), {})
        _w(os.path.join(self.rep, "sub", f"ai_narratives_{TAG}.json"), {})          # 하위 폴더 사본은 보존 대상 아님
        _w(os.path.join(self.rep, "upload_pending", "pack.zip"), "x")
        _w(os.path.join(self.data, "outlook", "mail.csv"), "time\n")

    def test_report_only(self):
        self._seed()
        self.assertEqual(app.reset_files("report", report=self.rep, data=self.data), (2, 1))
        self.assertTrue(os.path.exists(narratives.path_of(self.rep, TAG)))
        self.assertTrue(os.path.exists(os.path.join(self.rep, "upload_pending", "pack.zip")))
        self.assertTrue(os.path.exists(os.path.join(self.data, "outlook", "mail.csv")))

    def test_all(self):
        self._seed()
        self.assertEqual(app.reset_files("all", report=self.rep, data=self.data), (4, 0))
        self.assertFalse(os.path.exists(narratives.path_of(self.rep, TAG)))
        self.assertTrue(os.path.exists(os.path.join(self.rep, "upload_pending", "pack.zip")))

    def test_judge_cache_kept_on_report_only(self):
        cache = os.path.join(self.rep, "judge_cache.json")
        _w(cache, {"v": 1, "items": {}})
        _w(os.path.join(self.rep, f"mm_meta_{TAG}.json"), {})
        self.assertEqual(app.reset_files("report", report=self.rep, data=self.data), (1, 0))
        self.assertTrue(os.path.exists(cache))                                        # 이어서 판정 기록은 보존
        self.assertEqual(app.reset_files("all", report=self.rep, data=self.data), (1, 0))
        self.assertFalse(os.path.exists(cache))

    def test_http_reset_report(self):
        self._seed()
        self.assertEqual((app.REPORT, app.DATA), (self.rep, self.data))              # 실제 폴더를 지우지 않게
        st, out = self.serve().req("POST", "/api/reset", {"what": "report"})
        self.assertEqual(st, 200)
        self.assertEqual((out.get("removed"), out.get("kept_narratives")), (2, 1))
        self.assertTrue(os.path.exists(narratives.path_of(self.rep, TAG)))
        self.assertTrue(any("월별 리뷰 코멘트 1개 파일은 보존" in ln for ln in app.JOB["log"]))
        self.assertFalse(app.JOB["running"])


class NarrateButton(_Base):
    """[리뷰 코멘트 재생성] — 본문 {all} 이 narrate_job(all) 로 · --all 은 명령 끝에."""

    def test_cmd(self):
        self.assertEqual(app.narrate_cmd(TAG, True)[-6:],
                         ["--from", "2026-01-01", "--to", "2026-10-12", "--narrate-only", "--all"])
        self.assertEqual(app.narrate_cmd(TAG)[-1], "--narrate-only")

    def test_post_passes_all(self):
        got, done = [], threading.Event()

        def fake(all_months=False):
            got.append(all_months)
            with app.LOCK:
                app.JOB.update(running=False, step="")
            done.set()

        srv = self.serve()
        with mock.patch.object(app, "narrate_job", fake):
            for body, want in (({"all": True}, True), (None, False), ({"all": False}, False)):
                done.clear()
                st, out = srv.req("POST", "/api/narrate", body)
                self.assertEqual(st, 200)
                self.assertTrue(done.wait(10))
                self.assertEqual((got[-1], out.get("all")), (want, want))
        self.assertIn("JSON.stringify({all})", app.PAGE)


class ReportNarratives(_Base):
    """리포트 5절은 이월한 달까지(이전 분석 코멘트 표시) · 기간 밖 달 없음 — D: Agentic 판정 대기 MM · 체계 폴백 표시."""

    def test_build(self):
        _w(os.path.join(self.rep, f"mm_meta_{TAG}.json"),
           {"period": ["2026-01-01", "2026-10-12"], "total_mm": 1.0, "avail_mm": 2.0, "mm_basis": {}})
        _w(narratives.path_of(self.rep, TAG), {"2026-10": _nar("10월 코멘트")})
        _w(narratives.path_of(self.rep, TAG_Y), {"2026-03": _nar("3월 코멘트"), "2026-04": _nar("4월 코멘트", earlier=True)})
        _w(narratives.path_of(self.rep, TAG_25), {"2025-12": _nar("작년 12월 코멘트")})
        _w(os.path.join(self.rep, f"agentic_{TAG}.json"), {"match": [], "mm_recalc": {"rule_rows": 3, "rule_mm": 0.42}})
        _w(os.path.join(self.rep, f"entities_{TAG}.json"),
           {"fallback": True, "models": [{"name": "Alpha-X", "l1": "개발", "match": ["alpha"]}, {"name": "공통"}]})
        with mock.patch.object(report_out, "_privacy_ctx", lambda: None):
            doc = report_out.build(TAG)
        self.assertIn("5. 월별 리뷰 코멘트", doc)
        for s in ("10월 코멘트", "3월 코멘트", "4월 코멘트"):
            self.assertIn(s, doc)
        self.assertNotIn("작년 12월 코멘트", doc)
        i3, i10 = doc.index(">2026-03"), doc.index(">2026-10")
        self.assertIn("(이전 분석 코멘트)", doc[i3:i3 + 60])
        self.assertNotIn("(이전 분석 코멘트)", doc[i10:i10 + 40])
        self.assertIn("AI 판정 대기 3행 · 0.42 MM", doc)
        self.assertIn("규칙 폴백 체계(임시)", doc)
        self.assertIn("<th>과제</th><th>업무 영역</th>", doc)


# ── A·B: 판정 기록 → 배너 ─────────────────────────────────────────────────────────────────────
class JudgedIssues(_Base):
    def test_new_keys_pass_through(self):
        self.signals()
        _w(os.path.join(self.rep, f"ai_judgments_{TAG}.json"),
           {"judged": 120, "total": 200, "failed_rows": 30, "partial_chunks": 1, "aborted": True,
            "abort_kind": "throttle", "abort_reason": "Copilot 사용량 제한(일시)", "unseen_rows": 50,
            "filled_rows": {"same": 5, "conv": 3, "token": 2, "sim": 10}, "rule_rows": 30, "cache_reused": 40,
            "group_rows": 25, "reps": 60, "lowinfo_rows": 12, "cooldowns": 3, "model_fallback": "자동", "items": {}})
        ok, n, total, iss = app._judged_info(TAG)
        self.assertTrue(ok)
        self.assertEqual((n, total), (120, 200))
        self.assertEqual((iss["abort_kind"], iss["abort_reason"]), ("throttle", "Copilot 사용량 제한(일시)"))
        self.assertEqual(iss["filled_rows"], 20)
        self.assertEqual(iss["filled_by"], {"same": 5, "conv": 3, "token": 2, "sim": 10})
        for k, v in (("unseen_rows", 50), ("rule_rows", 30), ("cache_reused", 40), ("group_rows", 25), ("reps", 60),
                     ("lowinfo_rows", 12), ("cooldowns", 3), ("failed_rows", 30), ("partial_chunks", 1)):
            self.assertEqual(iss[k], v, k)
        self.assertEqual(iss["model_fallback"], "자동")
        self.assertTrue(iss["aborted"])

    def test_old_file_keeps_old_keys_only(self):
        self.signals()
        _w(os.path.join(self.rep, f"ai_judgments_{TAG}.json"), {"judged": 5, "total": 9, "failed_rows": 4, "aborted": False})
        self.assertEqual(app._judged_info(TAG)[3], {"failed_rows": 4, "aborted": False})

    def test_banner_wording(self):
        page = app.PAGE
        for s in ("Copilot 사용량 제한으로 중단", "Copilot 로그인 만료로 중단", "사람이 손대야 풀리는 상태로 중단", "시간 예산 도달",
                  "AI가 직접 못 본 행", "규칙으로 기존 과제(또는 공통)에 임시 배정", "비슷한 AI 판정(AI(유사))",
                  "1~2시간 뒤 [재분석만]+AI 정제", "지난 실행 재사용"):
            self.assertIn(s, page, s)
        self.assertNotIn("실패한 행은 규칙이 임시로 뽑은 토큰으로 남아 있습니다", page)


# ── D: Agentic·워크플로우 ─────────────────────────────────────────────────────────────────────
class AgenticStale(_Base):
    """근거 키(match[].keys)로 센 결과(axis plain)는 정제본↔원본 전환에 '정제본 무효화' 안내를 띄우지 않는다."""

    def _a(self, keyed):
        m = {"task": "AL1", "fit": 70, "work": ["Alpha-X / 시험"]}
        if keyed:
            m["keys"] = ["Alpha-X␟시험"]
        return {"rows_file": f"mm_rows_{TAG}_refined.csv", "match": [m],
                "mm_recalc": {"axis": "plain" if keyed else "rows", "rows_file": f"mm_rows_{TAG}.csv"}}

    def test_keyed_plain_no_note(self):
        self.signals()
        ap = os.path.join(self.rep, f"agentic_{TAG}.json")
        with mock.patch.object(app, "agentic_recalc", lambda tag="": False):
            out = {}
            app._agentic_stale(self._a(True), TAG, ap, out)
            self.assertNotIn("reextracted", out)
            out2 = {}
            app._agentic_stale(self._a(False), TAG, ap, out2)
        self.assertTrue(out2.get("reextracted"))
        self.assertEqual(out2.get("reextracted_title"), "정제본 무효화 이후 결과")

    def test_reextracted_still_noted(self):
        self.signals(judged=False)                       # signals 가 규칙 축 — 판정 뒤 재추출
        out = {}
        with mock.patch.object(app, "agentic_recalc", lambda tag="": False):
            app._agentic_stale(self._a(True), TAG, os.path.join(self.rep, f"agentic_{TAG}.json"), out)
        self.assertEqual(out.get("reextracted_title"), "재추출 이후 결과")


class WorkflowStage(_Base):
    """결과가 없으면 상태 파일의 중단 사유(빨간 줄 재료)와 갈래를 싣는다 · 새 stop.kind 의 갈래."""

    def _state(self, stage, kind, reason="", err="", hint="", state="failed"):
        _w(os.path.join(self.rep, f"stage_state_{TAG}_{stage}.json"),
           {"schema": 1, "stage": stage, "tag": TAG, "state": state, "updated": time.time(),
            "stop": {"kind": kind, "reason": reason}, "error": ({"error": err, "hint": hint} if err else {})})

    def test_no_file_reason(self):
        self.signals()
        self._state("flow", "throttle", "Copilot 사용량 제한 — 남은 묶음 보내지 않음", "Copilot 사용량 제한(일시)", "1~2시간 뒤")
        _st, out = self.serve().req("GET", "/api/workflow")
        self.assertEqual(out.get("stage_stop_kind"), "throttle")
        self.assertEqual(out.get("stage_kind"), "throttle")
        self.assertEqual(out.get("stage_reason"), "Copilot 사용량 제한 — 남은 묶음 보내지 않음")
        self.assertEqual(out.get("stage_error"), "Copilot 사용량 제한(일시) — 1~2시간 뒤")

    def test_flows_present_no_reason(self):
        self.signals()
        self._state("flow", "fail", "왕복 실패")
        _w(os.path.join(self.rep, f"workflow_{TAG}.json"),
           {"ok": True, "flows": [{"model": "Alpha-X / 시험", "steps": []}], "carried_from": TAG_Y, "carried": 1})
        _st, out = self.serve().req("GET", "/api/workflow")
        self.assertNotIn("stage_reason", out)
        self.assertEqual(out.get("carried_from"), TAG_Y)

    def test_stage_kind_map(self):
        for kind, want in (("throttle", "throttle"), ("gate", "gate"), ("fail", "failed"), ("gain", "failed"),
                           ("budget", "budget"), ("login", "failed"), ("stall", "stalled")):
            self._state("agentic", kind, state="partial")
            self.assertEqual(app._stage_kind("Agentic 매칭", TAG), want, kind)


# ── E: 날짜표·합계·팀즈 날짜만 ────────────────────────────────────────────────────────────────
DB = {
    "2026-10-05": {"h": 0.0, "tags": {}, "pc": {"on": 0.0, "night": 0.0, "always_on": False, "rec": "none"}},
    "2026-10-06": {"h": 0.0, "tags": {}, "pc": {"on": 3.2, "night": 3.2, "always_on": False, "rec": "event"},
                   "ev": {"pc_after_h": 3.2, "act_after": 0, "pas_after": 7, "credit_h": 0.0, "why": "no_active_after"}},
    "2026-10-07": {"h": 8.0, "tags": {"regular": 8.0}, "pc": {"on": 0.0, "night": 0.0, "always_on": False, "rec": "none"},
                   "floor": {"kind": "std_nopc", "est": True, "add_h": 6.0, "open": ["메일(발신)"]},
                   "untimed": {"n": 3, "credit_min": 0}},
    "2026-10-08": {"h": 2.5, "tags": {"regular": 2.0, "extended": 0.5}, "floor": {"kind": "trace_hint", "add_h": 1.0},
                   "pc": {"on": 1.0, "night": 0.0, "always_on": False, "rec": "hint"},
                   "ev": {"pc_after_h": 0.0, "act_after": 2, "pas_after": 0, "credit_h": 0.0, "why": "no_pc_after"},
                   "ai_n_kept": 2},
    "2026-10-09": {"h": 9.5, "tags": {"regular": 8.0, "extended": 1.5}, "evening": [["19:00", "20:30"]], "absent": 0.5,
                   "floor": {"kind": "untimed", "add_h": 0.33, "open": ["메일(발신·일자)"]},
                   "untimed": {"n": 1, "credit_min": 20},
                   "ev": {"pc_after_h": 1.5, "act_after": 3, "pas_after": 1, "credit_h": 1.5, "why": "credited"}},
}


class FloorTable(unittest.TestCase):
    def test_rows(self):
        rows = report_out.floor_day_rows(DB)
        self.assertEqual([r["date"] for r in rows], sorted(DB, reverse=True))          # 최신순
        by = {r["date"]: r for r in rows}
        self.assertEqual(by["2026-10-05"]["method"], "기록 없음")
        self.assertEqual(by["2026-10-06"]["method"], "흔적 없음")
        self.assertEqual(by["2026-10-06"]["after"], "PC 19:00 이후 3.2h · 내 흔적 0 · 받은 7 → 미인정")
        self.assertEqual(by["2026-10-07"]["method"], "표준일 추정(PC 기록 없는 달)")
        self.assertIn("날짜만 아는 발신 3통(하한에 포함)", by["2026-10-07"]["after"])
        self.assertEqual(by["2026-10-08"]["method"], "흔적 창(브라우저 사용)")
        for s in ("내 흔적 2건 · 퇴근 후 PC 기록 없음(발신 세션만)", "AI 비업무 발신 2건 시간 유지", "브라우저 기록만"):
            self.assertIn(s, by["2026-10-08"]["after"])
        self.assertEqual(by["2026-10-09"]["method"], "시각 미상 발신")
        for s in ("퇴근 후 1.5h 인정", "날짜만 아는 발신 1통(20분 인정)", "부재 0.5일"):
            self.assertIn(s, by["2026-10-09"]["after"])
        self.assertEqual([r["date"] for r in report_out.floor_day_rows(DB, limit=2)], ["2026-10-09", "2026-10-08"])
        self.assertIn("PC 18:00 이후", report_out.floor_day_rows(DB, edge="18:00")[3]["after"])
        self.assertEqual(report_out.day_method({"h": 4, "floor": {"kind": "window", "est": True}}),
                         "PC 하한(가동 창 − 절전 공백) · 표준일 추정")

    def test_section(self):
        b = {"day_basis": DB, "cfg_used": {"pcFloorWindow": ["08:00", "19:00"], "noPcMonthDay": "standard"},
             "evening_missed_days": 2, "evening_missed_pc_h": 4.5, "untimed_sends": 4, "untimed_credit_h": 0.33,
             "std_nopc_days": 1, "std_nopc_h": 6.0, "hint_only_days": 1}
        doc = "\n".join(report_out.floor_section({"ai_n_time_kept": 2}, b, max_rows=3))
        for s in ("<th>퇴근 후·시각</th>", "시간 근거 합계", "퇴근 후 미인정 2일·PC 4.5h", "시각 미상 발신 4통(0.3h 인정)",
                  "표준일 추정 1일(+6.0h — PC 기록 없는 달)", "브라우저 기록만 있는 평일 1일", "AI 비업무 발신 시간 유지 2건",
                  "최근 3일만 표시"):
            self.assertIn(s, doc, s)
        self.assertLess(doc.index("<td>2026-10-09</td>"), doc.index("<td>2026-10-08</td>"))
        self.assertNotIn("<td>2026-10-06</td>", doc)                                     # 최근 3일만
        self.assertEqual(report_out.time_basis_line({}, {}), "")

    def test_peers_skip_date_only_teams(self):
        rows = [{"source": "팀즈(수신·일자)", "who": "홍길동", "weight": "1"},
                {"source": "팀즈(수신)", "who": "김철수", "weight": "1"}]
        self.assertEqual([a["key"] for a in report_out.peers(rows)], ["김철수"])


class TeamsDateOnly(_Base):
    """데이터 보기에서 팀즈 날짜만 행(time_precision=date)의 12:00 자리표를 시각으로 보이지 않는다."""

    def test_data_view(self):
        _w(os.path.join(self.data, "m365", "teams_web.csv"),
           "time,from,chat,kind,replied_time,summary,time_precision\n"
           "2026-10-01 12:00,홍길동,프로젝트A,recv,,일정 공유,date\n"
           "2026-10-02 09:13,김철수,프로젝트A,recv,,시험 결과,minute\n")
        _st, out = self.serve().req("GET", "/api/data?src=teams")
        self.assertEqual(sorted(r["time"] for r in out["rows"]), ["2026-10-01", "2026-10-02 09:13"])


class PageWiring(unittest.TestCase):
    """C·D·E — 화면 스크립트에 새 재료를 그리는 자리가 있다(문법은 tools\\check_page_js.py 가 본다)."""

    def test_page(self):
        p = app.PAGE
        for s in ("loadReview(curTab)", "curTab=id", "이전 실행 코멘트", "빠진 달·최근 달·데이터가 바뀐 달을 다시 만듭니다",
                  "⑤ 그 달은 AI 판정된 신호가 적어", "월별 리뷰 코멘트·AI 판정 기록은 보존", "AI 판정 대기", "개인정보 관문", "과제와 무관",
                  "기간 결과를 이어받음", "최근 실행이 남긴 사유", "퇴근 후 미인정", "시각 미상 발신", "표준일 추정(기본)",
                  "AI 비업무 발신 시간 유지", "Copilot 대기 중", "규칙 폴백 체계(임시)", "지난 체계 재사용",
                  "Copilot 사용량 제한</b>으로 멈췄습니다"):
            self.assertIn(s, p, s)
        self.assertNotIn("상한을 올리거나 [재매칭]으로 다시 물으면 늘어납니다", p)
        self.assertNotIn("이 달만 다시 만듭니다", p)


if __name__ == "__main__":
    unittest.main()
