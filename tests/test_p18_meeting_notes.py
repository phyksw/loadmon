# -*- coding: utf-8 -*-
r"""tests\test_p18_meeting_notes.py — 일정 본문(회의 안건)을 걸러서 AI 판정에 참고(LM28 — '일정 회의 내용도 참고, 물론 필터링').

  · clean_body : Teams(한·영 · 옛·새 판 · COM 이 한 줄로 편 본문 · 구분선 없음)·Zoom·Webex·Meet 안내문 · URL·이메일·전화/회의 번호·
                 긴 숫자 · 전달 머리(보낸 사람:/From: … 보낸 날짜:/Sent:)·인용 꼬리 · 회의 암호 · 참석자 목록 · 맺음말 이름 ·
                 녹화 안내 · 세로줄 꼬리 · 경계 자르기(토큰을 자르지 않음) · 멱등(G1 재실행에도 그대로)
  · load_notes : 종일·취소·거절·한가함·미정(설정)·부재중·근태·비업무·제외어(제목·본문)·비공개·자격증명·사적 본문 제외 · 기간 ·
                 추가PC · body 열 없는 옛 파일 · bodyToAI=false · noteMaxChars · 키가 실제 회의 신호(extract)와 맞는다
  · judge      : 회의 줄에만 ' — 안건:'(같은 시각·제목의 메일 행에는 없음) · 안건이 G3(카나리아)에 걸리면 안건만 빠지고 회의는 간다 ·
                 캐시 내용 키 — 안건이 생긴 회의만 한 번 다시 묻고 나머지 캐시는 그대로 · 같은 내용 묶음은 안건까지 같아야 ·
                 signals 열 불변·signals·캐시·판정 기록에 안건 원문 없음(팀 반출 불변)
  · mailmerge  : calendar.csv 끝 열 body · 접히는 출처의 본문을 받는다 · body 열 없는 옛 출처 파일
  · run.g1_mail: 본문 정리 + 정제 · 회의 암호·자격증명 본문 때문에 회의 행이 버려지지 않음 · 접히는 웹 행의 본문을 남는 행으로 ·
                 body 열 없는 파일 그대로 · 두 번 돌려도 같다
  · PowerShell(run_tests.py p18 --ps-only=CalBody): Get-CalBody(보호 멤버·비공개·예외·자르기) · 수집기 body 열·cal_body·일정 달만 다시 읽기
가명만 쓴다(홍길동·김철수·이영희·프로젝트A). 실제 Copilot·Edge·Outlook 은 쓰지 않는다. 임시 파일은 TemporaryDirectory 안에만.
"""
import contextlib
import csv
import inspect
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

import _boot
import copilot_auto as ca  # noqa: E402
import extract  # noqa: E402
import judge  # noqa: E402
import mailmerge  # noqa: E402
import meetnote  # noqa: E402
import privacy  # noqa: E402
import stage_state  # noqa: E402

import run as R  # noqa: E402 - _boot 이 ROOT 를 sys.path 에 넣는다

CANARY = "zzcanaryzz"                 # 시험용 카나리아(실재하지 않는 값)
TAG = "20260101-20261012"
SIG_COLS = ["time", "source", "who", "project", "activity", "weight", "text", "flag"]
CAL_H = mailmerge.CAL_COLS + [mailmerge.SRC_COL, mailmerge.CAL_BODY]

TEAMS_KR = ("시험 결과 검토 및 일정 협의\r\n"
            "________________________________________________________________________________\r\n"
            "Microsoft Teams 도움이 필요하세요?<https://aka.ms/JoinTeamsMeeting?omkt=ko-KR>\r\n"
            "지금 모임에 참가<https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZmQ3YjA1%40thread.v2/0?context=%7b%22Tid%22%7d>\r\n"
            "모임 ID: 123 456 789 012\r\n"
            "암호: Ab3xYz\r\n"
            "________________________________\r\n"
            "전화로 참가\r\n"
            "+82 2-1234-5678,,123456789#<tel:+82212345678,,123456789#> 대한민국, 서울\r\n"
            "로컬 번호 찾기<https://dialin.teams.microsoft.com/x>\r\n"
            "전화 회의 ID: 123 456 789#\r\n"
            "이끌이용: 모임 옵션<https://teams.microsoft.com/meetingOptions/x> | 전화 접속 PIN 재설정<https://dialin.teams.microsoft.com/usp>\r\n"
            "________________________________________________________________________________\r\n")
