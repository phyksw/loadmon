# -*- coding: utf-8 -*-
"""
copilot_auto.py — 사람 개입 없는 M365 Copilot 연동 (Edge DevTools Protocol).

원리: 전용 Edge 프로필(최초 1회만 로그인)을 디버그 포트로 띄우고,
      채팅 입력창에 프롬프트를 넣고 전송 → 응답 텍스트가 안정화되면 회수.
      외부 라이브러리 없이 표준 라이브러리만 사용 (사내 PC pip 제약 대응).

사용:
  python tools\\copilot_auto.py --send prompt.txt --out reply.json   # 프롬프트 전송→응답 회수
  python tools\\copilot_auto.py --send prompt.txt --no-split         # 분할 없이 옛 방식(한 번에 주입)
  python tools\\copilot_auto.py --probe                              # 상태만 확인(로그인 여부 등)
  python tools\\copilot_auto.py --diagnose                           # 입력창/버튼 후보 덤프

종료 출력(stdout, JSON 한 건): {"ok":bool,"phase":str,"reply":str,"error":str,"hint":str,"parts":int,
                              "cut":bool}
  phase: ready | login_required | sent | replied | edge_not_found | launch_failed |
         input_not_found | no_reply | copilot_error | throttled | error | stub
  throttled(LM28 진단 A): 답이 Copilot 사용량 제한 문구다(is_throttle_reply) — 재시도 사다리를 타지 않고 바로 돌려준다
       (즉시 다시 보내면 제한이 길어진다). 쉬었다 다시 보내기는 호출자(judge.copilot_send)의 몫이다. <프로필>.throttle.json 에
       관찰을 남겨 다음 단계 프로세스가 안다(throttle_state). --reload 는 보내기 전에 채팅 페이지를 새로 고치고, --model 은
       이번 왕복만 모델을 바꾼다.
       LM28 — 답을 기다리는 동안에도 본다: 보낸 뒤의 답 머리(짧은 산문·JSON 없음)나 보낸 뒤 새로 뜬 알림(role=alert·aria-live·
       토스트 — js_notices)에 제한 문구가 있고 그 글이 그대로면(생성 중이 아니면 ~5초 · '중지' 버튼이 사라졌으면 한 폴) replyTimeoutSec·
       새 채팅 사다리를 기다리지 않고 바로 throttled 로 돌려준다(그동안의 재전송 하나하나가 제한을 늘린다). 같은 실행(LM_RUN_ID)이
       사용량 제한으로 멈췄으면(run_stopped) 보내지 않고 바로 hard 'throttled'(run_stop_result). 보내기 사이에는
       copilotAuto.minGapSec(기본 15초 · 0 = 끔) 간격을 둔다 — 앞 전송 시각은 <프로필>.pace.json(프로세스를 넘어 · pace_wait).
       한 실행(LM_RUN_ID)에서 Copilot 때문에 쉬는 시간은 모든 단계를 합쳐 copilotAuto.runWaitMaxSec(기본 300초 · 0 = 쉬지 않음)
       안이다 — 쉰 초 합계는 <프로필>.wait.json(run_wait_left·add_run_wait — 쉬는 쪽은 judge·agentic·flow·run.py).
  cut: 답 꼬리에 '생성 중단' 문구("OK, I've stopped generating the response.")가 있다 — 재시도
       사다리(새 채팅)로도 반복되면 잘린 앞부분을 ok+cut 으로 돌려주고, 호출자(judge/refine)가
       잘린 JSON 을 마지막 완전한 항목까지 복구한 뒤 나머지만 다시 묻는다(적응 분할).
  slow(LM28 — 느린 긴 답): replyTimeoutSec 는 기본 마감이다. 그때 답이 아직 자라고 있으면 왕복 예산(roundtripMaxSec) 끝까지 더
       기다리고(약 1분마다 stderr 진행 줄), 예산 끝에도 쓰는 중이면 입력창의 '중지' 단추(정확한 이름 하나)만 눌러 끊은 뒤 받은 데까지를
       ok+cut+slow(+stopped) 로 돌려준다. 사다리·judge 의 쉬기 사다리·나눔 전체 재전송은 slow 를 다시 보내지 않는다 — 같은 프롬프트를
       새 채팅에 또 보내면 Copilot 이 앞 채팅들의 답을 뒤에서 마저 써 대화 목록에 같은 답이 쌓였다(현장 제보).
  전송 전에는 앞 답의 생성이 끝났는지(중지 버튼) 확인하고, 전송 클릭이 '중지'에 먹혀 프롬프트가
  입력창에 남으면 한 번 더 보낸다 — 생성 중 전송이 앞 답을 끊고 다음 왕복까지 시간 초과로 끌던
  큰 사람(청크 20개 이상)의 연속 실패 경로.

긴 프롬프트(LM22, 보완툴 AutoSend 이식):
  · 입력 한도(약 9,000자)를 넘는 프롬프트는 줄 경계에서 8,000자 조각으로 나눠 **같은 채팅**에
    차례로 보내고, 마지막 조각이 "이제 전체를 보고 JSON 을 출력하라"고 시킨다.
  · 모든 답 끝에 [[전송끝]] 서약을 요구한다 — 서약이 보이면 안정 폴링을 기다리지 않고 즉시
    회수하고(조기 완료), 안 보이면 아무것도 보내지 않은 채 같은 탭을 다시 읽으며 기다린다
    (생성 중에 다음 조각을 보내면 전송 버튼이 '중지'가 되어 답을 끊는다 — 실측).
  · 나눔 조각에는 '새 채팅 재시도 사다리'를 쓰지 않는다(앞 조각 문맥이 지워진다) — 실패하면
    새 채팅에서 전체를 처음부터 1회 다시 보낸다.

테스트 전용 스텁(LM_COPILOT_STUB=<dir>):
  · --send 가 Edge 를 띄우지 않고 <dir> 의 JSON 파일을 응답으로 돌려준다(phase "stub").
    회귀 시험(run.py 경로는 자식 프로세스라 in-process 패치가 닿지 않음)만을 위한 분기이며,
    산출물에는 phase 로 '스텁 판정'임이 드러난다. 배포 환경에서는 이 변수를 두지 말 것.

LM28 — 우리 Edge 만 다루고, 개인 계정·정책·잠금을 먼저 본다:
  · ensure_edge 가 띄우면 data\\lm30v1_edge\\owner.json{pid,port,t,root,browser} 를 쓴다. close_own_edge 는 그 표식이 있고
    브라우저 ID 가 같을 때만 CDP Browser.close 를 보낸다(taskkill 없음 · keepEdgeOpen·로그인 대기 중이면 두기).
  · Edge 는 CREATE_BREAKAWAY_FROM_JOB 로 띄운다 — 단계의 Job 정리에 휩쓸리지 않아 한 실행에 한 번만 뜬다.
    상위 Job 이 이탈을 막으면(ERROR_ACCESS_DENIED) 플래그 없이 1회.
  · 같은 프로필은 직렬로 — edge_lock(msvcrt · <프로필>.busy.lock · 600초를 넘으면 R-EDGEBUSY).
  · Edge 정책은 읽기만(HKLM 이 HKCU 보다 우선): RemoteDebuggingAllowed=0·UserDataDir 강제면 띄우지 않고 R-EDGEPOL,
    종료 때 쿠키를 지우는 정책(ClearBrowsingDataOnExit=1·DefaultCookiesSetting=4)이면 R-EDGEKEEP 안내 1회.
  · 탭·계정은 URL 호스트의 정확·마디 접미 일치로만 판정한다(page_kind — 부분 문자열 금지). 업무 Copilot 호스트가 아니면
    보내지 않는다(개인 계정 화면은 R-PERSONAL · 미상은 로그인 대기). Outlook·Teams 탭은 닫거나 옮기지 않는다.
  · 로그인 화면은 AADSTS 번호만 읽어 사유를 나눈다(R-LOGIN-DEVICE·R-LOGIN-WAIT·R-CA). 안내는 프로세스당 1회(stderr).
  · --remote-allow-origins 는 http://127.0.0.1:<port> 만(예전 '*' 금지). WS 가 403 이면 그 Origin 으로 한 번 더 붙는다.
  · 죽은 프로필(오류 화면)이 서로 다른 왕복에서 2회 연속이면 우리 Edge 를 닫고 <프로필>.bad-<시각> 으로 바꾼 뒤 새로 띄운다.
  · send_inproc(prompt, fresh, deadline) — judge 등이 같은 프로세스에서 부르는 --send(왕복마다 파이썬을 띄우지 않는다).
    보내기 직전 G3 최종 검사(privacy.gate_prompt)에 걸리면 {status:'blocked'} 를 돌려주고 보내지 않는다. CLI --send 도 같은
    길(_send)을 탄다. gate_rows 는 프롬프트에 넣을 행을 privacy.gate_items 로 거른다(호출자 judge·refine·flow·agentic).
  · python tools\\copilot_auto.py --close  → 우리가 띄운 Edge 만 닫는다(작업 끝 정리 — 호출 시점은 run.py).

LM28 — Copilot 채팅 정리(copilotAuto.deleteChats, 기본 켬): LM28 이 연 대화만, 다 쓴 때에 대화 목록에서 지운다.
  · 새 채팅을 여는 길은 _fresh_chat 하나 — 다 쓴 우리 채팅을 먼저 지우고(retire_chat) 새 채팅을 연 뒤 '우리 것'으로 적는다.
    실행 끝에는 close_own_edge 가 Edge 를 닫기 전에 마지막 채팅을 지운다(retire_current). --send --retire 는 왕복 뒤 바로 지운다
    ([AI 연결 진단]). 소유는 <프로필>.chats.json(프롬프트 원문 없음 — 앵커 sha1·길이·대화 id·누계)이 프로세스를 넘어 기억한다.
  · 기록은 숫자·사유 코드만 — copilot_trace 의 stage 'chat' 줄 · chat_line()('[copilot] 채팅 정리: …' — 단계 로그) ·
    chat_totals()(run.py 의 last_run 단계 'Copilot 채팅 정리').
  · LM28: 아직 답을 쓰는 중인 채팅은 지우지 않는다(남김 'gen'). 화면 사유(목록에서 못 찾음·메뉴 없음 …)로 남기면 대화 목록 구조를
    숫자로만 세어(js_chat_census) 둘째 줄 '[copilot] 채팅 정리 구조: …'로 남긴다. 삭제 판정(소유 확인)은 그대로다.
  · LM28(2026-10-17): 지우기 전에 대화 목록 항목의 제목이 우리 첫 질문의 앞부분과 같은지 해시로 맞춰 본다(다르면 'notitle' — 그 항목은
    누르지 않는다). 목록이 접혀 있으면(좁은 창) 탐색 창 단추·넓은 화면 흉내(CDP Emulation — 정리가 끝나면 늘 되돌림)로 길만 연다. 긴
    질문을 접어 첫 줄만 보이는 화면은 머리 앵커(첫 줄 앞 60자)로 소유를 확인한다. 화면 규칙이 바뀌어 CHAT_REV 2(판 1 의 멈춤은 풀린다).
  · LM28(2026-10-17) 사람이 쓰던 채팅은 건드리지 않는다(사용자 요구 — 지우지도, 질문을 넣지도 않는다): 이어 보내기 직전 화면이 이
    프로세스의 우리 채팅임을 확인하지 못하면(_continue_why — 앵커·대화 id·소유) 새 채팅을 열고, 새 채팅으로 옮긴 것을 확인하지 못하면
    (_open_fresh — 한 번 더 새로 고쳐 열어 봄) 보내지 않는다(phase 'no_new_chat'). 나눠 보내는 둘째 조각부터도 같은 확인(phase 'moved').
  · LM28: 다음 단계(정제·Agentic·워크플로우)의 첫 왕복은 fresh=RESUME — 앞 단계의 우리 채팅이 온전하게 끝났고(last_ok) 20분 안이며
    화면이 그 채팅이면 새 채팅 없이 이어 쓴다(아니면 예전처럼 새 채팅).
  · LM28(2026-10-17): 조각을 많이 보내는 호출자(Copilot 메일·일정·팀즈 수집기)는 ChatKeep 으로 한 채팅을 이어 쓴다 — 첫 조각(앞 단계의
    우리 채팅이면 RESUME)·나쁜 조각 뒤·chatTurns 마다만 새 채팅. 이어 보내기(fresh 거짓) 직전 탭 주소의 대화 id 가 이 프로세스의 우리
    채팅과 다르면(사람이 전용 Edge 에서 다른 대화를 누름) 그 대화에 보내지 않고 새 채팅을 연다(_moved_away — 주소에 id 가 없으면 예전 그대로).
"""
import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000   # 상위 Job(단계 정리)에서 Edge 를 떼어 띄운다 — 단계가 끝나도 Edge 는 산다
ERROR_ACCESS_DENIED = 5                  # 상위 Job 이 이탈(BREAKAWAY_OK)을 허락하지 않을 때 CreateProcess 가 내는 오류
_sleep = time.sleep                      # 시험이 대기를 0 으로 바꿀 수 있게(Edge 수명주기 함수만)
if os.path.join(ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "core"))
import lmname  # noqa: E402  — LM30v1 이름 단일원(CDP 포트·전용 Edge 프로필)

# ── 설정 (config.json 의 copilotAuto 로 덮어쓰기 가능) ──
# 포트·프로필은 LM24·LM28·LM29·LM30 과 다르게 둔다(lmname.CDP_PORT · data\lm30v1_edge) — 같은 PC 의 LM24·LM28·LM29·LM30 Edge 를 재사용·조종하지 않게.
DEFAULTS = {
    "url": "https://m365.cloud.microsoft/chat",
    "port": lmname.CDP_PORT,
    "profileDir": lmname.edge_profile(ROOT),
    # 입력창 후보 — 위에서부터 시도, 화면에 보이는 첫 요소 사용
    # 실측(2026-08): BizChat 입력창은 SPAN[contenteditable][role=textbox] aria-label="Copilot에 메시지 보내기"
    "inputSelectors": [
        "[contenteditable='true'][role='textbox']",
        ".fai-EditorInput__input",
        "span[contenteditable='true']",
        "div[contenteditable='true']",
        "[contenteditable='plaintext-only']",
        "textarea[placeholder]",
        "textarea",
    ],
    # 전송 버튼 후보 — 없으면 Enter 키로 대체
    "sendSelectors": [
        "button[aria-label*='보내기']", "button[aria-label*='전송']",
        "button[aria-label*='Send']", "button[data-testid*='send']",
        "button[type='submit']",
    ],
    # 응답을 읽을 영역 — 없으면 body 전체
    "chatRootSelectors": ["main", "[role='main']", "body"],
    "model": "GPT-5.6",          # Copilot 채팅의 모델 선택기에서 고를 모델 (부분일치)
    # 서약([[전송끝]]) 조기 완료가 있으므로 안정 폴링을 넉넉히 잡아도 평소 왕복은 느려지지 않는다
    # — 긴 답을 쓰다 잠시 멈춘 것을 완료로 오인해 조기 회수하던 결함(실측) 방지.
    "replyTimeoutSec": 300,
    "stablePolls": 6,          # innerText가 N회 연속 동일하면 응답 완료로 판정
    # 입력창이 뜰 때까지 기다리는 한도(초). 한 번 못 찾은 것을 곧 영구 실패로 부르면
    # 일시적인 SPA 렌더 지연 하나가 AI 판정 전체를 건너뛰게 만든다(실측 — 상위과제 분류 빈칸).
    "readyWaitSec": 60,
    # 첫 글자가 오기까지 기다려 주는 한도(초). '깊이 생각하기' 모델은 첫 토큰 전에 수십 초를 생각한다 —
    # 그 동안 화면에는 프롬프트 에코 꼬리만 있어 예전 규칙(stablePolls×pollSec = 24초)이 '답이 멈췄다' 로
    # 오인하고 빈 답을 성공으로 돌려줬다(감사 실측 · LM24 공통). 빈 답은 judge 가 반으로 나눠 다시 묻는다 → 왕복 3배.
    "firstTokenSec": 180,
    "pollSec": 2,
    # 왕복 1회(사다리 3단 + 고정 대기)의 총 예산(초). 0 이면 끔(예전 동작 = 최악 24~31분).
    # 이 안에 못 끝내면 있는 대로 돌려주고 호출자(judge/refine/flow)가 묶음을 나눠 다시 묻는다 —
    # 한 묶음이 30분을 붙잡고 있으면 그 단계의 시간 예산이 통째로 녹는다(감사 실측).
    "roundtripMaxSec": 900,
    # 이 전용 프로필의 디스크 캐시 상한(MB). 상한이 없어 GB 급으로 자랐고, 그것이 PC 간 폴더 이동이
    # 10~30분 걸리던 원인이었다(파일 수 94%·용량 96%). 캐시는 새 PC 에서 어차피 다시 받는다.
    # 0 이면 상한 없음(예전 동작). config.copilotAuto.diskCacheMB 로 조절.
    "diskCacheMB": 200,
    # LM28 — 키 설명은 config.default.json 의 _copilotAuto_옵션_설명.
    "inProcess": True,            # judge 등이 이 모듈을 임포트해 같은 프로세스에서 왕복(send_inproc). false = 자식 프로세스
    "requireWorkAccount": True,   # 업무(회사) Copilot 화면에서만 보낸다 — 개인 계정이면 R-PERSONAL
    "keepEdgeOpen": False,        # true 면 close_own_edge 가 닫지 않는다(종료 때 쿠키를 지우는 정책 PC)
    "deleteChats": True,          # LM28 이 연 Copilot 대화를 다 쓰면 대화 목록에서 지운다(false·"false"·0·"off" = 끔)
    # 프롬프트를 보내는 사이의 최소 간격(초) — 프로세스를 넘어(<프로필>.pace.json). 판정 묶음·재시도·다음 단계가 잇달아 보내 요청이
    # 몰리면 Copilot 이 「요청이 너무 많다」고 막는다(현장 제보). 0 = 끔. 평소 왕복은 답을 기다리는 동안 이미 지나 있어 느려지지 않는다.
    "minGapSec": 15,
    # 한 번 분석(run.py 한 실행 — LM_RUN_ID)에서 Copilot 때문에 쉬는 시간의 합계 상한(초) — 판정·정제·월별 코멘트·Agentic·워크플로우를
    # 모두 합친다(<프로필>.wait.json). 다 쓰면 그 단계의 남은 묶음은 보내지 않고 여기까지의 결과를 지킨다. 0 = 쉬지 않음(막히면 바로 멈춤).
    "runWaitMaxSec": 300,
}
# 빈 값은 기본값을 쓰는 load_cfg 규칙의 예외 — 이 키들은 0 도 '끔'으로 받는다(설정가이드가 0·false 를 같은 뜻으로 안내한다).
# chatTurns 0 = 묶음(조각)마다 새 채팅(chat_turns — LM28 2026-10-17)
KEEP_FALSY = ("deleteChats", "minGapSec", "runWaitMaxSec", "chatTurns")

# ── 긴 프롬프트 분할 (보완툴 AutoSend 이식) ──
# flow.py 실측 주석: "과제 12~15개면 20,000~40,000자가 되어 입력 주입이 한도를 넘긴다".
# 드라이버는 주입 후 앞 15자만 확인하므로 입력창 한도에서 뒤가 잘려도 모른 채 전송된다 →
# 응답 회수 앵커(프롬프트 꼬리)도 못 찾아 실패가 연쇄된다. 그래서 한도 안 조각으로 나눈다.
SAFE_PROMPT = 9000                  # 이 길이까지는 한 번에 보낸다 (flow.py 의 실측 안전 예산)
PART_PROMPT = 8000                  # 조각 크기 (머리말 여유 포함)
_RT_DEADLINE = None           # 현재 왕복의 벽시계 마감(epoch) — run_roundtrip/_split 이 세팅


def _dl_left(default=10 ** 6):
    """왕복 마감까지 남은 초 — v3: 폴링 대기 26곳이 예산 밖이어서 '예산 900초'의 실제 값이
    경로마다 달랐다(구조 감사). 고정 대기가 이 값을 상한으로 삼으면 예산이 전 구간을 덮는다."""
    if _RT_DEADLINE is None:
        return default
    return max(0.0, _RT_DEADLINE - time.time())


SENTINEL = "[[전송끝]]"             # 답이 '다 쓰였다'는 서약 — 이것이 보이기 전에는
                                    # 어떤 클릭·다음 전송도 하지 않는다 (생성 중단 방지)
PLEDGE_TAIL = f"\n\n(답을 다 쓴 뒤 맨 마지막 줄에 {SENTINEL} 이라고 쓰세요.)"
# 호출자(judge/refine/agentic/flow)가 '한 번에 보내려면' 지켜야 할 프롬프트 예산 — SAFE_PROMPT 에서
# 서약 지시(PLEDGE_TAIL)와 여유를 뺀 값. judge.PROMPT_BUDGET 이 같은 값을 복제한다(드라이버 임포트 회피).
PROMPT_BUDGET = SAFE_PROMPT - len(PLEDGE_TAIL) - 550


def make_parts(prompt, reserve=0):
    """긴 프롬프트를 줄 경계에서 조각내고, 조각마다 진행 안내 머리말을 붙인다.
    마지막 조각이 '이제 전체를 분석해 JSON 을 출력하라'고 시킨다.
    reserve: 한 조각일 때 뒤에 덧붙일 서약 지시 길이 — 그만큼 여유를 두고 분할을 결정한다."""
    prompt = str(prompt or "")
    if len(prompt) + int(reserve or 0) <= SAFE_PROMPT:
        return [prompt]
    bodies, cur, size = [], [], 0
    for ln in prompt.splitlines(keepends=True):
        while len(ln) > PART_PROMPT:              # 한 줄이 조각보다 긴 극단 방어
            if cur:
                bodies.append("".join(cur))
                cur, size = [], 0
            bodies.append(ln[:PART_PROMPT])
            ln = ln[PART_PROMPT:]
        if cur and size + len(ln) > PART_PROMPT:
            bodies.append("".join(cur))
            cur, size = [], 0
        cur.append(ln)
        size += len(ln)
    if cur:
        bodies.append("".join(cur))
    total = len(bodies)
    parts = []
    for i, body in enumerate(bodies, 1):
        if i < total:
            pre = (f"[긴 자료 나눔 {i}/{total}] 지시와 자료가 길어 {total}번에 나눠 보냅니다. "
                   f"전체를 받을 때까지 분석·JSON 출력을 시작하지 말고, 이 조각을 기억한 뒤 "
                   f"'받았습니다 {i}/{total} {SENTINEL}' 라고만 답하세요.\n\n")
        else:
            pre = (f"[긴 자료 나눔 {total}/{total} — 마지막] 아래가 자료의 끝입니다. "
                   f"이제 지금까지 받은 조각 전체를 하나의 자료로 보고, 첫 조각의 지시와 "
                   f"출력 형식(JSON) 그대로 분석해 JSON 하나만 출력한 뒤, "
                   f"그 다음 줄에 {SENTINEL} 이라고 쓰세요.\n\n")
        parts.append(pre + body)
    return parts


def echo_sentinels(prompt, anchor, how):
    """응답 슬라이스에 섞여 들어오는 **프롬프트 에코 몫**의 서약 개수.
    pick_reply 가 'anchor' 로 잘랐으면 앵커 뒤 꼬리만 에코로 남고, 'offset' 이면 에코 전체가
    남는다. 프롬프트 자체가 서약 지시("…[[전송끝]] 이라고 쓰세요")를 담고 있으므로 이 몫을
    빼지 않으면 답이 오기도 전에 '서약이 보인다'고 오판한다."""
    prompt = str(prompt or "")
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos >= 0:
            return prompt[pos + len(anchor):].count(SENTINEL)
    return prompt.count(SENTINEL)


def has_pledge(reply, prompt, anchor, how):
    """이번 답 안에 서약이 있는가 — 에코 몫을 넘는 서약이 있어야 참. 'fulltext' 는 이전
    대화의 옛 서약을 오인할 수 있어 항상 거짓(안정 폴링으로 완료 판정)."""
    if how == "fulltext":
        return False
    return str(reply or "").count(SENTINEL) > echo_sentinels(prompt, anchor, how)


def strip_echo(reply, prompt, anchor, how):
    """응답 슬라이스 앞에 붙은 **프롬프트 에코**를 걷어낸다 — 앵커는 '마지막 8줄 중 가장 긴
    줄'이라 그 뒤 최대 7줄(수백 자)이 답 앞에 따라온다. 그대로 두면 짧은 오류 문구가
    500자 상한을 넘겨 is_error_reply 가 놓치고(재시도 불발), 나눔 조각의 '받았습니다' 확인도
    흐려진다. 공백을 무시한 접두 일치일 때만 자르고, 조금이라도 다르면(렌더 변형·'더 보기'
    접힘) 자르지 않는다 — 잘못 자르면 여는 '{' 가 날아간다."""
    reply = str(reply or "")
    prompt = str(prompt or "")
    if how == "fulltext" or not prompt:
        return reply
    echo = prompt
    if how == "anchor" and anchor:
        pos = prompt.rfind(anchor)
        if pos < 0:
            return reply
        echo = prompt[pos + len(anchor):]
    want = re.sub(r"\s+", "", echo)
    if not want:
        return reply
    i, j, n = 0, 0, len(reply)
    while i < n and j < len(want):
        c = reply[i]
        if c.isspace():
            i += 1
            continue
        if c != want[j]:
            return reply
        i += 1
        j += 1
    return reply[i:] if j == len(want) else reply


def load_cfg(cfg_path=None):
    cfg = dict(DEFAULTS)
    try:
        with open(cfg_path or os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            user = json.load(f).get("copilotAuto") or {}
        # 빈 값은 기본값을 쓰되, 명시한 false 는 받는다(inProcess·requireWorkAccount 를 끌 수 있게). KEEP_FALSY 는 0 도 받는다
        cfg.update({k: v for k, v in user.items()
                    if v or v is False or (k in KEEP_FALSY and v is not None and v != "")})
    except Exception:
        pass
    # LM24·LM28·LM29·LM30 의 config.json 을 그대로 옮겨 온 경우(옛 포트·옛 프로필) — lmname 값이 우선한다.
    # 경고는 stderr 로 1줄(stdout 은 결과 JSON 한 건 계약) — 인프로세스 왕복은 이 함수를 자주 부르므로 프로세스당 1회.
    fixed = lmname.fix_edge_cfg(cfg, ROOT)
    if fixed:
        _notice(f"CFG-OLD|{cfg_path or ''}|{','.join(fixed)}",
                f"경고: config 의 옛 판 값을 {lmname.SHORT} 값으로 바꿔 씁니다 — " + ", ".join(fixed), label="")
    return cfg


def _truthy(v, default=False):
    """설정 참/거짓 — 비었으면 default."""
    if v is None or v == "":
        return default
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "y", "on")


# ── LM28 사유 코드(결과 dict 의 reason) — 사람이 할 일은 REASON_HINT, 안내는 프로세스당 1회 ──
R_EDGEPOL = "R-EDGEPOL"            # Edge 정책이 디버그 포트·전용 프로필을 막음 — 띄우지 않는다
R_EDGEKEEP = "R-EDGEKEEP"          # 정책이 종료 때 쿠키를 지움 — 닫으면 매번 다시 로그인
R_EDGEBUSY = "R-EDGEBUSY"          # 다른 작업이 전용 Edge 를 쓰는 중(edge_lock 대기 초과)
R_EDGEFOREIGN = "R-EDGEFOREIGN"    # 그 포트의 디버그 Edge 가 우리 프로필 것이 아님 — 붙지 않는다
R_EDGELAUNCH = "R-EDGELAUNCH"      # Edge 를 띄우지 못함(실행 오류·포트 안 열림)
R_PERSONAL = "R-PERSONAL"          # 개인 Microsoft 계정 화면 — 업무 자료를 보내지 않는다(fatal)
R_ACCOUNT = "R-ACCOUNT"            # 공용 호스트(office.com 등)에 머묾 — 계정 종류를 모르면 보내지 않는다
R_LOGIN = "R-LOGIN"                # 로그인 필요(회사 IdP 화면 포함)
R_LOGIN_DEVICE = "R-LOGIN-DEVICE"  # 장치 기반 조건부 액세스 — Edge 프로필에 회사 계정 로그인으로 풀린다
R_LOGIN_WAIT = "R-LOGIN-WAIT"      # 사용 약관·추가 인증 단계 — 사람이 그 화면에서 마친다
R_CA = "R-CA"                      # 조건부 액세스 정책 차단
R_DEAD = "R-DEADPROFILE"           # 전용 프로필이 오류 화면만 냄
R_NET = "R-NET"                    # 네트워크 오류 화면(프로필 문제가 아님 — 계수하지 않는다)
R_GATE = "R-GATE"                  # G3 최종 프롬프트 검사에 걸림 — 보내지 않음
R_THROTTLE = "R-THROTTLE"          # Copilot 사용량 제한 문구 — 사다리 없이 돌려주고 호출자가 쉬었다 다시 보낸다
REASON_HINT = {
    R_EDGEPOL: "회사 Edge 정책(RemoteDebuggingAllowed=0 또는 UserDataDir 강제)이 전용 Edge 를 막습니다 — AI 단계는 "
               "PC 자료(규칙)로 진행합니다. 프롬프트 파일(report\\judge_*.md)을 Copilot 에 직접 붙여 쓸 수는 있습니다",
    R_EDGEKEEP: "회사 Edge 정책이 브라우저를 닫을 때 쿠키를 지웁니다 — 매번 다시 로그인하지 않으려면 "
                "config\\config.json 의 copilotAuto.keepEdgeOpen 을 true 로 두세요",
    R_EDGEBUSY: "다른 작업(웹 메일·팀즈 읽기·AI 연결 진단 등)이 전용 Edge 를 쓰고 있습니다 — 그 작업이 끝난 뒤 다시 실행하세요",
    R_EDGEFOREIGN: "디버그 포트 {port} 를 다른 프로그램의 Edge 가 쓰고 있습니다 — 그 Edge 를 닫거나 "
                   "config\\config.json 의 copilotAuto.port 를 바꾸세요(우리 것이 아닌 브라우저는 조종하지 않습니다)",
    R_EDGELAUNCH: "Edge 를 디버그 포트로 띄우지 못했습니다 — 열린 전용 Edge 창(data\\lm30v1_edge)을 닫고 다시 실행하세요",
    R_PERSONAL: "전용 Edge 가 개인 Microsoft 계정 화면(copilot.microsoft.com·login.live.com 등)입니다 — 업무 자료는 "
                "보내지 않았습니다. 전용 Edge 창에서 회사(조직) 계정으로 로그인하세요",
    R_ACCOUNT: "전용 Edge 가 업무용 Copilot(m365.cloud.microsoft) 화면에 머물지 않아 계정 종류를 확인할 수 없습니다 — "
               "보내지 않았습니다. 전용 Edge 창에서 회사(조직) 계정으로 로그인했는지 확인하세요",
    R_LOGIN: "방금 열린 Edge 창에서 회사 계정으로 로그인해 두세요 — 이후에는 무개입으로 동작합니다",
    R_LOGIN_DEVICE: "회사 장치 조건부 액세스(AADSTS 53000 계열)입니다 — 전용 Edge 창 오른쪽 위 프로필 단추에서 회사 계정으로 "
                    "'Edge 에 로그인'한 뒤 다시 실행하세요",
    R_LOGIN_WAIT: "로그인 화면에 사용 약관·추가 인증 단계가 남아 있습니다 — 전용 Edge 창에서 마친 뒤 다시 실행하세요",
    R_CA: "회사 조건부 액세스 정책이 이 브라우저의 접속을 막습니다(AADSTS 5300x) — IT 담당자에게 문의하세요",
    R_DEAD: "전용 Edge 가 오류 화면만 냅니다 — 서로 다른 실행에서 2회 연속이면 프로필을 새로 만듭니다(로그인 1회 다시)",
    R_NET: "네트워크(사내망·VPN) 연결을 확인한 뒤 다시 실행하세요",
    R_THROTTLE: "Copilot 이 잠시 응답을 제한했습니다 — 몇 분 쉬었다 자동으로 이어 보냅니다. 계속되면 1~2시간 뒤 [재분석만]",
}
LAST = {"reason": "", "keep": False, "breakaway": True}   # 마지막 ensure_edge 의 사유(웹 수집기는 진리값만 본다)
_NOTICED = set()


def _notice(code, text, label=None):
    """사람이 풀 수 있는 안내는 프로세스당 1회(code 별) — stderr(stdout 은 결과 JSON 한 건 계약)."""
    if code in _NOTICED:
        return
    _NOTICED.add(code)
    lab = code if label is None else label
    try:
        print(f"[copilot_auto] {lab + ': ' if lab else ''}{text}", file=sys.stderr, flush=True)
    except (OSError, ValueError, UnicodeEncodeError):
        pass


def _hint(reason, cfg=None):
    return REASON_HINT.get(reason, "").replace("{port}", str((cfg or {}).get("port") or lmname.CDP_PORT))


def find_edge():
    for p in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
        if os.path.exists(p):
            return p
    return None


def http_json(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def debugger_alive(port):
    try:
        http_json(port, "/json/version")
        return True
    except Exception:
        return False


# ── 최소 WebSocket 클라이언트 (RFC6455, 클라이언트 마스킹/조각 프레임/ping 처리) ──
class WsForbidden(ConnectionError):
    """WS 핸드셰이크 403 — Edge 의 --remote-allow-origins 가 이 Origin(없음 포함)을 받지 않았다."""


class WS:
    def __init__(self, url, timeout=30, origin=None):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.origin = origin
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               + (f"Origin: {origin}\r\n" if origin else "")
               + f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        try:
            self.sock.sendall(req.encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("ws handshake: connection closed")
                resp += chunk
            status = resp.split(b"\r\n", 1)[0]
            if b" 101 " not in status:
                if b" 403 " in status:
                    raise WsForbidden("ws handshake 403: " + status[:80].decode(errors="replace"))
                raise ConnectionError("ws handshake rejected: " + resp[:120].decode(errors="replace"))
        except BaseException:
            self.close()                      # 실패한 소켓을 남기지 않는다
            raise

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("ws: connection closed")
            buf += chunk
        return buf

    def send_text(self, text):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = b"\x81"                       # FIN + text
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_text(self):
        """다음 완결 텍스트 메시지 1건 (조각 프레임 조립, ping 자동 응답)"""
        parts = []
        while True:
            b1, b2 = self._read_exact(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(n) if n else b""
            if opcode == 9:                    # ping → pong
                mask = os.urandom(4)
                masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                self.sock.sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + masked)
                continue
            if opcode == 8:
                raise ConnectionError("ws: closed by server")
            if opcode in (1, 2, 0):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def ws_open(url, timeout=30, origin=None):
    """WS 연결 — 기본은 Origin 없이(Edge 는 Origin 없는 연결을 받는다). 403 이면 자기 포트 Origin
    (http://127.0.0.1:<port> — 우리가 띄운 Edge 의 --remote-allow-origins 와 같은 값)으로 한 번 더(C-36)."""
    try:
        return WS(url, timeout, origin=origin)
    except WsForbidden:
        m = re.match(r"ws://[^:/]+:(\d+)/", str(url or ""))
        if origin or not m:
            raise
        return WS(url, timeout, origin=f"http://127.0.0.1:{m.group(1)}")


class CDP:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = ws_open(ws_url)
        self.next_id = 0

    def call(self, method, params=None, timeout=25):
        self.next_id += 1
        mid = self.next_id
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while True:
            remain = end - time.time()
            if remain <= 0:
                raise TimeoutError(f"CDP {method}: {timeout}초 내 무응답")
            # per-call 데드라인을 소켓에 실제로 전달 — 고정 30초에 묶이면 timeout 인자가 무의미해진다
            self.ws.sock.settimeout(max(0.5, min(remain, 30.0)))
            try:
                msg = json.loads(self.ws.recv_text())
            except TimeoutError as e:
                # 타임아웃이 프레임 중간에 나면 스트림 동기가 깨질 수 있으므로 이 연결은 재사용 금지
                raise TimeoutError(f"CDP {method}: {timeout}초 내 무응답 (연결 재수립 필요)") from e
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})

    def reconnect(self):
        """타임아웃 후 스트림 desync 대비 — 새 소켓으로 재접속"""
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = ws_open(self.ws_url, origin=getattr(self.ws, "origin", None))

    def eval(self, expr, timeout=25):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": False},
                      timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError("JS: " + str(res.get("description", ""))[:200])
        return res.get("value")

    def close(self):
        self.ws.close()


