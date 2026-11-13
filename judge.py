# -*- coding: utf-8 -*-
r"""
judge.py — 신호 판정(AgentFinder32 · Agentic AI 전환 과제 발굴). 내 메일·일정에서 뽑은 신호를 회사 M365 Copilot 이
[업무 여부, 과제, 업무유형, 세부업무]로 분류한다. 이 분류는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다 — 사람을
평가하거나 근태·업무량을 보는 데 쓰지 않습니다.

  [0] 체계 수립 — 표본(출처·제목)으로 상위 과제 체계를 세운다(지정 과제는 늘 포함) → entities_<tag>.json
  [1..N] 신호 판정 — 묶음(행 수 40 · 글자 예산 PROMPT_BUDGET)마다 [번호, "y"|"n", 과제, 유형, 세부업무].
         묶음 프롬프트는 머리말까지 혼자서 완결이다. 잘린 답은 복구하고 빠진 행만 다시 묻는다(적응 분할).
  산출 — signals_<tag>.csv(판정 열을 더해 되쓴다) · work_rows_<tag>.csv(§5.5 — 근거건수는 판정 뒤 다시 센다) ·
         pivots_<tag>.json(§5.7) · evidence_<tag>.md(근거 표본 — 날짜는 MM-DD) · ai_judgments_<tag>.json(판정 기록 — 원문 없음)

  python judge.py --from YYYY-MM-DD --to YYYY-MM-DD [--chunk 40] [--redo] [--fast]
  (청크 기본값은 config.copilotAuto.judgeChunk 로도 바꿀 수 있다 — --chunk 가 우선)

프롬프트 원칙(R2·R4·R5·D10·D19):
  · 줄마다 날짜(YYYY-MM-DD)·출처(메일(수신)/메일(발신)/회의 …)·상대('나' = 내가 보낸 메일, 그 밖은 빈칸)·제목만 싣는다.
    시각·사람 이름·주소·도메인·가명(p:…)·가중치·건수·비중은 싣지 않는다.
  · 모든 Copilot 프롬프트의 맨 앞 머리말(AI_PREFIX — "아래 목록만 사용하세요 …")은 copilot_send 한 곳에서 붙인다
    (refine·agentic·flow·core\details 의 왕복도 모두 이 함수를 지난다).
  · 행은 먼저 G3 행 관문(copilot_auto.gate_rows → privacy.gate_items: 제한 고객·민감정보·식별번호·사적·광고 의심 제외)을 지나고,
    완성된 프롬프트는 최종 검사(g3_prompt)를 지난다. 걸린 행은 보내지 않고 규칙 판정으로 둔다(실패로 세지 않는다).
  · 광고 의심(signals flag 'ad') 행은 보내지 않고 비업무로 둔다.

이어서 판정 캐시(report\judge_cache.json — 내용 키의 sha1 → 판정, 원문 없음): 같은 신호는 기간이 바뀌어도 다시 묻지 않는다.
읽을 때 retention.intermediateDays 보다 오래 쓰지 않은 항목은 버리고, AgentFinder32 표식이 없는 캐시(옛 판)는 쓰지 않는다.
같은 내용(같은 계열·RE/FW 머리를 뗀 같은 앞 95자)은 대표 한 줄만 보내고 판정을 묶음 전체에 쓴다. AI 가 직접 못 본 행은
같은 내용·규칙 토큰·비슷한 신호의 판정을 빌려 'AI(유사)' 로 채운다(판정 기록·캐시에는 넣지 않는다).

Copilot 이 막히면(사용량 제한·일시 오류) copilot_send 가 쉬었다 새로 고쳐 다시 보낸다(일시 오류 1·2·2분, 사용량 제한은
copilotAuto.throttleWaitSec 한 번). 한 실행(AF32_RUN_ID)의 쉬는 시간 합계는 copilotAuto.runWaitMaxSec 안이다. 사용량 제한으로
멈추면 같은 실행의 뒤 단계(정제·Agentic·워크플로우)는 보내지 않는다(copilot_auto.run_stopped).

시작할 때 내 자료인지(consent.require — 다른 사용자의 자료면 종료 코드 4 · 지우는 중이면 3)와 이 기간의 run_meta 표식(AgentFinder32)을
확인한다. 종료 코드: 0 정상 · 1 입력 없음 · 2 부분(예산 중단·실패 잔여) · 3 지우는 중 또는 판정 0건(마지막 줄 JSON {"ok":false,"error","hint"}
— signals/work_rows 는 규칙 판정으로 쓰고 entities 기존 파일은 보존한다. run.py 가 이 코드를 보고 정제·Agentic·워크플로우를 건너뛴다).

copilot_send(prompt, tag, name, fresh=None) 은 다른 모듈(refine·agentic·flow·core\details)이 공유하는 Copilot 왕복 1회 접점이다.
프롬프트 파일(report\judge_<name>_<tag>.md — 중간 자료, 보관기한 retention.intermediateDays)은 성공한 왕복이면 회수 직후 지우고,
실패한 왕복·해석 못 한 답(note_bad_reply)의 것만 남긴다 — 그 파일이 '회사 Copilot 에 붙여 넣기' 안내 대상이다.
"""
import csv
import functools
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
from details import explain_failure  # noqa: E402  - 로그인 필요 등 "사람이 손대야 풀리는" 실패 판정
import details  # noqa: E402  - 과제명 관문(사람·공지 — task_name_ok 등)·상위 채움(level1_fill) 단일원
from details import ax_flag, field_of  # noqa: E402  - work_rows 끝 열 ax(AX 연계 표식)·field(분야)
from details import ukey2  # noqa: E402  - 과제 신원 축(공백·구분자·대소문자 무시, 괄호 꼬리 보존)
import lmname  # noqa: E402  - 산출물 표식(product)
from progress import progress  # noqa: E402

PRODUCT = lmname.PRODUCT
# D19 — 모든 Copilot 프롬프트의 맨 앞(copilot_send 가 붙인다). 이 문장으로 시작하는 프롬프트에는 다시 붙이지 않는다.
AI_PREFIX = "아래 목록만 사용하세요. 메일·채팅·파일·웹을 검색하지 마세요."
GENERIC_WORDING = details.GENERIC_WORDING     # D19 — agentic·flow 프롬프트가 더하는 문장(이름 대신 업무 행위로)
NO_WIN = 0x08000000
_DEC = json.JSONDecoder()
WORKTYPES = ["개발", "사무", "현장", "협업"]


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def _as_list(v):
    """AI 응답 필드 방어 — null/스칼라도 안전한 리스트로.
    실제 Copilot 응답은 예시와 다른 타입(match:5, models:null)을 낼 수 있고,
    그때 판정이 죽으면 화면이 규칙 결과로 남는다(실측)."""
    if isinstance(v, list):
        return v
    return [] if v in (None, "", {}) else [v]


PART_PROMPT = 8000          # tools/copilot_auto.PART_PROMPT 와 같은 값 — 조각 수 추정용
                            # (드라이버를 임포트하지 않는 이유: 임포트 시 stdout 재설정 부작용)
PROMPT_BUDGET = 8400        # 한 번에 보내는 프롬프트 상한 = copilot_auto.PROMPT_BUDGET(9,000 − 서약 지시 − 여유).
                            # 이 안이면 드라이버가 나누지 않는다(나눔은 왕복 2배 + 마지막 조각에만 답).
MIN_SPLIT = 5               # 적응 분할의 최소 행 — 이보다 작게는 나누지 않는다
MAX_SPLIT_DEPTH = 2         # 40 → 20 → 10 (LM28 진단 A — 예전 3단은 실패 청크 하나에 왕복 15회를 썼다)
SHORT_REPLY_CHARS = 400     # JSON 없는 짧은 답(거절·제한 문구일 수 있다)은 한 단계만 나눠 본다
MIN_RETRY_ROWS = 3          # 부분 성공(잘린 답 복구) 뒤 빠진 행이 이 수 이상이면 그 행만 다시 묻는다
SOFT_FAIL_CHUNKS = 3        # 연속으로 이만큼 청크가 0건이면 적응 재시도를 끄고 1회씩만 시도
ABORT_FAIL_CHUNKS = 6       # 연속으로 이만큼 0건이면 남은 청크를 규칙으로 둔다(수 시간 공회전 방지)
                            # — 개인정보 관문(G3)에 막혀 보내지 않은 청크는 실패가 아니라 skipped 다(이 계수에 넣지 않는다)
SEEN_MAX_NAMES = 30         # 청크에 동봉하는 '앞서 쓴 세부업무 이름' 상한
SEEN_MAX_CHARS = 600
# LM28 진단 A — Copilot 이 막히면(사용량 제한·일시 오류) 바로 다시 보내지 않고 쉬었다가 새로 고친 뒤 같은 묶음을 보낸다.
# 예전에는 실패 묶음을 즉시 반으로 나눠(+드라이버 사다리 3회) 몇 분 안에 수십 번을 더 보내 제한이 풀리지 않았다.
TRANSIENT_PHASES = {"throttled", "copilot_error", "no_reply", "empty_reply", "timeout", "error"}
# LM28 — 한 번 쉬기는 2분 이하, 한 실행의 쉬는 시간은 모든 단계를 합쳐 copilotAuto.runWaitMaxSec(기본 5분) 안(사용자 요청 '10분은 길다 —
# 3~5분으로'). 예전 사다리(2·5·10분 · 프로세스 합계 25분)는 단계마다 따로 쉬어 한 실행이 반시간 넘게 멈출 수 있었다.
COOLDOWN_SEC = (60, 120, 120)       # 쉬는 사다리(1·2·2분) — 세 번 쉬고도 막히면 강한 제한(hard)으로 보고 남은 묶음은 보내지 않는다
COOLDOWN_CAP_SEC = 5 * 60           # 한 프로세스가 쉬는 시간 합계 상한(실행 합계 상한은 copilot_auto.run_wait_left — runWaitMaxSec)
COOLDOWN_MIN_SEC = 30               # 이보다 짧게밖에 못 쉬면(전체 마감) 쉬지 않고 실패를 그대로 돌려준다(합계 상한을 다 썼으면 hard)
HARD_RECENT_SEC = 300               # 다른 프로세스가 남긴 강한 제한 기록이 이 안이면 첫 왕복 전에 남은 시간만 쉰다(실행 합계 안)
# LM28 — 사용량 제한(「요청이 너무 많음」)은 일시 오류 사다리(1·2·2분 × 세 번 다시 보내기)를 타지 않는다: 그동안의 재전송이 제한을
# 늘려 한 단계가 반시간 넘게 멈췄다(현장 제보). copilotAuto.throttleWaitSec(기본 120초, 0 = 쉬지 않고 바로 멈춤)만큼 **한 번** 쉬고
# 다시 보내, 그래도 막히면 강한 제한 — 같은 실행의 뒤 단계는 보내지 않는다(copilot_auto.run_stopped).
THROTTLE_WAIT_SEC = 120
# 이어서 판정 캐시(report\judge_cache.json) — 기간 tag 가 날마다 바뀌어도 이미 판정한 신호는 다시 묻지 않는다.
# 항목은 retention.intermediateDays 안에 마지막으로 쓴 것만 남는다(cache_keep_days — 읽을 때·저장할 때 버린다).
JUDGE_CACHE = "judge_cache.json"
JUDGE_CACHE_V = 3                   # AF32 — 날짜만 쓰는 내용 키 · product 표식(옛 판 캐시는 쓰지 않는다)
CACHE_MAX = 150_000                 # 상한 — 넘으면 오래 쓰지 않은 판정부터 뺀다
GROUP_MAX = 100                     # 같은 내용 묶음 하나의 행 상한 — 넘으면 시간 순으로 나눠 대표를 따로 세운다
GROUP_KEY_CHARS = 95                # = row_line 이 보내는 원문 길이 — 이 앞부분이 같으면 Copilot 이 보는 줄도 같다