TEAMS_EN = ("Hi all, let's review the DVT test results and finalize the schedule.\n"
            "________________________________________________________________________________\n"
            "Microsoft Teams Need help?<https://aka.ms/JoinTeamsMeeting?omkt=en-US>\n"
            "Join the meeting now<https://teams.microsoft.com/l/meetup-join/19%3ameeting_ABC%40thread.v2/0>\n"
            "Meeting ID: 123 456 789 012\n"
            "Passcode: Ab3xYz\n"
            "________________________________\n"
            "Dial in by phone\n"
            "+1 234-567-8901,,123456789#<tel:+12345678901,,123456789#> United States, Seattle\n"
            "Find a local number<https://dialin.teams.microsoft.com/x>\n"
            "Phone conference ID: 123 456 789#\n"
            "For organizers: Meeting options<https://teams.microsoft.com/meetingOptions/x> | Reset dial-in PIN<https://dialin.x/usp>\n"
            "________________________________________________________________________________\n")
# COM 은 줄바꿈·탭을 공백으로 바꿔 한 줄로 남긴다(옛 판 한글 안내문)
TEAMS_KR_OLD_FLAT = ("안건: 시제품 평가 결과 공유 ________________________________________________________________________________ "
                     "Microsoft Teams 모임 컴퓨터, 모바일 앱 또는 회의실 디바이스에서 참가 여기를 클릭하여 모임에 참가 "
                     "자세한 정보 | 모임 옵션 ________________________________________________________________________________")
TEAMS_NO_SEP = "주간 진행 점검 Microsoft Teams 모임 지금 모임에 참가 모임 ID: 123 456 789 012 암호: Ab3xYz"
ZOOM_KR = ("홍길동님이 귀하를 예약된 Zoom 회의에 초대합니다. 주제: 주간 회의 시간: 2026년 10월 14일 10:00 AM 서울 "
           "Zoom 회의 참가 https://us02web.zoom.us/j/12345678901?pwd=abcDEF123 회의 ID: 123 4567 8901 암호: 123456")
WEBEX = ("Agenda: firmware update review Join Webex meeting https://corp.webex.com/corp/j.php?MTID=m1234 "
         "Meeting number (access code): 123 456 7890 Meeting password: Ab3xYz Join by phone +1-415-655-0001 US Toll")
MEET = "자료 리뷰 Join with Google Meet meet.google.com/abc-defg-hij Join by phone (US) +1 234-567-8901 PIN: 123456789#"
MIXED = ("설계 검토 자료 공유: https://share.example.com/sites/a/b.pptx 담당 hong.gd@corp.example 연락처 010-1234-5678 "
         "/ 일정 2026-10-14 14:00 확정 / 회의실 3층 / 접수 9876543210123")
FWD_EN = ("Please review before the meeting. -----Original Message----- From: Hong Gildong <hong@corp.example> "
          "Sent: Monday, October 13, 2026 10:00 AM To: Team Subject: DVT")
FWD_KR = ("검토 후 의견 주세요 보낸 사람: 홍길동 <hong@corp.example> 보낸 날짜: 2026년 10월 13일 월요일 오전 10:00 "
          "받는 사람: 팀 제목: 결과 공유")
SAMPLES = (TEAMS_KR, TEAMS_EN, TEAMS_KR_OLD_FLAT, TEAMS_NO_SEP, ZOOM_KR, WEBEX, MEET, MIXED, FWD_EN, FWD_KR)


def _write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _cal(start, subject, body="", end=None, all_day="False", busy="2", cats="", resp="3", ms="1", src="com"):
    """merged calendar.csv 한 행(CAL_H 순)."""
    return [start, end or start[:11] + "23:00", all_day, busy, subject, cats, "", resp, ms, src, body]


def _lmstatus(line):
    s = str(line or "")
    return json.loads(s[s.index("{"):]) if s.startswith("LMSTATUS") else {}