# ── Edge 정책(읽기만) ──
EDGE_POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Edge"
EDGE_POLICY_NAMES = ("RemoteDebuggingAllowed", "UserDataDir", "ClearBrowsingDataOnExit", "DefaultCookiesSetting")
_POLICY = {}                                  # 프로세스당 1회 읽은 값


def read_edge_policies():
    """Edge 정책 값(HKLM 이 HKCU 보다 우선) — 읽기만 한다. 없거나 못 읽으면 {}."""
    if "v" in _POLICY:
        return dict(_POLICY["v"])
    out = {}
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):     # 뒤(HKLM)가 덮는다
            try:
                with winreg.OpenKey(hive, EDGE_POLICY_KEY) as k:
                    for name in EDGE_POLICY_NAMES:
                        try:
                            out[name] = winreg.QueryValueEx(k, name)[0]
                        except OSError:
                            pass
            except OSError:
                continue
    except ImportError:
        pass
    _POLICY["v"] = out
    return dict(out)


def _int_or_none(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def edge_policy_reason(pol):
    """정책 → (사유, 근거). R-EDGEPOL = 띄우지 않는다(디버그 포트 금지·사용자 데이터 폴더 강제 — 전용 프로필을 못 쓴다),
    R-EDGEKEEP = 띄우되 '닫으면 매번 다시 로그인' 안내(종료 때 쿠키 삭제·세션 쿠키만). 해당 없으면 ("", "")."""
    pol = pol if isinstance(pol, dict) else {}
    if "RemoteDebuggingAllowed" in pol and _int_or_none(pol.get("RemoteDebuggingAllowed")) == 0:
        return R_EDGEPOL, "RemoteDebuggingAllowed=0"
    if str(pol.get("UserDataDir") or "").strip():
        return R_EDGEPOL, "UserDataDir"
    if _int_or_none(pol.get("ClearBrowsingDataOnExit")) == 1:
        return R_EDGEKEEP, "ClearBrowsingDataOnExit=1"
    if _int_or_none(pol.get("DefaultCookiesSetting")) == 4:
        return R_EDGEKEEP, "DefaultCookiesSetting=4"
    return "", ""


# ── 소유 표식(owner.json)·프로필 상태 ──
OWNER_FILE = "owner.json"
DEAD_LIMIT = 2                                # 서로 다른 왕복에서 죽은 프로필 2회 연속 → 프로필 새로 만들기
EDGE_LOCK_WAIT = 600                          # 전용 Edge 잠금 대기 상한(초) — 넘으면 R-EDGEBUSY
PROBE_LOCK_WAIT = 10                          # 진단(--probe·--diagnose)은 오래 기다리지 않는다(화면 요청 안)


def owner_path(cfg):
    return os.path.join(cfg["profileDir"], OWNER_FILE)


def _side_path(cfg, suffix):
    """프로필 폴더 **옆** 파일(<프로필>.busy.lock · <프로필>.state.json) — 프로필 이름을 바꿀 때 열린 핸들이 막지 않게."""
    return str(cfg["profileDir"]).rstrip("\\/") + suffix


def read_owner(cfg):
    try:
        with open(owner_path(cfg), encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _version(port):
    """그 포트의 /json/version(dict) — 응답이 없으면 None."""
    try:
        v = http_json(port, "/json/version")
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001 - 응답 없음 = 없음
        return None


def _browser_path(ver):
    """/json/version 의 webSocketDebuggerUrl → '/devtools/browser/<id>' (브라우저 신원)."""
    try:
        return urlparse(str((ver or {}).get("webSocketDebuggerUrl") or "")).path or ""
    except ValueError:
        return ""


def _write_owner(cfg, pid):
    """우리가 띄웠다는 표식 — close_own_edge 는 이것이 있고 브라우저 ID 가 같을 때만 닫는다."""
    port = int(cfg["port"])
    return _write_json(owner_path(cfg), {"pid": int(pid or 0), "port": port,
                                         "t": time.strftime("%Y-%m-%d %H:%M:%S"), "root": ROOT,
                                         "browser": _browser_path(_version(port))})


def _update_owner(cfg, **kv):
    """표식이 있을 때만 값을 고친다(우리가 띄우지 않은 Edge 에는 표식을 만들지 않는다)."""
    o = read_owner(cfg)
    if o is None:
        return False
    if all(o.get(k) == v for k, v in kv.items()):
        return True
    o.update(kv)
    return _write_json(owner_path(cfg), o)


def _drop_owner(cfg):
    try:
        os.remove(owner_path(cfg))
    except OSError:
        pass


def _read_dap(profile_dir):
    """프로필의 DevToolsActivePort → (포트, '/devtools/browser/<id>') · 없으면 None."""
    try:
        with open(os.path.join(profile_dir, "DevToolsActivePort"), encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f.read().splitlines()]
        return int(lines[0]), (lines[1] if len(lines) > 1 else "")
    except (OSError, ValueError, IndexError):
        return None


def owns_port(cfg):
    """그 포트의 디버그 Edge 가 우리 전용 프로필의 것인가 — 프로필의 DevToolsActivePort(포트·브라우저 경로)로 확인.
    표식이 없으면 판정할 수 없으므로 LM24 처럼 재사용(True), 표식이 있는데 포트·브라우저가 다르면 남의 것(False)."""
    dap = _read_dap(cfg["profileDir"])
    if not dap:
        return True
    port = int(cfg["port"])
    if dap[0] != port:
        return False
    v = _version(port)
    if not v or not dap[1]:
        return True
    return str(v.get("webSocketDebuggerUrl") or "").endswith(dap[1])


# ── Edge 수명주기 ──
def edge_args(cfg, edge):
    """기동 인자 — Origin 은 자기 포트만 허용한다(예전 '*' 는 같은 PC 의 웹 페이지가 로그인 세션을 조종할 수 있었다).
    --disk-cache-size: 이 프로필의 디스크 캐시 상한(바이트). 상한이 없어 GB 급으로 자랐고,
    그것이 PC 간 폴더 이동이 10~30분 걸리던 원인이었다(파일 수 94%·용량 96%). 캐시는 새 PC 에서
    어차피 다시 받는 것이라 줄여도 잃는 것이 없다. 0 이면 상한을 걸지 않는다(예전 동작).
    배경 스로틀링 해제 3종 — 창이 뒤에 있거나 탭이 비활성이면 크로미움이 타이머·렌더를 늦춘다.
    그러면 답이 화면 텍스트로 자라지 않아 드라이버가 헛되이 기다린다(제보: 커서를 대니 움직였다)."""
    port = int(cfg["port"])
    return ([edge, f"--user-data-dir={cfg['profileDir']}", f"--remote-debugging-port={port}",
             f"--remote-allow-origins=http://127.0.0.1:{port}", "--no-first-run", "--no-default-browser-check",
             "--disable-background-timer-throttling", "--disable-backgrounding-occluded-windows",
             "--disable-renderer-backgrounding"]
            + ([f"--disk-cache-size={int(cfg.get('diskCacheMB') or 0) * 1048576}"]
               if int(cfg.get("diskCacheMB") or 0) > 0 else [])
            + ["--window-size=1150,900", cfg["url"]])


def _popen_edge(args):
    """Edge 기동 — 상위 Job 에서 떼어 띄운다(CREATE_BREAKAWAY_FROM_JOB). 상위 Job 이 이탈을 막아 거부되면
    (ERROR_ACCESS_DENIED) 플래그 없이 1회 — 그때는 그 단계가 끝날 때 Edge 도 끝나고 다음 단계가 다시 띄운다.
    표준 입출력은 넘기지 않는다(부모의 파이프를 Edge 가 붙잡으면 부모가 끝을 모른다)."""
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        p = subprocess.Popen(args, creationflags=NO_WIN | CREATE_BREAKAWAY_FROM_JOB, **kw)
        LAST["breakaway"] = True
        return p
    except OSError as e:
        if getattr(e, "winerror", None) != ERROR_ACCESS_DENIED:
            raise
    LAST["breakaway"] = False
    return subprocess.Popen(args, creationflags=NO_WIN, **kw)


def ensure_edge(cfg):
    """디버그 포트가 살아 있고 우리 프로필의 것이면 재사용, 없으면 전용 프로필로 새로 띄운다 →
    'reused' | 'launched' | None. None 의 사유는 LAST['reason'](R-EDGEPOL·R-EDGEFOREIGN·R-EDGELAUNCH) —
    웹 수집기(Get-OutlookWeb·Get-TeamsWeb)는 진리값만 보므로 반환 형식은 LM24 그대로다."""
    LAST["reason"] = ""
    if os.environ.get("LM_NO_BROWSER"):        # 회귀 시험용 — 실제 Edge 를 띄우지 않는다(스텁 드라이버는 무관)
        return None
    port = cfg["port"]
    if debugger_alive(port):
        if not owns_port(cfg):
            LAST["reason"] = R_EDGEFOREIGN
            _notice(R_EDGEFOREIGN, _hint(R_EDGEFOREIGN, cfg))
            return None
        return "reused"
    edge = find_edge()
    if not edge:
        return None
    why, basis = edge_policy_reason(read_edge_policies())
    if why == R_EDGEPOL:
        LAST["reason"] = R_EDGEPOL
        _notice(R_EDGEPOL, f"({basis}) " + _hint(R_EDGEPOL, cfg))
        return None
    if why == R_EDGEKEEP:
        LAST["keep"] = True
        _notice(R_EDGEKEEP, f"({basis}) " + _hint(R_EDGEKEEP, cfg))
    os.makedirs(cfg["profileDir"], exist_ok=True)
    try:
        proc = _popen_edge(edge_args(cfg, edge))
    except OSError:
        LAST["reason"] = R_EDGELAUNCH
        return None
    for _ in range(40):                        # 최대 20초 대기
        _sleep(0.5)
        if debugger_alive(port):
            _write_owner(cfg, getattr(proc, "pid", 0))
            return "launched"
    LAST["reason"] = R_EDGELAUNCH
    return None


def close_own_edge(cfg=None, reason="", force=False, tidy=True):
    """우리가 띄운 전용 Edge 만 닫는다 → {"closed": bool, "why": str(, "chats": 정리 코드)}. 작업 단위(수집 1회·분석 1회)가 끝날 때
    부른다(run.py · 화면의 시작·[중지]·종료).
    · owner.json(ensure_edge 가 띄울 때 쓴 표식)이 없으면 아무것도 하지 않는다 — 사람이 띄운 Edge 는 건드리지 않는다.
    · keepEdgeOpen=true 면 닫지 않는다(종료 때 쿠키를 지우는 정책 PC — R-EDGEKEEP).
    · 로그인 대기 중(login_pending)이면 닫지 않는다 — 사람이 그 창에서 로그인하는 중일 수 있다(force 면 무시).
    · /json/version 이 응답하고 브라우저 ID 가 표식과 같을 때만 CDP Browser.close 를 보낸다(taskkill 은 쓰지 않는다).
      포트가 닫히길 최대 5초 기다린 뒤 표식을 지운다 — 그래도 안 닫혀도 강제 종료하지 않는다.
    · tidy(LM28 채팅 정리): 우리 Edge 이고 로그인 대기가 아니면 닫기 전에(keepEdgeOpen 이라 두는 때도) 마지막 우리 채팅을 지운다
      (_tidy_chats — 상한 CHAT_RETIRE_SEC, 예외를 내지 않는다 — 정리가 닫기를 막지 않는다). 죽은 프로필 교체(recreate_profile)는
      tidy=False — 오류 화면에는 지울 채팅이 보이지 않는다."""
    cfg = cfg if isinstance(cfg, dict) else load_cfg()
    if _truthy(cfg.get("keepEdgeOpen")) and not force:
        out = {"closed": False, "why": "keep"}
        own = read_owner(cfg) if tidy else None
        if own and not own.get("login_pending"):
            code = _tidy_chats(cfg, reason)
            if code != "none":
                out["chats"] = code
        return out
    own = read_owner(cfg)
    if not own:
        return {"closed": False, "why": "not_ours"}
    if own.get("login_pending") and not force:
        return {"closed": False, "why": "login_pending"}
    try:
        port = int(own.get("port") or cfg["port"])
    except (TypeError, ValueError):
        port = int(cfg["port"])
    ver = _version(port)
    if not ver:
        _drop_owner(cfg)                        # 이미 꺼졌다 — 표식만 치운다
        return {"closed": False, "why": "gone"}
    ws = str(ver.get("webSocketDebuggerUrl") or "")
    if own.get("browser") and not ws.endswith(str(own["browser"])):
        _drop_owner(cfg)                        # 그 포트의 브라우저가 우리가 띄운 것이 아니다(표식이 낡았다)
        return {"closed": False, "why": "not_ours"}
    chats = _tidy_chats(cfg, reason) if tidy else "none"
    try:
        b = CDP(ws)
        try:
            b.call("Browser.close", timeout=5)
        except (TimeoutError, RuntimeError, OSError):
            pass                                # 닫히면서 연결이 끊기는 것이 정상이다
        finally:
            b.close()
    except (OSError, ValueError, AttributeError):
        pass
    for _ in range(10):                         # 포트가 닫히길 최대 5초
        if not debugger_alive(port):
            break
        _sleep(0.5)
    _drop_owner(cfg)
    trace("edge_close", why=str(reason or "")[:40], port=port)
    out = {"closed": True, "why": str(reason or "done")}
    if chats != "none":
        out["chats"] = chats
    return out


class EdgeBusy(RuntimeError):
    """전용 Edge 잠금을 얻지 못했다(R-EDGEBUSY)."""
    reason = R_EDGEBUSY


_LOCKS = {}                                    # 잠금 파일 경로 → [파일, 깊이] — 같은 프로세스 안 재진입


def lock_path(cfg):
    return _side_path(cfg, ".busy.lock")


@contextlib.contextmanager
def edge_lock(cfg=None, timeout=EDGE_LOCK_WAIT):
    """전용 Edge(같은 프로필)를 쓰는 작업을 직렬로 — msvcrt 바이트 잠금(<프로필>.busy.lock). 프로세스가 죽으면 OS 가
    잠금을 푼다(낡은 잠금이 남지 않는다). 같은 프로세스 안에서는 다시 들어갈 수 있다. timeout 초를 넘기면 EdgeBusy."""
    cfg = cfg if isinstance(cfg, dict) else load_cfg()
    path = lock_path(cfg)
    held = _LOCKS.get(path)
    if held:
        held[1] += 1
        try:
            yield path
        finally:
            held[1] -= 1
        return
    try:
        import msvcrt
    except ImportError:                         # 윈도가 아니면 잠그지 않는다(시험·개발용)
        yield path
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    t_end = time.time() + max(0.0, float(timeout or 0))
    waited = False
    while True:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            if time.time() >= t_end:
                f.close()
                raise EdgeBusy(f"전용 Edge 를 다른 작업이 쓰고 있습니다({int(timeout or 0)}초 대기 초과)") from None
            if not waited:
                waited = True
                _notice("EDGE-WAIT", "다른 작업이 전용 Edge 를 쓰고 있어 끝나기를 기다립니다(최대 "
                                     f"{int(timeout or 0)}초)")
            _sleep(min(2.0, max(0.05, t_end - time.time())))
    _LOCKS[path] = [f, 1]
    try:
        yield path
    finally:
        _LOCKS.pop(path, None)
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        f.close()


def _state(cfg):
    try:
        with open(_side_path(cfg, ".state.json"), encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def _note_dead(cfg):
    """죽은 프로필 관찰 1회 기록 → 연속 횟수."""
    st = _state(cfg)
    n = int(st.get("dead") or 0) + 1
    st.update(dead=n, dead_t=time.strftime("%Y-%m-%d %H:%M:%S"))
    _write_json(_side_path(cfg, ".state.json"), st)
    return n


def _reset_dead(cfg):
    st = _state(cfg)
    if st.get("dead"):
        st["dead"] = 0
        _write_json(_side_path(cfg, ".state.json"), st)


# ── 사용량 제한 기록(LM28 진단 A) — <프로필>.throttle.json {t, n, hard, hard_t} ──
# 판정이 강한 제한(쉬고도 막힘)으로 멈춘 직후 다음 단계(정제·Agentic·워크플로우 — 다른 프로세스)가 15초 만에 같은 벽으로 들어갔다.
# 기록을 남겨 다음 프로세스의 첫 왕복이 남은 시간만 쉬게 한다(judge.copilot_send). 성공 왕복이 지운다(_after).
# LM28 — 사용량 제한(「요청이 너무 많음」)으로 멈춘 강한 제한은 실행 표식(run = LM_RUN_ID)·갈래(kind 'throttle')도 적는다 {…, run, kind}.
# 같은 실행의 뒤 단계(다른 프로세스 — 월별 코멘트·정제·Agentic·워크플로우·메일/팀즈 확인)는 이 표식을 보고 보내지 않는다
# (run_stopped — 남은 시간 쉬기도 없이). 지난 실행의 기록은 5분 안이면 남은 시간만 쉬고(이번 실행의 쉬는 시간 합계 안) 한 번 보낸다.
# 옛 판 기록(run 없음)도 그대로 읽힌다.
THROTTLE_FILE = ".throttle.json"


def note_throttle(cfg=None, hard=False, run=None, kind=None):
    """사용량 제한 관찰 1회 기록. 1시간 안의 관찰은 n 을 늘린다. hard(강한 제한)는 성공 왕복이 지울 때까지 남긴다
    (hard_t = 마지막 강한 제한 시각). 기록 실패는 무시한다(왕복을 막지 않는다).
    run·kind 는 강한 제한일 때만 적는다 — 사용량 제한으로 멈춘 실행의 표식(LM_RUN_ID)과 갈래('throttle'). 강한 제한을 run 없이
    다시 적으면(일시 오류 사다리 끝의 hard) 표식을 지운다 — 다음 단계는 예전처럼 남은 시간만 쉬고 한 번 보낸다. 약한 관찰은 둔다."""
    try:
        cfg = cfg or load_cfg()
        p = _side_path(cfg, THROTTLE_FILE)
        now = time.time()
        try:
            with open(p, encoding="utf-8-sig") as f:
                o = json.load(f)
            o = o if isinstance(o, dict) else {}
        except (OSError, ValueError):
            o = {}
        try:
            n = int(o.get("n") or 0) + 1 if now - float(o.get("t") or 0) < 3600 else 1
            hard_t = now if hard else float(o.get("hard_t") or 0)
        except (TypeError, ValueError):
            n, hard_t = 1, (now if hard else 0.0)
        rec = {"t": now, "n": n, "hard": bool(hard_t)}
        if hard_t:
            rec["hard_t"] = hard_t
            rid, knd = (run, kind) if hard else (o.get("run"), o.get("kind"))
            if rid:
                rec["run"] = str(rid)[:64]
            if knd:
                rec["kind"] = str(knd)[:20]
        return _write_json(p, rec)
    except Exception:  # noqa: BLE001 - 기록이 왕복을 막지 않게
        return False


def throttle_state(cfg=None, run=False):
    """마지막 사용량 제한 기록 → (지난 초, 강한 제한인가) · 기록이 없으면 None. 강한 제한이면 지난 초는 마지막 강한 제한부터.
    run=True 면 (지난 초, 강한 제한인가, 실행 표식, 갈래) — 표식·갈래는 강한 제한일 때만(없으면 "")."""
    try:
        cfg = cfg or load_cfg()
        with open(_side_path(cfg, THROTTLE_FILE), encoding="utf-8-sig") as f:
            o = json.load(f)
        hard = bool(o.get("hard"))
        t = float((o.get("hard_t") if hard else o.get("t")) or 0)
        rid = str(o.get("run") or "") if hard else ""
        knd = str(o.get("kind") or "") if hard else ""
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return None
    if t <= 0:
        return None
    age = max(0.0, time.time() - t)
    return (age, hard, rid, knd) if run else (age, hard)


def run_id():
    """이번 실행의 표식 — run.py 가 시작 때 LM_RUN_ID 에 싣고 자식(수집기·판정·정제·Agentic·워크플로우)이 물려받는다. 없으면 ""."""
    return str(os.environ.get("LM_RUN_ID") or "").strip()


def run_stopped(cfg=None):
    """이번 실행이 Copilot 사용량 제한으로 AI 단계를 멈췄는가 — 강한 제한 기록의 실행 표식이 지금 실행과 같을 때만.
    표식이 없는 실행(단계를 따로 돌림)·지난 실행의 기록은 아니다(그때는 judge 가 남은 시간만 쉬고 한 번 보내 본다)."""
    rid = run_id()
    if not rid:
        return False
    ts = throttle_state(cfg, run=True)
    return bool(ts and ts[1] and len(ts) > 2 and ts[2] == rid)


def run_stop_result():
    """같은 실행이 사용량 제한으로 멈춘 뒤의 왕복 결과 — 보내지 않았다. hard=True 라 explain_failure 가 치명으로 보고 호출자가
    남은 묶음을 보내지 않은 채 여기까지의 결과를 지킨다(규칙 판정·지난 결과 · abort_kind 'throttle')."""
    return {"ok": False, "phase": "throttled", "reason": R_THROTTLE, "hard": True, "run_stop": True,
            "error": "Copilot 사용량 제한 — 이번 실행은 더 보내지 않음",
            "hint": "Copilot 이 「요청이 너무 많다」고 해 이번 실행의 AI 단계를 멈췄습니다 — 1~2시간 뒤 [재분석만]"}


def clear_throttle(cfg):
    """성공 왕복 — 제한 기록을 지운다(있을 때만)."""
    try:
        p = _side_path(cfg, THROTTLE_FILE)
        if os.path.exists(p):
            os.remove(p)
    except (OSError, KeyError, TypeError):
        pass


# ── 보내기 간격(LM28) — <프로필>.pace.json {t} ──
# 판정 묶음·재시도·월별 코멘트·정제·Agentic·워크플로우·메일/팀즈 확인이 프로세스를 넘어 잇달아 보내면 짧은 시간에 요청이 몰려 Copilot 이
# 「요청이 너무 많다」고 막는다(현장 제보). 앞 전송 시각을 프로필 옆 파일에 남기고 copilotAuto.minGapSec(기본 15초 · 0 = 끔)이 지나기
# 전이면 남은 만큼만 기다린다. 파일이 없거나 깨졌으면 기다리지 않는다(첫 전송·옛 판).
PACE_FILE = ".pace.json"
PACE_QUIET_SEC = 5            # 이보다 짧게 기다리면 아무 줄도 찍지 않는다(평소 왕복의 짧은 맞춤은 조용히)


def _min_gap(cfg):
    try:
        return max(0.0, float((cfg or {}).get("minGapSec", DEFAULTS["minGapSec"])))
    except (TypeError, ValueError):
        return float(DEFAULTS["minGapSec"])


def pace_wait(cfg):
    """앞 전송(다른 프로세스 포함)에서 minGapSec 이 지나지 않았으면 남은 만큼만 기다린다 → 기다린 초.
    왕복 마감(_dl_left)에서 1분은 답을 기다릴 몫으로 남긴다. 시계가 뒤로 가 앞 시각이 미래여도 minGapSec 을 넘겨 기다리지 않는다."""
    gap = _min_gap(cfg)
    if gap <= 0:
        return 0.0
    try:
        with open(_side_path(cfg, PACE_FILE), encoding="utf-8-sig") as f:
            last = float(json.load(f).get("t") or 0)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return 0.0
    wait = min(gap, last + gap - time.time(), _dl_left(10 ** 6) - 60.0)
    if wait <= 0:
        return 0.0
    if wait > PACE_QUIET_SEC:
        try:
            print(f"[copilot_auto] 요청 간격 — 앞 요청에서 {gap:.0f}초가 지나지 않아 {wait:.0f}초 기다렸다 보냅니다"
                  "(copilotAuto.minGapSec)", file=sys.stderr, flush=True)
        except (OSError, ValueError, UnicodeEncodeError):
            pass
    _sleep(wait)
    return round(wait, 1)


def mark_sent(cfg):
    """방금 프롬프트를 보냈다 — 다음 전송(다른 프로세스 포함)의 간격 기준. 기록 실패는 무시한다."""
    try:
        _write_json(_side_path(cfg, PACE_FILE), {"t": time.time()})
    except Exception:  # noqa: BLE001 - 기록이 왕복을 막지 않게
        pass


# ── 실행의 쉬는 시간 합계(LM28) — <프로필>.wait.json {run, sec, t} ──
# 쉬는 사다리·사용량 제한 대기·다음 단계의 남은 시간 쉬기·Agentic/워크플로우의 쉬기·run.py 의 재시도 대기는 단계(프로세스)마다 따로
# 셌다 — 한 실행이 다 합쳐 반시간 넘게 쉴 수 있었다(사용자 요청 '분석이 길면 업무에도 지장'). 이 실행(LM_RUN_ID)에서 쉰 초를 프로세스를
# 넘어 모으고, 쉬는 쪽(judge._cool_room·run.py)은 copilotAuto.runWaitMaxSec(기본 300초 · 0 = 쉬지 않음)의 남은 몫 안에서만 쉰다.
# 실행 표식이 없으면(단계를 따로 돌림) 합계 상한이 없다(예전처럼 프로세스 상한만). 다른 실행의 기록은 0 부터 다시 센다.
WAIT_FILE = ".wait.json"


def run_wait_max(cfg=None):
    """copilotAuto.runWaitMaxSec → 한 실행에서 쉬는 초 합계 상한(≥ 0 · 0 = 쉬지 않음). 음수·글자·무한은 기본값."""
    dflt = float(DEFAULTS["runWaitMaxSec"])
    try:
        v = (cfg or load_cfg()).get("runWaitMaxSec", dflt)
        n = dflt if v is None or v == "" else float(v)
    except Exception:  # noqa: BLE001 - 설정을 못 읽으면 기본값
        return dflt
    return n if 0 <= n < float("inf") else dflt


def run_waited(cfg=None):
    """이번 실행(LM_RUN_ID)에서 지금까지 쉰 초 — 실행 표식이 없거나 기록이 없거나 깨졌거나 다른 실행의 것이면 0."""
    rid = run_id()[:64]
    if not rid:
        return 0.0
    try:
        with open(_side_path(cfg or load_cfg(), WAIT_FILE), encoding="utf-8-sig") as f:
            o = json.load(f)
        if str(o.get("run") or "") != rid:
            return 0.0
        n = float(o.get("sec") or 0)
    except Exception:  # noqa: BLE001 - 기록을 못 읽으면 쉬지 않은 것으로 본다
        return 0.0
    return n if n > 0 else 0.0


def run_wait_left(cfg=None):
    """이번 실행에서 더 쉴 수 있는 초 = max(0, runWaitMaxSec − 쉰 초). 실행 표식이 없으면 무한(합계 상한 없음)."""
    if not run_id():
        return float("inf")
    try:
        cfg = cfg or load_cfg()
    except Exception:  # noqa: BLE001
        cfg = dict(DEFAULTS)
    return max(0.0, run_wait_max(cfg) - run_waited(cfg))


def add_run_wait(sec, cfg=None):
    """방금 sec 초 쉬었다 — 이번 실행의 합계에 더한다(다른 실행의 기록이면 새로 센다). 실행 표식이 없거나 sec ≤ 0 이면 아무것도
    하지 않는다. 기록 실패는 무시한다(쉬기·왕복을 막지 않는다) → 적었으면 True."""
    try:
        sec = float(sec)
        rid = run_id()[:64]
        if not rid or not sec > 0:
            return False
        p = _side_path(cfg or load_cfg(), WAIT_FILE)
        try:
            with open(p, encoding="utf-8-sig") as f:
                o = json.load(f)
            prev = float(o.get("sec") or 0) if str(o.get("run") or "") == rid else 0.0
        except Exception:  # noqa: BLE001 - 없거나 깨진 기록은 0 부터
            prev = 0.0
        prev = prev if prev > 0 else 0.0
        return _write_json(p, {"run": rid, "sec": round(prev + sec, 1), "t": time.time()})
    except Exception:  # noqa: BLE001 - 기록이 쉬기를 막지 않게
        return False


def recreate_profile(cfg):
    """죽은 프로필(서로 다른 왕복에서 오류 화면 2회 연속) — 우리 Edge 를 닫고 프로필 폴더를 <이름>.bad-<시각> 으로 바꾼 뒤
    새로 띄운다(로그인 1회 다시). 사람이 띄운 Edge 가 그 프로필을 쓰고 있으면(표식 없음·포트 살아 있음) 손대지 않는다.
    옛 .bad-* 는 지우지 않는다(사람이 확인하고 지운다). 채팅 정리는 하지 않는다(tidy=False — 오류 화면에는 대화가 보이지 않는다)."""
    close_own_edge(cfg, "dead_profile", force=True, tidy=False)
    if debugger_alive(cfg["port"]):
        return False
    src = str(cfg["profileDir"]).rstrip("\\/")
    if os.path.isdir(src):
        try:
            os.replace(src, f"{src}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
        except OSError:
            return False
    _reset_dead(cfg)
    trace("profile_recreated")
    ensure_edge(cfg)
    return True


def edge_fail(cfg):
    """ensure_edge 가 None 일 때의 결과 dict — 사유(LAST['reason'])가 있으면 그 문구로. phase 는 LM24 그대로
    (edge_not_found · launch_failed — 둘 다 사람이 손대야 풀리는 실패라 호출자가 남은 묶음을 보내지 않는다)."""
    out = {"ok": False, "phase": "edge_not_found" if not find_edge() else "launch_failed",
           "error": "Edge 실행 실패",
           "hint": "Edge 설치 여부 확인 · 보안 정책이 디버그 포트를 막는 환경이면 클립보드(수동) 방식 사용"}
    r = LAST.get("reason") or ""
    if r:
        out.update(reason=r, hint=_hint(r, cfg),
                   error={R_EDGEPOL: "Edge 정책이 전용 Edge(디버그 포트)를 막음",
                          R_EDGEFOREIGN: "디버그 포트를 다른 브라우저가 쓰는 중"}.get(r, out["error"]))
    return out


# ── 호스트 판정(C-36·F-26·F-27) — 정확 일치 또는 '.' 으로 시작하는 항목은 마디 단위 접미 일치. 부분 문자열 비교 금지
#    (예전 'office.com' 부분 일치는 Outlook 웹 탭을 Copilot 탭으로 잡고 진짜 탭을 닫았다).
# 업무(Entra) 계정만 쓰는 Microsoft 365 호스트 — 여기서만 보낸다
WORK_HOSTS = ("m365.cloud.microsoft", ".cloud.microsoft", "outlook.office.com", "outlook.office365.com",
              ".office365.com", ".sharepoint.com")
# 개인·회사 공용 호스트 — 계정 종류의 근거가 되지 않는다(채팅 주소로 한 번 다시 들어가 본 뒤에도 여기면 보내지 않는다)
MIXED_HOSTS = ("office.com", ".office.com", "microsoft365.com", ".microsoft365.com")
# 개인 Microsoft 계정 화면(소비자 Copilot·개인 계정 로그인) — 업무 자료를 보내지 않는다
PERSONAL_HOSTS = ("copilot.microsoft.com", "login.live.com", "account.live.com", "bing.com", ".bing.com")
# 회사 로그인 호스트 — certauth.* 는 따로(인증서 로그인), AD FS 는 경로 /adfs/ 로 판정
LOGIN_HOSTS = ("login.microsoftonline.com", ".login.microsoftonline.com", "login.microsoft.com", "login.windows.net")
# Outlook·Teams·SharePoint 탭 — 채팅 탭으로 쓰지 않고, 닫거나 다른 주소로 옮기지 않는다(웹 수집기·사람의 탭)
APP_TAB_HOSTS = ("outlook.office.com", "outlook.office365.com", "outlook.cloud.microsoft", "outlook.live.com",
                 "teams.microsoft.com", "teams.cloud.microsoft", "teams.live.com", ".sharepoint.com")
DEAD_SCHEMES = ("chrome-error://", "edge-error://")
BLANK_PREFIXES = ("about:blank", "about:newtab", "edge://newtab", "chrome://newtab", "chrome-search://",
                  "edge://new-tab-page")
LOOPBACK = ("127.0.0.1", "localhost")


def host_in(host, entries):
    """호스트가 목록에 드는가 — 정확 일치, '.' 으로 시작하는 항목은 마디 단위 접미사(LM27 settings.host_in)."""
    h = str(host or "").lower().rstrip(".")
    if not h:
        return False
    for e in entries or ():
        e = str(e or "").lower()
        if e.startswith("."):
            if h.endswith(e) and len(h) > len(e):
                return True
        elif h == e:
            return True
    return False


def _host(url):
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def page_kind(url, cfg=None):
    """탭 URL → 'work'(업무 Copilot·M365 — 보내도 됨) · 'mixed'(office.com·microsoft365.com — 개인·회사 공용, 근거 아님)
    · 'personal'(개인 Microsoft 계정) · 'login' · 'adfs'(회사 IdP) · 'blank' · 'dead'(오류 화면) · 'other'(그 밖 — 회사
    IdP 로그인 중으로 본다). cfg.url 의 호스트가 루프백(시험용 가짜 채팅)이면 그 호스트만 'work' 로 본다."""
    u = str(url or "").strip()
    low = u.lower()
    if not u or low.startswith(BLANK_PREFIXES):
        return "blank"
    if low.startswith(DEAD_SCHEMES):
        return "dead"
    if low.startswith(("edge://", "chrome://")):
        return "login"                          # Edge 로그인 강제(BrowserSignin) 등 사람이 풀 내부 화면
    try:
        p = urlparse(u)
    except ValueError:
        return "other"
    host = (p.hostname or "").lower()
    if not host:
        return "other"
    if host_in(host, PERSONAL_HOSTS):
        return "personal"
    if host_in(host, LOGIN_HOSTS) or host.startswith("certauth."):
        return "login"
    if "/adfs/" in "/" + (p.path or "").lower().strip("/") + "/":
        return "adfs"
    if host_in(host, WORK_HOSTS):
        return "work"
    if host_in(host, MIXED_HOSTS):
        return "mixed"
    if cfg and host in LOOPBACK and host == _host(cfg.get("url")):
        return "work"
    return "other"


def is_app_tab(url):
    return host_in(_host(url), APP_TAB_HOSTS)


# Copilot 채팅 탭으로 다시 쓰는 탭 — 로그인·리디렉트로 호스트가 바뀌어도 **같은 탭을 재사용**한다.
# 예전에는 cfg.url 의 호스트만 봤다. 그래서 리디렉트된 탭을 못 알아보고 매 왕복마다 새 탭을 만들었고
# (단계마다 드라이버가 새 프로세스라 계속 늘어난다), 새 탭은 활성 탭이 아니어서 크로미움이 렌더·타이머를
# 늦춰 답이 자라지 않았다 — 제보의 "채팅 창이 2개 뜨고, 새 창에 커서를 대니 움직였다" 가 그 증상이다.
# LM28: 업무·공용 M365 호스트(Outlook·Teams·SharePoint 제외)와 로그인 중인 탭만 — 개인 계정 화면은 아니다.
def _is_chat_tab(url, want="", cfg=None):
    k = page_kind(url, cfg)
    if k in ("work", "mixed"):
        return not is_app_tab(url)
    if k in ("login", "adfs"):
        return True
    return bool(want) and _host(url) == str(want).lower() and k != "personal"


def _close_tab(port, tid):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{tid}", timeout=5).read()
        return True
    except Exception:
        return False


def find_tab(cfg):
    """Copilot 탭을 **하나만** 두고 그 ws URL 을 돌려준다.
    · 채팅 탭(_is_chat_tab — 업무 M365 호스트·로그인 중인 탭)이면 재사용 — 리디렉트된 탭도 같은 탭으로 본다.
      업무 호스트 탭을 로그인 탭보다 먼저 쓴다.
    · 같은 채팅 주소(cfg.url 호스트)의 탭이 여러 개면 하나만 남기고 닫는다. Outlook·Teams 탭·로그인 탭은 닫지 않는다
      (웹 수집기·사람의 탭일 수 있다).
    · 맞는 탭이 없으면 빈 탭·오류 탭·개인 계정 탭만 그 URL 로 옮긴다(그 밖의 탭은 두고 새 탭을 만든다)."""
    port = cfg["port"]
    try:
        tabs = [t for t in http_json(port, "/json") if t.get("type") == "page"]
    except Exception:
        return None
    want = _host(cfg["url"])
    hits = [t for t in tabs if _is_chat_tab(t.get("url"), want, cfg)]
    if hits:
        hits.sort(key=lambda t: 0 if page_kind(t.get("url"), cfg) in ("work", "mixed") else 1)   # 안정 정렬
        keep = hits[0]
        for t in hits[1:]:                      # 같은 채팅 탭이 여러 개 — 하나만 남긴다
            if t.get("id") and _host(t.get("url")) == want and not is_app_tab(t.get("url")):
                _close_tab(port, t["id"])
        return keep["webSocketDebuggerUrl"]
    # 채팅 탭이 없다 — 빈 탭·오류 탭·개인 계정 탭을 옮겨 쓴다(새 창·새 탭을 늘리지 않는다). 남의 탭은 옮기지 않는다.
    for t in tabs:
        ws = t.get("webSocketDebuggerUrl")
        if not ws or is_app_tab(t.get("url")) or page_kind(t.get("url"), cfg) not in ("blank", "dead", "personal"):
            continue
        try:
            c = CDP(ws)
            try:
                c.call("Page.navigate", {"url": cfg["url"]}, timeout=20)
                for _ in range(8):       # 준비되면 즉시 탈출(제보 ④ — 고정 20초 대기 축소)
                    time.sleep(1)
                    st = c.eval(js_state())
                    if st and st.get("ready") in ("interactive", "complete"):
                        break
            finally:
                c.close()
            return ws
        except Exception:
            continue
    from urllib.parse import quote
    for method in ("PUT", "GET"):               # 신버전은 PUT, 구버전은 GET
        try:
            t = http_json(port, "/json/new?" + quote(cfg["url"], safe=""), method=method)
            return t["webSocketDebuggerUrl"]
        except Exception:
            continue
    return None


def activate(cdp):
    """탭을 앞으로 — 보이지 않는 탭은 크로미움이 렌더·타이머를 늦춰 답이 자라지 않는다(제보의 정체).
    실패해도 왕복은 계속한다(포커스가 없을 뿐이다)."""
    try:
        cdp.call("Page.bringToFront", timeout=10)
        return True
    except Exception:
        return False


# ── 페이지 조작 ──
def js_state():
    return "({url: location.href, title: document.title, ready: document.readyState})"


def login_required(state, cfg=None):
    """로그인 화면(회사 로그인·AD FS·Edge 내부 로그인 화면)이거나 빈 탭인가 — 호스트 정확 판정(page_kind)."""
    return page_kind((state or {}).get("url", ""), cfg) in ("login", "adfs", "blank")


# 로그인 화면 AADSTS 오류 번호 분류(Microsoft Entra 오류 코드 — LM27 bridge.session.aadsts_kind 이식). 번호만 읽는다.
DEVICE_CA_CODES = frozenset({"50005", "50097", "53000", "53001"})    # 장치 기반 조건부 액세스 — Edge 프로필 로그인으로 풀림
POLICY_CA_CODES = frozenset({"53002", "53003", "53004", "530032"})   # 조직 정책 차단
INTERACTIVE_CODES = frozenset({"50158"})                            # 외부 보안 과제(사용 약관·타사 MFA) — 사람이 마친다


def aadsts_kind(code):
    """AADSTS 번호(문자열·정수) → 'device' · 'policy' · 'interactive' · 'other' · ''(번호 아님)."""
    c = str(code or "").strip()
    if not re.fullmatch(r"\d{5,6}", c):
        return ""
    if c in DEVICE_CA_CODES:
        return "device"
    if c in INTERACTIVE_CODES:
        return "interactive"
    if c in POLICY_CA_CODES or c.startswith("53"):
        return "policy"                         # 표에 없는 53xxx 도 조건부 액세스 계열
    return "other"


def aadsts_reason(code):
    """AADSTS 번호 → 사유 코드(R-LOGIN-DEVICE · R-LOGIN-WAIT · R-CA · R-LOGIN)."""
    return {"device": R_LOGIN_DEVICE, "interactive": R_LOGIN_WAIT, "policy": R_CA}.get(aadsts_kind(code), R_LOGIN)


def js_aadsts():
    """로그인 화면의 AADSTS 번호(숫자만) — 화면 글·계정은 돌려주지 않는다."""
    return (r"(function(){var t=(document.body&&document.body.innerText)||'';"
            r"var m=t.match(/AADSTS(\d{5,6})/);return m?m[1]:'';})()")


NET_ERR_RX = re.compile(r"ERR_(?:INTERNET_DISCONNECTED|NAME_NOT_RESOLVED|NAME_RESOLUTION_FAILED|NETWORK_CHANGED"
                        r"|CONNECTION_\w+|PROXY_\w+|TIMED_OUT|ADDRESS_UNREACHABLE|NETWORK_ACCESS_DENIED"
                        r"|TUNNEL_CONNECTION_FAILED|SSL_PROTOCOL_ERROR)")


def _login_result(cdp, cfg, kind):
    """로그인 대기 결과 — 로그인 화면이면 AADSTS 번호로 사유를 나눈다. 안내는 프로세스당 1회."""
    code = ""
    if kind in ("login", "adfs"):
        try:
            code = str(cdp.eval(js_aadsts(), timeout=10) or "")
        except (TimeoutError, RuntimeError, OSError):
            code = ""
    reason = R_ACCOUNT if kind == "mixed" else (aadsts_reason(code) if code else R_LOGIN)
    _notice(reason, _hint(reason, cfg))
    err = {R_CA: "회사 조건부 액세스 정책 차단", R_ACCOUNT: "업무 계정 화면 아님 — 보내지 않음",
           R_LOGIN_DEVICE: "장치 조건부 액세스 — Edge 프로필 로그인 필요"}.get(reason, "로그인 필요 (최초 1회)")
    out = {"ok": False, "phase": "login_required", "reason": reason, "error": err, "hint": _hint(reason, cfg)}
    if code:
        out["aadsts"] = code
    return out


def _personal_result(cfg):
    _notice(R_PERSONAL, _hint(R_PERSONAL, cfg))
    # phase 는 login_required(사람이 손대야 풀리는 실패 — 남은 묶음을 보내지 않는다). 사유는 reason 이 말한다.
    return {"ok": False, "phase": "login_required", "reason": R_PERSONAL,
            "error": "개인 Microsoft 계정 Copilot — 업무 자료를 보내지 않음", "hint": _hint(R_PERSONAL, cfg)}


def _dead_result(cdp, cfg):
    """오류 화면 — 네트워크 오류면 프로필 탓이 아니므로 세지 않는다. 그 밖이면 1회 기록하고, 연속 DEAD_LIMIT 회면 프로필을
    새로 만든다(recreate_profile)."""
    try:
        txt = str(cdp.eval("(document.body&&document.body.innerText||'').slice(0,2000)", timeout=10) or "")
    except (TimeoutError, RuntimeError, OSError):
        txt = ""
    if NET_ERR_RX.search(txt):
        return {"ok": False, "phase": "no_reply", "reason": R_NET, "error": "네트워크 오류 화면",
                "hint": _hint(R_NET, cfg)}
    n = _note_dead(cfg)
    out = {"ok": False, "phase": "launch_failed", "reason": R_DEAD,
           "error": f"전용 Edge 가 오류 화면만 냄({n}회 연속)", "hint": _hint(R_DEAD, cfg)}
    if n >= DEAD_LIMIT and recreate_profile(cfg):
        out["recreated"] = True
        out["hint"] = "전용 Edge 프로필을 새로 만들어 다시 띄웠습니다 — 열린 Edge 창에서 회사 계정으로 한 번 로그인한 뒤 다시 실행하세요"
    return out


def wait_page(cdp, cfg, tries=30):
    """페이지가 준비되고 업무 Copilot 호스트에 닿을 때까지(최대 tries 초) — (state, kind).
    개인 계정 화면이면 바로 돌려준다(기다려도 회사 계정이 되지 않는다). 오류 화면·공용 호스트(office.com 등)면 채팅 주소로
    한 번 다시 들어가 본다 — 회사 계정이면 업무 호스트로 간다."""
    require_work = _truthy(cfg.get("requireWorkAccount"), True)
    state, kind, nudged = {}, "", False
    for _ in range(max(1, int(tries))):
        state = cdp.eval(js_state()) or {}
        kind = page_kind(state.get("url"), cfg)
        if kind == "personal" and require_work:
            break
        if kind in ("dead", "mixed") and not nudged:
            nudged = True
            try:
                cdp.call("Page.navigate", {"url": cfg["url"]}, timeout=20)
            except (TimeoutError, RuntimeError, OSError):
                pass
            time.sleep(2)
            continue
        ready = state.get("ready") in ("interactive", "complete")
        if ready and _sendable(kind, cfg):
            break
        if ready and nudged and kind in ("dead", "mixed"):
            break                               # 다시 들어가 봤는데도 그대로다 — 더 기다리지 않는다
        time.sleep(1)
    return state, kind


def _sendable(kind, cfg):
    """이 화면에 프롬프트를 넣어도 되는가 — 업무 호스트만(requireWorkAccount=false 면 LM24 처럼 로그인 화면만 아니면)."""
    if kind == "work":
        return True
    if not _truthy(cfg.get("requireWorkAccount"), True):
        return kind in ("mixed", "personal", "other")
    return False


def page_gate(cdp, cfg, state, kind):
    """wait_page 결과 → 보내면 안 되는 상태의 결과 dict(None = 보내도 됨)."""
    if kind == "personal" and _truthy(cfg.get("requireWorkAccount"), True):
        return _personal_result(cfg)
    if kind == "dead":
        return _dead_result(cdp, cfg)
    if not _sendable(kind, cfg):
        return _login_result(cdp, cfg, kind)
    return None


def js_chat_text(cfg):
    sels = json.dumps(cfg["chatRootSelectors"])
    return ("(function(){for(const s of " + sels + "){const el=document.querySelector(s);"
            "if(el&&el.innerText&&el.innerText.length>0)return el.innerText;}"
            "return document.body?document.body.innerText:'';})()")


def js_pick_model(model):
    """모델 선택기(실측 aria-label '모델 선택기')를 열고 이름이 일치하는 항목을 클릭.
    이미 선택돼 있으면 스킵. 실패해도 전체 왕복은 계속한다(베스트 에포트)."""
    m = json.dumps(model)
    return ("""(function(){
  const want=""" + m + """.toLowerCase();
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const btns=[...document.querySelectorAll("button")].filter(b=>vis(b)&&
    ((b.getAttribute("aria-label")||"").includes("모델")||(b.getAttribute("aria-label")||"").toLowerCase().includes("model")));
  if(!btns.length)return {ok:false,err:"selector_not_found"};
  const btn=btns[0];
  const cur=(btn.getAttribute("aria-label")||"")+" "+(btn.innerText||"");
  // 표기 차이를 무시하고 비교한다 — js_pick_model_item 과 같은 규칙. 설정은 'GPT-5.6' 인데
  // 버튼 라벨은 'GPT 5.6 깊이 생각하기'(하이픈이 아니라 공백)라, 그대로 includes 하면 이
  // 단축 경로가 영원히 성립하지 않아 매 왕복 메뉴를 여닫으며 2.5초씩 버렸다(감사 실측).
  const nrm=x=>x.toLowerCase().replace(/[-\\s._]/g,"");
  if(nrm(cur).includes(nrm(want)))return {ok:true,already:true,cur:cur.slice(0,60)};
  // 이미 열려 있으면 다시 누르면 '닫힌다'(토글). 실측에서 이 때문에 모델 선택이 매번
  // 실패했다 — 열려 있는지 먼저 확인하고, 닫혀 있을 때만 연다.
  const open=[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")]
    .filter(vis).length;
  if(open>0)return {ok:true,opened:true,alreadyOpen:true,items:open};
  btn.click();
  return {ok:true,opened:true};
})()""")


def js_menu_open():
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  return {open:[...document.querySelectorAll("[role='menuitem'],[role='menuitemradio']")]
    .filter(vis).length};
})()""")


def js_pick_model_item(model):
    """열린 메뉴에서 목표 모델을 클릭. 최상위에 없으면 'GPT ›' 같은 하위 메뉴를 열어야 하므로
    submenu 후보를 돌려준다 — 실측(2026-08) Copilot 메뉴가
    [자동 / 빠른 응답 / 깊이 생각하기 / GPT ›] 구조로 바뀌어 평면 검색만으로는 못 찾는다."""
    m = json.dumps(model)
    return (r"""(function(){
  const want=""" + m + r""".toLowerCase();
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  // 메뉴 role 이 있는 항목만 — li/button 전역 탐색은 무관한 화면 요소를 클릭할 위험(실측 메뉴는 전부 role 보유)
  const nodes=[...document.querySelectorAll("[role='menuitemradio'],[role='menuitem'],[role='option']")]
    .filter(vis);
  const txt=e=>(e.innerText||e.getAttribute("aria-label")||"").trim();
  // 표기 차이를 무시하고 비교한다 — 설정은 'GPT-5.6' 인데 메뉴 실제 이름은
  // 'GPT 5.6 깊이 생각하기'(하이픈이 아니라 공백)라 그대로 비교하면 영원히 못 찾는다(실측).
  const norm=x=>x.toLowerCase().replace(/[-\s._]/g,"");
  const wantN=norm(want);
  // 1) 목표 모델이 그대로 보이면 클릭
  const hit=nodes.find(e=>norm(txt(e)).includes(wantN));
  if(hit){hit.click();return {ok:true,picked:txt(hit).slice(0,60)};}
  // 2) 없으면 하위 메뉴 후보 — 목표 이름의 앞 토큰(예: 'GPT-5.6' → 'gpt')을 품고
  //    펼침 표시(aria-haspopup / aria-expanded / › 아이콘)가 있는 항목
  const head=norm(want).replace(/[0-9].*$/,"") || want.split(/[-\s._]/)[0];
  const sub=nodes.find(e=>{
    const t=norm(txt(e));
    if(!t||t.length>40)return false;
    const looksParent=e.getAttribute("aria-haspopup")||e.getAttribute("aria-expanded")!==null
      ||/[›>❯»]/.test(txt(e))||(e.querySelector&&e.querySelector("svg"));
    return t.includes(head)&&looksParent;
  });
  if(sub){sub.click();return {ok:false,submenu:txt(sub).slice(0,40)};}
  return {ok:false,err:"item_not_found",seen:nodes.slice(0,12).map(txt).filter(Boolean).slice(0,8)};
})()""")


def select_model(cdp, cfg, override=None):
    """전송 전에 모델을 선택한다 — 실패는 경고로만 남기고 진행.
    메뉴가 [모드 목록 + 'GPT ›' 하위 메뉴]로 바뀌었으므로 하위 메뉴를 한 단계 열어본다.
    override 는 재시도 사다리의 '자동 모델 폴백'용."""
    model = (override or cfg.get("model") or "").strip()
    if not model:
        return "모델 미지정"
    try:
        r1 = cdp.eval(js_pick_model(model)) or {}
        if r1.get("already"):
            return f"모델 유지({model})"
        if not r1.get("ok"):
            return "모델 선택기 없음 — 기본 모델 사용"
        time.sleep(0.9)
        # 클릭했는데 안 열렸으면(렌더 지연·클릭 무시) 한 번 더 연다
        if not r1.get("alreadyOpen"):
            chk = cdp.eval(js_menu_open()) or {}
            if not chk.get("open"):
                cdp.eval(js_pick_model(model))
                time.sleep(1.0)
        seen = []
        for _depth in range(3):                     # 최상위 → 하위 메뉴 → 그 하위까지
            r2 = cdp.eval(js_pick_model_item(model)) or {}
            if r2.get("ok"):
                time.sleep(0.7)
                return f"모델 선택: {r2.get('picked', model)}"
            if r2.get("submenu"):
                time.sleep(0.9)                     # 하위 메뉴 열림 대기
                continue
            seen = r2.get("seen") or seen
            break
        cdp.eval("(function(){document.body.click();return 1;})()")   # 메뉴 닫기
        hint = (" · 메뉴: " + ", ".join(seen)) if seen else ""
        return f"모델 '{model}' 항목 없음 — 기본 모델 사용{hint}"
    except Exception as e:
        return f"모델 선택 실패({type(e).__name__}) — 기본 모델 사용"


def js_focus(cfg):
    """입력창을 찾아 포커스만 준다 — 실제 주입은 CDP Input.insertText가 정석
    (React/Lexical류 리치 에디터는 execCommand/DOM 조작을 무시하는 경우가 많음)"""
    sels = json.dumps(cfg["inputSelectors"])
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>40&&r.height>8;};
  let el=null,sel='';
  for(const s of """ + sels + """){
    for(const c of document.querySelectorAll(s)){ if(vis(c)&&!c.disabled){el=c;sel=s;break;} }
    if(el)break;
  }
  if(!el)return {ok:false,err:'input_not_found'};
  el.focus();
  window.__lm_input=el;
  return {ok:true,tag:el.tagName,sel:sel};
})()""")


def js_editor_text():
    return ("(function(){const el=window.__lm_input;if(!el)return '';"
            "return el.value!==undefined&&el.tagName!=='DIV'?el.value:(el.innerText||el.textContent||'');})()")


def js_insert_fallback(prompt):
    """Input.insertText가 안 먹은 경우의 예비: execCommand → 값 직접 설정 + input 이벤트"""
    p = json.dumps(prompt)
    return ("""(function(){
  const el=window.__lm_input; if(!el)return {ok:false};
  el.focus();
  const p=""" + p + """;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){
    const d=Object.getOwnPropertyDescriptor(el.__proto__,'value');
    if(d&&d.set){d.set.call(el,p);}else{el.value=p;}
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }else{
    let done=false;
    try{done=document.execCommand('insertText',false,p);}catch(e){}
    if(!done){
      el.textContent=p;
      el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:p}));
    }
  }
  return {ok:true};
})()""")


def js_click_send(cfg):
    sels = json.dumps(cfg["sendSelectors"])
    return ("""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  for(const s of """ + sels + """){
    for(const b of document.querySelectorAll(s)){
      if(vis(b)&&!b.disabled){b.click();return {ok:true,sel:s};}
    }
  }
  return {ok:false};
})()""")


def press_enter(cdp):
    for t, key in (("rawKeyDown", None), ("char", "\r"), ("keyUp", None)):
        params = {"type": t, "key": "Enter", "code": "Enter",
                  "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13}
        if key:
            params["text"] = key
        cdp.call("Input.dispatchKeyEvent", params)


def js_diagnose():
    return """(function(){
  const info=el=>{const r=el.getBoundingClientRect();
    return {tag:el.tagName,visible:r.width>0&&r.height>0,w:Math.round(r.width),
      aria:el.getAttribute('aria-label')||'',testid:el.getAttribute('data-testid')||'',
      role:el.getAttribute('role')||'',ph:el.getAttribute('placeholder')||''};};
  return {url:location.href,title:document.title,
    editors:[...document.querySelectorAll("[contenteditable],[role='textbox'],textarea,input")].slice(0,10).map(info),
    buttons:[...document.querySelectorAll('button')].filter(b=>{const r=b.getBoundingClientRect();return r.width>0;}).slice(0,40).map(info)};
})()"""


# Copilot 일시 오류 응답 — 이 문구가 오면 내용이 아니라 서비스 상태 문제다 (실측 스크린샷)
# '다시 시도' 단독은 정상 분석문에 인용될 수 있어 트리거에서 제외 — 서비스 오류를
# 단정할 수 있는 정형 문구만 쓴다 (스크린샷 문구는 '응답할 수 없습니다'로 잡힌다)
ERROR_REPLY_MARKS = ("응답할 수 없습니다", "응답 할 수 없습니다", "문제가 발생했",
                     "무언가 잘못", "죄송합니다. 지금은",
                     "sorry, i can't respond", "something went wrong", "can't respond right now")


def is_error_reply(reply):
    """짧고 정형화된 오류 문구인지 — 정상 분석문에 인용된 경우를 배제하려고
    길이(500자 미만)와 앞부분(300자) 매칭을 함께 본다."""
    r = (reply or "").strip()
    if not r or len(r) > 500:
        return False
    head = r[:300].lower()
    return any(m.lower() in head for m in ERROR_REPLY_MARKS)


# Copilot 사용량 제한(일시) 문구 — 오류 문구와 달리 **즉시 다시 보내면 제한이 길어진다**(새 채팅·자동 모델 사다리를 타지 않는다).
# 정확한 회사 문구는 아직 실측 전이라 넓게 잡되, 짧은 산문(600자 이하·JSON 없음)의 앞 400자에서만 찾는다(분석문 인용 배제).
# 현장 실측 문구(LM28): "현재 요청이 너무 많아 일시적으로 응답할 수 없습니다. 나중에 다시 시도하세요." — '응답할 수 없습니다' 는 오류
# 문구(ERROR_REPLY_MARKS)이기도 하므로 어디서나 제한 판정을 먼저 한다(오류면 새 채팅 사다리로 곧장 다시 보내 제한이 길어진다).
THROTTLE_REPLY_MARKS = ("한도에 도달", "한도를 초과", "사용 한도", "사용량 한도", "메시지 한도", "요청이 너무 많", "너무 많은 요청",
                        "일시적으로 응답할 수 없", "잠시 후 다시 시도", "잠시 후에 다시 시도", "잠시 뒤 다시 시도",
                        "잠시 뒤에 다시 시도", "나중에 다시 시도", "잠시 기다린 후", "수요가 많", "reached the limit",
                        "reached your limit", "usage limit", "rate limit", "too many requests", "too many messages",
                        "lot of requests right now", "high volume of requests", "temporarily unable to respond",
                        "try again later", "try again in a few minutes", "try again in a little while",
                        "limit for now", "temporarily unavailable", "high demand", "throttl")
THROTTLE_SETTLE_SEC = 5        # 답을 기다리는 동안 제한 후보 글이 이만큼 그대로면 돌려준다(생성 중이 아닐 때)
THROTTLE_BUSY_SEC = 30         # '중지' 버튼이 아직 보이면 이만큼 그대로일 때만(버튼이 멈춘 화면 — 끝없이 기다리지 않게)
NOTICE_MAX = 12                # 한 번에 읽는 알림 수 상한


def is_throttle_reply(reply):
    """답이 사용량 제한 문구인가 — 비어 있지 않고 600자 이하·'{' 없음, 앞 400자에 표식 문구."""
    r = (reply or "").strip()
    if not r or len(r) > 600 or "{" in r:
        return False
    head = r[:400].lower()
    return any(m.lower() in head for m in THROTTLE_REPLY_MARKS)


def js_notices():
    """화면에 보이는 알림·상태 영역의 글(600자 이하만, 최대 NOTICE_MAX) — 사용량 제한이 답 말풍선 대신 알림(토스트·배너·
    role=alert·aria-live)으로 뜨는 화면용(그때는 답 자리가 비어 firstTokenSec·사다리를 다 기다렸다). 숨은 읽기 전용 영역은 뺀다."""
    return r"""/*LM28:notices*/(function(){
  const sel="[role='alert'],[role='alertdialog'],[role='status'],[aria-live='assertive'],[aria-live='polite'],"+
    "[class*='toast' i],[class*='messagebar' i],[class*='notification' i],[class*='banner' i],[data-testid*='toast' i],"+
    "[data-testid*='error' i]";
  const vis=el=>{const r=el.getBoundingClientRect(); if(r.width<=4||r.height<=4)return false;
    const s=getComputedStyle(el); return s.visibility!=="hidden"&&s.display!=="none"&&parseFloat(s.opacity||"1")>0.05;};
  const out=[], seen=new Set(); let els=[];
  try{els=[...document.querySelectorAll(sel)];}catch(e){return out;}
  for(const el of els){ if(out.length>=12)break; if(!vis(el))continue;
    const t=(el.innerText||"").trim(); if(!t||t.length>600||seen.has(t))continue; seen.add(t); out.push(t);}
  return out;})()"""


def _notices(cdp):
    """보이는 알림 글 목록 — 못 읽으면 None(평가 실패) · 이상한 값이면 []."""
    try:
        r = cdp.eval(js_notices(), timeout=10)
    except (TimeoutError, OSError, RuntimeError):
        return None
    if not isinstance(r, list):
        return []
    return [str(x).strip() for x in r if isinstance(x, str) and str(x).strip()][:NOTICE_MAX]


def _new_notice(cdp, pre, prompt):
    """보낸 뒤 새로 뜬 알림 중 사용량 제한 문구(is_throttle_reply — 짧은 산문·JSON 없음·머리에 표식)인 것 → 그 글 · 없으면 "".
    보내기 전에 이미 떠 있던 알림(pre)과 우리가 보낸 글의 일부(대화 영역이 aria-live 인 화면의 내 말풍선)는 보지 않는다."""
    old, ptxt = set(pre or ()), str(prompt or "")
    for t in _notices(cdp) or ():
        if t in old or t in ptxt:
            continue
        if is_throttle_reply(t):
            return t
    return ""


def _throttle_settled(n, gen, busy_seen, poll):
    """사용량 제한 후보 글이 n 폴째 그대로다 → 이제 돌려줘도 되는가. 앞부분만 보인 정상 답(산문 머리 뒤에 JSON 이 올 수 있다)을
    집지 않으려고 바로는 돌려주지 않는다: '중지' 버튼을 본 뒤 사라졌으면(생성 끝) 한 폴 확인, 생성 중이 아니면 THROTTLE_SETTLE_SEC,
    버튼이 아직 보이면 THROTTLE_BUSY_SEC 그대로일 때만."""
    held = n * max(0.5, float(poll or 2))
    if gen is True:
        return held >= THROTTLE_BUSY_SEC
    if busy_seen and gen is False:
        return n >= 1
    return held >= THROTTLE_SETTLE_SEC


def _throttled(cfg, reply=""):
    """사용량 제한 결과 dict — 기록(note_throttle)을 남기고 사다리 없이 돌려준다."""
    note_throttle(cfg)
    return {"ok": False, "phase": "throttled", "reason": R_THROTTLE, "error": "Copilot 사용량 제한(일시)",
            "hint": _hint(R_THROTTLE, cfg), "reply": str(reply or "")[:300]}


# 생성이 중간에 끊긴 답 — 생성 중에 전송 버튼을 누르면(그때는 '중지' 버튼이다) Copilot 이 남기는 정형
# 문구(실측 "OK, I've stopped generating the response."). 오류 응답과 달리 **앞부분에 정상 답(잘린 JSON)이
# 붙어 있을 수 있어** 꼬리에서 찾고, 호출자가 잘린 JSON 을 복구해 쓸 수 있게 ok 는 유지한 채 cut 표식만 단다.
CUT_REPLY_MARKS = ("i've stopped generating", "stopped generating the response", "stopped generating",
                   "응답 생성을 중지", "응답 생성을 중단", "생성을 중지했", "생성이 중지되", "생성을 중단했")


def is_cut_reply(reply):
    """답의 꼬리(300자)에 '생성 중단' 문구가 있는가."""
    tail = (reply or "").strip()[-300:].lower()
    return bool(tail) and any(m in tail for m in CUT_REPLY_MARKS)


def js_is_generating():
    """아직 답을 쓰는 중인가 — 전송 자리에 '중지' 버튼이 떠 있으면 생성 중이다.
    UI 표기가 바뀌어도 죽지 않게 후보 문구를 넓게 잡고, 못 찾으면 '생성 중 아님'(진행)."""
    return r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const b=[...document.querySelectorAll("button")].filter(vis).find(e=>{
    const t=((e.getAttribute("aria-label")||"")+" "+(e.getAttribute("title")||"")).toLowerCase().trim();
    return t.includes("생성 중지")||t.includes("응답 중지")||t.includes("stop generating")||
           t.includes("stop responding")||t==="stop"||t==="중지";});
  return !!b;})()"""


def wait_idle(cdp, secs=45):
    """앞 답의 생성이 끝날 때까지 기다린다(최대 secs). 생성 중에 다음 프롬프트를 보내면 전송 버튼이
    '중지'라 클릭이 **앞 답을 끊고**(잘린 JSON) 새 프롬프트는 입력창에 남는다(실측) — 큰 사람(청크 20개
    이상)에서 연속 실패의 시작점이었다. returns 기다린 초(0 = 바로 진행)."""
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            if not cdp.eval(js_is_generating()):
                break
        except (TimeoutError, RuntimeError, OSError):
            break
        time.sleep(2)
    return round(time.time() - t0, 1)


# ── LM28 — 느린 긴 답(현장 제보: 워크플로우 단계의 긴 JSON) ─────────────────────────────────────────────────────────────
# 예전에는 replyTimeoutSec 가 고정 마감이었다 — 답이 아직 자라는 중이어도 no_reply 로 돌려, 같은 프롬프트를 새 채팅에 두 번(사다리 ①②)
# 더 보내고 judge 의 쉬기 사다리가 또 보냈다. Copilot 은 그 답들을 뒤에서 끝까지 써, 사람의 대화 목록에는 다 쓴 답이 든 채팅이
# 여럿 남고 우리 실행은 '시간 초과' 였다. 이제 replyTimeoutSec 는 기본 마감이고, 그때 답이 살아 있으면(아래) 왕복 예산(roundtripMaxSec)
# 끝까지 더 기다린다. 예산 끝에도 쓰는 중이면 입력창의 '중지' 단추(정확한 이름 하나)만 눌러 끊고 받은 데까지를 ok+cut+slow 로
# 돌려준다 — 호출자는 완전한 항목만 쓰고 빠진 것만 더 작게 다시 묻는다(같은 프롬프트를 다시 보내지 않는다).
SLOW_ALIVE_SEC = 90            # 답 몸통이 이 안에 SLOW_GROW_CHARS 자 이상 자랐으면 '살아 있음'
SLOW_ALIVE_BUSY_SEC = 180      # '중지' 버튼이 보이면 이만큼 안에 자랐어도 살아 있음(긴 생각 사이의 멈춤)
SLOW_GROW_CHARS = 20           # 이보다 적게 는 것은 자란 것으로 치지 않는다(상대 시각·'편집됨' 같은 화면 잡음)
SLOW_NOTE_SEC = 60             # 연장 중 진행 줄 간격(초) — 단계 감시기가 산 것으로 본다
SLOW_MARGIN_SEC = 10           # 왕복 마감 직전 여유 — '중지'를 누르고 마지막 글을 읽을 몫
SLOW_CAP_SEC = 900             # 왕복 예산이 꺼진(roundtripMaxSec 0) 경우 기본 마감 뒤 연장 상한
# 누를 수 있는 '중지' 단추 이름 — js_is_generating 의 후보 문구 그대로(정확히 같을 때만 · 대소문자·공백 무시). 다른 단추는 보지 않는다.
STOP_LABELS = ("중지", "생성 중지", "응답 중지", "응답 생성 중지", "stop", "stop generating", "stop responding")


def js_stop_button():
    """입력창의 생성 '중지' 단추 하나 → {r: ok · none · many · covered, x, y}(글은 돌려주지 않는다). aria-label → title → 보이는 글 순으로
    한 이름만 보고 STOP_LABELS 와 **정확히** 같을 때만 후보다. 메뉴·대화상자·대화 목록(nav·aside·listbox) 안의 단추는 보지 않는다.
    후보가 둘 이상이거나 그 점에 다른 요소가 있으면 누르지 않는다."""
    return ("/*LM28:stop_btn*/(function(){\nconst WANT=" + json.dumps(list(STOP_LABELS), ensure_ascii=False) + ";" + r"""