def _copilot_cfg():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return json.load(f).get("copilotAuto") or {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def chunk_default(key, default):
    """청크 기본값 — --chunk 명시 > config.copilotAuto.<key> > 코드 기본값."""
    v = arg("--chunk", "")
    if not v:
        v = _copilot_cfg().get(key)
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else int(default)


SAFE_PROMPT = 9000          # tools/copilot_auto.SAFE_PROMPT 와 같은 값 — 이 길이까지는 드라이버가 한 번에 보낸다
PLEDGE_RESERVE = 60         # 드라이버가 붙이는 서약 지시 길이 여유(copilot_auto.PLEDGE_TAIL)


def n_parts_of(prompt_text):
    r"""드라이버(copilot_auto.make_parts)와 **같은 규칙**으로 조각 수를 센다.
    예전에는 len // PART_PROMPT + 1 이었다 — 8,001~9,000자(호출자들의 정상 상한: flow 8,300 ·
    judge/refine 8,409)를 2조각으로 세어, 드라이버가 1조각으로 보내는 왕복에 부모가 54분을 허용했다.
    자식은 늦어도 스스로 접으므로(roundtripMaxSec) 효과는 '진짜 멈춘 왕복을 두 배 늦게 끊는 것' 뿐이었다."""
    n = len(str(prompt_text or ""))
    if n + PLEDGE_RESERVE <= SAFE_PROMPT:
        return 1
    return (n + PART_PROMPT - 1) // PART_PROMPT + 1      # 줄 경계로 나누므로 한 조각 여유를 둔다


def roundtrip_timeout(n_parts=1):
    """자식(copilot_auto)의 재시도 사다리 예산에 맞춘 타임아웃 — 부모가 짧으면
    '정상 재시도 중'을 죽여버린다. 드라이버가 긴 프롬프트를 조각으로 나눠 보내면 왕복이
    조각 수만큼 늘어나므로 예산도 그만큼 곱한다(n_parts)."""
    try:
        sec = float(_copilot_cfg().get("replyTimeoutSec") or 300)
    except (ValueError, TypeError):
        sec = 300.0
    n = max(1, int(n_parts or 1))
    base = max(900.0, sec * 3 + 180)
    try:                        # 자식이 먼저 접는다(copilotAuto.roundtripMaxSec) — 부모는 5분 여유만 두고 지켜본다
        rt = float(_copilot_cfg().get("roundtripMaxSec") or 0)
    except (ValueError, TypeError):
        rt = 0.0
    if rt > 0:
        base = min(base, rt + 300.0)
    return base * n


_FIRST_SEND = [True]        # 판정 세션의 첫 왕복인지 (새 채팅으로 시작)
_NEED_FRESH = [False]       # 직전 왕복이 실패했거나 답을 해석 못 했다 — 다음 왕복은 새 채팅에서
                            # (AF32: 끊긴 답·느린 답은 아니다 — 드라이버가 이어 보내기 직전에 우리 채팅인지 다시 보고 아니면 새 채팅을 연다)
_ROTATIONS = [0]            # AF32 — 이 프로세스의 chatTurns 회전(같은 채팅에 상한만큼 보내 새 채팅으로 넘어간) 횟수 — 판정 기록·구조 줄
NOANS_PHASES = ("no_reply", "empty_reply")   # AF32 — 실패한 왕복이 채팅에 답 글을 남기지 않은 갈래(쉬었다 같은 채팅에 다시 — RELOAD_KEEP)
_TURNS = [0]                # 지금 채팅에서 성공한 왕복 수 — config.copilotAuto.chatTurns 에 닿으면 다음 왕복은 새 채팅
_CHAT_TURNS = [None]        # chatTurns 캐시 (None = 아직 안 읽음)
CHAT_TURNS_DEFAULT = 12     # 한 채팅에 이어 보내는 왕복 상한. 0 = 묶음마다 새 채팅(LM22 1차 방식)
_RESUME = "resume"          # = copilot_auto.RESUME — 다음 단계의 첫 왕복을 앞 단계의 우리 채팅에 이어 보낸다(화면 확인은 드라이버)
_RELOAD_KEEP = "keep"       # = copilot_auto.RELOAD_KEEP — 새 채팅 대신 같은 대화를 그 자리에서 새로 고친 뒤 이어 보낸다(AF32)
# 이어 쓸 수 있는 왕복 이름(정제·Agentic·워크플로우·세부업무 병합의 첫 왕복) — 판정 묶음·체계 수립은 늘 예전 규칙(새 채팅)
RESUME_NAMES = ("refine", "agentic", "flow", "detail3")


def chat_turns():
    """config.copilotAuto.chatTurns — 한 채팅에서 이어 보내는 왕복 수. 묶음(청크)이 같은 채팅에서 이어지면 Copilot 이
    앞 묶음의 판정·이름 짓기를 기억해 과제·세부업무 표기가 일관된다(제보: '청크마다 새 채팅이라 기억이 안 이어진다').
    너무 길어진 채팅은 답이 끊기거나 앞 답을 되풀이하므로 상한마다 새 채팅으로 넘어간다. 0 이면 묶음마다 새 채팅."""
    if _CHAT_TURNS[0] is None:
        v = CHAT_TURNS_DEFAULT
        try:
            with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
                raw = (json.load(f).get("copilotAuto") or {}).get("chatTurns", CHAT_TURNS_DEFAULT)
            v = int(raw)
            if v < 0:
                v = CHAT_TURNS_DEFAULT
        except (OSError, ValueError, TypeError):
            v = CHAT_TURNS_DEFAULT
        _CHAT_TURNS[0] = v
    return _CHAT_TURNS[0]
                            # (끊긴 생성·오류 문구가 남은 채팅에 이어 보내면 다음 답까지 오염된다, 실측)
_STUB_NOTED = [False]       # 스텁 응답임을 로그에 한 번만 남긴다
_LAST_PROMPT = [None]       # (경로, 본문) — 직전 성공 왕복 뒤 지운 프롬프트 파일. note_bad_reply 가 되살린다(V-06)
_HARD = [False]             # 이 프로세스가 강한 사용량 제한(세 번 쉬고도 막힘)을 봤다 — 다음 일시 오류는 쉬지 않고 바로 hard
_COOLED = [0.0]             # 이 프로세스가 쉰 초 합계(COOLDOWN_CAP_SEC 상한)
_COOLDOWNS = [0]            # 이 프로세스의 '쉬고 다시 보내기' 횟수(ai_judgments.cooldowns)
_MODEL_FALLBACK = [""]      # 두 번 쉬고도 막히면 이 프로세스의 남은 왕복은 이 모델로(config.copilotAuto.fallbackModel)
_THR_CHECKED = [False]      # 첫 왕복 전에 다른 프로세스의 강한 제한 기록(copilot_auto.throttle_state)을 봤는가
_RUN_STOP_SAID = [False]    # '이번 실행은 사용량 제한으로 멈췄다' 줄을 이 프로세스에서 이미 찍었나(한 번만)
_BUDGET_SAID = [False]      # '이번 실행의 쉬는 시간(runWaitMaxSec)을 다 썼다' 줄을 이 프로세스에서 이미 찍었나(한 번만)
_WAIT_TICKS = [0]           # 대기 진행 줄의 누적 눈금 — 진행 지킴이(core.watch)의 진행 시계가 늘 앞으로 가게


def _restore_prompt():
    """직전 성공 왕복의 프롬프트 파일을 되살린다 — 답은 왔지만 해석하지 못한 청크는 '회사 Copilot 에 붙여 넣기' 안내
    대상이라 파일이 남아 있어야 한다. 한 번만 되살린다(다음 왕복이 시작되면 잊는다)."""
    lp = _LAST_PROMPT[0]
    _LAST_PROMPT[0] = None
    if not lp:
        return
    try:
        with open(lp[0], "w", encoding="utf-8") as f:
            f.write(lp[1])
    except OSError:
        pass


def note_bad_reply():
    """호출자가 '응답을 받았지만 해석하지 못했다'고 알린다 — 다음 copilot_send 는 새 채팅에서,
    그리고 방금 지운 프롬프트 파일(report\\judge_<name>_<tag>.md)은 되살린다(V-06).
    LM28: 드라이버가 이 프로세스에 올라와 있으면 그 채팅을 '온전하지 않음'으로 적는다 — 다음 단계가 이어 쓰지 않는다(chat_mark_bad)."""
    _NEED_FRESH[0] = True
    _restore_prompt()
    m = sys.modules.get("copilot_auto")
    if m is not None and hasattr(m, "chat_mark_bad"):
        try:
            m.chat_mark_bad()
        except Exception:  # noqa: BLE001 - 기록이 판정을 막지 않게
            pass
def who_label(who, n=16):
    """프롬프트에 싣는 상대(who) 표기 — 내가 보낸 메일('나')이면 '나', 그 밖은 늘 ""(D8). 가명(p:…)·이름·주소·도메인은
    Copilot 에 보내지 않는다. n 은 옛 호출 꼴과 맞추는 자리(쓰지 않는다)."""
    return "나" if str(who or "").strip() == "나" else ""


def _ca():
    """드라이버 모듈(tools/copilot_auto.py) — 인프로세스 왕복·G3 관문용. 임포트에 부작용이 없다(stdout 재설정은 CLI 만).
    이미 올라와 있으면(시험·다른 호출자) 그것을 쓴다."""
    m = sys.modules.get("copilot_auto")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("copilot_auto", os.path.join(ROOT, "tools", "copilot_auto.py"))
        m = importlib.util.module_from_spec(spec)
        sys.modules["copilot_auto"] = m
        try:
            spec.loader.exec_module(m)
        except BaseException:
            sys.modules.pop("copilot_auto", None)
            raise
    return m


def chat_note():
    """단계 끝 한 줄 '[copilot] 채팅 정리: 만든 n · 지운 m · 남긴 k (사유: …)' — 이 프로세스가 연·지운·남긴 Copilot 채팅 수(숫자와
    사유만 — 제목·글 없음). 드라이버를 이 프로세스에서 쓰지 않았거나(inProcess=false — 자식 프로세스) 한 일이 없으면 찍지 않는다.
    마지막 줄 JSON 규약 때문에 JSON 줄보다 먼저 부른다(judge·refine·agentic·flow)."""
    m = sys.modules.get("copilot_auto")
    try:
        s = m.chat_line() if m is not None and hasattr(m, "chat_line") else ""
    except Exception:  # noqa: BLE001 - 기록 한 줄이 단계를 막지 않는다
        s = ""
    if s:
        print(s, flush=True)


def _inproc():
    """config.copilotAuto.inProcess — 기본 true(config.default.json). false 면 예전처럼 드라이버를 자식 프로세스로."""
    v = _copilot_cfg().get("inProcess", True)
    return not (v is False or str(v).strip().lower() in ("0", "false", "no", "n", "off"))


def g3_rows(rows, fields=("text",)):
    """G3 행 관문(copilot_auto.gate_rows → privacy.gate_items) → (보낼 행 사본, {제외 사유: 건수})."""
    return _ca().gate_rows(rows, fields)


def g3_prompt(text):
    """G3 최종 프롬프트 검사 → True = 보내도 됨(관문을 세우지 못하면 False)."""
    try:
        return bool(_ca().gate_ok(text))
    except Exception:  # noqa: BLE001 - 관문 오류 = 보내지 않음(fail-closed)
        return False


def g3_pick(rows, k, fields=("text",)):
    """표본용 — rows 전체에 고르게 퍼진 2k 행(끝 포함)만 관문에 통과시킨다(전체를 정제하지 않는다). 순서는 유지."""
    if not rows:
        return []
    n = len(rows)
    m = min(n, max(1, 2 * int(k)))
    idx = sorted({round(j * (n - 1) / (m - 1)) for j in range(m)}) if m > 1 else [n - 1]
    return g3_rows([rows[i] for i in idx], fields)[0]


_AD_FLAG = re.compile(r"(?<![a-z])ad(?![a-z])", re.I)


def is_ad_row(r):
    """signals 의 flag 열에 'ad'(G2 광고 의심)가 있는가."""
    return bool(_AD_FLAG.search(str((r or {}).get("flag") or "")))


def _is_transient(res):
    """쉬었다가 같은 묶음을 다시 보낼 일시 실패인가 — 실패이고, 관문 차단·사람이 손댈 일(explain_failure fatal)이 아니며,
    phase 가 TRANSIENT_PHASES(사용량 제한·오류 응답·무응답·빈 답·시간 초과·드라이버 오류)이거나 '시간 초과' 문구거나
    사유가 네트워크(R-NET)·전용 Edge 사용 중(R-EDGEBUSY)일 때.
    LM28: 느린 긴 답(slow — 드라이버가 왕복 예산 끝에 받은 데까지 돌려준 답)은 일시 실패가 아니다 — 같은 묶음을 다시 보내면 같은 길이의
    답을 또 기다리고 Copilot 이 앞 채팅의 답을 뒤에서 마저 써 대화 목록에 같은 답이 쌓인다. 호출자가 받은 데까지 쓰고 빠진 것만 작게 묻는다."""
    if not isinstance(res, dict) or res.get("ok") or res.get("phase") == "blocked" or res.get("slow"):
        return False
    if explain_failure(res)[2]:
        return False
    return (str(res.get("phase") or "") in TRANSIENT_PHASES or "시간 초과" in str(res.get("error") or "")
            or str(res.get("reason") or "") in ("R-NET", "R-EDGEBUSY"))


def _run_wait_left():
    """이번 실행에서 더 쉴 수 있는 초(copilot_auto.run_wait_left — copilotAuto.runWaitMaxSec − 모든 단계가 쉰 초).
    실행 표식이 없거나(단계를 따로 돌림) 기록을 못 읽으면 무한 — 실행 합계로는 줄이지 않는다."""
    try:
        return float(_ca().run_wait_left())
    except Exception:  # noqa: BLE001 - 기록을 못 읽으면 실행 합계 상한 없음
        return float("inf")


def _cool_room(sec):
    """쉴 수 있는 초 — 바라는 sec 를 전체 마감(AF32_AI_DEADLINE − 2분)·프로세스 합계 상한(COOLDOWN_CAP_SEC)·이번 실행의 남은
    쉬는 시간(_run_wait_left — copilotAuto.runWaitMaxSec) 안으로."""
    room = min(COOLDOWN_CAP_SEC - _COOLED[0], _run_wait_left())
    try:
        at = float(os.environ.get("AF32_AI_DEADLINE") or 0)
    except ValueError:
        at = 0.0
    if at > 0:
        room = min(room, at - time.time() - 120.0)
    return max(0.0, min(float(sec), room))


def _note_cooled(sec):
    """방금 sec 초 쉬었다 — 프로세스 합계(_COOLED)와 이번 실행의 합계(copilot_auto.add_run_wait)에 더한다. 기록 실패는 무시한다."""
    _COOLED[0] += sec
    try:
        _ca().add_run_wait(sec)
    except Exception:  # noqa: BLE001 - 기록이 쉬기·왕복을 막지 않게
        pass


def wait_room(sec):
    """다른 모듈(agentic·flow)이 쉬기 전에 — 바라는 sec 중 쉴 수 있는 초(_cool_room: 전체 마감·프로세스 합계·이번 실행의 남은 몫)."""
    return _cool_room(sec)


def note_waited(sec):
    """다른 모듈(agentic·flow)이 sec 초 쉰 뒤 — 프로세스·실행 합계에 더한다(_note_cooled)."""
    _note_cooled(sec)


def _fmt_wait(sec):
    """쉬는 시간 표기 — 분으로 나눠떨어지면 '1분(60초)', 아니면 '90초'(줄인 값을 분으로 반올림해 부풀려 말하지 않게)."""
    s = int(round(float(sec)))
    return f"{s // 60}분({s}초)" if s >= 60 and s % 60 == 0 else f"{s}초"


def _budget_line():
    """이번 실행의 쉬는 시간 합계(copilotAuto.runWaitMaxSec)를 다 썼을 때의 한 줄."""
    try:
        m = int(round(float(_ca().run_wait_max())))
    except Exception:  # noqa: BLE001
        m = 300
    tail = " — 이 단계의 남은 묶음은 보내지 않고 여기까지의 결과를 지킵니다(1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행])"
    if m <= 0:
        return "        이번 실행은 Copilot 을 기다리며 쉬지 않게 설정돼 있습니다(copilotAuto.runWaitMaxSec 0)" + tail
    total = f"{m // 60}분" if m >= 60 and m % 60 == 0 else f"{m}초"
    return f"        이번 실행에서 Copilot 을 기다리며 쉬는 시간(모두 {total} — copilotAuto.runWaitMaxSec)을 다 썼습니다" + tail


def _cooldown(sec):
    """sec 초 쉰다 — 30초마다 진행 줄('Copilot 대기')을 찍어 진행 지킴이(core.watch)의 무진전 시계가 멈추지 않게(쉬는 동안 끊기지 않게).
    눈금은 프로세스 누적이라 쉬기를 거듭해도 늘 앞으로 간다."""
    end = time.monotonic() + max(0.0, float(sec))
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        _WAIT_TICKS[0] += 1
        progress("Copilot 대기", _WAIT_TICKS[0], max(_WAIT_TICKS[0], int(COOLDOWN_CAP_SEC // 30)))
        time.sleep(min(30.0, left))


def _fallback_model():
    """config.copilotAuto.fallbackModel — 키가 없으면 '자동', 빈 값이면 끔('')."""
    v = _copilot_cfg().get("fallbackModel", "자동")
    return str(v).strip() if v is not None else ""


def _pre_throttle_wait():
    """이 프로세스의 첫 왕복 전에 한 번 — 다른 프로세스(판정·정제·Agentic …)가 5분(HARD_RECENT_SEC) 안에 강한 제한을 남겼으면
    남은 시간만 쉰다(전체 마감·이번 실행의 쉬는 시간 합계 안 — _cool_room). 예전에는 판정이 막힌 직후 다음 단계가 15초 만에 같은
    벽으로 들어갔다. 합계를 다 써 쉴 수 없으면 쉬지 않고 한 번만 보내 본다(그렇다고 한 줄 알린다).
    returns True = 그런 기록이 있었다 — 그 뒤 첫 왕복도 막히면 쉬는 사다리 없이 바로 hard."""
    if _THR_CHECKED[0]:
        return False
    _THR_CHECKED[0] = True
    try:
        ts = _ca().throttle_state(run=True)
    except Exception:  # noqa: BLE001 - 기록을 못 읽으면 없는 것으로 본다
        ts = None
    if not ts or not ts[1] or float(ts[0]) >= HARD_RECENT_SEC:
        return False
    sec = _cool_room(HARD_RECENT_SEC - float(ts[0]))
    # LM28 — 지난 실행이 사용량 제한으로 멈춘 기록이면 그렇다고 분명히 말한다(같은 실행의 기록은 copilot_send 가 먼저 걸렀다)
    rid = str(ts[2] or "") if len(ts) > 2 else ""
    if sec >= 1:
        if rid and rid != _run_id():
            print(f"        지난 실행이 Copilot 사용량 제한(요청이 너무 많음)으로 멈췄습니다({float(ts[0]) / 60:.0f}분 전) — "
                  f"{_fmt_wait(sec)} 쉬고 한 번 보내 봅니다(그래도 막히면 이 단계도 멈추고 여기까지의 결과를 지킵니다)", flush=True)
        else:
            print(f"        Copilot 사용량 제한 기록({float(ts[0]) / 60:.0f}분 전) — {_fmt_wait(sec)} 쉬고 보냅니다", flush=True)
        _cooldown(sec)
        _note_cooled(sec)
    elif _run_wait_left() < 1:
        print("        이번 실행에서 쉴 수 있는 시간을 다 써 쉬지 않고 한 번만 보내 봅니다(그래도 막히면 이 단계도 멈춥니다)",
              flush=True)
    return True


def _run_id():
    """이번 실행의 표식(run.py 가 시작 때 싣는 AF32_RUN_ID) — 단계를 따로 돌리면 ""."""
    return str(os.environ.get("AF32_RUN_ID") or "").strip()


def _run_stopped():
    """이번 실행이 Copilot 사용량 제한으로 AI 단계를 멈췄는가 — 강한 제한 기록(copilot_auto.throttle_state)의 실행 표식이 지금 실행과
    같을 때만. 표식이 없는 실행(단계를 따로 돌림)·지난 실행의 기록·옛 판 기록(표식 없음)은 아니다(예전처럼 _pre_throttle_wait)."""
    rid = _run_id()
    if not rid:
        return False
    try:
        ts = _ca().throttle_state(run=True)
    except Exception:  # noqa: BLE001 - 기록을 못 읽으면 없는 것으로 본다
        return False
    return bool(ts and ts[1] and len(ts) > 2 and str(ts[2] or "") == rid)


def _run_stop_result():
    """같은 실행이 사용량 제한으로 멈춘 뒤 — 보내지 않고(남은 시간 쉬기도 없이) 강한 제한 결과를 돌려준다. 호출자는 강한 제한과 똑같이
    남은 묶음을 보내지 않고 여기까지의 결과를 지킨다(규칙 판정·지난 결과 · abort_kind 'throttle')."""
    _HARD[0] = True
    if not _RUN_STOP_SAID[0]:
        _RUN_STOP_SAID[0] = True
        print("        이번 실행은 Copilot 사용량 제한(요청이 너무 많음)으로 AI 단계를 멈췄습니다 — 이 단계는 Copilot 에 보내지 않고 "
              "여기까지의 결과를 지킵니다(1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행])", flush=True)
    return {"ok": False, "phase": "throttled", "reason": "R-THROTTLE", "hard": True, "run_stop": True,
            "error": "Copilot 사용량 제한 — 이번 실행은 더 보내지 않음",
            "hint": "Copilot 이 「요청이 너무 많다」고 해 이번 실행의 AI 단계를 멈췄습니다 — 1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행]"}


def _throttle_wait_sec():
    """config.copilotAuto.throttleWaitSec — 사용량 제한이면 한 번 쉬는 초(기본 THROTTLE_WAIT_SEC). 0 이면 쉬지 않고 바로 멈춘다.
    음수·글자는 기본값. 프로세스 합계 상한(COOLDOWN_CAP_SEC)을 넘기지 않는다 — 실제로 쉬는 초는 copilot_send 가 _cool_room 으로
    한 번 더 줄인다(전체 마감·이번 실행의 쉬는 시간 합계 copilotAuto.runWaitMaxSec)."""
    v = _copilot_cfg().get("throttleWaitSec", THROTTLE_WAIT_SEC)
    try:
        n = float(THROTTLE_WAIT_SEC if v is None or v == "" else v)
    except (TypeError, ValueError):
        n = float(THROTTLE_WAIT_SEC)
    if n < 0:
        n = float(THROTTLE_WAIT_SEC)
    return min(n, float(COOLDOWN_CAP_SEC))


def _send_once(prompt_text, pf, name, want_fresh, n_parts, reload=False):
    """_transport 1회 — 새로 고침(reload)·대체 모델(_MODEL_FALLBACK)은 켜졌을 때만 넘긴다(옛 꼴의 _transport 와도 맞게)."""
    kw = {}
    if reload:
        kw["reload"] = _RELOAD_KEEP if reload == _RELOAD_KEEP else True     # AF32 — 같은 대화 새로 고침은 그대로 넘긴다
    if _MODEL_FALLBACK[0]:
        kw["model"] = _MODEL_FALLBACK[0]
    res = _transport(prompt_text, pf, name, want_fresh, roundtrip_timeout(n_parts), **kw)
    if not isinstance(res, dict):
        return {"ok": False, "error": "드라이버 출력 형식 오류", "hint": str(res)[-150:]}
    return res


def _go_hard(res, k, throttle=False, budget=False):
    """강한 사용량 제한 — 이 프로세스의 다음 일시 오류는 쉬지 않고 바로 hard, 다른 프로세스도 알게 기록(copilot_auto.note_throttle).
    결과에 hard=True — explain_failure 가 fatal 로 보고 호출자(judge·refine·agentic·flow)가 남은 묶음을 보내지 않는다.
    throttle=True(LM28 — 사용량 제한 「요청이 너무 많음」으로 멈춤)면 실행 표식(AF32_RUN_ID)·갈래 'throttle' 도 적는다 — 같은 실행의
    뒤 단계는 보내지 않는다. 일시 오류 사다리 끝의 hard 는 표식 없이 적는다(다음 단계는 예전처럼 남은 시간만 쉬고 한 번 보낸다).
    budget=True(LM28 — 이번 실행의 쉬는 시간 합계 runWaitMaxSec 를 다 써서 멈춤)면 그렇다는 한 줄만 찍는다(프로세스에 한 번 —
    '계속 막고 있다'·'n번 쉬고도' 처럼 사실과 다른 줄을 함께 찍지 않게)."""
    first = not _HARD[0]
    _HARD[0] = True
    try:
        if throttle:
            _ca().note_throttle(hard=True, run=_run_id(), kind="throttle")
        else:
            _ca().note_throttle(hard=True)
    except Exception:  # noqa: BLE001 - 기록 실패가 판정을 막지 않게
        pass
    if budget:
        if not _BUDGET_SAID[0]:
            _BUDGET_SAID[0] = True
            print(_budget_line(), flush=True)
    elif first and throttle:
        print("        Copilot 이 「요청이 너무 많다」며 계속 막고 있습니다(사용량 제한) — 이번 실행의 AI 단계는 더 보내지 않고 "
              "여기까지의 결과를 지킵니다(1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행])", flush=True)
    elif first:
        print("        " + (f"Copilot 이 {k}번 쉬고 다시 보내도 막혔습니다" if k else "Copilot 이 여전히 막혀 있습니다")
              + "(강한 사용량 제한) — 남은 묶음은 보내지 않고 여기까지의 결과를 지킵니다(1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행])",
              flush=True)
    return dict(res, hard=True)


def _abort_kind_of(res):
    """치명 실패 결과 → 중단 갈래: throttle(강한 사용량 제한) · login(로그인 만료·개인 계정) · fatal(그 밖의 사람이 손댈 일)."""
    res = res if isinstance(res, dict) else {}
    if res.get("hard"):
        return "throttle"
    rs = str(res.get("reason") or "")
    if res.get("phase") == "login_required" or rs.startswith("R-LOGIN") or rs == "R-PERSONAL":
        return "login"
    return "fatal"


def with_prefix(prompt_text):
    """D19 머리말(AI_PREFIX)로 시작하는 프롬프트 — 이미 그 문장으로 시작하면 그대로."""
    s = str(prompt_text or "")
    return s if s.lstrip().startswith(AI_PREFIX) else AI_PREFIX + "\n" + s


def copilot_send(prompt_text, tag, name, fresh=None):
    """Copilot 왕복 1회 — 프롬프트를 report\\judge_{name}_{tag}.md 로 쓰고 드라이버를
    부른다(분할·서약은 드라이버 몫 · inProcess 면 같은 프로세스, 아니면 자식 프로세스). 반환 {"ok","reply",...,"error","hint"}.
    fresh: True = 새 채팅에서 시작, None(기본) = **같은 채팅에서 이어서** — 이 프로세스의 첫 성공 왕복까지만 새 채팅
           (+ 직전 왕복이 실패/해석 불가·끊김이면 새 채팅, + 한 채팅의 왕복이 config.copilotAuto.chatTurns 에 닿으면 새 채팅,
           chatTurns=0 이면 매번 새 채팅), False = 무조건 이어서.
           판정·정제·Agentic·워크플로우의 묶음(청크)은 모두 None 으로 보내 앞 묶음의 문맥(과제·세부업무 표기)을 잇는다 —
           묶음마다 새 채팅을 열면 Copilot 의 기억이 끊겨 표기가 흔들렸다(제보). 프롬프트는 여전히 혼자서 완결이라 드라이버가
           재시도로 새 채팅을 열어도 답이 나온다.
    반환 dict 의 cut=True 는 답이 생성 중단 문구로 끝났다는 뜻 — 잘린 JSON 복구 대상.
    프롬프트 파일은 **성공한 왕복이면 회수 직후 지운다**(V-06: 실행당 64~83개가 report\\ 에 누적돼 신호 원문
    사본이 쌓였다) — 실패한 왕복(왕복 자체 실패, 답에 JSON 꼴이 없음)의 것만 남겨 '회사 Copilot 에 붙여 넣기' 안내에 쓴다.
    답은 왔지만 호출자가 해석하지 못한 경우는 note_bad_reply() 가 방금 지운 파일을 되살린다.
    LM28: 먼저 G3 최종 검사(g3_prompt) — 걸리면 파일도 쓰지 않고(붙여 넣기 안내 대상이 아니다) {"phase":"blocked"} 를
    돌려준다. 호출자는 그 묶음을 skipped 로 세고 그 행만 규칙으로 둔다(재시도·새 채팅 전환 없음).
    config.copilotAuto.inProcess(기본 true)면 같은 프로세스에서 왕복(_transport → copilot_auto.send_inproc).
    LM28 진단 A — 일시 오류·사용량 제한(_is_transient)이면 바로 다시 보내지 않고 COOLDOWN_SEC(1·2·2분)만큼 쉬었다가 페이지를
    새로 고치고 새 채팅에서 같은 프롬프트를 다시 보낸다(결과의 cooldowns = 쉬고 다시 보낸 횟수 — 호출자는 또 쉬지 않는다).
    두 번 쉬고도 막히면 이 프로세스의 남은 왕복은 config.copilotAuto.fallbackModel(기본 '자동', 빈 값이면 끔)로 보낸다.
    세 번 쉬고도 막히면 결과에 hard=True(강한 제한 — explain_failure 가 fatal 로 본다)를 달고, 이 프로세스의 다음 일시 오류는
    쉬지 않고 바로 hard 다. 쉬는 시간은 전체 마감(AF32_AI_DEADLINE − 2분)·프로세스 합계 5분·이번 실행의 합계(모든 단계 —
    copilotAuto.runWaitMaxSec, 기본 5분) 안. 실행 합계를 다 쓰면 다음 일시 오류·사용량 제한은 쉬지 않고 바로 hard(_go_hard budget=True ·
    사용량 제한이면 실행 표식도). 다른 프로세스가 5분 안에 남긴 강한 제한 기록이 있으면 첫 왕복 전에 남은 시간만 한 번 쉰다(실행 합계 안).
    chatTurns 회전(새 채팅)마다 페이지도 새로 고친다.
    LM28 — 사용량 제한(phase 'throttled' · 「요청이 너무 많음」)은 위 사다리 대신 copilotAuto.throttleWaitSec(기본 2분, 0 = 쉬지 않음)
    만큼 **한 번** 쉬고 새로 고쳐 다시 보낸다. 그래도 막히면 hard + 실행 표식 기록(_go_hard throttle=True) — 같은 실행(AF32_RUN_ID)의
    다음 copilot_send 는 이 프로세스든 뒤 단계 프로세스든 보내지 않고(남은 시간 쉬기도 없이) 바로 hard 'throttled'(_run_stop_result).
    다른 일시 오류(무응답·빈 답·오류 문구·시간 초과 …)는 사다리(1·2·2분)를 탄다.
    LM28 — 느린 긴 답(결과 slow — 드라이버가 왕복 예산 끝에 받은 데까지 돌려준 ok+cut)은 쉬기·다시 보내기 사다리를 타지 않는다
    (_is_transient). 정제·Agentic·워크플로우의 첫 왕복(RESUME_NAMES)은 앞 단계의 우리 채팅을 이어 쓸 수 있다(드라이버 RESUME).
    AF32(D19) — 모든 프롬프트의 맨 앞에 AI_PREFIX 를 여기 한 곳에서 붙인다(이미 그 문장으로 시작하면 다시 붙이지 않는다).
    최종 검사·프롬프트 파일·드라이버는 머리말을 붙인 프롬프트를 본다.
    D10 — 하루 중 시각(HH:MM)은 프롬프트와 프롬프트 파일(report\\judge_*.md)에 싣지 않는다(privacy.mask_clock — G2·G3 의 뒷받침)."""
    import privacy
    prompt_text = privacy.mask_clock(with_prefix(prompt_text))
    if _run_stopped():
        return _run_stop_result()            # 이번 실행은 사용량 제한으로 멈췄다 — 프롬프트 파일도 쓰지 않는다(보내지 않았다)
    if not g3_prompt(prompt_text):
        return {"ok": False, "status": "blocked", "phase": "blocked", "reason": "R-GATE",
                "error": "개인정보 관문(G3) — 제한 고객·민감정보·식별번호·카나리아가 있어 보내지 않음",
                "hint": "이 묶음은 규칙 판정으로 처리합니다 — 재시도하지 않습니다"}
    pf = os.path.join(ROOT, "report", f"judge_{name}_{tag}.md")
    _LAST_PROMPT[0] = None                   # 새 왕복이 시작되면 앞 왕복의 파일은 더 되살리지 않는다
    try:
        # 백신·DLP·열린 앱이 이전 프롬프트 파일을 잠그면 판정이 통째로 죽는다(실측)
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt_text)
    except OSError as e:
        return {"ok": False, "error": f"프롬프트 파일 쓰기 실패({type(e).__name__})",
                "hint": f"{pf} 를 잠근 프로그램을 닫고 재실행"}
    n_parts = n_parts_of(prompt_text)                          # 드라이버와 같은 규칙으로 센다
    limit = chat_turns()
    want_fresh = (fresh is True
                  or (fresh is None and (_FIRST_SEND[0] or _NEED_FRESH[0] or limit <= 0 or _TURNS[0] >= limit)))
    # chatTurns 회전(같은 탭을 오래 쓴 뒤의 새 채팅)이면 페이지도 새로 고친다 — 몇 시간 쓴 탭(만료된 페이지 토큰·커진 대화)은
    # 새 채팅 버튼만으로는 실패가 이어졌다(진단 A). 첫 왕복·실패 뒤의 새 채팅은 예전처럼 버튼만.
    reload = bool(want_fresh and not _FIRST_SEND[0] and 0 < limit <= _TURNS[0])
    if reload and fresh is None and not _NEED_FRESH[0]:
        _ROTATIONS[0] += 1                       # AF32 — 회전은 그대로 두되 센다(판정 기록 rotations · 구조 줄)
    if want_fresh:
        # 판정의 첫 왕복은 새 채팅에서 — 수집 단계의 실패 대화가 판정을 오염시키지 않게.
        # 직전 왕복이 실패했을 때도 새 채팅 — 끊긴 생성·오류 문구가 남은 채팅은 다음 답을 오염시킨다.
        # 한 채팅의 왕복이 chatTurns 에 닿아도 새 채팅 — 너무 길어진 대화는 답이 끊기거나 앞 답을 되풀이한다.
        _TURNS[0] = 0
    resume = False
    if (want_fresh and fresh is None and _FIRST_SEND[0] and not _NEED_FRESH[0] and limit > 0
            and str(name or "").startswith(RESUME_NAMES) and _inproc()):
        # LM28 — 다음 단계(정제·Agentic·워크플로우)의 첫 왕복: 앞 단계의 우리 채팅이 온전하게 끝났고(last_ok) 20분 안이며 chatTurns 가
        # 남았으면 새 채팅 대신 이어 쓴다 — 단계마다 새 채팅이 하나씩 대화 목록에 쌓이던 것을 줄인다. 화면이 그 채팅인지는 드라이버가
        # 보내기 직전에 다시 보고(앵커·대화 id·생성 중 아님) 아니면 예전처럼 새 채팅을 연다(결과 resumed). 소유 기록은 그대로다.
        try:
            can, sent = _ca().chat_resumable(turns=limit)
        except Exception:  # noqa: BLE001 - 모르면 예전처럼 새 채팅
            can, sent = False, 0
        if can:
            resume = True
            _TURNS[0] = int(sent)
    pre_hard = _pre_throttle_wait()
    res = _send_once(prompt_text, pf, name, _RESUME if resume else want_fresh, n_parts, reload)
    k = lk = 0                                   # k = 쉬고 다시 보낸 횟수(결과 cooldowns) · lk = 일시 오류 사다리의 단
    thr_waited = False                           # 사용량 제한으로 이미 한 번 쉬었다(LM28 — 두 번째는 쉬지 않고 hard)
    while _is_transient(res):
        if str(res.get("phase") or "") == "throttled":
            # 사용량 제한 — 일시 오류 사다리를 타지 않는다(그동안의 재전송이 제한을 늘린다). throttleWaitSec 한 번만 쉬고 다시.
            wait = _throttle_wait_sec()
            if _HARD[0] or pre_hard or thr_waited or wait <= 0:
                res = _go_hard(res, k, throttle=True)    # 이번 실행의 AI 단계를 멈춘다(실행 표식 기록)
                break
            sec = _cool_room(wait)
            if sec < min(float(COOLDOWN_MIN_SEC), wait):
                spent = _run_wait_left() < COOLDOWN_MIN_SEC    # 이번 실행의 쉬는 시간 합계(runWaitMaxSec)를 다 썼다
                if spent or _COOLED[0] >= COOLDOWN_CAP_SEC - COOLDOWN_MIN_SEC:
                    res = _go_hard(res, k, throttle=True, budget=spent)
                break                            # 전체 마감이 가깝다 — 쉬지 않고 실패를 그대로 돌려준다
            print(f"        Copilot 사용량 제한(요청이 너무 많음) — {_fmt_wait(sec)} 쉬고 새로 고친 뒤 같은 묶음을 "
                  "한 번만 다시 보냅니다(그래도 막히면 이번 실행의 AI 단계를 멈추고 여기까지의 결과를 지킵니다)", flush=True)
            _cooldown(sec)
            _note_cooled(sec)
            _COOLDOWNS[0] += 1
            k += 1
            thr_waited = True
            _TURNS[0] = 0
            res = _send_once(prompt_text, pf, name, True, n_parts, True)
            continue
        if _HARD[0] or pre_hard or lk >= len(COOLDOWN_SEC):
            res = _go_hard(res, k)               # 쉬고도 막혔다(또는 이미 강한 제한) — 더 보내지 않는다
            break
        sec = _cool_room(COOLDOWN_SEC[lk])
        short = sec < COOLDOWN_MIN_SEC
        spent = short and _run_wait_left() < COOLDOWN_MIN_SEC  # 이번 실행의 쉬는 시간 합계(runWaitMaxSec)를 다 썼다
        if short and (spent or _COOLED[0] >= COOLDOWN_CAP_SEC - COOLDOWN_MIN_SEC):
            res = _go_hard(res, k, budget=spent)   # 쉬는 시간 합계를 다 썼다 — 더 보내지 않는다(대체 모델 안내도 없이)
            break
        if lk == 2 and not _MODEL_FALLBACK[0]:
            fb = _fallback_model()
            if fb:
                _MODEL_FALLBACK[0] = fb
                print(f"        두 번 쉬고도 막혀 이 단계의 남은 왕복은 '{fb}' 모델로 보냅니다")
        if short:
            break                                # 전체 마감이 가깝다 — 쉬지 않고 실패를 그대로 돌려준다
        print(f"        Copilot 일시 오류({str(res.get('phase') or res.get('error') or '')[:30]}) — "
              f"{_fmt_wait(sec)} 쉬고 새로 고친 뒤 같은 묶음을 다시 보냅니다 ({lk + 1}/{len(COOLDOWN_SEC)})", flush=True)
        _cooldown(sec)
        _note_cooled(sec)
        _COOLDOWNS[0] += 1
        k += 1
        lk += 1
        if str(res.get("phase") or "") in NOANS_PHASES:
            # AF32 — 실패한 왕복이 답 글을 남기지 않았다(무응답·빈 답): 새 채팅을 열지 않고 같은 대화를 그 자리에서 새로 고쳐 다시 보낸다
            # (드라이버 RELOAD_KEEP — 우리 채팅임을 다시 확인하고, 못 하면 그때 새 채팅). 오류 문구가 남은 채팅은 예전처럼 새 채팅.
            res = _send_once(prompt_text, pf, name, False, n_parts, _RELOAD_KEEP)
        else:
            _TURNS[0] = 0                        # 새로 고친 새 채팅에서 다시 보낸다
            res = _send_once(prompt_text, pf, name, True, n_parts, True)
    if k:
        res = dict(res, cooldowns=k)
    if res.get("phase") == "blocked":
        return res                           # 드라이버의 최종 검사에 걸렸다 — 보내지 않았으니 채팅 상태를 바꾸지 않는다
    if res.get("phase") == "stub" and not _STUB_NOTED[0]:
        _STUB_NOTED[0] = True
        print("        ※ AF32_COPILOT_STUB 스텁 응답 — 테스트 전용, 실제 Copilot 판정이 아닙니다")
    if res.get("ok"):
        _FIRST_SEND[0] = False       # 성공했을 때만 소진 — 실패하면 다음도 새 채팅
        _HARD[0] = False             # 제한이 풀렸다 — 다음 일시 오류는 다시 쉬는 사다리부터
        # LM30(2026-10-21) — 끊긴 답·느린 답(cut·slow) 뒤에도 새 채팅을 열지 않는다(사용자 제보: Copilot 채팅 도배). 호출자가 잘린 앞부분을 쓰고
        # 빠진 것만 작게 다시 묻는 왕복은 같은 채팅에 이어 보낸다 — 드라이버가 보내기 직전에 우리 채팅인지(앵커·대화 id) 다시 보고, 아니면 그때
        # 새 채팅을 연다(_continue_why). 예전에는 끊긴 답마다 다음 왕복이 새 채팅이었다. 해석 실패(note_bad_reply)·왕복 실패는 그대로 새 채팅.
        _NEED_FRESH[0] = False
        if resume and not res.get("resumed"):
            _TURNS[0] = 0                        # 이어 쓰려 했지만 화면이 그 채팅이 아니어서 새 채팅을 열었다
        # 드라이버가 재시도 사다리로 새 채팅을 열었으면 그 채팅의 첫 왕복이다
        _TURNS[0] = 1 if ("새 채팅" in str(res.get("retry") or "")) else _TURNS[0] + 1
        reply = str(res.get("reply") or "")
        if "{" in reply and "}" in reply:
            # 성공 왕복 — 프롬프트 파일은 지우되 본문은 기억해 둔다(해석 실패 시 note_bad_reply 가 되살림).
            # JSON 꼴이 전혀 없는 답(산문·거부 문구)은 해석 실패가 예정돼 있으니 파일을 그대로 둔다.
            _LAST_PROMPT[0] = (pf, prompt_text)
            try:
                os.remove(pf)
            except OSError:
                _LAST_PROMPT[0] = None
    else:
        _NEED_FRESH[0] = True
    return res


def _transport(prompt_text, pf, name, want_fresh, lim, reload=False, model=None):
    """드라이버 왕복 1회 → 결과 dict(--send 의 JSON 과 같은 꼴).
    · inProcess(기본): copilot_auto.send_inproc — 왕복마다 파이썬을 띄우지 않는다. 상한은 드라이버의 내부 데드라인
      (deadline = 지금 + lim → roundtripMaxSec·잠금 대기·CDP 소켓 timeout).
    · inProcess=false: 예전처럼 자식 프로세스(--send pf). 1분마다 경과를 찍고, 한도를 넘기면 **드라이버 프로세스만**
      끝낸다(taskkill 트리 종료는 쓰지 않는다 — Edge 는 Job 에서 떨어져 있어 다음 왕복이 이어 쓰고, 닫기는 close_own_edge).
    · reload(LM28 진단 A): 보내기 전에 채팅 페이지를 새로 고친다(쉬었다 다시 보내기·chatTurns 회전). model: 이번 왕복만
      모델을 바꾼다(두 번 쉬고도 막힐 때의 대체 모델). 둘 다 켜졌을 때만 드라이버에 넘긴다."""
    import threading
    if _inproc():
        try:
            ca = _ca()
        except Exception as e:  # noqa: BLE001 - 드라이버를 못 읽으면 사람이 손대야 한다(설치 손상)
            return {"ok": False, "error": f"드라이버 실행 실패({type(e).__name__})", "hint": str(e)[:150]}
        # 자식 프로세스 경로와 같이 1분마다 경과를 찍는다(스레드 — 프로세스를 띄우지 않는다). 화면이 멈춘 것처럼 보이지
        # 않게, 그리고 상태 파일이 없는 단계의 진행 지킴이(core.watch)(stdout 침묵 한도)가 정상 왕복을 끊지 않게.
        _stop = threading.Event()
        _t0 = time.time()

        def _beat_loop():
            while not _stop.wait(60):
                print(f"        … Copilot 응답 대기 {int((time.time() - _t0) / 60)}분 / 최대 {int(lim / 60)}분 ({name})",
                      flush=True)
        threading.Thread(target=_beat_loop, daemon=True).start()
        kw = {}
        if reload:
            kw["reload"] = _RELOAD_KEEP if reload == _RELOAD_KEEP else True
        if model:
            kw["cfg"] = dict(ca.load_cfg(), model=str(model))
        try:
            fr = _RESUME if want_fresh == _RESUME else bool(want_fresh)     # RESUME 은 그대로 — 드라이버가 화면을 보고 정한다
            return ca.send_inproc(prompt_text, fresh=fr, deadline=time.time() + float(lim),
                                  stage=str(name or "")[:40], **kw)
        finally:
            _stop.set()
    try:
        cmd = [sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"), "--send", pf]
        if want_fresh:
            cmd.append("--fresh")
        if reload:
            cmd.append("--reload-keep" if reload == _RELOAD_KEEP else "--reload")
        if model:
            cmd += ["--model", str(model)]
        # AF32_STAGE — 드라이버가 report\copilot_trace_YYYYMMDD.jsonl(날짜별 계측 파일)에 '어느 단계의 왕복인지' 를 남기게 한다.
        # 이름만 넘긴다(chunk3·refine1·wf1 …). 프롬프트 원문은 계측에 들어가지 않는다.
        # 왕복은 최장 roundtrip_timeout(기본 27분 × 조각 수)이다. 예전에는 그 동안 **출력이 한 줄도 없어**
        # 화면이 멈춘 것으로 보였다(제보 '무한 정지'). 이제 1분마다 경과를 찍는다.
        _p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                                 AF32_STAGE=str(name or "")[:40]),
                              creationflags=NO_WIN)
        # 답은 길다(워크플로우 판정은 수십~수백 KB). 파이프를 **읽으면서** 기다려야 한다 —
        # 끝난 뒤 한 번에 읽으면 자식이 윈도 파이프 버퍼를 넘겨 쓰다 막혀 영원히 끝나지 않는다(실측).
        _buf = []
        _rd = threading.Thread(target=lambda: _buf.append(_p.stdout.read() if _p.stdout else b""),
                               daemon=True)
        _rd.start()
        _t0 = _beat = time.time()
        while _p.poll() is None:
            time.sleep(1)
            _now = time.time()
            if _now - _t0 > lim:
                try:
                    _p.kill()                    # 드라이버만(TerminateProcess) — 자식이 스스로 접지 못한 경우의 안전판
                    _p.wait(timeout=30)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                raise subprocess.TimeoutExpired(cmd, lim)
            if _now - _beat >= 60:
                _beat = _now
                print(f"        … Copilot 응답 대기 {int((_now - _t0) / 60)}분 / 최대 {int(lim / 60)}분 ({name})",
                      flush=True)
        _rd.join(timeout=30)
        out = subprocess.CompletedProcess(cmd, _p.returncode, b"".join(_buf), b"")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "왕복 시간 초과",
                "hint": "Copilot 응답 지연 — 이 청크는 규칙 판정으로 진행"}
    except OSError as e:
        return {"ok": False, "error": f"드라이버 실행 실패({type(e).__name__})",
                "hint": str(e)[:150]}
    txt = (out.stdout or b"").decode("utf-8", "replace").strip()
    try:
        res = json.loads(txt.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "드라이버 출력 해석 실패", "hint": txt[:150]}
    if not isinstance(res, dict):
        return {"ok": False, "error": "드라이버 출력 형식 오류", "hint": txt[-150:]}
    return res


def _squash(s):
    return re.sub(r"\s+", "", str(s or ""))


_FP = "sha1:"      # skip 항목 접두어 — 지난 판 프롬프트 예시를 원문 없이 지문으로 기억한다(_fp)


def _fp(s):
    """공백을 뺀 원문의 sha1 지문('sha1:…') — 채팅에 남아 있을 수 있는 지난 판 예시를 원문 없이 에코 방어에 쓴다."""
    return _FP + hashlib.sha1(_squash(s).encode("utf-8")).hexdigest()


def _skip_set(skip):
    """skip(예시 원문 또는 _fp 지문) → 비교 집합 — 원문은 공백을 뺀 꼴, 지문은 그대로."""
    return {s if s.startswith(_FP) else _squash(s) for s in (skip or ()) if s}


def _skipped(raw, skip_n):
    """raw(답에서 찾은 JSON 원문)가 예시와 같은가 — 공백을 뺀 원문 또는 그 지문으로 비교."""
    if not skip_n:
        return False
    sq = _squash(raw)
    return sq in skip_n or _fp(sq) in skip_n


def rfind_json(reply, want_key, skip=()):
    """답 뒤쪽부터 '{' 를 거슬러 올라가며 want_key 를 가진 첫 완전한 JSON 객체를 찾는다.
    skip: 프롬프트에 실은 **출력 형식 예시** 문자열들(지난 판 예시는 _fp 지문) — 앵커 실패(fulltext)로 답에 프롬프트
    에코가 섞이면 예시가 '답'으로 해석돼 예시의 번호·이름이 판정에 들어갔다(실측: 판정 0·1행이 예시의 '프로젝트A/…',
    정제는 Level 3 '...'). 공백을 뺀 원문이 예시와 같으면(또는 그 지문이 같으면) 건너뛴다."""
    reply = str(reply or "")
    skip_n = _skip_set(skip)
    i = reply.rfind("{")
    n = 0
    while i != -1 and n < 600:
        try:
            o, end = _DEC.raw_decode(reply, i)
            if isinstance(o, dict) and want_key in o:
                if not _skipped(reply[i:end], skip_n):
                    return o
        except ValueError:
            pass
        n += 1
        i = reply.rfind("{", 0, i)
    return {}


def _close_truncated(text, i):
    """text[i:] 를 앞에서 훑어(문자열·이스케이프·괄호 상태) 최상위 객체 안 목록의 '마지막 완전한 원소'
    뒤에서 끊어 닫는다 → (dict, 쓴 원문) / (None, ""). {"키":[ 원소, 원소, 잘린원소 → {"키":[ 원소, 원소 ]}."""
    stack, in_str, esc = [], False, False
    last_good = -1
    j, n = i, len(text)
    while j < n:
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            stack.append(c)
        elif c in "}]":
            if not stack:
                break
            stack.pop()
            if not stack:                       # 최상위 객체가 닫혔다 — 그대로 해석
                raw = text[i:j + 1]
                try:
                    o = json.loads(raw)
                    return (o, raw) if isinstance(o, dict) else (None, "")
                except ValueError:
                    return None, ""
            if len(stack) == 2 and stack[1] == "[":   # 최상위 dict → 목록 → 원소 하나가 닫힘
                last_good = j + 1
        j += 1
    if last_good <= 0:
        return None, ""
    raw = text[i:last_good] + "]}"
    try:
        o = json.loads(raw)
        return (o, raw) if isinstance(o, dict) else (None, "")
    except ValueError:
        return None, ""


def repair_json(reply, want_key, skip=()):
    """잘린 JSON 복구 — Copilot 이 긴 답을 중간에 끊으면(길이 한도·생성 중단) {"j":[[…],[…],[12,"y","과
    처럼 끝난다. rfind_json 은 이런 답에서 아무것도 못 찾아 청크 전체가 규칙으로 떨어졌다. 마지막 완전한
    원소까지 닫아 해석하고, 호출자는 빠진 원소만 다시 묻는다. skip: rfind_json 과 같은 예시 방어.
    returns dict(빈 dict = 복구 불가)."""
    reply = str(reply or "")
    skip_n = _skip_set(skip)
    key = f'"{want_key}"'
    k = reply.rfind(key)
    tries = 0
    while k != -1 and tries < 50:
        i = reply.rfind("{", 0, k)
        if i != -1 and not reply[i + 1:k].strip():       # '{' 바로 뒤가 키 = 최상위 객체 시작
            o, raw = _close_truncated(reply, i)
            if isinstance(o, dict) and want_key in o and not _skipped(raw, skip_n):
                return o
        k = reply.rfind(key, 0, k)
        tries += 1
    return {}


# 판정 행 하나: [번호,"y"|"n"(,과제,유형,세부업무)] — JSON 이 통째로 깨졌을 때(여는 '{' 유실·표 변형)
# 완전한 행만 긁어내는 최후 수단. 프롬프트 예시 행은 strip_example_rows 가 에코일 때만 걸러낸다(V-04).
_ROW_RE = re.compile(
    r'\[\s*(\d{1,6})\s*,\s*"([ynYN][^"]{0,8})"\s*(?:,\s*"((?:[^"\\]|\\.){0,80})"\s*'
    r'(?:,\s*"((?:[^"\\]|\\.){0,20})"\s*(?:,\s*"((?:[^"\\]|\\.){0,80})"\s*)?)?)?\]')


def _unesc(g):
    """정규식이 잡은 JSON 문자열 조각의 이스케이프(\\" \\\\ \\n \\uXXXX)를 푼다 — 못 풀면 원문.
    예전에는 그대로 저장돼 '역슬래시\\\\경로'·'\\\\uc218\\\\uad11' 같은 값이 model/detail 에 들어갔다(V-04)."""
    if g is None or "\\" not in g:
        return g
    try:
        v = json.loads('"' + g + '"')
        return v if isinstance(v, str) else g
    except ValueError:
        return g


def scan_rows(reply, spans=False):
    """완전한 판정 행만 긁어낸다. spans=True 면 (행 목록, [(시작, 끝)]) — 예시 에코 판별용."""
    out, sp = [], []
    for m in _ROW_RE.finditer(str(reply or "")):
        row = [int(m.group(1)), _unesc(m.group(2))] + [_unesc(g) for g in m.groups()[2:] if g is not None]
        out.append(row)
        sp.append((m.start(), m.end()))
    return (out, sp) if spans else out


def strip_example_rows(reply, rows, spans):
    """정규식 경로의 예시 방어(V-04) — 답 전체(공백 제거)가 프롬프트 예시(지난 판 예시 지문 포함)와 같으면 전부 버리고,
    그 밖에는 예시의 두 행(JUDGE_EXAMPLE_ROWS 의 [0,"y","프로젝트A","개발",…] 또는 지난 판 첫 행 — 지문
    JUDGE_EXAMPLE_OLD_ROW0 — 뒤 [1,"n"])이 **그 순서로 붙어 예시처럼 `]}` 로 닫힌 경우**(프롬프트 에코)만 그 둘을
    버린다. 예전에는 예시와 같은 행을 낱개로 버려 진짜 [1,"n"]·[0,"y","프로젝트A",…] 가 사라졌다."""
    if _skipped(reply, _skip_set(JUDGE_EXAMPLES)):
        return []
    e0, e1 = JUDGE_EXAMPLE_ROWS

    def _is_e0(r):
        return r == e0 or (len(r) == len(e0) and _fp(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
                           in JUDGE_EXAMPLE_OLD_ROW0)
    keep, i = [], 0
    while i < len(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if (_is_e0(rows[i]) and nxt is not None and nxt[:2] == e1 and not any(nxt[2:])):
            gap = reply[spans[i][1]:spans[i + 1][0]]
            tail = reply[spans[i + 1][1]:spans[i + 1][1] + 12]
            if re.fullmatch(r"\s*,\s*", gap) and re.match(r"\s*\]\s*\}", tail):
                i += 2
                continue
        keep.append(rows[i])
        i += 1
    return keep


# ── [0] 과제 체계 수립 — 지정 과제는 항상 포함, 나머지는 표본에서 자동 발견 ──
def _sample_lines(rows, k, fmt):
    """rows 전체에 고르게 퍼진 k개 표본 줄 — 처음과 끝(마지막 행)을 반드시 포함한다.
    rows[::step][:k] 는 k < N < 2k 에서 '앞 k개' 가 되어 뒤쪽이 통째로 빠졌다 — 아래 식은 어느 N 에서도 처음과 끝을 담는다."""
    if not rows or k <= 0:
        return []
    n = len(rows)
    if n <= k:
        return [fmt(r) for r in rows]
    idx = sorted({round(j * (n - 1) / (k - 1)) for j in range(k)}) if k > 1 else [n - 1]
    return [fmt(rows[i]) for i in idx]


def _fit_rows(rows, k, fmt, head_len, budget=PROMPT_BUDGET, k_min=20):
    """고르게 퍼진 k 행을 골라 줄로 만들고, 머리말 + 표본이 budget 을 넘으면 표본을 고르게 줄인다(k_min 까지) → 줄 목록."""
    while True:
        lines = _sample_lines(rows, k, fmt)
        if k <= k_min or len(lines) <= k_min or head_len + sum(len(s) + 1 for s in lines) <= budget:
            return lines
        k = max(k_min, int(k * 0.85))
# l1(상위) 예시 값은 details.L1_META 에서 꺼낸다 — 상위 이름을 details 밖에 하드코딩하지 않는다(tools/check_l1.py)
TAXONOMY_EXAMPLE = json.dumps(
    {"models": [{"name": "과제A", "match": ["kwa"], "obs": "근거가 된 표본 조각", "l1": next(iter(details.L1_META))},
                {"name": "공통", "match": [], "l1": details.snap1("공통")}]},
    ensure_ascii=False, separators=(",", ":"))
CONSOLIDATE_EXAMPLE = '{"models":[{"name":"대표이름","match":["키워드"],"merged":["흡수된이름"]},{"name":"공통","match":[]}]}'
_UNMASK = {}                # ukey2(가려 보낸 글) → 원래 이름 — Copilot 답의 가린 이름을 이 PC 에서 원래 이름으로 되돌린다


class _GateCache(dict):
    """과제 이름(·설명·키워드·힌트) → 프롬프트에 실을 글(G3 행 관문을 지난 사본) | None(싣지 않음) — 프로세스 안 캐시.
    비우면(설치 폴더가 바뀜) 되돌림 표(_UNMASK)도 함께 비운다."""

    def clear(self):
        super().clear()
        _UNMASK.clear()


_SENDABLE = _GateCache()


def sendable(s):
    """이 글(과제 이름·설명·키워드·힌트)을 프롬프트에 실을 때 쓰는 글 → G3 행 관문(privacy.gate_items: 제한 고객·민감정보·식별번호·
    카나리아 행은 빼고, 직함 붙은 사람 이름은 [사람]·privacy.customers 는 [고객사] 로 가린다)을 지난 사본 | None(싣지 않는다).
    관문이 가린 글을 원문 대신 싣는다 — 관문을 지났다는 판정만 받고 원문을 실으면 가린 이름이 그대로 Copilot 에 갔다. 가린 글은
    되돌림 표(_UNMASK)에 적는다(unmask_name 이 Copilot 답의 그 이름을 원래 이름으로 바꾼다 — 이 PC 안에서만)."""
    s = " ".join(str(s or "").split())
    if not s:
        return None
    if s not in _SENDABLE:
        try:
            kept = g3_rows([{"text": s}], ("text",))[0]
            v = " ".join(str((kept[0] or {}).get("text") or "").split()) if kept else ""
        except Exception:  # noqa: BLE001 - 관문을 세우지 못하면 싣지 않는다(fail-closed)
            v = ""
        _SENDABLE[s] = v or None
        if v and v != s:
            _UNMASK.setdefault(ukey2(v), s)
    return _SENDABLE[s]


def sendable_text(s):
    """이 글을 프롬프트에 실을 수 있는가(sendable 이 글을 돌려주나) — 싣는 글은 늘 sendable(s) 의 사본이다."""
    return sendable(s) is not None


def unmask_name(s):
    """Copilot 이 돌려준 이름 → 우리가 가려 보낸 이름(sendable)이면 원래 이름, 아니면 그대로."""
    if not _UNMASK or not isinstance(s, str):
        return s
    return _UNMASK.get(ukey2(s), s)


def unmask_models(models):
    """Copilot 이 돌려준 과제 목록(models) → 이름·흡수 이름(merged)·키워드(match)를 원래 이름으로 되돌린 사본. 되돌리지 못한 가림
    표식('[' 가 든 글)이 남은 키워드는 뺀다 — 가림 표식이 키워드가 되면 규칙 매칭이 가린 글끼리 묶는다."""
    out = []
    for m in models or ():
        if not isinstance(m, dict):
            continue
        m = dict(m)
        if isinstance(m.get("name"), str):
            m["name"] = unmask_name(m["name"].strip())
        for k in ("merged", "match"):
            if isinstance(m.get(k), list):
                vals = [unmask_name(str(x).strip()) for x in m[k] if str(x).strip()]
                m[k] = [x for x in vals if not (k == "match" and "[" in x)]
        out.append(m)
    return out


def _sample_fmt(r, n=80):
    """체계 표본 한 줄 — '- [출처] (나) 제목'. 날짜·시각·상대 이름은 싣지 않는다."""
    lab = who_label(r.get("who"))
    return f"- [{r.get('source') or ''}]{(' ' + lab) if lab else ''} {(r.get('text') or '')[:n]}"


def taxonomy_prompt(rows, hints, pinned=()):
    # G3 — 표본 후보(고르게 퍼진 200행)만 관문에 통과시킨 사본에서 고른다(광고·제한 고객·민감정보·식별번호 행 제외, 재정제)
    rows = g3_pick(rows, 100)
    lines = [
        "당신은 Agentic AI 전환 과제 발굴을 위한 업무 분류의 설계자입니다. 아래는 한 사람의 메일·일정 제목 표본입니다.",
        "이 사람의 업무를 두 축의 체계로 설계하세요.",
        "",
        "1. models = 상위 '과제' 목록 (JSON 키는 models) — 업무가 모이는 최상위 덩어리(과제·제품 개발 갈래·사내 시스템).",
        "   ★ 표본에서 실제로 관찰되는 것만 넣는다. 힌트 목록에 있어도 표본에 흔적이 없으면",
        "     제외하고, 힌트에 없어도 표본에서 상위 과제로 보이면 반드시 추가한다.",
        "   match 에는 그 과제를 식별할 소문자 키워드들, obs 에는 근거가 된 표본 한 조각.",
        "   같은 개체의 표기 변형(대소문자·축약·한/영)은 대표 이름 하나로 통일한다.",
        "   과제가 아닌 것(공통 사무·팀 운영·사내 행정)은 '공통' 하나로 묶는다.",
        "   ★ 계층 규율: models 는 **상위 개체**만. 'OO 설계'·'OO 보고서 작성' 같은 **중위 업무**(동사형 산출 활동)는",
        "     과제가 아니다 — 그 업무가 속한 상위 과제를 세우고, 업무 자체는 신호 판정의 세부업무 축으로 내린다.",
        "     상위가 불분명하면 '공통' 소속.",
        "   ★ 사람 이름·호칭(○○ 책임/님)·부서명, 인사·발령·공지·교육 안내·설문 같은 사내 행정은 과제가 아니다 —",
        "     models 에 넣지 말 것(행정은 '공통').",
        "   l1 = 그 과제의 업무 성격(상위) — 아래 중 택1:",
        *details.l1_def_lines("     "),
        "2. worktypes = 업무유형 4종 고정: 개발 / 사무 / 현장 / 협업",
        "",
        "출력은 JSON 하나만(설명·표·코드블록 없이). obs 는 40자 이내:",
        TAXONOMY_EXAMPLE,
        "",
    ]
    # 지정 과제·설명·키워드·힌트는 G3 행 관문을 지난 사본(sendable — 가린 이름은 가린 채)만 싣는다(원문을 싣지 않는다)
    pins = [(p, nm) for p, nm in ((p, sendable(p.get("name"))) for p in (pinned or ())) if nm]
    if pins:
        lines.append("· 사용자 지정 과제 — 이 표기 그대로 **반드시 models 에 포함**하고,")
        lines.append("  표본에서 이들에 속하는 흔적의 식별 키워드를 match 에 보강할 것:")
        for p, nm in pins:
            dsc = sendable(str(p.get("desc") or "")[:60]) if p.get("desc") else None
            d = f" — {dsc}" if dsc else ""
            k = list(dict.fromkeys(x for x in (sendable(str(x)) for x in (p.get("match") or [])) if x))
            lines.append(f"    · {nm}{d}" + (f" (키워드: {', '.join(k)})" if k else ""))
    hs = list(dict.fromkeys(x for x in (sendable(h) for h in (hints or ())) if x))[:25]
    if hs:
        lines.append("· 힌트(지난 분석에서 발견 등): " + ", ".join(hs) + " — 참고만 하고, 채택 여부는 표본 관찰로 판단할 것")
    lines += ["", "[표본]"]
    head_len = sum(len(x) + 1 for x in lines)
    return "\n".join(lines + _fit_rows(rows, 100, _sample_fmt, head_len))


def consolidate_prompt(models, rows):
    """초안 과제 목록에서 '같은 실체가 다른 이름으로 갈린 것'을 통합하도록 한 번 더 묻는다 — 표기 변형만 합친다.
    같은 표본이라도 실행마다 체계가 흔들리던 것(예: 'AX' 와 'Agentic AI' 가 분리)을 줄인다."""
    names = list(dict.fromkeys(x for x in (sendable(m.get("name")) for m in models) if x))   # 관문을 지난 사본만
    lines = [
        "아래는 한 사람의 업무를 분류하기 위해 초안으로 뽑은 '상위 과제' 목록입니다.",
        "같은 실체가 다른 이름으로 갈린 것을 하나로 합쳐 최종 목록을 만들어 주세요.",
        "",
        "· 같은 과제의 표기 변형(띄어쓰기·대소문자·한/영 표기·약어와 풀어 쓴 이름)만 합친다 (대표 이름 하나 선택).",
        "· 일의 갈래가 다르고 표본에서 따로 불리면 합치지 않는다.",
        "· 서로 다른 과제는 합치지 않는다.",
        "· 과제가 아닌 공통 사무·팀 운영은 '공통' 하나로.",
        "· merged 에는 그 이름으로 흡수된 초안 이름들을 적는다.",
        "",
        "출력은 JSON 하나만(설명·표·코드블록 없이):",
        CONSOLIDATE_EXAMPLE,
        "",
        "[초안 목록] " + ", ".join(names)[:1500],
        "",
        "[표본]"]
    head_len = sum(len(x) + 1 for x in lines)
    rows = g3_pick(rows, 40)                   # G3 — 표본은 관문을 통과한 사본에서
    return "\n".join(lines + _fit_rows(rows, 40, lambda r: f"- {(r.get('text') or '')[:70]}", head_len))


def merge_log_lines(models):
    """통합 왕복 결과(models 의 merged) → 로그 줄 ['통합: 대표 ← 흡수1, 흡수2', …] — 표기만 다른 같은 이름은 적지 않는다."""
    out = []
    for m in models or ():
        if not isinstance(m, dict) or not str(m.get("name") or "").strip():
            continue
        nm = str(m["name"]).strip()
        mg = [str(x).strip() for x in _as_list(m.get("merged"))
              if str(x).strip() and ukey2(str(x)) != ukey2(nm)]
        mg = list(dict.fromkeys(mg))
        if mg:
            out.append(f"통합: {nm} ← {', '.join(mg[:8])}" + (f" 외 {len(mg) - 8}개" if len(mg) > 8 else ""))
    return out


def apply_merges(models, draft=()):
    """consolidate 결과의 merged 를 match 키워드로 흡수 — 판정 단계에서 옛 이름이 나와도
    대표 이름으로 정규화되도록 한다.
    draft(통합 전 초안 — taxonomy 결과): 대표에 l1 이 없으면 같은 이름 또는 merged 이름의 초안 값을 옮긴다.
    consolidate 응답 형식에는 l1 이 없어, 통합을 거치면 taxonomy 가 판정한 상위가 사라졌다."""
    by = {}
    for d in draft or ():
        if isinstance(d, dict) and d.get("name"):
            by.setdefault(ukey2(d["name"]), d)
    out = []
    for m in models:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        ent = dict(m)
        ent["match"] = list(dict.fromkeys(
            [str(k).lower() for k in _as_list(m.get("match"))]
            + [str(k).lower() for k in _as_list(m.get("merged"))]))
        if not ent.get("l1"):
            for nm in [m["name"]] + [str(x) for x in _as_list(m.get("merged"))]:
                v = (by.get(ukey2(nm)) or {}).get("l1")
                if v:
                    ent["l1"] = v
                    break
        out.append(ent)
    return out


def fallback_models(rows, known, people=(), prev=()):
    """taxonomy 왕복 실패 시 — 등록 프로젝트(known) + 지난 정상 체계(prev — 이름 또는 models 항목) + 규칙 귀속에서
    자주 나온 토큰(최대 8개, 2회 이상)을 후보로. 규칙 토큰은 상투어·잡음·사람 이름·공지류를 거른다(진단 B — 폴백 체계가
    사람 이름·'근태공지' 를 과제로 세우고 entities 로 되먹이던 경로). 같은 과제(ukey2)는 하나로 묶고 매칭어를 합친다.
    모든 항목에 obs '규칙 폴백' — entities 에 남아도 AI 체계와 구분된다."""
    freq = Counter(r.get("project") for r in rows
                   if r.get("project") and r["project"] not in ("미지정", "공통") and _rule_name_ok(r["project"])
                   and not NOISE_MODEL.match(r["project"]) and details.task_name_ok(r["project"], people))
    auto = [p for p, n in freq.most_common(8) if n >= 2]
    out, idx = [], {}
    for p in list(known or []) + list(prev or []) + auto:
        src = p if isinstance(p, dict) else {}
        if isinstance(p, (tuple, list)) and p:
            src = {"name": p[0], "match": list(p[1] or []) if len(p) > 1 else []}
        nm = str((src.get("name") if src else p) or "").strip()
        if not nm or nm == "공통":
            continue
        keys = [nm.lower()] + [str(k).strip().lower() for k in _as_list(src.get("match")) if str(k).strip()]
        k = ukey2(nm)
        if k in idx:                      # 같은 과제의 다른 표기(규칙 토큰 'orionx' ↔ 지난 체계 'Orion-X') — 매칭어만 합친다
            cur = out[idx[k]]
            cur["match"] = list(dict.fromkeys(cur["match"] + keys))
            continue
        idx[k] = len(out)
        e = {"name": nm, "match": list(dict.fromkeys(keys)), "obs": "규칙 폴백"}
        if src.get("l1"):
            e["l1"] = src["l1"]
        out.append(e)
    return out + [{"name": "공통", "match": [], "obs": "규칙 폴백"}]


# 파일명 접두어·범용 토큰은 과제가 아니다 — 프롬프트 지시만으로는 새는 것이
# 실측 확인돼 코드에서도 걸러낸다 (entities 힌트 순환 오염 방지)
NOISE_MODEL = re.compile(
    r"^(img|image|scan|doc|docs|file|files|tmp|temp|misc|etc|기타|잡음|미지정|none|n/a)\d*$", re.I)


def sanitize_models(models, people=()):
    """taxonomy·discovered 결과에서 잡음 이름 제거 + 대소문자 중복 통합, '공통' 보장.
    pinned(사용자 지정)는 잡음 필터를 우회한다 — 사용자가 명시한 이름은 코드가 지우지 않는다.
    LM28(진단 B): 상투어·버전(규칙 과제명 잡음)·사람 이름(people = details.person_keys 키)·공지류(근태공지·인사발령 …)도
    과제가 아니다 — 이 관문이 taxonomy·지난 체계·폴백·발견 모든 경로에 걸린다. l1(상위)은 고정 범주로 스냅하고, 모델별 product 키(옛 판)는 버린다."""
    out, seen = [], set()
    for m in models:
        name = str(m.get("name") or "").strip() if isinstance(m, dict) else str(m).strip()
        if not name:
            continue
        if not (isinstance(m, dict) and m.get("pinned")) and (
                NOISE_MODEL.match(name) or not _model_name_ok(name) or not details.task_name_ok(name, people)):
            continue
        # 신원 축은 ukey2 — 예전에는 .lower() 뿐이라 '설계 검토'/'설계검토'/'설계-검토' 가 서로 다른
        # 과제로 남았고, 그 변형이 discovered 로 적립돼 다음 실행의 후보로 되먹여져 분할이 영구화됐다.
        k = ukey2(name)
        if k in seen:
            continue
        seen.add(k)
        if isinstance(m, dict):
            m = dict(m)
            m["name"] = name                  # 공백 등 정규화된 이름으로 기록
            m.pop("product", None)                # 모델별 제품 이름은 쓰지 않는다(파일 머리의 product 는 산출물 표식이다)
            if m.get("l1") is not None:       # 상위 — 고정 범주로 스냅, 못 짚으면 지운다(억지로 찍지 않는다)
                l1 = details.snap1(m.get("l1"))
                if l1:
                    m["l1"] = l1
                else:
                    m.pop("l1", None)
            out.append(m)
        else:
            out.append({"name": name, "match": [k]})
    if not any(m["name"] == "공통" for m in out):
        out.append({"name": "공통", "match": []})
    return out


def _load_prev_entities(rep, people=()):
    r"""지난 분석의 과제 체계 — report\entities_*.json 을 최신부터 훑어 규칙 폴백 산출물("fallback": true, 옛 판은
    AI 흔적 없는 목록 — details.entities_is_fallback)은 건너뛰고 첫 정상 체계를 쓴다. 옛 지정 표식(pinned)은 떼고
    sanitize_models(사람 이름·공지류·잡음 관문)를 거친다 — 지난 실행이 남긴 사람 이름이 힌트로 되살아나지 않게.
    returns (models, 경로) — 없으면 ([], "")."""
    ent, path = details.newest_entities(rep)
    if not path:
        return [], ""
    models = [{k: v for k, v in m.items() if k != "pinned"} for m in _as_list(ent.get("models"))
              if isinstance(m, dict) and str(m.get("name") or "").strip()]
    return sanitize_models(models, people), path


def to_model(name, models):
    """판정이 돌려준 과제명을 체계의 대표 표기로 정규화 — 대소문자 변형 분리 계상 방지"""
    n = unmask_name(str(name or "").strip())   # 우리가 가려 보낸 이름([사람]·[고객사])이면 원래 이름으로(sendable)
    # 표기 변형(띄어쓰기·하이픈·가운뎃점·대소문자)을 체계의 대표 이름으로 접는다. consolidate 왕복이
    # 통합한 merged 이름도 함께 실어, 그 왕복의 결과가 판정 성공 행에도 적용되게 한다 — 예전에는
    # merged 가 match 로만 들어가 **판정 실패 행(rule_model)에만** 반영되는 역전이 있었다(감사 실측).
    canon = {}
    for m in models:
        nm = m["name"]
        canon.setdefault(ukey2(nm), nm)
        for alt in (m.get("merged") or []):
            canon.setdefault(ukey2(alt), nm)
    return canon.get(ukey2(n), n)


def final_model(raw, models, people=(), pinned_keys=()):
    """AI 가 돌려준 과제명 → 최종 과제명(LM28 진단 B — 과제명 관문). to_model 로 체계의 대표 표기로 접은 뒤
    · 지정 과제(pinned_keys — ukey2 키, 또는 models 의 pinned)는 그대로
    · 체계에 있는 이름은 그대로 — 단 공지류·사람 이름이면 '공통'(관문 없이 들어온 옛 체계 대비)
    · 체계에 없는 새 이름(판정 중 발견)은 잡음·상투어·사람 이름·공지류가 아닐 때만 그대로, 아니면 '공통'.
    예전에는 to_model 이 모르는 이름을 그대로 돌려줘 사람 이름·'근태공지' 가 과제가 되고 entities 발견으로 되먹였다."""
    md = to_model(raw, models) or "공통"
    k = ukey2(md)
    if k in {ukey2(p) for p in (pinned_keys or ())} | {ukey2(m["name"]) for m in models if m.get("pinned")}:
        return md
    if k in {ukey2(m["name"]) for m in models}:
        return "공통" if (details.is_notice_name(md) or details.is_person_name(md, people)) else md
    if NOISE_MODEL.match(md) or not _model_name_ok(md) or not details.task_name_ok(md, people):
        return "공통"
    return md


@functools.lru_cache(maxsize=8192)
def _rule_name_ok(s):
    """규칙 과제명·매칭어로 쓸 수 있는가 — 상투어·버전·6~8자리 날짜·Untitled·copy 는 아니다(F-19·W2-13, extract 와 같은 규칙).
    LM30(2026-10-27): 대화 낱말뿐인 이름('책임님'·'보내드렸습니다'·'가능하실까요')도 아니다(extract.talk_name)."""
    try:
        from extract import rule_name_ok, talk_name
        return rule_name_ok(s) and not talk_name(s)
    except ImportError:
        return bool(str(s or "").strip())


_CODE_NAME = re.compile(r"^[A-Z]+\d+[A-Z]+$")      # 'V2X' 같은 대문자 제품·과제 코드 — 버전 꼴('v2a')과 구분


def _model_name_ok(s):
    """AI·지난 체계·발견 과제명의 상투어 관문(LM28 진단 B) — 규칙 과제명과 같은 규칙(_rule_name_ok)이되,
    대문자 코드('V2X')는 버전 꼴('v2x')로 보지 않는다(규칙 토큰은 소문자라 extract 판정 그대로)."""
    return _rule_name_ok(s) or bool(_CODE_NAME.match(str(s or "").strip()))


def rule_model(r, models):
    """미판정(청크 실패) 행을 taxonomy의 match 키워드로 과제 축에 매핑 —
    규칙 토큰('agentic' 조각 등)이 과제명 네임스페이스에 그대로 섞이는 것 방지.
    LM28: 잡음 매칭어(상투어·버전·날짜·Untitled·copy)는 쓰지 않는다 — 'untitled' 매칭어가 편집기 탭 신호를 끌어오던 것."""
    low = f"{r.get('project') or ''} {r.get('text') or ''}".lower()
    # 토큰 경계 매칭 — raw 부분문자열은 오탐이 실측됐다('AX'⊂'tax/max', 'ai'⊂'email').
    # projmap 이 같은 이유로 이미 버린 방식이라 그 판정기를 그대로 재사용한다.
    try:
        from projmap import _kw_hit, _text_tokens
        toks = _text_tokens(low)
    except ImportError:
        _kw_hit, toks = None, None
    for m in models:
        if m["name"] == "공통":
            continue
        keys = [k for k in [m["name"].lower()] + [str(k).lower() for k in _as_list(m.get("match"))]
                if _rule_name_ok(k)]
        if _kw_hit is not None:
            if any(k and _kw_hit(k, toks) for k in keys):
                return m["name"]
        elif any(k and len(k) >= 2 and k in low for k in keys):
            return m["name"]
    return "공통"


# ── [1..N] 신호 판정 ───────────────────────────────────────────────────────
JUDGE_EXAMPLE_ROWS = [[0, "y", "프로젝트A", "개발", "설계 검토"], [1, "n"]]
JUDGE_EXAMPLE = json.dumps({"j": JUDGE_EXAMPLE_ROWS}, ensure_ascii=False, separators=(",", ":"))
# 지난 판 프롬프트 예시 에코 방어 — Copilot 채팅에 남아 있을 수 있는 지난 두 판의 예시('{"j":[[0,"y","프로젝트A","개발",…],
# [1,"n","","",""]]}'·'…,[1,"n"]]}')를 원문 대신 공백 뺀 원문의 sha1 지문(_fp)으로 기억한다. ROW0 은 그 첫 행의 지문(정규식 경로).
JUDGE_EXAMPLE_OLD = ("sha1:3392ab652a19059a495aab495fb936501bcdad16",
                     "sha1:e90ead0fcfe1052e5cd8196facb631eb0a196f4d")
JUDGE_EXAMPLE_OLD_ROW0 = frozenset({"sha1:071a15f9c65564813529e882492819e5c8380b3f"})
JUDGE_EXAMPLES = (JUDGE_EXAMPLE, *JUDGE_EXAMPLE_OLD)


# 회의 안건(일정 본문을 core\meetnote 가 정제한 것 — config.calendar.bodyToAI 가 켜졌을 때만). 회의 줄 끝에만 붙고, 머리말 안내 한
# 줄은 안건이 든 묶음에만 넣는다.
NOTE_SEP = " — 안건: "
NOTE_HINT = "· 회의 줄 끝의 '— 안건:' 은 그 일정 본문을 정제·요약한 것입니다 — 과제·세부업무를 고르는 참고로만 쓰세요."
NOTE_KEY_SEP = "|안건:"     # 판정 캐시 내용 키에 안건을 넣는 구분자 — 안건이 생기거나 바뀐 회의만 한 번 다시 판정한다


def row_line(r, idx):
    """판정 줄 — '#번호 | YYYY-MM-DD | 출처 | 나·- | 제목[:95]'(+ 회의 안건). 시각·상대 이름·도메인은 싣지 않는다(D10·D8)."""
    line = (f"#{idx} | {str(r.get('time') or '')[:10]} | {r.get('source') or ''} | "
            f"{who_label(r.get('who')) or '-'} | {(r.get('text') or '')[:95]}")
    nt = " ".join(str(r.get("note") or "").split())
    return line + NOTE_SEP + nt if nt and _fam(r) == "회의" else line


def judge_prompt(chunk, start, models, first=True, seen_details=(), idxs=None):
    """청크 프롬프트 — 항상 머리말(기준·과제 목록·출력 형식)을 포함한다(first 는 호환용, 무시).
    드라이버의 재시도 사다리가 새 채팅을 열어도 기준 없는 빈 채팅에 떨어지지 않게 혼자서 완결이다.
    idxs: 행의 절대 번호 목록(적응 분할 재시도처럼 연속이 아닐 때) — 없으면 start 부터 연속.
    과제 목록은 G3 행 관문을 지난 사본만 싣는다(sendable — 제한 고객 이름이 든 지정 과제는 싣지 않고, 가린 이름은 가린 채)."""
    names = []
    for m in models:
        nm = sendable(str(m.get("name") or ""))
        if not nm:
            continue
        desc = str(m.get("desc") or "")[:30]
        dsc = sendable(desc) if desc else None
        item = nm + (f"({dsc})" if dsc else "")
        if item not in names:
            names.append(item)
    head = [
        "당신은 Agentic AI 전환 과제 발굴을 위한 업무 분류의 판정자입니다. 각 메일·일정 줄을 읽고 판정하세요.",
        "",
        "판정 형식: [번호, \"y\"|\"n\", \"과제\", \"유형\", \"세부업무\"] — 비업무(n)는 [번호,\"n\"] 두 칸만.",
        "· y/n : 업무 여부. 공지·알림(행정·교육·윤리·인사 시스템의 자동 알림·뉴스레터·시스템 발송),",
        "  광고·프로모션, 개인 용무, 의미 없는 잡음은 n. 과감하게 걸러낼 것.",
        "· 과제 : 아래 목록에서 고르되 목록의 표기를 그대로 쓴다(변형 금지). 목록에 없어도",
        "  제목에 상위 과제 이름이 분명히 보이면 그 이름을 새로 쓴다(새 과제 발견) —",
        "  단, 이미 목록에 같은 개체의 다른 표기가 있으면 그 표기를 쓴다. 어느 쪽도 아니면 \"공통\".",
        "   → " + ", ".join(names),
        "  ★ 사람 이름·호칭·부서는 과제가 아니다 — 그 줄의 내용이 가리키는 과제를 고른다. 모르면 \"공통\".",
        "  ★ 이 묶음의 줄만 보고 판정하세요 — 앞 묶음에서는 과제·세부업무 표기만 이어 쓰세요.",
        "  ★ 인사·발령·공지·교육 안내는 과제가 아니다 — 단순 공지는 n, 내가 처리한 행정이면 \"공통\".",
        "· 유형 : 개발 / 사무 / 현장 / 협업 중 하나",
        "· 세부업무 : 짧은 명사구 — 같은 일은 같은 이름으로 (예: '설계 검토', '부품 발주',",
        "   '시험 결과 정리', '주간보고'). 조사 붙은 조각('보고의' 등) 금지.",
    ]
    if any(str(r.get("note") or "").strip() and _fam(r) == "회의" for r in chunk):
        head.append(NOTE_HINT)
    if seen_details:
        head += ["★ 앞선 묶음에서 이미 쓴 세부업무 이름 — 같은 일이면 새 이름을 만들지 말고 이 표기를",
                 "  그대로 재사용할 것(이름이 갈리면 같은 일이 여러 줄로 쪼개집니다):",
                 "  " + " / ".join(list(seen_details)[:SEEN_MAX_NAMES])]
    head += [
        "",
        "출력은 JSON 하나만(설명·표·코드블록 없이). 모든 번호를 빠짐없이 번호 순서대로:",
        JUDGE_EXAMPLE,
        "",
    ]
    if idxs is None:
        idxs = range(start, start + len(chunk))
    body = [row_line(r, i) for i, r in zip(idxs, chunk, strict=True)]
    return "\n".join(head + body)


def parse_judgments_ex(reply, idxs):
    """답 → {번호: 판정} + info{json, repaired, scan}. 완전한 JSON → 잘린 JSON 복구(repair_json) →
    행 정규식(scan_rows) 순으로 시도한다. repaired/scan 이 참이면 '답이 온전하지 않았다'는 뜻이라
    호출자가 빠진 행을 다시 묻는다. 프롬프트 예시 행은 어느 경로에서도 받지 않는다."""
    valid = {int(i) for i in idxs}
    info = {"json": False, "repaired": False, "scan": False}
    o = rfind_json(reply, "j", skip=JUDGE_EXAMPLES)
    if o:
        info["json"] = True
    else:
        o = repair_json(reply, "j", skip=JUDGE_EXAMPLES)
        if o:
            info["json"] = info["repaired"] = True
    rows = [r for r in _as_list(o.get("j")) if isinstance(r, list)] if o else []
    if not rows:
        sc, sp = scan_rows(reply, spans=True)
        rows = strip_example_rows(reply, sc, sp)
        if rows:
            info["scan"] = info["repaired"] = True
    out = {}
    for row in rows:
        if not (isinstance(row, list) and len(row) >= 2):
            continue
        try:
            idx = int(row[0])
        except (TypeError, ValueError):
            continue
        if idx in valid:
            g = [str(x).strip() for x in (list(row[1:]) + ["", "", ""])[:4]]
            out[idx] = {"work": g[0].lower().startswith("y"), "model": g[1],
                        "worktype": g[2] if g[2] in WORKTYPES else ("사무" if g[0].lower().startswith("y") else ""),
                        "detail": g[3][:40]}
    return out, info


def parse_judgments(reply, start, n):
    """호환 — 연속 번호 start..start+n-1 의 판정만 돌려준다."""
    return parse_judgments_ex(reply, range(start, start + n))[0]


# ── 이어서 판정 캐시 — report\judge_cache.json ─────────────────────────────────────────────
# 캐시는 기간과 무관하게 내용 키(signal_sig2 의 sha1)로 판정만 남긴다 — 신호 원문은 남기지 않는다.
def signal_sig2(r):
    """'이어서 판정' 키 — 날짜|출처 계열(괄호 앞)|원문 머리 120자. 라벨(메일(수신)/메일(수신전용))이 바뀌어도 같다."""
    return (f"{(r.get('time') or '')[:10]}|{str(r.get('source') or '').split('(')[0]}|"
            f"{' '.join((r.get('text') or '').split())[:120]}")


def _ckey(sig2):
    """캐시 키 — sig2 의 sha1 앞 20자(캐시 파일·판정 기록에 신호 원문이 남지 않는다)."""
    return hashlib.sha1(str(sig2 or "").encode("utf-8")).hexdigest()[:20]

def _jt(j):
    """판정 → 비교용 튜플 (업무, 과제, 유형, 세부업무) — 비업무는 과제·유형·세부업무를 비운다."""
    w = bool((j or {}).get("work"))
    if not w:
        return (False, "", "", "")
    return (True, str(j.get("model") or ""), str(j.get("worktype") or ""), str(j.get("detail") or ""))


def _jd(t):
    """_jt 튜플 → 판정 dict."""
    return {"work": bool(t[0]), "model": t[1], "worktype": t[2], "detail": t[3]}


def _cache_entry(j, today):
    """판정 → 캐시 항목 {"w":0|1, "m","t","d", "at": 마지막으로 쓴 날}."""
    w, m, t, d = _jt(j)
    e = {"w": 1 if w else 0, "at": today}
    if w:
        e.update(m=m[:80], t=t, d=d[:40])
    return e


def _from_cache(e):
    """캐시 항목({"w",…}) 또는 옛 판정 기록 항목({"work","model",…}) → 판정 dict(못 읽으면 None)."""
    if not isinstance(e, dict):
        return None
    if "w" in e:
        return _jd((bool(e.get("w")), str(e.get("m") or ""), str(e.get("t") or ""), str(e.get("d") or "")))
    if "work" in e:
        return _jd(_jt(e))
    return None


def _write_json_atomic(path, obj):
    """tmp → os.replace(백신·색인기가 잠깐 잡으면 쉬고 다시). 판정 캐시는 크고 묶음마다 쓰므로 들여쓰기 없이 쓴다
    (details.save_json_atomic 은 indent=1). returns 저장했으면 True."""
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        for i in range(6):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                time.sleep(0.2 * (i + 1))
    except (OSError, TypeError, ValueError):
        pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


def cache_keep_days(cfg=None):
    """판정 캐시 항목의 보관 일수 = retention.intermediateDays(설정은 낮추기만 — afcfg.get 이 상한을 건다)."""
    import afcfg
    try:
        c = cfg if isinstance(cfg, dict) else afcfg.load(ROOT)
        v = int(afcfg.get(c, "retention.intermediateDays"))
    except (TypeError, ValueError, OSError):
        v = int(afcfg.RETENTION_MAX["intermediateDays"])
    return max(1, min(v, int(afcfg.RETENTION_MAX["intermediateDays"])))


def _cache_cut(keep_days, today=None):
    """이 날짜(YYYY-MM-DD)보다 앞서 마지막으로 쓴 캐시 항목은 버린다 — 오늘 − keep_days."""
    t = date.fromisoformat(str(today)[:10]) if today else date.today()
    return (t - timedelta(days=max(1, int(keep_days)))).isoformat()


def _since_day(v):
    r"""캐시 시작 표시 → 'YYYY-MM-DD' | "". report\ 아래는 날짜만(D10) — 옛 파일의 epoch 초는 그날 날짜로 접는다(로직에는 쓰지 않는다)."""
    if isinstance(v, str):
        s = v.strip()[:10]
        return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        try:
            return date.fromtimestamp(float(v)).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return ""


def load_judge_cache(rep, keep_days=None, today=None):
    r"""report\judge_cache.json → {"v", "since": 캐시를 새로 시작한 날('YYYY-MM-DD' | ""), "items": {키: {"w","m","t","d","at"}},
    "expired": 버린 수}. AgentFinder32 표식이 없는 파일(옛 판)·깨진 파일은 빈 캐시로 시작한다. 읽을 때 retention.intermediateDays
    (keep_days — 없으면 설정)보다 오래 쓰지 않은 항목은 버린다(파일은 다음 저장 때 줄어든다). 옛 파일의 epoch 'since' 는 날짜로 접는다."""
    empty = {"v": JUDGE_CACHE_V, "since": "", "items": {}, "expired": 0}
    try:
        with open(os.path.join(rep, JUDGE_CACHE), encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError, TypeError):
        return empty
    if not (isinstance(o, dict) and o.get("product") == PRODUCT and isinstance(o.get("items"), dict)):
        return empty
    cut = _cache_cut(cache_keep_days() if keep_days is None else keep_days, today)
    items = {k: v for k, v in o["items"].items() if isinstance(v, dict) and str(v.get("at") or "") >= cut}
    return {"v": JUDGE_CACHE_V, "since": _since_day(o.get("since")), "items": items,
            "expired": len(o["items"]) - len(items)}


def save_judge_cache(rep, cache, d0=None, prune=True, keep_days=None, today=None):
    """판정 캐시 저장(원자 교체 · 표식 product). prune: retention.intermediateDays 보다 오래 쓰지 않은 항목을 빼고, CACHE_MAX 를
    넘으면 오래 쓰지 않은 것부터 뺀다(묶음마다 하는 중간 저장은 prune=False). d0 은 옛 호출 꼴과 맞추는 자리. returns 저장했으면 True."""
    items = cache.setdefault("items", {})

    def _at(v):
        return str(v.get("at") or "") if isinstance(v, dict) else ""
    if prune:
        cut = _cache_cut(cache_keep_days() if keep_days is None else keep_days, today)
        for k in [k for k, v in items.items() if _at(v) < cut]:
            del items[k]
        if len(items) > CACHE_MAX:
            for k, _v in sorted(items.items(), key=lambda kv: _at(kv[1]))[:len(items) - CACHE_MAX]:
                del items[k]
    return _write_json_atomic(os.path.join(rep, JUDGE_CACHE),
                              {"product": PRODUCT, "v": JUDGE_CACHE_V, "since": _since_day(cache.get("since")),
                               "items": items})


def _cached_name_ok(model, people=(), pinned_keys=()):
    """다시 쓰는 판정의 과제명 관문(진단 B) — 사람 이름·공지류 과제는 버리고 다시 판정한다(지정 과제·'공통'·빈 값은 통과)."""
    m = str(model or "").strip()
    return (not m) or m == "공통" or details.task_name_ok(m, people, pinned_keys)


def pack_chunks(rows, chunk_n, head_len, budget=PROMPT_BUDGET):
    """행을 [(start, n)] 로 자른다 — 행 수(chunk_n)와 글자 예산 둘 다로. 머리말(head_len)+행 합이 budget 을
    넘기 전에 끊는다(첫 행은 항상 넣는다). 긴 제목·긴 과제 목록·긴 '앞서 쓴 이름' 목록이면 40행이
    9,000자를 넘어 드라이버가 나눠 보내고, 나눔은 왕복 2배에 마지막 조각에만 답이 온다."""
    out, i, n_rows = [], 0, len(rows)
    while i < n_rows:
        size, n = 0, 0
        while i + n < n_rows and n < chunk_n:
            ln = len(row_line(rows[i + n], i + n)) + 1
            if n and head_len + size + ln > budget:
                break
            size += ln
            n += 1
        out.append((i, n))
        i += n
    return out


# ── 같은 내용 묶음 ──────────────────────────────────────────────────────────────────────
# 스레드의 메일마다 한 줄씩 보내면 왕복이 수백 회가 된다. 같은 내용(같은 계열·RE/FW 머리를 뗀 같은 앞 95자 — Copilot 이 보는
# 줄이 같다)은 대표 한 줄만 보내고 그 판정을 묶음 전체에 쓴다.
_GK_PREFIX = re.compile(r"^\s*((re|fw|fwd|답장|전달|회신|답변)\s*[:：]\s*)+", re.I)


def _fam(r):
    """출처 계열 — '메일(수신)' → '메일'."""
    return str((r or {}).get("source") or "").split("(")[0]


def _substantive(text):
    """업무를 가리킬 낱말이 하나라도 있는가 — extract._tokens 중 상투어·버전·날짜가 아닌 것(rule_name_ok)."""
    from extract import _tokens, rule_name_ok
    return any(rule_name_ok(t) for t in _tokens(text))


def group_key(r):
    """같은 내용 묶음 키 → (계열, 정규화한 원문 앞 95자) 또는 None(혼자 보낸다).
    RE/FW/회신 머리를 떼고 소문자·앞뒤 구두점 정리. 숫자는 남긴다('설계 검토 1' 과 '설계 검토 2' 는 다른 일).
    6자 미만, 업무 낱말이 하나도 없는 원문은 묶지 않는다."""
    t = _GK_PREFIX.sub("", " ".join(str(r.get("text") or "").split()))
    t = t.lower().strip(" .-_~!?")
    if len(t) < 6 or not _substantive(t):
        return None
    return _fam(r), t[:GROUP_KEY_CHARS]


def _wt(r):
    try:
        return float(r.get("weight") or 0)
    except (TypeError, ValueError):
        return 0.0


def group_reps(rows, idxs, keys, cap=GROUP_MAX):
    """같은 내용 묶음 → (대표 행 번호 목록(번호 순), {대표: [구성원 …]}). 키가 None 인 행은 혼자 대표다.
    한 묶음이 cap 행을 넘으면 시간 순으로 나눠 조각마다 대표를 세운다. 대표 = (가중치, 원문 길이, 시각)이 가장 큰 행."""
    by, reps, members = defaultdict(list), [], {}
    for i in idxs:
        k = keys[i]
        if k is None:
            reps.append(i)
        else:
            by[k].append(i)
    cap = max(1, int(cap))
    for ids in by.values():
        ids.sort(key=lambda i: (str(rows[i].get("time") or ""), i))
        for s in range(0, len(ids), cap):
            part = ids[s:s + cap]
            rep = max(part, key=lambda i: (_wt(rows[i]), len(str(rows[i].get("text") or "")),
                                           str(rows[i].get("time") or ""), -i))
            reps.append(rep)
            others = [i for i in part if i != rep]
            if others:
                members[rep] = others
    reps.sort()
    return reps, members


def recent_details(judged, prev_idxs=(), people=()):
    """청크에 동봉할 '앞서 쓴 세부업무 이름' — 직전 청크가 쓴 이름(빈도순)을 먼저, 그 다음 전체 빈도순.
    예전에는 전체를 가나다순으로 잘라 30개를 보냈다 — 이름이 200개면 'ㄱ~ㄴ' 만 가고 정작 직전
    청크의 이름은 빠져 청크마다 새 이름이 생겼다. 30개·600자 상한. 행정 표기·사람 이름(people — details.person_keys)이
    든 이름은 이어 쓰게 하지 않는다(판정 반영 때 활동명으로 바뀌는 이름을 다음 묶음에 되먹이지 않는다)."""
    prev = Counter(judged[i]["detail"] for i in prev_idxs
                   if i in judged and judged[i].get("work") and judged[i].get("detail"))
    allc = Counter(j["detail"] for j in judged.values() if j.get("work") and j.get("detail"))
    out, size = [], 0
    for name, _ in list(prev.most_common()) + list(allc.most_common()):
        if name in out or not details.detail_name_ok(name) or details.is_person_name(name, people):
            continue
        if len(out) >= SEEN_MAX_NAMES or size + len(name) + 3 > SEEN_MAX_CHARS:
            break
        out.append(name)
        size += len(name) + 3
    return out


def meeting_notes(rows, cfg, d0, d1, data_dir=None):
    r"""회의 신호 행 번호 → 안건(config.calendar.bodyToAI 가 켜졌을 때만 — 기본은 끔).
    core\meetnote.load_notes 가 data\outlook\calendar.csv 의 일정 본문을 정제·필터하고, 회의 행(출처 '회의')과는
    meetnote.note_key(날짜, 제목) 으로만 맞댄다 — 회의가 아닌 행에는 붙지 않는다. 붙이기 전에 안건만 G3 관문(g3_rows)에 먼저
    넣어 통과한 것만 쓴다(안건 때문에 회의 행이 통째로 규칙 판정이 되지 않게). 본문 없음·읽기 실패면 {}. 출력은 건수만."""
    import meetnote
    if not meetnote.enabled(cfg):
        return {}
    idx = [i for i, r in enumerate(rows) if _fam(r) == "회의"]
    if not idx:
        return {}
    try:
        book = meetnote.load_notes(data_dir or os.path.join(ROOT, "data"), d0, d1, cfg)
    except Exception as e:  # noqa: BLE001 - 안건은 참고일 뿐 — 읽기 실패가 판정을 멈추지 않게(제목만으로 판정)
        print(f"[judge] 회의 안건(일정 본문)을 읽지 못해 제목만으로 판정합니다({type(e).__name__})")
        return {}
    if not book:
        return {}
    cand = {}
    for i in idx:
        nt = book.get(meetnote.note_key(str(rows[i].get("time") or "")[:10], rows[i].get("text")))
        if nt:
            cand[i] = nt
    if not cand:
        print(f"[judge] 회의 안건 {len(book)}건이 있지만 같은 날짜·제목의 회의 신호가 없어 붙이지 않습니다")
        return {}
    kept, _why = g3_rows([{"text": nt, "_gi": i} for i, nt in cand.items()], ("text",))
    out = {it["_gi"]: it["text"] for it in kept if str(it.get("text") or "").strip()}
    print(f"[judge] 회의 안건(일정 본문 정제) {len(out)}건을 회의 판정의 참고로 붙입니다"
          + (f" · 개인정보 관문에서 뺀 안건 {len(cand) - len(out)}건" if len(cand) > len(out) else ""))
    return out


def judge_rows(idxs, rows, models, seen, tag, label, depth, st):
    """행 묶음 하나를 판정한다(적응 분할). returns {번호: 판정}.
    · 완전한 JSON → 그대로(모델이 빠뜨린 행은 omitted_rows — 재왕복 없이 규칙).
    · 잘린 답(cut·복구·정규식) → 복구된 행은 쓰고, 빠진 행이 MIN_RETRY_ROWS 이상이면 그 행만 다시 묻는다.
    · 통째 실패(왕복 실패·JSON 없음) → 2*MIN_SPLIT 행 이상이면 반으로 나눠 각각 재시도(깊이 MAX_SPLIT_DEPTH).
    · st: roundtrips·repaired·retries·failed_rows·omitted_rows·notes·last_err·soft(재시도 끔) 누적.
    · G3(LM28): 행은 먼저 관문(g3_rows)을 거친다 — 걸린 행은 보내지 않고 규칙 판정으로 남는다(gated_rows). 보낼 행이 없거나
      최종 프롬프트 검사(copilot_send → phase 'blocked')에 걸리면 왕복하지 않고 빈 결과 — 깊이 0 이면 st['_skipped'] 를 세워
      호출자가 연속 실패로 세지 않게 한다(재시도·반분도 하지 않는다). 관문에 걸린 행 번호는 st['gated_idx'](채우기 제외).
    · LM28 진단 A: 일시 오류·사용량 제한(_is_transient)은 나누지 않는다 — copilot_send 가 이미 쉬고 다시 보냈다(st['transient']).
      JSON 없는 짧은 답(SHORT_REPLY_CHARS 미만 — 거절·제한 문구일 수 있다)은 한 단계만 나눈다. 강한 제한(hard)·로그인 만료 등
      사람이 손댈 실패는 st['fatal'](사유)·st['fatal_kind'](throttle·login·fatal). 빠뜨린 행 번호는 st['omitted_idx']."""
    idxs = list(idxs)
    if st.get("fatal"):
        st["failed_rows"] += len(idxs)            # 같은 묶음의 앞 조각이 사람이 손댈 실패였다 — 나머지는 보내지 않는다
        return {}
    # 회의 안건(st['meet_notes'] = {회의 행 번호: 안건}, main 의 meeting_notes 가 관문을 미리 통과시킨 것)은 'note'
    # 필드로 행과 같은 관문을 다시 지난다. 회의가 아닌 행·안건 없는 행에는 note 가 없다(signals 에 같은 이름 열이 생겨도 싣지 않음)
    notes = st.get("meet_notes") or {}
    items = []
    for i in idxs:
        it = dict(rows[i], _gi=i)
        it.pop("note", None)
        if i in notes and _fam(rows[i]) == "회의":
            it["note"] = notes[i]
        items.append(it)
    kept, why = g3_rows(items, ("text", "note") if notes else ("text",))
    n_gated = len(idxs) - len(kept)
    if n_gated:
        st["gated_rows"] = st.get("gated_rows", 0) + n_gated
        _sent = {it["_gi"] for it in kept}
        st.setdefault("gated_idx", set()).update(i for i in idxs if i not in _sent)
        st["notes"].append(f"{label}: 개인정보 관문 {n_gated}행 제외(" + ", ".join(sorted(why)) + ")")
    if not kept:
        if depth == 0:
            st["_skipped"] = True
        return {}
    idxs = [it["_gi"] for it in kept]
    chunk = kept                                 # 재정제한 사본 — 원본 행(signals 되쓰기)은 그대로
    # 묶음은 같은 채팅에서 이어 보낸다(fresh=None — 첫 왕복·실패 뒤·chatTurns 마다만 새 채팅). 프롬프트는 혼자서 완결이라
    # 새 채팅에 떨어져도 답이 나오고, 이어지면 앞 묶음의 표기를 Copilot 이 기억한다
    res = copilot_send(judge_prompt(chunk, idxs[0], models, seen_details=seen, idxs=idxs),
                       tag, label)
    if res.get("phase") == "blocked":
        # 최종 프롬프트 검사에 걸렸다 — 보내지 않았고 재시도도 하지 않는다. 이 행들은 규칙 판정으로 남는다.
        st["gated_rows"] = st.get("gated_rows", 0) + len(idxs)
        st.setdefault("gated_idx", set()).update(idxs)
        st["notes"].append(f"{label}: 개인정보 관문 — 묶음을 보내지 않음(규칙 판정)")
        if depth == 0:
            st["_skipped"] = True
        return {}
    try:
        _cd = int(res.get("cooldowns") or 0)
    except (TypeError, ValueError):
        _cd = 0
    st["roundtrips"] += 1 + _cd                   # 쉬고 다시 보낸 왕복도 센다
    got, info = {}, {}
    if res.get("ok"):
        got, info = parse_judgments_ex(res.get("reply", ""), idxs)
        if info.get("repaired"):
            st["repaired"] += 1
            st["notes"].append(f"{label}: 잘린 응답 복구 {len(got)}행" + (" (정규식)" if info.get("scan") else ""))
        elif res.get("cut"):
            st["notes"].append(f"{label}: 생성 중단 응답 — {len(got)}행 회수")
        elif not got:
            st["notes"].append(f"{label}: 응답에서 JSON 없음")
            note_bad_reply()
    else:
        st["last_err"] = " — ".join(x for x in (str(res.get("error") or ""),
                                                str(res.get("hint") or "")) if x)[:200]
        st["notes"].append(f"{label}: 실패({res.get('error', '')})")
        # 사람이 손대야 풀리는 실패(로그인 필요·Edge 없음·입력창 없음)는 **나눠 다시 물어도 똑같다**.
        # 예전에는 이것을 적응 분할로 되풀이해 청크 하나에 왕복 15회를 썼다(실행당 49회 · 28분).
        # agentic·flow 는 이미 explain_failure 로 접는데 judge 만 안 보고 있었다.
        _why, _how, _fatal = explain_failure(res)
        if _fatal:
            st["fatal"] = f"{_why} — {_how}"
            st["fatal_kind"] = _abort_kind_of(res)
            st["failed_rows"] += len(idxs)
            return got
        if _is_transient(res):
            # 일시 오류·사용량 제한 — copilot_send 가 이미 쉬었다가 새로 고쳐 다시 보냈다(또는 마감이라 쉴 수 없었다).
            # 반으로 나눠 즉시 다시 보내면 막힌 Copilot 에 요청만 퍼붓는다(예전: 묶음 하나에 왕복 최대 15회 × 사다리 3회).
            st["transient"] = str(res.get("phase") or "timeout")
            st["failed_rows"] += len(idxs)
            return got
    missing = [i for i in idxs if i not in got]
    if not missing:
        return got
    incomplete = (not res.get("ok")) or (not got) or bool(info.get("repaired")) or bool(res.get("cut"))
    if not incomplete:
        st["omitted_rows"] += len(missing)          # 온전한 답인데 모델이 빠뜨림 — 규칙으로
        st.setdefault("omitted_idx", set()).update(missing)
        return got
    max_depth = MAX_SPLIT_DEPTH
    if res.get("ok") and not got and len(str(res.get("reply") or "").strip()) < SHORT_REPLY_CHARS:
        max_depth = min(max_depth, 1)               # JSON 없는 짧은 답 — 거절·제한 문구일 수 있어 한 단계만 나눠 본다
    if st.get("soft") or depth >= max_depth:
        st["failed_rows"] += len(missing)
        return got
    if got:                                          # 부분 성공 — 빠진 행만
        if len(missing) >= MIN_RETRY_ROWS:
            st["retries"] += 1
            got.update(judge_rows(missing, rows, models, seen, tag, f"{label}r", depth + 1, st))
        else:
            st["failed_rows"] += len(missing)
        return got
    if len(idxs) >= 2 * MIN_SPLIT:                   # 통째 실패 — 반으로
        st["retries"] += 1
        h = len(idxs) // 2
        for k, sub in enumerate((idxs[:h], idxs[h:])):
            got.update(judge_rows(sub, rows, models, seen, tag, f"{label}{'ab'[k]}", depth + 1, st))
        return got
    st["failed_rows"] += len(idxs)
    return got


# ── AI 가 직접 못 본 행 채우기 ──────────────────────────────────────────────────────────
# 실패·중단으로 남은 행이 모두 규칙 이름('공통/기타')으로 쌓이지 않게, 가장 비슷한 AI 판정을 빌려 채우고 'AI(유사)' 로 표시한다 —
# 채운 판정은 판정 기록·캐시에 넣지 않아 다음 실행이 AI 에 다시 묻는다.
FILL_TOKEN_SHARE = 0.6      # 규칙 토큰 채우기 — 한 과제가 그 토큰 판정 행의 이 비율 이상이고
FILL_TOKEN_MIN = 3          # … 이 행 수 이상일 때만
FILL_SIM_PER_TOKEN = 300    # 유사 채우기 — 낱말 하나가 가리키는 판정 행 상한


def _day(r):
    """행 날짜 → 일련 번호(거리 비교용) · 못 읽으면 None."""
    try:
        return date.fromisoformat(str(r.get("time") or "")[:10]).toordinal()
    except (TypeError, ValueError):
        return None


def fill_unjudged(rows, judged, targets, keys=None):
    """AI 가 직접 못 본 행을 비슷한 판정으로 채운다 → {행: (판정, 방법)} — 방법은 same·token·sim.
    ① same — 같은 내용 묶음 키(group_key)인 판정 행 중 가장 흔한 판정(비업무 n 도 옮기는 유일한 단계)
    ② token — mine 규칙 토큰(project — 미지정·공통·상투어 제외): 그 토큰 판정 행의 60% 이상(3행 이상)이 한 과제면 그 과제와
       그 과제의 가장 흔한 (유형, 세부업무)
    ③ sim — 드문 낱말(df ≤ max(30, 0.5%·N) · 대화 낱말 제외)의 IDF 합(Σ log(N/df))이 가장 큰 판정 행(합 ≥ log(N/30) · 같으면 가까운
       날짜) — 그 행이 업무일 때만(비업무와 가장 닮았으면 채우지 않는다)
    ②·③은 업무 판정만 옮기고 행을 버리지 않는다. 강한 행정 공지 제목은 ②·③으로 채우지 않는다(규칙의 '공통/공지').
    targets: 채울 후보(판정 없음·광고 아님·관문 아님). keys: group_key 목록(없으면 새로 만든다)."""
    out = {}
    targets = [i for i in targets if i not in judged]
    if not targets or not judged:
        return out
    keys = keys if keys is not None else [group_key(r) for r in rows]
    by_key = defaultdict(Counter)
    for i, j in judged.items():
        if keys[i] is not None:
            by_key[keys[i]][_jt(j)] += 1
    left = []
    for i in targets:                                         # ① same
        c = by_key.get(keys[i]) if keys[i] is not None else None
        if c:
            out[i] = (dict(_jd(c.most_common(1)[0][0]), via="same"), "same")
        else:
            left.append(i)
    left = [i for i in left if not details.is_notice_subject(rows[i].get("text"))]
    if not left or not any(j.get("work") for j in judged.values()):
        return out

    def _ptok(r):
        p = str(r.get("project") or "").strip()
        return p if p and p not in ("미지정", "공통") and _rule_name_ok(p) else ""
    tot, cnt, wd = Counter(), defaultdict(Counter), defaultdict(Counter)
    for i, j in judged.items():
        p = _ptok(rows[i])
        if not p:
            continue
        tot[p] += 1
        if j.get("work"):
            cnt[p][str(j.get("model") or "")] += 1
            wd[(p, str(j.get("model") or ""))][(str(j.get("worktype") or ""), str(j.get("detail") or ""))] += 1
    rest = []
    for i in left:                                            # ② token
        p = _ptok(rows[i])
        c = cnt.get(p) if p else None
        if c:
            m, n = c.most_common(1)[0]
            if n >= FILL_TOKEN_MIN and n >= FILL_TOKEN_SHARE * tot[p]:
                wt, dt = wd[(p, m)].most_common(1)[0][0]
                out[i] = ({"work": True, "model": m, "worktype": wt, "detail": dt, "via": "token"}, "token")
                continue
        rest.append(i)
    if rest:
        _fill_sim(rows, judged, rest, out)                    # ③ sim
    return out


def _fill_sim(rows, judged, left, out):
    """fill_unjudged ③ sim — 드문 낱말의 IDF 합이 가장 큰 판정 행(업무일 때만). 대화 낱말·상투어는 낱말로 치지 않는다
    (extract.content_words)."""
    from extract import content_words
    n_all = len(rows)
    toks, df = [], Counter()
    for r in rows:
        ts = set(content_words(r.get("text") or ""))
        toks.append(ts)
        df.update(ts)
    lim = max(30.0, 0.005 * n_all)
    index = defaultdict(list)
    for i in sorted(judged):
        for t in toks[i]:
            if df[t] <= lim and len(index[t]) < FILL_SIM_PER_TOKEN:
                index[t].append(i)
    thr = math.log(n_all / 30.0) if n_all > 30 else 0.0
    for i in left:
        sc = defaultdict(float)
        for t in toks[i]:
            if t in index:
                w = math.log(n_all / df[t])
                for j in index[t]:
                    sc[j] += w
        if not sc:
            continue
        best = max(sc.values())
        if best <= 0 or best < thr:
            continue
        di = _day(rows[i])
        j = min((j for j, s in sc.items() if s >= best - 1e-9),
                key=lambda j: (abs(_day(rows[j]) - di) if (di is not None and _day(rows[j]) is not None) else float("inf"),
                               j))
        if judged[j].get("work"):
            out[i] = (dict(judged[j], via="sim"), "sim")

# ── 피벗(§5.7)·공통업무 ─────────────────────────────────────────────────────────────────
COMMON_TOP = 12             # 공통업무(2개 이상 과제에 걸친 세부업무) 상한


def build_pivots(kept):
    """판정된 신호 행 → {"product", "by_worktype": {유형: 근거건수}, "common": [{"name","worktype","근거건수"}]}.
    common = 2개 이상 과제('공통' 제외)에 걸친 세부업무(표준화·자동화 후보) — worktype 은 그 세부업무의 가장 흔한 유형,
    근거건수는 그 세부업무의 신호 수. 건수만 쓴다(시간·MM·비중 없음)."""
    by_wt = Counter()
    det_models, det_wt, det_n = defaultdict(set), defaultdict(Counter), Counter()
    for r in kept:
        md = str(r.get("model") or "").strip() or "공통"
        wt = str(r.get("worktype") or "").strip() or "사무"
        dt = str(r.get("detail") or r.get("activity") or "").strip() or "기타"
        by_wt[wt] += 1
        det_models[dt].add(md)
        det_wt[dt][wt] += 1
        det_n[dt] += 1
    common = [{"name": dt, "worktype": det_wt[dt].most_common(1)[0][0], "근거건수": det_n[dt]}
              for dt, ms in det_models.items() if len([m for m in ms if m != "공통"]) >= 2 and dt != "기타"]
    common.sort(key=lambda x: (-x["근거건수"], x["name"]))
    return {"product": PRODUCT,
            "by_worktype": dict(sorted(by_wt.items(), key=lambda kv: (-kv[1], kv[0]))),
            "common": common[:COMMON_TOP]}
_MERGE_STOP = {"관리", "업무", "작업", "진행", "기타", "관련", "대응", "지원", "및",
               "수립", "정의", "정리", "구조", "구성"}


def _detail_tokens(name):
    return {t for t in re.split(r"[\s_\-·/()\[\],]+", str(name or "").lower())
            if len(t) >= 2 and t not in _MERGE_STOP}


def _detail_note(name):
    """세부업무 이름 끝의 괄호 꼬리 — '구조 해석(양산)' → '양산'. 실제 구분 표기라
    꼬리가 다르면(없음 vs 있음 포함) 같은 일로 병합하지 않는다(core/details._note3 와 동일)."""
    m = re.search(r"[(（]([^)）]*)[)）]\s*$", str(name or ""))
    return m.group(1).strip().casefold() if m else ""


def merge_details(rows, amap=None):
    """같은 과제 안에서 사실상 같은 세부업무를 대표 이름 하나로 통합한다.
    AI가 청크마다 '공용 Capability 설계' / 'Capability 구조 설계'처럼 다르게 이름 붙이면
    (과제 × 세부업무) 격자가 곱셈으로 늘어나 같은 일이 여러 줄로 쪼개진다 — 한 행이어야 할 것이
    6행으로 쪼개지던 실측 결함. 가중치가 큰 이름을 대표로 삼는다. returns 병합된 행 수

    LM22: ① 괄호 꼬리가 다른 이름('레이아웃 검토(양산)' / '(선행)' / 꼬리 없음)은 토큰이 겹쳐도
    절대 병합하지 않는다 — 예전 토큰 규칙은 괄호를 구분자로 갈라 셋을 하나로 오병합했다(실측).
    ② 세부업무 병합 캐시(core/details — Copilot 이 '같은 묶음의 일'로 묶은 대표 이름)는 **여기서 쓰지
    않는다**(amap 을 명시해 넘길 때만). 그 캐시는 워크플로우·Agentic 의
    담당업무 축에만 적용하고, 판정 신호·업무 분류의 세부업무(하위) 이름은 판정
    이름 그대로 둔다 — 캐시를 판정 단계에 적용하니 검토/수정/리뷰 회의 같은 국면들이 하나로 접혀
    상위·중위·하위 구분이 사라졌다(제보: 'LM20 은 엔티티 구분이 잘 됐는데')."""
    if amap is None:
        amap = {}
    n = 0
    if amap:
        for r in rows:
            md, d = r.get("model") or "공통", r.get("detail") or "기타"
            rep, hops = amap.get((md, d)), 0
            while rep and (md, rep) in amap and amap[(md, rep)] != rep and hops < 5:
                rep, hops = amap[(md, rep)], hops + 1     # 사슬은 끝까지(캐시가 평탄하지 않아도)
            if rep and rep != d:
                r["detail"] = rep
                n += 1
    by_model = defaultdict(lambda: defaultdict(float))
    for r in rows:
        by_model[r.get("model") or "공통"][r.get("detail") or "기타"] += float(r.get("weight") or 0)
    # ③ 캐시가 정한 대표 이름(amap 의 값)은 대표로 먼저 고정한다 — 토큰 부분집합 규칙이 가중치 큰
    # 다른 이름('레이아웃 검토 회의')에 흡수시키면 signals/work_rows 의 Level 3 가 캐시 키·대표와
    # 어긋나 details.apply_detail_map 이 더는 맞지 않는다(F6).
    fixed_by = defaultdict(set)
    for (md, _k), rep in (amap or {}).items():
        if rep:
            fixed_by[md].add(rep)
    canon = {}
    for md, dts in by_model.items():
        reps = []
        fixed = fixed_by.get(md, set())
        ordered = sorted(dts.items(), key=lambda kv: -kv[1])
        for name, _w in ordered:
            if name in fixed:
                canon[(md, name)] = name
                reps.append((name, _detail_tokens(name), _detail_note(name)))
        for name, _w in ordered:
            if name in fixed:
                continue
            toks, note = _detail_tokens(name), _detail_note(name)
            hit = None
            for rname, rtoks, rnote in reps:
                if not toks or not rtoks or note != rnote:
                    continue
                if len(toks & rtoks) >= 2 or toks <= rtoks or rtoks <= toks:
                    hit = rname
                    break
            canon[(md, name)] = hit or name
            if not hit:
                reps.append((name, toks, note))
    for r in rows:
        k = (r.get("model") or "공통", r.get("detail") or "기타")
        rep = canon.get(k)
        if rep and rep != k[1]:
            r["detail"] = rep
            n += 1
    return n


WORK_COLS = ["Function", "Level 1", "유형", "Level 2", "Level 3", "상세설명", "근거건수", "근거", "확신도", "ax", "field",
             "share"]                     # §5.5 — 제품·이름·mm·활동일수·evidence 는 쓰지 않는다
EVIDENCE_MAX = 12           # evidence_<tag>.md 에 (과제, 세부업무)마다 남기는 근거 표본 줄 상한
EVIDENCE_CHARS = 100        # 근거 표본 한 줄의 제목 상한


def _wf(r):
    try:
        return max(0.0, float(r.get("weight") or 0))
    except (TypeError, ValueError):
        return 0.0


def _confidence(fams, n):
    """확신도 — 출처 계열 수(메일·회의)와 근거건수로만(날짜·시간 없음): 상 = 2계열·5건 이상 · 중 = 2계열 또는 3건 이상 · 하."""
    if fams >= 2 and n >= 5:
        return "상"
    return "중" if (fams >= 2 or n >= 3) else "하"


def _write_csv_atomic(path, cols, rows):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    os.replace(tmp, path)


def _write_text_atomic(path, text):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def evidence_md(kept, order=None, per=EVIDENCE_MAX):
    """판정된 신호 행 → evidence_<tag>.md 글(§5.5): '## <L2> / <L3> — 근거 N건' 다음 '- MM-DD <제목>' 줄(같은 제목은 한 번,
    기간에 고르게 퍼진 per 줄). 광고 의심 행은 싣지 않는다. order = [(L2, L3)] 순서(없으면 근거건수 내림)."""
    by = defaultdict(list)
    for r in kept:
        if is_ad_row(r):
            continue
        by[(str(r.get("model") or "").strip() or "공통", str(r.get("detail") or "").strip() or "기타")].append(r)
    keys = list(order or sorted(by, key=lambda k: (-len(by[k]), k)))
    out = []
    for k in keys:
        lst = sorted(by.get(k) or [], key=lambda r: str(r.get("time") or ""))
        if not lst:
            continue
        uniq, seen = [], set()
        for r in lst:
            t = " ".join(str(r.get("text") or "").split())[:EVIDENCE_CHARS]
            if t and t not in seen:
                seen.add(t)
                uniq.append((str(r.get("time") or "")[5:10], t))
        out.append(f"## {k[0]} / {k[1]} — 근거 {len(lst)}건")
        out.extend(f"- {d} {t}" for d, t in _sample_lines(uniq, per, lambda x: x))
        out.append("")
    return "\n".join(out)


def write_outputs(kept, tag, cfg, rep):
    r"""판정 완료 신호 → report\work_rows_<tag>.csv(§5.5) + pivots_<tag>.json(§5.7) + evidence_<tag>.md.
    judge 본류와 retag(지정 반영 재분류)·화면의 오할당 제외 양쪽에서 부른다. 근거건수는 지금 행으로 다시 센다.
    share = 그 (과제, 세부업무)의 신호 가중치 비율(정렬용 상대값 — 시간·MM 이 아니다). returns (행 수, 피벗)."""
    merged = merge_details(kept)
    if merged:
        print(f"        같은 일로 판정된 세부업무 {merged}건 통합 (행 파편화 방지)")
    # 상위(Level 1) 채움 재료 — taxonomy 가 과제마다 판정한 l1(entities)·사람이 못 박은 상위(projects.json level1)
    l1_map, pin = {}, {}
    try:
        with open(os.path.join(rep, f"entities_{tag}.json"), encoding="utf-8-sig") as f:
            ent = json.load(f)
        for m in (ent.get("models") or []):
            if isinstance(m, dict) and m.get("name") and m.get("l1"):
                _l1 = details.snap1(m.get("l1"))
                if _l1:
                    l1_map[ukey2(m["name"])] = _l1
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    import projmap
    for p in projmap.load_user_projects(ROOT):
        _l1 = details.snap1(p.get("level1"))
        if _l1:
            pin[ukey2(p["name"])] = _l1
    tot_w = sum(_wf(r) for r in kept) or 1e-9
    agg = defaultdict(lambda: {"w": 0.0, "n": 0, "fam": Counter(), "wt": Counter()})
    for r in kept:
        a = agg[(str(r.get("model") or "").strip() or "공통", str(r.get("detail") or "").strip() or "기타")]
        a["w"] += _wf(r)
        a["n"] += 1
        a["fam"][_fam(r) or "기타"] += 1
        a["wt"][str(r.get("worktype") or "").strip() or "사무"] += 1
    out_rows = []
    for (md, dt), a in sorted(agg.items(), key=lambda kv: (-kv[1]["w"], -kv[1]["n"], kv[0])):
        out_rows.append({"Function": (cfg or {}).get("function", ""),
                         "Level 1": details.level1_fill(md, dt, l1_map, pin, ROOT),
                         "유형": a["wt"].most_common(1)[0][0], "Level 2": md, "Level 3": dt, "상세설명": "",
                         "근거건수": a["n"],
                         "근거": " · ".join(f"{s} {n}" for s, n in a["fam"].most_common()),
                         "확신도": _confidence(len(a["fam"]), a["n"]),
                         "ax": ax_flag(f"{md} {dt}"), "field": field_of(f"{md} {dt}"),
                         "share": round(a["w"] / tot_w, 4)})
    _write_csv_atomic(os.path.join(rep, f"work_rows_{tag}.csv"), WORK_COLS, out_rows)
    _write_text_atomic(os.path.join(rep, f"evidence_{tag}.md"),
                       evidence_md(kept, order=[(r["Level 2"], r["Level 3"]) for r in out_rows]))
    pv = build_pivots(kept)
    _write_json_atomic(os.path.join(rep, f"pivots_{tag}.json"), pv)
    return len(out_rows), pv


def _stage_budget(floor_min=15.0):
    r"""core.budget.stage_budget 위임 — 단계 시간 예산(config.aiStageBudgetMin · 전체 마감 AF32_AI_DEADLINE)."""
    from budget import stage_budget
    return stage_budget(floor_min=floor_min, root=ROOT, now=time.time, mono=time.monotonic)


def _is_ai_row(r):
    """AI 가 판정한 행인가 — 'AI'(직접·재사용·같은 내용 묶음) · 'AI(유사)'(비슷한 판정으로 채움). '규칙' 은 아니다."""
    return str((r or {}).get("judge") or "").startswith("AI")


SIGNAL_COLS = ["time", "source", "who", "project", "activity", "weight", "text",
               "model", "worktype", "detail", "judge", "flag", "via"]


def main():
    import extract
    d0, d1 = arg("--from"), arg("--to")
    rc = details.consent_gate("judge", ROOT) or details.restricted_gate("judge", ROOT)   # 다른 사용자의 자료 4 · 지우는 중 3 · 제한 고객 목록 없음 4
    if rc:
        return rc
    # 80행은 입력 한도(9,000자)를 넘긴다 — 40행이 안전값(실측). 넘치면 드라이버가 조각으로 나눠 보내지만 왕복이 늘어난다.
    chunk_n = chunk_default("judgeChunk", 40)
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}"
    rep = os.path.join(ROOT, "report")
    sp = os.path.join(rep, f"signals_{tag}.csv")
    if not os.path.exists(sp):
        print(f"[judge] 입력 없음 — 먼저 mine.py 실행 ({sp})")
        return 1
    if not details.af32_tag_ok(tag, rep):
        print(f"[judge] report\\run_meta_{tag}.json 에 {PRODUCT} 표식이 없어 이 기간 자료를 쓰지 않습니다 — 먼저 mine.py 를 실행하세요")
        return 1
    with open(sp, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("[judge] 신호 0건")
        return 1
    for r in rows:                              # 날짜만(D10) — 시각이 섞인 옛 꼴이어도 판정·산출은 날짜만 쓴다
        r["time"] = str(r.get("time") or "")[:10]
    from stage_state import open_stage
    _ss = open_stage(rep, tag, "judge")        # 상태 파일 — 하트비트·진행·중단 사유
    cfg = extract.load_cfg()
    known = [str(k) for k in (cfg.get("projects") or []) if isinstance(k, str)]
    model_name = (cfg.get("copilotAuto") or {}).get("model", "GPT-5.6")

    # 사용자 지정 과제(UI에서 입력) — 힌트가 아니라 고정 엔티티로 체계에 항상 포함
    import projmap
    pinned = [{"name": p["name"], "match": p.get("match") or [], "desc": p.get("desc", ""),
               "obs": "사용자 지정", "pinned": True}
              for p in projmap.load_user_projects(ROOT)]
    pinned_l = {p["name"].lower() for p in pinned}
    # 과제명 관문 재료: 사람 이름 키(signals 의 who 열 + G1 이 남긴 이름 해시 data\cache\name_hashes.json — 코드에 이름을
    # 두지 않는다 · AF32 의 who 는 가명이라 해시가 주된 재료다)·지정 과제 키
    people = details.person_keys((r.get("who") for r in rows), ROOT)
    pinned_keys = {ukey2(p["name"]) for p in pinned}

    # 지난 분석에서 발견된 과제도 힌트로(실행 간 일관성) — 채택 여부는 이번 표본 관찰이 결정. 규칙 폴백 체계는 건너뛴다.
    prev_ms, prev_path = _load_prev_entities(rep, people)
    prev_models = [m["name"] for m in prev_ms if m["name"] != "공통"]
    hints = [h for h in dict.fromkeys(known + prev_models) if h.lower() not in pinned_l]

    # [재개·묶음] — 체계 왕복보다 먼저. 지난 판정(다른 날짜 기간 포함)을 내용 키로 회수하고, 같은 내용은 대표 한 줄만 보낸다.
    # 보낼 것이 없고 지난 정상 체계가 있으면 체계·통합 왕복도 건너뛴다.
    today = date.today().isoformat()
    keep_days = cache_keep_days(cfg)
    # 회의 안건(config.calendar.bodyToAI): 안건이 붙은 회의 행은 내용 키에 안건을 넣는다 — 안건이 생기거나 바뀐 회의만
    # 한 번 다시 판정한다. 캐시 파일에는 키의 sha1 만 남는다(안건 원문 없음)
    notes = meeting_notes(rows, cfg, d0, d1)
    ckeys = [_ckey(signal_sig2(r) + (NOTE_KEY_SEP + notes[i] if i in notes else "")) for i, r in enumerate(rows)]
    judged, n_fail, n_partial, last_err = {}, 0, 0, ""
    redo = "--redo" in sys.argv                   # 처음부터 판정 — 캐시를 새로 시작한다
    cache = ({"v": JUDGE_CACHE_V, "since": today, "items": {}, "expired": 0} if redo     # 날짜만(D10)
             else load_judge_cache(rep, keep_days, today))
    citems = cache["items"]
    if cache.get("expired"):
        print(f"[judge] 판정 캐시에서 보관기한({keep_days}일)이 지난 항목 {cache['expired']}건을 버립니다")
    n_exact = n_named = 0
    if not redo:
        for i in range(len(rows)):
            e = citems.get(ckeys[i])
            j = _from_cache(e)
            if j is None:
                continue
            if j["work"] and not _cached_name_ok(j["model"], people, pinned_keys):
                n_named += 1                      # 사람 이름·공지류 과제로 판정된 옛 판정 — 다시 묻는다
                continue
            e["at"] = today                       # 마지막으로 쓴 날 — 보관기한·상한은 이 날짜로 센다
            judged[i] = dict(j, via="cache")
        n_exact = len(judged)
    # G3 — 광고 의심(signals flag 'ad') 행은 Copilot 에 보내지 않고 비업무로 둔다
    ad_idx = {i for i, r in enumerate(rows) if i not in judged and is_ad_row(r)}
    if ad_idx:
        print(f"[judge] 광고 의심 신호 {len(ad_idx)}건은 보내지 않고 비업무로 둡니다(개인정보 관문 G3)")
    gkeys = [group_key(r) for r in rows]
    for i, nt in notes.items():                   # 안건이 붙은 회의는 안건까지 같아야 한 묶음이다(Copilot 이 보는 줄이 같게)
        if gkeys[i] is not None:
            gkeys[i] = (gkeys[i][0], gkeys[i][1] + NOTE_SEP + nt)
    # (a) 같은 내용 재사용 — 지난 판정이 있는 묶음 키의 새 행(옛 스레드의 새 회신 등)은 왕복 없이 그 판정을 쓴다
    by_key = defaultdict(Counter)
    for i, j in judged.items():
        if gkeys[i] is not None:
            by_key[gkeys[i]][_jt(j)] += 1
    n_keyed = 0
    for i in range(len(rows)):
        if i in judged or i in ad_idx or gkeys[i] is None or gkeys[i] not in by_key:
            continue
        judged[i] = dict(_jd(by_key[gkeys[i]].most_common(1)[0][0]), via="reuse")
        citems[ckeys[i]] = _cache_entry(judged[i], today)
        n_keyed += 1
    # (b) 남은 행은 같은 내용끼리 묶어 대표만 보낸다(대표의 판정을 구성원 전체에)
    todo = [i for i in range(len(rows)) if i not in judged and i not in ad_idx]
    reps, members = group_reps(rows, todo, gkeys)
    n_members = sum(len(v) for v in members.values())
    n_reused = n_exact + n_keyed
    if n_reused or n_named:
        print(f"[judge] 이어서 판정 — 지난 실행(다른 날짜 포함) {n_reused}건 재사용"
              + (f"(같은 내용 {n_keyed}건 포함)" if n_keyed else "")
              + (f" · 사람 이름·공지류 과제로 판정된 {n_named}건은 다시 판정" if n_named else "")
              + f" · 남은 {len(todo)}건")
    if members:
        print(f"        같은 내용 묶음 — 대표 {len(members)}줄이 {len(members) + n_members}행을 대신합니다"
              f"(보낼 줄 {len(reps)})")

    def _view(i):
        """프롬프트에 싣는 행 — 회의 안건을 붙인 사본(원본 행은 그대로)."""
        return dict(rows[i], note=notes[i]) if i in notes else rows[i]
    # 체계·통합 표본은 같은 내용을 한 줄로(광고 제외) — 스레드 회신이 표본을 덮지 않게
    _sreps, _sm = group_reps(rows, [i for i in range(len(rows)) if i not in ad_idx], gkeys)
    sample_rows = [rows[i] for i in _sreps] or rows
    st = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_rows": 0, "omitted_rows": 0,
          "notes": [], "last_err": "", "soft": False, "aborted": False, "gated_rows": 0,
          "gated_idx": set(), "omitted_idx": set(), "group_rows": 0, "abort_kind": "", "abort_reason": "",
          "meet_notes": notes}                    # 회의 안건 {행 번호: 안건} — judge_rows 가 그 회의 줄에만 붙인다

    # [0] 엔티티 체계 — 지정은 항상 포함(코드로 강제), 나머지는 AI가 표본에서 자동 발견
    n_chunks = -(-len(reps) // chunk_n)
    res, _fatal0, used_fallback, reused_tax = {}, False, False, False
    _why0 = _how0 = ""
    models = []
    if not reps and prev_ms:
        # 보낼 신호가 없다(전부 재사용·광고) — 체계·통합 왕복을 하지 않고 지난 정상 체계를 쓴다
        models = sanitize_models(pinned + prev_ms, people)
        tax_ok, reused_tax = True, True
        print(f"[judge] 보낼 신호가 없어 체계 수립 왕복을 건너뜁니다 — 지난 체계 재사용({os.path.basename(prev_path)})")
        print("        모델: " + ", ".join(m["name"] for m in models[:10]))
    else:
        progress("AI 판정", 0, n_chunks + 1)
        print(f"[judge] 0/{n_chunks + 1} 과제 체계 수립 왕복 (모델 {model_name}"
              + (f" · 지정 {len(pinned)}개" if pinned else "") + ") — 응답까지 수십 초 걸립니다")
        res = copilot_send(taxonomy_prompt(sample_rows, hints, pinned), tag, "taxonomy")
        # 이 왕복이 사실상 프로브다 — 로그인이 안 됐으면 여기서 이미 드러난다. 다만 한 번으로 단정하지는 않는다(아래).
        _why0, _how0, _fatal0 = explain_failure(res)
        tax_ok = bool(res.get("ok"))          # 체계 왕복 성공 여부 — entities 저장 관문이 본다
        if _fatal0:
            print(f"[judge] 체계 수립 왕복이 실패했습니다 — {_why0}")
            print(f"        {_how0}")
            print("        규칙 판정으로 신호·업무 분류는 그대로 만듭니다. 로그인 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행]을 누르면 AI 판정만 이어서 합니다.")
        if res.get("ok"):
            o = (rfind_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,))
                 or repair_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,)))
            models = unmask_models(m for m in _as_list(o.get("models"))      # 가려 보낸 지정 과제·힌트 → 원래 이름
                                   if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"].strip())
            if not models:
                note_bad_reply()
        # AI가 지정 과제의 match를 보강했으면 병합해 pinned에 흡수 (표기·설명은 사용자 것이 우선)
        for m in models:
            for p in pinned:
                if str(m.get("name", "")).strip().lower() == p["name"].lower():
                    p["match"] = list(dict.fromkeys(p["match"] + [str(k).lower() for k in _as_list(m.get("match"))]))
        # 초안이 2개를 넘으면 한 번 더 물어 같은 실체를 통합한다(--fast 로 생략 가능)
        if len(models) > 2 and "--fast" not in sys.argv:
            progress("AI 판정", 0, n_chunks + 2)
            print("[judge] 0b 과제 체계 통합 왕복 (같은 실체가 갈리는 것 방지)")
            draft = sanitize_models(models, people)
            rc2 = copilot_send(consolidate_prompt(draft, sample_rows), tag, "consolidate")
            if rc2.get("ok"):
                o2 = rfind_json(rc2.get("reply", ""), "models", skip=(CONSOLIDATE_EXAMPLE,))
                cand = unmask_models(m for m in _as_list(o2.get("models")) if isinstance(m, dict) and m.get("name"))
                if cand and len(cand) <= len(models):
                    print("        통합 후: " + ", ".join(m["name"] for m in cand[:10]))
                    for _ln in merge_log_lines(cand):      # 무엇을 무엇에 합쳤는지 — 과병합을 로그로 찾게
                        print("        " + _ln)
                    models = apply_merges(cand, draft)     # 통합 응답에 없는 l1 은 초안에서 옮긴다
                else:
                    print("        통합 결과가 유효하지 않아 초안 유지")
            else:
                print("        통합 왕복 실패 — 초안 유지")
        models = sanitize_models(pinned + models, people)   # 지정이 앞 → 중복 시 사용자 표기가 대표
        # AI가 새 과제를 하나도 못 주면(왕복 실패든, 산문 응답으로 파싱 실패든) 규칙 폴백 — 지정 + 지난 정상 체계 + 걸러진 규칙
        # 토큰. entities 에 "fallback": true 를 남겨 다음 실행·mine 이 되먹지 않게 한다.
        ai_added = any(not m.get("pinned") and m["name"] != "공통" for m in models)
        if not ai_added and not (res.get("ok") and rfind_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,))):
            models = sanitize_models(pinned + fallback_models(rows, known, people, prev_ms), people)
            used_fallback = True
            print("        체계 수립 실패(왕복 또는 응답 파싱) — 지정+지난 체계+규칙 발견 후보로 폴백")
        else:
            print("        모델: " + ", ".join(m["name"] for m in models[:10]))
    # entities 파일은 판정이 끝난 뒤에 쓴다 — 판정이 0건(왕복 전부 실패)이면 기존 파일을 규칙 폴백 체계로 덮지 않고 보존한다
    ent_p = os.path.join(rep, f"entities_{tag}.json")
    ent_obj = {"product": PRODUCT, "models": models, "worktypes": WORKTYPES, "hints_used": hints}
    if used_fallback:
        ent_obj["fallback"] = True                # 규칙 폴백 체계 — 지난 체계로 되먹이지 않는다(details.entities_is_fallback)
    if reused_tax:
        ent_obj["reused_from"] = os.path.basename(prev_path)
    ent_prev = os.path.exists(ent_p)

    # [1..N] 신호 판정 — 대표 행만, 행 수(chunk_n)와 글자 예산 둘 다로 자른다. 머리말 길이는 과제 목록과 '앞서 쓴 이름' 목록
    # 상한, 회의 안건 안내 줄과 D19 머리말(AI_PREFIX)까지 넣어 잰다.
    head_len = (len(judge_prompt([], 0, models)) + SEEN_MAX_CHARS + 160 + len(AI_PREFIX) + 1
                + (len(NOTE_HINT) + 1 if notes else 0))
    plan = pack_chunks([_view(i) for i in reps], chunk_n, head_len)
    chunks = [reps[s:s + n] for s, n in plan]          # 청크마다 대표 행 번호(원본 행 인덱스)
    if len(chunks) != n_chunks and not n_reused:
        print(f"        글자 예산({PROMPT_BUDGET:,}자)에 맞춰 청크 {n_chunks}→{len(chunks)}개"
              f" (머리말 {head_len:,}자 · 행 최대 {max((n for _s, n in plan), default=0)}개)")
    n_skip = 0                                 # 개인정보 관문에 막혀 보내지 않은 청크(연속 실패 계수 밖)
    if _fatal0:
        # 체계 수립 왕복 한 번으로 '사람이 손대야 풀리는 실패' 라고 단정하지 않는다 — 일시적 실패(입력창을 아직 못 찾음 등)도
        # 같은 얼굴로 온다. 청크를 하나만 더 보내 확인하고, 같은 실패면 청크 루프의 관문이 aborted 로 접는다.
        print("        확인을 위해 첫 청크 하나만 보내 봅니다 — 같은 실패면 거기서 접습니다.")
    consec, prev_idxs = 0, ()
    _dl, _bud = _stage_budget()
    _budget_stop = ""
    for ci, idxs in enumerate(chunks):
        n = len(idxs)
        # 예산 관문 — 스스로 멈추고 아래 저장 경로를 그대로 탄다(부모의 상한에 끊기면 뒤 단계를 모두 건너뛴다)
        if _dl is not None and _budget_stop == "" and time.monotonic() > _dl:
            if _ss is not None:
                _ss.note_resume(pending=len(plan) - ci)
            _budget_stop = (f"시간 예산 {_bud:.0f}분을 넘겨 남은 {len(plan) - ci}청크를 보내지 "
                            "않았습니다 — 여기까지의 판정을 저장하고 끝냅니다"
                            "(다시 실행하면 남은 신호만 이어서 판정합니다 · config.aiStageBudgetMin)")
            print(f"[judge] {_budget_stop}")
            if not st["abort_kind"]:
                st["abort_kind"], st["abort_reason"] = "budget", _budget_stop
            save_judge_cache(rep, cache, prune=False)
        if _budget_stop or st["aborted"]:
            st["failed_rows"] += n
            n_fail += 1
            continue
        progress("AI 판정", ci + 1, len(chunks) + 1)
        _cover = sum(len(members.get(i, ())) for i in idxs)
        print(f"[judge] {ci+1}/{len(chunks)} 신호 판정 왕복 (#{idxs[0]}~#{idxs[-1]}"
              + (f" · 같은 내용 {_cover}행 포함" if _cover else "") + ")")
        st["notes"] = []
        st["_skipped"] = False
        _g0 = st["gated_rows"]
        got = judge_rows(idxs, rows, models, recent_details(judged, prev_idxs, people), tag, f"chunk{ci+1}", 0, st)
        judged.update(got)
        # 같은 내용 묶음 — 대표의 판정을 구성원 전체에. 관문에 걸린 대표의 구성원·빠뜨린 대표의 구성원도 같은 처지로 센다.
        _n_mem = 0
        for i in idxs:
            mem = members.get(i, ())
            if not mem:
                continue
            if i in got:
                for m in mem:
                    judged[m] = dict(got[i], via="group")
                _n_mem += len(mem)
            elif i in st["gated_idx"]:
                st["gated_idx"].update(mem)
            elif i in st["omitted_idx"]:
                st["omitted_idx"].update(mem)
        st["group_rows"] += _n_mem
        prev_idxs = idxs
        if got:
            consec = 0
            if len(got) < n - (st["gated_rows"] - _g0):     # 관문에 걸린 행은 '부분 판정' 이 아니다
                n_partial += 1
            # 묶음마다 캐시에 저장 — 중간에 끊겨도 여기까지의 판정은 다음 실행이 다시 묻지 않는다
            for i in got:
                for m in (i, *(members.get(i, ()))):
                    citems[ckeys[m]] = _cache_entry(judged[m], today)
            save_judge_cache(rep, cache, prune=False)
        elif st.get("_skipped"):
            n_skip += 1                       # 개인정보 관문(G3)에 막혀 보내지 않았다 — 연속 실패 계수 밖(그 행만 규칙 판정)
        else:
            consec += 1
            n_fail += 1
            last_err = st.get("last_err") or last_err
        note = ("" if not st["notes"] else " · " + " / ".join(st["notes"][:4]))
        print(f"        판정 {len(got)}/{n}건" + (f"(+같은 내용 {_n_mem}행)" if _n_mem else "") + note)
        if st.get("fatal"):
            # 사람이 손대야 풀리는 상태(로그인 만료·강한 사용량 제한 등) — 남은 청크는 바로 규칙 판정으로
            st["aborted"] = True
            st["abort_kind"] = st.get("fatal_kind") or "fatal"
            st["abort_reason"] = st["fatal"]
            print(f"        {st['fatal']}")
            print("        남은 청크는 규칙 판정으로 둡니다 — 해결한 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행]을 누르면 AI 판정만 이어서 합니다.")
            save_judge_cache(rep, cache, prune=False)
        elif consec >= ABORT_FAIL_CHUNKS:
            st["aborted"] = True
            st["abort_kind"] = "content"
            st["abort_reason"] = (f"연속 {consec}청크 0건"
                                  + (f" — {st.get('last_err')}" if st.get("last_err") else ""))[:300]
            print(f"        연속 {consec}청크 0건 — 남은 청크는 규칙 판정으로 둡니다"
                  "(Copilot 상태를 확인한 뒤 재실행하면 이어서 판정됩니다)")
            save_judge_cache(rep, cache, prune=False)
        elif consec >= SOFT_FAIL_CHUNKS and not st["soft"]:
            st["soft"] = True
            print(f"        연속 {consec}청크 0건 — 적응 재시도(반분·빠진 행)를 끄고 1회씩만 시도합니다")
    if _fatal0 and not chunks and not st.get("fatal"):
        # 체계 왕복이 사람이 손댈 실패였고 확인할 묶음이 없다
        st["fatal"] = f"{_why0} — {_how0}"
        st["aborted"] = True
        st["abort_kind"], st["abort_reason"] = _abort_kind_of(res), st["fatal"]
    if st["aborted"]:
        print(f"        중단으로 건너뛴 청크 포함 0건 청크 {n_fail}/{len(chunks)}")
    if n_skip or st["gated_rows"]:
        print(f"        개인정보 관문(G3): 보내지 않은 청크 {n_skip}개 · 규칙 판정으로 둔 행 {st['gated_rows']}건"
              " (연속 실패로 세지 않음)")
    save_judge_cache(rep, cache, keep_days=keep_days, today=today)     # 끝 저장 — 보관기한·상한 가지치기 포함

    # AI 가 직접 못 본 행 채우기 — 같은 내용·규칙 토큰·비슷한 판정 순. 관문 행·광고는 채우지 않는다.
    gated = st["gated_idx"]
    unseen = [i for i in range(len(rows)) if i not in judged and i not in ad_idx and i not in gated]
    fills = fill_unjudged(rows, judged, unseen, gkeys)
    filled_n = Counter(how for _j, how in fills.values())

    # 판정 반영 — 한 곳에서: AI 유래 과제명은 final_model(사람 이름·공지류·잡음 → '공통'), 사람 이름 세부업무는 활동명.
    # 미판정 행은 match 키워드로 매핑(강한 행정 공지 제목은 '공통/공지').
    kept, dropped_rows = [], []
    for i, r in enumerate(rows):
        j = judged.get(i)
        if j is None and i in fills:
            j = fills[i][0]
        if j is None and i in ad_idx:
            r["judge"] = "ad"
            dropped_rows.append(r)          # 광고 의심 — 비업무
            continue
        if j is None:
            if details.is_notice_subject(r.get("text")):
                r.update(model="공통", worktype="사무", detail="공지", judge="규칙")
            else:
                r.update(model=rule_model(r, models), worktype="사무", detail=r.get("activity") or "기타", judge="규칙")
            r["via"] = "rule"
            kept.append(r)
        elif not j["work"]:
            r["judge"] = "AI-n"
            dropped_rows.append(r)          # 비업무
        else:
            dt = j["detail"] or r.get("activity") or "기타"
            if details.is_person_name(dt, people) or not details.detail_name_ok(dt):
                dt = r.get("activity") or "기타"
            r.update(model=final_model(j["model"], models, people, pinned_keys), worktype=j["worktype"] or "사무",
                     detail=dt, judge=("AI(유사)" if j.get("via") in ("token", "sim") else "AI"),
                     # 과제를 받은 길(이 PC 안에서만): ai 직접 · group 같은 문장 묶음 · cache 지난 판정 · reuse 지난 판정의 같은 문장 ·
                     # same/token/sim 채움
                     via=str(j.get("via") or "ai"))
            kept.append(r)
    rule_rows = sum(1 for r in kept if r.get("judge") == "규칙")
    # 실패 행 다시 세기 — 판정 없음 − 광고 − 관문 − 모델이 빠뜨린 행(대표가 실패하면 구성원도 실패다)
    _unj = {i for i in range(len(rows)) if i not in judged and i not in ad_idx}
    st["omitted_rows"] = len(_unj & st["omitted_idx"])
    st["failed_rows"] = len(_unj - gated - st["omitted_idx"])
    st["gated_rows"] = max(int(st["gated_rows"]), len(_unj & gated))
    if fills:
        print(f"        AI 가 직접 못 본 행 {len(unseen)}건 중 {len(fills)}건을 비슷한 판정으로 채움(같은 내용 "
              f"{filled_n['same']} · 규칙 토큰 {filled_n['token']} · 비슷한 신호 {filled_n['sim']})")
    # 사용자 지정 규칙 자동 재적용 — AI가 '공통'·자동발견으로 판정한 신호라도 지정 과제의 이름·키워드가 원문에 직격이면 지정으로
    if pinned:
        rn, rby, _rev = projmap.retag_rows(kept, projmap.load_user_projects(ROOT))
        if rn:
            print("        지정 규칙 자동 적용: "
                  + " · ".join(f"{k} {v}건" for k, v in sorted(rby.items(), key=lambda x: -x[1])))
    # 유사 세부업무 통합을 signals 저장 '전에' 끝낸다 — signals 와 work_rows 의 세부업무 이름이 갈리지 않게(write_outputs 도 멱등)
    merge_details(kept)
    # signals 되쓰기 — 판정 열을 더한다. flag(G2 광고 의심 표식)는 끝 쪽에 남긴다. via(과제를 받은 길)는 이 PC 안에서만.
    for r in kept:
        r["project"] = r.get("model", r.get("project", ""))
        r["activity"] = r.get("detail", r.get("activity", ""))
    _write_csv_atomic(sp, SIGNAL_COLS, kept)
    # 판정 중 새로 발견된 과제(체계에 없던 이름) → entities 에 discovered 로 기록(다음 실행의 체계 힌트). 비교는 ukey2.
    # 발견 목록은 최종 반영값(kept 의 AI 유래 행)에서 만든다 — final_model 이 '공통' 으로 돌린 사람 이름·공지류는 들어올 수 없다.
    model_names_l = {ukey2(m["name"]) for m in models}
    discovered = sorted({str(r.get("model") or "").strip() for r in kept
                         if _is_ai_row(r) and str(r.get("model") or "").strip()
                         and str(r.get("model")).strip() != "공통"
                         and ukey2(str(r.get("model")).strip()) not in model_names_l
                         and not NOISE_MODEL.match(str(r.get("model")).strip())})
    if discovered:
        print("        판정 중 새 과제 발견: " + ", ".join(discovered))
        ent_obj["models"] = sanitize_models(
            ent_obj["models"] + [{"name": d, "match": [d.lower()], "obs": "판정 중 발견"} for d in discovered], people)
        ent_obj["discovered"] = discovered
    if (judged and tax_ok) or not ent_prev:
        _write_json_atomic(ent_p, ent_obj)
    elif not tax_ok:
        # 체계 왕복이 실패한 실행 — 청크는 규칙 폴백 체계로 판정됐다. 그 체계로 entities 를 덮으면 다음 실행의 힌트가 폴백
        # 이름으로 퇴화한다. 발견된 새 과제만 기존 체계(AgentFinder32 것일 때만)에 보탠다.
        if discovered:
            try:
                with open(ent_p, encoding="utf-8-sig") as f:
                    ent_prev_obj = json.load(f)
                if isinstance(ent_prev_obj, dict) and ent_prev_obj.get("product") == PRODUCT:
                    ent_prev_obj["models"] = sanitize_models(
                        list(ent_prev_obj.get("models") or [])
                        + [{"name": d, "match": [d.lower()], "obs": "판정 중 발견"} for d in discovered], people)
                    _write_json_atomic(ent_p, ent_prev_obj)
            except (OSError, ValueError, TypeError):
                pass
        print("        체계 수립 왕복 실패 — 기존 entities 파일을 보존합니다(규칙 폴백 체계로 덮지 않음)")
    else:
        print("        판정 0건 — 기존 entities 파일을 보존합니다(규칙 폴백 체계로 덮지 않음)")

    dropped = len(dropped_rows)
    # 판정 기록 — 건수와 판정만(신호 원문 없음 · 항목 키는 내용 키의 sha1). items 에는 AI 판정(재사용·같은 내용 포함)만.
    _write_json_atomic(os.path.join(rep, f"ai_judgments_{tag}.json"), {
        "product": PRODUCT, "model": model_name, "total": len(rows), "judged": len(judged),
        "dropped_nonwork": dropped, "chunks": len(chunks), "failed_chunks": n_fail,
        "partial_chunks": n_partial, "failed_rows": st["failed_rows"],
        "omitted_rows": st["omitted_rows"], "repaired": st["repaired"],
        "retries": st["retries"], "roundtrips": st["roundtrips"],
        "aborted": st["aborted"], "chunk_rows": chunk_n, "prompt_budget": PROMPT_BUDGET,
        "skipped_chunks": n_skip, "gated_rows": st["gated_rows"], "ad_rows": len(ad_idx),
        "meeting_notes": len(notes),
        "cache_reused": n_reused, "cache_key_reused": n_keyed, "cache_expired": int(cache.get("expired") or 0),
        "group_rows": st["group_rows"], "reps": len(reps), "unseen_rows": len(unseen),
        "filled_rows": {k: int(filled_n.get(k, 0)) for k in ("same", "token", "sim")},
        "rule_rows": rule_rows, "abort_kind": st["abort_kind"], "abort_reason": st["abort_reason"],
        "cooldowns": _COOLDOWNS[0], "model_fallback": _MODEL_FALLBACK[0] or "", "rotations": _ROTATIONS[0],
        "cache_version": JUDGE_CACHE_V,
        "items": {str(k): dict(v, k=ckeys[k]) for k, v in judged.items() if 0 <= k < len(rows)}})

    # 업무 분류(work_rows) + 피벗 + 근거 표본 (retag·화면 제외와 공용 — write_outputs)
    n_out, pv = write_outputs(kept, tag, cfg, rep)
    cov = len(judged) / len(rows) * 100
    print(f"[judge] 판정 {len(judged)}/{len(rows)}건({cov:.0f}%) · 비업무 제외 {dropped}건"
          f" · 업무 분류 {n_out}줄 · 공통업무 {len(pv['common'])}건")
    if n_fail or n_partial or st["repaired"] or st["retries"]:
        print(f"        왕복 {st['roundtrips']}회(청크 {len(chunks)} · 재시도 {st['retries']}) · "
              f"잘린 응답 복구 {st['repaired']}회 · 실패 청크 {n_fail} · 부분 청크 {n_partial} · "
              f"실패로 규칙에 남은 행 {st['failed_rows']} · 모델이 빠뜨린 행 {st['omitted_rows']}")
    # 사진 한 장으로 판정 구조를 읽는 줄(현장 확인용) — 재사용·묶음·왕복·대기·채움·규칙·중단 갈래
    print(f"[judge] 구조: 신호 {len(rows)} · 재사용 {n_reused} · 같은 내용 대표 {len(reps)}(→{len(reps) + n_members}행) · "
          f"왕복 {st['roundtrips']} · 대기 {_COOLDOWNS[0]}회 · 채움 {len(fills)} · "
          f"규칙 {rule_rows} · 중단 {st['abort_kind'] or '없음'}"
          + (f" · 채팅 회전 {_ROTATIONS[0]}회(chatTurns {chat_turns()}번마다 새 채팅)" if _ROTATIONS[0] else "")
          + (f" · 대체 모델 {_MODEL_FALLBACK[0]}" if _MODEL_FALLBACK[0] else ""))

    if not judged:
        # 판정이 한 건도 없다 — 왕복이 전부 실패했거나 응답을 하나도 해석하지 못했다. signals/work_rows 는 규칙 임시 결과로 두고,
        # 사유는 마지막 줄 JSON 으로 run.py 에 넘긴다(rc 3 — 정제·Agentic·워크플로우를 건너뛴다).
        if n_fail == len(chunks) and last_err and not st["repaired"]:
            err = "AI 판정 실패(왕복 전부 실패)"
        else:
            err = (f"AI 판정 0건(청크 {len(chunks)}개 전부 0건 · 왕복 {st['roundtrips']}회"
                   + (f" · 개인정보 관문으로 보내지 않은 청크 {n_skip}개" if n_skip else "")
                   + ((" · " + {"throttle": "Copilot 사용량 제한으로 중단", "login": "Copilot 로그인 만료로 중단",
                                "fatal": "사람이 손대야 풀리는 상태로 중단"}.get(st.get("abort_kind") or "",
                                                                       "연속 실패로 중단"))
                      if st["aborted"] else "") + ")")
        # 성공 왕복의 프롬프트 파일은 지워진다 — 남아 있는 실패 청크 파일 하나를 안내한다
        import glob as _glob
        left = sorted(_glob.glob(os.path.join(rep, f"judge_chunk*_{tag}.md")))
        hint = last_err or (f"report\\{os.path.basename(left[0])} 를 회사 M365 Copilot(m365.cloud.microsoft, 회사 계정)에만 붙여 넣어 "
                            "응답 형식을 확인하세요" if left
                            else "Copilot 응답 형식을 [AI 연결 진단]으로 확인하세요")
        print(f"[judge] {err} — {hint}")
        print("        signals/work_rows 는 규칙 판정으로 두고 entities 기존 파일은 보존합니다")
        chat_note()
        print(json.dumps({"ok": False, "error": err, "hint": hint, "judged": 0,
                          "chunks": len(chunks), "failed_chunks": n_fail}, ensure_ascii=False))
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason=err, error=err, hint=hint)
        return 3
    chat_note()
    # rc 규약: 부분(예산 중단·실패 잔여)은 2 — '이어서' 가 데이터가 된다. 완주는 0.
    _partial = bool(_budget_stop) or st["failed_rows"] > 0 or st["omitted_rows"] > 0
    if _ss is not None:
        if _partial:
            _ss.note_resume(pending=max(int(st["failed_rows"] + st["omitted_rows"]), 1))
            # 중단 갈래 — 강한 사용량 제한(throttle)·로그인 만료(login)는 다시 보내도 같은 벽이다(run.py 가 재시도하지 않는다)
            _sk = ("budget" if _budget_stop else
                   {"throttle": "throttle", "login": "login"}.get(st.get("abort_kind") or "", "fatal"))
            _ss.finish("partial", stop_kind=_sk,
                       reason=(_budget_stop or st.get("abort_reason")
                               or f"실패 행 {st['failed_rows']}·누락 {st['omitted_rows']}"))
        else:
            _ss.finish("done")
    return 2 if _partial else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
