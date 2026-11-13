# -*- coding: utf-8 -*-
r"""
consent.py — 시작 관문(내 자료인가 · 지우는 중이 아닌가) · 안내문 · 모두 지우기(spec §6.2 · D12 · R3).
이 도구는 쓰겠다는 뜻을 묻지도 적지도 않는다 — 그것은 서면으로 따로 받는다(PAPER_CONSENT_LINE). 모듈·함수 이름은 예전 그대로다.
모든 시작점(화면·run.py·각 단계 CLI·teamup·수집기)은 require 로 두 가지만 본다: 이 설치의 자료가 지금 Windows 사용자의 것인가,
'모두 지우기' 가 진행 중이 아닌가.

안내문 notice(cfg) -> dict — 한국어 절 {purpose, collected, not_collected, channels, ai, period, retention, rights, sharing,
  scheduled_purge}. 각 절 = {"title": 제목, "lines": [문장]}; retention 은 "rows": [{"class","item","where","days"}] 를 더 가진다
  (class = retention 의 분류 raw·intermediate·result·html·share·other 와 서버 줄 serverPersonal·serverTeam — keep 밖 전부).
  읽기만 하는 설명글이다(화면의 [안내] · CLI --notice · 서면 양식에 붙이는 글) — 누르거나 답할 것이 없다.
  저장·전송하는 것(§5 열)과 설정(수집 경로·일정 본문·기간 상한·보관 일수·팀 문턱·매일 정리·Copilot 채팅 지우기·문의처
  privacy.contact)을 그대로 반영한다. 문장은 코드가 지키는 만큼만 말한다 — 가리기는 '이 도구가 알아보는 것만', 서버 사본의
  일수는 '그 서버의 설정'(상한만 약속), Outlook 앱 수집기의 임시 원자료(RAW_FILE_LINE)와 이름 해시의 기한도 적는다.
  공유 가리기 문장(SHARE_MASK_LINE·SHARE_CHECK_LINE)과 팀 기여분 파일 문장(TEAM_FILE_LINE)은 공유 리포트·확인 창이 같은 말로 쓴다.
  PAPER_CONSENT_LINE('내 권리' 절의 첫 줄 — 화면·bat·문서가 같은 문장을 쓴다) · WITHDRAW_PAPER_LINE · CONTACT_LINE(문의처 한 줄).

data\withdrawal.json = {"product","state":"in_progress"|"done","withdrawn_at","server_withdrawal","chats_left"} — 모두 지우기의 기록.
  날짜는 'YYYY-MM-DD' 만(D10) — 예전 판이 남긴 시각은 status 가 날짜만 남기고 다시 쓴다(다른 사용자의 자료는 건드리지 않는다).
  state 가 없는 예전 기록은 done. 이 모듈은 그 밖의 기록 파일을 읽지도 쓰지도 않는다(옛 판이 남긴 기록 파일은 retention 이 지운다).
API
  status(root, cfg) -> {"accepted","other_user","unknown_owner","withdrawal_state","withdrawn_at","chats_left"}
      accepted = 이 설치의 자료가 지금 Windows 사용자의 것이고(install.load 의 user_ok) 모두 지우기가 진행 중이 아니다 —
                 이것만 참이면 수집·분석·공유를 할 수 있다. 그 밖에 필요한 것은 없다.
      withdrawal_state = None · "in_progress" · "done" · withdrawn_at = 마지막으로 모두 지운 날 | None · chats_left = 그때 못 지운
      Copilot 채팅 수.
  require(root, cfg) -> status        쓸 수 없으면 ConsentRequired(reason, message):
      "other_user" — 다른 사용자의 자료·주인을 알 수 없는 자료(install.OTHER_USER_MSG · install.UNKNOWN_OWNER_MSG) · code 4
      "withdrawn"  — 모두 지우기가 진행 중(WIPING_MSG) · code 3.  MESSAGES 는 이 두 열쇠뿐이다.
  모두 지우기의 순서(화면 POST /api/consent/withdraw · 이 CLI):
      ⓪ CLI(cli_withdraw · --withdraw)는 먼저 누구의 자료인지 본다 — 다른 사용자의 자료·주인을 알 수 없는 자료면
         ConsentRequired("other_user")(종료 코드 4): 아무것도 쓰지 않고, 서버에 닿지 않고, 전용 Edge 를 건드리지 않는다(그 폴더의
         전용 Edge 는 그 사람의 로그인이다). 그런 폴더는 화면의 [열지 않고 지우기]나 AgentFinder32.bat(retention.py --purge-all)
         이 지운다 — 화면도 같은 요청을 409 로 거절한다. withdraw·begin_withdrawal 은 이 확인을 하지 않는다(그 두 길이 쓴다).
      ① begin_withdrawal(root, cfg) — 분석·수집 작업이 돌면(retention.run_active · 없으면 _busy) WithdrawBusy(아무것도 지우지
         않는다). 아니면 data\withdrawal.json 에 state 'in_progress' 를 먼저 쓰고 남은 공유 영수증에 "withdraw": true 를 붙인다
         — 이때부터 require 가 막고, 끊겨도 다음 시작 때 resume_withdrawal 이 마저 지운다.
      ② teamup.withdraw_all(root, cfg, timeout=10)
      ③ copilot_auto.sweep_owned(None, budget, why="withdraw", launch=True, lock_wait=30) — 전용 Edge 가 꺼져 있으면 띄워 이 도구가
         연 채팅을 지운다 · close_own_edge
      ④ withdraw(root, cfg, *, server_withdrawal=None, unregister=True, chats_left=None) -> {"deleted","errors","task_removed",
         "pending_receipts","withdrawn_at","chats_left","state"} — ①(이미 했으면 그대로) → 남은 Copilot 채팅 수를 기록(③ 의 결과와
         data\af32_edge.chats.json 의 owned[] 중 큰 값 — 그 기록은 곧 지워진다) → 큰 자료부터(retention.purge_all keep_consent=True)
         → 설치 정보(마지막) → 매일 정리 작업 지우기 → state 'done'. 큰 자료 가운데 못 지운 파일이 남으면(다른 프로그램이 연
         파일) 설치 정보·매일 정리 작업을 그대로 두고 'in_progress' 로 남긴다 — 다음 시작 때 다시 지운다.
         서버에서 아직 지우지 못한 영수증은 표시한 채 남겨 시작할 때마다 다시 지운다(teamup.retry_withdrawals).
      다 지운 뒤('done')에는 바로 다시 쓸 수 있다 — 다음 시작이 새 설치 정보를 만든다(지운 기록과 표시한 영수증은 자료로 세지 않는다).
  resume_withdrawal(root, cfg) -> None | ④ 의 결과(+ "resumed": True) — state 가 'in_progress' 면 ④ 를 마저 한다(서버·Edge 는
      건드리지 않는다). 화면 시작·run.py 시작·retention --purge(매일 정리 작업 포함)가 부른다. 예외를 내지 않는다.
  withdraw_message(res) -> 한국어 한 줄(지운 수 · 못 지운 수 · 서버에 남은 공유 · 지우지 못한 Copilot 채팅 수 — CHATS_LEFT_MSG ·
      채팅 지우기를 설정으로 꺼 둔 때는 CHATS_OFF_MSG)
  contact_info(cfg) -> (이름, 연락 방법) · contact_line(cfg) -> 문의·이의 한 줄(CONTACT_LINE — 안내문 '내 권리' 절 · 화면)
  매일 정리 예약 작업은 여기서 만들지 않는다(retention.sync_task 가 시작할 때 맞춘다). 다 지우면 그 작업을 지운다.
CLI  python core\consent.py --status [--json] | --notice | --withdraw [--yes] [--json] ('지우기' 입력 또는 --yes)   [--root R]
     --status 종료 코드: 0 쓸 수 있음 · 3 모두 지우기가 진행 중 · 4 다른 사용자·주인을 알 수 없는 자료 · 1 오류.
     --withdraw: 0 · 1 실패(작업 중이라 지우지 않음 · 못 지운 것이 남음) · 4 다른 사용자·주인을 알 수 없는 자료(아무것도 하지 않음).
"""
import importlib
import json
import os
import re
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402
import install  # noqa: E402
import lmname  # noqa: E402
import retention  # noqa: E402