const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const PUA=new RegExp("["+String.fromCharCode(57344)+"-"+String.fromCharCode(63743)+"]","g");   // 아이콘 글꼴 문자
const nrm=s=>(s||"").replace(PUA,"").replace(/\s+/g," ").trim().toLowerCase();
const OUT="[role='menu'],[role='menubar'],[role='dialog'],[role='alertdialog'],[role='tooltip'],[role='listbox'],nav,aside,[role='navigation']";
let hs=[];
for(const b of document.querySelectorAll("button,[role='button']")){
  if(!vis(b)||b.closest(OUT))continue;
  const n=nrm(b.getAttribute("aria-label"))||nrm(b.getAttribute("title"))||nrm(b.textContent);
  if(WANT.includes(n))hs.push(b);}
hs=hs.filter((x,i)=>hs.indexOf(x)===i&&!hs.some(y=>y!==x&&x.contains(y)));
if(!hs.length)return {r:"none"};
if(hs.length>1)return {r:"many",n:hs.length};
const q=hs[0].getBoundingClientRect(),x=Math.round(q.left+q.width/2),y=Math.round(q.top+q.height/2);
const h=document.elementFromPoint(x,y);
if(!(h&&(h===hs[0]||hs[0].contains(h))))return {r:"covered"};
return {r:"ok",x:x,y:y};
})()""")


def _stop_generation(cdp):
    """왕복을 접는 순간 아직 생성 중이면(js_is_generating) 입력창의 '중지' 단추 하나(js_stop_button — 정확한 이름)만 신뢰 마우스로 누른다
    → 눌렀으면 True. 생성 중이 아니거나 단추를 하나로 못 정하면 아무것도 누르지 않는다(False — 그때는 Copilot 이 뒤에서 마저 쓴다).
    끊어 두는 까닭: 뒤에서 다 쓴 답이 사람의 대화 목록에 남고, 생성 중인 채팅은 정리(삭제)도 하지 않는다('gen')."""
    try:
        if cdp.eval(js_is_generating(), timeout=10) is not True:
            return False
        r = cdp.eval(js_stop_button(), timeout=10)
        if not (isinstance(r, dict) and r.get("r") == "ok"):
            return False
        _chat_mouse(cdp, r.get("x"), r.get("y"))
    except Exception:  # noqa: BLE001 - 못 누르면 그대로 둔다(왕복 결과는 받은 데까지)
        return False
    _sleep(1.5)                                # 끊긴 뒤 화면 글('응답을 중지했습니다')이 붙을 시간
    return True


def _slow_note(waited, left, chars):
    """연장 대기 중 진행 한 줄(stderr — stdout 은 결과 JSON 한 건 계약 · 단계 프로세스는 stderr 도 감시기에 간다). 글은 싣지 않는다."""
    try:
        print(f"[copilot_auto] 답이 길어 Copilot 이 아직 쓰는 중입니다 — 기다린 지 {waited / 60:.0f}분 · 지금 {int(chars):,}자 · "
              f"왕복 예산 안에서 최대 {max(0.0, left) / 60:.0f}분 더 기다립니다(같은 질문을 다시 보내지 않습니다)",
              file=sys.stderr, flush=True)
    except (OSError, ValueError, UnicodeEncodeError):
        pass


def js_new_chat():
    return r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const cands=[...document.querySelectorAll("button,a")].filter(vis).filter(e=>{
    const t=((e.getAttribute("aria-label")||"")+" "+(e.innerText||"")).toLowerCase();
    return t.includes("새 채팅")||t.includes("새 대화")||t.includes("new chat");});
  if(!cands.length)return {ok:false};
  cands[0].click();
  return {ok:true,label:(cands[0].getAttribute("aria-label")||cands[0].innerText||"").slice(0,30)};
})()"""


