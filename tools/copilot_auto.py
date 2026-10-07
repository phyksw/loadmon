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
         input_not_found | no_reply | copilot_error | error | stub
  cut: 답 꼬리에 '생성 중단' 문구("OK, I've stopped generating the response.")가 있다 — 재시도
       사다리(새 채팅)로도 반복되면 잘린 앞부분을 ok+cut 으로 돌려주고, 호출자(judge/refine)가
       잘린 JSON 을 마지막 완전한 항목까지 복구한 뒤 나머지만 다시 묻는다(적응 분할).
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
  · ensure_edge 가 띄우면 data\\lm28_edge\\owner.json{pid,port,t,root,browser} 를 쓴다. close_own_edge 는 그 표식이 있고
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
"""
import argparse
import base64
import contextlib
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
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_WIN = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000   # 상위 Job(단계 정리)에서 Edge 를 떼어 띄운다 — 단계가 끝나도 Edge 는 산다
ERROR_ACCESS_DENIED = 5                  # 상위 Job 이 이탈(BREAKAWAY_OK)을 허락하지 않을 때 CreateProcess 가 내는 오류
_sleep = time.sleep                      # 시험이 대기를 0 으로 바꿀 수 있게(Edge 수명주기 함수만)
if os.path.join(ROOT, "core") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "core"))
import lmname  # noqa: E402  — LM28 이름 단일원(CDP 포트·전용 Edge 프로필)

# ── 설정 (config.json 의 copilotAuto 로 덮어쓰기 가능) ──
# 포트·프로필은 LM24 와 다르게 둔다(9533 · data\lm28_edge) — 같은 PC 의 LM24 Edge 를 재사용·조종하지 않게.
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
}

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
        # 빈 값은 기본값을 쓰되, 명시한 false 는 받는다(inProcess·requireWorkAccount 를 끌 수 있게)
        cfg.update({k: v for k, v in user.items() if v or v is False})
    except Exception:
        pass
    # LM24 의 config.json 을 그대로 옮겨 온 경우(옛 포트·옛 프로필) — lmname 값이 우선한다.
    # 경고는 stderr 로 1줄(stdout 은 결과 JSON 한 건 계약) — 인프로세스 왕복은 이 함수를 자주 부르므로 프로세스당 1회.
    fixed = lmname.fix_edge_cfg(cfg, ROOT)
    if fixed:
        _notice(f"CFG-OLD|{cfg_path or ''}|{','.join(fixed)}",
                "경고: config 의 옛 판 값을 LM28 값으로 바꿔 씁니다 — " + ", ".join(fixed), label="")
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
REASON_HINT = {
    R_EDGEPOL: "회사 Edge 정책(RemoteDebuggingAllowed=0 또는 UserDataDir 강제)이 전용 Edge 를 막습니다 — AI 단계는 "
               "PC 자료(규칙)로 진행합니다. 프롬프트 파일(report\\judge_*.md)을 Copilot 에 직접 붙여 쓸 수는 있습니다",
    R_EDGEKEEP: "회사 Edge 정책이 브라우저를 닫을 때 쿠키를 지웁니다 — 매번 다시 로그인하지 않으려면 "
                "config\\config.json 의 copilotAuto.keepEdgeOpen 을 true 로 두세요",
    R_EDGEBUSY: "다른 작업(웹 메일·팀즈 읽기·AI 연결 진단 등)이 전용 Edge 를 쓰고 있습니다 — 그 작업이 끝난 뒤 다시 실행하세요",
    R_EDGEFOREIGN: "디버그 포트 {port} 를 다른 프로그램의 Edge 가 쓰고 있습니다 — 그 Edge 를 닫거나 "
                   "config\\config.json 의 copilotAuto.port 를 바꾸세요(우리 것이 아닌 브라우저는 조종하지 않습니다)",
    R_EDGELAUNCH: "Edge 를 디버그 포트로 띄우지 못했습니다 — 열린 전용 Edge 창(data\\lm28_edge)을 닫고 다시 실행하세요",
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


def close_own_edge(cfg=None, reason="", force=False):
    """우리가 띄운 전용 Edge 만 닫는다 → {"closed": bool, "why": str}. 작업 단위(수집 1회·분석 1회)가 끝날 때 부른다(run.py).
    · owner.json(ensure_edge 가 띄울 때 쓴 표식)이 없으면 아무것도 하지 않는다 — 사람이 띄운 Edge 는 건드리지 않는다.
    · keepEdgeOpen=true 면 닫지 않는다(종료 때 쿠키를 지우는 정책 PC — R-EDGEKEEP).
    · 로그인 대기 중(login_pending)이면 닫지 않는다 — 사람이 그 창에서 로그인하는 중일 수 있다(force 면 무시).
    · /json/version 이 응답하고 브라우저 ID 가 표식과 같을 때만 CDP Browser.close 를 보낸다(taskkill 은 쓰지 않는다).
      포트가 닫히길 최대 5초 기다린 뒤 표식을 지운다 — 그래도 안 닫혀도 강제 종료하지 않는다."""
    cfg = cfg if isinstance(cfg, dict) else load_cfg()
    if _truthy(cfg.get("keepEdgeOpen")) and not force:
        return {"closed": False, "why": "keep"}
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
    return {"closed": True, "why": str(reason or "done")}


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


def recreate_profile(cfg):
    """죽은 프로필(서로 다른 왕복에서 오류 화면 2회 연속) — 우리 Edge 를 닫고 프로필 폴더를 <이름>.bad-<시각> 으로 바꾼 뒤
    새로 띄운다(로그인 1회 다시). 사람이 띄운 Edge 가 그 프로필을 쓰고 있으면(표식 없음·포트 살아 있음) 손대지 않는다.
    옛 .bad-* 는 지우지 않는다(사람이 확인하고 지운다)."""
    close_own_edge(cfg, "dead_profile", force=True)
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
                  err=(r.get("error") or "")[:60])
        except Exception:  # noqa: BLE001
            pass
        return res
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def run_roundtrip(cfg, prompt, fresh=False):
    """프롬프트 전송 → 응답 회수. Copilot 일시 오류('응답할 수 없습니다')나 무응답이면
    단계적으로 재시도한다: ① 새 채팅에서 같은 모델로 ② 새 채팅 + 자동 모델로.
    어느 단계에서 성공했는지 retry 노트로 남긴다.
    왕복 1회 총 예산은 cfg.roundtripMaxSec(0 이면 끔)다 — 사다리를 다 태우면 고정 대기까지 합쳐 한 왕복에
    30분이 들고(감사 실측), 그 동안 호출자는 아무것도 받지 못한다. 부모가 강제 종료하기 전에 **자식이
    스스로** 접어야 '정상 재시도 중' 이 죽지 않고 화면에 이유가 남는다."""
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
    try:
        if fresh:
            # 판정처럼 '깨끗한 문맥'이 필요한 왕복은 새 채팅에서 시작한다 —
            # 앞선 실패 대화(예: 팀즈 조회 거절)가 문맥에 남으면 답이 오염된다.
            try:
                new_chat(cdp, cfg)
            except Exception:
                pass
        res = _roundtrip_once(cdp, cfg, prompt)
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
        cfg2["replyTimeoutSec"] = int(min(cfg2["replyTimeoutSec"], max(60, _rt_left() - 60)))
        how2 = new_chat(cdp, cfg)
        res2 = _roundtrip_once(cdp, cfg2, prompt)
        if res2.get("ok") and not is_error_reply(res2.get("reply")) and not res2.get("cut"):
            res2["retry"] = f"1단계 재시도 성공 (새 채팅 · {how2})"
            return res2
        # ② 새 채팅 + 자동 모델 폴백 (특정 모델 라우팅 장애 대비)
        if _rt_left() < 120:
            res2["retry"] = f"왕복 예산 {_rt_max // 60}분을 다 써 2단계 재시도는 하지 않았습니다"
            return res2 if res2.get("reply") else res
        cfg2["replyTimeoutSec"] = int(min(cfg2["replyTimeoutSec"], max(60, _rt_left() - 60)))
        new_chat(cdp, cfg)
        res3 = _roundtrip_once(cdp, cfg2, prompt, model_override="자동")
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
            baseline = len(cdp.eval(js_chat_text(cfg), timeout=30) or "")
        except TimeoutError:
            try:
                cdp.reconnect()
            except Exception:
                pass
            baseline = len(cdp.eval(js_chat_text(cfg), timeout=45) or "")
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
        deadline = time.time() + min(float(cfg["replyTimeoutSec"]), _dl_left(10 ** 6))
        how = "anchor"
        last, stable, idle = None, 0, 0
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
        while time.time() < deadline:
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
                                     busy_seen=busy_seen)
            # 버튼 상태는 매 폴 본다(버튼 목록 훑기 — innerText 보다 훨씬 가볍다). 텍스트가 늘고 있는 동안
            # 버튼이 보이면 '이 UI 에서 선택자가 맞는다' 는 증거가 된다.
            try:
                gen = bool(cdp.eval(js_is_generating(), timeout=10))
            except (TimeoutError, OSError, RuntimeError):
                gen = None            # 못 물어봤으면 판단하지 않는다(안전 쪽)
            if gen:
                busy_seen = True
            body = strip_echo(new, prompt, anchor, how).strip()     # 에코 꼬리를 걷어낸 '진짜 답'
            if not body and (gen or (time.time() - t_gen0) < first_token_s):
                # 아직 첫 글자가 없다 — 생각 중이다(버튼이 보이거나 유예 안). 멈춘 답으로 세지 않는다.
                stable, idle = 0, 0
            elif new.strip() and new == last:
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
                                         busy_seen=busy_seen)
            else:
                stable, idle = 0, 0
            last = new
        return {"ok": False, "phase": "no_reply", "error": "응답 시간 초과",
                "reply": (last or "").strip(), "sentinel": False,
                "hint": "Copilot 창이 응답을 생성 중인지 확인 — 반복되면 화면 스크린샷을 Claude에게"}


def _looks_closed(reply):
    """답이 JSON 꼴({ 나 [ 가 있음)이면 괄호가 모두 닫혔는가 — 산문이면 항상 참.
    잘린 JSON 을 '완료' 로 집지 않기 위한 값싼 확인이다(파싱이 아니라 개수만 본다)."""
    s = str(reply or "")
    if "{" not in s and "[" not in s:
        return True
    return s.count("{") <= s.count("}") and s.count("[") <= s.count("]")


def _reply_result(reply, note_model, how, sentinel, waited=0, resent=False,
                  gen_sec=0.0, done_by="", busy_seen=None):
    """회수 결과 dict — cut(생성 중단 문구가 꼬리에 있음)·waited(앞 답 생성 대기 초)·resent(전송 재클릭)
    를 함께 남겨 호출자가 잘린 답을 복구·부분 재시도할 수 있게 한다.
    gen_sec·done_by 는 계측용 — 답을 기다린 초와 무엇으로 완료를 알았는지
    (pledge=서약 / idle=중지 버튼 사라짐 / stable=같은 텍스트 반복)."""
    reply = (reply or "").strip()
    out = {"ok": True, "phase": "replied", "reply": reply, "model": note_model, "pick": how,
           "sentinel": bool(sentinel), "cut": is_cut_reply(reply)}
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


def _run_parts(cdp, cfg, parts, fresh, deadline=None):
    """같은 CDP·같은 채팅에서 조각을 차례로 보낸다 — 조각별 _roundtrip_once, 사다리 없음.
    조각마다 서약을 확인하고, 없으면 _wait_rest 로 기다린 뒤에만 다음 조각을 보낸다.
    deadline(epoch 초): 넘기면 조각을 더 보내지 않고 시간 초과로 접는다 — 예전에는 이 다부 경로에
    왕복 예산이 없어 한 왕복이 76~80분까지 무제동으로 돌았다(제보 ④ · 검증 CONFIRMED)."""
    total = len(parts)
    if fresh:
        try:
            new_chat(cdp, cfg)
        except Exception:
            pass
    res = {"ok": False, "phase": "error", "error": "왕복 시작 실패"}
    for i, part in enumerate(parts, 1):
        if deadline is not None and time.time() > deadline:
            return {"ok": False, "phase": "timeout", "parts": total,
                    "error": f"나눔 {i}/{total}: 왕복 예산을 넘겨 중단(이 청크는 규칙 판정으로)",
                    "hint": "Copilot 응답 지연 — config.copilotAuto.roundtripMaxSec"}
        res = _roundtrip_once(cdp, cfg, part)
        if not res.get("ok"):
            res["error"] = f"나눔 {i}/{total}: " + str(res.get("error") or "왕복 실패")
            return res
        reply = res.get("reply") or ""
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


def run_roundtrip_split(cfg, prompt, fresh=False):
    """--send 의 기본 경로. 한 조각이면 서약 지시를 덧붙여 기존 run_roundtrip(재시도 사다리
    유지). 여러 조각이면 같은 채팅에 차례로 보내고, 실패하면 새 채팅에서 전체를 1회 재시도.
    결과 dict 형식은 run_roundtrip 과 같고 parts(조각 수)만 더한다."""
    parts = make_parts(prompt, reserve=len(PLEDGE_TAIL))
    if len(parts) == 1:
        res = run_roundtrip(cfg, prompt + PLEDGE_TAIL, fresh=fresh)
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
            res = _run_parts(cdp, cfg, parts, fresh=(fresh or attempt == 2), deadline=_deadline)
        except Exception as e:
            res = {"ok": False, "phase": "error", "error": f"{type(e).__name__}: {e}"}
        finally:
            cdp.close()
        if res.get("ok"):
            if attempt == 2:
                res["retry"] = "나눔 전송 실패 → 새 채팅에서 전체 재전송 성공"
            res["parts"] = len(parts)
            return res
        if attempt == 1 and res.get("phase") in ("login_required", "input_not_found", "launch_failed"):
            break                        # 사람이 개입해야 하는 상태(로그인·개인 계정·죽은 프로필) — 재시도해도 같다
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
    ('"match"', ("agentic.json", "match.json")),                   # agentic.py
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
    if LAST.get("keep") and "edge_keep" not in res:
        res["edge_keep"] = R_EDGEKEEP


def _send(cfg, prompt, fresh=False, no_split=False, lock_wait=EDGE_LOCK_WAIT):
    """--send 와 send_inproc 의 공용 길 — G3 최종 검사 → (스텁) → 전용 Edge 잠금 안에서 왕복. 결과 dict 는 --send 의 JSON."""
    prompt = str(prompt or "")
    if not gate_ok(prompt):
        return blocked_result(prompt)
    if stub_dir():
        return run_stub(cfg, prompt, fresh=bool(fresh))       # 테스트 전용 — Edge 미기동
    try:
        with edge_lock(cfg, timeout=lock_wait):
            res = (run_roundtrip(cfg, prompt, fresh=bool(fresh)) if no_split
                   else run_roundtrip_split(cfg, prompt, fresh=bool(fresh)))
    except EdgeBusy as e:
        return busy_result(e)
    _after(cfg, res)
    return res


def send_inproc(prompt, fresh=False, deadline=None, cfg=None, stage=""):
    """--send 를 같은 프로세스에서 — judge.copilot_send(inProcess) 가 부른다(왕복마다 파이썬을 띄우지 않는다).
    반환 dict 는 --send 가 출력하는 JSON 과 같다(같은 _send). deadline(epoch 초)이 있으면 왕복 예산(roundtripMaxSec)과
    잠금 대기를 그 안으로 줄인다 — 인프로세스 왕복은 밖에서 끊을 수 없으므로 드라이버의 내부 데드라인(_RT_DEADLINE ·
    CDP 소켓 timeout)이 상한이다. 예외는 --send 처럼 {"ok":False,"phase":"error"} 로 돌려준다."""
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
                "buttons": len((dbg or {}).get("buttons", []))}
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
    a = ap.parse_args()
    cfg = load_cfg()
    if a.url:
        cfg["url"] = a.url
    if a.port:
        cfg["port"] = a.port
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
            res = _send(cfg, prompt, fresh=bool(a.fresh), no_split=bool(a.no_split))   # send_inproc 과 같은 길
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
