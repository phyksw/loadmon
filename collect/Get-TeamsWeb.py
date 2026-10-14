# -*- coding: utf-8 -*-
"""
Get-TeamsWeb.py — 팀즈 웹(teams.microsoft.com)을 전용 Edge 프로필로 열어 채팅을 읽는다 (폴백).

Get-OutlookWeb.py 와 같은 방식이다: Copilot 에 쓰는 전용 Edge 프로필(data\\lm29_edge)에 회사 계정으로
한 번 로그인해 두면, **팀즈 앱이 꺼져 있어도** 동작한다. 앱 창 읽기(Get-TeamsWindow.ps1)는 화면에 그려진
부분만 UI 자동화로 긁으므로 창 크기·테마·팀즈 버전에 따라 PC 마다 0건이 되곤 했다(실측 제보). 웹 경로는
화면 렌더가 아니라 문서 구조(role·data-tid·aria-label)를 읽으므로 그 편차가 없고, 스크롤로 지난 날짜까지
거슬러 올라간다.

  python collect\\Get-TeamsWeb.py --from 2026-06-01 --to 2026-06-30 [--max-chats 200] [--budget 900] [--force]

출력: data\\m365\\teams_web.csv   (time,from,chat,kind,replied_time,summary,time_precision)
      — Graph·창 읽기 경로와 같은 스키마(+ 끝 열 time_precision: minute | date — 메일 웹 수집기와 같은 약속, date 면 12:00 은
        자리표)라 분석기(core\\extract.py 의 teams_*.csv)가 그대로 인제스트한다.
      이미 있는 teams_*.csv 전부와 대조해 같은 메시지는 다시 적지 않는다(경로가 겹쳐도 중복 계상 없음).
      data\\m365\\teams_web_rooms.json — 방 커서 {ver: '<판>|<collect.cursorEpoch>', rooms: {sha1(방)[:12]:
      {status, oldest, newest_read, …}}, dom_census: {…}} (메시지 원문 없음 — newest_read 는 해시, dom_census 는 화면 구조만).
      ver 가 다르면 버리고 처음부터 읽는다.
종료 코드(= LMSTATUS rc, LM28): 0 새 행 저장 / 1 기간에 활동한 방 없음 / 2 로그인 필요(전용 Edge 창에서 1회 · R-LOGIN·R-PERSONAL)
          / 3 불가·불완전(R-WEBSEL 목록·스크롤 영역 못 찾음 · R-ROOMGONE · R-TIMEOUT · R-EDGEBUSY · Edge 기동 사유) / 4 새 행 0
          (LM24 의 '기존 누적이 있으면 0' 은 없앴다 — 이번 실행이 읽은 것으로만 정한다.)
마지막 줄: LMSTATUS {v,src:'teams_web',rc,reason,counts,ranges[{axis:'teams',from,to,st}]}
          counts: rooms_listed·list_end·opened·complete·incremental_ok·cut_budget·cut_no_scroller·roomgone·rows_new·teams_present
                  · open_notfound·pane_stuck·open_same_pane·open_by_sel·open_by_title·open_by_conv·open_by_doc·open_by_content
                  · click_<방법>·click_<방법>_doc·read_cand·read_gen·list_expanded·list_collapsed(+진단 · dom_census)

LM28 '읽음' 규칙(F-06·F-07·F-30·C-21·W1-05 — 검증된 방만 읽음으로 적는다):
  · 목록은 가상 스크롤을 끝까지 내린다(새 방 0 화면 3번 또는 끝). 상한 teamsWebMaxChats(기본 200, 0 = 무제한).
    마지막 활동이 기간 시작 전인 방은 열지 않는다. 지난 실행에서 잘린 방(cut·roomgone)을 먼저 연다.
  · LM28-TW-2(2026-10-11 회사 PC 실측 '목록 61 · 열기 못찾음 10 · 화면멈춤 2(빈2)' 뒤 다시 짬) — 방을 이름으로 다시 찾지 않는다:
    목록을 위에서부터 한 화면씩 걸으며(1차: 끝까지 모으며 잘린 방을 연다 · 2차: 맨 위로 되돌려 남은 방을 연다) 그 화면 스냅샷의
    항목을 그 자리에서 누른다. 누르기 직전에 같은 순번의 항목이 같은 대화 ID/안정 이름인지 확인하고, 다르면 그 화면에서
    ID → 안정 이름(가장 가까운 순번) 순으로 다시 맞춘다. 방 커서 열쇠는 대화 ID, 없으면 안정 이름(teams_parse.room_id).
    안정 이름 = aria-label 첫 조각(항목의 잎 글과 같을 때) → aria-labelledby 첫 요소 글 → 첫 줄의 잎(시각·숫자뿐인 배지·단추·
    아바타 글·두 번째 줄 미리보기 제외, 굵은 잎 먼저). 마우스를 올리면 바뀌는 시각·단추 글은 이름이 되지 않는다.
    구역 머리(aria-expanded 가 있거나 안에 다른 항목을 품은 항목)는 방이 아니다 — 누르지 않는다(지난 판은 머리가 안쪽 방의 대화
    ID 를 물려받아 방으로 보였고, 누르면 구역이 접혀 나머지 방을 못 찾았을 수 있다). 닫힌 최상위 구역은 1차에서 펼친다
    (실행마다 EXPAND_MAX 번) — 못 펼친 구역이 남으면 목록 끝이 아니다(그 안의 방이 기간에 활동했을 수 있다).
  · 방 전환은 확인한다: 먼저 '앞 방 그대로'를 막는다 — 지금 화면 메시지 지문(data-mid·<time datetime>+글 해시)의 절반 이상이
    앞 방에서 본 것이면 아니다. 그다음 ① 목록 항목의 선택 표시가 이 방 ② 지금 대화 ID(주소·탭 세션 기록·머리 id)가 이 방 키
    ③ 머리 제목이 이 방 이름과 맞고 누른 뒤 화면이 바뀜 ④ 창 제목(document.title '채팅 | <방> + n | Microsoft Teams')의 방 조각이
    이 방(teams_parse.doc_fits)이고 메시지가 바뀜(또는 누르기 전부터 이 방이 열려 있었음) ⑤ 머리 제목을 못 찾는 화면에서 메시지가
    모두 새 ID 로 바뀜 — 중 하나면 읽는다(창 제목이 다른 방을 말하면 ①·⑤ 는 쓰지 않는다). 아니면 R-ROOMGONE.
    누르기(통한 방법을 다음 방부터 먼저): 신뢰 입력 마우스(CDP Input.dispatchMouseEvent 옮김→누름→뗌 — 항목 왼쪽~가운데의 보이는
    점, 오른쪽 '…' 단추·좁은 단추·링크는 피하고 scrollIntoView 뒤 뷰포트 안인지 확인) → 합성 사건(isTrusted=false 를 받는 화면) →
    포커스 + CDP 키 Enter. 앞 시도가 연 메뉴는 CDP Escape 로 닫는다. 처음부터 12방 연속 실패면 남은 방은 열지 않는다.
  · 메시지 후보(data-tid)가 하나도 안 맞으면(또는 맞은 후보에 시각이 없으면) 일반 읽기: 대화 영역(목록 밖)의 time[datetime] 을
    붙잡아 메시지 단위(그 시각만 품은 가장 큰 조상 — li·listitem·article·group·data-tid*=message 한 메시지가 시각 둘을 품으면 그것,
    같은 부모 아래 비슷한 형제 행은 함께)로 묶고, 작성자 = [data-tid*=author]·[id^=author-] 또는 시각 앞 같은 줄의 짧은 잎,
    본문 = 작성자·시각을 뺀 가장 긴 글 덩어리. 날짜 구분선·되감기·지문도 이 단위로 한다. 머리 후보가 없으면 창 제목의 방 조각을
    CSV 방 이름으로 쓴다(정규화해 목록 이름과 같을 때만 — 지난 판 규칙).
  · 화면 구조 진단(현장 사진 한 장으로 원인 확정): 끝의 요약 줄 앞에 '[teams-web] 구조: …'(후보별 개수·실패 사유별 수·확인 근거별 수·
    선택 표시·대화 ID 출처·통한 누르기)와 '[teams-web] 구조+: …'(창 제목 꼴·누르기 방법별 시도/창 제목 바뀜·대화 영역 시각 수·
    대화 영역 data-tid 상위 8·목록 항목 잎 꼴·aria-level/expanded·읽은 경로·문서 보임) 두 줄을 찍고, 같은 것과 가린 골격을
    LMSTATUS counts.dom_census 와 teams_web_rooms.json 의 dom_census 에 남긴다(글자 없음 — 태그·role·data-tid·aria 이름·값 길이·
    개수·가린 꼴, 4KB 안).
  · 위로 되감기: 'top' 이면 6초까지 지난 메시지 로드를 기다린다(3번 연속 높이 증가가 없을 때만 맨 위 확인 = complete).
    'no-scroller' 면 스크롤되는 조상을 다시 찾고, 그래도 없으면 cut_no_scroller('처음까지 읽음'이 아니다).
    되감기 상한 teamsWebMaxScroll(기본 60). 기간 시작 전 날짜에 닿으면 complete.
  · 다음 실행: complete·incremental_ok 방은 최신부터 읽다가 지난 newest_read 와 같은 메시지가 나오면 멈춘다(incremental_ok —
    겹침으로 검증). 목록의 마지막 활동 날짜·미리보기가 지난 확인 때와 같고 오늘이 아니면 열지 않는다(새 메시지 없음).
    newest_read 는 complete·incremental_ok 일 때만 앞으로 옮긴다.
  · 날짜는 <time datetime> 를 우선하고, 머리 조각(시각·title·aria-label)과 날짜 구분선에서만 찾는다(본문 날짜 금지).
    날짜를 못 짚은 메시지는 버린다. 작성자가 없는 연속 메시지는 직전 작성자를 잇는다(내 말풍선은 '나').
  · LM28-TW-3(야근이 덜 잡히던 것 — E): 날짜만 짚은 메시지는 버리지 않고 time_precision=date 로 남긴다(정오를 시각으로 지어내지
    않는다 — 분석은 '그날 일했다' 는 흔적으로만 쓴다). 내 말풍선은 제 클래스·자손 표지 → 조상 표지(대화 칸 안쪽·다른 메시지를 품지
    않은 조상) → 위치 규칙(오른쪽 붙음·작성자 없음 = 나) 순으로 본다. '나' 이름에 로그온 화면 표시명을 보탠다. 저장은 지난 판의
    날짜만 행을 분 단위로, 남의 말로 적힌 내 메시지를 내 발신으로 제자리에서 바로잡는다(Store). '구조:' 줄 끝에 '내 메시지 n/m ·
    판정불가 k · 이어받음 j'(판정불가인데 직전 작성자를 이어받은 행 — 내 말이 남의 말로 적혔을 수 있다).
  · 방마다 저장한다(예산에 끊겨도 앞 방은 남는다). 중복 키는 teams_parse.key_of(날짜 포함 · 정제된 글).
  · 일자 판정(teams 축): teams_parse.day_ranges — 목록 끝(또는 마지막 방이 d 보다 오래됨) + 마지막 활동 ≥d 인 모든 방을
    d 이하까지 읽음이면 ok, 그 밖은 partial. 오늘은 ok 대신 partial.
  · 전용 Edge 는 copilot_auto.edge_lock 안에서만 쓰고(다른 작업과 직렬), 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다).

Copilot 과 달리 LLM 을 거치지 않으므로 지어낸 행이 없고, 데이터는 PC 밖으로 나가지 않는다(브라우저가 내
채팅을 보여주는 것을 읽을 뿐이다). replied_time 은 웹에서도 측정할 수 없어 빈 값(미측정)으로 둔다.

화면 구조는 Microsoft 가 바꿀 수 있어 선택자를 여러 벌 두고 '무엇으로 몇 개를 잡았는지' 를 로그·counts.selector_diag 에
남긴다(회사 PC 의 원문을 밖으로 보낼 수 없으므로 진단은 숫자로 한다).
시험: tests\\fakes\\fake_teams.py(FakeTeams — 이 모듈 JS 상수의 머리 표식 /*LM28:tw_…*/ 에 각본 응답). LM24 의
      LM_TEAMSWEB_FAKE(화면 응답 JSON) 주입은 방 확인·되감기 판정을 흉내 낼 수 없어 없앴다.
"""
import csv
import glob
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import owa_parse  # noqa: E402  — 목록 날짜 조각(오늘·요일·어제·M/D) 해석
import teams_parse  # noqa: E402  — LM28 순수 판정(키·방 판정·일자 판정)

OUT_DIR = os.path.join(ROOT, "data", "m365")
# time_precision(LM28 E — 메일 웹 수집기와 같은 약속): minute(시각을 짚음) · date(날짜만 — time 의 12:00 은 자리표, 분석이 시각
# 근거로 쓰지 않는다). 예전 6열 파일은 다음 저장 때 7열로 다시 쓴다(빈 값 = 시각 있음).
HDR = "time,from,chat,kind,replied_time,summary,time_precision"
# 방 커서 판 — teams_web_rooms.json 의 ver '판|collect.cursorEpoch'(TW-2: 방 열쇠가 안정 이름으로 바뀜 · TW-3: 내 말풍선 판정
# (조상 표지·위치 규칙)·날짜만 메시지 보존 — 지난 판이 남의 말로 적은 내 메시지를 다시 읽어 바로잡게 처음부터 읽는다)
COLLECTOR_VER = "LM28-TW-3"
STATE_NAME = "teams_web_rooms.json"
TEAMS_URL = "https://teams.microsoft.com/"          # LM28: 문서에 없는 /v2/ 경로 대신 시작 주소(도착 호스트는 cloud.microsoft 일 수 있다)
HOSTS = ("teams.microsoft.com", "teams.cloud.microsoft", "teams.office.com")
PERSONAL_HOSTS = ("teams.live.com",)                # 개인용 Teams — 업무 채팅이 아니다(R-PERSONAL)
SUMMARY_MAX = 200               # 창 읽기 경로와 같은 길이
MAX_CHATS = 200                 # teamsWebMaxChats 기본(0 = 무제한)
MAX_SCROLL = 60                 # teamsWebMaxScroll 기본 — 방 하나를 위로 되감는 횟수 상한
LIST_STALL = 3                  # 목록: 새 이름 0 화면이 이만큼 이어지면 끝
LIST_SCREENS = 400              # 목록 화면 상한(안전)
EXPAND_MAX = 4                  # 닫힌 최상위 구역을 펼쳐 보는 횟수 상한(실행마다)
INPUT_TIMEOUT = 8               # CDP 입력(마우스·키) 한 번의 응답 상한(초) — 넘으면 연결을 다시 잇고 그 방법은 그만 쓴다
ROOM_STALL = 3                 # 방: 되감아도 새 항목이 없는 화면이 이만큼 이어지면 그 방은 여기까지(cut)
TOP_CONFIRM = 3                 # 'top' 뒤 높이 증가 없는 확인 횟수(× TOP_WAIT = 6초)
TOP_WAIT = 2.0
SCROLL_WAIT = 1.8               # 되감기 뒤 지난 메시지가 붙기를 기다리는 상한
OPEN_WAIT = 2.5                 # 방 전환 확인 대기 — 누르는 방법 하나마다(첫 방법은 2배)
OPEN_ABORT = 12                 # 처음부터 이만큼 연속 전환 실패(확인 0)면 남은 방은 열지 않는다(다음 실행이 다시 — '구조' 줄로 원인 확정)
STALE_RATIO = 0.5               # 지금 화면 메시지 지문 중 앞 방에서 본 것이 이 비율 이상이면 '앞 방 그대로'
CENSUS_MAX = 3900               # dom_census 직렬화 상한(UTF-8 바이트) — last_run.json·진단 묶음의 4KB 안
CUT_STATES = ("cut_budget", "cut_no_scroller", "roomgone")
_sleep = time.sleep             # 시험(FakeTeams)이 대기를 가짜 시계로 바꿀 수 있게
_mono = time.monotonic


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else d


def log(msg):
    print(f"[teams-web] {msg}")
    sys.stdout.flush()


def _load_cfg():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ── 날짜·시각 해석은 메일 웹 수집기의 것을 그대로 쓴다 ────────────────────────
# 같은 회사 PC 의 같은 지역 설정에서 이미 검증된 해석기다. 여기서 다시 만들면 한·영·일·중 표기와
# 미국식/유럽식 순서를 또 틀리게 된다(메일 쪽 감사에서 이미 겪은 항목).
_spec = importlib.util.spec_from_file_location("_owa", os.path.join(_HERE, "Get-OutlookWeb.py"))
_owa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_owa)
find_times = _owa.find_times
find_date = _owa.find_date

TODAY_W = ("오늘", "today", "今日", "今天")
YDAY_W = ("어제", "yesterday", "昨日", "昨天")
# 요일 이름 → 월=0. 한 글자('월')는 '8월' 과 섞이므로 두 글자 이상만 본다.
WDAY = {}
for _i, _ws in enumerate((("월요일", "monday", "mon"), ("화요일", "tuesday", "tue"), ("수요일", "wednesday", "wed"),
                          ("목요일", "thursday", "thu"), ("금요일", "friday", "fri"), ("토요일", "saturday", "sat"),
                          ("일요일", "sunday", "sun"))):
    for _w in _ws:
        WDAY[_w] = _i


def _norm(s):
    return teams_parse.norm_name(s)