def new_chat(cdp, cfg):
    """새 채팅으로 전환 — 버튼을 찾으면 클릭, 없으면 채팅 URL 재진입(새 대화로 열림).
    **같은 탭에서** 한다(새 탭·새 창을 만들지 않는다). 전환 뒤 탭을 다시 앞으로 올린다."""
    activate(cdp)
    try:
        r = cdp.eval(js_new_chat()) or {}
        if r.get("ok"):
            time.sleep(3)
            activate(cdp)
            return "새 채팅 버튼"
    except Exception:
        pass
    try:
        cdp.eval("(function(){location.href=" + json.dumps(cfg["url"]) + ";return 1;})()")
        for _ in range(8):               # 준비되면 즉시 탈출 — 실패 왕복마다 20초를 세 번 세던 것을 줄인다(제보 ④)
            time.sleep(1)
            st = cdp.eval(js_state())
            if st and st.get("ready") in ("interactive", "complete"):
                break
        time.sleep(1)
        return "URL 재진입"
    except Exception:
        return "실패"


def reload_page(cdp, cfg, wait=15):
    """채팅 주소로 다시 들어간다(페이지 새로 고침 — 같은 탭). 몇 시간 이어 쓴 탭(만료된 페이지 토큰·커진 대화 DOM)은 새 채팅
    버튼만으로는 실패가 이어졌다(LM28 진단 A). 준비될 때까지 최대 wait 초 기다린다 — 로그인이 풀렸으면 다음 page_gate 가
    login_required 로 드러낸다."""
    activate(cdp)
    try:
        cdp.call("Page.navigate", {"url": cfg["url"]}, timeout=20)
    except (TimeoutError, RuntimeError, OSError):
        return "실패"
    end = time.time() + max(1.0, min(float(wait), _dl_left(wait)))
    for _ in range(int(wait) + 1):
        _sleep(1)
        try:
            st = cdp.eval(js_state()) or {}
        except (TimeoutError, RuntimeError, OSError):
            st = {}
        if st.get("ready") in ("interactive", "complete") or time.time() > end:
            break
    activate(cdp)
    return "새로 고침"


# ── LM28 — Copilot 채팅 정리: LM28 이 연 대화만, 다 쓴 때에 지운다 ─────────────────────────────────────────────────────
# 제보: 프로세스마다 첫 왕복·chatTurns 회전·실패 사다리(새 채팅 2번)·월별 코멘트(달마다 새 채팅)·Copilot 메일/팀즈 조각·
# [AI 연결 진단]이 저마다 새 대화를 열어 사람의 Copilot 대화 목록이 LM28 채팅으로 도배됐다. 월별 코멘트는 여전히 달마다 새 채팅이다
# (문맥 분리 — 한 채팅에 이어 묻던 때 다른 달의 내용이 섞여 든 현장 제보). LM28(2026-10-17): Copilot 메일·일정·팀즈 수집기는 이제 조각마다
# 새 채팅을 열지 않고 한 채팅을 이어 쓴다(ChatKeep — 첫 조각·나쁜 조각 뒤·chatTurns 마다만 새 채팅). 그래도 여는 대화는 LM28 이 다 쓴
# 때(다음 새 채팅 직전 · 실행 끝 Edge 를 닫기 전)에 대화 목록에서 지운다. 판정·정제·Agentic·워크플로우·수집기가 같은 탭을 차례로 쓰는 다른 프로세스라 소유는
# <프로필>.chats.json 이 기억한다(edge_lock 안에서만 고친다 · 원자적 교체):
#   {ours, sent, anchor_sha, alen, hsha, hlen, tpre, conv, href, pid, created_at, stage, t_last,
#    totals: {made, deleted, kept, failed, why{사유: 수}, last{code, t}, last_fail, last_fail_t, hold{rev, t}, census}}
#   · 우리 것 = LM28 이 새 채팅을 열고(_fresh_chat — 주소의 대화 id 가 열기 전과 같으면 새 채팅이 아니다) 거기에 보낸 대화. 남이 연
#     대화에 이어 보낸 것은 끝까지 우리 것이 아니다. 프롬프트 원문은 남기지 않는다 — 마지막 프롬프트의 끝 앵커(build_anchor, 공백 정리)와
#     머리 앵커(첫 줄 앞 60자 — head_key)의 sha1·길이, 첫 프롬프트 앞부분 8~64자의 길이별 해시(tpre — title_prefixes · 목록 제목 확인용 ·
#     새 채팅에서만 생기고 이어 보내도 그대로), 답 뒤 주소의 대화 id 만(href 는 경로까지 — 질의·# 없음).
#   · 지우기(retire_chat → _retire_steps) — 하나라도 아니면 아무것도 누르지 않고(누른 뒤면 Esc) '남김'으로 센다:
#     설정 켬 · 멈춤 아님 · 보낸 적 있음 → 화면 글에 우리 앵커(끝 앵커 또는 머리 앵커 — 긴 질문을 접어 첫 줄만 보이는 화면) → 주소의
#     대화 id 가 우리가 본 id 와 같음 → tpre 있음(없으면 예전 판이 연 채팅 — 'notitle') → 대화 목록에서 지금 대화의 항목이 하나(링크
#     주소에 id · '현재' 표시 — 둘 다 찾으면 같은 항목) → 그 항목의 제목(첫 줄 · 끝 '…' 뗌)이 첫 프롬프트의 앞부분과 같음(해시 — 다르면
#     'notitle') → 그 항목 위에 신뢰 마우스 → 그 항목 안 '추가 작업(…)'(제목을 한 번 더 확인) → 메뉴에서 글자가 정확히 '삭제'인 항목 →
#     확인 창에서 글자가 정확히 '삭제'인 단추(창이 안 뜨면 메뉴가 끝) → 확인: 두 앵커가 모두 화면에서 사라짐 · 또는 대화 id 가 바뀜 ·
#     또는 화면은 그대로인데 목록 항목 수와 제목이 맞는 항목 수가 둘 다 딱 1 줄어듦(메뉴를 열기 전에 센 수 — js_chat_count) · 또는 링크로
#     찾은 항목이 목록에서 사라짐. 눌렀는데도 확인되지 않으면(mismatch) 다른 대화를 지웠을 수 있다 — 이 프로세스는 더 지우지 않고
#     (_CHAT_KILL) 상태 파일에 멈춤(hold)을 남겨 다른 프로세스도 CHAT_REV 판이 바뀔 때(새 배포)까지 지우지 않는다.
#   · 목록이 접혀 있으면(현장 사진: 125~150% 배율의 1150px 전용 Edge — 좁은 배치라 대화 기록이 서랍으로만 열려 하나도 지우지 못했다)
#     항목을 찾기 전에 길만 연다(무엇을 지울지는 정하지 않는다 — _chat_find): 대화 기록 펼침 단추 1번 → 탐색 창 단추(이름이 탐색·사이드·
#     패널·확장 … 이고 하나뿐일 때) 1번 → 넓은 화면 흉내(CDP Emulation 폭 1600 — _chat_wide) 뒤 다시 보고, 그래도 없으면 그 화면에서
#     두 단추를 한 번씩 더. 넓은 화면은 정리가 어떻게 끝나든(예외·이른 반환 포함) retire_chat 의 finally 가 되돌린다(_chat_unwide).
#   · 왕복마다 지우지 않는다 — chatTurns 안의 이어 보내기는 그 대화의 문맥에 기댄다.
#   · 기록은 숫자·사유 코드만(copilot_trace 의 stage 'chat' · last_run 'Copilot 채팅 정리' · 단계 로그 '[copilot] 채팅 정리:').
CHATS_FILE = ".chats.json"
CHAT_RETIRE_SEC = 25           # 정리 한 번의 상한(초) — 넘기면 'timeout' 으로 남기고 하던 일을 계속한다
CHAT_LOCK_WAIT = 15            # 실행 끝 정리가 잠금을 기다리는 상한(초) — 다른 작업이 Edge 를 쓰면 정리를 미룬다(busy)
CHAT_PENDING_SEC = 7200        # 열고 아직 보내지 않은 '우리 채팅' 표시가 유효한 시간(초 — 연 프로세스 안에서만 믿는다)
CHAT_REV = 2                   # 화면 조작 규칙의 판 — mismatch 로 멈춘 삭제는 이 판이 바뀔 때까지 멈춘다.
#                                2(LM28 2026-10-17): 화면 규칙이 바뀌었다(목록 제목 확인 · 접힌 목록 열기 · 머리 앵커 · 목록 셈으로 확인) —
#                                판 1 에서 남은 멈춤(hold rev 1)은 풀린다(새 규칙으로 다시 해 본다)
CHAT_LINE_HEAD = "[copilot] 채팅 정리: "     # 단계 로그 한 줄의 머리 — run.py 가 실패 사유 줄로 오인하지 않게 이 머리로 거른다
CHAT_DELETE_LABELS = ("삭제", "대화 삭제", "채팅 삭제", "delete", "delete chat", "delete conversation")   # 메뉴 항목(정확히)
CHAT_CONFIRM_LABELS = ("삭제", "delete")      # 확인 창 단추(정확히) — '취소'·'닫기' 는 보지도 않는다
CHAT_FAIL = frozenset({"noitem", "ambiguous", "covered", "nomore", "nomenu", "nodelete", "noconfirm", "mismatch",
                       "error", "timeout", "notitle"})  # 화면 조작이 막힌 사유(실패) — 그 밖의 '남김'은 설정·소유 사유
CHAT_WHY = {
    "deleted": "지움", "off": "설정으로 끔", "hold": "삭제 멈춤(지난번 확인 실패)", "lost": "화면이 다른 대화로 바뀜",
    "noanchor": "확인용 줄이 없는 프롬프트", "replaced": "정리 전에 새 채팅이 열림", "noitem": "대화 목록에서 못 찾음",
    "ambiguous": "대화 목록에서 하나로 못 정함", "covered": "다른 창에 가려 누르지 못함", "nomore": "'추가 작업(…)' 단추 없음",
    "nomenu": "메뉴가 열리지 않음", "nodelete": "메뉴에 '삭제' 없음", "noconfirm": "확인 창에 '삭제' 단추 없음",
    "mismatch": "지운 뒤에도 채팅이 화면에 남음", "error": "화면 조작 오류", "timeout": "시간 초과",
    "busy": "다른 작업이 전용 Edge 를 쓰는 중", "notab": "Copilot 탭 없음", "noedge": "전용 Edge 꺼짐",
    "gen": "답을 쓰는 중이라 남김", "notitle": f"목록 항목의 제목이 {lmname.SHORT} 이 보낸 질문과 달라 남김",
}
# LM28 — 화면 사유로 남겼을 때(아래 코드) 대화 목록의 '구조'를 숫자·0/1 로만 센다(js_chat_census — 제목·글·주소·id 없음). 단계 로그에
# 'CHAT_CENSUS_HEAD …' 한 줄(chat_line 의 둘째 줄)·copilot_trace·상태 파일 totals.census 에 남는다 — 현장 사진 한 장으로 왜 못 지웠는지
# (목록이 접혔나·링크에 대화 id 가 있나·'현재' 표시가 있나) 알 수 있게. 삭제 판정은 바꾸지 않는다(조사는 읽기만).
# LM28(2026-10-17): 'notitle'(제목이 다름)도 조사한다 · _retire_steps 가 적은 표시(CENSUS_CTX_KEYS — 넓은 화면 흉내·탐색 창 단추·제목 일치,
# 숫자만)를 함께 싣는다.
CHAT_CENSUS_CODES = frozenset({"noitem", "ambiguous", "covered", "nomore", "nomenu", "nodelete", "noconfirm", "timeout",
                               "notitle"})
CHAT_CENSUS_HEAD = "[copilot] 채팅 정리 구조: "   # run.py CHAT_LINE_HEAD('[copilot] 채팅 정리')로 시작 — 실패 사유 줄로 집지 않는다
CENSUS_TEXT = (("nnav", "탐색 창"), ("navw", "탐색 창 너비"), ("fold", "탐색 창 접힘 추정"), ("nreg", "목록 영역"),
               ("nrow", "목록 항목"), ("nlink", "목록 링크"), ("nid", "대화 id 꼴 링크"), ("nhc", "이 대화 id 링크"),
               ("nhcv", "그중 목록에 보임"), ("ncur", "현재 표시"), ("ncurv", "그중 목록 안"), ("nsel", "선택 표시"),
               ("nselv", "그중 목록 안"), ("ntgc", "접힌 목록 단추"), ("ntgo", "펼친 목록 단추"), ("nmore", "목록의 메뉴 단추"),
               ("nmenu", "열린 메뉴"), ("ndlg", "열린 대화상자"), ("gen", "답 쓰는 중"), ("cid", "주소에 대화 id"),
               ("wide", "넓은 화면으로 바꿔 봄"), ("navtg", "탐색 창 단추 누름"), ("tm", "제목 일치"))
CENSUS_JS_KEYS = ("nnav", "navw", "nreg", "nrow", "nlink", "nid", "nhc", "nhcv", "ncur", "ncurv", "nsel", "nselv",
                  "ntgc", "ntgo", "nmore", "nmenu", "ndlg")
CENSUS_CTX_KEYS = ("wide", "navtg", "tm")     # 화면 JS 가 아니라 _retire_steps 가 ctx 에 적는 표시(숫자) — 구조 조사·copilot_trace 에 싣는다
CHAT_WIDE_W = 1600             # 넓은 화면 흉내의 폭(CSS px) — 이만큼 넓으면 Copilot 이 대화 목록을 펼친 배치로 그린다(_chat_wide)
# LM28 — 다음 단계(정제·Agentic·워크플로우)의 첫 왕복은 앞 단계의 우리 채팅을 이어 쓸 수 있다(새 채팅을 덜 연다). 상태 파일이 우리 것 ·
# 마지막 왕복 온전(last_ok) · 이만큼 안(t_ok) · 보낸 수 < chatTurns 이고, 보내기 직전 화면이 그 채팅(앵커·대화 id)이며 생성 중이 아닐 때만.
# 소유 기록은 그대로다 — 이어 보낸 프롬프트는 _chat_before_send/_chat_after_send 가 같은 규칙으로 센다(만든 채팅 수는 늘지 않는다).
CHAT_RESUME_SEC = 1200
RESUME = "resume"              # fresh 자리의 값(judge.copilot_send → send_inproc) — 화면이 우리 채팅일 때만 이어 쓰고, 아니면 새 채팅
_RESUMED = [None]              # 이번 _send 에서 RESUME 이 실제로 이어 썼나(None = RESUME 아님) — 결과의 resumed
_CHAT_KILL = [False]           # 이 프로세스의 삭제 멈춤(mismatch 뒤 — 더 지우지 않는다)
# 이 프로세스 몫(단계 로그 한 줄 — chat_line). notfresh = 새 채팅을 열었는데 주소의 대화 id 가 그대로라 맡지 않은 수(우리 것 아님 —
# 남김에 넣지 않는다. 현장 주소 꼴이 예상과 다르면 여기가 커진다 — 사진으로 안다)
_CHAT_PROC = {"made": 0, "deleted": 0, "kept": 0, "failed": 0, "notfresh": 0, "why": {}}
# 대화 id 꼴 토큰 — GUID, 또는 숫자·영문이 섞인 16자 이상(영숫자·_·-). 채팅 시작 주소의 경로 뒤·# 조각·대화 계열 질의 값에서만 찾는다
_CONV_TOKEN = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
                         r"|(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}")


def _chat_on(cfg):
    """copilotAuto.deleteChats — 기본 켬. false·"false"·0·"off"·"no" 면 끔."""
    return _truthy((cfg or {}).get("deleteChats"), True)


def _chats_path(cfg):
    return _side_path(cfg, CHATS_FILE)


def chat_state(cfg=None):
    """<프로필>.chats.json(채팅 소유·누계) — 없거나 깨졌으면 {}."""
    cfg = cfg if isinstance(cfg, dict) else load_cfg()
    try:
        with open(_chats_path(cfg), encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def _chats_save(cfg, st):
    return _write_json(_chats_path(cfg), st)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _age_sec(ts):
    try:
        return max(0.0, time.time() - time.mktime(time.strptime(str(ts or "")[:19], "%Y-%m-%d %H:%M:%S")))
    except (ValueError, OverflowError):
        return float(10 ** 9)


def _chat_held(st):
    """상태 파일의 삭제 멈춤(mismatch)이 지금 판(CHAT_REV)의 것인가."""
    h = ((st or {}).get("totals") or {}).get("hold") if isinstance((st or {}).get("totals"), dict) else None
    return isinstance(h, dict) and h.get("rev") == CHAT_REV


def _chat_reset(st):
    """소유 칸만 비운다(누계 totals 는 둔다) → 같은 dict."""
    tot = st.get("totals") if isinstance(st.get("totals"), dict) else {}
    st.clear()
    st.update(ours=False, sent=0, totals=tot)
    return st


def _chat_tally(st, code):
    """한 건 세기 — 누계(st['totals'])와 이 프로세스 몫(_CHAT_PROC). made·deleted·notfresh(맡지 않은 새 채팅 — 우리 것이 아니라
    남김에 넣지 않는다)는 그 칸, 그 밖의 코드는 '남김'(kept · why[코드])이고 화면 조작이 막힌 사유(CHAT_FAIL)면 failed 도.
    설정으로 끈 것(off)은 남긴 까닭(last_fail)으로 적지 않는다."""
    tot = st.get("totals")
    if not isinstance(tot, dict):
        tot = st["totals"] = {}
    for d in (tot, _CHAT_PROC):
        if code in ("made", "deleted", "notfresh"):
            d[code] = int(d.get(code) or 0) + 1
            continue
        d["kept"] = int(d.get("kept") or 0) + 1
        w = d.get("why") if isinstance(d.get("why"), dict) else {}
        w[code] = int(w.get(code) or 0) + 1
        d["why"] = w
        if code in CHAT_FAIL:
            d["failed"] = int(d.get("failed") or 0) + 1
    if code in ("made", "notfresh"):
        return
    tot["last"] = {"code": code, "t": _now()}
    if code not in ("deleted", "off"):
        tot["last_fail"], tot["last_fail_t"] = code, _now()


def conv_id(url, cfg=None):
    """채팅 주소 → 대화 id 꼴 토큰 — 채팅 시작 주소(cfg.url) 경로 뒤·# 조각·대화 계열 질의 값(conv·thread·chatid)에서. 없으면 "".
    새 채팅(시작 주소)에는 id 가 없다. 화면 글·제목은 보지 않는다."""
    try:
        p = urlparse(str(url or ""))
        base = (urlparse(str((cfg or {}).get("url") or DEFAULTS["url"])).path or "").rstrip("/")
    except ValueError:
        return ""
    if not p.hostname:
        return ""
    path = p.path or ""
    if base and path.lower().startswith(base.lower()):
        path = path[len(base):]
    toks = [m.group(0) for m in _CONV_TOKEN.finditer(path + " " + (p.fragment or ""))]
    for k, v in parse_qsl(p.query or ""):
        if re.search(r"conv|thread|chatid", k, re.I):
            toks += [m.group(0) for m in _CONV_TOKEN.finditer(v)]
    return toks[-1] if toks else ""


def _plain_href(url):
    """저장용 주소 — 질의·# 조각을 뺀 scheme://host/path."""
    try:
        p = urlparse(str(url or ""))
    except ValueError:
        return ""
    return f"{p.scheme}://{p.hostname}{p.path}" if p.hostname else ""


def anchor_key(prompt):
    """채팅 소유 확인용 앵커 → (sha1, 길이) — build_anchor(개행 없는 한 줄의 끝 100자 이내)의 공백을 한 칸으로 줄인 것. 원문은
    돌려주지 않는다(상태 파일에는 해시만 남는다). 20자 미만이면 ("", 0) — 짧은 줄은 남의 대화에도 있을 수 있다."""
    a = re.sub(r"\s+", " ", build_anchor(prompt)).strip()
    if len(a) < 20:
        return "", 0
    return hashlib.sha1(a.encode("utf-8")).hexdigest(), len(a)


def page_has_anchor(text, sha, alen):
    """화면 글에 우리 앵커가 있는가 — 해시로만 비교한다. 줄(공백 정리)의 끝 alen 자 → 없으면 같은 길이의 모든 창(줄 앞뒤에 다른
    글이 붙어 그려진 경우 — 이름표·시각). 앵커에는 개행이 없으므로 줄을 넘는 창은 보지 않는다(뒤 60만 자까지)."""
    try:
        n = int(alen or 0)
    except (TypeError, ValueError):
        return False
    if not sha or n < 20 or not isinstance(text, str) or len(text) < n:
        return False
    lines = [s for s in (re.sub(r"\s+", " ", ln).strip() for ln in text[-600000:].splitlines()) if len(s) >= n]
    h = hashlib.sha1
    for s in lines:
        if h(s[-n:].encode("utf-8")).hexdigest() == sha:
            return True
    for s in lines:
        for i in range(len(s) - n):                 # 끝 창은 위에서 봤다
            if h(s[i:i + n].encode("utf-8")).hexdigest() == sha:
                return True
    return False


HEAD_MAX = 60                  # 머리 앵커 — 프롬프트 첫 줄의 앞 이만큼(20자 미만이면 없음)


def head_key(prompt):
    """머리 앵커 → (sha1, 길이) — 프롬프트의 첫 줄(빈 줄은 건너뜀 · 공백을 한 칸으로)의 앞 HEAD_MAX 자. LM28(2026-10-17): Copilot 이 긴
    질문을 접어 첫 몇 줄만 보여 주면 끝 앵커(anchor_key — 끝 줄들 중 가장 긴 줄)가 화면에 없다 — 그때 이 앵커로 소유를 확인한다.
    20자 미만이면 ("", 0)(짧은 줄은 남의 대화에도 있을 수 있다). 원문은 돌려주지 않는다."""
    for ln in str(prompt or "").splitlines():
        s = re.sub(r"\s+", " ", ln).strip()
        if s:
            s = s[:HEAD_MAX]
            return (hashlib.sha1(s.encode("utf-8")).hexdigest(), len(s)) if len(s) >= 20 else ("", 0)
    return "", 0


def _page_is_ours(text, st):
    """화면 글이 우리 채팅을 보여 주나 — 마지막 프롬프트의 끝 앵커(anchor_sha·alen) 또는 머리 앵커(hsha·hlen)가 있으면 참(해시로만).
    보내기 전(_chat_before_send)·이어 쓰기(_resume_ok)·지우기 전 확인과 지운 뒤 확인(둘 다 없어야 '사라짐')이 같이 쓴다."""
    st = st if isinstance(st, dict) else {}
    return (page_has_anchor(text, st.get("anchor_sha"), st.get("alen"))
            or page_has_anchor(text, st.get("hsha"), st.get("hlen")))


# ── LM28(2026-10-17) — 대화 목록 항목의 제목 확인 ─────────────────────────────────────────────────────────────────────────
# 현장의 대화 목록 제목은 그 채팅에 보낸 첫 프롬프트의 앞부분이다(개행은 공백 · 길면 '…'). 첫 보내기 때 그 앞부분의 TITLE_MIN~TITLE_MAX
# 길이마다 해시(FNV-1a 32 — UTF-16 단위마다라 JS 의 charCodeAt 과 같은 값)를 상태 파일 tpre 에 둔다(원문 없음). 지우기 전에 JS(_JS_TITLE)가
# 찾은 항목의 제목을 같은 규칙으로 정리해 그 길이의 해시만 맞춰 보고 0/1(tm)만 돌려준다 — 제목 글은 파이썬으로 오지 않는다. 다르면 그 항목은
# 누르지 않는다('notitle' — 사람의 대화가 '현재' 항목인 화면에서도 지우지 않는다). 한 번 더 거르는 조건일 뿐 다른 확인을 대신하지 않는다.
TITLE_MIN, TITLE_MAX = 8, 64
FNV_OFFSET, FNV_PRIME = 0x811C9DC5, 0x01000193
# 공백 묶음 글자(문자 클래스 안 — '-' 는 범위) — 파이썬 \s 와 JS \s 의 합집합(두 쪽이 같은 글자를 한 칸으로 줄인다). JS 에는 json.dumps 로
# 그대로 넘긴다. 소스에는 ASCII 만 둔다(chr — U+1680 · U+2000~200A · U+2028 · U+2029 · U+202F · U+205F · U+3000 · U+FEFF)
_TITLE_WS = ("\t\n\x0b\x0c\r \x1c-\x1f\x85\xa0" + chr(0x1680) + chr(0x2000) + "-" + chr(0x200A)
             + "".join(chr(c) for c in (0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF)))
_TITLE_WS_RX = re.compile("[" + _TITLE_WS + "]+")
_TITLE_PUA_RX = re.compile("[" + chr(0xE000) + "-" + chr(0xF8FF) + "]")   # 아이콘 글꼴 문자(U+E000~F8FF) — 소스에 그 글자를 두지 않는다
_TITLE_TAIL_RX = re.compile(r"(?: |…|\.\.\.)+$")                          # 제목 끝 말줄임('…'·'...')과 칸


def _u16(s):
    """글 → UTF-16 단위(정수) 목록 — JS 의 length·charCodeAt·slice 와 같은 단위(보조 평면 글자는 둘)."""
    b = str(s or "").encode("utf-16-le", "surrogatepass")
    return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]


def _fnv_units(units):
    h = FNV_OFFSET
    for c in units:
        h = ((h ^ c) * FNV_PRIME) & 0xFFFFFFFF
    return f"{h:08x}"


def fnv1a32_hex(s):
    """FNV-1a 32비트(UTF-16 단위마다 xor 뒤 곱) → 8자리 16진수 — _JS_TITLE 의 fnv 와 같은 값(ASCII 는 바이트 FNV-1a 와도 같다)."""
    return _fnv_units(_u16(s))


def _title_norm(s):
    """제목 비교용 정리 — 아이콘 글꼴 문자를 빼고 공백 묶음(_TITLE_WS)을 한 칸으로 줄인 뒤 앞뒤 칸을 뗀다(JS tnorm 과 같다)."""
    return _TITLE_WS_RX.sub(" ", _TITLE_PUA_RX.sub("", str(s or ""))).strip(" ")


def title_prefixes(prompt):
    """첫 프롬프트 → {"L": 앞 L UTF-16 단위의 FNV-1a 해시} (L = TITLE_MIN~TITLE_MAX · 정리한 글이 그보다 짧으면 그 길이까지) — 상태 파일
    tpre. 해시 사다리만 남는다(원문 없음)."""
    u = _u16(_title_norm(prompt))[:TITLE_MAX]
    return {str(n): _fnv_units(u[:n]) for n in range(TITLE_MIN, len(u) + 1)}


def title_tm(text, tpre):
    """_JS_TITLE 의 tmOf 와 같은 규칙(파이썬 거울 — 시험의 가짜 화면이 쓴다): 항목 글의 첫 줄(정리 뒤 빈 줄은 건너뜀) · 끝 '…'·'...'·칸
    뗌 · L = min(길이, TITLE_MAX) · L >= TITLE_MIN 이고 앞 L 단위의 해시가 tpre[L] 이면 1, 아니면 0."""
    t = ""
    for ln in re.split(r"\r\n?|\n", str(text or "")):
        t = _title_norm(ln)
        if t:
            break
    u = _u16(_TITLE_TAIL_RX.sub("", t))
    n = min(len(u), TITLE_MAX)
    if n < TITLE_MIN or not isinstance(tpre, dict):
        return 0
    return 1 if tpre.get(str(n)) == _fnv_units(u[:n]) else 0


def _tpre_js(tpre):
    """상태 파일의 tpre → JS 객체 글 — 키는 TITLE_MIN~TITLE_MAX 숫자, 값은 8자리 16진수만(그 밖은 버린다 — 상태 파일이 깨져도 JS 에
    다른 글이 들어가지 않는다)."""
    out = {}
    for k, v in (tpre.items() if isinstance(tpre, dict) else ()):
        if re.fullmatch(r"\d{1,2}", str(k)) and TITLE_MIN <= int(k) <= TITLE_MAX and re.fullmatch(r"[0-9a-f]{8}", str(v)):
            out[str(int(k))] = str(v)
    return json.dumps(out, sort_keys=True)


# js_chat_row·js_chat_count 가 함께 쓰는 제목 규칙(JS). @…@ 자리는 _js_title 이 채운다. 제목 글은 함수 밖으로 내보내지 않는다(tmOf 의 0/1 만).
_JS_TITLE = r"""const TPRE=@TPRE@;
const PUA=new RegExp("["+String.fromCharCode(57344)+"-"+String.fromCharCode(63743)+"]","g");   // 아이콘 글꼴 문자(U+E000~F8FF)
const WS=new RegExp(@WS@,"g");                                                                   // 공백 묶음 — 파이썬 _TITLE_WS 와 같은 글자
const tnorm=s=>String(s||"").replace(PUA,"").replace(WS," ").replace(/^ +| +$/g,"");
const ttl=e=>{for(const ln of String((e&&e.innerText)||"").split(/\r\n?|\n/)){const t=tnorm(ln);if(t)return t.replace(/(?: |…|\.\.\.)+$/,"");}return "";};
const fnv=s=>{let h=@OFF@;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,@PRIME@);}return (h>>>0).toString(16).padStart(8,"0");};
const tmOf=e=>{const t=ttl(e),L=Math.min(t.length,@MAX@);return (L>=@MIN@&&TPRE[String(L)]===fnv(t.slice(0,L)))?1:0;};
"""


def _js_title(tpre):
    """_JS_TITLE 에 tpre(_tpre_js)·공백 글자(_TITLE_WS)·FNV 상수·길이 규칙을 채운 JS 글(줄 끝 개행 포함)."""
    return (_JS_TITLE.replace("@TPRE@", _tpre_js(tpre)).replace("@WS@", json.dumps("[" + _TITLE_WS + "]+"))
            .replace("@OFF@", f"0x{FNV_OFFSET:08x}").replace("@PRIME@", f"0x{FNV_PRIME:08x}")
            .replace("@MAX@", str(TITLE_MAX)).replace("@MIN@", str(TITLE_MIN)))


def _chat_url(cdp):
    """탭의 지금 주소 — 못 읽으면 ""."""
    try:
        st = cdp.eval(js_state(), timeout=10)
    except Exception:  # noqa: BLE001 - 주소를 못 읽으면 '모름'
        return ""
    return str(st.get("url") or "") if isinstance(st, dict) else ""


def _jsd(cdp, js, timeout=10):
    """JS 평가 → dict(아니면 {}). 평가 오류는 그대로 올린다(정리를 '오류'로 접는다)."""
    r = cdp.eval(js, timeout=timeout)
    return r if isinstance(r, dict) else {}