ROOT = os.path.dirname(_HERE)
INSTALL_FILE = "install.json"
WITHDRAWAL_FILE = "withdrawal.json"
RECEIPTS_FILE = "share_receipts.json"
CHATS_FILE = lmname.EDGE_PROFILE_NAME + ".chats.json"   # 전용 Edge 옆의 Copilot 채팅 기록(copilot_auto 의 owned[])
WD_IN_PROGRESS = "in_progress"
WD_DONE = "done"
LAST_FILES = (INSTALL_FILE,)                            # 모두 지울 때 마지막에 지운다(큰 자료를 다 지운 뒤 — 남은 자료의 주인을 안다)
CHAT_SWEEP_SEC = 300                                    # 모두 지울 때 채팅 정리 상한(초 — copilot_auto.SWEEP_BUTTON_SEC 와 같다)
CHAT_LOCK_WAIT = 30                                     # 그 정리가 전용 Edge 잠금을 기다리는 상한(초)
# 이 설치 폴더에서 돌면 지우지 않는 프로그램(명령줄에 '<설치 폴더>\…' 와 이 이름이 함께 있는 프로세스)
BUSY_SCRIPTS = ("run.py", "mine.py", "judge.py", "refine.py", "agentic.py", "flow.py", "report_out.py", "retag.py",
                "Get-OutlookData.ps1", "Get-OutlookWeb.py", "Get-MailViaCopilot.py", "Diagnose-Collectors.ps1")
BUSY_SHARE = ("teamup", "--share")                      # 보내는 중인 공유(둘이 함께 있을 때만 — 미리보기·상태 확인은 막지 않는다)
# 그 프로그램을 돌리는 실행 파일 — 이 이름의 프로세스만 명령줄을 읽는다(core\proc.process_list — 새 프로세스를 띄우지 않는다)
BUSY_EXES = ("python.exe", "pythonw.exe", "py.exe", "powershell.exe", "pwsh.exe")
_PS_PROCS = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "      # 한글 설치 경로가 깨지지 않게(기본은 OEM 코드 페이지)
             "Get-CimInstance Win32_Process -Property ProcessId,CommandLine | "
             "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
PURPOSE_LINE = ("이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다. 사람을 평가하거나 근태·업무량을 보는 데 쓰지 않습니다.")
# 서면으로 따로 받는다는 한 문장 — 안내문 '내 권리' 절의 첫 줄이고, 화면의 늘 보이는 줄·bat·문서가 같은 문장을 쓴다
PAPER_CONSENT_LINE = ("이 도구는 서면 동의서를 낸 사람만 씁니다. 동의는 서면으로 따로 받으며, "
                      "이 도구는 동의를 묻거나 기록하지 않습니다.")
DATA_TAB = "[내 데이터]"                                 # 화면의 탭 이름(ui\app 의 PAGE 와 같다)
WIPE_BUTTON = "[모두 지우기(서버 사본 포함)]"            # 그 탭의 모두 지우기 단추 이름(PAGE 와 같다)
# 서면으로 낸 것을 거두는 길과 내 자료를 지우는 길('내 권리' 절 — 화면의 탭·단추 이름 그대로)
WITHDRAW_PAPER_LINE = ("서면 동의를 거두려면 문의처에 알립니다. 이 PC 와 조직장 서버에 있는 내 자료는 언제든 [내 데이터] 탭의 "
                       "[모두 지우기(서버 사본 포함)]로 지울 수 있습니다.")
# 문의처 한 줄(안내문 '내 권리' 절의 끝 줄 · 화면) — {who} = 설정 privacy.contact 의 이름(연락 방법) 또는 CONTACT_DEFAULT
CONTACT_LINE = "서면 동의와 그 철회, 공유(공유를 요구받은 때 포함)에 대한 문의나 이의는 {who}에게 할 수 있습니다."
WIPING_MSG = "자료를 지우는 중입니다 — 다 지운 뒤 다시 시작할 수 있습니다"
MESSAGES = {                                            # require 가 막는 두 까닭(ConsentRequired.reason)의 한 줄
    "other_user": install.OTHER_USER_MSG,
    "withdrawn": WIPING_MSG,
}
UNKNOWN_OWNER_MSG = getattr(install, "UNKNOWN_OWNER_MSG", install.OTHER_USER_MSG)   # 설치 정보가 없어 주인을 모르는 자료
BUSY_MSG = "분석·수집 작업이 돌고 있어 지우지 않았습니다 — 작업이 끝난 뒤 다시 지울 수 있습니다"
# 안내문의 '내 권리' 절 — '언제든 지울 수 있다'(WITHDRAW_PAPER_LINE)에 붙는 단서: 작업 중에는 거절한다(WithdrawBusy · BUSY_MSG)
BUSY_NOTICE_LINE = "분석·수집 작업이 도는 동안에는 모두 지우기를 하지 않습니다 — 그 작업이 끝나거나 멈춘 뒤에 지울 수 있습니다."
CHATS_LEFT_MSG = "이 도구가 연 Copilot 채팅 {n}개를 지우지 못했습니다 — Copilot 대화 목록에서 직접 지울 수 있습니다"
CHATS_OFF_MSG = ("Copilot 채팅 지우기가 설정(copilotAuto.deleteChats)으로 꺼져 있어 이 도구가 연 채팅을 지우지 않았습니다 — "
                 "Copilot 대화 목록에서 직접 지울 수 있습니다")     # 화면(ui\app.CHATS_OFF_LINE)과 같은 말
CHANNEL_TEXT = {
    "com": "Outlook 앱 — 이 PC 에 설치된 Outlook 에서 내 기본 사서함의 메일·일정만 읽습니다.",
    "owa": "Outlook 웹 — 이 도구 전용 Edge 창에서 내가 직접 로그인한 내 계정의 메일·일정 목록만 읽습니다(메일을 열지 않습니다).",
    "copilot": "내 M365 Copilot — 회사 테넌트 안에서 내 계정으로 내 사서함의 메일·일정 목록(날짜·받은/보낸·제목·참여자 도메인)만 묻습니다.",
}
# Outlook 앱 수집기만 쓰는 임시 원자료(data\outlook\raw — 이름·주소가 든다): 정제(G1)가 끝나면 지우고, 멈춘 실행이 남긴 것은
# retention.drop_raw 가 지운다(화면의 [중지]·창 닫기·시작, run.py 시작, 강제 종료, retention.py --purge)
RAW_FILE_LINE = ("Outlook 앱으로 읽을 때는 읽은 목록(이름·주소 포함)을 가리기 전까지 이 PC 의 임시 파일(data\\outlook\\raw)에 두고, "
                 "가린 뒤 바로 지웁니다. 중간에 멈춰 남은 임시 파일은 멈출 때나 다음에 시작할 때 지웁니다.")
# Outlook 웹의 메일 목록은 줄마다 본문 첫머리(미리보기)를 함께 보인다 — 수집기는 그 글을 제목·날짜로 쓰지 않는다(메일을 열지 않는다)
OWA_PREVIEW_LINE = "Outlook 웹의 메일 목록에 함께 보이는 미리보기 글(본문 첫머리)은 쓰지도 저장하지도 않습니다."
# 공유 리포트(report_out)·화면 확인 창이 같은 말로 쓰는 문장 — 공유 가리기가 지키는 것과 지키지 못하는 것, 팀 기여분이 남는 곳.
# 늘 지키는 것만 적는다: 사전에 든 이름·이름 해시·호칭 이름, 연락처·식별 번호(허용 패턴과 상관없이 가린다), 건수는 싣지 않는다.
SHARE_MASK_LINE = ("공유 자료에서는 이 도구가 아는 이름(제한 고객 목록·과제 목록·내 업무 분류에 나온 이름과 분석하며 본 사람 이름)과 "
                   "메일 주소·전화번호·식별 번호를 [고객사]·[과제]·[사람]·[코드] 같은 표시로 가립니다. "
                   "업무별 근거 건수는 싣지 않습니다.")