def logon_display_name():
    r"""로그온 화면 표시명(HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI 의 LastLoggedOnDisplayName —
    회사 AD 표시명 = 팀즈 표시명이 대부분). 마지막 로그온 계정(LastLoggedOnSAMUser, 없으면 LastLoggedOnUser)의 끝 조각이 지금
    USERNAME 일 때만(Get-TeamsWindow.ps1 과 같은 규칙). 못 읽으면 ''. 프로세스를 띄우지 않는다."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI") as k:
            def _v(name):
                try:
                    return str(winreg.QueryValueEx(k, name)[0] or "").strip()
                except OSError:
                    return ""
            name, user = _v("LastLoggedOnDisplayName"), _v("LastLoggedOnSAMUser") or _v("LastLoggedOnUser")
    except (ImportError, OSError):
        return ""
    me = str(os.environ.get("USERNAME") or "").strip().lower()
    return name if (name and user and me and user.split("\\")[-1].strip().lower() == me) else ""


def self_names(cfg):
    """'나' 로 볼 표시 이름 — config.owner · teamsSelfNames · Windows 계정 · 로그온 표시명(LM28 E) · 팀즈가 쓰는 '나/You'."""
    out = {"나", "you", "본인", "me", "자신"}
    vals = [cfg.get("owner"), os.environ.get("USERNAME"), logon_display_name()]
    vals += list(cfg.get("teamsSelfNames") or [])
    for v in vals:
        v = _norm(v)
        if v:
            out.add(v)
    return out


def rel_date(text, today):
    """'오늘'·'어제'·요일 이름 → date. 요일은 오늘 이전의 가장 가까운 그 요일(팀즈는 최근 6일을 요일로 보여준다)."""
    t = str(text or "").lower()
    if any(w in t for w in TODAY_W):
        return today
    if any(w in t for w in YDAY_W):
        return today - timedelta(days=1)
    for w, wd in WDAY.items():
        if w in t:
            back = (today.weekday() - wd) % 7
            return today - timedelta(days=back or 7)
    return None


def iso_dt(s):
    """<time datetime="…"> 값 → 이 PC 시간대의 datetime(분까지). 팀즈 웹은 이 속성을 UTC(끝의 Z)로 준다 —
    그대로 쓰면 한국에서 9시간 어긋나 새벽 근무로 둔갑한다. LM28: owa_parse.iso_local 로(두 웹 수집기가 같은 해석)."""
    r = teams_parse.iso_local(s)
    if not r:
        return None
    d, (hh, mi) = r
    return datetime(d.year, d.month, d.day, hh, mi)


# '오전 9시 12분' 처럼 콜론 없는 표기 - 팀즈의 제목 속성(title)은 이 형태로 자주 온다.
# 메일 쪽 해석기(RE_TIME)는 콜론·마침표만 받으므로 여기서 '9:12' 로 바꿔 넘긴다.
# 메일 수집기를 고치면 이미 검증된 메일 해석에 위험이 가므로 팀즈 쪽에서만 정규화한다.
RE_HM_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时]\s*(\d{1,2})\s*[분分]")
RE_H_WORD = re.compile(r"(?<!\d)(\d{1,2})\s*[시時时](?!\s*\d|간)")


def hm_words(s):
    s = RE_HM_WORD.sub(lambda m: f"{m.group(1)}:{int(m.group(2)):02d}", str(s or ""))
    return RE_H_WORD.sub(lambda m: m.group(1) + ":00", s)


def stamp(head, body, cur_date, d0, d1, today):
    """(날짜, 시각) 을 뽑는다 → (datetime, 'iso'|'full'|'sep'|'rel'|'date') 또는 (None, 사유).
    'date'(LM28 E) = 날짜만 안다 — datetime 의 12:00 은 자리표(time_precision=date 로 저장, 분석이 시각 근거로 쓰지 않는다).
    예전엔 머리에 날짜만 있으면 정오를 시각으로 지어냈고, 시각이 하나도 없으면 날짜 구분선이 있어도 메시지를 버렸다.

    ★ 날짜는 **머리 조각(head)에서만** 찾는다. head = <time datetime> · 타임스탬프 · title 속성 ·
    aria-label 처럼 화면이 '이 메시지의 시각' 이라고 말해 주는 것들이고, body 는 본문이다.
    본문에는 '지난 회의(2026-06-12) 결론대로' 같은 **다른 날짜**가 흔히 적혀 있어서, 그것을 쓰면
    9월 메시지가 6월 신호가 된다 — 그러면 6월 리뷰에 하지도 않은 최근 일이 등장한다(제보).
    창 읽기 수집기는 이미 같은 이유로 헤더와 본문을 나눠 본다(Get-TeamsWindow.ps1 의 '본문의
    8/15 까지는 날짜로 보지 않는다'). 웹 쪽에도 같은 규칙을 둔다.

    날짜 구분선(cur_date)은 화면이 직접 알려 준 그 날이라 **본문 추측보다 항상 앞선다**.
    날짜를 끝내 못 짚으면 그 메시지는 버린다 — 시각만 있는 줄에 오늘 날짜를 붙이면 지난 달
    대화가 전부 오늘로 몰린다(창 읽기에서 겪은 실측 결함)."""
    head = [hm_words(x) for x in head if x]
    body = [hm_words(x) for x in body if x]
    for s in head:                       # <time datetime> 가 맨 앞 — 지역 표기보다 우선(C-21)
        v = iso_dt(s)
        if v:
            return v, "iso"
    for s in head:                       # 제목 속성에 '2026년 6월 3일 오후 3:24' 같은 완전한 표기가 오는 경우
        d = find_date(s, d0, d1)
        if not d:
            continue
        hm = find_times(s)
        if hm:
            return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "full"
        # 머리에 날짜만 — 시각은 머리의 다른 조각·본문 앞머리('홍길동 오후 3:24')에서 찾아 그 날짜에 쓴다(LM28 E)
        for s2 in head + body:
            hm = find_times(s2)
            if hm:
                return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "full"
        return datetime(d.year, d.month, d.day, 12, 0), "date"
    # 시각은 본문 앞머리에서 와도 된다(화면이 '홍길동 오후 3:24' 를 한 덩어리로 그리는 스킨) —
    # 날짜만 본문에서 오면 안 된다.
    hm = None
    for s in head + body:
        hm = find_times(s)
        if hm:
            break
    if not hm:
        if cur_date:                      # 시각은 끝내 없지만 날짜 구분선이 그 날을 말해 준다 — 날짜만으로 남긴다(LM28 E)
            return datetime(cur_date.year, cur_date.month, cur_date.day, 12, 0), "date"
        return None, "시각 없음"
    if cur_date:                          # 날짜 구분선이 알려준 그 날 (팀즈 웹은 날짜마다 구분선을 그린다)
        return datetime(cur_date.year, cur_date.month, cur_date.day, hm[0][0], hm[0][1]), "sep"
    for s in head:
        d = rel_date(s, today)
        if d:
            return datetime(d.year, d.month, d.day, hm[0][0], hm[0][1]), "rel"
    return None, "날짜 없음"


RE_AUTHOR = re.compile(r"^\s*([^\d,|]{2,20}?)\s*(?:님이|님|씨)?\s*(?:,|said|says|wrote|은|는)\b")


def explicit_author(it):
    """화면이 '이 메시지의 작성자' 라고 말한 이름 — data-tid 로 잡힌 이름, 없으면 aria-label 의 첫 토큰. 없으면 ""."""
    a = (it.get("author") or "").strip()
    if 1 < len(a) <= 40:
        return a
    m = RE_AUTHOR.match(it.get("label") or "")
    if m:
        a = m.group(1).strip()
        if 1 < len(a) <= 40 and not find_times(a):
            return a
    return ""


def author_of(it, texts):
    """발신자 — data-tid 로 잡힌 이름이 우선, 없으면 aria-label 의 첫 토큰, 그래도 없으면 첫 잎 글자(이름이 맨 앞인 스킨)."""
    a = explicit_author(it)
    if a:
        return a
    for s in texts[:2]:                   # 렌더 순서상 이름이 맨 앞에 오는 스킨
        s = s.strip()
        if 1 < len(s) <= 40 and not find_times(s) and not find_date(s):
            return s
    return ""


def body_of(it, texts, author, ts):
    b = (it.get("body") or "").strip()
    if len(b) >= 3:
        return b
    drop = {_norm(author), _norm(ts)}
    out = [s for s in texts if _norm(s) not in drop and len(s.strip()) >= 2]
    return re.sub(r"\s{2,}", " ", " ".join(out)).strip()


# ── 화면 읽기 스크립트(머리 표식 /*LM28:이름*/ — 시험의 FakeTeams 가 이 표식으로 응답을 고른다) ──────────
# LM28(2026-10-08 회사 PC 실측 — 새 Teams 웹 v2): 목록 61개는 찾았는데 61개 모두 '전환 실패'. 머리 제목·메시지·선택 표시
# 선택자가 하나씩만 있어 그 화면과 어긋나면 어느 방도 전환을 확인하지 못했다. 그래서 선택자를 '여러 후보 + 기능 판별'로 두고
# (앞 후보부터 · 실제로 맞은 후보 run.pref 를 다음 방부터 먼저), 무엇이 몇 개 맞았는지를 '구조' 줄·dom_census 로 남긴다.
# 후보 출처: 공개 코드(gediz/teams-web-chat-exporter 의 DOM 폴백 — chat-pane-item·chat-pane-message·channel-pane-message·
# message-body·[id^="message-body-"]·[id^="content-"]·[id^="author-"]·[id^="chat-header-"] h2·[id^="chat-topic-person-"]·
# message-pane-list-viewport·chat-message-list·time[datetime]·.fui-Divider__wrapper·탭 세션 기록 mainWindowNavHistory) + LM24·LM27 판.
_LIST_SELS = ['[data-tid="chat-list"] [data-tid="chat-list-item"]', '[data-tid="chat-list-item"]',
              '[data-tid="chat-list"] [role="treeitem"]', '[role="tree"] [role="treeitem"]',
              '[role="list"] [role="listitem"][data-tid]', '[role="listbox"] [role="option"]']
_LIST_CODE = ["chat-list>item", "chat-list-item", "chat-list>treeitem", "tree>treeitem", "list>listitem", "listbox>option"]
# 목록 후보마다 '항목 하나'의 선택자(맨 끝 조각) — 항목 안에 이것이 또 있으면 구역 머리(중첩 트리), 대화 ID·잎 글은 제 것만 본다
_LIST_ITEM = ['[data-tid="chat-list-item"]', '[data-tid="chat-list-item"]', '[role="treeitem"]', '[role="treeitem"]',
              '[role="listitem"][data-tid]', '[role="option"]']
# 메시지 후보 (선택자, 구조 줄 약칭, 본문 단위 — True 면 메시지 본문 요소라 항목은 가장 가까운 li·listitem·article)
_MSG = [('[data-tid="chat-pane-item"]', "pane-item", False),
        ('[data-tid="chat-pane-message"]', "pane-msg", False),
        ('[data-tid="channel-pane-message"]', "chan-msg", False),
        ('[data-tid="message-pane-list-viewport"] [role="listitem"]', "vp-li", False),
        ('[data-tid="chat-message-list"] [role="listitem"]', "list-li", False),
        ('[data-tid="message-pane"] [role="listitem"]', "mpane-li", False),
        ('[role="log"] [role="listitem"]', "log-li", False),
        ('[data-tid="message-body"]', "msg-body", True),
        ('[id^="message-body-"]', "id-body", True),
        ('[role="main"] [role="listitem"]', "main-li", False)]
_MSG_SELS = [m[0] for m in _MSG]
# 대화 머리 후보 (선택자, 약칭) — 단체방 [id^="chat-header-"] h2 · 1:1·나와의 대화 [id^="chat-topic-person-"] 가 새 Teams 웹
_HEAD = [('[id^="chat-header-"] h2', "hdr-h2"), ('[id^="chat-topic-person-"]', "topic-person"),
         ('[data-tid="chat-header-title"]', "hdr-title"), ('[data-tid="chat-title"]', "chat-title"),
         ('[data-tid="chatTitle"]', "chatTitle"), ('[data-tid="chat-header"] [role="heading"]', "hdr-heading"),
         ('[data-tid="message-pane-header"] h2', "mph-h2"), ('[data-tid="message-pane-header"] [role="heading"]', "mph-heading"),
         ('[data-tid="channel-header"] h2', "chan-h2"), ('[data-tid="channel-header"] h1', "chan-h1"),
         ('[data-tid="channelTitle-text"]', "chanTitle"), ('[role="main"] h1', "main-h1"), ('[role="main"] h2', "main-h2")]
_HEAD_SELS = [h[0] for h in _HEAD]
# 메시지 목록 스크롤 영역 후보 (선택자, 약칭)
_VP = [('[data-tid="message-pane-list-viewport"]', "vp"), ('[data-tid="chat-message-list"]', "msg-list"),
       ('[data-tid="message-pane-list-runway"]', "runway"), ('[data-tid="channel-pane-viewport"]', "chan-vp"),
       ('[data-tid="channel-pane-runway"]', "chan-runway"), ('[data-tid="message-pane"]', "mpane"), ('[role="log"]', "log")]
_VP_SELS = [v[0] for v in _VP]
_SEP_SEL = '[role="separator"],[data-tid*="divider"],.fui-Divider__wrapper,[data-testid="timestamp-divider"]'
GEN = -2                                  # 메시지 후보 순번 자리의 '일반 읽기'(time[datetime] 단위) 표지
CLICK_MODES = ("mouse", "synth", "key")   # 신뢰 입력 마우스(CDP) → 합성 사건 → 포커스 + CDP 키 Enter
_CLICK_KO = {"mouse": "마우스", "synth": "합성", "key": "키"}
_CLICK_ACT = {"mouse": "aim", "synth": "synth", "key": "focus"}
# 공통 조각: 후보표 · 대화 ID(19:…@thread / 48:notes — LM27 idOf 이식, 글 속성은 보지 않는다. 항목 '제 것'만 — 안에 품은 다른 항목의
# ID 를 물려받지 않는다) · 잎 글(글 노드를 직접 가진 요소 — 제 것만) · 행 사각형(구역 머리는 제 줄만) · 구역 머리 판정 · 안정 이름
# 맞춤(sigHit) · 이름 정규화(teams_parse.norm_name 과 같은 규칙) · 선택 표시 · 메시지 지문(data-mid → 본문 id → <time datetime>+글
# 해시) · 후보 고르기(run.pref 먼저 — 맞은 후보에 시각이 없으면 일반 읽기) · 일반 읽기 단위(genUnits) · 지금 대화 ID
_JS_COMMON = ("const SELS = " + json.dumps(_LIST_SELS) + ";\n"
              "const SELI = " + json.dumps(_LIST_ITEM) + ";\n"
              "const MSGS = " + json.dumps(_MSG_SELS) + ";\n"
              "const MSGUP = " + json.dumps([i for i, m in enumerate(_MSG) if m[2]]) + ";\n"
              "const HEADS = " + json.dumps(_HEAD_SELS) + ";\n"
              "const VPS = " + json.dumps(_VP_SELS) + ";\n"
              "const SEP = " + json.dumps(_SEP_SEL) + ";\n"
              "const GEN = " + str(GEN) + ";\n"
              "const PREF = __PREF__;\n" + r"""
const TSEL = 'time[datetime],[datetime]';
const MARK = 'li,[role="listitem"],[role="article"],[role="group"],[data-tid*="message" i]';
const RXID = /(19:[^\s\/?#"'&,;<>]+@[A-Za-z0-9.\-]+|48:notes)/;
const pickId = v => { v = String(v || ""); if (!v) return ""; try { v = decodeURIComponent(v); } catch (x) {}
  const m = v.match(RXID); return m ? m[1] : ""; };
const ID_SKIP = /^(aria-label|aria-description|aria-roledescription|title|alt|class|style)$/;
const attrId = e => { if (!e || !e.attributes) return "";
  for (const a of e.attributes) { if (ID_SKIP.test(a.name)) continue; const c = pickId(a.value); if (c) return c; }
  return ""; };
const ownOf = (x, e, isel) => !isel || x.closest(isel) === e;
const idOf = (e, isel) => { if (!e) return ""; let c = attrId(e); if (c) return c;
  for (const s of ['[data-item-key]', '[data-conversation-id]', '[data-chat-id]', '[data-fui-tree-item-value]', 'a[href*="/l/"]', '[id*="19:"]']) {
    for (const x of e.querySelectorAll(s)) { if (!ownOf(x, e, isel)) continue; c = attrId(x); if (c) return c; } }
  return ""; };
const ownText = x => { let s = ""; for (const n of x.childNodes) { if (n.nodeType === 3) s += n.textContent; }
  return s.replace(/\s+/g, " ").trim(); };
const textEls = (e, isel, n) => { const out = [], seen = new Set(); if (!e) return out;
  const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
  for (let t = w.nextNode(); t && out.length < n; t = w.nextNode()) {
    const p = t.parentElement;
    if (!p || seen.has(p) || !(t.textContent || "").trim()) continue;
    seen.add(p);
    if (!ownOf(p, e, isel) || p.closest("script,style,template,noscript")) continue;
    out.push(p); }
  return out; };
const leafs = (e, n) => textEls(e, "", n).map(ownText).filter(Boolean);
const nm = s => (s || "").replace(/[\s.·,()\[\]\-]+/g, "").toLowerCase();
const hookOf = s => { s = String(s || ""); const m = s.match(/^[A-Za-z][A-Za-z0-9_.\-]{0,39}/);
  if (!m) return s ? "?" : ""; const h = m[0].replace(/\d{4,}.*$/, ""); return h + (h.length < s.length ? "~" : ""); };
const order = (n, p) => { const o = []; if (typeof p === "number" && p >= 0 && p < n) o.push(p);
  for (let i = 0; i < n; i++) if (i !== p) o.push(i); return o; };
const listEls = () => { for (let i = 0; i < SELS.length; i++) { const els = [...document.querySelectorAll(SELS[i])];
    if (els.length) return [els, SELS[i], i]; }
  return [[], "", -1]; };
const iselOf = i => (i >= 0 && i < SELI.length) ? SELI[i] : "";
const nestOf = (e, isel) => (e && isel) ? e.querySelectorAll(isel).length : 0;
const isHdr = (e, isel) => !!e && (e.getAttribute("aria-expanded") !== null || nestOf(e, isel) > 0);
const okRect = q => !!q && q.width > 4 && q.height > 4;
const rowRect = (e, isel) => { const r = e.getBoundingClientRect();
  if (nestOf(e, isel) > 0 || !okRect(r)) {
    for (const c of e.children) { if (isel && (c.matches(isel) || c.querySelector(isel))) continue;
      const q = c.getBoundingClientRect(); if (okRect(q)) return q; } }
  return r; };
const lblOf = e => ((e && (e.getAttribute("aria-label") || e.getAttribute("title"))) || "").trim();
const lbyOf = e => { const v = (e && e.getAttribute("aria-labelledby")) || ""; const id = v.split(/\s+/).filter(Boolean)[0];
  const x = id ? document.getElementById(id) : null; return x ? (x.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120) : ""; };
const sigHit = (e, isel, sig) => { if (!e || !sig) return false;
  const l = lblOf(e).split(/[,|·]| - /)[0].trim(); if (l && l === sig) return true;
  if (lbyOf(e) === sig) return true;
  return textEls(e, isel, 24).some(x => ownText(x) === sig); };
const SELMARK = '[aria-selected="true"],[aria-current="page"],[aria-current="true"],[aria-current="location"],[data-is-selected="true"],[data-selected="true"]';
const SELATTR = '[aria-selected],[aria-current],[data-is-selected],[data-selected]';
const hostOf = e => e.closest('[role="treeitem"],[role="option"],[role="listitem"],[role="row"],[role="tab"]') || e;
const selOf = e => { if (!e || !e.isConnected) return null; const h = hostOf(e);
  if (e.matches(SELMARK) || h.matches(SELMARK) || e.querySelector(SELMARK)) return true;
  return (e.matches(SELATTR) || h.matches(SELATTR) || e.querySelector(SELATTR)) ? false : null; };
const hsh = s => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(36); };
const midOf = e => { let v = e.getAttribute("data-mid");
  if (!v) { const x = e.querySelector("[data-mid]"); if (x) v = x.getAttribute("data-mid"); }
  if (!v) { const B = '[id^="content-"],[id^="message-body-"]'; const x = e.matches(B) ? e : e.querySelector(B); if (x) v = x.id; }
  return v || ""; };
const fidOf = e => { const v = midOf(e); if (v) return "m:" + String(v).slice(0, 60);
  const tm = e.matches(TSEL) ? e : e.querySelector(TSEL); const d = tm ? String(tm.getAttribute("datetime") || "").slice(0, 32) : "";
  let s = e.textContent || ""; if (tm && tm !== e) s = s.replace(tm.textContent || "", " ");   // 시각 글('방금'·'1분')은 흔들린다 — 뺀다
  const h = hsh(s.replace(/\s+/g, " ").trim().slice(0, 200)); return d ? "t:" + d + ":" + h : "h:" + h; };
const docOrder = (a, b) => a === b ? 0 : ((a.compareDocumentPosition(b) & 4) ? -1 : 1);
const lcaOf = els => { if (!els.length) return null; const b = els[els.length - 1]; let c = els[0].parentElement;
  while (c && !c.contains(b)) c = c.parentElement; return c; };
const listBox = els => { const c = lcaOf(els);
  if (!c || c === document.body || c === document.documentElement || c.matches('[role="main"],main') || c.querySelector('[role="main"],main')) return null;
  return c; };
const primTimes = () => { const [els, , li] = listEls(); const isel = iselOf(li); const lb = listBox(els);
  return [...document.querySelectorAll(TSEL)].filter(x => (lb ? !lb.contains(x) : !(isel && x.closest(isel)))
    && !x.closest(SEP) && !x.closest('[role="tree"],[role="menu"],[role="tooltip"]')); };
const scrollerish = x => { try { return /(auto|scroll|overlay)/.test(getComputedStyle(x).overflowY); } catch (z) { return false; } };
const genUnits = () => { const T = primTimes(); if (!T.length) return [];
  const lb = listBox(listEls()[0]);
  const cnt = (a, k) => { let c = 0; for (const x of T) { if (a.contains(x) && ++c > k) break; } return c; };
  const stop = x => !x || x === document.body || x === document.documentElement || (lb && x.contains(lb))
    || x.matches('[role="main"],main') || scrollerish(x);
  const us = new Set();
  for (const t of T) {
    let a = t, up = t.parentElement;
    while (!stop(up) && cnt(up, 1) === 1) { a = up; up = up.parentElement; }
    let u = a;
    if (!stop(up) && up.matches(MARK) && cnt(up, 3) <= 3 && ((a.textContent || "").length - (t.textContent || "").length) <= 40
        && ![...up.querySelectorAll(MARK)].some(m => T.some(y => m.contains(y)))) u = up;
    us.add(u); }
  const par = new Map();
  for (const u of us) { const p = u.parentElement; if (p) par.set(p, (par.get(p) || 0) + 1); }
  for (const [p, k] of par) { if (k < 2) continue;
    const ref = [...us].find(u => u.parentElement === p);
    const same = [...p.children].filter(c => c.tagName === ref.tagName && (c.getAttribute("role") || "") === (ref.getAttribute("role") || ""));
    if (same.length < 3) continue;
    for (const c of same) { if (us.has(c) || c.matches(SEP) || (c.querySelector(SEP) && !c.querySelector(TSEL))) continue;
      if ((c.textContent || "").trim()) us.add(c); } }
  const all = [...us];
  return all.filter(u => !all.some(v => v !== u && v.contains(u))).sort(docOrder).slice(0, 400); };
const msgPick = () => { for (const i of order(MSGS.length, PREF.msg)) { let els = [...document.querySelectorAll(MSGS[i])];
    if (!els.length) continue;
    if (MSGUP.includes(i)) els = [...new Set(els.map(x => x.closest('li,[role="listitem"],[role="article"]') || x))];
    if (!els.some(x => x.matches(TSEL) || x.querySelector(TSEL))) { const g = genUnits(); if (g.length) return [GEN, g]; }
    return [i, els]; }
  const g = genUnits();
  return g.length ? [GEN, g] : [-1, []]; };
const headPick = () => { for (const i of order(HEADS.length, PREF.head)) { const e = document.querySelector(HEADS[i]); if (!e) continue;
    const s = (e.getAttribute("title") || e.textContent || "").trim(); if (s) return [i, s.slice(0, 120)]; }
  return [-1, ""]; };
const convNow = () => { let c = pickId(location.href); if (c) return [c, "url"];
  try { for (let i = 0; i < sessionStorage.length; i++) { const k = sessionStorage.key(i) || "";
      if (!/mainWindowNavHistory$/.test(k)) continue;
      const h = JSON.parse(sessionStorage.getItem(k) || "[]"); if (!Array.isArray(h) || !h.length) continue;
      let ix = h.length - 1;
      try { const o = JSON.parse(sessionStorage.getItem(k + "Index") || "{}");
        if (o && typeof o.windowHistoryIndex === "number" && o.windowHistoryIndex >= 0 && o.windowHistoryIndex < h.length) ix = o.windowHistoryIndex; } catch (x) {}
      const en = ((h[ix] || {}).activeEntities || {}).mainEntity || {};
      c = pickId(en.id); if (c) return [c, "nav"]; } } catch (x) {}
  for (const s of ['[id^="chat-header-"]', '[data-tid="message-pane-list-viewport"]', '[data-tid="chat-pane"]', '[data-tid="chat-message-list"]']) {
    c = attrId(document.querySelector(s)); if (c) return [c, "dom"]; }
  return ["", ""]; };
""")
# 목록 한 화면 스냅샷(LM28-TW-2) — 항목마다 순번·대화 ID(제 것)·aria-label·aria-labelledby 첫 요소 글·aria-level·aria-expanded·
# 품은 항목 수(nest — 구역 머리)·행 사각형 r[왼, 위, 폭, 높이]·잎 lf[[글, 줄(0 첫 줄 · 1 아래 줄 · -1 모름), 굵게(≥600), 표지]].
# 표지: B 좁은 단추·메뉴 단추 안 · I 아바타·그림·svg 안 · H aria-hidden 안 · S 크기 없음(숨김). 안정 이름은 파이썬이 고른다
# (stable_name — 시험이 그 규칙을 직접 본다). 글은 메모리에서만 쓴다(디스크·진단에 쓰지 않는다).
JS_CHATS = r"""/*LM28:tw_list*/
(() => {
""" + _JS_COMMON + r"""
  const out = {href: "", how: "", n: 0, items: [], cen: null, vw: innerWidth, vh: innerHeight};
  const [els, how, li] = listEls(); const isel = iselOf(li);
  out.how = how;
  window.__lm_chats = els;
  out.n = els.length;
  const lfOf = (e, rw) => { const xs = textEls(e, isel, 12); const rs = xs.map(x => x.getBoundingClientRect());
    const ok = rs.filter(r => r.width > 2 && r.height > 2);
    const top0 = ok.length ? Math.min(...ok.map(r => r.top)) : 0;
    const band = ok.length ? Math.max(6, Math.min(...ok.map(r => r.height)) * 0.6) : 0;
    return xs.map((x, k) => { const r = rs[k]; let f = "";
      const b = x.closest('button,[role="button"],[aria-haspopup]');
      if (b && b !== e && e.contains(b) && b.getBoundingClientRect().width < rw * 0.5) f += "B";
      if (x.closest('[role="img"],svg,[class*="vatar"]')) f += "I";
      if (x.closest('[aria-hidden="true"]')) f += "H";
      const vis = r.width > 2 && r.height > 2; if (!vis) f += "S";
      let w = 400; try { w = parseInt(getComputedStyle(x).fontWeight, 10) || 400; } catch (z) {}
      return [ownText(x).slice(0, 80), vis ? (r.top - top0 < band ? 0 : 1) : -1, w >= 600 ? 1 : 0, f]; }); };
  out.items = els.slice(0, 400).map((e, i) => { const r = rowRect(e, isel); return {
    idx: i, key: idOf(e, isel), label: lblOf(e).slice(0, 300), lby: lbyOf(e),
    lv: parseInt(e.getAttribute("aria-level") || "0", 10) || 0, ex: e.getAttribute("aria-expanded") || "", nest: nestOf(e, isel),
    r: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], lf: lfOf(e, r.width)}; });
  // 목록 구조(글자 없이): 첫 '방' 항목(구역 머리 아님)의 태그·role·data-tid · 방 항목 수·대화 ID 가진 수·aria-label/labelledby 가진 수 ·
  // 선택 표시 '예'·'있음' 수 · aria-level 분포 · aria-expanded 참/거짓 수 · 다른 항목을 품은 항목(중첩 구역 머리) 수
  const room = out.items.filter(x => !(x.ex || x.nest));
  const f = els.find(e => !isHdr(e, isel)) || els[0];
  if (f) { const lv = {};
    for (const x of out.items) { const k = String(x.lv || "-"); lv[k] = (lv[k] || 0) + 1; }
    out.cen = {role: hookOf(f.getAttribute("role")), tag: f.tagName.toLowerCase(), tid: hookOf(f.getAttribute("data-tid")),
      rooms: room.length, keyed: room.filter(x => x.key).length, lbl: room.filter(x => x.label).length,
      lby: room.filter(x => x.lby).length, selT: els.filter(e => selOf(e) === true).length,
      selA: els.filter(e => selOf(e) !== null).length, exp: out.items.filter(x => x.ex).length,
      lv: Object.entries(lv).slice(0, 6).map(x => x[0] + ":" + x[1]),
      ex: [out.items.filter(x => x.ex === "true").length, out.items.filter(x => x.ex === "false").length,
           out.items.filter(x => x.nest).length]}; }
  return JSON.stringify(out);
})()
"""
# 목록 한 화면 아래로 — 'end' 끝 · 'fits' 스크롤 영역 없이 전체가 보임 · 'no-scroller' 스크롤 영역 못 찾음(끝을 모른다)
JS_LIST_SCROLL = r"""/*LM28:tw_list_scroll*/
(() => {
""" + _JS_COMMON + r"""
  let el = window.__lm_listsc;
  if (!el || !el.isConnected) {
    el = null;
    let els = (window.__lm_chats || []).filter(e => e.isConnected);   // 가상 목록은 내린 뒤 앞 항목이 문서에서 빠진다 — 다시 찾는다
    if (!els.length) els = listEls()[0];
    let c = els.length ? els[0] : null;
    for (let i = 0; i < 14 && c; i++) {
      if (c.scrollHeight > c.clientHeight + 20 && getComputedStyle(c).overflowY !== "visible") { el = c; break; }
      c = c.parentElement;
    }
    if (!el) {
      if (!els.length) return "no-list";
      const r = els[els.length - 1].getBoundingClientRect();
      return (r.bottom <= window.innerHeight + 2) ? "fits" : "no-scroller";
    }
    window.__lm_listsc = el;
  }
  const before = el.scrollTop;
  el.scrollTop = el.scrollTop + Math.max(200, el.clientHeight - 60);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  return el.scrollTop > before ? "scrolled" : "end";
})()
"""
# 목록 맨 위로(2차 걷기 시작) — 기억한 스크롤 영역이 다시 그려져 문서에서 빠졌으면 목록 항목에서 다시 찾는다(못 찾으면 'none')
JS_LIST_TOP = r"""/*LM28:tw_list_top*/
(() => {
""" + _JS_COMMON + r"""
  let el = window.__lm_listsc;
  if (!el || !el.isConnected) {
    el = null;
    const els = listEls()[0]; let c = els.length ? els[0] : null;
    for (let i = 0; i < 14 && c; i++) {
      if (c.scrollHeight > c.clientHeight + 20 && getComputedStyle(c).overflowY !== "visible") { el = c; break; }
      c = c.parentElement;
    }
    if (!el) return "none";
    window.__lm_listsc = el;
  }
  el.scrollTop = 0; el.dispatchEvent(new Event("scroll", {bubbles: true})); return "ok";
})()
"""
# 방 항목 겨누기·누르기(LM28-TW-2 — 이름으로 다시 찾지 않는다): 스냅샷 순번 IDX 의 항목이 대화 ID(KEY)·안정 이름(SIG — aria-label
# 첫 조각·labelledby 글·제 잎 글 중 하나와 같음)이 맞는지 보고, 아니면 지금 목록에서 맞는 항목 중 순번이 가장 가까운 것.
# HDR = 구역 머리를 겨누는가(닫힌 구역 펼치기) — 방을 겨눌 때는 구역 머리를 고르지 않는다. scrollIntoView 뒤 뷰포트 안인지 보고,
# 행의 왼쪽~가운데(폭의 30·45·15·60%) 중 elementFromPoint 가 그 항목 안이고 좁은 단추('…'·메뉴)·링크가 아닌 점을 고른다.
# ACT: aim = 점만 돌려준다(파이썬이 CDP 신뢰 입력으로 누른다) · synth = 그 점의 요소에 합성 포인터·마우스 사건 · focus = 항목에
# 포커스(파이썬이 CDP 키 Enter). menu = 열린 메뉴가 있다(파이썬이 CDP Escape 로 닫는다).
JS_AIM = r"""/*LM28:tw_aim*/
(() => {
  const IDX = __IDX__, KEY = __KEY__, SIG = __SIG__, ACT = __ACT__, HDR = __HDR__;
""" + _JS_COMMON + r"""
  const [els, , li] = listEls(); const isel = iselOf(li);
  const hit = e => !!e && e.isConnected && isHdr(e, isel) === HDR && (KEY ? idOf(e, isel) === KEY : sigHit(e, isel, SIG));
  const prev = window.__lm_chats || [];
  let t = (IDX >= 0 && hit(prev[IDX])) ? prev[IDX] : ((IDX >= 0 && hit(els[IDX])) ? els[IDX] : null);
  if (!t) { let bd = 1e9; els.forEach((e, i) => { if (hit(e)) { const d = Math.abs(i - IDX); if (d < bd) { bd = d; t = e; } } }); }
  if (!t) return JSON.stringify({r: "gone"});
  window.__lm_target = t;
  const inView = q => okRect(q) && q.top >= 0 && q.left >= 0 && q.bottom <= innerHeight && q.right <= innerWidth;
  let r = rowRect(t, isel);
  if (!inView(r)) { try { t.scrollIntoView({block: "center", inline: "nearest"}); } catch (z) {} r = rowRect(t, isel); }
  const y = Math.round(r.top + r.height / 2);
  let px = -1, why = "";
  for (const f of [0.3, 0.45, 0.15, 0.6]) {
    const x = Math.round(r.left + r.width * f);
    const h = document.elementFromPoint(x, y);
    if (!h || !(h === t || t.contains(h))) { why = h ? "cover" : "none"; continue; }
    const b = h.closest('button,[role="button"],[aria-haspopup],a[href]');
    if (b && b !== t && t.contains(b) && b.getBoundingClientRect().width < r.width * 0.5) { why = "btn"; continue; }
    px = x; why = ""; break; }
  const out = {r: "ok", x: px >= 0 ? px : Math.round(r.left + r.width * 0.3), y: y, hit: px >= 0 ? 1 : 0, why: why,
    vis: inView(r) ? 1 : 0, i: els.indexOf(t), menu: document.querySelector('[role="menu"]') ? 1 : 0};
  if (ACT === "synth") {
    const el = (out.hit ? document.elementFromPoint(out.x, out.y) : null) || t;
    for (const ev of ["pointerover", "mouseover", "pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      const o = {bubbles: true, cancelable: true, composed: true, view: window, clientX: out.x, clientY: out.y, button: 0,
                 buttons: (ev === "pointerdown" || ev === "mousedown") ? 1 : 0};
      let e2 = null;
      if (ev.startsWith("pointer") && typeof PointerEvent === "function") {
        try { e2 = new PointerEvent(ev, Object.assign({pointerId: 1, isPrimary: true, pointerType: "mouse"}, o)); } catch (z) { e2 = null; }
      }
      el.dispatchEvent(e2 || new MouseEvent(ev, o)); }
    out.r = "fired";
  } else if (ACT === "focus") {
    try { if (!t.hasAttribute("tabindex")) t.setAttribute("tabindex", "-1"); t.focus({preventScroll: true}); } catch (z) {}
    const a = document.activeElement; out.focus = (a && (a === t || t.contains(a))) ? 1 : 0;
  }
  return JSON.stringify(out);
})()
"""
# 대화 화면 상태(메모리에서만 비교 — 디스크에 쓰지 않는다): 메시지 수·맞은 후보(GEN = 일반 읽기) · 머리 제목·맞은 후보 · 이 방 항목의
# 선택 상태(예/아님/표시 없음 null) · 메시지 지문 fp(맨 앞 4 + 맨 뒤 4 — 'm:' 메시지 ID · 't:' 시각+글 해시 · 'h:' 글 해시) ·
# 지금 대화 ID 와 그 출처 · 창 제목(document.title) · 주소
JS_PANE = r"""/*LM28:tw_pane*/
(() => {
  const KEY = __KEY__, SIG = __SIG__;
""" + _JS_COMMON + r"""
  const [mi, els] = msgPick();
  const [hi, chat] = headPick();
  const [lels, , li] = listEls(); const isel = iselOf(li);
  // 선택 표시는 '이 방' 항목의 것 — 누르기 전 스냅샷에서 마지막으로 누른 항목은 앞 방이다
  const mine = e => !!e && e.isConnected && !isHdr(e, isel) && (KEY ? idOf(e, isel) === KEY : sigHit(e, isel, SIG));
  let t = window.__lm_target;
  if (!mine(t)) t = lels.find(mine) || null;
  const fp = [...new Set([...els.slice(0, 4), ...els.slice(-4)].map(fidOf))];
  const [conv, cv] = convNow();
  return JSON.stringify({n: els.length, mi: mi, chat: chat, hi: hi, sel: selOf(t), fp: fp, conv: conv, cv: cv,
    doc: String(document.title || "").slice(0, 200), url: String(location.href || "").slice(0, 400)});
})()
"""
# 대화 화면 한 장 — 메시지(맞은 후보 또는 일반 읽기 단위)와 날짜 구분선을 문서 순서로. 구분선은 메시지 목록 안에서만 찾고
# (왼쪽 목록의 구역 선 제외), 메시지 안의 구분선은 날짜 구분선이 아니다. 구분선에 <time datetime> 이 있으면 그 값도 싣는다.
# 일반 읽기(GEN): 작성자 = [data-tid*=author]·[id^=author-] 또는 시각 앞 같은 줄의 짧은 잎(단추·아바타 글 제외) · 본문 = 시각·작성자를
# 품지 않은 가장 긴 글 덩어리 · 내 말풍선 = 클래스(ChatMyMessage 등) → 없으면 위치(오른쪽 붙음·작성자 없음 = 나, 왼쪽 = 남).
JS_MSGS = r"""/*LM28:tw_msgs*/
(() => {
""" + _JS_COMMON + r"""
  const out = {href: "", how: "", mi: -1, chat: "", hi: -1, n: 0, items: [], doc: String(document.title || "").slice(0, 200)};
  const [mi, els] = msgPick();
  if (!els.length) return JSON.stringify(out);
  out.how = mi === GEN ? "gen" : MSGS[mi];
  out.mi = mi;
  const hp = headPick();
  out.hi = hp[0];
  out.chat = hp[1];
  const box = (mi === GEN ? lcaOf(els) : null)
    || els[0].closest('[data-tid="message-pane-list-viewport"],[data-tid="chat-message-list"],[data-tid="message-pane-list-runway"],[role="log"],[role="main"]')
    || document;
  const clsOf = x => (typeof x.className === "string") ? x.className : ((x.className && x.className.baseVal) || "");
  const MYQ = '[class*="ChatMyMessage"],[class*="myMessage"],[class*="message-mine"]';
  const genItem = u => {
    const tms = [...(u.matches(TSEL) ? [u] : []), ...u.querySelectorAll(TSEL)];
    const tm = tms[0] || null;
    let au = u.querySelector('[data-tid*="author" i],[id^="author-"]');
    let author = au ? (au.textContent || "").replace(/\s+/g, " ").trim() : "";
    const lf = textEls(u, "", 30);
    if (!author && tm) { const tr = tm.getBoundingClientRect();
      for (const x of lf) {
        if (x === tm || tm.contains(x) || (tm.compareDocumentPosition(x) & 4)) break;
        if (x.closest('button,[role="button"],[role="img"],svg,[class*="vatar"]')) continue;
        const s = ownText(x); if (s.length < 2 || s.length > 40) continue;
        const xr = x.getBoundingClientRect();
        if (tr.height > 0 && xr.height > 0 && Math.abs(xr.top - tr.top) > Math.max(12, tr.height)) continue;
        author = s; au = x; break; } }
    const uw = u.getBoundingClientRect().width;
    let best = null, bl = 0;
    for (const x of u.querySelectorAll("*")) {
      if (tm && (x.contains(tm) || tm.contains(x))) continue;
      if (au && (x.contains(au) || au.contains(x))) continue;
      if (x.closest('[role="img"],svg')) continue;
      const b = x.closest('button,[role="button"]');
      if (b && u.contains(b) && b.getBoundingClientRect().width < uw * 0.5) continue;
      const n = (x.textContent || "").trim().length; if (n > bl) { bl = n; best = x; } }
    let mine = null;
    const myA = u.closest(MYQ);
    if (/ChatMyMessage|message-mine|myMessage/i.test(clsOf(u)) || u.querySelector(MYQ) || (myA && myA !== box && box.contains(myA))) mine = true;
    else if (/ChatMessage/i.test(clsOf(u)) || u.querySelector('[class*="ChatMessage"]')) mine = false;
    else if (best && box !== document) { const bx = box.getBoundingClientRect(), q = best.getBoundingClientRect();
      if (bx.width > 200 && q.width > 0) {
        if (!author && q.left - bx.left >= bx.width * 0.3 && bx.right - q.right <= bx.width * 0.12) mine = true;
        else if (q.left - bx.left < bx.width * 0.25) mine = false; } }
    return {t: "msg", gen: 1, mid: midOf(u), fid: fidOf(u), label: (u.getAttribute("aria-label") || "").slice(0, 400),
      author: author.slice(0, 60),
      ts: tm ? String(tm.getAttribute("title") || tm.getAttribute("aria-label") || tm.textContent || "").trim().slice(0, 80) : "",
      iso: tms.map(x => x.getAttribute("datetime")).filter(Boolean).slice(0, 3),
      titles: [...u.querySelectorAll("[title]")].map(x => (x.getAttribute("title") || "").trim()).filter(Boolean).slice(0, 6),
      body: best ? (best.textContent || "").replace(/\s+/g, " ").trim().slice(0, 600) : "",
      texts: lf.map(ownText).filter(Boolean).slice(0, 20), mine: mine}; };
  const mset = new Set(els);
  const seps = [...box.querySelectorAll(SEP)].filter(s => !mset.has(s) && !els.some(u => u.contains(s)));
  const all = els.concat(seps).sort(docOrder);
  for (const e of all) {
    if (!mset.has(e)) {
      const s = (e.textContent || "").trim(); const tm = e.matches(TSEL) ? e : e.querySelector(TSEL);
      if (s && s.length <= 60) out.items.push({t: "sep", text: s, iso: tm ? String(tm.getAttribute("datetime") || "") : ""});
      continue;
    }
    if (mi === GEN) { out.items.push(genItem(e)); continue; }
    const au = e.querySelector('[data-tid="message-author-name"],[data-tid="messageAuthorName"],[id^="author-"]');
    const ts = e.querySelector('[data-tid="message-timestamp"],time,[data-tid="message-status"] time');
    const bd = e.querySelector('[data-tid="messageBodyContent"],[id^="content-"],[data-tid="message-content"],[data-tid="message-body"],[id^="message-body-"]');
    const cls = (typeof e.className === "string") ? e.className : ((e.className && e.className.baseVal) || "");
    // 내 말풍선(LM28 E): 제 클래스·자손 표지 → 조상 표지(대화 칸 안쪽이고 다른 메시지를 품지 않은 조상만 — 목록 전체를 감싼 칸이
    // 'myMessage…' 류 이름이어도 모두 내 말이 되지 않게) → 둘 다 없으면 일반 읽기와 같은 위치 규칙(오른쪽 붙음·작성자 없음 = 나, 왼쪽 = 남)
    const myA = e.closest(MYQ);
    let mine = /ChatMyMessage|message-mine|myMessage/i.test(cls) || !!e.querySelector('[class*="ChatMyMessage"],[class*="myMessage"]')
      || !!(myA && box !== document && myA !== box && box.contains(myA) && !els.some(o => o !== e && myA.contains(o)));
    let other = !mine && (/ChatMessage/i.test(cls) || !!e.querySelector('[class*="ChatMessage"]'));
    if (!mine && !other && box !== document) {
      const bx = box.getBoundingClientRect(), q = (bd || e).getBoundingClientRect();
      if (bx.width > 200 && q.width > 0) {
        if (!au && q.left - bx.left >= bx.width * 0.3 && bx.right - q.right <= bx.width * 0.12) mine = true;
        else if (q.left - bx.left < bx.width * 0.25) other = true; } }
    out.items.push({t: "msg", mid: midOf(e), fid: fidOf(e),
      label: (e.getAttribute("aria-label") || "").slice(0, 400),
      author: au ? (au.textContent || "").trim() : "",
      ts: ts ? ((ts.getAttribute("title") || ts.getAttribute("datetime") || ts.textContent || "").trim()) : "",
      iso: [...e.querySelectorAll("time[datetime]")].map(x => x.getAttribute("datetime")).filter(Boolean).slice(0, 3),
      titles: [...e.querySelectorAll("[title]")].map(x => (x.getAttribute("title") || "").trim()).filter(Boolean).slice(0, 6),
      body: bd ? (bd.textContent || "").trim().slice(0, 600) : "",
      texts: leafs(e, 20), mine: mine ? true : (other ? false : null)});
  }
  out.n = out.items.filter(x => x.t === "msg").length;
  return JSON.stringify(out);
})()
"""
# 위로 한 화면 — {r: scrolled|top|no-scroller, how, h·n·f: 되감기 **전** 높이·메시지 수·맨 위 메시지(로드 확인의 기준)}.
# 스크롤 영역은 '실제로 움직이는' 요소만(scrollTop 을 1 바꿔 보고 되돌린다) — overflow:visible 조상을 맨 위로 오판하지 않게(F-06).
# __DEEP__=1 이면 다시 찾기: 메시지의 모든 조상(overflow 표기 무관)과 문서 스크롤까지 본다. 찾은 요소는 표식을 달아 다음에 먼저 쓴다.
JS_SCROLL_UP = r"""/*LM28:tw_scroll_up*/
(() => {
  const DEEP = __DEEP__;
""" + _JS_COMMON + r"""
  const moves = e => { if (!e || !e.isConnected || e.scrollHeight <= e.clientHeight + 20) return false;
    const t = e.scrollTop; e.scrollTop = t - 1; let ok = e.scrollTop !== t;
    if (!ok) { e.scrollTop = t + 1; ok = e.scrollTop !== t; }
    e.scrollTop = t; return ok; };
  const first = () => { const m = msgPick()[1][0]; return m ? fidOf(m) : ""; };
  const m0 = msgPick()[1][0] || null;
  const count = () => msgPick()[1].length;
  let el = document.querySelector("[data-lm28-scroller]"), how = "marked";
  if (!moves(el)) { el = null; how = ""; }
  if (!el) {
    for (const s of VPS) { const e = document.querySelector(s); if (moves(e)) { el = e; how = s; break; } }
  }
  if (!el) {
    let m = m0;
    while (m && m !== document.body) {
      if (getComputedStyle(m).overflowY !== "visible" && moves(m)) { el = m; how = "ancestor"; break; }
      m = m.parentElement;
    }
  }
  if (!el && DEEP) {
    let m = m0;
    while (m && m !== document.documentElement) { if (moves(m)) { el = m; how = "deep-ancestor"; break; } m = m.parentElement; }
    if (!el && moves(document.scrollingElement)) { el = document.scrollingElement; how = "document"; }
  }
  if (!el) return JSON.stringify({r: "no-scroller", how: "", h: 0, n: count(), f: first()});
  document.querySelectorAll("[data-lm28-scroller]").forEach(x => { if (x !== el) x.removeAttribute("data-lm28-scroller"); });
  try { el.setAttribute("data-lm28-scroller", "1"); } catch (x) {}
  const base = {h: el.scrollHeight, n: count(), f: first()};
  const before = el.scrollTop;
  // 0 으로 자르지 않는다 — 아래에서 쌓는(column-reverse) 목록은 맨 아래가 0 이고 위로 갈수록 음수다(브라우저가 범위를 알아서 자른다)
  el.scrollTop = el.scrollTop - Math.max(400, el.clientHeight - 60);
  el.dispatchEvent(new Event("scroll", {bubbles: true}));
  if (el.scrollTop >= before) { try { el.dispatchEvent(new WheelEvent("wheel", {deltaY: -400, bubbles: true})); } catch (x) {} }
  return JSON.stringify({r: el.scrollTop < before ? "scrolled" : "top", how: how, h: base.h, n: base.n, f: base.f});
})()
"""
# 지난 메시지가 붙었는지 — 표식 단 스크롤 영역의 높이 · 메시지 수 · 맨 위 메시지
JS_HEIGHT = r"""/*LM28:tw_height*/
(() => {
""" + _JS_COMMON + r"""
  const el = document.querySelector("[data-lm28-scroller]");
  const els = msgPick()[1];
  return JSON.stringify({h: el ? el.scrollHeight : 0, n: els.length, f: els[0] ? fidOf(els[0]) : ""});
})()
"""
# 화면 구조 진단(LM28 — 현장 사진 한 장으로 원인 확정): 후보별 개수 · 머리 후보별 글자 수 · 스크롤 영역(높이·보이는 높이·위치) ·
# 목록 선택 표시 종류별 수 · 대화 ID 출처 · 메시지 영역 data-tid 빈도 · 골격(연 항목·머리·메시지 하나 — 태그·role·data-tid·
# id 앞머리·aria-* 이름과 값 길이(상태 값만 그대로)·자식 수). 글자: 시각·구분선 안의 잎만 가린 글(글자→x, 숫자·구두점·오전/오후 유지),
# 그 밖은 길이만. 이름·제목·본문·주소는 나가지 않는다.
JS_CENSUS = r"""/*LM28:tw_census*/
(() => {
""" + _JS_COMMON + r"""
  const mask = s => String(s || "").replace(/오전|오후|어제|Yesterday|AM|PM|am|pm|\p{L}/gu, m => m.length > 1 ? m : "x")
    .replace(/\s+/g, " ").trim().slice(0, 24);
  const ENUM = /^(true|false|mixed|page|step|location|date|time|polite|assertive|off|on|none|list|tree|menu|listbox|dialog|grid|\d{1,3})$/;
  const TIMEY = 'time,[datetime],[data-tid*="timestamp"],[role="separator"],[data-tid*="divider"],.fui-Divider__wrapper';
  const node = (e, d) => { let s = d + " " + e.tagName.toLowerCase();
    if (e.id) { const m = e.id.match(/^[A-Za-z][A-Za-z_\-]*/); s += "#" + (m ? m[0].slice(0, 24) : ""); }
    const r = e.getAttribute("role"); if (r) s += " r=" + hookOf(r);
    const t = e.getAttribute("data-tid"); if (t) s += " t=" + hookOf(t);
    const tt = e.getAttribute("data-testid"); if (tt) s += " tt=" + hookOf(tt);
    for (const a of e.attributes) { const n = a.name;
      if (n.startsWith("aria-")) s += " " + n.slice(5) + (ENUM.test(a.value) ? "=" + a.value : "#" + a.value.length);
      else if (n === "title" || n === "data-mid" || n === "datetime" || n === "href" || n === "data-fui-tree-item-value") s += " " + n + "#" + a.value.length;
      else if (n === "tabindex") s += " ti=" + a.value.slice(0, 3); }
    const k = e.childElementCount;
    if (!k) { const x = (e.textContent || "").trim(); if (x) s += (e.matches(TIMEY) || e.closest(TIMEY)) ? ' ~"' + mask(x) + '"' : " ~#" + x.length; }
    else s += " +" + k;
    return s.slice(0, 100); };
  const skel = (root, maxd, maxn) => { const out = []; if (!root) return out;
    const walk = (e, d) => { if (out.length >= maxn) return; out.push(node(e, d)); if (d >= maxd) return;
      for (const c of e.children) { if (out.length >= maxn) break; walk(c, d + 1); } };
    walk(root, 0); return out; };
  const cnt = s => { try { return document.querySelectorAll(s).length; } catch (x) { return -1; } };
  const out = {loc: (location.host + location.pathname).replace(new RegExp(RXID.source, "g"), "<id>")
    .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, "<id>").replace(/\d{5,}/g, "<n>").slice(0, 60)};
  out.list = SELS.map(cnt);
  out.msg = MSGS.map(cnt);
  out.head = HEADS.map(s => { const e = document.querySelector(s); return e ? (e.getAttribute("title") || e.textContent || "").trim().length : -1; });
  out.vp = VPS.map(s => { const e = document.querySelector(s); return e ? [e.scrollHeight, e.clientHeight, Math.round(e.scrollTop)] : 0; });
  const lels = listEls()[0];
  out.sel = {n: lels.length, ast: 0, asa: 0, ac: 0, ds: 0, cls: 0};
  const hasM = (e, h, q) => e.matches(q) || h.matches(q) || !!e.querySelector(q);
  for (const e of lels) { const h = hostOf(e);
    if (hasM(e, h, '[aria-selected="true"]')) out.sel.ast++;
    if (hasM(e, h, "[aria-selected]")) out.sel.asa++;
    if (hasM(e, h, '[aria-current]:not([aria-current="false"])')) out.sel.ac++;
    if (hasM(e, h, '[data-is-selected="true"],[data-selected="true"]')) out.sel.ds++;
    const c = String(typeof h.className === "string" ? h.className : "") + " " + String(typeof e.className === "string" ? e.className : "");
    if (/selected|active/i.test(c)) out.sel.cls++; }
  out.conv = convNow()[1];
  const region = document.querySelector('[role="main"]') || document.body;
  const tc = {};
  for (const e of region.querySelectorAll("[data-tid]")) { const k = hookOf(e.getAttribute("data-tid")); if (k) tc[k] = (tc[k] || 0) + 1; }
  out.tids = Object.entries(tc).sort((a, b) => b[1] - a[1]).slice(0, 24).map(x => x[0] + ":" + x[1]);
  // LM28-TW-2 '구조+' 원자료: 대화 영역(목록 밖) data-tid 상위 8 · 일반 읽기 단위 수 · 대화 영역 시각(time[datetime]) 수 · 문서 전체 시각 수 ·
  // 창 제목(파이썬이 글자를 가린 꼴만 남긴다) · 문서 보임·초점 · iframe(수·열리는 수·그 안 시각 수) · shadow root 수
  const li0 = listEls()[2]; const isel0 = iselOf(li0); const lb0 = listBox(lels);
  const tc2 = {};
  for (const e of document.querySelectorAll("[data-tid]")) { if (lb0 ? lb0.contains(e) : (isel0 && e.closest(isel0))) continue;
    const k = hookOf(e.getAttribute("data-tid")); if (k) tc2[k] = (tc2[k] || 0) + 1; }
  out.tids2 = Object.entries(tc2).sort((a, b) => b[1] - a[1]).slice(0, 8).map(x => x[0] + ":" + x[1]);
  try { out.gen = genUnits().length; } catch (z) { out.gen = -1; }
  try { out.times = primTimes().length; } catch (z) { out.times = -1; }
  out.tall = document.querySelectorAll(TSEL).length;
  out.doc = String(document.title || "").slice(0, 200);
  out.vis = String(document.visibilityState || "");
  try { out.foc = document.hasFocus() ? 1 : 0; } catch (z) { out.foc = -1; }
  let ifr = 0, ifa = 0, ift = 0;
  for (const f of document.querySelectorAll("iframe")) { ifr++;
    try { const d = f.contentDocument; if (d) { ifa++; ift += d.querySelectorAll(TSEL).length; } } catch (z) {} }
  out.ifr = [ifr, ifa, ift];
  let sh = 0; for (const e of document.querySelectorAll("*")) { if (e.shadowRoot) sh++; }
  out.sh = sh;
  let it = window.__lm_target; if (!it || !it.isConnected) it = lels.find(e => !isHdr(e, isel0)) || lels[0] || null;
  const hx = lels.find(e => isHdr(e, isel0)) || null;
  const hh = document.querySelector('[role="main"] h1,[role="main"] h2,main h1,main h2');
  const hd = document.querySelector('[id^="chat-header-"],[data-tid="message-pane-header"],[data-tid="chat-header"],[data-tid="channel-header"]')
    || (hh ? hh.parentElement : null);
  const [mi, mels] = msgPick();
  let me = mels.length ? (mels.find(x => x.querySelector("time")) || mels[mels.length - 1]) : null;
  if (!me) { const vp = VPS.map(s => document.querySelector(s)).find(Boolean) || document.querySelector('[role="main"]');
    if (vp) me = vp.querySelector('li,[role="listitem"],[role="article"]') || vp; }
  out.skel = {item: skel(it, 4, 14), head: skel(hd, 3, 8), msg: skel(me, 5, 18), hdr: skel(hx, 2, 6)};
  out.mi = mi;
  return JSON.stringify(out);
})()
"""


_PH = re.compile(r"__(PREF|KEY|SIG|ACT|IDX|HDR|DEEP)__")


def _js(run, js, room=None, deep=False, idx=-1, act="aim", hdr=False):
    """JS 자리표 채우기(한 번에 — 값 속 글이 다른 자리표로 다시 바뀌지 않게) — __PREF__(실제로 맞은 후보 순번 run.pref) ·
    __KEY__/__SIG__(방 — 대화 ID · 안정 이름) · __IDX__(스냅샷 순번) · __ACT__(aim·synth·focus) · __HDR__(구역 머리를 겨눔) ·
    __DEEP__(스크롤 영역 다시 찾기). 공통 조각이 든 모든 스크립트는 이것을 거쳐 보낸다."""
    room = room or {}
    vals = {"PREF": json.dumps(getattr(run, "pref", None) or {"msg": -1, "head": -1}),
            "KEY": json.dumps(str(room.get("key") or "")), "SIG": json.dumps(str(room.get("sig") or "")),
            "ACT": json.dumps(str(act)), "IDX": str(_int(idx, -1)), "HDR": "true" if hdr else "false",
            "DEEP": "1" if deep else "0"}
    return _PH.sub(lambda m: vals[m.group(1)], js)


class Browser:
    def __init__(self):
        spec = importlib.util.spec_from_file_location("_ca", os.path.join(ROOT, "tools", "copilot_auto.py"))
        self.ca = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ca)
        self.cfg = self.ca.load_cfg()
        self.port = self.cfg["port"]
        self.cdp = None
        self.own_tab = ""          # LM28: 이 수집기가 /json/new 로 연 탭 id — 끝에 이것만 닫는다(사람·다른 작업의 탭은 두기)
        self.reason = ""           # LM28: 로그인·기동 실패 사유 코드(LMSTATUS reason)

    def start(self):
        if not self.ca.ensure_edge(self.cfg):
            self.reason = self.ca.LAST.get("reason") or "R-EDGELAUNCH"     # R-EDGEPOL·R-EDGEFOREIGN·R-EDGELAUNCH(WP5)
            return False
        ws = None
        for t in [t for t in self.ca.http_json(self.port, "/json") if t.get("type") == "page"]:
            # LM28: 호스트 정확 일치(부분 문자열 금지 — C-36). 개인용 Teams 탭은 쓰지 않는다.
            if self.ca.host_in(self.ca._host(t.get("url")), HOSTS):
                ws = t["webSocketDebuggerUrl"]
                break
        if not ws:
            # 새 탭에서 연다 — Copilot 탭(판정에 쓰는 대화 맥락)을 건드리지 않기 위해서다
            for method in ("PUT", "GET"):
                try:
                    t = self.ca.http_json(self.port, "/json/new?" + quote(TEAMS_URL, safe=""), method=method)
                    ws = t["webSocketDebuggerUrl"]
                    self.own_tab = str(t.get("id") or "")
                    break
                except Exception:
                    continue
        if not ws:
            self.reason = "R-EDGELAUNCH"
            return False
        self.cdp = self.ca.CDP(ws)
        try:
            self.cdp.call("Page.enable")
        except Exception:
            pass
        # LM28-TW-2: 탭을 앞으로 — 숨은 탭(다른 탭 뒤)은 크로미움이 그리기 단계(가상 목록의 크기 측정·IntersectionObserver)를 돌리지
        # 않아 대화 화면이 비어 보일 수 있고, 신뢰 입력(CDP 마우스)도 보이는 탭이어야 확실하다. 실패해도 계속(문서 보임은 '구조+' 줄에).
        act = getattr(self.ca, "activate", None)
        if callable(act):
            act(self.cdp)
        return True

    def href(self):
        try:
            return str(self.cdp.eval("location.href"))
        except Exception:
            return ""

    def goto(self, url, wait=6.0):
        try:
            self.cdp.call("Page.navigate", {"url": url})
        except Exception:
            self.cdp.reconnect()
            self.cdp.call("Page.navigate", {"url": url})
        return self.wait_ready(wait)

    def kind(self, url):
        """탭 주소 → 'work'(팀즈 업무 호스트) · 'personal'(teams.live.com) · 그 밖은 copilot_auto.page_kind(WP5)."""
        h = self.ca._host(url)
        if self.ca.host_in(h, PERSONAL_HOSTS):
            k = "personal"
        elif self.ca.host_in(h, HOSTS):
            k = "work"
        else:
            k = self.ca.page_kind(url, self.cfg)
        if k == "personal" and not self.ca._truthy(self.cfg.get("requireWorkAccount"), True):
            return "work" if self.ca.host_in(h, HOSTS + PERSONAL_HOSTS) else "login"     # LM24 처럼(개인 계정 허용 설정)
        return k

    def _login(self, kind):
        """로그인 화면 → 'login' | 'personal'. 사유를 남기고 owner.json 에 로그인 대기를 적는다(close_own_edge 가 창을 두게 — WP5)."""
        if kind == "personal":
            self.reason = "R-PERSONAL"
        else:
            code = ""
            if kind in ("login", "adfs"):
                try:
                    code = str(self.cdp.eval(self.ca.js_aadsts(), timeout=10) or "")
                except Exception:
                    code = ""
            self.reason = self.ca.aadsts_reason(code) if code else "R-LOGIN"
        try:
            self.ca._update_owner(self.cfg, login_pending=time.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass
        return "personal" if kind == "personal" else "login"

    def wait_ready(self, settle=6.0, limit=90):
        """팀즈 웹은 첫 로드가 느리다(워크로드 셸 → 채팅). → 'login' | 'personal' | 'ok' | 'timeout'
        LM28: 로그인 판정은 주소의 부분 문자열이 아니라 호스트 판정(page_kind)으로. 팀즈가 아닌 호스트(회사 IdP 등)에서 끝까지
        머물면 로그인 대기로 본다."""
        t0 = time.time()
        kind = ""
        while time.time() - t0 < limit:
            time.sleep(1.0)
            h = self.href()
            kind = self.kind(h)
            if kind in ("login", "adfs", "personal"):
                return self._login(kind)
            if not self.ca.host_in(self.ca._host(h), HOSTS + PERSONAL_HOSTS):
                continue
            try:
                rs = self.cdp.eval("document.readyState")
                n = int(self.cdp.eval('document.querySelectorAll(\'[data-tid="chat-list-item"],'
                                      '[role="treeitem"],[role="main"]\').length') or 0)
            except Exception:
                rs, n = "", 0
            if rs == "complete" and n > 0:
                time.sleep(settle)
                kind = self.kind(self.href())
                if kind in ("login", "adfs", "personal"):
                    return self._login(kind)
                try:
                    self.ca._update_owner(self.cfg, login_pending="")
                except Exception:
                    pass
                return "ok"
        if kind in ("other", "mixed"):
            return self._login(kind)
        self.reason = "R-TIMEOUT"
        return "timeout"

    def eval_json(self, js, timeout=40):
        r = self.cdp.eval(js, timeout=timeout)
        if isinstance(r, str):
            try:
                return json.loads(r)
            except ValueError:
                return {}
        return r or {}

    def close(self, keep_tab=False):
        """CDP 연결을 닫고, 이 수집기가 연 탭만 닫는다(keep_tab — 로그인 대기면 사람이 그 탭에서 로그인한다)."""
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass
        if self.own_tab and not keep_tab:
            try:
                self.ca._close_tab(self.port, self.own_tab)
            except Exception:
                pass
            self.own_tab = ""


# ── 수집 ─────────────────────────────────────────────────────────────────────
class Run:
    """한 번의 수집 — 기간·오늘·시간 예산·상한·계수(LMSTATUS counts)·화면 진단(selector_diag). 시험은 today·deadline 을 넘긴다."""

    def __init__(self, d0, d1, today=None, deadline=None, max_chats=MAX_CHATS, max_scroll=MAX_SCROLL, selfs=None,
                 ctx=None):
        self.d0, self.d1 = d0, d1
        self.today = today or date.today()
        self.deadline = deadline
        self.max_chats = max(0, int(max_chats))
        self.max_scroll = max(1, int(max_scroll))
        self.selfs = selfs or {"나", "you", "본인", "me", "자신"}
        self.ctx = ctx
        self.timed_out = False
        self.c = {"rooms_listed": 0, "list_end": False, "opened": 0, "complete": 0, "incremental_ok": 0,
                  "cut_budget": 0, "cut_no_scroller": 0, "roomgone": 0, "rows_new": 0, "teams_present": False,
                  "skipped_old": 0, "not_opened": 0, "unchanged_skip": 0, "pages": 0, "scrolls": 0, "dup_other": 0,
                  "no_time": 0, "no_body": 0, "no_author": 0,
                  # 내 메시지 진단(LM28 E): 남길 행 · 그중 내 발신 · 화면 판정(내 것·남의 것·판정불가) · 판정불가인데 이어받음 ·
                  # 날짜만 · 지난 판의 날짜만 행을 분 단위로(prec_up)·남의 말로 적힌 내 메시지를 내 발신으로(mine_fixed) 바로잡음
                  "rows_read": 0, "rows_sent": 0, "mine_t": 0, "mine_f": 0, "mine_n": 0, "au_inherit": 0, "date_only": 0,
                  "prec_up": 0, "mine_fixed": 0,
                  # 방 전환 — 실패 사유(그 방은 roomgone)·확인 근거(방마다 하나). last_run.json 의 counts 에 남도록 앞쪽에 둔다.
                  "open_notfound": 0, "pane_stuck": 0, "open_same_pane": 0, "open_by_sel": 0, "open_by_title": 0,
                  "open_by_conv": 0, "open_by_doc": 0, "open_by_content": 0}
        self.sd = {}
        self.pref = {"msg": -1, "head": -1}     # 이 화면에서 실제로 맞은 메시지·머리 후보 순번 — 다음 방부터 먼저 쓴다
        self.cen = {}                           # 화면 구조 진단 원자료(list: 목록 구조 · pane: JS_CENSUS · pane_kind: fail|ok|page)
        self.diag = {}                          # '구조+' 줄 원자료(가린 꼴만 — doc: 창 제목 꼴 · leaf: 목록 항목 잎 꼴)
        self.open_ok = 0                        # 이번 실행에서 전환을 확인한 방 수
        self.open_fail_streak = 0               # 연속 전환 실패(확인 0 일 때 OPEN_ABORT 에 닿으면 남은 방은 열지 않는다)
        self.aborted = False
        self.no_mouse = False                   # CDP 마우스 입력이 오류·시간 초과 — 이번 실행에서는 다음 방법부터

    def out_of_time(self):
        if self.deadline is not None and _mono() > self.deadline:
            self.timed_out = True
            return True
        return False

    def bump(self, k, n=1):
        self.c[k] = self.c.get(k, 0) + n


_BADGE = re.compile(r"^[(\[]?\d{1,4}\+?[)\]]?$")                     # 숫자뿐인 배지(안 읽음 수 '3'·'99+')
_REL_W = re.compile(r"^(방금|지금|now|just now)$|^\d{1,3}\s*(분|시간|일|주|min|mins|h|hr|hrs|d|w)(\s*(전|ago))?$", re.I)


def _timeish(s):
    """시각·날짜·요일·상대 시각뿐인 글('오후 3:12'·'15:12'·'어제'·'화요일'·'10/5'·'방금'·'5분 전') — 이름이 될 수 없다."""
    s = str(s or "").strip()
    return bool(s) and (owa_parse.is_datetime_text(s) or bool(_REL_W.match(s)))


def _lf(it):
    """JS 잎 묘사 → [(글, 줄, 굵게, 표지)] — 줄 0 첫 줄 · 1 아래 줄 · -1 모름. 잎 묘사가 없는 각본(texts 만)은 줄 모름으로."""
    out = []
    for x in it.get("lf") or ():
        if isinstance(x, (list, tuple)) and x:
            out.append((str(x[0] or "").strip()[:80], _int(x[1] if len(x) > 1 else -1, -1),
                        _int(x[2] if len(x) > 2 else 0), str(x[3] if len(x) > 3 else "")))
    if not out:
        out = [(str(t).strip()[:80], -1, 0, "") for t in (it.get("texts") or ()) if str(t).strip()]
    return [x for x in out if x[0]]


def _texts(it):
    """잎 글(단추·아바타 글 빼고) — 마지막 활동·미리보기 판단 재료."""
    return [x[0] for x in _lf(it) if not ({"B", "I"} & set(x[3]))]


def _is_hdr(it):
    """구역 머리 — aria-expanded 가 있거나(펼침 단추) 안에 다른 항목을 품었다(중첩 트리). 방이 아니다(누르면 구역이 접힌다)."""
    return bool(it.get("hdr")) or bool(str(it.get("ex") or "")) or _int(it.get("nest")) > 0


def stable_name(it):
    """목록 항목의 안정 이름 → (이름, 출처 'label'|'lby'|'leaf'|'') — 화면을 내리거나 마우스를 올려도 바뀌지 않는 글.
    첫 줄 후보 = 잎 중 시각·날짜·상대 시각·숫자뿐인 배지·좁은 단추(B)·아바타/그림(I)·크기 없는 잎(S)·두 번째 줄(미리보기) 제외.
    ① aria-label 첫 조각 — 첫 줄 후보 하나와 같을 때(쓸 만한 잎이 아예 없으면 그대로. '읽지 않음, …' 같은 상태 머리말·단체방
       'A, B' 의 첫 사람만 남는 조각은 후보와 달라 버린다)
    ② aria-labelledby 첫 요소 글 — 첫 줄 후보 하나와 같을 때
    ③ 첫 줄 후보 중 aria-hidden(H) 아닌 것 → 굵은 것(≥600) → 문서 순서. 줄을 모르면(잎 묘사 없음) 모든 후보에서 같은 순서."""
    lf = _lf(it)
    cands = [x for x in lf if 1 < len(x[0]) <= 80 and not ({"B", "I", "S"} & set(x[3])) and not _BADGE.match(x[0])
             and not _timeish(x[0])]
    pool = cands
    if any(x[1] >= 0 for x in cands):
        pool = [x for x in cands if x[1] == 0] or [x for x in cands if x[1] < 0]
    pool = sorted(pool, key=lambda x: ("H" in x[3], not x[2]))     # 안정 정렬 — 같은 등급이면 문서 순서
    leaf = pool[0][0] if pool else ""
    norms = {_norm(x[0]) for x in pool}
    lb = str(it.get("label") or "").strip()
    if lb:
        head = re.split(r"[,|·]| - ", lb)[0].strip()
        if 1 < len(head) <= 80 and not _timeish(head) and not find_times(head) and (_norm(head) in norms or not cands):
            return head, "label"
    lby = str(it.get("lby") or "").strip()
    if 1 < len(lby) <= 80 and _norm(lby) in norms:
        return lby, "lby"
    return (leaf, "leaf") if leaf else ("", "")


def chat_name(item):
    """대화방 이름(안정 이름이 없을 때의 예비) — aria-label 의 첫 조각, 없으면 시각·날짜가 아닌 첫 잎."""
    lb = (item.get("label") or "").strip()
    if lb:
        head = re.split(r"[,|·]| - ", lb)[0].strip()
        if 1 < len(head) <= 60 and not find_times(head):
            return head
    for s in (item.get("texts") or []):
        s = s.strip()
        if 1 < len(s) <= 60 and not find_times(s) and not find_date(s) and not _BADGE.match(s):
            return s
    return ""


def last_activity(item, today):
    """목록 항목의 마지막 활동 → (date, (시, 분)|None) | None — 날짜·시각뿐인 잎 글자('오후 3:12'·'어제'·'화요일'·'10/5')만 본다
    (미리보기 속 '3/5 보고' 는 날짜가 아니다 — owa_parse.list_when)."""
    texts = [str(x) for x in (item.get("texts") or []) if owa_parse.is_datetime_text(x)]
    r = owa_parse.list_when(texts, today) if texts else None
    if not r:
        r = owa_parse.list_when(owa_parse.frags_of(item.get("label")), today)
    return r


def _preview(item, name):
    """미리보기 해시 — 이름·날짜·배지·단추·아바타·숨은 잎을 뺀 잎 글자(없으면 aria-label 조각). 원문은 남기지 않는다."""
    parts = [x[0] for x in _lf(item) if not ({"B", "I", "S"} & set(x[3]))]
    if not parts:
        parts = owa_parse.frags_of(item.get("label"))
    keep = [p for p in parts if p and _norm(p) != _norm(name) and not owa_parse.is_datetime_text(p) and not _BADGE.match(p)]
    if not keep:
        return ""
    return hashlib.sha1(teams_parse.clean(" ".join(keep)).encode("utf-8")).hexdigest()[:12]


def _room_of(item, run):
    """목록 항목 → 방 기록. 열쇠(ident)는 대화 ID, 없으면 안정 이름 — 방 커서(teams_web_rooms.json)의 rid 가 된다.
    sig(안정 이름 원문)는 누르기 직전 그 화면에서 항목을 다시 맞추는 데 쓴다(JS sigHit)."""
    sn, src = stable_name(item)
    name = sn or chat_name(item)
    key = str(item.get("key") or "")
    ident = key or ("n:" + _norm(sn))
    la = last_activity(item, run.today)
    return {"rid": teams_parse.room_id(ident), "ident": ident, "key": key, "name": name, "nname": _norm(name),
            "sig": sn, "src": src, "label": str(item.get("label") or ""), "last": la[0] if la else None,
            "preview": _preview(item, name), "verdict": None, "read_to": None, "skip": None}


def _items(pg):
    """JS_CHATS 응답의 항목 → 정리한 항목(texts·hdr·idx 채움)."""
    out = []
    for it in pg.get("items") or ():
        if isinstance(it, dict):
            it = dict(it)
            it["idx"] = _int(it.get("idx"), -1)
            it["texts"] = _texts(it)
            it["hdr"] = _is_hdr(it)
            out.append(it)
    return out


def _snap(br, run):
    """목록 한 화면 스냅샷 → (응답, 항목들). 첫 화면의 목록 구조(글자 없음)는 진단으로 남긴다."""
    pg = br.eval_json(_js(run, JS_CHATS)) or {}
    if isinstance(pg.get("cen"), dict) and not run.cen.get("list"):
        run.cen["list"] = pg["cen"]
    return pg, _items(pg)


def _leaf_shape(items):
    """'구조+' 의 목록 항목 잎 꼴(글자 없음) — 첫 방 항목의 잎 종류 순서('시각·이름*·미리보기·배지' — * 굵게 · (숨김) 크기 없음) +
    이 화면 방 항목 중 aria-label·labelledby 를 가진 수."""
    rooms = [it for it in items if not it["hdr"]]
    if not rooms:
        return "방 항목 없음(머리 " + str(sum(1 for it in items if it["hdr"])) + ")"
    it = rooms[0]
    sn = stable_name(it)[0]
    kinds = []
    for t, ln, b, f in _lf(it)[:8]:
        if "I" in f:
            k = "그림"
        elif "B" in f:
            k = "단추"
        elif _BADGE.match(t):
            k = "배지"
        elif _timeish(t):
            k = "시각"
        elif sn and t == sn:
            k = "이름"
        elif ln >= 1:
            k = "미리보기"
        else:
            k = "글"
        kinds.append(k + ("*" if b else "") + ("(숨김)" if "S" in f else ""))
    lbl = sum(1 for x in rooms if x.get("label"))
    lby = sum(1 for x in rooms if x.get("lby"))
    return f"{'·'.join(kinds) or '없음'} (라벨{lbl}·lby{lby}/{len(rooms)})"


class _Walk:
    """목록 걷기 상태 — 방 목록(목록 순서)·열쇠 → 방 · 방 커서 · 저장소 · 앞서 확인한 방 화면(cur) · 닫힌 구역 펼치기 기록."""

    def __init__(self, state, store, save_state):
        self.rooms, self.by, self.state, self.store, self.save_state = [], {}, state, store, save_state
        self.cur, self.how, self.capped, self.exp_tried = None, "", False, set()


def _register(run, w, it, first):
    """처음 보는 방이면 방 목록 끝에 더한다(1차 걷기·상한 안). 마지막 활동이 기간 시작 전이면 '기간 전'으로 표시한다. → 방 | None."""
    r = _room_of(it, run)
    if r["ident"] == "n:":
        if first:
            run.bump("list_noname")
        return None
    room = w.by.get(r["ident"])
    if room is not None or w.capped:
        return room
    room = r
    if room["last"] is not None and room["last"] < run.d0:
        room["skip"] = "old"
        run.bump("skipped_old")                  # 마지막 활동이 기간 시작 전 — 열지 않는다
    w.by[room["ident"]] = room
    w.rooms.append(room)
    if run.max_chats and len(w.rooms) >= run.max_chats:
        w.capped = True
        run.bump("list_capped")
    return room


def _due(w, room, phase):
    """이번 걷기에서 열 방인가 — 1차는 지난 실행에서 잘린 방(cut·roomgone)만, 2차는 아직 정하지 않은 모든 방."""
    if room.get("verdict") is not None or room.get("skip"):
        return False
    if phase == "first":
        return (w.state.get(room["rid"]) or {}).get("status") in CUT_STATES
    return True


def _expand(br, run, w, items):
    """닫힌 최상위 구역(aria-expanded=false · 단계 1 이하 · 대화 ID 없음)을 펼친다 — 지난 판이 구역 머리를 방으로 알고 눌러
    접어 두었을 수 있다(새 Teams 는 접힘을 기억한다). 신뢰 마우스 → 합성 사건 순, 다시 찍어 aria-expanded=true 면 펼침.
    → 이 화면에서 하나라도 펼쳤으면 True(같은 화면을 다시 본다). 실행마다 EXPAND_MAX 번 · 못 펼친 구역은 list_collapsed."""
    for it in items:
        if not (it["hdr"] and str(it.get("ex")) == "false" and _int(it.get("lv")) <= 1 and not it.get("key")):
            continue
        sig = stable_name(it)[0]
        k = _norm(sig) + "|" + str(_int(it.get("lv")))
        if k in w.exp_tried:
            continue
        w.exp_tried.add(k)
        if len(w.exp_tried) > EXPAND_MAX or not sig:
            run.bump("list_collapsed")
            continue
        ok = False
        for mode in ("mouse", "synth"):
            if mode == "mouse" and run.no_mouse:
                continue
            a = _aim(br, run, {"sig": sig}, it["idx"], act=_CLICK_ACT[mode], hdr=True)
            if a.get("r") not in ("ok", "fired"):
                break
            if mode == "mouse" and not _mouse(br, run, a):
                continue
            _sleep(0.8)
            _, again = _snap(br, run)
            h = next((x for x in again if x["hdr"] and stable_name(x)[0] == sig), None)
            if h is not None and str(h.get("ex")) == "true":
                ok = True
                break
        run.bump("list_expanded" if ok else "list_collapsed")
        if ok:
            return True
    return False


def _walk(br, run, w, phase):
    """목록을 위에서부터 한 화면씩 걷는다(LM28-TW-2 — 이름으로 다시 찾지 않고 그 화면 스냅샷의 항목을 그 자리에서 연다).
    phase 'first': 방 목록을 끝까지 모으며(닫힌 최상위 구역은 펼친다) 지난 실행에서 잘린 방을 연다 · 'rest': 맨 위로 되돌려
    남은 방을 연다(열 방이 다 끝나면 멈춘다). 끝: 이 걷기에서 처음 본 방이 없는 화면 LIST_STALL 번 · 'end'·'fits'.
    → 목록 끝에 닿았나(상한·예산·스크롤 영역 없음이면 False — F-07)."""
    if phase == "rest":
        try:
            if str(br.cdp.eval(_js(run, JS_LIST_TOP)) or "") != "ok":
                run.bump("list_top_none")        # 스크롤 영역 없음('다 들어감') 또는 못 찾음 — 지금 자리부터
        except Exception:  # noqa: BLE001 — 되돌리기 실패면 지금 자리부터(못 본 방은 not_reached)
            run.bump("list_top_err")
        _sleep(0.6)
    seen, stall = set(), 0
    for _ in range(LIST_SCREENS):
        if run.out_of_time():
            return False
        pg, items = _snap(br, run)
        w.how = w.how or str(pg.get("how") or "")
        if not items:
            return False
        if phase == "first":
            if not run.diag.get("leaf_rooms"):               # 방 항목이 처음 보이는 화면의 잎 꼴(접힌 구역 뒤에도)
                run.diag["leaf"] = _leaf_shape(items)
                run.diag["leaf_rooms"] = any(not it["hdr"] for it in items)
            if _expand(br, run, w, items):
                continue
        new, here = 0, []
        for it in items:
            if it["hdr"]:
                if phase == "first":
                    run.bump("list_headers")      # 구역 머리(즐겨찾기·최근 — 펼침 단추·품은 항목)는 방이 아니다
                continue
            room = _register(run, w, it, phase == "first")
            if room is None or room["ident"] in seen:
                continue
            seen.add(room["ident"])
            new += 1
            here.append((room, it))
        for room, it in here:
            if _due(w, room, phase):
                _visit(br, run, w, room, it)
                if run.out_of_time():
                    return False
        if phase == "first" and w.capped:
            return False
        if phase == "rest" and not any(_due(w, r, "rest") for r in w.rooms):
            return True
        stall = 0 if new else stall + 1
        if stall >= LIST_STALL:
            return True
        r = str(br.cdp.eval(_js(run, JS_LIST_SCROLL)) or "")
        if r in ("end", "fits"):
            return True
        if r != "scrolled":
            run.bump("list_" + re.sub(r"\W", "_", r or "none"))
            return False
        _sleep(0.6 if new else 1.5)              # 새 방이 없던 화면 뒤에는 목록이 채워질 시간을 더 준다(자리표시자만 보인 화면)
    return False


def _int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


def _pane(br, run, room):
    """대화 화면 상태(JS_PANE) — 메모리에서만 비교한다(지문·대화 ID·머리 제목을 디스크에 쓰지 않는다)."""
    p = br.eval_json(_js(run, JS_PANE, room)) or {}
    sel = p.get("sel")
    return {"n": _int(p.get("n")), "chat": str(p.get("chat") or "").strip(),
            "sel": sel if isinstance(sel, bool) else None,
            "fp": [str(x)[:64] for x in (p.get("fp") or []) if x][:8],
            "conv": str(p.get("conv") or "")[:160], "cv": str(p.get("cv") or "")[:8],
            "doc": str(p.get("doc") or "")[:200], "url": str(p.get("url") or "")[:400],
            "mi": _int(p.get("mi"), -1), "hi": _int(p.get("hi"), -1)}


def _doc_match(room, doc):
    """창 제목이 이 방인가 → True | False | None(창 제목에 방 조각이 없다) — teams_parse.doc_fits."""
    return teams_parse.doc_fits(doc, room.get("name") or room.get("nname") or "", room.get("label") or "")


def _doc_shape(doc):
    """창 제목의 가린 꼴(글자→x · 숫자·구두점·'|'·'+'·오전/오후 유지) — '구조+' 줄·dom_census 용(방 이름은 나가지 않는다)."""
    return owa_parse.mask_shape(re.sub(r"\s+", " ", str(doc or "")), 40) if doc else ""


def _title_names(room):
    """방 이름 후보(정규화) — 목록 이름, 그리고 aria-label 앞 조각 1~4개를 이은 것(단체방 머리 'A, B, C' 와 맞춘다)."""
    return teams_parse.name_keys(room.get("nname") or "", room.get("label") or "")


def _title_ok(room, chat):
    """CSV 방 이름에 머리 제목을 써도 되는가 — 정규화해 정확히 같을 때만(지난 판 그대로 — 중복 열쇠의 방 이름이 바뀌지 않게)."""
    c = _norm(chat)
    return len(c) >= 2 and c in _title_names(room)


def _title_match(room, chat):
    """전환 확인용 — 표기만 다른 머리 제목(외부·괄호·'외 2명'·단체방 이름 순서)도 그 방으로 본다(teams_parse.title_fits)."""
    return teams_parse.title_fits(chat, room.get("name") or room.get("nname") or "", room.get("label") or "")


def _aim(br, run, room, idx, act="aim", hdr=False):
    """JS_AIM — 스냅샷 순번 idx 의 항목을 대화 ID·안정 이름으로 확인(다르면 그 화면에서 다시 맞춤)하고 누를 점을 받는다
    (act synth·focus 는 JS 가 그 자리에서 합성 사건·포커스까지). → {r: ok|fired|gone, x, y, hit, why, vis, i, menu, focus?}."""
    try:
        a = br.eval_json(_js(run, JS_AIM, room, idx=idx, act=act, hdr=hdr)) or {}
    except Exception as e:  # noqa: BLE001 — 겨누기 실패는 '못 찾음'과 같다(그 방은 roomgone — 다음 실행이 다시)
        run.bump("aim_err")                      # 우리 스크립트 오류 문구만(화면 글 아님) — '구조+' 줄에 싣는다
        run.sd["aim_err"] = _scrub(str(e), 80)
        if isinstance(e, TimeoutError):          # 프레임 중간에 끊긴 연결은 재사용 금지(copilot_auto.CDP)
            try:
                br.cdp.reconnect()
            except Exception:  # noqa: BLE001
                pass
        return {"r": "error"}
    return a if isinstance(a, dict) else {}


def _input_fail(br, run, mode, e):
    """CDP 입력 오류 — 숫자·사유 이름만 남기고, 시간 초과면 연결을 다시 잇는다(프레임 중간에 끊긴 연결은 재사용 금지).
    마우스가 안 되면 이번 실행에서는 다음 방법부터."""
    run.bump("input_err")
    run.sd["input_err"] = f"{mode}:{type(e).__name__}"
    if mode == "mouse":
        run.no_mouse = True
    if isinstance(e, TimeoutError):
        try:
            br.cdp.reconnect()
        except Exception:  # noqa: BLE001
            pass


def _mouse(br, run, a):
    """신뢰 입력 누르기 — CDP Input.dispatchMouseEvent 옮김 → 누름(왼쪽, 1번) → 뗌을 겨눈 점에. → 보냈나."""
    x, y = _int(a.get("x")), _int(a.get("y"))
    if x <= 0 or y <= 0:
        return False
    try:
        br.cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0},
                    timeout=INPUT_TIMEOUT)
        for t, b in (("mousePressed", 1), ("mouseReleased", 0)):
            br.cdp.call("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "buttons": b, "clickCount": 1},
                        timeout=INPUT_TIMEOUT)
        return True
    except Exception as e:  # noqa: BLE001 — 입력이 막힌 화면·시간 초과 — 다음 방법으로
        _input_fail(br, run, "mouse", e)
        return False


_KEYS = {"Enter": (13, "\r"), "Escape": (27, "")}


def _key(br, run, name):
    """신뢰 입력 키 — CDP Input.dispatchKeyEvent(rawKeyDown → char → keyUp, copilot_auto.press_enter 와 같은 꼴). → 보냈나."""
    code, text = _KEYS[name]
    try:
        for t in ("rawKeyDown", "char", "keyUp"):
            if t == "char" and not text:
                continue
            p = {"type": t, "key": name, "code": name, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}
            if t == "char":
                p["text"] = text
            br.cdp.call("Input.dispatchKeyEvent", p, timeout=INPUT_TIMEOUT)
        return True
    except Exception as e:  # noqa: BLE001
        _input_fail(br, run, "key", e)
        return False


def _switched(room, cur, pre, p):
    """방 전환 확인(LM28 — 2026-10 새 Teams 웹 실측 뒤 다시 짬) → (확인됨, 근거, 실패 사유).
    먼저 막는다: 메시지 0개('empty') · 지금 화면 메시지 지문의 절반 이상이 앞 방(cur.fids — 앞 방을 열 때·읽는 동안 본 지문,
    그 뒤 확인 못 한 화면 것까지)에 있다('same_pane' — 앞 방 메시지를 이 방으로 적지 않는다). '바뀜'(moved) = 누르기 전 화면(pre)과
    메시지 지문이 절반 넘게 다르다(누르기 전 메시지가 없었으면 바뀐 것). 그다음 하나라도 맞으면 확인:
      sel     이 방 목록 항목(또는 그 treeitem·option 조상·안쪽)의 선택 표시가 '예' + (바뀜 또는 누르기 전부터 이 방이 선택돼 있었음)
      conv    지금 대화 ID(주소·탭 세션 기록·머리 id 의 19:…@…)가 이 방 키 + (바뀜 또는 누르기 전부터 이 방) —
              키가 없는 방은 대화 ID 가 누르기 전과 달라졌고 바뀌었고 머리 제목이 반대하지 않을 때
      title   머리 제목이 이 방 이름과 맞고(표기만 다른 경우 포함 — 외부·괄호·'외 n명'·단체방 이름 순서) + 바뀜
      doc     창 제목(document.title)의 방 조각이 이 방(teams_parse.doc_fits — '+ n'·쉼표 나열·앞부분 일치 허용) + (바뀜 또는
              누르기 전부터 창 제목이 이 방 — 이미 열려 있던 방). 창 제목은 메시지보다 먼저 바뀔 수 있어 창 제목 바뀜만으로는 아니다.
      content 머리 제목을 못 찾는 화면 — 누른 뒤 메시지가 모두 새것(메시지 ID 'm:' 또는 <time datetime>+글 해시 't:' 지문끼리만 —
              시각 없는 글 해시 'h:' 는 '방금' 같은 표기만 바뀌어도 달라진다. 't:' 의 글 해시는 JS fidOf 가 시각 요소의 글을 빼고
              만든다). 선택 표시가 '아님'이면 아니다.
    창 제목이 다른 방을 말하면(dm False) sel·content·키 없는 conv 는 쓰지 않는다(약한 근거끼리 맞서면 읽지 않는다 — P4).
    (선택 표시만 먼저 옮고 화면은 앞 방 그대로인 순간을 첫 방에서도 막으려고 sel·conv 에도 '바뀜'을 건다 — 앞 방 지문이 없는 첫 방.)
    실패 사유: empty · same_pane · unchanged(누른 뒤 메시지·머리·창 제목·주소 모두 그대로) · title_diff(바뀌었는데 머리 제목이나
    창 제목이 다른 방) · unverified(바뀌었는데 확인할 표지 없음)."""
    if p["n"] <= 0:
        return False, "", "empty"
    fp = list(p["fp"])
    pool = (cur or {}).get("fids") or set()
    if pool and teams_parse.overlap(fp, pool) >= STALE_RATIO:
        return False, "", "same_pane"
    pre_fp = set(pre.get("fp") or ())
    moved = (not pre_fp) or teams_parse.overlap(fp, pre_fp) < STALE_RATIO
    head_moved = _norm(p["chat"]) != _norm(pre.get("chat"))
    doc_moved = (p.get("doc") or "") != (pre.get("doc") or "") or (p.get("url") or "") != (pre.get("url") or "")
    key = room.get("key") or ""
    tm = _title_match(room, p["chat"]) if p["chat"] else None       # None = 머리 제목을 못 찾는 화면
    dm = _doc_match(room, p.get("doc"))                              # None = 창 제목에 방 조각이 없다
    if p["sel"] is True and (moved or pre.get("sel") is True) and dm is not False:
        return True, "sel", ""
    if p["conv"] and key and p["conv"] == key and (moved or pre.get("conv") == key):
        return True, "conv", ""
    if p["conv"] and not key and pre.get("conv") and p["conv"] != pre["conv"] and moved and tm is not False and dm is not False:
        return True, "conv", ""
    if tm and moved:
        return True, "title", ""
    if dm and (moved or _doc_match(room, pre.get("doc"))):
        return True, "doc", ""
    ids = bool(fp) and bool(pre_fp) and all(x[:2] in ("m:", "t:") for x in fp + list(pre_fp))
    if tm is None and dm is not False and p["sel"] is not False and ids and teams_parse.overlap(fp, pre_fp) == 0:
        return True, "content", ""
    if not moved and not head_moved and not doc_moved:
        return False, "", "unchanged"
    return False, "", ("title_diff" if (tm is False or dm is False) else "unverified")


def _confirm(br, run, room, cur, pre, limit):
    """누른 뒤 limit 초까지 화면을 본다 → (확인됨, 근거|실패 사유, 마지막 화면)."""
    t_end = _mono() + limit
    why, p = "unchanged", None
    while True:
        _sleep(0.25)
        p = _pane(br, run, room)
        ok, how, w = _switched(room, cur, pre, p)
        if ok:
            return True, how, p
        why = w or why
        if _mono() >= t_end:
            return False, why, p


def _click_order(run):
    """누르는 방법 순서 — 통한 방법을 먼저, 그다음 마우스(신뢰 입력) → 합성 사건 → 포커스 + 키. 마우스 입력이 막혔으면 뺀다."""
    modes = [x for x in CLICK_MODES if not (x == "mouse" and run.no_mouse)]
    m = run.sd.get("how_click")
    return ([m] if m in modes else []) + [x for x in modes if x != m]


def _remember(run, p):
    """확인된 화면에서 맞은 후보를 기억한다 — 다음 방부터 그 메시지·머리 후보를 먼저 쓴다."""
    if 0 <= p.get("mi", -1) < len(_MSG):
        run.pref["msg"] = p["mi"]
    if 0 <= p.get("hi", -1) < len(_HEAD):
        run.pref["head"] = p["hi"]
        run.sd["how_head"] = _HEAD_SELS[p["hi"]]
    if p.get("cv"):
        run.sd["how_conv"] = p["cv"]


def _capture(br, run, kind):
    """화면 구조 진단(JS_CENSUS)을 한 번씩만 — 첫 실패 화면이 이긴다(원인 확정에 쓸모가 크다). 성공·빈 목록 화면은 아직 없을 때만.
    한 실행에 많아야 2번(성공 1 + 실패 1)."""
    have = run.cen.get("pane_kind")
    if have == "fail" or (have and kind != "fail"):
        return
    try:
        r = br.eval_json(_js(run, JS_CENSUS)) or {}
    except Exception as e:  # noqa: BLE001 — 진단은 수집을 막지 않는다(우리 스크립트 오류 문구만 남긴다)
        run.sd["census_err"] = _scrub(str(e), 80)
        return
    if isinstance(r, dict) and r:
        run.cen["pane"], run.cen["pane_kind"] = r, kind


def open_room(br, run, room, it, cur):
    """방을 그 화면 스냅샷 항목(it — 순번·행 사각형)에서 열고 전환을 확인한다 → 확인한 화면 상태(dict — n·chat·fp…) | None
    (R-ROOMGONE — 그 방 행 0). 누르기 직전마다 JS_AIM 이 같은 순번의 항목이 이 방(대화 ID·안정 이름)인지 보고 다르면 그 화면에서
    다시 맞춘다(못 맞추면 open_notfound). 누르는 방법: 통한 방법 먼저, 없으면 신뢰 마우스 → 합성 사건 → 포커스 + CDP Enter.
    방법마다 _switched 로 확인한다(첫 방법은 OPEN_WAIT×2 — 느린 회사 PC). 방법별 시도(click_<방법>)와 그 뒤 창 제목이 바뀐 수
    (click_<방법>_doc)를 센다. 실패는 사유별로: open_notfound · open_same_pane(앞 방 그대로) · pane_stuck(+ pane_empty·
    pane_unchanged·pane_title_diff·pane_unverified). cur = 앞서 확인한 방 {rid, chat, n, fids} — 첫 방이면 None.
    확인 못 한 화면의 지문은 cur.fids 에 보탠다(다음 방 비교)."""
    pre = _pane(br, run, room)                    # 누르기 전 화면 — '바뀌었나'의 기준
    found, why, last = False, "unchanged", None
    for k, mode in enumerate(_click_order(run)):
        a = _aim(br, run, room, it.get("idx", -1), act=_CLICK_ACT[mode])
        if a.get("r") not in ("ok", "fired"):
            if found:
                continue                          # 앞 방법이 화면을 바꿔 항목이 잠깐 빠졌다 — 다음 방법으로
            break                                 # 목록에서 그 방을 찾지 못함(재렌더·가상 목록)
        found = True
        run.bump("click_" + mode)
        if a.get("menu"):
            _key(br, run, "Escape")              # 앞 시도가 연 메뉴('…')를 신뢰 입력으로 닫는다
        if mode == "mouse" and not _mouse(br, run, a):
            continue
        if mode == "key" and not _key(br, run, "Enter"):
            continue
        ok, how, last = _confirm(br, run, room, cur, pre, OPEN_WAIT * (2 if k == 0 else 1))
        if last is not None:
            if (last.get("doc") or "") != (pre.get("doc") or ""):
                run.bump("click_" + mode + "_doc")
            run.diag["doc"] = _doc_shape(last.get("doc"))
        if ok:
            run.bump("open_by_" + how)
            run.sd["how_click"], run.sd["how_open"] = mode, how
            _remember(run, last)
            _capture(br, run, "ok")
            _sleep(0.4)                           # 머리가 먼저 바뀌고 메시지가 늦게 붙는 화면 — 한 번 더 숨을 고른다
            return last
        why = how
    if not found:
        run.bump("open_notfound")
    elif why == "same_pane":
        run.bump("open_same_pane")
    else:
        run.bump("pane_stuck")
        run.bump("pane_" + why)
    if cur is not None and last is not None:
        cur.setdefault("fids", set()).update(last.get("fp") or ())
    _capture(br, run, "fail")
    return None


def parse_page(page, run, chat):
    """대화 화면 한 장 → [{ident, mn, inh, dt?, au?, bd?, me?}] (문서 순서). 날짜를 못 짚은 메시지는 dt 없이(정체 판정용 ident 만).
    작성자: 화면이 말한 이름 → 내 말풍선이면 '나' → 직전 작성자를 잇는다(남의 말풍선이 내 말풍선 뒤면 잇지 않는다) →
    화면 전체에 작성자 표식이 없는 스킨이면 첫 잎 글자(LM24).
    LM28(E) 진단: mn = 화면의 내 말풍선 판정(True·False·None 판정불가) · inh = 판정불가인데 직전 작성자를 이어받았다(read_room 이
    저장한 행마다 mine_t·mine_f·mine_n·au_inherit 로 센다 — '구조:' 줄의 '내 메시지')."""
    items = [it for it in (page.get("items") or []) if isinstance(it, dict)]
    has_author = any(it.get("t") != "sep" and explicit_author(it) for it in items)
    out, cur, last_au, last_me = [], None, "", False
    for it in items:
        if it.get("t") == "sep":
            d = find_date(it.get("text"), run.d0, run.d1) or rel_date(it.get("text"), run.today)
            if not d and it.get("iso"):          # 구분선의 <time datetime> (일반 읽기 화면)
                v = iso_dt(it.get("iso"))
                d = v.date() if v else None
            if d:
                cur = d
            continue
        texts = [str(x) for x in (it.get("texts") or [])]
        idsrc = str(it.get("mid") or "") or "|".join((str(it.get("label") or "")[:200], str(it.get("ts") or ""),
                                                       str(it.get("body") or "")[:200], " ".join(texts[:4])[:200]))
        m = {"ident": hashlib.sha1(idsrc.encode("utf-8")).hexdigest()[:16]}
        # 머리 조각(화면이 '이 메시지의 시각' 이라 말하는 것)과 본문을 나눠 넘긴다 — 본문 날짜를 시각으로 삼지 않는다.
        head = [str(x) for x in ((it.get("iso") or []) + [it.get("ts") or ""]
                                 + list(it.get("titles") or []) + [it.get("label") or ""])]
        dt, how = stamp(head, texts[:3], cur, run.d0, run.d1, run.today)
        mine = it.get("mine")
        au = explicit_author(it)
        inh = False
        if mine is True:
            au = au or "나"
        elif not au:
            if has_author:
                if last_au and not (mine is False and last_me):
                    au = last_au
                    inh = mine is None
            else:
                au = author_of(it, texts)
        m.update(mn=mine if mine in (True, False) else None, inh=inh)
        if au:
            last_au, last_me = au, (mine is True or _norm(au) in run.selfs)
        if not dt:
            run.bump("no_time")
            out.append(m)
            continue
        if not au:
            run.bump("no_author")                  # 작성자 머리가 화면 위에 있다 — 더 되감으면 그때 읽힌다
            out.append(m)
            continue
        bd = body_of(it, texts, au, it.get("ts") or "")
        if len(bd) < 3:
            run.bump("no_body")
            out.append(m)
            continue
        m.update(dt=dt, au=au, bd=bd, how=how, me=(mine is True or _norm(au) in run.selfs), chat=chat)
        out.append(m)
    return out


def _height(br, run):
    p = br.eval_json(_js(run, JS_HEIGHT)) or {}
    return {"h": _int(p.get("h")), "n": _int(p.get("n")), "f": str(p.get("f") or "")}


def _wait_growth(br, run, base, limit):
    """지난 메시지가 붙을 때까지(높이·메시지 수·맨 위 메시지가 바뀜) 확인하며 기다린다 → True | False(limit 초 동안 그대로)."""
    t_end = _mono() + limit
    while True:
        _sleep(0.4)
        p = _height(br, run)
        if p["h"] > base.get("h", 0) or p["n"] != base.get("n", 0) or p["f"] != base.get("f", ""):
            return True
        if _mono() >= t_end:
            return False


def _scroll_js(run, deep):
    return _js(run, JS_SCROLL_UP, deep=deep)


def scroll_up(br, run):
    """위로 한 화면 → 'scrolled'(또는 맨 위에서 지난 메시지가 더 붙음) | 'top_confirmed' | 'no_scroller'.
    'top' 이면 TOP_WAIT 초씩 TOP_CONFIRM 번 로드를 기다린다 — 그동안 한 번도 늘지 않아야 맨 위 확인(W1-05).
    'no-scroller' 면 스크롤되는 조상을 다시 찾는다(F-06) — 그래도 없으면 no_scroller('처음까지 읽음'이 아니다)."""
    r = br.eval_json(_scroll_js(run, False)) or {}
    if r.get("r") not in ("scrolled", "top"):    # 'no-scroller' — 또는 스크립트 오류로 빈 응답: 맨 위로 보면 안 된다(F-06)
        run.bump("scroll_refind")
        r = br.eval_json(_scroll_js(run, True)) or {}
        if r.get("r") not in ("scrolled", "top"):
            return "no_scroller"
        run.bump("scroll_refound")
    if r.get("how"):
        run.sd["how_scroll"] = str(r["how"])
    base = {"h": _int(r.get("h")), "n": _int(r.get("n")), "f": str(r.get("f") or "")}
    if r.get("r") == "scrolled":
        _wait_growth(br, run, base, SCROLL_WAIT)
        return "scrolled"
    for _ in range(TOP_CONFIRM):
        if _wait_growth(br, run, base, TOP_WAIT):
            run.bump("top_loaded")             # 맨 위에서 기다렸더니 지난 메시지가 붙었다 — 맨 위가 아니었다
            return "scrolled"
        r2 = br.eval_json(_scroll_js(run, False)) or {}
        if r2.get("r") == "scrolled":
            return "scrolled"
    return "top_confirmed"


def _usable(st, run):
    """지난 확인(newest_read)으로 증분을 해도 되는가 — 확인한 구간이 이번 기간 시작을 덮을 때만."""
    return bool(st.get("newest_read")) and bool(st.get("oldest")) and str(st["oldest"]) <= run.d0.isoformat()


def read_room(br, run, room, st, fids=None):
    """한 방을 맨 아래(최신)부터 위로 되감으며 읽는다 → (rows, events, newest(해시, 날짜)|None, pages).
    멈춤: 지난 newest_read 와 겹침(overlap) · 기간 시작 전 날짜(reached_d0) · 맨 위 확인 · 스크롤 영역 없음 · 정체 · 되감기 상한 ·
    예산 · 머리 제목이 다른 방으로 바뀜(gone — 그 방 행 0 · 같은 머리 후보로 읽은 제목끼리만 비교. 창 제목은 알림으로 깜박일 수
    있어 gone 판정에 쓰지 않는다). 머리 후보가 없는 화면은 창 제목의 방 조각을 CSV 방 이름 후보로(정규화해 목록 이름과 같을 때만 —
    목록 이름이 없는 방은 그것을). 읽은 경로(후보 data-tid · 일반 읽기)를 방마다 센다(read_cand·read_gen).
    fids: 이 방에서 본 메시지 지문을 모으는 집합(다음 방의 '앞 방 그대로' 판정 — 메모리에만)."""
    prev = st.get("newest_read") if _usable(st, run) else ""
    rows, seen, events = {}, set(), set()
    stall = scrolls = pages = 0
    newest, oldest = None, None
    chat, head0, hi0, gen = room["name"], "", None, False
    while True:
        if run.out_of_time():
            events.add("budget")
            break
        page = br.eval_json(_js(run, JS_MSGS)) or {}
        pages += 1
        run.bump("pages")
        if page.get("how"):
            run.sd["how_msg"] = str(page["how"])[:80]
        if _int(page.get("mi"), -1) == GEN:
            gen = True
        if fids is not None:
            fids.update(str(it["fid"])[:64] for it in (page.get("items") or ())
                        if isinstance(it, dict) and it.get("t") == "msg" and it.get("fid"))
        head, hi = _norm(page.get("chat")), page.get("hi")
        if head and head0 and head != head0 and hi == hi0:
            events.add("gone")                   # 읽는 사이 다른 방이 열렸다 — 이 방 것으로 적지 않는다
            rows = {}
            break
        if head and not head0:
            head0, hi0 = head, hi
        if page.get("chat") and _title_ok(room, page.get("chat")):
            chat = str(page["chat"]).strip()
        elif not page.get("chat") and page.get("doc"):
            frag = (teams_parse.doc_room(page.get("doc")) or [""])[0]
            if frag and (_title_ok(room, frag) or not room.get("name")):
                chat = frag
        new = 0
        for m in parse_page(page, run, chat):
            if m["ident"] in seen:
                continue
            seen.add(m["ident"])
            new += 1
            if "dt" not in m:
                continue
            dt = m["dt"]
            day, hm = dt.date(), dt.strftime("%H:%M")
            h = teams_parse.msg_hash(day, hm, m["au"], m["bd"], run.ctx)
            if newest is None or dt >= newest[0]:
                newest = (dt, h)
            oldest = day if oldest is None else min(oldest, day)
            if prev and h == prev:
                events.add("overlap")
            if run.d0 <= day <= run.d1:
                k = teams_parse.key_of(day, hm, m["au"], m["chat"], m["bd"], run.ctx)
                # prec: 날짜만 짚은 메시지(stamp 'date' — 12:00 은 자리표)는 time_precision=date 로 남긴다(LM28 E — 버리지 않는다)
                rows.setdefault(k, {"time": dt.strftime("%Y-%m-%d %H:%M"), "from": m["au"], "chat": m["chat"],
                                    "kind": "sent" if m["me"] else "msg", "summary": m["bd"][:SUMMARY_MAX],
                                    "prec": "date" if m.get("how") == "date" else "minute",
                                    "mn": m.get("mn"), "inh": bool(m.get("inh"))})
        if "overlap" in events:                  # 지난 실행이 읽은 데까지 이어졌다(겹침으로 검증) — 더 되감을 이유가 없다
            break
        if oldest is not None and oldest < run.d0:
            events.add("reached_d0")             # 기간보다 오래된 데까지 왔다
            break
        stall = 0 if new else stall + 1
        if stall >= ROOM_STALL:
            events.add("stall")
            break
        if scrolls >= run.max_scroll:
            events.add("max_scroll")
            break
        r = scroll_up(br, run)
        if r == "no_scroller":
            events.add("no_scroller")            # 첫 실측: 이걸 top 으로 보아 방마다 한 화면만 읽고 1월부터 다 읽은 것으로 적었다
            break
        if r == "top_confirmed":
            events.add("top_confirmed")
            break
        scrolls += 1
        run.bump("scrolls")
    if pages:
        run.bump("read_gen" if gen else "read_cand")
    # 내 메시지 진단(LM28 E — '구조:' 줄): 이 방에서 남길 행 중 내 발신 · 화면 판정(내 것·남의 것·판정불가) · 판정불가인데 직전
    # 작성자를 이어받은 행 · 날짜만 짚은 행
    for r in rows.values():
        run.bump("rows_read")
        run.bump("rows_sent", 1 if r["kind"] == "sent" else 0)
        run.bump("mine_t" if r.get("mn") is True else ("mine_f" if r.get("mn") is False else "mine_n"))
        run.bump("au_inherit", 1 if r.get("inh") else 0)
        run.bump("date_only", 1 if r.get("prec") == "date" else 0)
    nw = (newest[1], newest[0].date().isoformat()) if newest else None
    return list(rows.values()), events, nw, pages


def next_state(st, verdict, events, newest, room, run):
    """방 커서 갱신 — newest_read 는 complete·incremental_ok 일 때만 앞으로 옮긴다. 잘린 방은 상태만 바꾸고 지난 확인 구간
    (oldest·newest_read)을 그대로 둔다(다음 실행이 그 구간과 겹치면 incremental_ok)."""
    st = dict(st or {})
    st["status"] = verdict
    st["t"] = run.today.isoformat()
    if verdict in teams_parse.VERIFIED:
        if verdict == "complete":
            st["oldest"] = (teams_parse.TOP_DATE.isoformat() if "top_confirmed" in events and "reached_d0" not in events
                            else run.d0.isoformat())
        if newest:
            st["newest_read"], st["newest_day"] = newest
        st["read_day"] = run.today.isoformat()
        if room.get("last") is not None:
            st["list_day"] = room["last"].isoformat()
            st["list_prev"] = room.get("preview") or ""
    return st


def _unchanged(room, st, run):
    """목록의 마지막 활동 날짜·미리보기가 지난 확인 때와 같고, 그 확인이 마지막 활동 날 **다음 날 이후**였다 → 새 메시지 없음
    (열지 않는다). 확인한 날과 마지막 활동 날이 같으면 그 뒤 같은 날 온 메시지가 미리보기를 안 바꿨을 수 있어 연다.
    오늘 활동한 방은 늘 연다."""
    if not _usable(st, run) or room.get("last") is None or room["last"] >= run.today or not room.get("preview"):
        return False
    last = room["last"].isoformat()
    return (st.get("list_day") == last and st.get("list_prev") == room["preview"]
            and str(st.get("read_day") or "") > last)


# ── 저장 ─────────────────────────────────────────────────────────────────────
def _esc(s):
    s = re.sub(r"[\r\n]+", " ", str(s or ""))
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


class Store:
    """teams_web.csv 누적 저장 — 덮어쓰지 않는다(이 파일은 실행할 때마다 그 시점에 보이는 대화만 담는다). 방마다 add → flush.
    중복은 teams_parse.key_of(날짜·시각·보낸이·정제 방·정제 요지 40자)로 — 다른 teams_*.csv(Graph·창 읽기)와 겹치는 메시지도
    다시 적지 않는다.
    LM28(E) — 지난 판의 행을 제자리에서 바로잡는다(행은 늘지 않는다 · dirty → flush):
      · 정밀도 래칫: 같은 날·보낸이·방·글의 날짜만 행(time_precision=date)은 분 단위 행이 오면 그것으로 바꾸고(prec_up), 분 단위
        행이 이미 있으면 날짜만 사본은 적지 않는다.
      · 내 발신: 같은 날·시각·방·글을 지난 판이 남의 말(직전 작성자를 이어받음)로 적었으면 이번 내 발신 행으로 바꾼다(mine_fixed —
        TW-3 이 커서를 버리고 처음부터 다시 읽는 이유). 다른 경로가 이미 잡은 메시지면 우리 파일의 틀린 행만 지운다."""

    def __init__(self, path, force=False, ctx=None):
        self.path, self.ctx = path, ctx
        self.rows, self.keys, self._other = [], set(), None
        self.loose, self.timed, self.recv = {}, set(), {}     # 래칫 색인 — 시각 뺀 열쇠 → 날짜만 행 · 분 단위 열쇠 · 보낸이 뺀 열쇠 → 남의 행
        self.dirty, self.prec_up, self.mine_fixed = False, 0, 0
        if os.path.exists(path) and not force:
            try:
                with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
                    for r in csv.DictReader(f):
                        if not r.get("time") or None in r.values():
                            continue
                        k = teams_parse.row_key(r.get("time"), r.get("from"), r.get("chat"), r.get("summary"), ctx)
                        if k in self.keys:
                            continue
                        self.keys.add(k)
                        self._put([r.get("time") or "", r.get("from") or "", r.get("chat") or "", r.get("kind") or "",
                                   r.get("replied_time") or "", r.get("summary") or "",
                                   (r.get("time_precision") or "").strip().lower()], k, old=True)
            except OSError:
                pass

    @staticmethod
    def _parts(k):
        """row_key (날, 시각, 보낸이, 방, 글) → (시각 뺀 열쇠, 보낸이 뺀 열쇠)"""
        return (k[0],) + tuple(k[2:]), tuple(k[:2]) + tuple(k[3:])

    def _put(self, row, k, i=None, old=False):
        """행을 넣거나(i 없음) i 자리를 바꾸고 래칫 색인을 맞춘다 → 자리. 남의 행 색인(recv — 내 발신으로 바로잡을 후보)은 지난 판이
        남긴 행(old)만 — 이번 실행이 읽은 남의 글(단체방의 같은 분 '넵')을 내 글이 덮지 않게."""
        if i is None:
            self.rows.append(row)
            i = len(self.rows) - 1
        else:
            self.rows[i] = row
        lk, sk = self._parts(k)
        if row[6] == "date":
            self.loose[lk] = i
        else:
            self.timed.add(lk)
        if old and row[3] != "sent":
            self.recv[sk] = i
        return i

    def _unindex(self, i):
        old = self.rows[i]
        if not old:
            return
        lk, sk = self._parts(teams_parse.row_key(old[0], old[1], old[2], old[5], self.ctx))
        if self.loose.get(lk) == i:
            del self.loose[lk]
        if self.recv.get(sk) == i:
            del self.recv[sk]

    def count(self):
        return sum(1 for r in self.rows if r)

    def other_keys(self):
        """이미 모아 둔 다른 teams_*.csv 전부의 열쇠 — Graph·창 읽기와 겹치는 메시지를 다시 적지 않는다."""
        if self._other is None:
            self._other = set()
            for p in glob.glob(os.path.join(os.path.dirname(self.path), "teams_*.csv")):
                if os.path.abspath(p) == os.path.abspath(self.path):
                    continue
                try:
                    with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
                        for r in csv.DictReader(f):
                            if r.get("time"):
                                self._other.add(teams_parse.row_key(r.get("time"), r.get("from"), r.get("chat"),
                                                                    r.get("summary"), self.ctx))
                except OSError:
                    continue
        return self._other

    def add(self, rows):
        """→ (새로 더한 행 수, 다른 경로와 겹쳐 뺀 수). 지난 판 행을 바로잡은 것(prec_up·mine_fixed)은 새 행이 아니다 — dirty 로 알린다."""
        added = dup = 0
        other = self.other_keys()
        for r in rows:
            prec = "date" if r.get("prec") == "date" else "minute"
            k = teams_parse.row_key(r["time"], r["from"], r["chat"], r["summary"], self.ctx)
            if k in self.keys:
                continue
            self.keys.add(k)
            lk, sk = self._parts(k)
            if prec == "date" and lk in self.timed:
                continue                        # 같은 글의 분 단위 행이 이미 있다 — 날짜만 사본은 적지 않는다
            row = [r["time"], r["from"], r["chat"], r["kind"], "", r["summary"], prec]
            i = self.loose.pop(lk, None) if prec == "minute" else None
            if i is not None:
                self.prec_up += 1
            elif r["kind"] == "sent":
                i = self.recv.pop(sk, None)
                if i is not None:
                    self.mine_fixed += 1
            if i is not None:                   # 지난 판의 행을 제자리에서 바로잡는다
                self._unindex(i)
                if k in other:
                    self.rows[i] = None         # 다른 경로가 이미 잡은 메시지 — 우리 파일의 틀린 행만 지운다
                else:
                    self._put(row, k, i)
                self.dirty = True
                continue
            if k in other:                      # Graph·창 읽기가 이미 잡은 메시지
                dup += 1
                continue
            self._put(row, k)
            added += 1
        return added, dup

    def flush(self):
        """시각순으로 다시 쓴다(rows 의 자리는 그대로 — 래칫 색인이 자리를 가리킨다). → 쓴 행 수"""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        out = sorted((r for r in self.rows if r), key=lambda x: x[0])
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(HDR + "\n")
            for r in out:
                f.write(",".join(_esc(c) for c in r) + "\n")
        os.replace(tmp, self.path)
        self.dirty = False
        return len(out)


def state_ver(cfg):
    try:
        ep = int(((cfg.get("collect") or {}).get("cursorEpoch")) or 1)
    except (TypeError, ValueError, AttributeError):
        ep = 1
    return f"{COLLECTOR_VER}|{ep}"


def state_load(path, ver):
    """→ (rooms 상태 dict, 폐기했나). 판·cursorEpoch(ver)가 다르면 버리고 처음부터 읽는다."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}, False
    if not isinstance(o, dict) or o.get("ver") != ver or not isinstance(o.get("rooms"), dict):
        return {}, True
    return {k: v for k, v in o["rooms"].items() if isinstance(v, dict)}, False