def js_chat_row(conv="", act="find", tpre=None):
    """대화 목록에서 '지금 대화' 항목 → {r, how, x, y, nh, nc, tg, tm} — 숫자·코드만(제목·글은 돌려주지 않는다).
    r: ok · none(못 찾음 — 대화 목록 펼침 단추가 하나면 그 점 tg) · many(후보 여럿) · split(주소 일치 항목과 '현재' 표시 항목이 다름)
       · covered(그 점에 다른 요소) · nomore(act=more 인데 그 항목 안에 '추가 작업' 단추 없음).
    찾기: ① 링크 주소에 대화 id(conv)가 든 a[href] ② aria-current(page·true)·aria-selected(true) — 둘 다 목록·탐색 영역(nav·aside·
    list·tree·ul·ol) 안이고 메뉴·대화상자 밖이며, '새 채팅'·탐색 이름('채팅'·'에이전트' 등 한 낱말)은 뺀다. ①이 있으면 ①이되 ②가 다른
    항목만 가리키면 split. 항목 = 가장 가까운 li·listitem·treeitem·option·row(없으면 그 요소).
    act=find: 항목을 화면 안으로 굴리고(scrollIntoView) 가운데 점. act=more: 그 항목(없으면 항목 하나만 품은 부모) 안의 aria-haspopup
    또는 '…'·'More'·'기타'·'더 보기'·'옵션'·'추가 작업' 단추의 가운데 점 — 돌려주기 전에 지금 보이는 메뉴(menu·listbox — 대화 목록이
    listbox 일 수도 있다)에 data-lm28-pre 표식을 단다(js_chat_menu 는 그 뒤에 열린 메뉴만 본다). 점마다 elementFromPoint 로 가림을 본다.
    tm(LM28 2026-10-17 · ok 일 때): 그 항목의 제목(_JS_TITLE — 첫 줄 · 아이콘 글꼴 문자 뺌 · 공백 정리 · 끝 '…'·'...' 뗌)의 앞
    L(= min(길이, TITLE_MAX)) UTF-16 단위의 해시가 tpre[L](첫 프롬프트 앞부분 — title_prefixes)과 같으면 1, 아니면 0(L < TITLE_MIN 이면 0).
    항목을 고르는 규칙은 그대로다 — tm 은 호출자가 한 번 더 거르는 데만 쓴다."""
    return ("/*LM28:chat_row*/(function(){\n"
            "const CONV=" + json.dumps(str(conv or "")) + ",ACT=" + json.dumps(str(act or "find")) + ";\n"
            + _js_title(tpre) + r"""const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const lab=e=>((e.getAttribute("aria-label")||"")+" "+(e.getAttribute("title")||"")+" "+(e.innerText||""))
  .replace(PUA,"").replace(/\s+/g," ").trim();
const POP="[role='menu'],[role='menubar'],[role='dialog'],[role='alertdialog'],[role='tooltip'],[role='combobox']";
const REG="nav,aside,[role='navigation'],[role='tree'],[role='list'],[role='listbox'],[role='grid'],ul,ol";
const NEWC=/^(새 채팅|새 대화|new chat|new conversation)/i;
const NAVW=/^(채팅|대화|copilot|chat|chats|home|홈|에이전트|agents?|페이지|pages|노트북|notebooks|만들기|create|라이브러리|library|검색|search)$/i;
const rowOf=e=>e.closest("li,[role='listitem'],[role='treeitem'],[role='option'],[role='row']")||e;
const inReg=e=>vis(e)&&!e.closest(POP)&&!!e.closest(REG);
const uniq=xs=>xs.filter((x,i)=>xs.indexOf(x)===i);
const same=(a,b)=>a===b||a.contains(b)||b.contains(a);
let hr=[],cr=[];
if(CONV){for(const a of document.querySelectorAll("a[href]")){
  const h=(a.getAttribute("href")||"")+" "+(a.href||"");
  if(h.indexOf(CONV)>=0&&inReg(a))hr.push(rowOf(a));}}
for(const e of document.querySelectorAll("[aria-current='page'],[aria-current='true'],[aria-selected='true']")){
  if(!inReg(e))continue;
  const t=lab(e);
  if(NEWC.test(t)||NAVW.test(t))continue;
  cr.push(rowOf(e));}
hr=uniq(hr);cr=uniq(cr);
let row=null,how="";
if(hr.length>1)return {r:"many",nh:hr.length,nc:cr.length};
if(hr.length===1){row=hr[0];how="href";
  if(cr.length){if(!cr.some(c=>same(c,row)))return {r:"split",nh:1,nc:cr.length};how="both";}}
else if(cr.length===1){row=cr[0];how="cur";}
else if(cr.length>1)return {r:"many",nh:0,nc:cr.length};
if(!row){
  const tg=[...document.querySelectorAll("button,[role='button']")].filter(b=>vis(b)&&b.getAttribute("aria-expanded")==="false"
    &&!b.closest(POP)&&!NEWC.test(lab(b))&&/(대화|채팅 기록|conversation|chats|history)/i.test(lab(b)));
  if(tg.length===1){const q=tg[0].getBoundingClientRect();
    return {r:"none",nh:0,nc:0,tg:[Math.round(q.left+q.width/2),Math.round(q.top+q.height/2)]};}
  return {r:"none",nh:0,nc:0,ntg:tg.length};}
const pt=e=>{const q=e.getBoundingClientRect(),x=Math.round(q.left+q.width/2),y=Math.round(q.top+q.height/2);
  const h=document.elementFromPoint(x,y);return {x:x,y:y,ok:!!h&&(h===e||e.contains(h))};};
if(ACT==="find"){
  try{row.scrollIntoView({block:"nearest"});}catch(_){}
  const p=pt(row);if(!p.ok)return {r:"covered",how:how};
  return {r:"ok",how:how,x:p.x,y:p.y,nh:hr.length,nc:cr.length,tm:tmOf(row)};}
const MORE=/(…|\.\.\.|\bmore\b|기타|더 보기|옵션|추가 작업|options)/i;
const pick=box=>[...box.querySelectorAll("button,[role='button']")].filter(b=>vis(b)&&(b.getAttribute("aria-haspopup")||MORE.test(lab(b))));
let bs=pick(row);
const up=row.parentElement;
if(!bs.length&&up&&up.querySelectorAll("a[href],li,[role='treeitem'],[role='listitem'],[role='option']").length<=1)bs=pick(up);
if(!bs.length)return {r:"nomore",how:how};
const b=bs.find(x=>x.getAttribute("aria-haspopup"))||bs[0];
const p=pt(b);if(!p.ok)return {r:"covered",how:how};
document.querySelectorAll("[data-lm28-pre]").forEach(x=>x.removeAttribute("data-lm28-pre"));
document.querySelectorAll("[role='menu'],[role='listbox']").forEach(x=>{if(vis(x))x.setAttribute("data-lm28-pre","1");});
return {r:"ok",how:how,x:p.x,y:p.y,nb:bs.length,tm:tmOf(row)};
})()""")


def js_chat_count(tpre=None):
    """LM28(2026-10-17) — 보이는 대화 목록 항목 수(n)와 그중 제목이 첫 프롬프트 앞부분과 맞는 항목 수(nt) → {n, nt}(숫자만 — 제목·글
    없음). 항목 = js_chat_row 와 같은 영역(nav·aside·list·tree·ul·ol … · 메뉴·대화상자 밖)의 li·listitem·treeitem·option·row·링크·'현재'·
    '선택' 표시를 가장 가까운 항목으로 모은 것. 지운 뒤에도 화면이 그 대화를 그대로 보여 줄 때 '목록에서 딱 하나 · 제목이 맞는 것도 딱
    하나 빠졌나'를 메뉴를 열기 전에 센 수와 맞춰 보는 데만 쓴다(_retire_steps ⑤ — 무엇을 지울지는 정하지 않는다)."""
    return ("/*LM28:chat_count*/(function(){\n" + _js_title(tpre)
            + r"""const vis=e=>{const q=e.getBoundingClientRect();return q.width>4&&q.height>4;};
const POP="[role='menu'],[role='menubar'],[role='dialog'],[role='alertdialog'],[role='tooltip'],[role='combobox']";
const REG="nav,aside,[role='navigation'],[role='tree'],[role='list'],[role='listbox'],[role='grid'],ul,ol";
const ROW="li,[role='listitem'],[role='treeitem'],[role='option'],[role='row']";
const rowOf=e=>e.closest(ROW)||e;
const inReg=e=>vis(e)&&!e.closest(POP)&&!!e.closest(REG);
let es=[];
try{es=[...document.querySelectorAll(ROW+",a[href],[aria-current='page'],[aria-current='true'],[aria-selected='true']")];}catch(_){es=[];}
const rs=[...new Set(es.filter(inReg).map(rowOf))];
let nt=0;
for(const x of rs)nt+=tmOf(x);
return {n:rs.length,nt:nt};
})()""")


def js_chat_navtg(skip=()):
    """LM28(2026-10-17) — 접힌 대화 목록을 여는 탐색 창 단추 하나 → {r: ok · none · many · covered, x, y, n}(숫자·코드만). 보이는
    button·role=button 중 aria-expanded='false' 이고 메뉴·대화상자·툴팁 밖이며, 이름이 탐색·navigation·사이드·패널·확장·펼치·메뉴 열기·
    대화/채팅 기록·history·chats … 이고 모델·계정·프로필·설정·공유·첨부·플러그인·'새 채팅'이 아닌 것(바깥·안이 함께 걸리면 안쪽만).
    skip = 이번 화면에서 이미 누른 점 [[x, y]…] — 그 점을 품은 단추는 다시 누르지 않는다. 하나일 때만 ok(가운데 점 · elementFromPoint 로
    가림 확인) — 여럿이면 누르지 않는다(many). 길만 연다 — 무엇을 지울지는 정하지 않는다."""
    pts = [[int(p[0]), int(p[1])] for p in (skip or ()) if isinstance(p, (list, tuple)) and len(p) == 2
           and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)]
    return ("/*LM28:chat_navtg*/(function(){\nconst SKIP=" + json.dumps(pts) + ";" + r"""
const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const PUA=new RegExp("["+String.fromCharCode(57344)+"-"+String.fromCharCode(63743)+"]","g");   // 아이콘 글꼴 문자(U+E000~F8FF)
const lab=e=>((e.getAttribute("aria-label")||"")+" "+(e.getAttribute("title")||"")+" "+(e.innerText||""))
  .replace(PUA,"").replace(/\s+/g," ").trim();
const POP="[role='menu'],[role='menubar'],[role='dialog'],[role='alertdialog'],[role='tooltip'],[role='combobox']";
const NAV=/(탐색|navigation|nav|사이드|sidebar|side bar|패널|panel|확장|expand|펼치|메뉴 열기|open menu|대화 기록|채팅 기록|history|chats|conversations)/i;
const NOT=/(모델|model|계정|account|프로필|profile|설정|setting|공유|share|첨부|attach|플러그|plugin)/i;
const NEWC=/^(새 채팅|새 대화|new chat|new conversation)/i;
const inq=(q,p)=>p[0]>=q.left&&p[0]<=q.right&&p[1]>=q.top&&p[1]<=q.bottom;
let cs=[...document.querySelectorAll("button,[role='button']")].filter(b=>{
  if(!vis(b)||b.getAttribute("aria-expanded")!=="false"||b.closest(POP))return false;
  const t=lab(b);
  if(!NAV.test(t)||NOT.test(t)||NEWC.test(t))return false;
  const q=b.getBoundingClientRect();
  return !SKIP.some(p=>inq(q,p));});
cs=cs.filter(x=>!cs.some(y=>y!==x&&x.contains(y)));
if(cs.length!==1)return {r:cs.length?"many":"none",n:cs.length};
const q=cs[0].getBoundingClientRect(),x=Math.round(q.left+q.width/2),y=Math.round(q.top+q.height/2);
const h=document.elementFromPoint(x,y);
if(!(h&&(h===cs[0]||cs[0].contains(h))))return {r:"covered",n:1};
return {r:"ok",x:x,y:y,n:1};
})()""")


def js_chat_view():
    """지금 뷰포트 크기(CSS px) → {w, h} — 넓은 화면 흉내(_chat_wide)의 기준."""
    return "/*LM28:chat_view*/({w:Math.round(window.innerWidth||0),h:Math.round(window.innerHeight||0)})"


def js_chat_menu():
    """'추가 작업'을 누른 **뒤에 열린** 메뉴(menu·listbox — 그 전부터 보이던 것은 js_chat_row(more)가 단 data-lm28-pre 로 뺀다)에서
    글자가 **정확히** CHAT_DELETE_LABELS 중 하나인 항목 하나 → {r: ok · nomenu · nodelete · many · covered, x, y, n}(글은 돌려주지
    않는다). 보이는 글이 있으면 그 글로만, 없으면 aria-label 로 본다(아이콘 글꼴 문자는 뺀다). 같은 이름이 둘이면 누르지 않는다.
    ok 를 돌려주기 전에 지금 보이는 대화상자에 data-lm28-pred 표식을 단다(js_chat_confirm 은 그 뒤에 뜬 확인 창만 본다)."""
    return ("/*LM28:chat_menu*/(function(){\nconst WANT=" + json.dumps(list(CHAT_DELETE_LABELS), ensure_ascii=False) + ";"
            + r"""
const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const PUA=new RegExp("["+String.fromCharCode(57344)+"-"+String.fromCharCode(63743)+"]","g");   // 아이콘 글꼴 문자
const nrm=s=>(s||"").replace(PUA,"").replace(/\s+/g," ").trim().toLowerCase();
const pops=[...document.querySelectorAll("[role='menu'],[role='listbox']")].filter(e=>vis(e)&&!e.closest("[data-lm28-pre]"));
if(!pops.length)return {r:"nomenu"};
let hs=[],n=0;
for(const p of pops)for(const it of p.querySelectorAll("[role='menuitem'],[role='menuitemradio'],[role='option'],button")){
  if(!vis(it))continue;n++;
  const t=nrm(it.innerText),a=nrm(it.getAttribute("aria-label"));
  if(t?WANT.includes(t):WANT.includes(a))hs.push(it);}
hs=hs.filter((x,i)=>hs.indexOf(x)===i&&!hs.some(y=>y!==x&&x.contains(y)));
if(!hs.length)return {r:"nodelete",n:n};
if(hs.length>1)return {r:"many",n:n};
const q=hs[0].getBoundingClientRect(),x=Math.round(q.left+q.width/2),y=Math.round(q.top+q.height/2);
const h=document.elementFromPoint(x,y);
if(!(h&&(h===hs[0]||hs[0].contains(h))))return {r:"covered",n:n};
document.querySelectorAll("[data-lm28-pred]").forEach(e=>e.removeAttribute("data-lm28-pred"));
document.querySelectorAll("[role='dialog'],[role='alertdialog'],dialog[open]").forEach(e=>{if(vis(e))e.setAttribute("data-lm28-pred","1");});
return {r:"ok",x:x,y:y,n:n};
})()""")


def js_chat_confirm():
    """'삭제'를 누른 **뒤에 뜬** 확인 창(dialog·alertdialog·dialog[open] — 그 전부터 보이던 것은 data-lm28-pred 로 뺀다)의 단추 중
    글자가 **정확히** CHAT_CONFIRM_LABELS('삭제'·'Delete')인 것 하나 → {r: ok · none(창 없음) · nobtn · many · covered, x, y}.
    '취소'·'닫기' 는 보지도 않는다."""
    return ("/*LM28:chat_confirm*/(function(){\nconst WANT=" + json.dumps(list(CHAT_CONFIRM_LABELS), ensure_ascii=False) + ";"
            + r"""
const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const PUA=new RegExp("["+String.fromCharCode(57344)+"-"+String.fromCharCode(63743)+"]","g");   // 아이콘 글꼴 문자
const nrm=s=>(s||"").replace(PUA,"").replace(/\s+/g," ").trim().toLowerCase();
const ds=[...document.querySelectorAll("[role='dialog'],[role='alertdialog'],dialog[open]")].filter(e=>vis(e)&&!e.closest("[data-lm28-pred]"));
if(!ds.length)return {r:"none"};
let hs=[];
for(const d of ds)for(const b of d.querySelectorAll("button,[role='button']")){
  if(!vis(b))continue;
  const t=nrm(b.innerText),a=nrm(b.getAttribute("aria-label"));
  if(t?WANT.includes(t):WANT.includes(a))hs.push(b);}
hs=hs.filter((x,i)=>hs.indexOf(x)===i&&!hs.some(y=>y!==x&&x.contains(y)));
if(!hs.length)return {r:"nobtn",n:ds.length};
if(hs.length>1)return {r:"many",n:ds.length};
const q=hs[0].getBoundingClientRect(),x=Math.round(q.left+q.width/2),y=Math.round(q.top+q.height/2);
const h=document.elementFromPoint(x,y);
if(!(h&&(h===hs[0]||hs[0].contains(h))))return {r:"covered",n:ds.length};
return {r:"ok",x:x,y:y,n:ds.length};
})()""")


def _chat_mouse(cdp, x, y, click=True):
    """신뢰 입력 마우스(CDP Input.dispatchMouseEvent — Get-TeamsWeb._mouse 와 같은 꼴): 옮김(+ click 이면 누름·뗌 왼쪽 1번)."""
    x, y = int(x), int(y)
    if x <= 0 or y <= 0:
        raise ValueError("누를 점 없음")
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none", "buttons": 0}, timeout=8)
    if click:
        for t, b in (("mousePressed", 1), ("mouseReleased", 0)):
            cdp.call("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "buttons": b,
                                                  "clickCount": 1}, timeout=8)


def _chat_esc(cdp):
    """열린 메뉴·확인 창 닫기 — Esc 두 번(실패해도 그만). 확인 창의 Esc 는 '취소'다(무엇도 지우지 않는다)."""
    for _ in range(2):
        try:
            for t in ("rawKeyDown", "keyUp"):
                cdp.call("Input.dispatchKeyEvent", {"type": t, "key": "Escape", "code": "Escape",
                                                    "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27}, timeout=5)
        except Exception:  # noqa: BLE001 - 닫기 실패는 그대로 둔다
            return
        _sleep(0.2)


def _chat_opened(cdp, cfg, how, pre=""):
    """LM28 이 방금 새 채팅을 열었다(_fresh_chat) → '우리 것(보내기 전)'으로 적는다. 열지 못했거나(how '실패') 주소의 대화 id 가
    열기 전(pre)과 같으면 새 채팅이 아니다(그 대화는 남의 것일 수 있다) — 적지 않는다. 정리 못 한 우리 채팅이 남아 있었으면 '남김'.
    LM28(2026-10-17) → 새 채팅으로 옮긴 것을 확인했나(참/거짓 — 소유 기록을 쓰다 실패해도 판정은 돌려준다). 거짓이면 _open_fresh 가
    한 번 더 열어 보고, 그래도 아니면 왕복은 보내지 않는다(사람이 쓰던 대화에 LM28 질문이 들어가지 않게)."""
    cid = conv_id(_chat_url(cdp), cfg)
    ok = str(how or "") not in ("", "실패") and not (cid and cid == conv_id(pre, cfg))
    try:
        st = chat_state(cfg)
        if st.get("ours") and int(st.get("sent") or 0) > 0:
            _chat_tally(st, "replaced")
        _chat_reset(st)
        if str(how or "") in ("", "실패"):
            pass                                        # 새 채팅이 열리지 않았다 — 지금 화면은 맡지 않는다
        elif not ok:
            _chat_tally(st, "notfresh")                 # 주소가 그 대화 그대로 — 새 채팅으로 확인되지 않았다(맡지 않음)
            trace("chat", act="open", code="notfresh")
        else:
            st.update(ours=True, sent=0, anchor_sha="", alen=0, hsha="", hlen=0, conv="", href="", pid=os.getpid(),
                      created_at=_now(), stage=str(os.environ.get("LM_STAGE") or "")[:40])
        _chats_save(cfg, st)
    except Exception:  # noqa: BLE001 - 소유 기록이 왕복을 막지 않는다
        pass
    return ok


def _chat_before_send(cdp, cfg, text):
    """보내기 직전 — 이 화면이 우리 채팅인가 → True/False. 열고 아직 보내지 않은 우리 채팅은 연 프로세스에서만(다른 프로세스는 그
    화면이 그 채팅인지 모른다) · 보낸 적 있는 우리 채팅은 화면 글에 우리 앵커(끝 앵커 또는 머리 앵커 — _page_is_ours)가 있고 주소의
    대화 id 가 같을 때만. 아니면 소유를 놓는다(보낸 적 있으면 '남김 — lost'). 남의 대화에 이어 보내는 것은 우리 것이 되지 않는다."""
    try:
        st = chat_state(cfg)
        if not st.get("ours"):
            return False
        if int(st.get("sent") or 0) <= 0:
            if st.get("pid") == os.getpid() and _age_sec(st.get("created_at")) < CHAT_PENDING_SEC:
                return True
            _chats_save(cfg, _chat_reset(st))
            return False
        cid, cid0 = conv_id(_chat_url(cdp), cfg), str(st.get("conv") or "")
        if _page_is_ours(text, st) and not (cid and cid0 and cid != cid0):
            return True
        sent = int(st.get("sent") or 0)
        _chat_tally(st, "lost")
        _chats_save(cfg, _chat_reset(st))
        trace("chat", act="lost", sent=sent)
        return False
    except Exception:  # noqa: BLE001
        return False


def _chat_after_send(cdp, cfg, prompt, own):
    """보낸 직후 — 우리 채팅이면(own) 앵커 해시·보낸 수를 고친다. 첫 프롬프트면 '만든 채팅' 1. 앵커를 만들 수 없는 프롬프트(20자 이상
    줄 없음)는 나중에 확인할 수 없어 지우지 않는다(남김 — noanchor).
    LM28(2026-10-17): 끝 앵커 옆에 머리 앵커(head_key — 마지막 프롬프트 첫 줄 앞 60자 · 20자 미만이면 빈 값)를 늘 새로 적고, 새 채팅의 첫
    프롬프트면 목록 제목 확인용 앞부분 해시(tpre — title_prefixes)를 적는다. tpre 는 이어 보내도 그대로이고 _chat_reset(새 채팅)으로만
    사라진다. 원문은 남기지 않는다."""
    if not own:
        return
    try:
        st = chat_state(cfg)
        if not st.get("ours"):
            return
        sent = int(st.get("sent") or 0)
        if sent <= 0:
            _chat_tally(st, "made")
            trace("chat", act="made", step=str(os.environ.get("LM_STAGE") or "")[:40])
            st["tpre"] = title_prefixes(prompt)
        sha, n = anchor_key(prompt)
        if not sha:
            _chat_tally(st, "noanchor")
            _chats_save(cfg, _chat_reset(st))
            return
        hs, hn = head_key(prompt)
        st.update(anchor_sha=sha, alen=n, hsha=hs, hlen=hn, sent=sent + 1, pid=os.getpid(), t_last=_now())
        _chats_save(cfg, st)
    except Exception:  # noqa: BLE001
        pass


def _chat_seen(cdp, cfg, ok=None):
    """왕복이 끝난 뒤 — 이 프로세스가 보낸 우리 채팅의 주소(대화 id·경로)를 적는다. 첫 답 뒤에야 주소에 id 가 생기는 화면이 있어
    보낼 때가 아니라 답 뒤에 본다. 다음 확인(보내기 전·지우기 전)이 지금 주소의 id 와 맞춰 본다.
    ok(LM28): 이번 왕복이 온전했나(_rt_good) — last_ok·t_ok 로 적는다(다음 단계가 이 채팅을 이어 쓸 수 있는지의 근거)."""
    try:
        st = chat_state(cfg)
        if not (st.get("ours") and int(st.get("sent") or 0) > 0 and st.get("pid") == os.getpid()):
            return
        url = _chat_url(cdp)
        cid = conv_id(url, cfg)
        dirty = False
        if cid and (cid != st.get("conv") or not st.get("href")):
            st.update(conv=cid, href=_plain_href(url))
            dirty = True
        if ok is not None:
            st["last_ok"] = bool(ok)
            if ok:
                st["t_ok"] = _now()
            dirty = True
        if dirty:
            _chats_save(cfg, st)
    except Exception:  # noqa: BLE001
        pass


def chat_resumable(cfg=None, turns=0):
    """다음 단계 프로세스의 첫 왕복이 지금 우리 채팅을 이어 쓸 수 있나(상태 파일만 — 화면 확인은 _resume_ok) → (참/거짓, 보낸 수).
    우리 것 · 보낸 적 있음 · 마지막 왕복 온전(last_ok) · CHAT_RESUME_SEC 안 · 보낸 수 < turns(chatTurns — 0 이면 늘 거짓)."""
    try:
        cfg = cfg if isinstance(cfg, dict) else load_cfg()
        st = chat_state(cfg)
        sent = int(st.get("sent") or 0)
        ok = bool(st.get("ours") and 0 < sent < int(turns or 0) and st.get("last_ok") is True
                  and _age_sec(st.get("t_ok")) < CHAT_RESUME_SEC)
        return ok, (sent if ok else 0)
    except Exception:  # noqa: BLE001 - 모르면 이어 쓰지 않는다(새 채팅)
        return False, 0


def _resume_ok(cdp, cfg):
    """RESUME — 지금 화면이 상태 파일의 우리 채팅인가: chat_resumable 의 상태 조건(보낸 수 상한은 호출자가 봤다) + 화면 글에 우리 앵커
    (끝 앵커 또는 머리 앵커 — _page_is_ours) + 주소의 대화 id 가 적어 둔 id 와 같음(적어 둔 id 가 있으면 지금 주소에도 같은 id 가 있어야)
    + 생성 중 아님. 하나라도 아니면 False."""
    try:
        st = chat_state(cfg)
        if not (st.get("ours") and int(st.get("sent") or 0) > 0 and st.get("last_ok") is True
                and _age_sec(st.get("t_ok")) < CHAT_RESUME_SEC):
            return False
        if not _page_is_ours(cdp.eval(js_chat_text(cfg), timeout=30), st):
            return False
        cid0 = str(st.get("conv") or "")
        if cid0 and conv_id(_chat_url(cdp), cfg) != cid0:
            return False
        return cdp.eval(js_is_generating(), timeout=10) is not True
    except Exception:  # noqa: BLE001 - 확인하지 못하면 새 채팅
        return False


def _continue_why(cdp, cfg):
    """LM28(2026-10-17) — 이어 보내기(fresh 거짓) 직전: 지금 화면에 이어 보내도 되나 → "" (된다) · "moved"(우리 채팅에서 다른 대화로 옮겨
    감 — 주소의 대화 id 가 다름) · "unverified"(우리 채팅임을 확인하지 못함). 사용자 요구: "이전에 사용자가 쓰고 있었던 채팅은 건드리면
    안 된다" — 사람이 전용 Edge 에서 자기 대화를 눌렀거나 소유를 놓친 화면에 LM28 질문을 이어 보내지 않는다(호출자가 새 채팅을 연다).
    된다 = 상태 파일이 우리 것 · 보낸 적 있음 · 이 프로세스(pid) · 화면 글에 우리 앵커(끝 또는 머리 — _page_is_ours) · _moved_away 아님.
    상태 파일·화면을 읽지 못하면 "unverified"(새 채팅 — 모르면 이어 보내지 않는다)."""
    try:
        if _moved_away(cdp, cfg):
            return "moved"
        st = chat_state(cfg)
        if not (st.get("ours") and int(st.get("sent") or 0) > 0 and st.get("pid") == os.getpid()):
            return "unverified"
        return "" if _page_is_ours(cdp.eval(js_chat_text(cfg), timeout=30), st) else "unverified"
    except Exception:  # noqa: BLE001 - 확인하지 못하면 이어 보내지 않는다
        return "unverified"


def _moved_away(cdp, cfg):
    """LM28(2026-10-17) — 이어 보내기(fresh 거짓) 직전: 화면이 이 프로세스가 보내던 우리 채팅에서 다른 대화로 옮겨 갔나. 상태 파일이
    우리 것 · 보낸 적 있음 · 이 프로세스(pid) · 적어 둔 대화 id(conv) 있음이고, 지금 탭 주소에도 대화 id 가 있는데 둘이 다를 때만 True
    (사람이 전용 Edge 에서 다른 대화를 눌렀다 — 다음 조각을 그 대화에 넣지 않는다). 주소에 대화 id 가 없는 화면·읽기 오류는 False(예전 그대로)."""
    try:
        st = chat_state(cfg)
        if not (st.get("ours") and int(st.get("sent") or 0) > 0 and st.get("pid") == os.getpid()):
            return False
        cid0 = str(st.get("conv") or "")
        if not cid0:
            return False
        cid = conv_id(_chat_url(cdp), cfg)
        return bool(cid) and cid != cid0
    except Exception:  # noqa: BLE001 - 모르면 예전 그대로(이어 보낸다)
        return False


def chat_mark_bad(cfg=None):
    """호출자가 답을 쓰지 못했다(해석 실패 — judge.note_bad_reply) — 이 채팅은 다음 단계가 이어 쓰지 않는다(last_ok False)."""
    try:
        cfg = cfg if isinstance(cfg, dict) else load_cfg()
        st = chat_state(cfg)
        if st.get("ours") and st.get("last_ok"):
            st["last_ok"] = False
            _chats_save(cfg, st)
    except Exception:  # noqa: BLE001
        pass


CHAT_TURNS_DEFAULT = 12        # = judge.CHAT_TURNS_DEFAULT — 한 채팅에 이어 보내는 왕복 상한(0 = 늘 새 채팅)


def chat_turns(cfg=None):
    """copilotAuto.chatTurns — 한 채팅에 이어 보내는 왕복(조각) 수(judge.chat_turns 와 같은 규칙). 없거나 숫자가 아니거나 음수면
    CHAT_TURNS_DEFAULT, 0 이면 늘 새 채팅. cfg 가 없으면 load_cfg()(0 도 받는다 — KEEP_FALSY). 예외를 내지 않는다."""
    try:
        cfg = cfg if isinstance(cfg, dict) else load_cfg()
        v = int(cfg.get("chatTurns", CHAT_TURNS_DEFAULT))
        return v if v >= 0 else CHAT_TURNS_DEFAULT
    except Exception:  # noqa: BLE001 - 모르면 기본값
        return CHAT_TURNS_DEFAULT


class ChatKeep:
    """LM28(2026-10-17) — 혼자서 완결인 조각을 많이 보내는 호출자(Copilot 메일·일정·팀즈 수집기)의 '새 채팅이냐 이어 쓰기냐'(프로세스에 하나).
    왜: 조각마다 새 채팅(fresh=True)을 열어 사람의 Copilot 대화 목록에 조각 수만큼 LM28 채팅이 쌓였다(현장 사진 — '…부터 …까지' 제목이
    줄줄이). 다 쓴 채팅 지우기가 되지 않는 PC 가 있어(원인 조사 중) 여는 수 자체를 줄인다. 조각 프롬프트는 기간을 못 박고 파서는 요청
    구간 밖 날짜의 행을 버리므로, 앞 조각의 답이 문맥에 남아도 섞이지 않는다.
    쓰는 법: fr = k.next() → send_inproc(…, fresh=fr) → k.done(좋았나, 결과).
      · 첫 조각 — 앞 단계의 우리 채팅을 이어 쓸 수 있으면(chat_resumable — 우리 것·마지막 왕복 온전·CHAT_RESUME_SEC 안·보낸 수 < turns)
        RESUME(드라이버가 보내기 직전에 화면을 다시 보고 우리 채팅이 아니면 새 채팅), 아니면 True(새 채팅).
      · 그다음 — 앞 조각이 좋았고 이 채팅에 보낸 수 < turns 면 False(같은 채팅에 이어서), 아니면 True(chatTurns 회전).
      · 나쁜 조각(답 없음·오류·끊김·느린 답·'조회 불가'·표 아닌 답) 뒤는 True — 그 답이 남은 채팅에 이어 보내면 다음 답이 오염된다.
      · turns <= 0(chatTurns=0)이면 늘 True(예전 동작).
    셈(judge.copilot_send 의 _TURNS 와 같다): 새 채팅이면 1 · RESUME 이 실제로 이어 썼으면(결과 resumed) 그 채팅의 보낸 수 + 1 · 드라이버가
    새 채팅을 열었으면(resumed 거짓 · 재시도 사다리의 '새 채팅') 1. 보내지 않은 조각(G3 관문)은 done 을 부르지 않는다 — 다음 next() 가 같은
    결정을 다시 낸다. 시험은 turns 와 resumable(cfg, turns) → (참/거짓, 보낸 수)를 넣는다."""

    def __init__(self, cfg=None, turns=None, resumable=None):
        self.cfg = cfg
        self.turns = chat_turns(cfg) if turns is None else chat_turns({"chatTurns": turns})
        self._resumable = resumable
        self.n = 0              # 지금 채팅에 보낸 좋은 조각 수(0 = 이어 쓸 채팅 없음 → 새 채팅)
        self.first = True       # 아직 결과를 받은 조각이 없다 — 첫 조각만 RESUME 을 본다
        self.base = 0           # RESUME 일 때 그 채팅에 이미 보낸 수
        self.last = None        # 마지막 next() 의 값(done 이 센다)

    def next(self):
        """다음 조각의 fresh — True(새 채팅) · False(같은 채팅에 이어서) · RESUME(앞 단계의 우리 채팅에 이어서 — 화면 확인은 드라이버)."""
        if self.turns <= 0:
            fr = True
        elif self.n > 0:
            fr = self.n >= self.turns
        elif self.first:
            try:
                ok, sent = (self._resumable or chat_resumable)(self.cfg, self.turns)
                self.base = int(sent or 0) if ok else 0
            except Exception:  # noqa: BLE001 - 모르면 새 채팅
                ok, self.base = False, 0
            fr = RESUME if ok else True
        else:
            fr = True
        self.last = fr
        return fr

    def done(self, good, res=None):
        """조각 결과 — good: 표·'없음'을 끊김 없이 받았다. res: send_inproc 결과(resumed·retry 를 본다). next() 없이 부르면 무시."""
        fr, self.last = self.last, None
        if fr is None:
            return
        self.first = False
        r = res if isinstance(res, dict) else {}
        if not good:
            self.n = 0
        elif fr == RESUME:
            self.n = self.base + 1 if r.get("resumed") is True else 1
        elif fr:
            self.n = 1
        else:
            self.n += 1
        if self.n and "새 채팅" in str(r.get("retry") or ""):
            self.n = 1          # 드라이버의 재시도 사다리가 새 채팅을 열었다 — 그 채팅의 첫 조각


def _chat_done(cfg, code, why="", t0=None, census=None, flags=None):
    """정리 한 번의 끝 — 세기·소유 비우기·기록. 지우지 못했어도 소유는 비운다(곧 새 채팅으로 넘어가거나 Edge 를 닫는다).
    mismatch 면 이 프로세스는 더 지우지 않고(_CHAT_KILL), 상태 파일에 멈춤(hold — CHAT_REV)을 남긴다.
    census(LM28 — 화면 사유로 남김일 때의 구조 조사 · 숫자만): 상태 파일 totals.census · 이 프로세스 몫(_CHAT_PROC['census'] —
    chat_line 의 둘째 줄) · copilot_trace 에 남긴다. flags(LM28 2026-10-17 — _retire_steps 의 표시 wide·navtg·tm, 숫자만)는
    copilot_trace 에만 싣는다(지운 때도 — 넓은 화면·탐색 창 단추로 지웠는지 사진 없이 안다)."""
    st = chat_state(cfg)
    sent = int(st.get("sent") or 0)
    _chat_tally(st, code)
    if code == "mismatch":
        _CHAT_KILL[0] = True
        st["totals"]["hold"] = {"rev": CHAT_REV, "t": _now()}
    cz = dict(census, code=code) if isinstance(census, dict) and census else None
    if cz:
        st["totals"]["census"] = dict(cz, t=_now())
        _CHAT_PROC["census"] = cz
    _chats_save(cfg, _chat_reset(st))
    extra = {k: v for k, v in (flags or {}).items()
             if k in CENSUS_CTX_KEYS and isinstance(v, int) and not isinstance(v, bool)}
    if cz:
        extra["census"] = cz
    trace("chat", act="retire", code=code, why=str(why or "")[:24], sent=sent,
          sec=round(time.time() - (t0 or time.time()), 1), **extra)


def js_chat_census(conv=""):
    """대화 목록 구조 조사(읽기만 — 누르지 않는다) → 숫자만 {nnav 보이는 탐색 창 수 · navw 가장 넓은 탐색 창 너비(px) · nreg 보이는 목록
    영역 · nrow 목록 항목 · nlink 목록 링크 · nid 경로에 대화 id 꼴이 든 링크 · nhc 이 대화 id(conv)가 든 링크 · nhcv 그중 목록에 보임 ·
    ncur/ncurv aria-current(전체/목록 안) · nsel/nselv aria-selected · ntgc/ntgo 대화 기록 펼침 단추(접힘/펼침) · nmore 목록의 메뉴 단추 ·
    nmenu 열린 메뉴 · ndlg 열린 대화상자}. 제목·글·주소·id 는 돌려주지 않는다(conv 는 비교에만 쓴다). 영역·항목 기준은 js_chat_row 와 같다."""
    return ("/*LM28:chat_census*/(function(){\nconst CONV=" + json.dumps(str(conv or "")) + ";" + r"""
const vis=e=>{const r=e.getBoundingClientRect();return r.width>4&&r.height>4;};
const POP="[role='menu'],[role='menubar'],[role='dialog'],[role='alertdialog'],[role='tooltip'],[role='combobox']";
const REG="nav,aside,[role='navigation'],[role='tree'],[role='list'],[role='listbox'],[role='grid'],ul,ol";
const ROW="li,[role='listitem'],[role='treeitem'],[role='option'],[role='row']";
const IDRX=/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,}/i;
const HIST=/(대화|채팅 기록|conversation|chats|history)/i;
const q=s=>{try{return [...document.querySelectorAll(s)];}catch(_){return [];}};
const inReg=e=>!e.closest(POP)&&!!e.closest(REG);
const lab=e=>((e.getAttribute("aria-label")||"")+" "+(e.getAttribute("title")||"")+" "+(e.textContent||"")).replace(/\s+/g," ");
const o={nnav:0,navw:0,nreg:0,nrow:0,nlink:0,nid:0,nhc:0,nhcv:0,ncur:0,ncurv:0,nsel:0,nselv:0,ntgc:0,ntgo:0,nmore:0,nmenu:0,ndlg:0};
for(const n of q("nav,aside,[role='navigation']")){if(vis(n)){o.nnav++;o.navw=Math.max(o.navw,Math.round(n.getBoundingClientRect().width));}}
o.nreg=q(REG).filter(vis).length;
o.nrow=q(ROW).filter(e=>vis(e)&&inReg(e)).length;
for(const a of q("a[href]")){
  const h=(a.getAttribute("href")||"")+" "+(a.href||""),v=vis(a)&&inReg(a);
  let p="";try{p=new URL(a.getAttribute("href")||"",document.baseURI).pathname;}catch(_){p="";}
  if(v)o.nlink++;
  if(IDRX.test(p))o.nid++;
  if(CONV&&h.indexOf(CONV)>=0){o.nhc++;if(v)o.nhcv++;}}
for(const e of q("[aria-current='page'],[aria-current='true']")){o.ncur++;if(vis(e)&&inReg(e))o.ncurv++;}
for(const e of q("[aria-selected='true']")){o.nsel++;if(vis(e)&&inReg(e))o.nselv++;}
for(const b of q("button,[role='button']")){
  if(!vis(b)||b.closest(POP))continue;
  const x=b.getAttribute("aria-expanded");
  if((x==="false"||x==="true")&&HIST.test(lab(b))){if(x==="false")o.ntgc++;else o.ntgo++;}
  if(b.getAttribute("aria-haspopup")&&inReg(b))o.nmore++;}
o.nmenu=q("[role='menu'],[role='listbox']").filter(vis).length;
o.ndlg=q("[role='dialog'],[role='alertdialog'],dialog[open]").filter(vis).length;
return o;
})()""")


def _chat_census(cdp, cfg, conv="", ctx=None):
    """화면 사유로 남길 때의 구조 조사 → 숫자만 dict(CENSUS_TEXT 의 키 · 화이트리스트 밖·숫자 아닌 값은 버린다). ok 0 = 구조를 읽지 못함.
    gen(생성 중 0/1)·cid(주소에 대화 id 0/1)·fold(탐색 창이 좁다 — 접힘 추정 0/1)는 여기서 더한다. 예외를 내지 않는다.
    ctx(LM28 2026-10-17): _retire_steps 가 적은 표시 중 CENSUS_CTX_KEYS(wide 넓은 화면 흉내 · navtg 탐색 창 단추 누른 수 · tm 제목 일치
    0/1)의 숫자만 더한다 — 넓은 화면을 켠 채로(되돌리기 전에) 센다."""
    out = {}
    try:
        r = _jsd(cdp, js_chat_census(conv), timeout=5)
    except Exception:  # noqa: BLE001 - 조사는 덤이다
        r = {}
    for k in CENSUS_JS_KEYS:
        v = r.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = max(0, min(99999, int(v)))
    if "nnav" in out:
        out["fold"] = 1 if (out["nnav"] and out.get("navw", 0) < 120) else 0
    try:
        out["gen"] = 1 if cdp.eval(js_is_generating(), timeout=5) is True else 0
    except Exception:  # noqa: BLE001
        pass
    out["cid"] = 1 if conv else 0
    for k in CENSUS_CTX_KEYS:
        v = (ctx if isinstance(ctx, dict) else {}).get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            out[k] = max(0, min(99, v))
    out["ok"] = 1 if any(k in out for k in CENSUS_JS_KEYS) else 0
    return out


def census_note(code, c):
    """구조 조사(숫자) → '사유 — 탐색 창 1 · 목록 항목 0 · …' 한 줄(글·id 없음). 조사가 없으면 ""."""
    if not isinstance(c, dict) or not c:
        return ""
    head = CHAT_WHY.get(str(code or ""), str(code or ""))
    if not c.get("ok"):
        return f"{head} — 화면 구조를 읽지 못했습니다"
    parts = []
    for k, lab in CENSUS_TEXT:
        v = c.get(k)
        if isinstance(v, int) and not isinstance(v, bool):
            parts.append(f"{lab} {v}")
    return f"{head} — " + " · ".join(parts)


def _chat_wide(cdp, ctx):
    """LM28(2026-10-17) — 넓은 화면 흉내(CDP Emulation.setDeviceMetricsOverride: 폭 max(CHAT_WIDE_W, 지금 폭) · 높이 지금 그대로 ·
    배율 0(그대로) · 모바일 아님) → 바꿨나. 좁은 창(125~150% 배율의 1150px 전용 Edge)의 Copilot 은 대화 목록을 접어 서랍으로만 보여
    준다 — 넓은 배치에서는 목록이 펼쳐진다. 이미 그만큼 넓으면 바꾸지 않는다. ctx['wide']=1 을 보내기 **전에** 적는다 — 보내다 시간
    초과가 나도 retire_chat 의 finally 가 _chat_unwide 로 되돌린다. 길만 연다(무엇을 지울지는 정하지 않는다)."""
    try:
        v = _jsd(cdp, js_chat_view(), timeout=5)
    except Exception:  # noqa: BLE001 - 크기를 모르면 폭만 바꾼다(높이 0 = 그대로)
        v = {}
    w, h = (int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 else 0
            for x in (v.get("w"), v.get("h")))
    if w >= CHAT_WIDE_W:
        return False
    ctx["wide"] = 1
    try:
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": max(CHAT_WIDE_W, w), "height": h,
                                                         "deviceScaleFactor": 0, "mobile": False}, timeout=8)
    except Exception:  # noqa: BLE001 - 못 바꿨으면 그대로 둔다(되돌리기는 finally)
        return False
    return True