SHARE_CHECK_LINE = "이 도구가 모르는 이름은 남을 수 있어, 보내기 전에 미리보기에서 항목마다 보고 고릅니다."
SHARE_FLAG_LINE = ("이름이 남은 것으로 보이는 항목은 미리보기에 따로 표시하고 처음에는 고르지 않은 채로 두며, "
                   "익명 팀 집계로는 보내지 않습니다.")
TEAM_FILE_LINE = ("익명 팀 집계로 보낸 기여분은 조직장 PC 의 팀 서버에 내 이름 없이 한 건씩 파일로 남고, 조직장은 그 파일을 "
                  "직접 열어 볼 수 있습니다. 참여 인원 기준은 집계 화면에만 적용됩니다.")     # 확인 창에 혼자 실려도 읽히게
M365_LINE = ("회사 M365 는 Copilot 과 주고받은 질문과 답{extra}을 회사 보존 정책에 따라 따로 보관할 수 있고, "
             "이 도구가 채팅을 지워도 그 보관분은 지울 수 없습니다.")
M365_COPILOT_EXTRA = "(Copilot 으로 읽은 내 메일·일정 제목 목록 포함)"
CONTACT_DEFAULT = "이 도구를 배포한 운영 담당"
_CONTACT_MAX = getattr(afcfg, "CONTACT_MAX", None) or {}
CONTACT_MAX = (int(_CONTACT_MAX.get("name", 40)), int(_CONTACT_MAX.get("channel", 120)))   # 문의처 이름·연락 방법 글자 수 상한(afcfg 와 같다)
_CTRL_RX = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_DATE_RX = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


class ConsentRequired(Exception):
    """시작 관문이 막았다(이름은 예전 그대로). reason = "other_user"(다른 사용자의 자료·주인을 알 수 없는 자료 — code 4) ·
    "withdrawn"(모두 지우기가 진행 중 — code 3). str(e) = message = 한국어 한 줄. code 는 부르는 쪽의 종료 코드로 쓴다."""

    code = 3

    def __init__(self, reason, message=None):
        self.reason = reason
        self.message = message or MESSAGES.get(reason) or WIPING_MSG
        self.code = 4 if reason == "other_user" else 3
        super().__init__(self.message)


class WithdrawBusy(Exception):
    """이 설치 폴더의 분석·수집 작업이 돌고 있어 지우지 않았다(아무것도 지우지 않았다). 화면은 409 busy 로 답한다."""

    code = 1
    reason = "busy"

    def __init__(self, message=None):
        self.message = message or BUSY_MSG
        super().__init__(self.message)


def _eff(cfg):
    c, _w = afcfg.effective(cfg if isinstance(cfg, dict) else {})
    return c


def _sec(title, lines, **extra):
    d = {"title": title, "lines": [x for x in lines if x]}
    d.update(extra)
    return d


def _int(v):
    if isinstance(v, bool):
        return int(v)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _clean(v, n):
    """설정에서 온 한 줄 — 제어·방향 문자를 빼고 공백을 한 칸으로, n 자까지. 글·숫자가 아니면 ""."""
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        return ""
    return " ".join(_CTRL_RX.sub(" ", str(v)).split())[:n].strip()


def _contact(c):
    v = afcfg.get(c, "privacy.contact")
    if isinstance(v, dict):
        name, chan = v.get("name"), v.get("channel")
    else:
        name, chan = v, ""
    return _clean(name, CONTACT_MAX[0]), _clean(chan, CONTACT_MAX[1])


def contact_info(cfg=None):
    """문의처(privacy.contact = {"name", "channel"} — 운영 담당이 채운다) → (이름, 연락 방법). 비었으면 ("", "")."""
    return _contact(_eff(cfg))


def _contact_line(c):
    name, chan = _contact(c)
    who = (f"{name}({chan})" if name and chan else name) or (f"운영 담당({chan})" if chan else CONTACT_DEFAULT)
    return CONTACT_LINE.format(who=who)


def contact_line(cfg=None):
    """문의·이의 한 줄(안내문 '내 권리' 절 · 화면의 읽기 전용 화면) — 문의처가 비었으면 '이 도구를 배포한 운영 담당'."""
    return _contact_line(_eff(cfg))