# ── 1) clean_body ────────────────────────────────────────────────────────────────
class CleanBody(unittest.TestCase):
    def test_signature_for_web_collector(self):
        """웹 경로(collect\\Get-OutlookWeb.py)가 늦게 임포트하는 계약 — clean_body(text, max_len=600)."""
        p = inspect.signature(meetnote.clean_body).parameters
        self.assertEqual(list(p), ["text", "max_len"])
        self.assertEqual(p["max_len"].default, 600)

    def test_teams_boilerplate(self):
        c = meetnote.clean_body
        self.assertEqual(c(TEAMS_KR), "시험 결과 검토 및 일정 협의")
        self.assertEqual(c(TEAMS_EN), "Hi all, let's review the DVT test results and finalize the schedule.")
        self.assertEqual(c(TEAMS_KR_OLD_FLAT), "안건: 시제품 평가 결과 공유")
        self.assertEqual(c(TEAMS_NO_SEP), "주간 진행 점검")
        # COM 이 줄바꿈을 공백으로 바꾼 같은 본문도 같다
        self.assertEqual(c(re.sub(r"[\r\n]+", " ", TEAMS_KR)), "시험 결과 검토 및 일정 협의")

    def test_other_meeting_tools(self):
        c = meetnote.clean_body
        self.assertEqual(c(ZOOM_KR), "")                                   # 초대 문장의 사람 이름까지
        self.assertEqual(c(WEBEX), "Agenda: firmware update review")
        self.assertEqual(c(MEET), "자료 리뷰")

    def test_links_numbers_kept_dates(self):
        out = meetnote.clean_body(MIXED)
        for bad in ("http", "@", "010", "1234-5678", "9876543210123", "share.example"):
            self.assertNotIn(bad, out)
        for keep in ("설계 검토 자료 공유", "2026-10-14 14:00", "회의실 3층"):
            self.assertIn(keep, out)
        self.assertEqual(meetnote.clean_body("pin: GPIO12 설정 · v1.2.3 릴리스 검토"), "pin: GPIO12 설정 · v1.2.3 릴리스 검토")

    def test_forwarded_and_quoted(self):
        c = meetnote.clean_body
        self.assertEqual(c(FWD_EN), "Please review before the meeting.")
        self.assertEqual(c(FWD_KR), "검토 후 의견 주세요")
        self.assertEqual(c("의견 주세요\n> 이전 글 첫 줄\n> 이전 글 둘째 줄"), "의견 주세요")
        self.assertEqual(c("From: 10:00 To: 11:00 설계 검토"), "From: 10:00 To: 11:00 설계 검토")   # 사람이 쓴 시간표

    def test_passcode_attendees_signoff(self):
        c = meetnote.clean_body
        out = c("자료 확인 암호: Ab3xYz 부탁드립니다")
        self.assertEqual(out, "자료 확인 부탁드립니다")
        self.assertFalse(privacy.credential_hit(out))
        self.assertEqual(c("참석자: 홍길동, 김철수, 이영희 안건: 시험 결과 공유"), "안건: 시험 결과 공유")
        self.assertEqual(c("참석자: 홍길동 책임, 김철수 선임\n안건: 양산 이관"), "안건: 양산 이관")
        self.assertEqual(c("검토 부탁드립니다. 홍길동 드림"), "검토 부탁드립니다.")
        self.assertEqual(c("Please check the draft. Thanks, John"), "Please check the draft.")
        self.assertEqual(c("자료 드림 예정 — 단가 올림 검토"), "자료 드림 예정 — 단가 올림 검토")      # 본문 동사는 남긴다

    def test_footer_recorded_human_teams(self):
        c = meetnote.clean_body
        self.assertEqual(c("장소: Microsoft Teams 회의 / 안건: 시험 결과"), "장소: Microsoft Teams 회의 / 안건: 시험 결과")
        self.assertEqual(c("자세한 정보는 첨부 참조"), "자세한 정보는 첨부 참조")
        self.assertEqual(c("안건 정리 Learn More | Meeting options"), "안건 정리")
        self.assertEqual(c("This meeting is being recorded. 안건: 결과 공유"), "안건: 결과 공유")
        self.assertEqual(c("이 모임은 녹화됩니다. 안건: 결과 공유"), "안건: 결과 공유")

    def test_cut_on_boundary(self):
        c = meetnote.clean_body
        s = "가" * 45 + " [사람] 회의"
        out = c(s, 50)
        self.assertLessEqual(len(out), 50)
        self.assertNotIn("[", out)                                        # 가림 토큰을 반쪽으로 자르지 않는다
        self.assertTrue(out.endswith("..."))
        s2 = "첫 문장은 시험 계획 검토입니다. 둘째 문장은 일정 협의와 담당 지정으로 길게 이어집니다"
        self.assertEqual(c(s2, 30), "첫 문장은 시험 계획 검토입니다.")
        self.assertLessEqual(len(c("검토 " * 400)), 600)

    def test_empty(self):
        for x in (None, "", "   ", "\r\n", "1. 2. 3.", "________"):
            self.assertEqual(meetnote.clean_body(x), "", repr(x))

    def test_idempotent_and_g1_stable(self):
        """G1 은 다음 수집 때 정제된 본문을 다시 거른다 — 거듭해도 바뀌지 않아야 한다(정제가 글을 늘려도 다시 잘리지 않는다)."""
        ctx = privacy.Ctx()
        for s in SAMPLES + ("검토 " * 400, "홍길동 책임과 " + "결과 공유 " * 90):
            c1 = meetnote.clean_body(s)
            self.assertEqual(meetnote.clean_body(c1), c1, s[:30])
            b1, _blank = meetnote.g1_body(s, ctx)
            self.assertLessEqual(len(b1), 600)
            self.assertEqual(meetnote.g1_body(b1, ctx), (b1, False), s[:30])
            self.assertEqual(privacy.sanitize(b1, "body", ctx)[0], b1, s[:30])     # 이어지는 scrub_csv 도 그대로 둔다
        self.assertEqual(meetnote.g1_body("서버 접속 비밀번호는 Abc123!@ 입니다", ctx), ("", True))