def _chat_unwide(cdp):
    """넓은 화면 흉내 되돌리기(CDP Emulation.clearDeviceMetricsOverride) — 실패해도 그만(예외를 내지 않는다)."""
    try:
        cdp.call("Emulation.clearDeviceMetricsOverride", {}, timeout=8)
    except Exception:  # noqa: BLE001
        pass


def _chat_count(cdp, tpre):
    """js_chat_count → (보이는 목록 항목 수, 그중 제목이 맞는 수) · 못 읽으면 None(셈으로 확인하지 않는다). 예외를 내지 않는다."""
    try:
        c = _jsd(cdp, js_chat_count(tpre), timeout=8)
    except Exception:  # noqa: BLE001 - 셈은 확인을 거드는 덤이다
        return None
    n, nt = c.get("n"), c.get("nt")
    if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (n, nt)):
        return n, nt
    return None


def _chat_find(cdp, cid, tpre, ctx, press, left):
    """_retire_steps ① — 대화 목록의 지금 대화 항목(js_chat_row find) → 마지막 js_chat_row 결과. 못 찾으면(none) 길만 연다 — 무엇을
    지울지는 정하지 않는다(항목은 늘 js_chat_row 의 같은 규칙 · 제목 확인은 호출자):
      ⓐ 대화 기록 펼침 단추(tg — 예전 그대로 한 번) ⓑ 탐색 창 단추(js_chat_navtg — 하나뿐일 때 한 번 · ⓐ 의 점은 다시 누르지 않음)
      ⓒ 넓은 화면 흉내(_chat_wide — 그 뒤 단계도 그 화면에서) 뒤 다시 보기 ⓓ 그래도 없으면 넓은 화면에서 ⓐ·ⓑ 를 한 번씩 더.
    누른 뒤 ~1.2초(넓은 화면은 ~1.5초) 기다려 다시 본다. 탐색 창 단추를 누른 수는 ctx['navtg']."""
    def look():
        return _jsd(cdp, js_chat_row(cid, "find", tpre))

    def opened(r):
        done = []
        tg = r.get("tg")
        if isinstance(tg, list) and len(tg) == 2:
            press({"x": tg[0], "y": tg[1]})
            done.append(tg)
            _sleep(1.2)
            r = look()
            if r.get("r") != "none":
                return r
        if left() <= 2:
            return r
        try:
            nv = _jsd(cdp, js_chat_navtg(done))
        except Exception:  # noqa: BLE001 - 길 찾기 실패는 '단추 없음'
            nv = {}
        if nv.get("r") == "ok":
            press(nv)
            ctx["navtg"] = int(ctx.get("navtg") or 0) + 1
            _sleep(1.2)
            r = look()
        return r

    r = look()
    if r.get("r") == "none":
        r = opened(r)
    if r.get("r") != "none" or left() <= 4 or not _chat_wide(cdp, ctx):
        return r
    _sleep(1.5)
    r = look()
    if r.get("r") == "none" and left() > 2:
        r = opened(r)
    return r


def _retire_steps(cdp, cfg, st, t_end, touched, ctx=None):
    """retire_chat 의 화면 단계 → 결과 코드. 누르기 전 확인을 모두 지나야 누른다(머리말). touched[0] = 무엇이든 눌렀다(끝에 Esc).
    ctx(LM28): 지금 주소의 대화 id 를 cid 로 돌려준다(화면 사유로 남길 때의 구조 조사용). 아직 답을 쓰는 중인 채팅은 아무것도 누르지 않고
    'gen'(남김 — 실패 아님) — 생성 중인 대화를 지우면 Copilot 이 다른 대화로 옮겨 가거나 지운 뒤에도 답이 남는다.
    LM28(2026-10-17) — 더 엄격하게, 그리고 접힌 목록에서도:
      · 화면 글은 끝 앵커 또는 머리 앵커로 본다(_page_is_ours — 긴 질문을 접어 첫 줄만 보이는 화면).
      · tpre(첫 프롬프트 앞부분 해시)가 없으면(예전 판이 연 채팅) 목록을 열지도 않고 'notitle'. 찾은 항목의 제목이 다르면(tm 0 — find 와
        more 두 번 본다) 그 항목은 누르지 않고 'notitle'.
      · 목록이 접혀 있으면 길만 연다(_chat_find — 펼침 단추·탐색 창 단추·넓은 화면 흉내). ctx 에 tm·navtg·wide 를 적는다(wide 는
        retire_chat 의 finally 가 되돌린다 — 뒤 단계는 그 화면에서 한다).
      · ⑤ 확인: 두 앵커가 모두 사라짐 · 대화 id 가 바뀜 · 화면은 그대로인데 메뉴를 열기 전에 센 목록 항목 수와 제목이 맞는 항목 수가 둘 다
        딱 1 줄어듦(js_chat_count) · 링크로 찾은 항목이 목록에서 사라짐 — 아니면 mismatch(멈춤)."""
    ctx = ctx if isinstance(ctx, dict) else {}

    def left():
        return t_end - time.time()

    def press(p, click=True):
        touched[0] = True
        _chat_mouse(cdp, p.get("x"), p.get("y"), click=click)

    txt = cdp.eval(js_chat_text(cfg), timeout=max(5.0, min(20.0, left())))
    if not _page_is_ours(txt, st):
        return "lost"
    cid, cid0 = conv_id(_chat_url(cdp), cfg), str(st.get("conv") or "")
    if cid and cid0 and cid != cid0:
        return "lost"
    ctx["cid"] = cid
    # ⓪ 아직 답을 쓰는 중이면 지우지 않는다(LM28 — 남김 'gen'). 물어보지 못했으면 예전처럼 다음 단계로(아래 확인들이 그대로 지킨다)
    try:
        if cdp.eval(js_is_generating(), timeout=8) is True:
            return "gen"
    except (TimeoutError, RuntimeError, OSError):
        pass
    # 목록 제목을 맞춰 볼 재료가 없다(예전 판이 연 채팅) — 아무것도 누르지 않고 남긴다
    tpre = st.get("tpre")
    if not (isinstance(tpre, dict) and tpre):
        return "notitle"
    # ① 대화 목록의 지금 대화 항목 — 목록이 접혀 있으면 길만 연다(펼침 단추 · 탐색 창 단추 · 넓은 화면 흉내)
    r = _chat_find(cdp, cid, tpre, ctx, press, left)
    if r.get("r") != "ok":
        return {"many": "ambiguous", "split": "ambiguous", "covered": "covered"}.get(str(r.get("r") or ""), "noitem")
    # 그 항목의 제목이 우리 첫 프롬프트의 앞부분이 아니면(사람의 대화가 '현재' 항목인 화면 등) 그 항목은 누르지 않는다
    ctx["tm"] = 1 if r.get("tm") == 1 else 0
    if not ctx["tm"]:
        return "notitle"
    if left() <= 0:
        return "timeout"
    c0 = _chat_count(cdp, tpre)         # ⑤ 의 셈 기준 — 메뉴를 열기 전(숫자만)
    # ② 그 항목 위에 신뢰 마우스(가려진 '추가 작업' 단추가 나타난다) → 그 항목 안의 단추(제목을 한 번 더 본다)
    press(r, click=False)
    _sleep(0.6)
    m = _jsd(cdp, js_chat_row(cid, "more", tpre))
    if m.get("r") != "ok":
        return {"many": "ambiguous", "split": "ambiguous", "covered": "covered", "nomore": "nomore"}.get(
            str(m.get("r") or ""), "noitem")
    if m.get("tm") != 1:
        ctx["tm"] = 0
        return "notitle"
    press(m)
    # ③ 메뉴 — 글자가 정확히 '삭제'인 항목 하나만
    mn = {}
    for _ in range(6):
        _sleep(0.4)
        mn = _jsd(cdp, js_chat_menu())
        if mn.get("r") != "nomenu":
            break
    if mn.get("r") != "ok":
        return {"nomenu": "nomenu", "covered": "covered", "many": "ambiguous"}.get(str(mn.get("r") or ""), "nodelete")
    if left() <= 0:
        return "timeout"
    press(mn)
    # ④ 확인 창 — 글자가 정확히 '삭제'인 단추만. 창이 뜨지 않으면 메뉴 클릭이 끝(확인 없는 화면)으로 보고 ⑤ 로
    seen = False
    for _ in range(8):
        _sleep(0.4)
        c = _jsd(cdp, js_chat_confirm())
        if c.get("r") == "ok":
            press(c)
            seen = False
            break
        seen = seen or c.get("r") in ("nobtn", "many", "covered")
    if seen:
        return "noconfirm"
    # ⑤ 확인 — 두 앵커가 화면에서 모두 사라졌나(지운 대화는 새 채팅 화면으로 바뀐다) · 주소의 대화 id 가 바뀌었나 · 화면은 그대로인데
    #   목록 항목 수와 제목이 맞는 항목 수가 둘 다 딱 1 줄었나(메뉴를 열기 전에 센 c0 — 다른 항목이 사라졌으면 제목 셈이 그대로라 아니다)
    for _ in range(16):
        _sleep(0.5)
        try:
            t2 = cdp.eval(js_chat_text(cfg), timeout=10)
        except (TimeoutError, RuntimeError, OSError):
            continue
        if not _page_is_ours(t2, st):
            return "deleted"
        if cid and conv_id(_chat_url(cdp), cfg) != cid:
            return "deleted"
        c1 = _chat_count(cdp, tpre) if c0 else None
        if c0 and c1 and c1[0] == c0[0] - 1 and c1[1] == c0[1] - 1:
            return "deleted"
    # 화면은 그대로인데 링크 주소로 찾았던 항목(강한 일치)이 목록에서 사라졌다 — 지워졌고 화면만 늦다
    if r.get("how") in ("href", "both") and _jsd(cdp, js_chat_row(cid, "find", tpre)).get("r") == "none":
        return "deleted"
    return "mismatch"


def retire_chat(cdp, cfg, why="", budget=CHAT_RETIRE_SEC):
    """다 쓴 우리 채팅(상태 파일 · 보낸 적 있음)을 Copilot 대화 목록에서 지운다 → 결과 코드(CHAT_WHY). 예외를 내지 않는다.
    새 채팅을 열기 직전(_fresh_chat — run_roundtrip·_run_parts·재시도 사다리)과 실행 끝 Edge 를 닫기 전(close_own_edge →
    retire_current)에만 부른다 — 왕복마다 부르지 않는다. 화면을 누르는 단계는 _retire_steps(머리말 참고).
    'none'(우리 것 아님)·'unsent'(열고 보내지 않음 — 목록에 없다)·'nocdp' 는 세지 않고, 그 밖은 지움(deleted) 또는 남김(+ 사유).
    LM28: 생성 중이면 'gen'(남김 — 실패 아님) · 화면 사유(CHAT_CENSUS_CODES)로 남기면 구조 조사(_chat_census — 숫자만)를 함께 남긴다.
    LM28(2026-10-17): 목록 제목이 우리 첫 질문과 다르거나 확인 재료가 없으면 'notitle'(누르지 않음 · 구조 조사함). 넓은 화면 흉내
    (_chat_wide)를 켰으면 어떻게 끝나든(예외·이른 반환 포함) finally 에서 되돌린다(_chat_unwide — 구조 조사·Esc 뒤). _retire_steps 의
    표시(wide·navtg·tm — 숫자)는 구조 조사와 copilot_trace 에 싣는다."""
    t0 = time.time()
    census, flags = None, None
    try:
        st = chat_state(cfg)
        if not st.get("ours"):
            return "none"
        if int(st.get("sent") or 0) <= 0:
            _chats_save(cfg, _chat_reset(st))
            return "unsent"
        if not _chat_on(cfg):
            code = "off"
        elif _CHAT_KILL[0] or _chat_held(st):
            code = "hold"
        elif cdp is None:
            return "nocdp"
        else:
            touched, ctx = [False], {}
            try:
                try:
                    code = _retire_steps(cdp, cfg, st, t0 + max(5.0, float(budget or CHAT_RETIRE_SEC)), touched, ctx)
                except Exception:  # noqa: BLE001 - 화면 조작 오류는 '남김'으로(왕복·닫기를 막지 않는다)
                    code = "error"
                if code in CHAT_CENSUS_CODES:
                    # 화면 사유로 남긴다 — 메뉴·확인 창을 닫기 전에 구조를 센다(읽기만 · 숫자만). 판정은 바꾸지 않는다.
                    census = _chat_census(cdp, cfg, ctx.get("cid") or str(st.get("conv") or ""), ctx)
                if touched[0] and code != "deleted":
                    _chat_esc(cdp)
            finally:
                if ctx.get("wide"):
                    _chat_unwide(cdp)                   # 넓은 화면 흉내는 어떻게 끝나든 되돌린다
            flags = {k: ctx[k] for k in CENSUS_CTX_KEYS if isinstance(ctx.get(k), int)}
        _chat_done(cfg, code, why, t0, census=census, flags=flags)
        return code
    except Exception:  # noqa: BLE001 - 정리가 왕복·닫기를 막지 않는다
        return "error"


def _fresh_chat(cdp, cfg, why="fresh", reload=False):
    """LM28 이 새 채팅을 여는 길(run_roundtrip·_run_parts — 새로 여는 곳을 늘리지 않는다): ① 다 쓴 우리 채팅을 지우고(retire_chat)
    ② 새 채팅(new_chat · reload 면 reload_page) ③ 그 채팅을 '우리 것(보내기 전)'으로 적는다(_chat_opened). → new_chat/reload_page 의 반환.
    새 채팅 단추를 눌렀는데 주소의 대화 id 가 그대로면(단추가 먹지 않음 · 지운 뒤 화면이 다른 대화로 옮겨 간 탭) 채팅 시작 주소로 다시
    들어간다(new_chat 의 '단추 없음' 길과 같은 새 채팅 하나) — 그대로 보내면 열려 있던 대화(남의 것일 수 있다)에 프롬프트가 들어간다.
    LM28(2026-10-17): 새 채팅으로 옮긴 것을 확인했는지(_chat_opened)를 _FRESH_OK[0] 에 적는다 — 보낼지는 _open_fresh 가 정한다."""
    retire_chat(cdp, cfg, why)
    pre = _chat_url(cdp)
    how = reload_page(cdp, cfg) if reload else new_chat(cdp, cfg)
    cid = conv_id(_chat_url(cdp), cfg)
    if not reload and cid and cid == conv_id(pre, cfg):
        how = reload_page(cdp, cfg)
    _FRESH_OK[0] = bool(_chat_opened(cdp, cfg, how, pre))
    return how


_FRESH_OK = [True]             # 마지막 _fresh_chat 이 새 채팅으로 옮긴 것을 확인했나(LM28 2026-10-17 — _open_fresh 가 본다)
NO_NEW_CHAT = (f"새 채팅이 열린 것을 확인하지 못해 보내지 않았습니다 — 사람이 쓰던 대화에 {lmname.SHORT} 질문이 들어가지 않게 "
               "(전용 Edge 의 Copilot 창에 '새 채팅' 단추가 보이는지 확인한 뒤 다시 실행하세요)")


def _screen_text(cdp, cfg):
    """지금 화면 글(js_chat_text) — 못 읽거나 글이 아니면 None."""
    try:
        t = cdp.eval(js_chat_text(cfg), timeout=30)
    except Exception:  # noqa: BLE001
        return None
    return t if isinstance(t, str) else None


def _same_screen(a, b):
    """두 화면 글이 같은 대화 그대로인가 — 공백을 한 칸으로 줄여 똑같고 40자 이상(짧은 글은 판단하지 않는다)."""
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    na, nb = re.sub(r"\s+", " ", a).strip(), re.sub(r"\s+", " ", b).strip()
    return len(na) >= 40 and na == nb


def _open_fresh(cdp, cfg, why="fresh", reload=False, guard_text=False):
    """LM28(2026-10-17) — 새 채팅을 열고(_fresh_chat) 옮긴 것을 확인 → new_chat/reload_page 의 반환(확인 못 하면 ""). 확인되지 않으면 채팅
    시작 주소로 한 번 더(새로 고침) 열어 본다. 사용자 요구: "이전에 사용자가 쓰고 있었던 채팅은 건드리면 안 된다" — 새 채팅으로 옮긴 것을
    확인하지 못한 화면(사람의 대화가 떠 있을 수 있다)에는 보내지 않는다(호출자가 왕복을 접는다 — NO_NEW_CHAT). 예외는 확인 못 함.
    guard_text: 지금 화면이 우리 채팅이 아닌 것을 안다(이어 보내기 확인 실패 — 사람의 대화일 수 있다) — 연 뒤 화면 글이 연 앞과 똑같으면
    (주소에 대화 id 가 없는 화면에서 새 채팅이 조용히 안 열림) 확인 못 한 것으로 본다."""
    for i, rl in enumerate((bool(reload), True)):
        if i and reload:
            break                                       # 이미 새로 고침으로 열어 봤다
        pre_t = _screen_text(cdp, cfg) if guard_text else None
        _FRESH_OK[0] = True
        try:
            how = _fresh_chat(cdp, cfg, why if not i else why + "-again", reload=rl)
        except Exception:  # noqa: BLE001 - 열다 오류 — 확인하지 못했다
            how, _FRESH_OK[0] = "", False
        if _FRESH_OK[0] and pre_t is not None and _same_screen(pre_t, _screen_text(cdp, cfg)):
            _FRESH_OK[0] = False                        # 화면이 그대로다 — 새 채팅으로 옮기지 못했다
            try:
                _chats_save(cfg, _chat_reset(chat_state(cfg)))   # 방금 '우리 것(보내기 전)'으로 적은 그 화면을 놓는다
            except Exception:  # noqa: BLE001
                pass
        if _FRESH_OK[0]:
            return str(how or "새 채팅")
        trace("chat", act="open", code="unconfirmed", again=i)
    return ""


def _no_new_chat(res=None):
    """새 채팅을 확인하지 못해 보내지 않은 왕복의 결과 — 앞 결과(res)가 있으면 그 답을 지키고 재시도 메모만 단다."""
    if isinstance(res, dict) and res:
        res["retry"] = "새 채팅이 열린 것을 확인하지 못해 재시도하지 않았습니다"
        return res
    return {"ok": False, "phase": "no_new_chat", "error": NO_NEW_CHAT,
            "hint": "전용 Edge 의 Copilot 창을 확인한 뒤 [AI 연결 진단]을 눌러 보세요"}


def _chat_tab_ws(cfg):
    """실행 끝 정리용 — 지금 열린 Copilot 채팅 탭(업무 호스트 · Outlook·Teams 아님)의 ws 주소. 탭을 만들거나 옮기지 않는다."""
    try:
        tabs = [t for t in http_json(cfg["port"], "/json") if isinstance(t, dict) and t.get("type") == "page"]
    except Exception:  # noqa: BLE001
        return ""
    for t in tabs:
        u = t.get("url")
        if page_kind(u, cfg) == "work" and not is_app_tab(u) and t.get("webSocketDebuggerUrl"):
            return str(t["webSocketDebuggerUrl"])
    return ""


def retire_current(cfg=None, why="end", budget=CHAT_RETIRE_SEC):
    """지금 탭의 우리 채팅을 지운다(실행 끝 · [AI 연결 진단] 왕복 뒤) → 결과 코드. 우리 Edge(프로필 포트)가 살아 있고 채팅 탭이
    있을 때만 화면에 닿는다 — 잠금(CHAT_LOCK_WAIT 초)을 못 얻으면 'busy', 탭이 없으면 'notab', Edge 가 없으면 'noedge'
    (그때는 소유를 그대로 둔다 — 다음 프로세스가 확인한다). 예외를 내지 않는다."""
    try:
        cfg = cfg if isinstance(cfg, dict) else load_cfg()
        st = chat_state(cfg)
        if not st.get("ours"):
            return "none"
        if int(st.get("sent") or 0) <= 0 or not _chat_on(cfg) or _CHAT_KILL[0] or _chat_held(st):
            return retire_chat(None, cfg, why)          # 화면에 닿지 않고 판정·세기만(보낸 적 없음·끔·멈춤)
        if not debugger_alive(cfg["port"]) or not owns_port(cfg):
            return "noedge"
        ws = _chat_tab_ws(cfg)
        if not ws:
            return "notab"
        with edge_lock(cfg, timeout=CHAT_LOCK_WAIT):
            cdp = CDP(ws)
            try:
                return retire_chat(cdp, cfg, why, budget=budget)
            finally:
                cdp.close()
    except EdgeBusy:
        return "busy"
    except Exception:  # noqa: BLE001 - 정리가 닫기·진단을 막지 않는다
        return "error"


def _tidy_chats(cfg, reason=""):
    """close_own_edge 의 닫기 전 정리 — retire_current(상한 CHAT_RETIRE_SEC) · 예외 없음."""
    try:
        return retire_current(cfg, "close:" + str(reason or "")[:16])
    except Exception:  # noqa: BLE001
        return "error"


CHAT_COUNTS = ("made", "deleted", "kept", "failed", "notfresh")


def chat_totals(cfg=None):
    """채팅 정리 누계(숫자·사유 코드만) — {made, deleted, kept, failed, notfresh, why{}, last_fail, ours(지금 우리 채팅이 남음),
    hold}. run.py 가 실행 시작·끝에 읽어 그 차이를 last_run 단계 'Copilot 채팅 정리' 로 남긴다."""
    st = chat_state(cfg)
    t = st.get("totals") if isinstance(st.get("totals"), dict) else {}
    out = {k: int(t.get(k) or 0) for k in CHAT_COUNTS}
    w = t.get("why") if isinstance(t.get("why"), dict) else {}
    out["why"] = {str(k): int(v or 0) for k, v in w.items()}
    out["last_fail"] = str(t.get("last_fail") or "")
    out["ours"] = bool(st.get("ours") and int(st.get("sent") or 0) > 0)
    out["hold"] = _chat_held(st)
    return out


def chat_delta(t0, t1):
    """두 누계(chat_totals)의 차이 — {made, deleted, kept, failed, notfresh, why{}, last_fail, left(지금 우리 채팅이 남음), hold}."""
    t0 = t0 if isinstance(t0, dict) else {}
    t1 = t1 if isinstance(t1, dict) else {}
    d = {k: max(0, int(t1.get(k) or 0) - int(t0.get(k) or 0)) for k in CHAT_COUNTS}
    w0, w1 = t0.get("why") or {}, t1.get("why") or {}
    d["why"] = {k: int(v or 0) - int(w0.get(k) or 0) for k, v in w1.items() if int(v or 0) - int(w0.get(k) or 0) > 0}
    d["last_fail"] = str(t1.get("last_fail") or "") if d["failed"] else ""
    d["left"] = bool(t1.get("ours"))
    d["hold"] = bool(t1.get("hold"))
    return d


def chat_busy(d):
    """정리 숫자에 한 일이 있나(만든·지운·남긴·맡지 않은 채팅) — 없으면 기록·로그 줄을 만들지 않는다."""
    return any(int((d or {}).get(k) or 0) for k in ("made", "deleted", "kept", "notfresh"))


def chat_note(d):
    """정리 숫자(chat_delta 꼴) → 한국어 한 줄 '만든 n · 지운 m · 남긴 k (사유: …)' — 제목·글은 없다."""
    d = d if isinstance(d, dict) else {}
    s = f"만든 {int(d.get('made') or 0)} · 지운 {int(d.get('deleted') or 0)} · 남긴 {int(d.get('kept') or 0)}"
    why = d.get("why") if isinstance(d.get("why"), dict) else {}
    if why:
        s += " (사유: " + ", ".join(f"{CHAT_WHY.get(k, k)} {n}" for k, n in sorted(why.items(), key=lambda x: -x[1])) + ")"
    if int(d.get("notfresh") or 0):
        s += f" · 새 채팅으로 확인되지 않아 맡지 않은 채팅 {int(d['notfresh'])}"
    if d.get("left"):
        s += " · 이어 쓰는 채팅 1개는 다음 새 채팅·실행 끝에 정리"
    if d.get("hold"):
        s += " · 삭제 멈춤 — 지운 뒤에도 채팅이 화면에 남아 더 지우지 않습니다(이 줄을 사진으로 보내 주세요)"
    return s


def chat_line():
    """단계 로그 한 줄(이 프로세스 몫) — '[copilot] 채팅 정리: 만든 n · 지운 m · 남긴 k (사유: …)'. 한 일이 없으면 "".
    LM28: 이 프로세스가 화면 사유로 남긴 적이 있으면 마지막 구조 조사를 둘째 줄 'CHAT_CENSUS_HEAD 사유 — 숫자들'로 붙인다."""
    p = _CHAT_PROC
    if not chat_busy(p):
        return ""
    left = False
    try:
        st = chat_state(None)
        left = bool(st.get("ours") and int(st.get("sent") or 0) > 0 and st.get("pid") == os.getpid())
    except Exception:  # noqa: BLE001
        left = False
    s = CHAT_LINE_HEAD + chat_note(dict(p, left=left, hold=_CHAT_KILL[0]))
    cz = p.get("census")
    if isinstance(cz, dict) and cz:
        s += "\n" + CHAT_CENSUS_HEAD + census_note(cz.get("code"), cz)
    return s


def chat_status(cfg=None):
    """[AI 연결 진단]·--diagnose 의 한 줄 — 마지막 정리 결과와 누계(숫자·사유만)."""
    cfg = cfg if isinstance(cfg, dict) else load_cfg()
    st = chat_state(cfg)
    t = chat_totals(cfg)
    last = ((st.get("totals") or {}).get("last") or {}) if isinstance(st.get("totals"), dict) else {}
    if not chat_busy(t):
        s = "아직 정리한 채팅 없음"
    else:
        s = f"누계 만든 {t['made']} · 지운 {t['deleted']} · 남긴 {t['kept']}"
        if isinstance(last, dict) and last.get("code"):
            s = f"마지막 {str(last.get('t') or '')[5:16]} {CHAT_WHY.get(last['code'], last['code'])} · " + s
        if t["last_fail"]:
            s += f" (마지막으로 남긴 까닭: {CHAT_WHY.get(t['last_fail'], t['last_fail'])})"
            cz = (st.get("totals") or {}).get("census") if isinstance(st.get("totals"), dict) else None
            if isinstance(cz, dict) and cz.get("code") == t["last_fail"]:
                s += " · 구조: " + census_note(cz.get("code"), cz).split(" — ", 1)[-1]
        if t["notfresh"]:
            s += f" · 새 채팅으로 확인되지 않아 맡지 않은 채팅 {t['notfresh']}"
    if not _chat_on(cfg):
        s += " · 설정으로 끔(copilotAuto.deleteChats=false)"
    if t["hold"]:
        s += " · 삭제 멈춤 — 지운 뒤에도 채팅이 화면에 남았습니다(이 줄을 사진으로 보내 주세요)"
    return s


TRACE_MAX = 4_000_000          # 이 크기를 넘으면 갈아 끼운다 — 로그가 조용히 커지지 않게