def notice(cfg=None):
    """안내문(한국어) — 설정을 반영한 절 dict. 읽기만 하는 설명글이다(답하거나 누를 것이 없다). 화면의 [안내]·CLI --notice·
    운영 문서 시험이 같은 것을 쓴다."""
    c = _eff(cfg)
    g = afcfg.get
    ch = [x for x in g(c, "collect.channels") if x in CHANNEL_TEXT]
    body, body_ai = bool(g(c, "calendar.collectBody")), bool(g(c, "calendar.bodyToAI"))
    subj = bool(g(c, "storeMailSubject"))
    days = {k: int(g(c, "retention." + k)) for k in afcfg.RETENTION_MAX}
    mx = int(g(c, "period.maxDays"))
    grp = max(5, int(g(c, "team.minGroupSize")))
    cell = max(3, int(g(c, "team.minCellSize")))
    sched = bool(g(c, "retention.scheduledPurge"))
    del_chats = afcfg.as_bool(g(c, "copilotAuto.deleteChats"), True)
    copilot = "copilot" in ch
    collected = [
        "메일: 받은 메일인지 보낸 메일인지, 받거나 보낸 날짜와 시각, 제목, 대화 제목, 받는 방식(받는 사람·참조).",
        "일정(회의): 회의 제목, 날짜와 시작·끝 시각, 장소." + (" 회의 본문(안건)도 600자까지 모읍니다." if body else ""),
        ("제목은 저장하지 않습니다 — 같은 대화인지 가리는 부호만 남깁니다." if not subj else ""),
        "보낸 사람·받는 사람·참조·주최자·참석자의 이름과 주소는 사내인지 사외인지 확인하고 제목 속 이름을 가리는 데만 잠깐 쓰고 저장하지 않습니다.",
        (RAW_FILE_LINE if "com" in ch else ""),
        "보낸 사람은 이름·주소 대신 부호(p:…)로 바꿔 둡니다. 이 부호를 만드는 열쇠는 이 PC 에만 두고 밖으로 내보내지 않습니다.",
        ("제목·장소" + ("·회의 본문" if body else "") + "의 사람 이름은 이 도구가 알아보는 것만 [사람]으로 가립니다 — "
         "메일·회의 참여자로 본 이름(이 PC 에 남은 이름 해시로 알아보는 이름 포함)과 '홍길동 책임'처럼 호칭·직함이 붙어 "
         "사람 이름으로 보이는 한글 이름입니다. "
         "그 밖의 이름(참여자로 보지 못했고 호칭·직함도 없는 이름, 영문 이름 등)은 그대로 남을 수 있습니다."),
        "전화번호·메일 주소와 주민등록번호·카드·계좌 같은 번호는 [전화]·[이메일]·[주민번호]·[카드]·[계좌] 같은 표시로 바꿔 둡니다.",
        ("같은 이름을 다음 분석에서도 가리려고 이름 조각을 열쇠로 바꾼 값(해시)만 이 PC 에 둡니다. "
         "이 값은 이 PC 의 열쇠로 이름과 맞춰 볼 수 있어, 그 이름을 마지막으로 본 날부터 "
         f"{days['intermediateDays']}일(남은 분석 결과와 함께 둔 것은 길어도 {days['resultDays']}일)이 지나면 지웁니다."),
        "분석 결과: 업무 분류(Level 1~3)와 업무별 근거 건수, Agentic AI 전환 후보, 워크플로우와 Agent 가능성 — 날짜만 남기고 시각은 남기지 않습니다.",
        "날짜·시각은 같은 메일을 한 번만 세는 데만 쓰고 수집 자료(data\\outlook)에만 둡니다.",
    ]
    not_collected = [
        "메일 본문과 첨부 파일은 읽지 않습니다." + ("" if body else " 일정 본문(회의 안건)도 모으지 않습니다."),
        (OWA_PREVIEW_LINE if "owa" in ch else ""),
        "PC 의 파일·폴더, 사용한 프로그램, PC 사용 시간·켜고 끈 시각, 웹 사용 기록, 출퇴근·근태 기록은 모으지 않습니다.",
        "Teams 채팅·모임 채팅·녹취록, 공유·그룹 사서함, 다른 사람의 사서함과 자료는 모으지 않습니다.",
        "읽은 뒤 바로 빼고 저장하지 않는 항목:",
        "· 비공개·개인·기밀로 표시한 메일·일정, 개인 범주·개인 폴더의 항목, 개인 주제어가 든 항목",
        "· 건강·노동조합·정치·종교·성생활·범죄 경력 같은 민감한 내용이 든 항목",
        "· 가린 뒤에도 주민등록번호·외국인등록번호·여권·운전면허·카드·계좌 번호 같은 식별 번호가 남는 항목, "
        "비밀번호·인증번호 같은 접속 정보가 든 항목",
        "· 사외 사람이 하나라도 있거나, 모든 참여자가 사내인지 확인할 수 없는 메일·회의",
        "· 제한 고객사(운영 담당이 배포한 목록)와 관련된 항목",
        "· 휴가·연차·병가·근태·출장·외근·재택·부재 같은 근태·행방 항목, 종일·한가함·부재중·취소·거절 일정",
        "몇 건을 뺐는지 건수만 [수집·제외 현황]에 보입니다.",
    ]
    channels = [CHANNEL_TEXT[x] for x in ch] or ["수집 경로가 꺼져 있어 아무것도 모으지 않습니다."]
    channels += [
        ("메일과 일정만 읽습니다. 실시간으로 지켜보지 않고, 내가 화면에서 [분석 실행]·[Outlook 웹 읽기]를 누르거나 "
         f"{lmname.BAT_PREFIX}.bat 을 실행할 때만 정한 기간을 한 번 읽습니다."),
        ("전용 Edge 창의 Outlook·M365 사이트 자료(캐시)는 단계마다 지우고 로그인 정보만 남깁니다."
         if ("owa" in ch or copilot) else ""),
    ]
    ai = [
        "AI 는 회사 M365 Copilot 을 내 회사 계정으로만 씁니다. 다른 AI 서비스나 외부 서버로 보내지 않습니다.",
        ("Copilot 에는 위 '모으는 항목'에 적은 대로 이름·주소·번호를 가린 제목 목록(날짜와 받은·보낸·회의 구분 포함)과 "
         "업무 분류만 보냅니다. 보낸 사람 부호는 보내지 않고 내가 보낸 메일만 '나'로 표시합니다."),
        ("가린 회의 본문(안건)을 판정의 참고로 함께 보냅니다." if (body and body_ai) else "회의 본문은 Copilot 에 보내지 않습니다."),
        ("Copilot 으로 메일·일정 목록을 읽을 때는 참여자 이름을 받지 않고, 제목 속 사람 이름을 [사람]으로 바꿔 써 달라고 "
         "Copilot 에 요청합니다." if copilot else ""),
        "Copilot 에는 고객사·제품·과제·사람 이름과 약어를 쓰지 말고 업무 행위로 답하라고 요청합니다.",
        "모은 자료와 결과를 AI 학습에 쓰지 않습니다.",
        ("이 도구가 연 Copilot 채팅은 다 쓰면 지웁니다." if del_chats else ""),
        M365_LINE.format(extra=M365_COPILOT_EXTRA if copilot else ""),
    ]
    period = [
        f"분석 기간은 어제까지 최대 {mx}일입니다. 오늘은 넣지 않습니다.",
        f"더 긴 기간을 고르면 어제부터 거슬러 {mx}일로 줄이고, 줄였다는 사실을 화면에 알립니다.",
        "기간 밖의 자료는 분석할 때마다 뺍니다.",
    ]
    other_label = (retention.LABELS.get("other") or ("그 밖의 작업 파일",))[0]
    rows = [
        {"class": "raw", "item": "수집 자료(메일·일정 목록)", "where": "이 PC data\\outlook", "days": days["rawDays"]},
        {"class": "intermediate", "item": "중간 자료(신호·업무 분류·근거·캐시)", "where": "이 PC report·data\\cache",
         "days": days["intermediateDays"]},
        {"class": "result", "item": "분석 결과(Agentic AI 후보·워크플로우)", "where": "이 PC report", "days": days["resultDays"]},
        {"class": "html", "item": "개인 리포트(HTML)", "where": "이 PC report", "days": days["htmlDays"]},
        {"class": "share", "item": "공유 미리보기·보낸 사본", "where": "이 PC report\\share", "days": days["shareDays"]},
        {"class": "other", "item": other_label,
         "where": "이 PC data·report 의 나머지 파일, 설치 폴더의 ui_error.log, %TEMP%\\af32_* 파일",
         "days": days.get(retention.DAYS_KEY.get("other"), days["intermediateDays"])},
        {"class": "serverPersonal", "item": "공유한 개인 리포트", "where": "조직장 PC 의 팀 서버",
         "days": days["serverPersonalDays"]},
        {"class": "serverTeam", "item": "공유한 익명 팀 집계 기여분", "where": "조직장 PC 의 팀 서버",
         "days": days["serverTeamDays"]},
    ]
    retention_lines = [
        ("보관기한이 지나면 자동으로 지웁니다 — 화면을 열 때, 분석을 시작하고 끝낼 때. 팀 서버는 켤 때와 켜 둔 동안 한 시간마다 "
         "지우고, 꺼져 있을 때는 조직장 PC 의 매일 정리 작업이 지웁니다(그 작업을 만들지 못한 PC 에서는 서버를 켤 때 지웁니다)."),
        ("보관 일수는 파일이 마지막으로 바뀐 날부터 셉니다. 수집 자료는 그중 가장 나중에 바뀐 날(보통 마지막으로 모은 날)부터 "
         "세어 한꺼번에 지웁니다."),
        ("조직장 서버의 사본은 받은 날부터(익명 팀 집계 기여분은 받은 달 1일부터) 세고, 일수는 그 서버의 설정을 따릅니다 — "
         "보내기 전 확인 창에 그 서버의 보관기한이 보이고, "
         f"개인 리포트 {afcfg.RETENTION_MAX['serverPersonalDays']}일·익명 팀 집계 기여분 "
         f"{afcfg.RETENTION_MAX['serverTeamDays']}일보다 길게 두는 서버에는 보내지 않습니다."),
        ("설치 정보(data\\install.json)와 전용 Edge 창의 로그인 정보(data\\af32_edge)는 보관 일수로는 지우지 않고, "
         f"{WIPE_BUTTON}를 하면 지웁니다."),
        "공유 기록(data\\share_receipts.json)은 서버 사본의 보관기한까지 두고, 모두 지울 때 서버 사본을 지우는 데 씁니다.",
        ("모두 지운 뒤에도 남는 것: 지운 기록(data\\withdrawal.json — 지운 날짜와 서버 사본·Copilot 채팅 정리 결과), "
         "서버에서 아직 지우지 못한 공유 기록(지울 때까지 시작할 때마다 다시 지웁니다), "
         "설정 폴더(config — 내 이름을 적은 설정, 팀 서버 주소와 참여 코드, 내가 지정한 과제 목록, 제한 고객 목록). "
         "설치 폴더를 지우면 함께 지워집니다."),
    ]
    rights = [
        PAPER_CONSENT_LINE,
        WITHDRAW_PAPER_LINE,
        ("모두 지우면 이 PC 의 모은 자료·결과·설치 정보와 전용 Edge 창의 로그인 정보를 지우고, 조직장 서버에 공유한 사본도 "
         "지웁니다."),
        BUSY_NOTICE_LINE,
        ("모두 지울 때 이 도구가 연 Copilot 채팅도 다시 지워 보고, 지우지 못한 채팅이 있으면 그 수를 알립니다." if del_chats else
         "Copilot 채팅 지우기를 설정으로 꺼 두어 이 도구가 연 채팅은 지우지 않습니다 — Copilot 대화 목록에서 직접 지울 수 있습니다."),
        "서버 사본을 바로 지우지 못하면 다음에 시작할 때 다시 지우고, 조직장에게 삭제를 요청할 수 있으며, "
        "서버 보관기한이 지나면 자동으로 지워집니다.",
        ("모두 지우기가 중간에 끊기거나(창을 닫거나 PC 가 꺼진 때) 다른 프로그램이 연 파일을 지우지 못하면 다음에 시작할 때 "
         "마저 지웁니다. 다 지울 때까지 이 도구는 분석·수집·공유를 시작하지 않습니다."),
        "다 지운 뒤에는 이 도구를 다시 쓸 수 있습니다 — 다시 시작하면 새 설치 정보로 처음부터 시작합니다.",
        f"{DATA_TAB} 탭에서 모은 자료만 지울 수도 있습니다.",
        f"설치 폴더를 지우기 전에 {WIPE_BUTTON}를 하면 조직장 서버의 사본, 매일 정리 작업"
        + (", 이 도구가 연 Copilot 채팅" if del_chats else "") + "까지 함께 지웁니다.",
        "이 안내문은 이 PC 의 지금 설정대로 만든 것입니다. 서면으로 받은 안내와 다르면 쓰기 전에 문의처에 알립니다.",
        _contact_line(c),
    ]
    sharing = [
        "공유는 따로 고르는 일이고 하지 않아도 됩니다. 처음에는 꺼져 있고 자동으로 보내지 않습니다.",
        "공유할 때는 [공유] 탭에서 보낼 내용을 미리 보고 항목별로 고른 뒤, 받을 서버·조직·전송 방식·서버 보관기한을 확인하고 보냅니다.",
        "개인 리포트는 조직장만 볼 수 있습니다.",
        f"익명 팀 집계에는 이름이 들어가지 않습니다. 참여 인원이 {grp}명 이상일 때만 보이고, {cell}명 이상이 낸 후보만 이름이 나옵니다.",
        TEAM_FILE_LINE,
        SHARE_MASK_LINE,
        SHARE_CHECK_LINE,
        SHARE_FLAG_LINE,
    ]
    if sched:
        scheduled = [f"매일 한 번 Windows 작업 스케줄러의 내 사용자 작업('{lmname.PRODUCT} 보관기한 정리')이 보관기한이 지난 자료를 지웁니다.",
                     "분석을 시작할 때 그 작업이 없으면 만듭니다(모은 자료가 있으면 화면을 열 때도 만듭니다 · "
                     "만들지 못하면 그렇다고 알립니다). 작업이 있는지는 하루에 한 번만 확인합니다.",
                     "모두 지우면 이 작업도 지우고, 다음에 분석을 시작할 때 다시 만듭니다."]
    else:
        scheduled = ["매일 정리 작업은 꺼져 있습니다. 화면을 열 때와 분석을 시작하고 끝낼 때 보관기한이 지난 자료를 지웁니다.",
                     "예전에 만든 매일 정리 작업이 남아 있으면 이 도구를 시작할 때 지웁니다(하루에 한 번 확인합니다)."]
    return {
        "purpose": _sec("목적", [PURPOSE_LINE, "인사평가, 근태 확인, 업무량 비교, 사람 감시에는 쓰지 않습니다."]),
        "collected": _sec("모으는 항목", collected),
        "not_collected": _sec("모으지 않는 항목과 바로 빼는 항목", not_collected),
        "channels": _sec("읽는 곳", channels),
        "ai": _sec("AI 사용", ai),
        "period": _sec("분석 기간", period),
        "retention": _sec("보관기한", retention_lines, rows=rows),
        "rights": _sec("내 권리", rights),
        "sharing": _sec("공유", sharing),
        "scheduled_purge": _sec("매일 정리", scheduled),
    }