# ── 2) load_notes ────────────────────────────────────────────────────────────────
class LoadNotes(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_t18n_")
        self.data = os.path.join(self._td.name, "data")
        D = "2026-03-"
        self.rows = {
            "ok": _cal(D + "02 10:00", "프로젝트A 설계 검토 (홍길동 책임)", TEAMS_KR),
            "allday": _cal(D + "03 00:00", "프로젝트A 워크숍", "워크숍 안건 정리", all_day="True"),
            "cancel": _cal(D + "04 10:00", "프로젝트A 일정 협의", "안건: 일정 협의", ms="5"),
            "decline": _cal(D + "05 10:00", "프로젝트A 결과 보고", "안건: 결과 보고", resp="4"),
            "free": _cal(D + "06 10:00", "프로젝트A 정보 공유", "안건: 정보 공유", busy="0", resp=""),
            "free_acc": _cal(D + "06 15:00", "프로젝트A 수락 회의", "안건: 수락 회의 검토", busy="0", resp="3"),
            "tent": _cal(D + "09 10:00", "프로젝트A 미정 회의", "안건: 미정 회의 검토", busy="1", resp=""),
            "priv_subj": _cal(D + "10 10:00", "비공개 약속", "안건: 비공개 검토"),
            "priv_cat": _cal(D + "10 15:00", "프로젝트A 점검", "안건: 점검 검토", cats="개인"),
            "nonwork": _cal(D + "11 10:00", "Canceled: 프로젝트A 주간 회의", "안건: 주간 검토", ms=""),
            "absence": _cal(D + "12 10:00", "프로젝트A 외부 일정", "안건: 외부 일정 검토", busy="3"),
            "excl_subj": _cal(D + "13 10:00", "이력서 검토", "안건: 서류 검토"),
            "excl_body": _cal(D + "13 15:00", "프로젝트A 일정 조정", "개인 사정으로 일정 조정 검토"),
            "cred": _cal(D + "16 10:00", "프로젝트A 서버 점검", "서버 접속 비밀번호는 Abc123!@ 입니다 검토 바랍니다"),
            "social": _cal(D + "17 18:00", "프로젝트A 회식", "회식 장소 맛집 공지 ㅋㅋ 다들 오세요"),
            "out": _cal("2025-12-30 10:00", "프로젝트A 작년 회의", "안건: 작년 회의 검토"),
        }
        _write(os.path.join(self.data, "outlook", "calendar.csv"), CAL_H, list(self.rows.values()))
        # 추가 PC — 본문 있는 회의 1 + body 열이 없는 옛 파일
        _write(os.path.join(self.data, "추가PC", "PC1", "outlook", "calendar.csv"), CAL_H,
               [_cal("2026-03-18 10:00", "프로젝트A 추가 PC 회의", "안건: 시험 장비 이관")])
        _write(os.path.join(self.data, "추가PC", "PC2", "outlook", "calendar.csv"), mailmerge.CAL_COLS,
               [["2026-03-19 10:00", "2026-03-19 11:00", "False", "2", "옛 파일 회의", "", "", "3", "1"]])

    def tearDown(self):
        self._td.cleanup()

    def key(self, name):
        r = self.rows[name]
        subj = privacy.sanitize(extract._one_line(r[4], None), "signal", privacy.make_ctx({"owner": ""}, self.data))[0]
        return meetnote.note_key(r[0], subj)

    def test_filters(self):
        st = {}
        notes = meetnote.load_notes(self.data, date(2026, 1, 1), date(2026, 10, 12), {"owner": ""}, stats=st)
        self.assertEqual(notes.get(self.key("ok")), "시험 결과 검토 및 일정 협의")
        self.assertIn(self.key("free_acc"), notes)                         # 주최·수락이면 한가함 표시라도 참석
        self.assertIn(self.key("tent"), notes)                             # tentativeMeetings=count(기본)
        for name in ("allday", "cancel", "decline", "free", "priv_subj", "priv_cat", "nonwork", "absence",
                     "excl_subj", "excl_body", "cred", "social", "out"):
            self.assertNotIn(self.key(name), notes, name)
        self.assertIn(("2026-03-18", "10:00", "프로젝트a 추가 pc 회의"), notes)   # 추가 PC 뿌리
        self.assertEqual(len(notes), 4)
        for why, n in (("종일", 1), ("참석 아님", 3), ("비공개", 2), ("비업무", 1), ("근태", 1), ("제외어", 2),
                       ("자격증명", 1), ("사적", 1), ("붙임", 4)):
            self.assertEqual(st.get(why), n, (why, st))
        self.assertTrue(all("홍길동" not in v for v in notes.values()))

    def test_tentative_skip_disabled_and_max(self):
        cfg = {"owner": "", "mm": {"tentativeMeetings": "skip"}}
        notes = meetnote.load_notes(self.data, "2026-01-01", "2026-10-12", cfg)
        self.assertNotIn(self.key("tent"), notes)
        self.assertEqual(meetnote.load_notes(self.data, "2026-01-01", "2026-10-12",
                                             {"calendar": {"bodyToAI": False}}), {})
        self.assertEqual(meetnote.load_notes(self.data, "2026-01-01", "2026-10-12",
                                             {"calendar": {"bodyToAI": "false"}}), {})
        short = meetnote.load_notes(self.data, "2026-01-01", "2026-10-12", {"calendar": {"noteMaxChars": 20}})
        self.assertTrue(short and all(len(v) <= 20 for v in short.values()), short)
        self.assertEqual(meetnote.note_max({"calendar": {"noteMaxChars": "x"}}), 160)
        self.assertEqual(meetnote.note_max({"calendar": {"noteMaxChars": 5000}}), 600)

    def test_key_matches_real_meeting_signal(self):
        """키는 extract 가 만든 실제 회의 신호(시각·정제 제목)와 맞아야 한다 — signals 의 text 는 100자 계약."""
        cfg = {"owner": ""}
        sig, _meta = extract.load_signals(self.data, date(2026, 1, 1), date(2026, 10, 12), cfg=cfg)
        meet = [s for s in sig if s[1] == "회의" and s[0].strftime("%Y-%m-%d %H:%M") == "2026-03-02 10:00"]
        self.assertEqual(len(meet), 1)
        notes = meetnote.load_notes(self.data, date(2026, 1, 1), date(2026, 10, 12), cfg)
        k = meetnote.note_key(meet[0][0].strftime("%Y-%m-%d %H:%M"), extract._one_line(meet[0][2], None)[:100])
        self.assertEqual(notes.get(k), "시험 결과 검토 및 일정 협의")


# ── 3) judge — 프롬프트·관문·캐시 ─────────────────────────────────────────────────────
def _idxs(prompt):
    return [int(x) for x in re.findall(r"^#(\d+) \|", prompt, re.M)]


class _Judge(unittest.TestCase):
    """judge.main 을 임시 ROOT 로 — 드라이버(_transport)만 가짜, G3 관문(g3_rows·g3_prompt)은 진짜(카나리아 CANARY)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="lm28_t18j_")
        self.tmp = self._tmp.name
        self.rep = os.path.join(self.tmp, "report")
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.rep)
        self.sent, self.cfg = [], {}
        ca._PRIV.clear()
        ca._PRIV.update(cfg={}, ctx=privacy.Ctx(), cans=(CANARY,))
        st = self.stack = contextlib.ExitStack()
        st.enter_context(mock.patch.dict(os.environ))
        for k in ("LM_AI_DEADLINE", "LM_COPILOT_STUB"):
            os.environ.pop(k, None)
        for name, val in (("ROOT", self.tmp), ("_FIRST_SEND", [True]), ("_NEED_FRESH", [False]), ("_TURNS", [0]),
                          ("_CHAT_TURNS", [None]), ("_HARD", [False]), ("_COOLED", [0.0]), ("_COOLDOWNS", [0]),
                          ("_MODEL_FALLBACK", [""]), ("_THR_CHECKED", [False]), ("_WAIT_TICKS", [0]),
                          ("_LAST_PROMPT", [None]), ("_STUB_NOTED", [True])):
            st.enter_context(mock.patch.object(judge, name, val))
        st.enter_context(mock.patch.object(judge, "_transport", self._transport))
        st.enter_context(mock.patch.object(judge, "_cooldown", lambda sec: None))
        st.enter_context(mock.patch.object(judge, "_copilot_cfg", lambda: {}))
        st.enter_context(mock.patch.object(ca, "throttle_state", lambda *a, **k: None))
        st.enter_context(mock.patch.object(ca, "note_throttle", lambda *a, **k: True))
        st.enter_context(mock.patch.object(extract, "load_cfg", lambda: self.cfg))
        self.out = io.StringIO()
        st.enter_context(contextlib.redirect_stdout(self.out))

    def tearDown(self):
        cur = stage_state.current()
        if cur is not None:
            cur.finish("failed")
        self.stack.close()
        ca._PRIV.clear()
        self._tmp.cleanup()

    def _transport(self, prompt_text, pf, name, want_fresh, lim, reload=False, model=None):
        self.sent.append({"name": name, "prompt": prompt_text})
        if name == "taxonomy":
            o = {"models": [{"name": "프로젝트A", "match": ["프로젝트a"]}, {"name": "공통", "match": []}]}
        else:
            o = {"j": [[i, "y", "프로젝트A", "개발", "설계 검토"] for i in _idxs(prompt_text)]}
        return {"ok": True, "phase": "replied", "reply": json.dumps(o, ensure_ascii=False)}

    def write_signals(self, rows):
        _write(os.path.join(self.rep, f"signals_{TAG}.csv"), SIG_COLS,
               [[r.get(c, "") for c in SIG_COLS] for r in rows])

    def write_cal(self, rows):
        _write(os.path.join(self.data, "outlook", "calendar.csv"), CAL_H, rows)

    def run_main(self):
        argv = ["judge.py", "--from", "2026-01-01", "--to", "2026-10-12", "--chunk", "40", "--fast", "--no-narrate"]
        with mock.patch.object(sys, "argv", argv):
            return judge.main()

    def chunk_prompts(self):
        return [s["prompt"] for s in self.sent if s["name"].startswith("chunk")]

    def sent_idxs(self):
        return sorted(i for p in self.chunk_prompts() for i in _idxs(p))

    def line_of(self, idx):
        for p in self.chunk_prompts():
            for ln in p.splitlines():
                if ln.startswith(f"#{idx} |"):
                    return ln
        return None


def _sig(t, text, source="회의", who=""):
    return {"time": t, "source": source, "who": who, "project": "", "activity": "회의", "weight": "2", "text": text}


class JudgeNotes(_Judge):
    def test_note_on_meeting_rows_only_and_gated(self):
        self.write_signals([_sig("2026-03-02 10:00", "프로젝트A 설계 검토"),
                            _sig("2026-03-02 10:00", "프로젝트A 설계 검토", "메일(수신)", "a@x.example"),
                            _sig("2026-03-03 14:00", "프로젝트A 주간 진행 점검"),
                            _sig("2026-03-04 09:30", "프로젝트A 고객 대응 회의")])
        self.write_cal([_cal("2026-03-02 10:00", "프로젝트A 설계 검토", TEAMS_KR),
                        _cal("2026-03-03 14:00", "프로젝트A 주간 진행 점검", f"{CANARY} 관련 안건 정리 검토"),
                        _cal("2026-03-04 09:30", "프로젝트A 고객 대응 회의", "회식 장소 맛집 공지 ㅋㅋ 다들 오세요")])
        self.assertEqual(self.run_main(), 0, self.out.getvalue()[-1500:])
        self.assertEqual(self.sent_idxs(), [0, 1, 2, 3])
        self.assertTrue(self.line_of(0).endswith(" | 프로젝트A 설계 검토 — 안건: 시험 결과 검토 및 일정 협의"), self.line_of(0))
        for i in (1, 2, 3):
            self.assertNotIn("안건:", self.line_of(i), i)                 # 메일 행 · 관문에 걸린 안건 · 사적 본문
        allp = "\n".join(self.chunk_prompts())
        self.assertIn(judge.NOTE_HINT, allp)
        self.assertNotIn(CANARY, allp)
        self.assertNotIn("Ab3xYz", allp)
        log = self.out.getvalue()
        self.assertIn("회의 안건(일정 본문 정제) 1건을 회의 판정의 참고로 붙입니다 · 개인정보 관문에서 뺀 안건 1건", log)
        with open(os.path.join(self.rep, f"ai_judgments_{TAG}.json"), encoding="utf-8") as f:
            aj = json.load(f)
        self.assertEqual(aj["meeting_notes"], 1)
        # signals 열은 그대로 · 안건 원문은 signals·캐시·판정 기록 어디에도 없다(팀 반출 불변)
        with open(os.path.join(self.rep, f"signals_{TAG}.csv"), encoding="utf-8-sig") as f:
            head = next(csv.reader(f))
        self.assertEqual(head, ["time", "source", "who", "project", "activity", "weight", "text",
                                "model", "worktype", "detail", "judge", "flag"])
        for fn in (f"signals_{TAG}.csv", judge.JUDGE_CACHE, f"ai_judgments_{TAG}.json"):
            with open(os.path.join(self.rep, fn), encoding="utf-8-sig") as f:
                self.assertNotIn("시험 결과 검토 및 일정 협의", f.read(), fn)
        self.assertTrue(all(r["judge"] == "AI" for r in _rows(os.path.join(self.rep, f"signals_{TAG}.csv"))))

    def test_cache_key_rejudges_only_new_note(self):
        sig = [_sig("2026-03-02 10:00", "프로젝트A 설계 검토"),
               _sig("2026-03-02 10:00", "프로젝트A 설계 검토", "메일(수신)", "a@x.example")]
        self.write_signals(sig)
        self.write_cal([_cal("2026-03-02 10:00", "프로젝트A 설계 검토", "")])     # 본문 없음 — 안건 없음
        self.run_main()
        self.assertEqual(self.sent_idxs(), [0, 1])
        self.sent.clear()
        self.write_signals(sig)
        self.write_cal([_cal("2026-03-02 10:00", "프로젝트A 설계 검토", TEAMS_KR)])
        self.run_main()
        self.assertEqual(self.sent_idxs(), [0])                          # 안건이 생긴 회의만 — 메일 행은 캐시
        self.sent.clear()
        self.write_signals(sig)
        self.run_main()
        self.assertEqual(self.chunk_prompts(), [])                       # 같은 안건 — 다시 묻지 않는다
        self.cfg = {"calendar": {"bodyToAI": False}}
        self.write_signals(sig)
        self.run_main()
        self.assertEqual(self.chunk_prompts(), [])                       # 끄면 예전 키 — 첫 판정 캐시

    def test_group_needs_same_note(self):
        subj = "프로젝트A 광학 모듈 설계 검토"
        self.write_signals([_sig(f"2026-03-0{d} 10:00", subj) for d in (2, 3, 4)])
        self.write_cal([_cal("2026-03-02 10:00", subj, "안건: 시험 결과 공유"),
                        _cal("2026-03-03 10:00", subj, "안건: 시험 결과 공유"),
                        _cal("2026-03-04 10:00", subj, "안건: 양산 이관 일정")])
        self.run_main()
        self.assertEqual(len(self.sent_idxs()), 2)                       # 같은 안건 둘은 한 묶음, 다른 안건은 따로
        self.assertTrue(all(r["judge"] == "AI" for r in _rows(os.path.join(self.rep, f"signals_{TAG}.csv"))))


# ── 4) mailmerge ─────────────────────────────────────────────────────────────────
class MergeBody(unittest.TestCase):
    def test_body_carried_and_old_files(self):
        with tempfile.TemporaryDirectory(prefix="lm28_t18m_") as td:
            out = os.path.join(td, "data", "outlook")
            src = os.path.join(out, "src")
            h = mailmerge.CAL_COLS + ["body"]
            _write(os.path.join(src, "cal_com.csv"), h,
                   [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "설계 검토", "", "", "3", "1", ""],
                    ["2026-03-03 09:00", "2026-03-03 10:00", "False", "2", "주간 회의", "", "", "3", "1", "안건 A"]])
            _write(os.path.join(src, "cal_owa.csv"), h,
                   [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "설계 검토", "", "", "", "", "안건 B"],
                    ["2026-03-04 09:00", "2026-03-04 10:00", "False", "2", "고객 회의", "", "", "", "", "안건 C"]])
            _write(os.path.join(src, "cal_index.csv"), ["start", "end", "all_day", "busy_status", "subject", "categories", "location"],
                   [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "설계 검토", "", ""],
                    ["2026-03-05 09:00", "2026-03-05 10:00", "False", "2", "옛 출처 회의", "", ""]])
            info = mailmerge.merge(src, out, norm=lambda s: s)
            self.assertTrue(info["ok"])
            p = os.path.join(out, "calendar.csv")
            with open(p, encoding="utf-8-sig", newline="") as f:
                self.assertEqual(next(csv.reader(f)), mailmerge.CAL_COLS + ["src", "body"])
            got = {r["subject"]: (r["src"], r["body"]) for r in _rows(p)}
            self.assertEqual(got, {"설계 검토": ("com", "안건 B"), "주간 회의": ("com", "안건 A"),
                                   "고객 회의": ("owa", "안건 C"), "옛 출처 회의": ("index", "")})
            self.assertEqual(info["cal_body"], 3)
            extract.READ_DROPPED.pop(p, None)
            self.assertEqual(len(extract._read(p)), 4)                       # 분석(extract)이 그대로 읽는다
            self.assertNotIn(p, extract.READ_DROPPED)


# ── 5) run.g1_mail ───────────────────────────────────────────────────────────────
class G1Body(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="lm28_t18g_")
        self.data = os.path.join(self._td.name, "data")
        self.src = os.path.join(self.data, "outlook", "src")
        self._saved = (dict(R.REPORT_DIR), list(R.RUN["stages"]))
        R.REPORT_DIR["p"] = os.path.join(self._td.name, "report")
        R.RUN["stages"] = []

    def tearDown(self):
        rep, stages = self._saved
        R.REPORT_DIR.clear()
        R.REPORT_DIR.update(rep)
        R.RUN["stages"] = stages
        self._td.cleanup()

    def g1(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            R.g1_mail({}, self.data)
        return buf.getvalue()

    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.src)):
            with open(os.path.join(self.src, n), "rb") as f:
                out[n] = f.read()
        return out

    def test_body_cleaned_rows_kept(self):
        h = mailmerge.CAL_COLS + ["body"]
        flat = re.sub(r"[\r\n]+", " ", TEAMS_KR)                         # COM 은 한 줄로 쓴다
        _write(os.path.join(self.src, "cal_com.csv"), h,
               [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "프로젝트A 설계 검토 (홍길동 책임)", "", "", "3", "1", flat],
                ["2026-03-03 10:00", "2026-03-03 11:00", "False", "2", "서버 점검", "", "", "3", "1",
                 "서버 접속 비밀번호는 Abc123!@ 입니다"]])
        _write(os.path.join(self.src, "cal_index.csv"), mailmerge.CAL_COLS, [["2026-03-02 10:00", "2026-03-02 11:00", "False",
                                                                             "2", "주간 회의", "", "", "", ""]])
        # 웹 출처: 정제된 옛 행(본문 없음) 뒤에 수집기가 같은 일정의 원문 행(본문 있음)을 다시 붙였다
        _write(os.path.join(self.src, "cal_owa.csv"), h,
               [["2026-03-04 10:00", "2026-03-04 11:00", "False", "2", "시제품 평가", "", "", "", "", ""],
                ["2026-03-04 10:00", "2026-03-04 11:00", "False", "2", "시제품 평가", "", "", "", "", TEAMS_KR_OLD_FLAT]])
        idx_before = self.snap()["cal_index.csv"]
        log = self.g1()
        com = _rows(os.path.join(self.src, "cal_com.csv"))
        self.assertEqual(len(com), 2)                                     # 회의 암호·자격증명 본문 때문에 회의가 버려지지 않는다
        self.assertEqual(com[0]["body"], "시험 결과 검토 및 일정 협의")
        self.assertEqual(com[0]["subject"], "프로젝트A 설계 검토 ([사람] 책임)")
        self.assertEqual(com[1]["body"], "")
        raw = self.snap()["cal_com.csv"].decode("utf-8-sig")
        for bad in ("Ab3xYz", "1234-5678", "Abc123", "teams.microsoft.com"):
            self.assertNotIn(bad, raw)
        self.assertEqual(self.snap()["cal_index.csv"], idx_before)        # body 열 없는 파일은 그대로
        owa = _rows(os.path.join(self.src, "cal_owa.csv"))
        self.assertEqual([(r["subject"], r["body"]) for r in owa], [("시제품 평가", "안건: 시제품 평가 결과 공유")])
        self.assertIn("일정 본문(회의 안건)", log)
        self.assertIn("자격증명이 남아 비운 본문 1건", log)
        before = self.snap()
        self.g1()
        self.assertEqual(self.snap(), before)                             # 두 번 돌려도 같다(멱등)

    def test_prep_without_body_column(self):
        p = os.path.join(self.src, "cal_index.csv")
        _write(p, mailmerge.CAL_COLS, [["2026-03-02 10:00", "2026-03-02 11:00", "False", "2", "주간 회의", "", "", "", ""]])
        info = meetnote.prep_body_csv(p, privacy.Ctx())
        self.assertTrue(info["ok"])
        self.assertFalse(info["changed"])


# ── 6) PowerShell — Get-CalBody · 수집기 body 열 ────────────────────────────────────────
class PsCalBody(unittest.TestCase):
    def setUp(self):
        self.r = _boot.ps_result("CalBody")
        if self.r is None:
            self.skipTest("PowerShell 시험 — tests\\run_tests.py p18 --ps-only=CalBody 로 돈다")
        self.assertNotIn("error", self.r, str(self.r.get("error")))

    def test_get_cal_body(self):
        b = self.r["body"]
        self.assertEqual((b["ok"]["why"], b["ok"]["body"], b["ok"]["touched"]), ("ok", "안건: 시험 결과 공유 검토 끝", 1))
        for k in ("private", "conf"):
            self.assertEqual((b[k]["why"], b[k]["body"], b[k]["touched"]), ("private", "", 0), k)
        self.assertEqual((b["prot"]["why"], b["prot"]["body"], b["prot"]["touched"]), ("prot", "", 0))   # 보호 멤버를 건드리지 않는다
        self.assertEqual((b["err"]["why"], b["err"]["body"]), ("err", ""))
        self.assertEqual(b["empty"]["why"], "empty")
        self.assertEqual(b["long"]["len"], 600)
        self.assertEqual(b["sur"]["len"], 599)                            # 반쪽 서로게이트는 버린다

    def test_collector_body_column_and_reread(self):
        c = self.r["col"]
        self.assertEqual(c["rc1"], 0, c["last1"])
        self.assertTrue(c["head1"].endswith(",meeting_status,body"), c["head1"])
        self.assertEqual(c["body1"], c["rows1"])
        self.assertGreater(c["rows1"], 0)
        self.assertTrue(c["cov1"])
        st2 = _lmstatus(c["last2"])
        self.assertEqual(c["rc2"], 0, c["last2"])
        self.assertEqual(st2["counts"]["months_read"], {"mail": 0, "calendar": 3})   # 옛 표 — 일정 달만 다시
        self.assertEqual(c["reread_note"], 1)
        self.assertTrue(c["head2"].endswith(",body"))
        self.assertEqual((c["rows2"], c["body2"]), (c["rows1"], c["rows1"]))
        self.assertTrue(c["cov2"])
        st3 = _lmstatus(c["last3"])
        self.assertEqual(st3["counts"]["months_read"]["calendar"], 0)
        self.assertTrue(st3["counts"]["cal_body_on"])
        self.assertTrue(self.r["tmp_removed"])


if __name__ == "__main__":
    unittest.main()