def trace(stage, **kw):
    """왕복 한 줄 기록 → report\\copilot_trace.jsonl.
    남기는 것: 단계·시각·프롬프트/답 **길이**·소요 초·완료 판정 방식·새 채팅 여부·성공 여부.
    남기지 않는 것: 프롬프트 원문·답 원문(신호 원문이 들어 있다·팀 서버로 나가지 않는다).
    실패해도 왕복을 막지 않는다 — 계측이 도구를 죽이면 안 된다."""
    try:
        p = os.path.join(ROOT, "report", "copilot_trace.jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            if os.path.getsize(p) > TRACE_MAX:
                os.replace(p, p + ".1")
        except OSError:
            pass
        row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "stage": stage}
        row.update(kw)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - 계측 실패가 판정을 막지 않게
        pass


def _traced(fn):
    """run_roundtrip / run_roundtrip_split 을 감싸 소요 시간을 남긴다."""
    def wrap(cfg, prompt, fresh=False, **kw):
        t0 = time.time()
        res = fn(cfg, prompt, fresh=fresh, **kw)
        try:
            r = res if isinstance(res, dict) else {}
            trace(os.environ.get("LM_STAGE", "") or fn.__name__,
                  sec=round(time.time() - t0, 1), prompt=len(prompt or ""),
                  reply=len(r.get("reply") or ""), ok=bool(r.get("ok")),
                  done_by=r.get("done_by", ""), gen=r.get("gen_sec", 0),
                  pick=r.get("pick", ""), pledge=bool(r.get("sentinel")),
                  fresh=bool(fresh), cut=bool(r.get("cut")),
                  parts=r.get("parts", 1), retry=r.get("retry", ""),
                  busy=r.get("busy_seen"),
                  slow=bool(r.get("slow")), stop=bool(r.get("stopped")), ext=r.get("ext_sec", 0),
                  resume=(fresh == RESUME),
                  phase=r.get("phase", ""), reason=r.get("reason", ""),
                  reload=bool(kw.get("reload")),
                  err=(r.get("error") or "")[:60])
        except Exception:  # noqa: BLE001
            pass
        return res
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def run_roundtrip(cfg, prompt, fresh=False, reload=False):
    """프롬프트 전송 → 응답 회수. Copilot 일시 오류('응답할 수 없습니다')나 무응답이면
    단계적으로 재시도한다: ① 새 채팅에서 같은 모델로 ② 새 채팅 + 자동 모델로.
    어느 단계에서 성공했는지 retry 노트로 남긴다.
    왕복 1회 총 예산은 cfg.roundtripMaxSec(0 이면 끔)다 — 사다리를 다 태우면 고정 대기까지 합쳐 한 왕복에
    30분이 들고(감사 실측), 그 동안 호출자는 아무것도 받지 못한다. 부모가 강제 종료하기 전에 **자식이
    스스로** 접어야 '정상 재시도 중' 이 죽지 않고 화면에 이유가 남는다.
    LM28 진단 A: 답이 사용량 제한 문구면(is_throttle_reply) 사다리 없이 phase 'throttled' 로 돌려준다(즉시 다시 보내면 제한이
    길어진다 — 쉬었다 다시 보내기는 호출자 몫). 오류 문구 뒤의 사다리 단계는 최대 30초 쉬고 보낸다. reload=True 면 새 채팅
    버튼 대신 채팅 페이지를 새로 고친 뒤 보낸다(오래 쓴 탭).
    LM28 채팅 정리: 새 채팅(fresh·reload·사다리 ①②)은 모두 _fresh_chat — 다 쓴 우리 채팅(사다리면 방금 실패한 채팅)을 먼저 대화
    목록에서 지운 뒤 연다. 새 채팅을 여는 곳은 늘리지 않았다.
    LM28: 답을 기다리던 중에 사용량 제한을 알아챈 왕복(_roundtrip_once 의 phase 'throttled')도 사다리를 타지 않고 그대로 돌려준다.
    LM28 느린 긴 답: slow(왕복 예산 안에 다 못 받은 답 — ok+cut)도 사다리를 타지 않고 그대로 돌려준다. fresh=RESUME(다음 단계의 첫
    왕복)이면 화면이 상태 파일의 우리 채팅일 때만(_resume_ok) 새 채팅 없이 이어 보내고, 아니면 fresh 와 같다.
    LM28(2026-10-17): 이어 보내기(fresh 거짓)도 화면이 이 프로세스의 우리 채팅에서 다른 대화로 옮겨 갔으면(_moved_away) 새 채팅에 보낸다."""
    _t_rt = time.time()
    _rt_max = max(0, int(cfg.get("roundtripMaxSec") or 0))
    global _RT_DEADLINE           # v3: 고정 대기(준비·입력창·유휴 폴링)도 왕복 예산 안에서 끝나게
    _RT_DEADLINE = (_t_rt + _rt_max) if _rt_max else None

    def _rt_left():
        return (_t_rt + _rt_max - time.time()) if _rt_max else 10 ** 6

    how = ensure_edge(cfg)
    if how is None:
        return edge_fail(cfg)
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "Copilot 탭을 만들 수 없음",
                "hint": "열린 Edge(자동 프로필) 창에서 직접 주소를 열어보세요: " + cfg["url"]}
    cdp = CDP(ws_url)
    activate(cdp)                     # 탭을 앞으로 — 비활성 탭은 답이 자라지 않는다(배경 스로틀링)

    def _err_pause(r):
        # 오류 문구 뒤에는 바로 다시 보내지 않는다 — 최대 30초 쉬고(왕복 예산 2.5분은 남긴다) 다음 단계로
        if r.get("ok") and is_error_reply(r.get("reply")):
            p = min(30.0, _rt_left() - 150)
            if p > 0:
                _sleep(p)
    try:
        if fresh == RESUME:
            # 다음 단계의 첫 왕복(LM28) — 화면이 상태 파일의 우리 채팅이면 새 채팅 없이 이어 보낸다. 아니면 예전처럼 새 채팅.
            ok_r = (not reload) and _resume_ok(cdp, cfg)
            _RESUMED[0] = ok_r
            fresh = not ok_r
        # LM28(2026-10-17) — 이어 보내기 직전 화면이 이 프로세스의 우리 채팅임을 확인하지 못하면(사람이 전용 Edge 에서 자기 대화를 누름 ·
        # 주소의 대화 id 가 다름 · 소유를 놓침) 그 대화에 보내지 않고 새 채팅을 연다 — 사람이 쓰던 채팅은 건드리지 않는다(사용자 요구).
        why_c = ""
        if not reload and not fresh:
            why_c = _continue_why(cdp, cfg)
            if why_c:
                fresh = True
                trace("chat", act=why_c)
        # 새 채팅은 늘 _open_fresh(→ _fresh_chat)로 연다 — 다 쓴 우리 채팅을 먼저 목록에서 지우고, 새 채팅을 '우리 것'으로 적는다(LM28 채팅
        # 정리). 새 채팅으로 옮긴 것을 확인하지 못하면 보내지 않는다(NO_NEW_CHAT — 열려 있던 대화는 사람의 것일 수 있다). 지금 화면이 우리
        # 채팅이 아닌 것을 알면(why_c) 단추 대신 채팅 시작 주소로 새로 들어가고, 화면 글이 그대로면 보내지 않는다(guard_text).
        if why_c:
            if not _open_fresh(cdp, cfg, "fresh", reload=True, guard_text=True):
                return _no_new_chat()
        elif reload:
            # 쉬었다 다시 보내기·chatTurns 회전 — 오래 쓴 탭은 새 채팅 버튼만으로는 실패가 이어졌다(진단 A).
            if not _open_fresh(cdp, cfg, "reload", reload=True):
                return _no_new_chat()
        elif fresh:
            # 판정처럼 '깨끗한 문맥'이 필요한 왕복은 새 채팅에서 시작한다 —
            # 앞선 실패 대화(예: 팀즈 조회 거절)가 문맥에 남으면 답이 오염된다.
            if not _open_fresh(cdp, cfg, "fresh"):
                return _no_new_chat()
        res = _once(cdp, cfg, prompt)
        # 사용량 제한 문구 — 사다리(새 채팅·자동 모델로 즉시 재전송)를 타지 않는다. 다시 보내면 제한이 길어진다.
        # (답을 기다리던 중에 알아챈 것은 이미 phase 'throttled' 로 온다)
        if res.get("phase") == "throttled":
            return res
        if res.get("ok") and is_throttle_reply(res.get("reply")):
            return _throttled(cfg, res.get("reply"))
        # LM28 — 느린 긴 답(slow: 왕복 예산 안에 다 못 받아 받은 데까지)은 사다리를 타지 않는다. 같은 프롬프트를 새 채팅에 다시 보내면
        # 같은 길이의 답을 또 기다리고, Copilot 은 앞 채팅들의 답을 뒤에서 마저 써 대화 목록에 같은 답이 쌓인다(현장 제보).
        if res.get("slow"):
            return res
        # 끊긴 답(cut)도 재시도 사유다 — 다만 앞부분에 잘린 JSON 이 남아 있을 수 있어 전부 실패하면
        # 그 답을 ok+cut 으로 돌려주고 호출자가 복구·부분 재시도한다(judge/refine 의 적응 분할).
        bad = ((res.get("ok") and (is_error_reply(res.get("reply")) or res.get("cut")))
               or res.get("phase") in ("no_reply", "empty_reply"))
        if not bad:
            return res
        # ① 새 채팅에서 같은 모델로 재시도 (대화 문맥 오염·일시 오류 해소)
        # 재시도는 **더 짧게 기다린다** — 1차가 replyTimeoutSec 를 다 쓰고 실패했다면 그 채팅·그 시각의
        # Copilot 이 느린 것이고, 같은 예산으로 세 번 기다리면 왕복 하나에 최악 24분이 든다(감사 실측).
        # 절반으로 줄여도 재시도 '횟수' 는 그대로라 회수 가능성은 유지되고 최악은 16분이 된다.
        cfg2 = dict(cfg)
        cfg2["replyTimeoutSec"] = max(120, int(cfg.get("replyTimeoutSec") or 480) // 2)
        # 빈 답·무응답이 한 번 확인된 뒤의 재시도는 '첫 글자 유예' 도 짧게 본다 — 유예 180초를 세 번 쓰면
        # 빈 답 한 건에 10분이 든다(감사 실측 · lm22 는 같은 상태를 24초에 끝냈다). 재시도 횟수는 그대로다.
        cfg2["firstTokenSec"] = max(30, int(cfg.get("firstTokenSec") or 180) // 2)
        if _rt_left() < 120:                   # 왕복 예산이 남지 않았다 — 있는 대로 돌려준다(호출자가 나눠 다시 묻는다)
            res["retry"] = f"왕복 예산 {_rt_max // 60}분을 다 써 재시도하지 않았습니다"
            return res
        _err_pause(res)
        cfg2["replyTimeoutSec"] = int(min(cfg2["replyTimeoutSec"], max(60, _rt_left() - 60)))
        # 실패한 채팅(우리 것이면)을 먼저 지우고 새 채팅 — 사다리가 대화 목록에 실패 채팅을 남기지 않게. 새 채팅을 확인하지 못하면 재시도하지
        # 않는다(LM28 2026-10-17 — 사람이 쓰던 대화에 보내지 않게)
        how2 = _open_fresh(cdp, cfg, "ladder1")
        if not how2:
            return _no_new_chat(res)
        res2 = _once(cdp, cfg2, prompt)
        if res2.get("phase") == "throttled":
            return res2
        if res2.get("ok") and is_throttle_reply(res2.get("reply")):
            return _throttled(cfg, res2.get("reply"))
        if res2.get("slow"):
            res2["retry"] = f"1단계 재시도(새 채팅 · {how2}) — 답이 길어 받은 데까지"
            return res2
        if res2.get("ok") and not is_error_reply(res2.get("reply")) and not res2.get("cut"):
            res2["retry"] = f"1단계 재시도 성공 (새 채팅 · {how2})"
            return res2
        # ② 새 채팅 + 자동 모델 폴백 (특정 모델 라우팅 장애 대비)
        if _rt_left() < 120:
            res2["retry"] = f"왕복 예산 {_rt_max // 60}분을 다 써 2단계 재시도는 하지 않았습니다"
            return res2 if res2.get("reply") else res
        _err_pause(res2)
        cfg2["replyTimeoutSec"] = int(min(cfg2["replyTimeoutSec"], max(60, _rt_left() - 60)))
        if not _open_fresh(cdp, cfg, "ladder2"):
            return _no_new_chat(res2 if res2.get("reply") else res)
        res3 = _once(cdp, cfg2, prompt, model_override="자동")
        if res3.get("phase") == "throttled":
            return res3
        if res3.get("ok") and is_throttle_reply(res3.get("reply")):
            return _throttled(cfg, res3.get("reply"))
        if res3.get("slow"):
            res3["retry"] = "2단계 재시도(새 채팅 + 자동 모델) — 답이 길어 받은 데까지"
            return res3
        if res3.get("ok") and not is_error_reply(res3.get("reply")) and not res3.get("cut"):
            res3["retry"] = "2단계 재시도 성공 (새 채팅 + 자동 모델)"
            return res3
        # 전부 실패 — 마지막 결과에 실패 이력. 끊긴 답 중에는 가장 긴 것을 남긴다(복구 재료).
        cuts = [r for r in (res, res2, res3) if r.get("ok") and r.get("cut") and not is_error_reply(r.get("reply"))]
        if cuts:
            final = max(cuts, key=lambda r: len(r.get("reply") or ""))
            final["retry"] = "끊긴 답 — 새 채팅·자동 모델 재시도에도 반복(잘린 앞부분만 회수)"
            return final
        final = res3 if res3.get("reply") else (res2 if res2.get("reply") else res)
        if final.get("ok") and is_error_reply(final.get("reply")):
            final = {"ok": False, "phase": "copilot_error", "reply": final.get("reply", ""),
                     "error": "Copilot 일시 오류 — 3단계 재시도 모두 실패",
                     "hint": "잠시 후 다시 실행하거나 Copilot 창에서 상태를 확인하세요"}
        final["retry"] = "새 채팅·자동 모델 재시도 모두 실패"
        return final
    finally:
        cdp.close()


def _once(cdp, cfg, prompt, model_override=None):
    """왕복 한 번(_roundtrip_once) + 끝난 뒤 우리 채팅의 주소(대화 id)·이번 왕복이 온전했는지 적기(_chat_seen — LM28 채팅 정리 ·
    다음 단계가 이어 쓸 수 있는지의 근거)."""
    res = _roundtrip_once(cdp, cfg, prompt, model_override=model_override)
    _chat_seen(cdp, cfg, ok=_rt_good(res))
    return res


def _rt_good(res):
    """온전한 왕복인가 — 답이 왔고 끊기지(cut·slow) 않았고 오류·사용량 제한 문구가 아니다."""
    r = res if isinstance(res, dict) else {}
    rep = r.get("reply")
    return bool(r.get("ok") and not r.get("cut") and not r.get("slow")
                and not is_error_reply(rep) and not is_throttle_reply(rep))


def build_anchor(prompt):
    """에코 앵커 — 페이지 텍스트에서 프롬프트 끝을 찾기 위한 표식.

    **반드시 개행이 없는 단 한 줄**이어야 한다. 예전에는 40자가 될 때까지 여러 줄을
    모아 공백으로 이어 붙였는데, 페이지 innerText 의 같은 자리에는 개행이 있어
    rfind 가 구조적으로 실패했다(실증: 현실적 4케이스 중 3개 -1). 앵커를 못 찾으면
    오프셋 폴백으로 떨어지고, 그 오프셋이 틀리면 응답 앞부분이 잘린다.

    마지막 8줄 중 '가장 긴 줄'을 쓴다 — 길수록 고유해서 에코 중간에 잘못 걸릴 위험이 낮다.
    """
    cands = [ln.strip() for ln in str(prompt or "").strip().splitlines() if ln.strip()][-8:]
    if not cands:
        return ""
    best = max(cands, key=len)
    return best[-100:] if len(best) >= 20 else ""


def pick_reply(txt, base, anchor):
    """페이지 전체 텍스트에서 '이번 응답'만 잘라낸다.

    ① 앵커를 찾았고 위치가 그럴듯하면 그 뒤 — 가장 정확하다.
    ② 앵커가 없어도 오프셋이 믿을 만하면 그 뒤.
    ③ 둘 다 아니면 **전문**. 자르는 것보다 안전하다 — 소비자는 rfind('{') 로 뒤에서부터
       JSON 을 찾으므로 앞에 메뉴·이전 대화가 섞여도 파싱에 지장이 없다. 반대로 잘못
       자르면 여는 '{' 가 날아가 응답이 통째로 버려진다.
    """
    if anchor:
        pos = txt.rfind(anchor)
        if pos >= 0 and pos >= base - 2000:
            return txt[pos + len(anchor):], "anchor"
    if base and base <= len(txt):
        # 오프셋이 페이지 안쪽을 가리킨다 = 아직 믿을 수 있다. 뒤가 짧아도(응답이 짧거나
        # 아직 도착 전) 그대로 쓴다 — 여기서 전문으로 넘기면 메뉴·이전 대화가 응답에
        # 섞인다(LM13 에서 고쳤던 결함의 재발 경로).
        return txt[base:], "offset"
    # base 가 페이지 길이보다 크다 = 인사말·추천 카드가 사라져 텍스트가 줄었다는 뜻.
    # 그 오프셋으로 자르면 응답 앞부분(여는 '{')이 날아간다 — 자르지 않는 편이 안전하다.
    return txt, "fulltext"


def _roundtrip_once(cdp, cfg, prompt, model_override=None):
    if True:
        # 페이지 로드/로그인 확인 — 업무 Copilot 호스트에서만 보낸다(개인 계정·공용 호스트·로그인 화면이면 보내지 않는다)
        state, kind = wait_page(cdp, cfg)
        stop = page_gate(cdp, cfg, state, kind)
        if stop is not None:
            return stop
        time.sleep(2)                          # SPA 렌더 여유
        # 앞 답이 아직 생성 중이면 끝날 때까지 기다린다 — 생성 중 전송 클릭은 '중지'가 되어 앞 답을
        # 끊고(잘린 JSON) 이번 프롬프트는 입력창에 남는다. 큰 사람의 연속 실패가 여기서 시작됐다.
        waited = wait_idle(cdp, secs=int(min(45, max(5, _dl_left(45)))))
        note_model = select_model(cdp, cfg, override=model_override)

        # 대형 DOM(긴 대화)에서 innerText 평가가 25초를 넘겨 왕복 전체가 error 로 죽던
        # 결함(검증 확정) — 응답 대기 루프(아래)와 같은 재수립 가드를 준다. 폴백은 0이
        # 아니라 재시도다: baseline=0 이면 앵커 미발견 시 페이지 전문이 응답으로 회수된다.
        try:
            t_base = cdp.eval(js_chat_text(cfg), timeout=30) or ""
        except TimeoutError:
            try:
                cdp.reconnect()
            except Exception:
                pass
            t_base = cdp.eval(js_chat_text(cfg), timeout=45) or ""
        baseline = len(t_base)
        # LM28 채팅 정리 — 이 화면이 우리 채팅인가(방금 연 새 채팅 · 우리 앵커가 보이는 채팅). 남의 대화면 보내도 우리 것이 아니다
        own = _chat_before_send(cdp, cfg, t_base)
        # 입력창은 **기다린다**. 예전엔 위의 time.sleep(2) 한 번이 유예의 전부여서, SPA 렌더가
        # 조금 늦거나 앞 답 정리가 겹치면 한 번 못 찾은 것이 곧 'input_not_found' 였다. 그 실패는
        # explain_failure 가 '사람이 손대야 풀리는 실패' 로 분류하는 이름이라, 일시적인 늦음 하나가
        # AI 판정 전체를 건너뛰게 만들었다(상위과제 분류 빈칸의 원인 — 실측). 조건을 폴링해
        # 여기서 끝까지 못 찾았을 때에만 영구 실패로 부른다.
        _ready_s = max(5, min(int(cfg.get("readyWaitSec") or 60), int(_dl_left(3600) * 0.5) or 5))
        _dl = time.time() + _ready_s
        ins = cdp.eval(js_focus(cfg))
        while not (ins and ins.get("ok")) and time.time() < _dl:
            time.sleep(1)
            ins = cdp.eval(js_focus(cfg))
        if not (ins and ins.get("ok")):
            dbg = cdp.eval(js_diagnose())
            dump = os.path.join(ROOT, "data", "copilot_auto_debug.json")
            os.makedirs(os.path.dirname(dump), exist_ok=True)
            with open(dump, "w", encoding="utf-8") as f:
                json.dump(dbg, f, ensure_ascii=False, indent=1)
            return {"ok": False, "phase": "input_not_found",
                    "error": f"채팅 입력창을 찾지 못함({_ready_s}초 대기)",
                    "hint": "data\\copilot_auto_debug.json 과 화면 스크린샷을 Claude에게 보여주면 선택자를 맞춰줄 수 있습니다"}
        # LM28 — 앞 전송(다른 단계 프로세스 포함)에서 minGapSec 이 지나야 보낸다(요청 몰림 → 「요청이 너무 많음」 방지).
        # 보내기 전에 이미 떠 있던 알림을 적어 둔다 — 보낸 뒤 새로 뜬 알림만 사용량 제한 근거로 본다.
        pace_wait(cfg)
        pre_notes = _notices(cdp) or []
        # 주입: CDP Input.insertText(IME/붙여넣기 수준 — 리치 에디터가 정상 수신) → 실패 시 예비 경로
        cdp.call("Input.insertText", {"text": prompt})
        time.sleep(0.4)
        got_in = cdp.eval(js_editor_text()) or ""
        if prompt.strip()[:15] not in got_in:
            cdp.eval(js_insert_fallback(prompt))
            time.sleep(0.4)
        time.sleep(0.5)
        sent = cdp.eval(js_click_send(cfg))
        if not (sent and sent.get("ok")):
            press_enter(cdp)                   # 전송 버튼이 없으면 Enter
        mark_sent(cfg)                         # 다음 전송의 간격 기준(minGapSec)
        # 전송 확인 — 클릭이 '중지' 버튼에 먹혔으면(앞 답 생성 중) 프롬프트가 입력창에 그대로 남는다.
        # 그때는 생성이 멎기를 기다렸다 한 번만 다시 보낸다(안 보내면 응답 대기가 통째로 시간 초과).
        resent = False
        time.sleep(1.0)
        try:
            left = cdp.eval(js_editor_text()) or ""
        except (TimeoutError, RuntimeError, OSError):
            left = ""
        head15 = prompt.strip()[:15]
        if head15 and head15 in left and len(left) >= len(prompt.strip()) * 0.8:
            wait_idle(cdp, secs=30)
            sent = cdp.eval(js_click_send(cfg))
            if not (sent and sent.get("ok")):
                press_enter(cdp)
            resent = True
            mark_sent(cfg)
        _chat_after_send(cdp, cfg, prompt, own)      # 우리 채팅이면 앵커 해시·보낸 수(첫 프롬프트면 '만든 채팅')

        # 에코 앵커: 프롬프트 마지막 줄을 채팅 텍스트에서 찾아 그 뒤를 응답으로 본다.
        # 문자 오프셋(baseline)만 쓰면 앞부분 재렌더(인사말 소멸·상대시각 갱신)에 슬라이스가 밀린다
        # 앵커는 '충분히 긴' 프롬프트 꼬리여야 한다 — "]" 한 글자면 에코 중간에 걸려 응답이 잘린다
        anchor = build_anchor(prompt)

        # 전송 직후 baseline 을 한 번 다시 잰다 — 새 채팅의 인사말·추천 카드는 첫 메시지를
        # 보내는 순간 DOM 에서 사라진다. innerText 가 append-only 가 아니라는 뜻이라,
        # 전송 전 baseline 을 그대로 쓰면 응답 앞부분(여는 '{' 포함)이 잘려 나간다.
        time.sleep(1.0)
        try:
            base = min(baseline, len(cdp.eval(js_chat_text(cfg), timeout=30) or ""))
        except (TimeoutError, OSError):
            base = 0                # 못 재면 자르지 않는다 — 전문 폴백이 안전하다

        # 응답 대기: 프롬프트 전송 이후 '새로 늘어난' 텍스트가 N회 연속 동일하면 완료
        t_wait0 = time.time()
        deadline = t_wait0 + min(float(cfg["replyTimeoutSec"]), _dl_left(10 ** 6))
        # ★ LM28 — deadline 은 기본 마감이다. 그때 답이 살아 있으면(SLOW_ALIVE_SEC 안에 SLOW_GROW_CHARS 자 이상 자람 · '중지' 버튼이
        #   보이면 SLOW_ALIVE_BUSY_SEC 안) 왕복 예산 끝(cap)까지 더 기다린다 — 절대 그 너머로는 아니다(머리말 '느린 긴 답').
        cap = (max(deadline, _RT_DEADLINE - SLOW_MARGIN_SEC) if _RT_DEADLINE is not None
               else deadline + SLOW_CAP_SEC)
        grow_len, grow_t, note_t, ext, gen = 0, t_wait0, 0.0, 0.0, None
        how = "anchor"
        last, last_key, stable, idle = None, None, 0, 0
        # ★ '중지' 버튼을 이 왕복에서 **한 번이라도 봤는가**. js_is_generating 은 못 찾으면 False(생성 중 아님)
        #   로 답하는, wait_idle 용의 '막지 않는 쪽이 안전한' 함수다. 그것을 조기 완료 판정에 그대로 쓰면 방향이
        #   반대다 — UI 의 버튼 표기가 후보 문구와 안 맞으면 '깊이 생각하기' 가 12초만 멈춰도 답을 쓰는 도중에
        #   회수한다(시뮬레이션: 멈춤 12~24초에서 답의 33% 만 회수 · LM24 는 온전). 잘린 답은 빠진 행 재질문을
        #   낳아 왕복이 배로 는다(제보: 분석 시간 2배). 버튼을 본 적이 있을 때에만 '사라짐' 을 완료 신호로 믿고,
        #   본 적이 없으면 예전 규칙(stablePolls)으로만 판정한다 — 선택자가 안 맞는 UI 에서는 LM24 와 같아진다.
        busy_seen = False
        # ★ 첫 글자가 오기 전의 '생각' 구간은 답이 멈춘 것이 아니다. 앵커 뒤에는 프롬프트 에코 꼬리가 남아
        #   new.strip() 이 참이라, 예전엔 그 상태가 stablePolls 만큼 이어지면(24~27초) 빈 답을 ok 로 돌려줬다
        #   (감사 실측 — LM24 공통). judge 는 '빈 성공' 을 JSON 없음으로 보고 청크를 반으로 나눠 다시 물어
        #   왕복이 3배가 됐다. 여기서는 (버튼이 보이거나 firstTokenSec 안이면) 빈 몸통을 세지 않고,
        #   그래도 끝내 비었으면 ok=False(empty_reply) 로 돌려 재시도 사다리(새 채팅)를 타게 한다.
        first_token_s = max(30, min(int(cfg.get("firstTokenSec") or 180), int(_dl_left(3600))))
        t_gen0 = time.time()          # 계측용 — 전송 뒤 첫 폴부터 완료까지
        # ★ LM28 — 사용량 제한 빠른 감지. 「요청이 너무 많음」이 답 말풍선으로 오면 예전에도 안정 폴링(stablePolls) 뒤 알아챘지만,
        #   알림(토스트·배너)으로 뜨거나 답 자리가 비면 firstTokenSec·replyTimeoutSec 을 다 기다리고 새 채팅 사다리로 두 번 더
        #   보냈다(왕복 하나에 수 분 · 재전송마다 제한이 길어짐). 이제 답 머리(짧은 산문·JSON 없음)나 보낸 뒤 새로 뜬 알림에 제한
        #   문구가 있고 그 글이 그대로면(_throttle_settled) 바로 throttled 로 돌려준다. 글 원문은 찍지 않는다.
        thr_last, thr_n = None, 0
        while True:
            now = time.time()
            if now >= deadline:
                alive = (now - grow_t < SLOW_ALIVE_SEC) or (gen is True and now - grow_t < SLOW_ALIVE_BUSY_SEC)
                if now >= cap or not alive:
                    break
                if now - note_t >= SLOW_NOTE_SEC:
                    note_t = now
                    _slow_note(now - t_wait0, cap - now, grow_len)
                ext = now - deadline
            time.sleep(cfg["pollSec"])
            try:
                txt = cdp.eval(js_chat_text(cfg), timeout=30) or ""
            except TimeoutError:
                # 대형 DOM innerText가 렌더러를 오래 점유한 경우 — 연결 재수립 후 계속 대기
                try:
                    cdp.reconnect()
                except Exception:
                    pass
                continue
            new, how = pick_reply(txt, base, anchor)
            if has_pledge(new, prompt, anchor, how):
                # 조기 완료: 서약([[전송끝]])은 답의 맨 마지막 줄이므로 보이는 순간 생성이 끝난
                # 것이다 — stablePolls 를 기다리지 않는다(그래서 stablePolls 를 넉넉히 잡아도
                # 평소 왕복이 느려지지 않는다). 한 번만 더 읽어 렌더 꼬리(각주 등)를 담는다.
                time.sleep(1.0)
                try:
                    txt2 = cdp.eval(js_chat_text(cfg), timeout=30) or ""
                    new2, how2 = pick_reply(txt2, base, anchor)
                    if has_pledge(new2, prompt, anchor, how2):
                        new, how = new2, how2
                except (TimeoutError, OSError, RuntimeError):
                    pass
                return _reply_result(strip_echo(new, prompt, anchor, how), note_model, how, True,
                                     waited, resent, gen_sec=time.time() - t_gen0, done_by="pledge",
                                     busy_seen=busy_seen, ext_sec=ext)
            # 버튼 상태는 매 폴 본다(버튼 목록 훑기 — innerText 보다 훨씬 가볍다). 텍스트가 늘고 있는 동안
            # 버튼이 보이면 '이 UI 에서 선택자가 맞는다' 는 증거가 된다.
            try:
                gen = bool(cdp.eval(js_is_generating(), timeout=10))
            except (TimeoutError, OSError, RuntimeError):
                gen = None            # 못 물어봤으면 판단하지 않는다(안전 쪽)
            if gen:
                busy_seen = True
            body = strip_echo(new, prompt, anchor, how).strip()     # 에코 꼬리를 걷어낸 '진짜 답'
            if is_throttle_reply(body):
                cand, via = body, "reply"
            else:
                cand, via = _new_notice(cdp, pre_notes, prompt), "notice"
            if cand:
                thr_n = thr_n + 1 if cand == thr_last else 0
                thr_last = cand
                if _throttle_settled(thr_n, gen, busy_seen, cfg["pollSec"]):
                    return dict(_throttled(cfg, cand), done_by="throttle", via=via, busy_seen=busy_seen,
                                gen_sec=round(time.time() - t_gen0, 1), waited=waited, resent=resent)
            else:
                thr_last, thr_n = None, 0
            if len(body) >= grow_len + SLOW_GROW_CHARS:
                grow_len, grow_t = len(body), time.time()          # 답이 자랐다 — 기본 마감 뒤 연장의 근거
            # ★ LM28 — '같은 글' 판정은 JSON 꼴 답이면 마지막 닫는 괄호까지만 본다(_stable_view). 답 뒤의 화면 잡음(상대 시각·추천
            #   질문 칩·꼬리말)이 바뀌어도 완료를 알아챈다 — 예전에는 잡음 때문에 끝난 답을 시간 초과로 버리고 새 채팅에 다시 보냈다.
            #   '중지' 버튼이 보이는 동안(생성 중)은 예전처럼 전체 글로 본다 — 닫힌 JSON 뒤에 아직 쓰는 글을 멈춤으로 보지 않게.
            key = _stable_view(body) if (body and gen is not True) else new
            if not body and (gen or (time.time() - t_gen0) < first_token_s):
                # 아직 첫 글자가 없다 — 생각 중이다(버튼이 보이거나 유예 안). 멈춘 답으로 세지 않는다.
                stable, idle = 0, 0
            elif new.strip() and key == last_key:
                stable += 1
                # 텍스트가 멈췄고, 버튼을 본 적이 있는데 지금은 없다 → 생성이 끝난 것. stablePolls 를 끝까지
                # 기다릴 이유가 없다(예전엔 서약을 못 잡은 왕복마다 8회 × 3초 = 24초를 흘려보냈다).
                # 틀릴 수 있으므로 **2회 연속** 확인한다. 버튼을 본 적이 없으면 이 지름길은 쓰지 않는다.
                # 답이 JSON 꼴이면 괄호가 닫혔을 때만 — '생각 중' 에 버튼을 잠깐 숨기는 UI 에서 반쪽 JSON 을 집지 않게.
                if busy_seen and gen is False and _looks_closed(new):
                    idle += 1
                else:
                    idle = 0
                if (stable >= cfg["stablePolls"]) or (stable >= 2 and idle >= 2):
                    if not body:
                        # 유예를 넘겼는데도 답이 비었다 — '빈 성공' 이 아니라 실패다. 호출자(run_roundtrip)의
                        # 사다리가 새 채팅에서 다시 보낸다. 예전엔 ok=True·"" 로 돌아가 judge 가 반분했다.
                        return {"ok": False, "phase": "empty_reply", "error": "답이 비어 있음(첫 글자가 오지 않음)",
                                "reply": "", "sentinel": False, "busy_seen": busy_seen,
                                "gen_sec": round(time.time() - t_gen0, 1),
                                "hint": "Copilot 이 생각만 하다 답을 내지 않았습니다 — 새 채팅에서 다시 보냅니다"}
                    # 어떤 경로로 회수했는지 남긴다 — fulltext 가 잦으면 앵커가 깨진 것이다
                    return _reply_result(strip_echo(new, prompt, anchor, how), note_model, how, False,
                                         waited, resent, gen_sec=time.time() - t_gen0,
                                         done_by=("idle" if stable < cfg["stablePolls"] else "stable"),
                                         busy_seen=busy_seen, ext_sec=ext)
            else:
                stable, idle = 0, 0
            last, last_key = new, key
        # 마감(기본 마감에 답이 멈춰 있었거나 왕복 예산 끝) — 아직 쓰는 중이면 '중지' 단추 하나만 눌러 끊고(뒤에서 마저 쓴 답이 목록에
        # 남지 않게) 받은 데까지를 ok+cut+slow 로 돌려준다. run_roundtrip·judge 는 slow 를 다시 보내지 않는다(호출자가 빠진 것만 작게).
        stopped = _stop_generation(cdp)
        if stopped:
            try:
                new2, how2 = pick_reply(cdp.eval(js_chat_text(cfg), timeout=30) or "", base, anchor)
                if len(strip_echo(new2, prompt, anchor, how2).strip()) >= len(strip_echo(last or "", prompt, anchor, how).strip()):
                    last, how = new2, how2
            except (TimeoutError, OSError, RuntimeError):
                pass
        body = strip_echo(last or "", prompt, anchor, how).strip()
        if body:
            return _reply_result(body, note_model, how, False, waited, resent, gen_sec=time.time() - t_gen0,
                                 done_by="slow", busy_seen=busy_seen, cut=True, slow=True, stopped=stopped,
                                 ext_sec=ext)
        return {"ok": False, "phase": "no_reply", "error": "응답 시간 초과",
                "reply": (last or "").strip(), "sentinel": False, "stopped": stopped,
                "hint": "Copilot 창이 응답을 생성 중인지 확인 — 반복되면 화면 스크린샷을 Claude에게"}


def _stable_view(body):
    """'같은 글' 판정에 쓰는 답 — JSON 꼴이면 마지막 닫는 괄호('}'·']')까지, 그 앞이 괄호 수로 닫혀 있을 때만(_looks_closed). 아직
    쓰는 중인 JSON(바깥 괄호가 열림)·산문은 그대로 — 긴 문자열 하나를 쓰는 동안 반쪽 JSON 을 '멈춤' 으로 보지 않게."""
    s = str(body or "")
    if "{" not in s and "[" not in s:
        return s
    k = max(s.rfind("}"), s.rfind("]"))
    if k < 0:
        return s
    head = s[:k + 1]
    return head if _looks_closed(head) else s


def _looks_closed(reply):
    """답이 JSON 꼴({ 나 [ 가 있음)이면 괄호가 모두 닫혔는가 — 산문이면 항상 참.
    잘린 JSON 을 '완료' 로 집지 않기 위한 값싼 확인이다(파싱이 아니라 개수만 본다)."""
    s = str(reply or "")
    if "{" not in s and "[" not in s:
        return True
    return s.count("{") <= s.count("}") and s.count("[") <= s.count("]")


def _reply_result(reply, note_model, how, sentinel, waited=0, resent=False,
                  gen_sec=0.0, done_by="", busy_seen=None, cut=None, slow=False, stopped=None, ext_sec=0.0):
    """회수 결과 dict — cut(생성 중단 문구가 꼬리에 있음)·waited(앞 답 생성 대기 초)·resent(전송 재클릭)
    를 함께 남겨 호출자가 잘린 답을 복구·부분 재시도할 수 있게 한다.
    gen_sec·done_by 는 계측용 — 답을 기다린 초와 무엇으로 완료를 알았는지
    (pledge=서약 / idle=중지 버튼 사라짐 / stable=같은 텍스트 반복 / slow=왕복 예산 끝에 받은 데까지).
    LM28: slow=True(느린 긴 답 — 예산 안에 다 못 받음)면 cut 도 참이다 · stopped = '중지' 단추를 눌렀나 · ext_sec = 기본 마감 뒤 더 기다린 초."""
    reply = (reply or "").strip()
    out = {"ok": True, "phase": "replied", "reply": reply, "model": note_model, "pick": how,
           "sentinel": bool(sentinel), "cut": is_cut_reply(reply) if cut is None else bool(cut)}
    if slow:
        out["slow"] = True
    if stopped is not None:
        out["stopped"] = bool(stopped)
    if ext_sec:
        out["ext_sec"] = round(float(ext_sec), 1)
    if waited:
        out["waited"] = waited
    if resent:
        out["resent"] = True
    if gen_sec:
        out["gen_sec"] = round(gen_sec, 1)
    if done_by:
        out["done_by"] = done_by
    if busy_seen is not None:
        out["busy_seen"] = bool(busy_seen)     # 이 왕복에서 '중지' 버튼을 봤는가 — 선택자가 UI 와 맞는지의 증거
    return out


# ── 분할 전송 (보완툴 AutoSend 이식) ──────────────────────────────────────
def _wait_rest(cdp, cfg, prompt, secs=300):
    """서약이 안 보인다 = 아직 쓰는 중일 수 있다 — **아무것도 보내지 않고** 같은 탭을
    다시 읽으며 서약이 나올 때까지 기다린다. 앵커(이번 프롬프트 꼬리)를 못 찾으면 None
    (이번 답의 시작점을 모르면 옛 서약을 오인할 수 있다). 60초째 그대로면 '끝났는데 서약만
    빠뜨린 답' 으로 보고 그 텍스트를 돌려준다."""
    anchor = build_anchor(prompt)
    if not anchor:
        return None
    deadline = time.time() + min(float(secs), _dl_left(10 ** 6))
    last, quiet = None, 0
    while time.time() < deadline:
        time.sleep(5)
        try:
            txt = cdp.eval(js_chat_text(cfg), timeout=30) or ""
        except TimeoutError:
            try:
                cdp.reconnect()
            except Exception:
                pass
            continue
        except (OSError, RuntimeError):
            continue                     # 대형 DOM 평가 지연은 다음 폴에
        reply, how = pick_reply(txt, 0, anchor)
        if how != "anchor":
            return None
        if has_pledge(reply, prompt, anchor, how):
            return strip_echo(reply, prompt, anchor, how).strip()
        quiet = quiet + 1 if reply == last else 0
        last = reply
        if quiet >= 12:                  # 60초째 그대로 = 끝났는데 서약만 빠뜨린 답
            return strip_echo(reply, prompt, anchor, how).strip() or None
    return strip_echo(last or "", prompt, anchor, "anchor").strip() or None


def _run_parts(cdp, cfg, parts, fresh, deadline=None, reload=False):
    """같은 CDP·같은 채팅에서 조각을 차례로 보낸다 — 조각별 _roundtrip_once, 사다리 없음.
    조각마다 서약을 확인하고, 없으면 _wait_rest 로 기다린 뒤에만 다음 조각을 보낸다.
    deadline(epoch 초): 넘기면 조각을 더 보내지 않고 시간 초과로 접는다 — 예전에는 이 다부 경로에
    왕복 예산이 없어 한 왕복이 76~80분까지 무제동으로 돌았다(제보 ④ · 검증 CONFIRMED).
    LM28 진단 A: 어느 조각의 답이든 사용량 제한 문구면 바로 phase 'throttled'. reload=True 면 새 채팅 대신 페이지 새로 고침.
    LM28 채팅 정리: 새 채팅은 _fresh_chat(다 쓴 우리 채팅 — 전체 재시도면 방금 실패한 나눔 채팅 — 을 먼저 지운다).
    LM28 느린 긴 답: 어느 조각이든 slow(왕복 예산 끝에 받은 데까지)면 _wait_rest 로 더 기다리거나 남은 조각을 보내지 않고 그대로 돌려준다
    (ok — 호출자 run_roundtrip_split 이 새 채팅 전체 재전송을 하지 않는다). fresh=RESUME·이어 보내기 확인(_continue_why)·새 채팅 확인
    (_open_fresh — 확인 못 하면 보내지 않음)은 run_roundtrip 과 같다. 둘째 조각부터도 보내기 직전에 화면이 우리 채팅인지 보고, 아니면 남은
    조각을 보내지 않는다(LM28 2026-10-17 — 조각 사이에 사람이 다른 대화를 눌렀어도 그 대화에 넣지 않는다)."""
    total = len(parts)
    if fresh == RESUME:
        ok_r = (not reload) and _resume_ok(cdp, cfg)
        _RESUMED[0] = ok_r
        fresh = not ok_r
    why_c = ""
    if not reload and not fresh:
        why_c = _continue_why(cdp, cfg)  # LM28(2026-10-17) — 우리 채팅임을 확인하지 못하면 새 채팅(run_roundtrip 과 같다)
        if why_c:
            fresh = True
            trace("chat", act=why_c)
    if why_c:
        if not _open_fresh(cdp, cfg, "fresh", reload=True, guard_text=True):
            return dict(_no_new_chat(), parts=total)
    elif reload:
        if not _open_fresh(cdp, cfg, "reload", reload=True):
            return dict(_no_new_chat(), parts=total)
    elif fresh:
        if not _open_fresh(cdp, cfg, "fresh"):
            return dict(_no_new_chat(), parts=total)
    res = {"ok": False, "phase": "error", "error": "왕복 시작 실패"}
    for i, part in enumerate(parts, 1):
        if deadline is not None and time.time() > deadline:
            return {"ok": False, "phase": "timeout", "parts": total,
                    "error": f"나눔 {i}/{total}: 왕복 예산을 넘겨 중단(이 청크는 규칙 판정으로)",
                    "hint": "Copilot 응답 지연 — config.copilotAuto.roundtripMaxSec"}
        if i > 1:
            why_c = _continue_why(cdp, cfg)
            if why_c:
                trace("chat", act=why_c, part=i)
                return {"ok": False, "phase": "moved", "parts": total,
                        "error": f"나눔 {i}/{total}: 화면이 {lmname.SHORT} 채팅이 아니어서 남은 조각을 보내지 않았습니다(사람이 쓰던 대화에 넣지 않게)",
                        "hint": "전용 Edge 의 Copilot 창에서 다른 대화를 누르지 마세요 — 다음 왕복은 새 채팅에서 다시 보냅니다"}
        res = _once(cdp, cfg, part)
        if not res.get("ok"):
            res["error"] = f"나눔 {i}/{total}: " + str(res.get("error") or "왕복 실패")
            return res
        reply = res.get("reply") or ""
        if is_throttle_reply(reply):
            return dict(_throttled(cfg, reply), parts=total)
        if res.get("slow"):
            res["parts"] = total
            res["note"] = f"나눔 {i}/{total}: 답이 길어 왕복 예산 안에 받은 데까지만 돌려줍니다(다시 보내지 않음)"
            return res
        if not res.get("sentinel"):
            more = _wait_rest(cdp, cfg, part)
            if more:
                reply = more
                res["reply"] = more
                res["sentinel"] = SENTINEL in more      # _wait_rest 는 에코를 걷어낸 답만 돌려준다
            if not res.get("sentinel"):
                if not reply.strip():
                    return {"ok": False, "phase": "no_reply",
                            "error": f"나눔 {i}/{total}: 응답을 받지 못했습니다",
                            "hint": "Copilot 창에서 생성이 멈췄는지 확인하세요"}
                if more is None:
                    # 관찰이 불가능했다 — 생성 중일 수 있으니 넉넉히 기다린 뒤 진행
                    # (생성 중에 다음을 보내면 전송 버튼이 '중지'가 되어 답을 끊는다)
                    time.sleep(min(30.0, max(1.0, _dl_left(30))))
                res["note"] = f"나눔 {i}/{total}: 서약 없이 생성 정지 확인 후 진행"
        if is_throttle_reply(reply):
            return dict(_throttled(cfg, reply), parts=total)
        if is_error_reply(reply):
            # 중간 조각의 일시 오류도 실패다 — 그 조각을 '받지 못한' 채 이어 가면 마지막
            # 답이 반쪽 자료로 만들어진다. 스테이지 전체를 새 채팅에서 다시 보낸다(호출자).
            return {"ok": False, "phase": "copilot_error", "reply": reply,
                    "error": f"나눔 {i}/{total}: Copilot 일시 오류 응답", "hint": reply[:80]}
        if i < total and "받았습니다" not in reply and len(reply) > 400:
            # 중간 조각에 확인 문구 대신 긴 답이 왔다 = 자료를 다 받기 전에 분석을 시작했을 수 있다.
            # 마지막 답이 앞 조각만으로 만들어질 위험 — 실패는 아니므로 표식만 남긴다(호출자 로그).
            res["note"] = f"나눔 {i}/{total}: 확인 문구 없이 긴 답({len(reply)}자) — 조기 분석 가능성"
    res["parts"] = total
    return res


def run_roundtrip_split(cfg, prompt, fresh=False, reload=False):
    """--send 의 기본 경로. 한 조각이면 서약 지시를 덧붙여 기존 run_roundtrip(재시도 사다리
    유지). 여러 조각이면 같은 채팅에 차례로 보내고, 실패하면 새 채팅에서 전체를 1회 재시도.
    결과 dict 형식은 run_roundtrip 과 같고 parts(조각 수)만 더한다. reload: 첫 시도 전에 채팅 페이지 새로 고침.
    사용량 제한(throttled)이면 새 채팅 전체 재시도도 하지 않는다."""
    parts = make_parts(prompt, reserve=len(PLEDGE_TAIL))
    if len(parts) == 1:
        res = (run_roundtrip(cfg, prompt + PLEDGE_TAIL, fresh=fresh, reload=True) if reload
               else run_roundtrip(cfg, prompt + PLEDGE_TAIL, fresh=fresh))
        res["parts"] = 1
        return res
    how = ensure_edge(cfg)
    if how is None:
        return dict(edge_fail(cfg), parts=len(parts))
    # 왕복 예산 — 단부 run_roundtrip:826-836 과 같은 상한을 다부 경로에도 건다(제보 ④)
    _rt_max = max(0, int(cfg.get("roundtripMaxSec") or 0))
    _deadline = (time.time() + _rt_max) if _rt_max else None
    global _RT_DEADLINE
    _RT_DEADLINE = _deadline      # v3: 다부 경로의 고정 대기도 같은 마감을 본다
    res = {"ok": False, "phase": "error", "error": "왕복 시작 실패"}
    for attempt in (1, 2):
        ws_url = find_tab(cfg)
        if not ws_url:
            return {"ok": False, "phase": "launch_failed", "error": "Copilot 탭을 만들 수 없음",
                    "parts": len(parts),
                    "hint": "열린 Edge(자동 프로필) 창에서 직접 주소를 열어보세요: " + cfg["url"]}
        cdp = CDP(ws_url)
        activate(cdp)                    # 탭을 앞으로 — 비활성 탭은 답이 자라지 않는다(배경 스로틀링, v24.13)
        try:
            res = _run_parts(cdp, cfg, parts, fresh=(True if attempt == 2 else fresh), deadline=_deadline,
                             reload=bool(reload and attempt == 1))
        except Exception as e:
            res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}"}
        finally:
            cdp.close()
        if res.get("ok"):
            if attempt == 2:
                res["retry"] = "나눔 전송 실패 → 새 채팅에서 전체 재전송 성공"
            res["parts"] = len(parts)
            return res
        if attempt == 1 and res.get("phase") in ("login_required", "input_not_found", "launch_failed", "throttled"):
            break                        # 사람이 개입해야 하는 상태(로그인·개인 계정·죽은 프로필)·사용량 제한 — 재시도해도 같다
    res["parts"] = len(parts)
    res["retry"] = "나눔 전송 · 새 채팅 전체 재시도 모두 실패"
    return res


# ── 테스트 전용 스텁 ─────────────────────────────────────────────────────
# LM_COPILOT_STUB=<dir> 이면 --send 가 Edge 를 띄우지 않고 <dir> 의 JSON 파일을 응답으로
# 돌려준다. 회귀 시험 전용 — run.py 경로는 judge/refine/agentic/flow 가 자식 프로세스라
# in-process 모의 sender 가 닿지 않기 때문에 드라이버에 분기가 있어야 한다.
# 배포 환경에서는 이 변수를 두지 않는다. 산출물에는 phase "stub" 으로 흔적이 남는다.
# 파일 선택: 프롬프트의 출력 형식 예시에서 **가장 앞에 나오는** 키가 최상위 키다
# (taxonomy 는 {"models":[{"name","match"…}]} 라 "match" 도 품고, groups 는 "items" 를
# 품는다 — 먼저 나온 키를 고르면 바깥 키가 이긴다). 키가 없는 판정 이어짐 청크("계속입니다…")는
# 본문 형식(#번호 | 시각 | …)으로 알아본다. <dir>/stub_map.json ({"부분문자열": "파일명"}) 이
# 있으면 그것을 먼저 본다. 아무것도 안 맞으면 default.json.
STUB_KEYS = (
    ('"flows"', ("flow.json", "flows.json")),                      # flow.py
    ('"new"', ("agentic.json", "new.json")),                       # agentic.py(LM29부터 — 니즈 후보 {"new":[…]})
    ('"groups"', ("groups.json", "detail3.json")),                 # core/details 세부업무 병합
    ('"items"', ("refine.json", "items.json")),                    # refine.py
    ('"summary"', ("narrative.json", "summary.json")),             # judge 월별 내러티브
    ('"j":', ("judge_rows.json", "judge.json", "j.json")),         # judge 신호 판정
    ('"models"', ("judge_models.json", "models.json")),            # judge 체계 수립·통합
)
STUB_BODY_PATTERNS = (
    (re.compile(r"^#\d+ \| \d{4}-\d{2}-\d{2}", re.M), ("judge_rows.json", "judge.json", "j.json")),
)



run_roundtrip = _traced(run_roundtrip)
run_roundtrip_split = _traced(run_roundtrip_split)

def stub_candidates(prompt):
    """프롬프트 → 스텁 파일 후보 이름 목록(우선순위 순)."""
    hits = [(prompt.find(k), k, names) for k, names in STUB_KEYS if k in prompt]
    cands = []
    if hits:
        cands.extend(min(hits)[2])
    else:
        for pat, names in STUB_BODY_PATTERNS:
            if pat.search(prompt):
                cands.extend(names)
                break
    cands.append("default.json")
    return cands


def stub_dir():
    d = (os.environ.get("LM_COPILOT_STUB") or "").strip()
    return d if d and os.path.isdir(d) else ""


def run_stub(cfg, prompt, fresh=False, sdir=None):
    """스텁 응답 — 프롬프트 키로 고른 파일 내용 + 서약. 파일이 없으면 실패(빈 스텁 = 실패 경로)."""
    sdir = sdir or stub_dir()
    prompt = str(prompt or "")
    parts = len(make_parts(prompt, reserve=len(PLEDGE_TAIL)))
    if not sdir:
        return {"ok": False, "phase": "stub", "error": "LM_COPILOT_STUB 폴더 없음", "parts": parts}
    cands = []
    try:
        with open(os.path.join(sdir, "stub_map.json"), encoding="utf-8-sig") as f:
            for k, v in (json.load(f) or {}).items():
                if isinstance(k, str) and isinstance(v, str) and k in prompt:
                    cands.append(v)
    except (OSError, ValueError, AttributeError):
        pass
    cands.extend(stub_candidates(prompt))
    for name in cands:
        p = os.path.join(sdir, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8-sig") as f:
                    body = f.read().strip()
            except OSError:
                continue
            try:                         # 기록: 어떤 프롬프트가 어느 파일로 답해졌는지
                with open(os.path.join(sdir, "_stub_log.jsonl"), "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "file": name,
                                        "chars": len(prompt), "parts": parts, "fresh": bool(fresh),
                                        "head": prompt[:60]}, ensure_ascii=False) + "\n")
            except OSError:
                pass
            return {"ok": True, "phase": "stub", "reply": body + "\n" + SENTINEL,
                    "model": "stub", "stub_file": name, "parts": parts, "sentinel": True}
    return {"ok": False, "phase": "stub", "error": "스텁 응답 파일 없음",
            "hint": f"{sdir} 에 {', '.join(cands[:3])} 중 하나를 두세요", "parts": parts}