NOTICE_ORDER = ("purpose", "collected", "not_collected", "channels", "ai", "period", "retention", "rights", "sharing",
                "scheduled_purge")


def notice_text(cfg=None):
    """안내문을 사람이 읽을 글로(CLI --notice — 서면 양식에 붙일 수 있다 · 로그)."""
    n = notice(cfg)
    out = [f"[{lmname.DISPLAY_TITLE}] 안내", ""]
    for k in NOTICE_ORDER:
        s = n[k]
        out.append(f"■ {s['title']}")
        out += [("  " + x) for x in s["lines"]]
        for r in s.get("rows") or ():
            out.append(f"  · {r['item']} — {r['where']} — {r['days']}일")
        out.append("")
    return "\n".join(out)


def _today():
    """모두 지우기 기록의 날짜 — 'YYYY-MM-DD'(시각은 남기지 않는다 · D10)."""
    return time.strftime("%Y-%m-%d")


def _date10(v):
    """'YYYY-MM-DD…' → 'YYYY-MM-DD'. 날짜로 시작하지 않으면 그대로, 비었으면 None."""
    if isinstance(v, str):
        m = _DATE_RX.match(v)
        if m:
            return m.group(1)
    return v or None


def _path(root, name):
    return os.path.join(str(root or ROOT), "data", name)