def state_save(path, ver, rooms, census=None):
    """방 커서 저장 — census(dom_census: 글자 없는 화면 구조 진단)를 주면 함께 싣는다(진단 묶음이 data\\m365\\*.json 을 싣는다)."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        o = {"ver": ver, "rooms": rooms}
        if census:
            o["dom_census"] = census
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(o, f, ensure_ascii=False, indent=0)
        os.replace(tmp, path)
    except OSError:
        pass


# ── 화면 구조 진단('구조' 줄 · dom_census) ──────────────────────────────────────
OPEN_KEYS = ("open_notfound", "pane_stuck", "open_same_pane", "open_by_sel", "open_by_title", "open_by_conv",
             "open_by_doc", "open_by_content", "pane_empty", "pane_unchanged", "pane_title_diff", "pane_unverified",
             "open_aborted", "room_error", "input_err")
PLUS_MAX = 380                  # '구조+' 줄 길이 상한(글자) — '[teams-web] ' 를 붙여도 run.py·last_run.json 의 census 400자 안
_RX_MAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def _hook(s):
    """코드가 붙인 표지(data-tid·role 값)만 — ASCII 영문으로 시작하는 앞머리, 4자리 이상 숫자부터는 버린다."""
    m = re.match(r"[A-Za-z][A-Za-z0-9_.\-]{0,39}", str(s or ""))
    return re.sub(r"\d{4,}.*$", "", m.group(0)) if m else ""


def _scrub(s, n=100):
    """화면이 이미 가린 구조 글을 한 번 더 — 시각 토큰(오전·오후·어제) 밖의 비ASCII 글자는 x, 메일 주소·대화 ID 꼴은 지운다."""
    s = re.sub(r"오전|오후|어제|([^\x00-\x7f])", lambda m: "x" if (m.group(1) and m.group(1).isalpha()) else m.group(0),
               str(s or ""))
    return _RX_MAIL.sub("<@>", s)[:n]


def _ints(v, n=16):
    """숫자 목록만(후보별 개수·[높이, 보이는 높이, 위치]) — 그 밖의 값은 -1."""
    if not isinstance(v, list):
        return []
    return [[_int(y) for y in x[:3]] if isinstance(x, list) else _int(x, -1) for x in v[:n]]


def _sel_desc(sc, lc):
    if isinstance(sc, dict) and sc:
        n = _int(sc.get("n"))
        if _int(sc.get("asa")):
            return f"aria-selected {_int(sc.get('ast'))}/{_int(sc.get('asa'))}"
        if _int(sc.get("ac")):
            return f"aria-current {_int(sc.get('ac'))}/{n}"
        if _int(sc.get("ds")):
            return f"data-selected {_int(sc.get('ds'))}/{n}"
        return "없음" + (f"(class {_int(sc.get('cls'))})" if _int(sc.get("cls")) else "")
    if lc:
        return f"예{_int(lc.get('selT'))}/표시{_int(lc.get('selA'))}"
    return "-"


def census_line(run):
    """'구조:' 한 줄(200자 안팎 — 현장 사진 한 장으로 원인 확정): 목록(맞은 후보·첫 방 항목 role·data-tid·대화 ID 가진 수) ·
    전환 실패 사유별 수(못찾음·화면멈춤(빈 화면·그대로·제목 다름·표지 없음)·앞방그대로) · 확인 근거별 수(창제목 = document.title) ·
    메시지 후보별 개수(없으면 일반 읽기 단위 수 '일반=n') · 머리 후보(글자 수 · 없으면 창 제목에 방 조각이 있었나) · 선택 표시 종류 ·
    대화 ID 출처 · 통한 누르기 방법(마우스 = CDP 신뢰 입력 · 합성 · 키)."""
    c, lc, pc = run.c, run.cen.get("list") or {}, run.cen.get("pane") or {}
    li = _LIST_CODE[_LIST_SELS.index(run.sd["how_list"])] if run.sd.get("how_list") in _LIST_SELS else "-"
    tid = _hook(lc.get("tid"))
    out = [f"목록 {_int(c.get('rooms_listed'))}({li}·{_hook(lc.get('role')) or _hook(lc.get('tag')) or '-'}"
           f"{'·tid=' + tid if tid else ''}·키{_int(lc.get('keyed'))})",
           f"열기 못찾음 {_int(c.get('open_notfound'))}",
           f"화면멈춤 {_int(c.get('pane_stuck'))}(빈{_int(c.get('pane_empty'))}·그대로{_int(c.get('pane_unchanged'))}"
           f"·제목다름{_int(c.get('pane_title_diff'))}·표지없음{_int(c.get('pane_unverified'))})",
           f"앞방그대로 {_int(c.get('open_same_pane'))}",
           f"확인 선택{_int(c.get('open_by_sel'))}·제목{_int(c.get('open_by_title'))}·ID{_int(c.get('open_by_conv'))}"
           f"·창제목{_int(c.get('open_by_doc'))}·내용{_int(c.get('open_by_content'))}"]
    msg = [x if isinstance(x, int) else 0 for x in (pc.get("msg") or [])][:len(_MSG)]
    hits = [f"{_MSG[i][1]}={v}" for i, v in enumerate(msg) if v > 0]
    gen = _int(pc.get("gen"), -1)
    out.append("메시지 " + ("·".join(hits[:3]) if hits else (f"일반={gen}" if gen > 0 else ("0" if msg else "-"))))
    hd = [x if isinstance(x, int) else -1 for x in (pc.get("head") or [])][:len(_HEAD)]
    hh = [f"{_HEAD[i][1]}({v}자)" for i, v in enumerate(hd) if v > 0]
    doc_room = bool(teams_parse.doc_room(pc.get("doc"))) if pc else False
    out.append("머리 " + (hh[0] if hh else ("창제목" if doc_room else ("없음" if hd else "-"))))
    out.append("선택표시 " + _sel_desc(pc.get("sel"), lc))
    out.append("ID " + ((str(pc.get("conv") or "") or "없음") if pc else "-"))
    out.append("클릭 " + _CLICK_KO.get(run.sd.get("how_click"), "-"))
    if c.get("open_aborted"):
        out.append(f"중단 {_int(c.get('open_aborted'))}")
    if c.get("room_error"):
        out.append(f"오류 {_int(c.get('room_error'))}({str(run.sd.get('room_error_msg') or '')[:40]})")
    # 내 메시지(LM28 E) — 남긴 행 중 내 발신 · 화면이 내 것/남의 것을 말하지 않은 행 · 그중 직전 작성자를 이어받은 행(내 말이 남의 말로
    # 적혔을 수 있다) · 날짜만 짚은 행
    out.append(f"내 메시지 {_int(c.get('rows_sent'))}/{_int(c.get('rows_read'))} · 판정불가 {_int(c.get('mine_n'))} · "
               f"이어받음 {_int(c.get('au_inherit'))}" + (f" · 날짜만 {_int(c.get('date_only'))}" if c.get("date_only") else ""))
    return "구조: " + " · ".join(out)


def _tids2(v, n=8):
    """대화 영역 data-tid 'hook:개수' 목록 → 다시 가린 것(ASCII 앞머리·4자리 이상 숫자 버림·개수는 숫자만)."""
    out = []
    for x in (v if isinstance(v, list) else [])[:n]:
        h, _, k = str(x).rpartition(":")
        h = _hook(h)[:20]
        if h:
            out.append(f"{h}:{_int(k)}")
    return out


def _lvs(v):
    """aria-level 분포 '단계:수' 목록 → 다시 가린 것(숫자·'-' 만)."""
    out = []
    for x in (v if isinstance(v, list) else [])[:6]:
        a, _, b = str(x).partition(":")
        a = a if (a == "-" or a.isdigit()) else "?"
        out.append(f"{a[:3]}:{_int(b)}")
    return out


def census_plus(run):
    """'구조+:' 한 줄(LM28-TW-2 — 선택자와 무관한 신호로 원인 확정): 창 제목 꼴(글자 x · '|'·'+'·숫자 유지) · 누르기 방법별
    시도/그 뒤 창 제목이 바뀐 수 · 대화 영역(목록 밖) time[datetime] 수(문서 전체·iframe 안) · 대화 영역 data-tid 상위 8 · 목록 항목
    잎 꼴 · aria-level 분포·aria-expanded 참/거짓 · 펼친/못 펼친 구역 · 읽은 경로(후보·일반) · 문서 보임·초점. 글자 없음."""
    c, lc, pc, dg = run.c, run.cen.get("list") or {}, run.cen.get("pane") or {}, run.diag
    doc = dg.get("doc") or (_doc_shape(pc.get("doc")) if pc else "")
    out = ["창 " + (doc or "-"),
           "누르기 " + "·".join(f"{_CLICK_KO[m]}{_int(c.get('click_' + m))}/{_int(c.get('click_' + m + '_doc'))}"
                              for m in CLICK_MODES)]
    tids = []
    if pc:
        s = f"시각 {_int(pc.get('times'), -1)}"
        if _int(pc.get("tall")) > _int(pc.get("times")):
            s += f"(문서{_int(pc.get('tall'))})"
        ifr = _ints(pc.get("ifr"), 3)
        if len(ifr) == 3 and ifr[0]:
            s += f"·틀{ifr[0]}(열림{ifr[1]}·시각{ifr[2]})"
        if _int(pc.get("sh")):
            s += f"·섀도{_int(pc.get('sh'))}"
        out.append(s)
        tids = _tids2(pc.get("tids2"))
        out.append("tid " + ("·".join(tids) if tids else "없음"))
    out.append("잎 " + str(dg.get("leaf") or "-")[:80])       # 우리가 만든 낱말(시각·이름·미리보기…)과 숫자뿐 — 화면 글 없음
    ex = _ints(lc.get("ex"), 3)
    s = f"단계 {'·'.join(_lvs(lc.get('lv'))) or '-'}"
    if len(ex) == 3:
        s += f" 펼침{ex[0]}·닫힘{ex[1]}·품음{ex[2]}"
    if c.get("list_expanded") or c.get("list_collapsed"):
        s += f" 펼쳐봄{_int(c.get('list_expanded'))}·못펼침{_int(c.get('list_collapsed'))}"
    out.append(s)
    out.append(f"읽기 후보{_int(c.get('read_cand'))}·일반{_int(c.get('read_gen'))}")
    if pc:
        out.append(f"보임 {re.sub(r'[^a-z]', '', str(pc.get('vis') or ''))[:10] or '-'}·초점{_int(pc.get('foc'), -1)}")
    if c.get("input_err"):
        out.append(f"입력오류 {_int(c.get('input_err'))}({re.sub(r'[^A-Za-z:]', '', str(run.sd.get('input_err') or ''))[:30]})")
    if c.get("aim_err"):
        out.append(f"겨눔오류 {_int(c.get('aim_err'))}({_scrub(run.sd.get('aim_err'), 50)})")
    if run.sd.get("census_err"):
        out.append(f"진단오류({_scrub(run.sd.get('census_err'), 40)})")
    line = "구조+: " + " · ".join(out)
    while len(line) > PLUS_MAX and tids:          # 길면 data-tid 부터 덜어 낸다(dom_census 에는 다 있다)
        tids.pop()
        out = [("tid " + ("·".join(tids) if tids else "…")) if x.startswith("tid ") else x for x in out]
        line = "구조+: " + " · ".join(out)
    return line[:PLUS_MAX]


def build_census(run, line, line2=""):
    """dom_census — 구조 두 줄 + 숫자 + 가린 꼴·골격(LMSTATUS counts·방 커서 파일에 같은 것). 글자 없음 · 4KB 안(넘으면 골격부터
    덜어 낸다)."""
    c, lc, pc = run.c, run.cen.get("list") or {}, run.cen.get("pane") or {}
    d = {"v": 2, "line": str(line)[:400], "line2": str(line2)[:400],
         "open": {k: _int(c.get(k)) for k in OPEN_KEYS},
         "click": {m: [_int(c.get("click_" + m)), _int(c.get("click_" + m + "_doc"))] for m in CLICK_MODES},
         "worked": str(run.sd.get("how_click") or ""), "how": str(run.sd.get("how_open") or ""),
         "pref": {"msg": _MSG[run.pref["msg"]][1] if 0 <= run.pref.get("msg", -1) < len(_MSG) else "",
                  "head": _HEAD[run.pref["head"]][1] if 0 <= run.pref.get("head", -1) < len(_HEAD) else ""},
         "read": {"cand": _int(c.get("read_cand")), "gen": _int(c.get("read_gen"))},
         "doc": str(run.diag.get("doc") or (_doc_shape(pc.get("doc")) if pc else ""))[:48],
         "leaf": str(run.diag.get("leaf") or "")[:80],
         # 내 메시지 진단(LM28 E) — 숫자만
         "mine": {k: _int(c.get(k)) for k in ("rows_read", "rows_sent", "mine_t", "mine_f", "mine_n", "au_inherit",
                                               "date_only", "prec_up", "mine_fixed")}}
    if lc:
        d["list"] = {"n": _int(c.get("rooms_listed")), "role": _hook(lc.get("role")), "tag": _hook(lc.get("tag")),
                     "tid": _hook(lc.get("tid")), "keyed": _int(lc.get("keyed")), "selT": _int(lc.get("selT")),
                     "selA": _int(lc.get("selA")), "exp": _int(lc.get("exp")), "rooms": _int(lc.get("rooms")),
                     "lbl": _int(lc.get("lbl")), "lby": _int(lc.get("lby")), "lv": _lvs(lc.get("lv")), "ex": _ints(lc.get("ex"), 3),
                     "expanded": _int(c.get("list_expanded")), "collapsed": _int(c.get("list_collapsed"))}
    if pc:
        sel = pc.get("sel") if isinstance(pc.get("sel"), dict) else {}

        def named(vals, codes, keep):
            # 후보 순번 → 약칭(맞은 것만): 목록·메시지는 개수 > 0, 머리는 있는 것(글자 수, 0 = 비었음), 스크롤 영역은 [높이, 보이는 높이, 위치]
            return {codes[i]: v for i, v in enumerate(_ints(vals, len(codes))) if keep(v)}
        d["pane"] = {"kind": str(run.cen.get("pane_kind") or ""),
                     "loc": re.sub(r"[^A-Za-z0-9.\-/<>_]", "", str(pc.get("loc") or ""))[:60],
                     "list": named(pc.get("list"), _LIST_CODE, lambda v: isinstance(v, int) and v > 0),
                     "msg": named(pc.get("msg"), [m[1] for m in _MSG], lambda v: isinstance(v, int) and v > 0),
                     "head": named(pc.get("head"), [h[1] for h in _HEAD], lambda v: isinstance(v, int) and v >= 0),
                     "vp": named(pc.get("vp"), [v[1] for v in _VP], lambda v: isinstance(v, list)),
                     "sel": {k: _int(sel.get(k)) for k in ("n", "ast", "asa", "ac", "ds", "cls")},
                     "conv": str(pc.get("conv") or "") if pc.get("conv") in ("url", "nav", "dom") else "",
                     "gen": _int(pc.get("gen"), -1), "times": _int(pc.get("times"), -1), "tall": _int(pc.get("tall"), -1),
                     "vis": re.sub(r"[^a-z]", "", str(pc.get("vis") or ""))[:10], "foc": _int(pc.get("foc"), -1),
                     "ifr": _ints(pc.get("ifr"), 3), "sh": _int(pc.get("sh"), -1), "tids2": _tids2(pc.get("tids2")),
                     "tids": [_scrub(x, 48) for x in (pc.get("tids") or []) if isinstance(x, str)][:24]}
        sk = pc.get("skel") if isinstance(pc.get("skel"), dict) else {}
        d["skel"] = {k: [_scrub(x) for x in (sk.get(k) or []) if isinstance(x, str)][:n]
                     for k, n in (("item", 14), ("head", 8), ("msg", 18), ("hdr", 6))}

    def size():
        return len(json.dumps(d, ensure_ascii=False).encode("utf-8"))
    while size() > CENSUS_MAX:
        sk = d.get("skel") or {}
        k = max(sk, key=lambda x: len(sk[x]), default=None)
        if k and sk[k]:
            sk[k].pop()
            continue
        if (d.get("pane") or {}).get("tids"):
            d["pane"]["tids"].pop()
            continue
        d.pop("skel", None)
        if size() > CENSUS_MAX:
            d.pop("pane", None)
        break
    return d


def emit_census(run, save_census=None):
    """'구조:'·'구조+:' 두 줄을 찍고(사람용 요약 줄 바로 앞 — run.py 가 last_run.json census·화면 마지막 12줄에 싣는다) dom_census 를
    counts 와 방 커서 파일에 남긴다."""
    s, s2 = census_line(run), census_plus(run)
    log(s)
    log(s2)
    cen = build_census(run, "[teams-web] " + s, "[teams-web] " + s2)
    run.c["dom_census"] = cen
    if save_census:
        try:
            save_census(cen)
        except Exception:  # noqa: BLE001 — 진단 저장 실패가 수집 결과를 바꾸지 않는다
            pass
    return cen


def _visit(br, run, w, room, it):
    """걷는 중 만난 방 하나 — 그대로면 건너뛰고(증분 확인), 처음부터 OPEN_ABORT 방 연속 전환 실패면 열지 않고, 아니면 그 화면
    스냅샷 항목(it)에서 열기·확인·되감기·저장·커서 갱신."""
    st = w.state.get(room["rid"]) or {}
    if _unchanged(room, st, run):
        room["verdict"], room["read_to"] = "incremental_ok", teams_parse._as_date(st.get("oldest"))
        run.bump("unchanged_skip")
        run.bump("incremental_ok")
        return
    if not run.open_ok and run.open_fail_streak >= OPEN_ABORT:
        # 처음부터 OPEN_ABORT 번 연속 전환 실패 — 같은 화면 구조라면 남은 방도 같다. 시간만 쓰지 않고 '구조' 줄로 원인을 받는다.
        if not run.aborted:
            run.aborted = True
            log(f"방 전환이 처음부터 {OPEN_ABORT}번 연속 확인되지 않아 남은 방은 열지 않습니다 — 다음 실행이 다시 시도합니다"
                f"('구조' 줄 참고)")
        room["skip"] = "aborted"
        run.bump("not_opened")
        run.bump("open_aborted")
        return
    run.bump("opened")
    events, rows, newest, pages = set(), [], None, 0
    try:
        p = open_room(br, run, room, it, w.cur)
        if p is not None:
            run.open_ok += 1
            run.open_fail_streak = 0
            w.cur = {"rid": room["rid"], "chat": p["chat"], "n": p["n"], "fids": set(p.get("fp") or ())}
            rows, events, newest, pages = read_room(br, run, room, st, w.cur["fids"])
        else:
            run.open_fail_streak += 1
            events.add("gone")
    except Exception as e:  # noqa: BLE001 — 화면 연결 오류(CDP 시간 초과 등)는 이 방만 '잘림'으로 — 읽음으로 적지 않는다
        run.bump("room_error")
        run.sd["room_error"] = type(e).__name__
        run.sd["room_error_msg"] = _scrub(str(e), 120)     # 'JS: TypeError: …' — 우리 스크립트 오류 문구(화면 글이 아니다)
        events, rows, newest = {"error"}, [], None
    v = teams_parse.room_verdict(events)
    room["verdict"] = v
    if v == "complete":
        room["read_to"] = (teams_parse.TOP_DATE if "top_confirmed" in events and "reached_d0" not in events
                           else run.d0)
    elif v == "incremental_ok":
        room["read_to"] = teams_parse._as_date(st.get("oldest"))
    run.bump(v)
    added = 0
    if rows and v != "roomgone":
        p0, f0 = w.store.prec_up, w.store.mine_fixed
        added, dup = w.store.add(rows)
        run.bump("dup_other", dup)
        run.bump("prec_up", w.store.prec_up - p0)        # 지난 판의 날짜만 행을 분 단위로(LM28 E)
        run.bump("mine_fixed", w.store.mine_fixed - f0)  # 지난 판이 남의 말로 적은 내 메시지를 내 발신으로(LM28 E)
        if added or w.store.dirty:
            w.store.flush()                      # 방마다 저장 — 예산에 끊기거나 강제 종료돼도 앞 방은 남는다
        run.bump("rows_new", added)
    w.state[room["rid"]] = next_state(st, v, events, newest, room, run)
    if w.save_state:
        w.save_state()
    log(f"  · {room['name'] or '(이름 없음)'} — {v} · 화면 {pages} → {len(rows)}건(새 {added})")


def collect(br, run, state, store, save_state=None):
    """목록 걷기 두 번(LM28-TW-2) → (방 목록, 목록 끝, 목록 선택자).
    1차: 목록을 끝까지 내리며 방을 모으고(닫힌 최상위 구역은 펼친다) 지난 실행에서 잘린 방(cut·roomgone)을 그 자리에서 연다.
    2차: 맨 위로 되돌려 남은 방을 그 자리에서 연다(방마다 열기·확인·되감기·저장). 마지막 활동이 기간 시작 전인 방은 열지 않는다.
    못 펼친 구역이 남으면 목록 끝이 아니다. 끝나고도 정하지 못한 방: 예산이면 not_opened, 아니면(목록이 바뀌어 2차에서 못 만남)
    not_reached — 둘 다 '읽음' 아님(다음 실행이 다시).
    state: 방 커서 dict(rid → 상태, 제자리에서 갱신) · save_state(): 방마다 커서를 파일에 남기는 함수(없으면 생략)."""
    w = _Walk(state, store, save_state)
    list_end = _walk(br, run, w, "first")
    if run.c.get("list_collapsed"):
        list_end = False                         # 펼치지 못한 구역 안의 방이 기간에 활동했을 수 있다
    rooms, how = w.rooms, w.how
    run.c["rooms_listed"] = len(rooms)
    run.c["list_end"] = bool(list_end)
    run.c["teams_present"] = bool(rooms)
    run.sd["how_list"] = how
    log(f"대화 목록 {len(rooms)}개 (선택자 {how or '못 찾음'}{' · 끝까지' if list_end else ' · 끝 미확인'})")
    if not rooms:
        _capture(br, run, "page")                # 목록을 못 찾은 화면 — 무엇이 떠 있는지 구조만 남긴다(R-WEBSEL 원인 확정)
    elif any(_due(w, r, "rest") for r in rooms) and not run.out_of_time():
        _walk(br, run, w, "rest")
    for r in rooms:
        if r.get("verdict") is None and not r.get("skip"):
            run.bump("not_opened" if run.timed_out else "not_reached")
    return rooms, list_end, how


def emit_status(rc, reasons=(), counts=None, ranges=None, src="teams_web"):
    """수집기 마지막 줄(LM28 P3) — 'LMSTATUS ' + JSON 한 줄. reason 은 사유 코드를 쉼표로(첫 코드가 주 사유)."""
    rs = ",".join(dict.fromkeys(r for r in reasons if r))
    print("LMSTATUS " + json.dumps({"v": 1, "src": src, "rc": int(rc), "reason": rs, "counts": counts or {},
                                    "ranges": ranges or []}, ensure_ascii=False))
    sys.stdout.flush()


def _web(br, run, state, store, save_state):
    """전용 Edge(잠금 안)에서 읽기 → (None | (rc, 사유), 결과). 이 수집기가 연 탭만 닫는다(로그인 대기면 둔다)."""
    try:
        started = br.start()
    except Exception as e:                  # 드라이버 부재·포트 충돌 — 사슬의 다음 경로(창 읽기)로 넘긴다
        log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
        return (3, "R-DRIVER"), None
    if not started:
        log("전용 Edge(디버그 포트)를 띄우지 못했습니다 — Edge 설치·config.copilotAuto.port 확인"
            + (f" ({br.reason})" if br.reason else ""))
        return (3, br.reason or "R-EDGELAUNCH"), None
    keep = False
    try:
        st = br.goto(TEAMS_URL)
        if st in ("login", "personal"):
            keep = True
            if st == "personal":
                log("전용 Edge 가 개인용 Teams(개인 Microsoft 계정) 화면입니다 — 업무 채팅이 아니므로 읽지 않습니다. 회사 계정으로 로그인하세요.")
            else:
                log("로그인 필요 — 지금 열린 전용 Edge 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인하세요 (Copilot 과 같은 창, 1회).")
            log("           로그인 뒤 [분석 실행]을 다시 누르면 이어서 읽습니다.")
            return (2, br.reason or ("R-PERSONAL" if st == "personal" else "R-LOGIN")), None
        if st != "ok":
            _capture(br, run, "page")            # 채팅 화면이 끝내 안 보임 — 무엇이 떠 있는지 구조만(글자 없이)
            log("팀즈 웹 화면이 뜨지 않았습니다(네트워크·차단?) — 전용 Edge 창에서 teams.microsoft.com 이 열리는지 확인하세요.")
            return (3, "R-TIMEOUT"), None
        try:
            return None, collect(br, run, state, store, save_state)
        except Exception as e:  # noqa: BLE001 — 목록 단계의 화면 연결 오류 — 방마다 이미 저장한 것은 남는다
            log(f"팀즈 웹 읽기 중 오류({type(e).__name__}: {str(e)[:80]}) — 지금까지 읽은 방은 저장했습니다")
            return (3, "R-WEBERROR"), None
    finally:
        br.close(keep_tab=keep)


def main():
    t0 = _mono()
    d0s = arg("--from") or (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    d1s = arg("--to") or datetime.now().strftime("%Y-%m-%d")
    d0, d1 = date.fromisoformat(d0s), date.fromisoformat(d1s)
    today = date.today()
    force = "--force" in sys.argv
    cfg = _load_cfg()
    try:
        max_chats = int(arg("--max-chats") or cfg.get("teamsWebMaxChats", MAX_CHATS))
        if max_chats < 0:
            max_chats = MAX_CHATS
    except (TypeError, ValueError):
        max_chats = MAX_CHATS
    try:
        max_scroll = int(cfg.get("teamsWebMaxScroll") or MAX_SCROLL)
        if max_scroll <= 0:
            max_scroll = MAX_SCROLL
    except (TypeError, ValueError):
        max_scroll = MAX_SCROLL
    try:
        # run.py 가 준 상한(1200초)보다 넉넉히 짧게 — 저장·정리 시간을 남긴다
        budget = float(arg("--budget") or arg("--budget-sec") or cfg.get("teamsWebBudgetSec") or 900)
    except ValueError:
        budget = 900.0
    try:                                # 키 정제 문맥 — G1(scrub_csv)과 같은 사전(고객사·협력사·본인)이어야 G1 뒤에도 키가 같다
        ctx = teams_parse.privacy.make_ctx(cfg, os.path.dirname(OUT_DIR))
    except Exception:  # noqa: BLE001 — 문맥을 못 만들면 기본 규칙으로(키가 조금 덜 맞을 뿐)
        ctx = None
    run = Run(d0, d1, today, deadline=t0 + budget, max_chats=max_chats, max_scroll=max_scroll, selfs=self_names(cfg),
              ctx=ctx)
    ver = state_ver(cfg)
    sp = os.path.join(OUT_DIR, STATE_NAME)
    state, reset = state_load(sp, ver)
    if reset:
        run.c["cursor_reset"] = 1
        log("방 커서의 판·cursorEpoch 가 달라 처음부터 읽습니다")

    if os.environ.get("LM_NO_BROWSER"):
        log("LM_NO_BROWSER 설정 — 브라우저를 띄우지 않습니다(시험용)")
        emit_status(3, ["R-NOBROWSER"], dict(run.c))
        return 3
    try:
        br = Browser()
    except Exception as e:              # 드라이버 모듈 부재 등 — 사슬의 다음 경로로 넘긴다
        log(f"드라이버를 쓸 수 없습니다({type(e).__name__}: {str(e)[:80]}) — 다음 대체 경로로")
        emit_status(3, ["R-DRIVER"], dict(run.c))
        return 3
    store = Store(os.path.join(OUT_DIR, "teams_web.csv"), force=force, ctx=run.ctx)

    def save_state(cen=None):
        # 방마다 커서와 함께 그때까지의 구조 진단도 남긴다(강제 종료돼도 진단 묶음이 원인을 싣는다)
        state_save(sp, ver, state, cen if cen is not None else build_census(run, "[teams-web] " + census_line(run),
                                                                             "[teams-web] " + census_plus(run)))
    try:
        with br.ca.edge_lock(br.cfg):   # 같은 전용 Edge 를 쓰는 작업(Copilot·Outlook 웹·진단)과 직렬(F-16)
            fail, res = _web(br, run, state, store, save_state)
    except br.ca.EdgeBusy as e:
        log(f"{e} — 다른 작업이 끝난 뒤 다시 실행하세요")
        emit_status(3, ["R-EDGEBUSY"], dict(run.c))
        return 3
    return finish(run, fail, res, store, save_census=save_state)


def finish(run, fail, res, store, save_census=None):
    """판정 → 로그·LMSTATUS. 방마다 이미 저장했으므로 여기서는 행을 쓰지 않는다. 화면을 본 실행이면 사람용 요약 줄 바로 앞에
    '구조:' 줄을 찍고 dom_census 를 counts·방 커서 파일(save_census)에 남긴다."""
    c = run.c
    c["selector_diag"] = dict(run.sd)
    ranges, reasons = [], []
    if fail:
        rc, why = fail
        reasons.append(why)
        if run.cen:                              # 화면은 떴는데 채팅 화면이 아니었다(R-TIMEOUT 등) — 무엇이 떠 있었는지
            emit_census(run, save_census)
        emit_status(rc, reasons, dict(c), ranges)
        return rc
    rooms, list_end, how = res
    log(f"진단: 목록 {how or '못 찾음'} · 메시지 {run.sd.get('how_msg') or '못 찾음'} · 스크롤 {run.sd.get('how_scroll') or '-'}"
        f" · 시각 못 짚음 {c['no_time']} · 작성자 미상 {c['no_author']} · 본문 없음 {c['no_body']}")
    if not rooms:
        emit_census(run, save_census)
        log("채팅 목록을 찾지 못했습니다 — 전용 Edge 창의 팀즈에서 [채팅] 탭이 열려 있는지 확인하세요.")
        reasons.append("R-WEBSEL")
        emit_status(3, reasons, dict(c), ranges)
        return 3
    ranges = teams_parse.day_ranges(rooms, list_end, run.d0, run.d1, cap=run.today)
    opened = c["opened"]
    left = c["not_opened"] - _int(c.get("open_aborted"))
    if left > 0:
        log(f"시간 예산에 닿아 남은 대화방 {left}개는 다음 실행이 먼저 읽습니다 — 지금까지 읽은 것은 방마다 저장했습니다.")
    if _int(c.get("not_reached")):
        log(f"목록이 바뀌어 다시 만나지 못한 대화방 {_int(c.get('not_reached'))}개는 다음 실행이 읽습니다.")
    if run.timed_out:
        reasons.append("R-TIMEOUT")
    emit_census(run, save_census)
    log(f"방: 읽음 {c['complete']} · 증분 {c['incremental_ok']}(그대로 {c['unchanged_skip']}) · 예산·상한에 잘림 {c['cut_budget']}"
        f" · 스크롤 영역 없음 {c['cut_no_scroller']} · 전환 실패 {c['roomgone']} · 기간 전 {c['skipped_old']}")
    try:
        shown = os.path.relpath(store.path, ROOT)
    except ValueError:              # 다른 드라이브(시험용으로 출력을 돌린 경우) - 표시일 뿐이니 죽지 않는다
        shown = store.path
    log(f"{shown} — 신규 {c['rows_new']}건 (다른 경로와 겹쳐 제외 {c['dup_other']}건) / 누적 {store.count()}건"
        + (f" · 지난 판 바로잡음(시각 {_int(c.get('prec_up'))}·내 발신 {_int(c.get('mine_fixed'))})"
           if c.get("prec_up") or c.get("mine_fixed") else ""))
    if opened and c["cut_no_scroller"] and c["cut_no_scroller"] + c["roomgone"] >= opened:
        reasons.insert(0, "R-WEBSEL")            # 연 방이 모두 스크롤 영역을 못 찾음 — 화면 구조가 바뀌었다
        rc = 3
    elif opened and c["roomgone"] >= opened:
        reasons.insert(0, "R-ROOMGONE")          # 어느 방도 전환을 확인하지 못함
        rc = 3
    elif c["rows_new"]:
        rc = 0
    elif not opened and not c["incremental_ok"]:
        rc = 1                                   # 기간에 활동한 방이 없다
    else:
        rc = 4
    emit_status(rc, reasons, dict(c), ranges)
    return rc


if __name__ == "__main__":
    sys.exit(main())