# ── G3 Copilot 직전 관문(privacy) — 문맥은 프로세스당 1회 만든다 ──────────────────────
_PRIV = {}
_EXT_MAIL_RX = re.compile(r"\[이메일@(?!(?:사내|개인메일|고객사|협력사|외부)\])[^\]]{1,64}\]")


def _org_labels(domains):
    """사내 메일 도메인의 이름 마디(마지막 TLD 제외) — 조직 이름은 사람을 가리키지 않으므로 카나리아에서 뺀다
    (Windows 도메인 이름이 회사 메일 도메인과 같으면 '@회사.com' 이 든 모든 프롬프트가 막히던 오탐)."""
    out = set()
    for d in domains or ():
        parts = str(d or "").lower().split(".")
        out.update(p for p in parts[:-1] if p)
    return out


def privacy_ctx(refresh=False):
    """G3 문맥 → (설정 전체, privacy.Ctx, 카나리아 튜플). config\\config.json 과 data\\…\\mail_source.json me[] 로 만든다."""
    if _PRIV.get("ctx") is not None and not refresh:
        return _PRIV["cfg"], _PRIV["ctx"], _PRIV["cans"]
    import privacy
    full = {}
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            o = json.load(f)
        full = o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        full = {}
    data_dir = os.path.join(ROOT, "data")
    ctx = privacy.make_ctx(full, data_dir)
    org = _org_labels(getattr(ctx, "internal_domains", ()))
    cans = tuple(c for c in privacy.canaries(full, data_dir) if c not in org)
    _PRIV.update(cfg=full, ctx=ctx, cans=cans)
    return full, ctx, cans


def gate_rows(items, fields=("text",), max_chars=400):
    """G3 행 관문 — privacy.gate_items(사적·광고 의심 제외 → 재정제 → 자격증명·고위험 잔여·카나리아 행 제외 →
    [사람#…]→[사람] → 필드당 400자) 뒤에 외부 도메인 이메일 라벨을 [이메일@외부] 로 접는다(⑦).
    → (보낼 행 사본 목록, {제외 사유: 건수}). 원본 행은 바꾸지 않는다."""
    import privacy
    full, ctx, cans = privacy_ctx()
    flds = [fields] if isinstance(fields, str) else list(fields or ())
    kept, dropped = privacy.gate_items(items, flds, full, canaries=cans, ctx=ctx, max_chars=max_chars)
    for it in kept:
        for f in flds:
            v = it.get(f)
            if isinstance(v, str) and "[이메일@" in v:
                it[f] = _EXT_MAIL_RX.sub("[이메일@외부]", v)
    return kept, dropped


def gate_ok(prompt):
    """G3 최종 프롬프트 검사(privacy.gate_prompt) → True = 보내도 됨. 관문을 세우지 못하면 보내지 않는다(fail-closed)."""
    try:
        import privacy
        full, ctx, cans = privacy_ctx()
        return bool(privacy.gate_prompt(str(prompt or ""), full, canaries=cans, ctx=ctx))
    except Exception:  # noqa: BLE001 - 관문 오류 = 보내지 않음
        return False


def blocked_result(prompt=""):
    return {"ok": False, "status": "blocked", "phase": "blocked", "reason": R_GATE,
            "error": "개인정보 관문(G3) — 최종 프롬프트에 고위험 잔여·카나리아가 있어 보내지 않았습니다",
            "hint": "이 묶음은 PC 자료(규칙)로 처리합니다 — 재시도하지 않습니다",
            "parts": len(make_parts(str(prompt or ""), reserve=len(PLEDGE_TAIL)))}


def busy_result(e=None):
    return {"ok": False, "phase": "launch_failed", "reason": R_EDGEBUSY,
            "error": str(e or "전용 Edge 를 다른 작업이 쓰고 있습니다"), "hint": _hint(R_EDGEBUSY)}


def _after(cfg, res):
    """왕복 결과로 소유 표식을 고친다 — 로그인 대기면 close_own_edge 가 창을 닫지 않게 표시하고, 성공이면 대기 표시와
    죽은 프로필 계수를 푼다. R-EDGEKEEP 이 관찰됐으면 결과에 싣는다(화면 안내용)."""
    if not isinstance(res, dict):
        return
    if res.get("phase") == "login_required":
        _update_owner(cfg, login_pending=time.strftime("%Y-%m-%d %H:%M:%S"))
    elif res.get("ok") and res.get("phase") != "stub":
        _update_owner(cfg, login_pending="")
        _reset_dead(cfg)
        clear_throttle(cfg)                   # 답이 왔다 — 사용량 제한 기록을 지운다(다음 단계가 쉬지 않게)
    if LAST.get("keep") and "edge_keep" not in res:
        res["edge_keep"] = R_EDGEKEEP


def _send(cfg, prompt, fresh=False, no_split=False, lock_wait=EDGE_LOCK_WAIT, reload=False):
    """--send 와 send_inproc 의 공용 길 — G3 최종 검사 → (스텁) → 전용 Edge 잠금 안에서 왕복. 결과 dict 는 --send 의 JSON.
    reload(LM28): 보내기 전에 채팅 페이지 새로 고침 — 켜졌을 때만 왕복 함수에 넘긴다.
    LM28: 이번 실행(LM_RUN_ID)이 사용량 제한으로 AI 단계를 멈췄으면 Edge 도 잠금도 건드리지 않고 바로 run_stop_result — judge 를
    거치지 않는 호출자(메일·팀즈 Copilot 확인 등)도 같은 실행 안에서는 더 보내지 않는다."""
    prompt = str(prompt or "")
    if run_stopped(cfg):
        return run_stop_result()
    if not gate_ok(prompt):
        return blocked_result(prompt)
    if stub_dir():
        return run_stub(cfg, prompt, fresh=bool(fresh))       # 테스트 전용 — Edge 미기동
    kw = {"reload": True} if reload else {}
    fr = RESUME if fresh == RESUME else bool(fresh)          # RESUME(다음 단계의 첫 왕복)은 그대로 넘긴다 — 화면 확인은 왕복 함수
    _RESUMED[0] = None
    try:
        with edge_lock(cfg, timeout=lock_wait):
            res = (run_roundtrip(cfg, prompt, fresh=fr, **kw) if no_split
                   else run_roundtrip_split(cfg, prompt, fresh=fr, **kw))
    except EdgeBusy as e:
        return busy_result(e)
    if fr == RESUME and isinstance(res, dict) and _RESUMED[0] is not None:
        res["resumed"] = bool(_RESUMED[0])                   # 이어 보냈나(False = 화면이 우리 채팅이 아니라 새 채팅을 열었다)
    _after(cfg, res)
    return res


def send_inproc(prompt, fresh=False, deadline=None, cfg=None, stage="", reload=False):
    """--send 를 같은 프로세스에서 — judge.copilot_send(inProcess) 가 부른다(왕복마다 파이썬을 띄우지 않는다).
    반환 dict 는 --send 가 출력하는 JSON 과 같다(같은 _send). deadline(epoch 초)이 있으면 왕복 예산(roundtripMaxSec)과
    잠금 대기를 그 안으로 줄인다 — 인프로세스 왕복은 밖에서 끊을 수 없으므로 드라이버의 내부 데드라인(_RT_DEADLINE ·
    CDP 소켓 timeout)이 상한이다. 예외는 --send 처럼 {"ok":False,"phase":"error"} 로 돌려준다.
    reload: 보내기 전에 채팅 페이지 새로 고침(judge 의 쉬었다 다시 보내기·chatTurns 회전). 모델을 바꿀 때는 cfg 의 model.
    fresh=RESUME(LM28): 화면이 앞 단계의 우리 채팅이면 이어 쓰고 아니면 새 채팅 — 결과의 resumed 가 실제로 이어 썼는지다.
    느린 긴 답의 연장 대기 중에는 드라이버가 약 1분마다 stderr 진행 줄을 찍는다(judge._transport 는 따로 1분마다 stdout 경과 줄)."""
    cfg = dict(cfg) if isinstance(cfg, dict) else load_cfg()
    lock_wait = EDGE_LOCK_WAIT
    if deadline:
        left = float(deadline) - time.time()
        rt = int(cfg.get("roundtripMaxSec") or 0)
        cap = int(max(60, left - 30))
        cfg["roundtripMaxSec"] = min(rt, cap) if rt > 0 else cap
        lock_wait = max(1.0, min(float(EDGE_LOCK_WAIT), left - 60))
    old = os.environ.get("LM_STAGE")
    if stage:
        os.environ["LM_STAGE"] = str(stage)[:40]        # 계측(copilot_trace)의 단계 이름
    try:
        if reload:
            return _send(cfg, prompt, fresh=fresh, lock_wait=lock_wait, reload=True)
        return _send(cfg, prompt, fresh=fresh, lock_wait=lock_wait)
    except Exception as e:  # noqa: BLE001 - --send 와 같은 꼴로
        return {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}",
                "hint": "이 메시지를 Claude에게 보여주세요"}
    finally:
        if stage:
            if old is None:
                os.environ.pop("LM_STAGE", None)
            else:
                os.environ["LM_STAGE"] = old


def run_probe(cfg):
    how = ensure_edge(cfg)
    if how is None:
        return edge_fail(cfg)
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "탭 생성 실패"}
    cdp = CDP(ws_url)
    try:
        time.sleep(1.5)
        state, kind = wait_page(cdp, cfg, tries=8)
        stop = page_gate(cdp, cfg, state, kind)
        if stop is not None:
            return stop
        return {"ok": True, "phase": "ready", "url": (state or {}).get("url", "")}
    finally:
        cdp.close()


def run_diagnose(cfg):
    how = ensure_edge(cfg)
    if how is None:
        return edge_fail(cfg)
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "탭 생성 실패"}
    cdp = CDP(ws_url)
    try:
        time.sleep(2)
        dbg = cdp.eval(js_diagnose())
        dump = os.path.join(ROOT, "data", "copilot_auto_debug.json")
        with open(dump, "w", encoding="utf-8") as f:
            json.dump(dbg, f, ensure_ascii=False, indent=1)
        return {"ok": True, "phase": "ready", "debug_file": dump,
                "editors": len((dbg or {}).get("editors", [])),
                "buttons": len((dbg or {}).get("buttons", [])),
                "chats": chat_status(cfg)}             # LM28 — 마지막 Copilot 채팅 정리 결과(숫자·사유만)
    finally:
        cdp.close()


def run_diagnose_model(cfg):
    """모델 선택 메뉴를 실제로 열고 그 안의 항목을 그대로 덤프한다 —
    Copilot UI가 바뀔 때 추측하지 않고 눈으로 확인하기 위한 진단."""
    how = ensure_edge(cfg)
    if how is None:
        return edge_fail(cfg)
    ws_url = find_tab(cfg)
    if not ws_url:
        return {"ok": False, "phase": "launch_failed", "error": "탭 생성 실패"}
    cdp = CDP(ws_url)
    try:
        time.sleep(2)
        opened = cdp.eval(js_pick_model(cfg.get("model") or "GPT")) or {}
        time.sleep(1.2)
        dump = cdp.eval(r"""(function(){
  const vis=el=>{const r=el.getBoundingClientRect();return r.width>4&&r.height>4;};
  const out=[];
  document.querySelectorAll("[role='menu'],[role='listbox'],[role='dialog'],ul,div")
   .forEach(c=>{ if(!vis(c))return; const r=c.getBoundingClientRect(); if(r.width>460||r.height>560)return;
     const kids=[...c.querySelectorAll("[role='menuitem'],[role='menuitemradio'],[role='option'],li,button")]
       .filter(vis).map(e=>({t:(e.innerText||"").trim().slice(0,40),
                             role:e.getAttribute("role")||e.tagName,
                             pop:e.getAttribute("aria-haspopup")||"",
                             exp:e.getAttribute("aria-expanded")||""}))
       .filter(x=>x.t);
     if(kids.length>=2&&kids.length<=15)out.push({box:c.getAttribute("role")||c.tagName,items:kids});});
  return {menus:out.slice(0,4)};
})()""") or {}
        return {"ok": True, "phase": "ready", "opened": opened, "menu": dump}
    finally:
        cdp.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # CLI 만 — 임포트(인프로세스 왕복)한 쪽의 stdout 은 건드리지 않는다
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", help="프롬프트 파일(UTF-8) 전송 후 응답 회수")
    ap.add_argument("--close", action="store_true", help="우리가 띄운 전용 Edge 만 닫기(owner.json 이 있을 때)")
    ap.add_argument("--force", action="store_true", help="--close 와 함께: 로그인 대기·keepEdgeOpen 이어도 닫기")
    ap.add_argument("--out", help="응답 저장 파일 (기본: stdout JSON에 포함)")
    ap.add_argument("--fresh", action="store_true",
                    help="새 채팅에서 시작 (앞선 대화 문맥 오염 방지 — 판정용)")
    ap.add_argument("--no-split", action="store_true",
                    help="긴 프롬프트를 나누지 않고 한 번에 주입 (옛 동작 — 서약 지시도 붙이지 않음)")
    ap.add_argument("--probe", action="store_true", help="상태 확인만")
    ap.add_argument("--diagnose", action="store_true", help="입력창/버튼 후보 덤프")
    ap.add_argument("--diagnose-model", action="store_true", help="모델 선택 메뉴를 열어 항목 덤프")
    ap.add_argument("--url", help="대상 URL 덮어쓰기 (테스트용)")
    ap.add_argument("--port", type=int, help="디버그 포트 덮어쓰기")
    ap.add_argument("--reload", action="store_true",
                    help="보내기 전에 채팅 페이지를 새로 고침 (오래 쓴 탭 — 판정의 쉬었다 다시 보내기)")
    ap.add_argument("--model", help="이번 왕복만 모델 바꾸기 (config 의 model 대신 — 예: 자동)")
    ap.add_argument("--retire", action="store_true",
                    help="--send 와 함께: 왕복 뒤 이 채팅을 Copilot 대화 목록에서 지운다(우리가 연 채팅만 — [AI 연결 진단])")
    a = ap.parse_args()
    cfg = load_cfg()
    if a.url:
        cfg["url"] = a.url
    if a.port:
        cfg["port"] = a.port
    if a.model:
        cfg["model"] = a.model
    try:
        if a.close:
            res = dict(close_own_edge(cfg, "cli", force=bool(a.force)), ok=True)
        elif a.probe or a.diagnose or getattr(a, "diagnose_model", False):
            # 진단은 화면 요청 안에서 돈다 — 분석이 전용 Edge 를 쓰는 중이면 오래 기다리지 않고 R-EDGEBUSY
            with edge_lock(cfg, timeout=PROBE_LOCK_WAIT):
                if a.probe:
                    res = run_probe(cfg)
                    _after(cfg, res)
                elif a.diagnose:
                    res = run_diagnose(cfg)
                else:
                    res = run_diagnose_model(cfg)
        elif a.send:
            with open(a.send, encoding="utf-8-sig") as f:
                prompt = f.read()
            if a.reload:
                res = _send(cfg, prompt, fresh=bool(a.fresh), no_split=bool(a.no_split), reload=True)
            else:
                res = _send(cfg, prompt, fresh=bool(a.fresh), no_split=bool(a.no_split))   # send_inproc 과 같은 길
            if a.retire:
                # [AI 연결 진단] — 한 번 묻고 끝나는 채팅이라 바로 지운다(우리가 연 채팅만). 결과 한 줄(숫자·사유)을 함께 돌려준다
                code = retire_current(cfg, "diag") if not stub_dir() else "none"
                ln1, _, ln2 = chat_line().partition("\n")         # 둘째 줄(구조 조사)은 한 줄로 붙인다 — 화면 로그 한 줄
                res["chats"] = (ln1[len(CHAT_LINE_HEAD):] + (" · 구조: " + ln2[len(CHAT_CENSUS_HEAD):] if ln2 else "")) or (
                    (CHAT_WHY.get(code, code) + " · " if code not in ("none", "unsent", "deleted") else "") + chat_status(cfg))
            if a.out and res.get("reply"):
                with open(a.out, "w", encoding="utf-8") as f:
                    f.write(res["reply"])
        else:
            ap.print_help()
            return 2
    except EdgeBusy as e:
        res = busy_result(e)
    except Exception as e:
        res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}",
               "hint": "이 메시지를 Claude에게 보여주세요"}
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