def _read(root, name):
    try:
        with open(_path(root, name), encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _write(root, name, obj):
    r"""data\name 을 통째로 바꿔 쓴다(임시 파일 → os.replace). 임시 파일 이름은 프로세스·스레드마다 다르고(화면의 요청 스레드가
    함께 status 를 불러도 서로의 임시 파일을 덮지 않는다), 쓰지 못하면 임시 파일을 남기지 않는다."""
    p = _path(root, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _err(name, e):
    return {"path": "data\\" + name, "why": f"쓰지 못함({type(e).__name__})", "holder": ""}


def _date_only(root, name, d, keys):
    r"""예전 판이 남긴 시각(HH:MM)을 지운다 — 날짜만 남기고 그 파일을 다시 쓴다(D10). → 고친 dict(쓰지 못해도 고친 값).
    쓰기 바로 전에 다시 읽어 그사이 다른 프로세스가 고쳐 쓴 파일(예 막 시작한 모두 지우기의 in_progress 기록)은 덮어쓰지 않는다."""
    if not d:
        return d
    fix = {k: _date10(d[k]) for k in keys if isinstance(d.get(k), str) and _date10(d[k]) != d[k]}
    if not fix:
        return d
    nd = dict(d, **fix)
    try:
        if _read(root, name) == d:
            _write(root, name, nd)
    except OSError:
        pass
    return nd


def _wd_state(wd):
    """모두 지우기 기록의 상태 — in_progress · done · None(기록 없음). state 가 없는 예전 기록은 done."""
    if not isinstance(wd, dict) or not wd:
        return None
    s = wd.get("state")
    if s in (WD_IN_PROGRESS, WD_DONE):
        return s
    return WD_DONE if wd.get("withdrawn_at") else None


def status(root=None, cfg=None):
    """쓸 수 있는 상태인가 — {"accepted","other_user","unknown_owner","withdrawal_state","withdrawn_at","chats_left"}.
    accepted = 이 설치의 자료가 지금 Windows 사용자의 것이고(install.load — 설치 정보가 없는 빈 설치면 새로 만든다) 모두 지우기가
    진행 중(withdrawal_state 'in_progress')이 아니다. 그 밖에 보는 것은 없다(cfg 는 부르는 쪽 모양을 지키려고 받기만 한다).
    withdrawn_at = 마지막으로 모두 지운 날('YYYY-MM-DD') | None · chats_left = 그때 지우지 못한 Copilot 채팅 수."""
    ins = install.load(root)
    ins = ins if isinstance(ins, dict) else {}
    other = not ins.get("user_ok")
    unknown = bool(ins.get("unknown_owner") or ins.get("reason") == "unknown_owner")
    wd = _read(root, WITHDRAWAL_FILE) or {}
    if not other:
        wd = _date_only(root, WITHDRAWAL_FILE, wd, ("withdrawn_at",))
    wstate = _wd_state(wd)
    return {"accepted": bool(not other and wstate != WD_IN_PROGRESS),
            "other_user": other,
            "unknown_owner": unknown,
            "withdrawal_state": wstate,
            "withdrawn_at": _date10(wd.get("withdrawn_at")),
            "chats_left": _int(wd.get("chats_left"))}


def status_code(st):
    """--status 종료 코드 — 0 쓸 수 있음 · 4 다른 사용자·주인을 알 수 없는 자료 · 3 모두 지우기가 진행 중."""
    if st.get("accepted"):
        return 0
    if st.get("other_user") or st.get("unknown_owner"):
        return 4
    return 3


def require(root=None, cfg=None):
    """쓸 수 있으면 status, 아니면 ConsentRequired(reason) — 부르는 쪽은 그 문장을 보이고 e.code 로 끝낸다.
    "other_user"(code 4): 다른 사용자의 자료(install.OTHER_USER_MSG) · 주인을 알 수 없는 자료(install.UNKNOWN_OWNER_MSG).
    "withdrawn"(code 3): 모두 지우기가 진행 중(WIPING_MSG) — 다음 시작 때 resume_withdrawal 이 마저 지운 뒤에 쓸 수 있다."""
    st = status(root, cfg)
    if st["accepted"]:
        return st
    if st["other_user"]:
        raise ConsentRequired("other_user", UNKNOWN_OWNER_MSG if st["unknown_owner"] else None)
    raise ConsentRequired("withdrawn")


# ── 모두 지우기(함수·파일 이름은 예전 그대로 withdraw·withdrawal) ─────────────────────────────────
def _mark_withdraw(pending):
    r"""모두 지울 때 서버에서 아직 못 지운 영수증에 "withdraw": true 를 붙인다 — 시작할 때마다 다시 지우는 것
    (teamup.retry_withdrawals)은 이 표시가 있는 영수증뿐이다. 그 뒤에 새로 보낸 공유(표시 없음)는 지우지 않는다. → 표시를 새로 붙인 수."""
    lst = pending.get("receipts") if isinstance(pending, dict) else pending
    n = 0
    for r in lst if isinstance(lst, list) else []:
        if isinstance(r, dict) and r.get("withdraw") is not True:
            r["withdraw"] = True
            n += 1
    return n


def _mark_receipts(root, errors=None):
    r"""data\share_receipts.json 의 영수증에 지우기 표시를 붙여 다시 쓴다 → 남은 영수증 수. 예외를 내지 않는다(못 쓰면 errors)."""
    try:
        with open(_path(root, RECEIPTS_FILE), encoding="utf-8-sig") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return 0
    lst = obj.get("receipts") if isinstance(obj, dict) else obj
    if not isinstance(lst, list):
        return 0
    n = sum(1 for r in lst if isinstance(r, dict))
    if _mark_withdraw(obj):
        try:
            _write(root, RECEIPTS_FILE, obj)
        except OSError as e:
            if errors is not None:
                errors.append(_err(RECEIPTS_FILE, e))
    return n


def _chats_recorded(root):
    r"""전용 Edge 의 채팅 기록(data\af32_edge.chats.json)에 남은 '이 도구가 연 Copilot 채팅' 수 — owned[] (+ 기록에 아직 없는
    지금 채팅). 모두 지우기가 그 기록을 지우기 전에 센다. 없거나 깨졌으면 0."""
    try:
        with open(os.path.join(str(root), "data", CHATS_FILE), encoding="utf-8-sig") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return 0
    if not isinstance(st, dict):
        return 0
    owned = [e for e in st.get("owned") or [] if isinstance(e, dict) and e.get("key")] \
        if isinstance(st.get("owned"), list) else []
    n = len(owned)
    if st.get("ours") and _int(st.get("sent")) > 0 and not any(e.get("key") == st.get("key") for e in owned):
        n += 1
    return n


def _run_active(root):
    """이 설치 폴더의 분석·수집이 도는가 — retention.run_active(C5: data\\run.lock 의 살아 있는 run.py 또는 _busy)가 있으면 그것,
    없으면 _busy. 알 수 없으면 False(지우는 쪽이 개인정보에 안전하다)."""
    fn = getattr(retention, "run_active", None)
    try:
        return bool(fn(root)) if callable(fn) else _busy(root)
    except Exception:  # noqa: BLE001 - 모르면 막지 않는다
        return False


def _save_wd(root, wd, errors):
    try:
        _write(root, WITHDRAWAL_FILE, wd)
    except OSError as e:
        errors.append(_err(WITHDRAWAL_FILE, e))


def begin_withdrawal(root=None, cfg=None):
    r"""모두 지우기 ① — 분석·수집 작업이 돌면 WithdrawBusy(아무것도 쓰지도 지우지도 않는다). 아니면 data\withdrawal.json 에
    state 'in_progress' 를 먼저 쓰고 남은 공유 영수증에 지우기 표시를 붙인다 → 그 기록 dict. 이미 'in_progress' 면(끊긴
    지우기) 작업 확인 없이 그 기록을 잇는다(그동안 require 가 막아 새 작업은 시작하지 못한다)."""
    root = os.path.abspath(str(root or ROOT))
    wd = _read(root, WITHDRAWAL_FILE) or {}
    if _wd_state(wd) != WD_IN_PROGRESS:
        if _run_active(root):
            raise WithdrawBusy()
        wd = {"product": lmname.PRODUCT, "state": WD_IN_PROGRESS, "withdrawn_at": _today()}
    errors = []
    _save_wd(root, wd, errors)
    n = _mark_receipts(root, errors)
    wd.setdefault("server_withdrawal", {"pending": n})
    return wd


def _rm(path):
    """파일 하나 지우기(retention._rm_file — 읽기 전용 풀기·잠깐 잠긴 파일 다시) → 지웠나(없으면 참)."""
    rm = getattr(retention, "_rm_file", None)
    if callable(rm):
        return bool(rm(path))
    try:
        os.remove(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return not os.path.lexists(path)


def _left_files(root, errs):
    """지우지 못해 지금도 남아 있는 파일(설치 폴더 기준 상대 경로) — errors 가운데 보통 파일로 남은 것만 센다.
    들어가지 않은 연결 폴더·읽지 못한 폴더·%TEMP% 항목은 세지 않는다(다시 해도 같아 지우기를 끝내지 못하게 된다)."""
    out = []
    for e in errs:
        rel = str(e.get("path") or "") if isinstance(e, dict) else ""
        if rel and not rel.startswith("%") and os.path.isfile(os.path.join(root, rel)):
            out.append(rel)
    return out


def _complete(root, wd, *, unregister=True, chats_left=None):
    r"""모두 지우기 ④ 의 지우기 — 영수증 표시 → 남은 채팅 수 기록 → 큰 자료(purge_all keep_consent=True: 설치 정보·영수증·
    지우기 기록은 남는다) → 옛 판이 남긴 기록 파일(retention.OLD_FORM_FILES — 큰 자료와 함께 지워지지 않았으면) →
    설치 정보(LAST_FILES) → 예약 작업 → 'done'.
    큰 자료 가운데 지우지 못한 파일이 남으면(다른 프로그램이 연 파일) 설치 정보·매일 정리 작업을 그대로 두고 'in_progress' 로
    남긴다 — 남은 자료의 주인을 알고, 다음 시작(또는 매일 정리 작업)이 다시 지운다. 설치 정보를 못 지워도 같다."""
    errors = []
    n_pending = _mark_receipts(root, errors)
    n_chats = max(_int(chats_left), _int(wd.get("chats_left")), _chats_recorded(root))
    wd = dict(wd, product=lmname.PRODUCT, state=WD_IN_PROGRESS, chats_left=n_chats,
              withdrawn_at=_date10(wd.get("withdrawn_at")) or _today())
    wd.setdefault("server_withdrawal", {"pending": n_pending})
    _save_wd(root, wd, errors)
    res = retention.purge_all(root, keep_consent=True, keep_edge=False)
    deleted = _int(res.get("deleted"))
    perrs = [e for e in res.get("errors") or [] if isinstance(e, dict)]
    errors += perrs
    left = _left_files(root, perrs)
    for rel in getattr(retention, "OLD_FORM_FILES", ()) or ():        # 옛 판의 기록 파일 — 이름은 retention 이 안다
        p = os.path.join(root, *str(rel).replace("\\", "/").split("/"))
        if os.path.isfile(p):
            if _rm(p):
                deleted += 1
            else:
                errors.append({"path": str(rel).replace("/", "\\"), "why": "지우지 못함", "holder": ""})
                left.append(str(rel).replace("/", "\\"))
    if not left:
        for name in LAST_FILES:
            p = _path(root, name)
            if not os.path.lexists(p):
                continue
            if _rm(p):
                deleted += 1
            else:
                errors.append({"path": "data\\" + name, "why": "지우지 못함", "holder": ""})
                left.append("data\\" + name)
    done = not left
    removed = retention.unregister_task(root) if (unregister and done) else None
    wd["state"] = WD_DONE if done else WD_IN_PROGRESS
    _save_wd(root, wd, errors)
    return {"deleted": deleted, "errors": errors, "task_removed": removed, "pending_receipts": n_pending,
            "withdrawn_at": wd["withdrawn_at"], "chats_left": n_chats, "state": wd["state"]}


def withdraw(root=None, cfg=None, *, server_withdrawal=None, unregister=True, chats_left=None):
    r"""모두 지우기 ④ — begin_withdrawal(이미 했으면 그대로 — 작업 중이면 WithdrawBusy) → 남은 Copilot 채팅 수 기록 → 큰 자료부터
    지우기(retention.purge_all) → 설치 정보(마지막) → 매일 정리 작업 지우기(unregister) → data\withdrawal.json 'done'.
    data\share_receipts.json 에 남은 영수증(서버에서 아직 못 지운 것 — teamup.withdraw_all 이 지운 것은 이미 빠졌다)은 표시한 채 둔다.
    chats_left = ③ 의 sweep_owned 결과 'left'(없으면 채팅 기록에서 센다).
    → {"deleted","errors","task_removed","pending_receipts","withdrawn_at","chats_left","state"}. 지우다 못 지운 것은 errors —
    못 지운 파일이 남으면 state 는 'in_progress'(설치 정보·매일 정리 작업은 그대로 · task_removed None)이고 다음 시작 때
    resume_withdrawal 이 다시 지운다. 'done' 뒤에는 바로 다시 쓸 수 있다(다음 status 가 새 설치 정보를 만든다)."""
    root = os.path.abspath(str(root or ROOT))
    wd = begin_withdrawal(root, cfg)
    if server_withdrawal is not None:
        wd["server_withdrawal"] = server_withdrawal
    return _complete(root, wd, unregister=unregister, chats_left=chats_left)


def resume_withdrawal(root=None, cfg=None):
    r"""끝나지 않은 모두 지우기(끊겼거나 못 지운 파일이 남은 것)를 마친다 — data\withdrawal.json 의 state 가 'in_progress' 면
    withdraw 의 지우기(④)를 다시 한다 → 그 결과 + {"resumed": True}(아직 못 지운 것이 남으면 state 'in_progress'), 할 일이 없으면
    None. 서버 사본은 건드리지 않는다(표시한 영수증은 teamup.retry_withdrawals 가 시작할 때마다 다시 지운다) · 전용 Edge 를
    띄우지도 닫지도 않는다(남은 채팅은 기록에서 센 수만 남긴다) · 작업 확인을 하지 않는다(지우는 중에는 require 가 막아 새
    작업이 시작하지 못한다). 화면 시작·run.py 시작·retention --purge(매일 정리 작업 포함)가 부른다. 예외를 내지 않는다."""
    try:
        root = os.path.abspath(str(root or ROOT))
        wd = _read(root, WITHDRAWAL_FILE)
        if _wd_state(wd) != WD_IN_PROGRESS:
            return None
        res = _complete(root, wd, unregister=True)
    except Exception as e:  # noqa: BLE001 - 시작을 막지 않는다(다음 시작 때 다시)
        return {"resumed": True, "deleted": 0, "errors": [{"path": "", "why": f"지우기를 마치지 못함({type(e).__name__})",
                                                         "holder": ""}], "task_removed": None, "pending_receipts": 0,
                "withdrawn_at": None, "chats_left": 0, "state": WD_IN_PROGRESS}
    res["resumed"] = True
    return res


def withdraw_message(res):
    """모두 지우기의 결과(withdraw·cli_withdraw·resume_withdrawal) → 한국어 한 줄 — 무엇을 지웠고 무엇이 남았는지만 말한다.
    Copilot 채팅은 지우지 못한 수(CHATS_LEFT_MSG)를, 채팅 지우기를 설정으로 꺼 둔 때(cli_withdraw 의 edge.sweep 'off')는
    지우지 않았다는 것(CHATS_OFF_MSG)을 말한다. 조직장 서버에서 지운 공유 수는 res["server"]["removed"] 가 있을 때만(CLI)."""
    res = res if isinstance(res, dict) else {}
    s = f"이 PC 의 자료 {_int(res.get('deleted'))}개를 지웠습니다"
    n_err = len(res.get("errors") or [])
    unfinished = res.get("state") == WD_IN_PROGRESS
    if n_err and unfinished:
        s += f" · {n_err}개는 지우지 못했습니다 — 파일을 연 프로그램을 닫으면 다음에 시작할 때 마저 지웁니다"
    elif n_err:
        s += f" · {n_err}개는 지우지 못했습니다(파일을 연 프로그램을 닫은 뒤 {DATA_TAB} 탭에서 다시 지울 수 있습니다)"
    elif unfinished:
        s += " · 다 지우지 못한 자료는 다음에 시작할 때 마저 지웁니다"
    server = res.get("server") if isinstance(res.get("server"), dict) else {}
    if _int(server.get("removed")):
        s += f" · 조직장 서버의 공유 {_int(server.get('removed'))}건을 지웠습니다"
    if _int(res.get("pending_receipts")):
        s += " · 조직장 서버에서 아직 지우지 못한 공유는 다음에 시작할 때 다시 지웁니다"
    edge = res.get("edge") if isinstance(res.get("edge"), dict) else {}
    if edge.get("sweep") == "off":
        s += " · " + CHATS_OFF_MSG
    elif _int(res.get("chats_left")):
        s += " · " + CHATS_LEFT_MSG.format(n=_int(res.get("chats_left")))
    return s


# ── CLI ───────────────────────────────────────────────────────────────────────────────────
def _busy_in(listing, root, me=None):
    r"""프로세스 목록('pid<TAB>명령줄' 줄들)에 이 설치 폴더의 분석·수집 프로그램이 있나. 명령줄에 '<설치 폴더>\' 와 BUSY_SCRIPTS
    의 이름(또는 BUSY_SHARE 의 둘 — 보내는 중인 공유)이 함께 있어야 한다 — 'C:\AF32' 는 'C:\AF32b\run.py' 를 잡지 않는다.
    이 프로세스(me)와 이 모듈의 CLI(consent.py) 는 뺀다."""
    base = os.path.normcase(os.path.abspath(str(root))).rstrip("\\/").lower() + "\\"
    names = tuple(n.lower() for n in BUSY_SCRIPTS)
    me = str(os.getpid() if me is None else me)
    for ln in str(listing or "").splitlines():
        pid, _t, cmd = ln.partition("\t")
        cmd = cmd.lower().replace("/", "\\")
        if not cmd or pid.strip() == me or base not in cmd or "consent.py" in cmd:
            continue
        if any(n in cmd for n in names) or all(x in cmd for x in BUSY_SHARE):
            return True
    return False


def _proc_listing():
    r"""지금 도는 파이썬·PowerShell 프로세스의 'pid<TAB>명령줄' 줄들 — core\proc.process_list(BUSY_EXES)로 읽는다(새 프로세스를
    띄우지 않는다 · 명령줄을 유니코드 그대로 읽어 한글 설치 경로도 맞는다). 읽지 못했거나 목록에 이 프로세스가 없으면
    (믿을 수 없는 목록) None — 부르는 쪽이 PowerShell 로 다시 본다."""
    try:
        import proc
        rows = [(int(pid), str(cmd or "")) for pid, cmd in proc.process_list(BUSY_EXES)]
    except Exception:  # noqa: BLE001 - 다른 길로 다시 본다
        return None
    if not any(pid == os.getpid() for pid, _c in rows):
        return None
    flat = str.maketrans("\r\n\t", "   ")                      # 한 프로세스 = 한 줄('pid<TAB>명령줄')이 깨지지 않게
    return "\n".join(f"{pid}\t{cmd.translate(flat)}" for pid, cmd in rows if cmd.strip())


def _ps_listing():
    """같은 목록을 PowerShell 로(예전 길 — _proc_listing 이 None 일 때만 · UTF-8 로 받아 한글 경로도 맞춘다). 못 읽으면 ""."""
    try:
        import subprocess
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_PROCS],
                           capture_output=True, timeout=20, creationflags=0x08000000)
        return (p.stdout or b"").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - 모르면 막지 않는다(지우는 쪽이 개인정보에 안전하다)
        return ""


def _busy(root):
    """이 설치 폴더의 분석·수집 작업이 도는가(최선 — 프로세스의 명령줄을 본다). 알 수 없으면 False.
    retention.run_active 가 잠금이 없을 때마다 부른다 — 보통은 프로세스를 새로 띄우지 않는다(_proc_listing)."""
    if os.name != "nt":
        return False
    listing = _proc_listing()
    if listing is None:
        listing = _ps_listing()
    return _busy_in(listing, root)


def _module(path, name):
    """제품 모듈 하나(이미 불렀으면 그것) — path 를 sys.path 끝에 더한다(앞에 끼우지 않는다)."""
    if name in sys.modules:
        return sys.modules[name]
    if path not in sys.path:
        sys.path.append(path)
    return importlib.import_module(name)


def _refuse_not_mine(root, cfg):
    r"""CLI 의 모두 지우기(서버 사본·Copilot 채팅·전용 Edge 까지 다루는 길)는 내 자료에만 한다 — 다른 사용자의 자료·주인을 알 수
    없는 자료면 ConsentRequired("other_user")(code 4 · install.OTHER_USER_MSG 또는 UNKNOWN_OWNER_MSG). 상태만 읽는다 — 그런
    폴더에는 아무것도 쓰지 않는다(install.load 는 남의 자료·주인을 모르는 자료에 설치 정보를 만들지 않고, status 는 남의 기록을
    고쳐 쓰지 않는다). 끝나지 않은 내 모두 지우기('in_progress')는 막지 않는다 — 마저 지운다. → status."""
    st = status(root, cfg)
    if st["other_user"] or st["unknown_owner"]:
        raise ConsentRequired("other_user", UNKNOWN_OWNER_MSG if st["unknown_owner"] else None)
    return st


def cli_withdraw(root, cfg, *, teamup_mod=None, copilot_mod=None):
    """모두 지우기 ①~④(CLI) → withdraw 결과 + server·edge 요약. 다른 사용자의 자료·주인을 알 수 없는 자료면 ① 보다 먼저
    ConsentRequired("other_user")(_refuse_not_mine — 아무것도 쓰지 않았고 서버·전용 Edge 를 건드리지 않았다: 그 폴더의 전용 Edge 는
    그 사람의 로그인이다). ① 이 막으면 WithdrawBusy(아무것도 하지 않았다).
    ②③ 은 실패해도 ④ 를 한다. ③ 은 전용 Edge 가 꺼져 있으면 띄워 이 도구가 연 채팅을 지운다(C6 — launch=True)."""
    root = os.path.abspath(str(root))
    _refuse_not_mine(root, cfg)
    begin_withdrawal(root, cfg)
    server = None
    try:
        teamup = teamup_mod or _module(root, "teamup")
        r = teamup.withdraw_all(root, cfg, timeout=10)             # 지우기만 — 보내는 함수는 부르지 않는다
        server = r if isinstance(r, dict) else {"ok": bool(r)}
    except Exception as e:  # noqa: BLE001 - 서버 사본 지우기 실패는 영수증이 남아 다음 시작 때 다시 한다
        server = {"ok": False, "error": type(e).__name__}
    edge, left = {}, None
    try:
        ca = copilot_mod or _module(os.path.join(root, "tools"), "copilot_auto")
        rep = ca.sweep_owned(None, budget=getattr(ca, "SWEEP_BUTTON_SEC", CHAT_SWEEP_SEC), why="withdraw", launch=True,
                             lock_wait=CHAT_LOCK_WAIT) or {}
        edge["sweep"] = str(rep.get("code") or "")
        left = _int(rep.get("left"))
        edge["close"] = str((ca.close_own_edge(None, reason="withdraw", force=True, tidy=False) or {}).get("why") or "")
    except Exception as e:  # noqa: BLE001 - Edge 정리는 덤 — 지우기는 계속한다(남은 채팅 수는 기록에서 센다)
        edge["error"] = type(e).__name__
    res = withdraw(root, cfg, server_withdrawal=server, chats_left=left)
    res.update(server=server, edge=edge)
    return res


WIPE_WORD = "지우기"                                     # --withdraw 가 --yes 없이 받는 낱말
# --withdraw 가 내 자료가 아니어서 거절할 때 그 까닭(install.OTHER_USER_MSG·UNKNOWN_OWNER_MSG) 다음에 찍는 줄 — 어디서 지우는지
NOT_MINE_HINT = "이 명령으로는 지우지 않았습니다 — 화면({ui})의 [열지 않고 지우기]나 {bat} 에서 지울 수 있습니다"


def _cli_refused(e, as_json):
    """--withdraw 가 다른 사용자의 자료·주인을 알 수 없는 자료라 거절했다 — 까닭과 어디서 지우는지를 찍고 종료 코드(4)를
    돌려준다. 아무것도 쓰지도 지우지도 않았다."""
    hint = NOT_MINE_HINT.format(ui=f"{lmname.BAT_PREFIX}-UI.bat", bat=f"{lmname.BAT_PREFIX}.bat")
    if as_json:
        print(json.dumps({"ok": False, "error": e.reason, "msg": e.message, "hint": hint}, ensure_ascii=False))
    else:
        print(e.message)
        print(hint)
    return e.code


def _status_label(st):
    if st["accepted"]:
        return "쓸 수 있음" + (f"(마지막으로 모두 지운 날 {st['withdrawn_at']})" if st.get("withdrawn_at") else "")
    if st.get("unknown_owner"):
        return "주인을 알 수 없는 자료"
    if st["other_user"]:
        return "다른 사용자의 자료"
    return "모두 지우는 중(다음에 시작할 때 마저 지움)"


def _cli_status(root, as_json):
    try:
        if not os.path.isdir(root):
            raise FileNotFoundError(root)
        cfg, _w = afcfg.load_effective(root)
        st = status(root, cfg)
    except Exception as e:  # noqa: BLE001 - 상태를 모르면 1
        print(json.dumps({"error": type(e).__name__}) if as_json else f"상태를 읽지 못했습니다({type(e).__name__})")
        return 1
    print(json.dumps(st, ensure_ascii=False) if as_json else _status_label(st))
    return status_code(st)


def _main(argv):
    def arg(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None
    root = os.path.abspath(arg("--root") or ROOT)
    as_json = "--json" in argv
    if "--status" in argv:
        return _cli_status(root, as_json)
    cfg, _w = afcfg.load_effective(root)
    if "--notice" in argv:
        print(notice_text(cfg))
        return 0
    if "--withdraw" in argv:
        try:
            _refuse_not_mine(root, cfg)                 # 낱말을 묻기 전에 — 내 자료가 아니면 아무것도 하지 않는다(4)
            if "--yes" not in argv:
                try:
                    ans = input(f"이 PC 의 내 자료와 조직장 서버의 사본을 모두 지우려면 '{WIPE_WORD}' 를 입력하세요: ").strip()
                except EOFError:
                    ans = ""
                if ans != WIPE_WORD:
                    print("지우지 않았습니다.")
                    return 1
            res = cli_withdraw(root, cfg)
        except ConsentRequired as e:
            return _cli_refused(e, as_json)
        except WithdrawBusy as e:
            print(json.dumps({"ok": False, "error": "busy", "msg": e.message}, ensure_ascii=False) if as_json else e.message)
            return 1
        res["msg"] = withdraw_message(res)
        print(json.dumps(res, ensure_ascii=False) if as_json else res["msg"])
        return 1 if res["errors"] else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
