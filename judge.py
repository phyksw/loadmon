# -*- coding: utf-8 -*-
"""
judge.py — raw 판정을 Copilot(GPT-5.6)이 수행한다. (LoadMonitor20: 계층 엔티티 판)

3단계 왕복 (시간이 걸리는 대신 정확):
  [0] 체계 수립  — raw 개요를 주고 '상위 과제(제품·프로젝트) + 업무유형(개발/사무/현장/협업)'
                  엔티티 체계를 AI가 raw에서 직접 발견·설계 → entities_*.json
                  (config.projects 는 힌트일 뿐 — raw에 없으면 채택하지 않고, 없어도 발견.
                   판정 중 새 과제는 discovered로 기록되어 다음 실행 힌트로 순환)
  [1..N] 신호 판정 — 각 신호를 [업무여부, 과제, 업무유형, 세부업무]로 판정 (청크 40건 —
                  80건은 입력 한도 9,000자를 넘긴다: 머리말 572자 + 행 최악 147자 → 80행 ≈ 12,400자)
                  · 청크는 행 수(40)와 **글자 예산(PROMPT_BUDGET)** 둘 다로 자른다 — 긴 제목·긴 과제
                    목록이면 40행 미만으로 줄어든다(pack_chunks). 모든 청크 프롬프트는 머리말(기준·과제
                    목록·형식)을 포함해 **혼자서 완결**이다 — 드라이버가 재시도로 새 채팅을 열어도 답이 나온다
                    (예전 "계속입니다" 청크는 빈 채팅에 떨어졌다). 그러면서도 청크는 **같은 채팅에서 이어** 보내
                    Copilot 이 앞 청크의 과제·세부업무 표기를 기억한다(첫 왕복·실패 뒤·config.copilotAuto.chatTurns
                    마다만 새 채팅 — 제보: 청크마다 새 채팅이라 기억이 안 이어짐).
                  · 응답이 잘렸거나(cut·불완전 JSON) JSON 을 못 찾으면 **적응 분할**: 잘린 JSON 은 마지막
                    완전한 행까지 복구(repair_json)하고 빠진 행만 다시 묻고, 통째 실패는 반으로 나눠
                    재시도(최소 5행·깊이 3). 결과는 ai_judgments 의 failed_rows/repaired/roundtrips 로 정직히 남긴다.
                  · 명명 일관성: 직전 청크가 쓴 세부업무 이름(빈도순, 30개·600자 상한)을 동봉한다.
  [월별] 내러티브 — 판정된 신호로 그 달의 기여 서술 생성 → ai_narratives_*.json

산출:
  signals_*.csv          판정 반영 (model/worktype/detail, 비업무 제거)
  mm_rows_*.csv          Level2=과제, Level3=세부업무, 유형=개발/사무/현장 (MM=투입/가용 기준)
  pivots_*.json          과제→유형/세부 · 유형→과제 양방향 + 공통업무(표준화·자동화 후보) + 에피소드
  ai_narratives_*.json   월별 리뷰 서술

  python judge.py --from ... --to ... [--chunk 40] [--no-narrate]
  (청크 기본값은 config.copilotAuto.judgeChunk 로도 바꿀 수 있다 — --chunk 가 우선)

종료 코드: 0 정상 · 1 입력 없음 · 3 판정 0건(왕복 전부 실패 등 — 마지막 줄 JSON {"ok":false,
"error","hint"}; signals/mm_rows 는 규칙 판정으로 쓰되 entities·ai_narratives 기존 파일은 보존,
월별 내러티브 왕복은 하지 않고 이전 코멘트를 이 기간 파일로 이월만 한다 — run.py 가 이 코드를 보고
정제·Agentic·워크플로우를 건너뛴다).

프롬프트의 상대(who) 열은 기본적으로 주소의 도메인만('@corp.co') 싣는다 — 사람 이름·주소를
Copilot 에 보내지 않는 원칙. config.copilotAuto.sendSenderAddress=true 일 때만 주소 그대로.

copilot_send(prompt, tag, name, fresh=None) 은 다른 모듈(refine·agentic·flow·team_refine·
core/details)이 공유하는 Copilot 왕복 1회 접점이다 — 드라이버(tools/copilot_auto.py)가
긴 프롬프트 분할·[[전송끝]] 서약을 처리하므로 여기서는 왕복 예산만 조각 수에 맞춘다.
프롬프트 파일(report\\judge_<name>_<tag>.md)은 성공한 왕복이면 회수 직후 지우고, 실패한 왕복·해석 못 한
답(note_bad_reply)의 것만 남긴다 — 그 파일이 '직접 붙여넣기' 안내 대상이다.

LM28 — G3 Copilot 직전 관문과 인프로세스 왕복:
  · 프롬프트에 넣는 행(판정 행·체계 표본·통합 표본·월별 표본)은 먼저 g3_rows(privacy.gate_items)를 거친다 — 사적·광고 의심·
    자격증명·고위험 잔여·카나리아 행은 보내지 않고(그 행만 규칙 판정), 나머지는 재정제한 사본을 보낸다. 원본 행은 그대로다.
  · signals 의 flag 'ad'(광고 의심) 행은 Copilot 에 보내지 않고 비업무로 둔다(LM24 에서 AI 가 'n' 으로 거르던 것).
  · copilot_send 는 보내기 전에 최종 검사(g3_prompt)를 하고, 걸리면 보내지 않고 {"phase":"blocked"} 를 돌려준다. 관문에 막힌
    청크는 skipped 로 따로 센다 — 연속 실패 계수(SOFT/ABORT_FAIL_CHUNKS)에 넣지 않는다(개인정보가 많은 사람이 AI 판정 전체를
    규칙으로 잃지 않게). ai_judgments 에 gated_rows·skipped_chunks 를 남긴다.
  · config.copilotAuto.inProcess(기본 true)면 드라이버를 임포트해 같은 프로세스에서 왕복한다(send_inproc). taskkill 은 쓰지 않는다.
  · 회의 안건(사용자 요청 '일정 회의 내용도 참고 — 걸러서'): 회의 줄 끝에 ' — 안건: …'(일정 본문을 core\\meetnote 가 정제한 것,
    config.calendar.bodyToAI·noteMaxChars)을 붙인다. 안건만 관문에 먼저 넣어 통과한 것만 쓰고, 행과 함께 note 필드로 다시 관문을
    지난다. 안건이 생기거나 바뀐 회의만 캐시 내용 키가 바뀌어 한 번 다시 판정한다. signals·팀 반출에는 안건이 없다.

LM28 진단 A — 수천 행 규모의 판정:
  · 이어서 판정 캐시(report\\judge_cache.json — 내용 키의 sha1 → 판정, 원문 없음): 기간 tag 가 날마다 바뀌어도 이미 판정한 신호는
    다시 묻지 않는다. 캐시 이전 판의 ai_judgments_*.json 도 한 번 이어받는다. 묶음마다 저장(중간에 끊겨도 남는다). --redo 는 새로 시작.
  · 같은 내용 묶음: 같은 계열·같은 앞 95자(RE/FW 머리 제외)는 대표 한 줄만 보내고 판정을 묶음 전체에 쓴다. 짧은 팀즈 대화
    (인사·맞장구)는 보내지 않는다. 재개·묶음은 체계 왕복보다 먼저 — 보낼 것이 없으면 지난 정상 체계를 쓰고 체계 왕복을 건너뛴다.
  · Copilot 이 막히면(사용량 제한·일시 오류) 반으로 나눠 즉시 다시 보내지 않고 copilot_send 가 쉬었다 새로 고쳐 다시 보낸다 —
    일시 오류는 1·2·2분, 사용량 제한(「요청이 너무 많음」 — phase 'throttled')은 copilotAuto.throttleWaitSec(기본 2분) 한 번만.
    그래도 막히면 강한 제한(hard) — 남은 묶음은 보내지 않고 ai_judgments 의 abort_kind 에 throttle·login·fatal·content·
    budget 을 남긴다. 사용량 제한으로 멈추면 실행 표식(LM_RUN_ID — run.py)을 기록해 같은 실행의 뒤 단계(월별 코멘트·정제·
    Agentic·워크플로우)는 보내지 않고 쉬지도 않는다(copilot_auto.run_stopped) — 예전에는 단계마다 10분을 쉬고 한 번씩 더 보내
    한 실행이 한 시간 넘게 멈춰 보였다(현장 제보).
  · 한 실행(LM_RUN_ID)에서 Copilot 때문에 쉬는 시간은 모든 단계(프로세스)를 합쳐 copilotAuto.runWaitMaxSec(기본 300초 · 0 = 쉬지
    않음) 안이다(copilot_auto.run_wait_left·add_run_wait). 다 쓰면 다음 일시 오류·사용량 제한은 쉬지 않고 강한 제한 — 그 단계의 남은
    묶음은 보내지 않고 여기까지의 결과를 지킨다(사용자 요청 '분석이 길면 업무에도 지장 — 3~5분으로').
  · AI 가 직접 못 본 행은 같은 내용·같은 대화·규칙 토큰·비슷한 신호의 판정을 빌려 'AI(유사)' 로 채운다(판정 기록·캐시에는 넣지 않는다).
    signals 의 judge: 'AI'(직접·재사용·같은 내용) · 'AI(유사)'(채움) · '규칙'. 버린 행 장부: 'ad'(광고 의심) · 'AI-n'(AI 비업무).

LM30(2026-10-27) — 과제가 하나로 묶이던 것(사용자 '한 사람과 채팅한다고 한 일을 하는 게 아니라 여러 일을 복합적으로 하잖아'):
  · 팀즈 줄은 signals 의 conv 열(대화방 이름의 소금 친 키 — 이 PC 안에서만, 프롬프트에 싣지 않는다)로 대화를 가른다. 같은 내용 묶음은
    같은 대화·같은 날 안에서만(group_key), 같은 내용 재사용(지난 판정의 같은 문장)은 팀즈에 쓰지 않는다.
  · 짧은 팀즈 대화(is_lowinfo)는 맞장구·호칭·시각·문장 끝 꼴뿐인 줄('네 확인했습니다'·'자료 보내드렸습니다'·'[사람] 책임님 확인
    부탁드립니다')까지 넓혔다 — 보내지 않고 같은 대화에서 채운다(fill_unjudged ②·⑤ — 같은 보낸이를 먼저 고르지 않는다). 보내는 줄이 준다.
  · 판정 캐시 v2 — 짧은 팀즈 대화의 지난 판정은 쓰지 않고 지운다(예전 같은 문장 묶음이 다른 방·다른 과제의 판정을 옮겨 놓았을 수 있다).
    다음 [분석 실행]·[재분석만]이 다시 모으지 않고 같은 대화에서 다시 채운다(Copilot 왕복 없음).
  · 판정 머리말: 과제는 '그 줄의 내용이 가리키는 과제'(같은 상대·같은 대화방이라도 줄마다 다를 수 있다) · '이 묶음의 줄만 보고'.
  · 체계 통합(consolidate)은 표기 변형만 합친다 · 체계·통합 표본에서 팀즈 줄은 40% 까지 · '통합: A ← B, C' 를 로그에 남긴다.
  · signals 끝 via 열 — 그 행이 과제를 받은 길(ai·group·cache·reuse·same·conv·token·sim·rule). 리뷰 화면의 과제별 한 줄과 구조 줄이 쓴다.
"""
import bisect
import csv
import functools
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
from details import explain_failure  # noqa: E402  - 로그인 필요 등 "사람이 손대야 풀리는" 실패 판정
import details  # noqa: E402  - 과제명 관문(사람·공지 — task_name_ok 등)·상위 채움(level1_fill) 단일원 — LM28 진단 B
from details import ax_flag, field_of  # noqa: E402  - mm_rows 끝 열 ax(AX 연계 표식)·field(분야) — LM28
from details import ukey2  # noqa: E402  - 과제 신원 축(공백·구분자·대소문자 무시, 괄호 꼬리 보존)
from progress import progress  # noqa: E402
try:                       # 과제 몫 시간화(옵션 mm.shareBasis="time") — LM28. 없으면 LM24 가중치 몫으로 계속
    import timeshare  # noqa: E402
    from timeshare import UNCLASSIFIED  # noqa: E402
except ImportError:
    timeshare, UNCLASSIFIED = None, "근무 중 미분류"
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
# 이어서 판정 캐시(report\judge_cache.json) — 기간 tag 가 날마다 바뀌어도 이미 판정한 신호는 다시 묻지 않는다
JUDGE_CACHE = "judge_cache.json"
JUDGE_CACHE_V = 2                   # LM30(2026-10-27) v2 — 짧은 팀즈 대화의 지난 판정은 쓰지 않고 같은 대화에서 다시 채운다
CACHE_MAX = 150_000                 # 상한 — 넘으면 오래 쓰지 않은 판정부터 뺀다
CACHE_KEEP_DAYS = 450               # 분석 시작일보다 이만큼 앞서 마지막으로 쓴 판정은 뺀다
LEGACY_JUDGMENT_FILES = 10          # 캐시 이전 판의 ai_judgments_*.json 을 최신부터 이만큼 읽는다
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
                            # (LM30: 끊긴 답·느린 답은 아니다 — 드라이버가 이어 보내기 직전에 우리 채팅인지 다시 보고 아니면 새 채팅을 연다)
_ROTATIONS = [0]            # LM30 — 이 프로세스의 chatTurns 회전(같은 채팅에 상한만큼 보내 새 채팅으로 넘어간) 횟수 — 판정 기록·구조 줄
NOANS_PHASES = ("no_reply", "empty_reply")   # LM30 — 실패한 왕복이 채팅에 답 글을 남기지 않은 갈래(쉬었다 같은 채팅에 다시 — RELOAD_KEEP)
_TURNS = [0]                # 지금 채팅에서 성공한 왕복 수 — config.copilotAuto.chatTurns 에 닿으면 다음 왕복은 새 채팅
_CHAT_TURNS = [None]        # chatTurns 캐시 (None = 아직 안 읽음)
CHAT_TURNS_DEFAULT = 12     # 한 채팅에 이어 보내는 왕복 상한. 0 = 묶음마다 새 채팅(LM22 1차 방식)
_RESUME = "resume"          # = copilot_auto.RESUME — 다음 단계의 첫 왕복을 앞 단계의 우리 채팅에 이어 보낸다(화면 확인은 드라이버)
_RELOAD_KEEP = "keep"       # = copilot_auto.RELOAD_KEEP — 새 채팅 대신 같은 대화를 그 자리에서 새로 고친 뒤 이어 보낸다(LM30)
# 이어 쓸 수 있는 왕복 이름(정제·Agentic·워크플로우·세부업무 병합의 첫 왕복) — 판정 묶음·체계 수립·월별 코멘트는 늘 예전 규칙(새 채팅)
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
_WAIT_TICKS = [0]           # 대기 진행 줄의 누적 눈금 — 감시기의 진행 시계가 늘 앞으로 가게


def _restore_prompt():
    """직전 성공 왕복의 프롬프트 파일을 되살린다 — 답은 왔지만 해석하지 못한 청크는 '직접 붙여넣기' 안내
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
_SEND_WHO = [None]          # config.copilotAuto.sendSenderAddress 캐시 (None = 아직 안 읽음)
_ADDR_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+)")
# 사람이 아닌 역할 계정(알림·시스템)의 로컬 파트는 남긴다 — 공지 판별에 쓰이고 개인정보가 아니다
_ROLE_LOCAL_RE = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|notice|alerts?|system|admin|"
    r"newsletter|helpdesk|support|info|postmaster|mailer[-_.]?daemon|bot)$", re.I)


def send_sender_address():
    """config.copilotAuto.sendSenderAddress — 기본 False. True 일 때만 상대 주소를 그대로 보낸다."""
    if _SEND_WHO[0] is None:
        v = _copilot_cfg().get("sendSenderAddress")
        _SEND_WHO[0] = (v is True) or (str(v or "").strip().lower() in ("1", "true", "yes", "y", "on"))
    return _SEND_WHO[0]


def who_label(who, n=16):
    """프롬프트에 싣는 상대(who) 표기. 기본은 주소의 도메인만('@corp.co') — 사람 이름·주소를
    Copilot 에 보내지 않는 원칙(사람 이름·MM 미전송과 같은 선). '나'(본인 발신 표식)·빈 값은
    그대로, 주소가 아닌 표시 이름은 '(상대)'. sendSenderAddress=true 면 예전처럼 원문[:n]."""
    s = str(who or "").strip()
    if not s or s in ("나", "-"):
        return s
    if send_sender_address():
        return s[:n]
    m = _ADDR_RE.search(s)
    if m:
        dom = m.group(1).strip(".").lower()
        local = m.group(0)[:m.group(0).rfind("@")].lower()
        lab = (local + "@" + dom) if _ROLE_LOCAL_RE.match(local) else ("@" + dom)
        return lab[:max(n, 24)]
    return "(상대)"


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
    """쉴 수 있는 초 — 바라는 sec 를 전체 마감(LM_AI_DEADLINE − 2분)·프로세스 합계 상한(COOLDOWN_CAP_SEC)·이번 실행의 남은
    쉬는 시간(_run_wait_left — copilotAuto.runWaitMaxSec) 안으로."""
    room = min(COOLDOWN_CAP_SEC - _COOLED[0], _run_wait_left())
    try:
        at = float(os.environ.get("LM_AI_DEADLINE") or 0)
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
    tail = " — 이 단계의 남은 묶음은 보내지 않고 여기까지의 결과를 지킵니다(1~2시간 뒤 [재분석만])"
    if m <= 0:
        return "        이번 실행은 Copilot 을 기다리며 쉬지 않게 설정돼 있습니다(copilotAuto.runWaitMaxSec 0)" + tail
    total = f"{m // 60}분" if m >= 60 and m % 60 == 0 else f"{m}초"
    return f"        이번 실행에서 Copilot 을 기다리며 쉬는 시간(모두 {total} — copilotAuto.runWaitMaxSec)을 다 썼습니다" + tail


def _cooldown(sec):
    """sec 초 쉰다 — 30초마다 진행 줄('Copilot 대기')을 찍어 감시기의 무진전 시계가 멈추지 않게(쉬는 동안 끊기지 않게).
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
    """이번 실행의 표식(run.py 가 시작 때 싣는 LM_RUN_ID) — 단계를 따로 돌리면 ""."""
    return str(os.environ.get("LM_RUN_ID") or "").strip()


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
              "여기까지의 결과를 지킵니다(1~2시간 뒤 [재분석만])", flush=True)
    return {"ok": False, "phase": "throttled", "reason": "R-THROTTLE", "hard": True, "run_stop": True,
            "error": "Copilot 사용량 제한 — 이번 실행은 더 보내지 않음",
            "hint": "Copilot 이 「요청이 너무 많다」고 해 이번 실행의 AI 단계를 멈췄습니다 — 1~2시간 뒤 [재분석만]"}


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
        kw["reload"] = _RELOAD_KEEP if reload == _RELOAD_KEEP else True     # LM30 — 같은 대화 새로 고침은 그대로 넘긴다
    if _MODEL_FALLBACK[0]:
        kw["model"] = _MODEL_FALLBACK[0]
    res = _transport(prompt_text, pf, name, want_fresh, roundtrip_timeout(n_parts), **kw)
    if not isinstance(res, dict):
        return {"ok": False, "error": "드라이버 출력 형식 오류", "hint": str(res)[-150:]}
    return res


def _go_hard(res, k, throttle=False, budget=False):
    """강한 사용량 제한 — 이 프로세스의 다음 일시 오류는 쉬지 않고 바로 hard, 다른 프로세스도 알게 기록(copilot_auto.note_throttle).
    결과에 hard=True — explain_failure 가 fatal 로 보고 호출자(judge·refine·agentic·flow·narrate)가 남은 묶음을 보내지 않는다.
    throttle=True(LM28 — 사용량 제한 「요청이 너무 많음」으로 멈춤)면 실행 표식(LM_RUN_ID)·갈래 'throttle' 도 적는다 — 같은 실행의
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
              "여기까지의 결과를 지킵니다(1~2시간 뒤 [재분석만])", flush=True)
    elif first:
        print("        " + (f"Copilot 이 {k}번 쉬고 다시 보내도 막혔습니다" if k else "Copilot 이 여전히 막혀 있습니다")
              + "(강한 사용량 제한) — 남은 묶음은 보내지 않고 여기까지의 결과를 지킵니다(1~2시간 뒤 [재분석만])",
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
    사본이 쌓였다) — 실패한 왕복(왕복 자체 실패, 답에 JSON 꼴이 없음)의 것만 남겨 '직접 붙여넣기' 안내에 쓴다.
    답은 왔지만 호출자가 해석하지 못한 경우는 note_bad_reply() 가 방금 지운 파일을 되살린다.
    LM28: 먼저 G3 최종 검사(g3_prompt) — 걸리면 파일도 쓰지 않고(직접 붙여넣기 안내 대상이 아니다) {"phase":"blocked"} 를
    돌려준다. 호출자는 그 묶음을 skipped 로 세고 그 행만 규칙으로 둔다(재시도·새 채팅 전환 없음).
    config.copilotAuto.inProcess(기본 true)면 같은 프로세스에서 왕복(_transport → copilot_auto.send_inproc).
    LM28 진단 A — 일시 오류·사용량 제한(_is_transient)이면 바로 다시 보내지 않고 COOLDOWN_SEC(1·2·2분)만큼 쉬었다가 페이지를
    새로 고치고 새 채팅에서 같은 프롬프트를 다시 보낸다(결과의 cooldowns = 쉬고 다시 보낸 횟수 — 호출자는 또 쉬지 않는다).
    두 번 쉬고도 막히면 이 프로세스의 남은 왕복은 config.copilotAuto.fallbackModel(기본 '자동', 빈 값이면 끔)로 보낸다.
    세 번 쉬고도 막히면 결과에 hard=True(강한 제한 — explain_failure 가 fatal 로 본다)를 달고, 이 프로세스의 다음 일시 오류는
    쉬지 않고 바로 hard 다. 쉬는 시간은 전체 마감(LM_AI_DEADLINE − 2분)·프로세스 합계 5분·이번 실행의 합계(모든 단계 —
    copilotAuto.runWaitMaxSec, 기본 5분) 안. 실행 합계를 다 쓰면 다음 일시 오류·사용량 제한은 쉬지 않고 바로 hard(_go_hard budget=True ·
    사용량 제한이면 실행 표식도). 다른 프로세스가 5분 안에 남긴 강한 제한 기록이 있으면 첫 왕복 전에 남은 시간만 한 번 쉰다(실행 합계 안).
    chatTurns 회전(새 채팅)마다 페이지도 새로 고친다.
    LM28 — 사용량 제한(phase 'throttled' · 「요청이 너무 많음」)은 위 사다리 대신 copilotAuto.throttleWaitSec(기본 2분, 0 = 쉬지 않음)
    만큼 **한 번** 쉬고 새로 고쳐 다시 보낸다. 그래도 막히면 hard + 실행 표식 기록(_go_hard throttle=True) — 같은 실행(LM_RUN_ID)의
    다음 copilot_send 는 이 프로세스든 뒤 단계 프로세스든 보내지 않고(남은 시간 쉬기도 없이) 바로 hard 'throttled'(_run_stop_result).
    다른 일시 오류(무응답·빈 답·오류 문구·시간 초과 …)는 사다리(1·2·2분)를 탄다.
    LM28 — 느린 긴 답(결과 slow — 드라이버가 왕복 예산 끝에 받은 데까지 돌려준 ok+cut)은 쉬기·다시 보내기 사다리를 타지 않는다
    (_is_transient). 정제·Agentic·워크플로우의 첫 왕복(RESUME_NAMES)은 앞 단계의 우리 채팅을 이어 쓸 수 있다(드라이버 RESUME)."""
    if _run_stopped():
        return _run_stop_result()            # 이번 실행은 사용량 제한으로 멈췄다 — 프롬프트 파일도 쓰지 않는다(보내지 않았다)
    if not g3_prompt(prompt_text):
        return {"ok": False, "status": "blocked", "phase": "blocked", "reason": "R-GATE",
                "error": "개인정보 관문(G3) — 고위험 잔여·카나리아가 있어 보내지 않음",
                "hint": "이 묶음은 PC 자료(규칙)로 처리합니다 — 재시도하지 않습니다"}
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
        _ROTATIONS[0] += 1                       # LM30 — 회전은 그대로 두되 센다(판정 기록 rotations · 구조 줄)
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
            # LM30 — 실패한 왕복이 답 글을 남기지 않았다(무응답·빈 답): 새 채팅을 열지 않고 같은 대화를 그 자리에서 새로 고쳐 다시 보낸다
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
        print("        ※ LM_COPILOT_STUB 스텁 응답 — 테스트 전용, 실제 Copilot 판정이 아닙니다")
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
        # 않게, 그리고 상태 파일이 없는 단계의 감시기(stdout 침묵 한도)가 정상 왕복을 끊지 않게.
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
        # LM_STAGE — 드라이버가 report\copilot_trace.jsonl 에 '어느 단계의 왕복인지' 를 남기게 한다.
        # 이름만 넘긴다(chunk3·narr_2026-06·wf1 …). 프롬프트 원문은 계측에 들어가지 않는다.
        # 왕복은 최장 roundtrip_timeout(기본 27분 × 조각 수)이다. 예전에는 그 동안 **출력이 한 줄도 없어**
        # 화면이 멈춘 것으로 보였다(제보 '무한 정지'). 이제 1분마다 경과를 찍는다.
        _p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                                 LM_STAGE=str(name or "")[:40]),
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


# ── [0] 엔티티 체계 수립 — 지정 프로젝트는 항상 포함, 나머지는 raw에서 자동 발견 ──
def _sample_lines(rows, k, fmt):
    """rows 전체에 고르게 퍼진 k개 표본 줄 — **끝(마지막 행)을 반드시 포함한다**.

    예전에는 rows[::step][:k] 였는데, step = len//k 가 1로 굳는 구간(k < N < 2k)에서는
    그냥 '앞 k개' 가 되어 뒤쪽이 통째로 빠졌다. 월별 리뷰에서 이게 특히 나빴다 — 신호 90건 상한에
    한 달 150건이면 6월 17일에서 끊겨, 모델은 6월 후반 근거를 못 받은 채 '6월 한 달' 을 쓰라는
    지시를 받는다. 그러면 없는 이야기로 공백을 메운다(제보: 과거 달에 하지도 않은 최근 일).
    실측 커버리지: N=120 75% · N=150 60% · N=179 50%. 아래 식은 어느 N 에서도 처음과 끝을 담는다."""
    if not rows or k <= 0:
        return []
    n = len(rows)
    if n <= k:
        return [fmt(r) for r in rows]
    idx = sorted({round(j * (n - 1) / (k - 1)) for j in range(k)}) if k > 1 else [n - 1]
    return [fmt(rows[i]) for i in idx]


def _fit_samples(rows, k, fmt, head_len, budget=PROMPT_BUDGET, k_min=20):
    """표본 수를 예산에 맞춘다 — 머리말 + 표본이 budget 을 넘으면 표본을 고르게 줄인다(k_min 까지).
    taxonomy(100줄)·narrative(90줄)는 실규모(제목 80~95자)에서 9,500~10,100자로 한도를 넘겨 드라이버가
    2조각으로 나눠 보냈다(실측) — '전체를 한 번에' 프롬프트에도 예산이 있어야 한다."""
    samples = _sample_lines(rows, k, fmt)
    while len(samples) > k_min and head_len + sum(len(s) + 1 for s in samples) > budget:
        k = max(k_min, int(k * 0.85))
        samples = _sample_lines(rows, k, fmt)
    return samples


# 체계·통합 표본의 팀즈 줄 상한(LM30 2026-10-27) — 팀즈 웹 읽기가 켜지면 표본 대부분이 채팅이 되고, 채팅 줄은 대개 과제 이름이 없어
# 체계가 거칠어졌다(합성 실측: 표본 54줄 중 채팅 37줄, 그중 과제 이름이 있는 줄 7). 다른 출처가 CHAT_CAP_MIN_OTHER 줄 미만이면 그대로.
CHAT_SAMPLE_SHARE = 0.4
CHAT_CAP_MIN_OTHER = 10


def _even_idx(n, k):
    """0..n-1 에서 고르게 퍼진 k 개 번호(끝 포함) — _sample_lines 와 같은 식."""
    if k <= 0 or n <= 0:
        return []
    if k >= n:
        return list(range(n))
    return sorted({round(j * (n - 1) / (k - 1)) for j in range(k)}) if k > 1 else [n - 1]


def _cap_chat(rows, share=CHAT_SAMPLE_SHARE, min_other=CHAT_CAP_MIN_OTHER):
    """표본 후보에서 팀즈 줄을 고르게 솎아 share 이하로 → (행 목록, 상한을 걸었나). 다른 출처가 min_other 줄 미만이면 그대로 둔다
    (채팅밖에 없는 사람의 표본을 비우지 않게)."""
    rows = list(rows or [])
    chat = [i for i, r in enumerate(rows) if _fam(r) == "팀즈"]
    other = len(rows) - len(chat)
    if not chat or other < min_other:
        return rows, False
    allow = int(other * share / (1.0 - share) + 1e-9)
    if len(chat) <= allow:
        return rows, True
    keep = {chat[j] for j in _even_idx(len(chat), allow)}
    return [r for i, r in enumerate(rows) if _fam(r) != "팀즈" or i in keep], True


def _trim_chat(pick, share):
    """고른 표본에서 팀즈 줄이 share 를 넘으면 넘는 만큼 고르게 뺀다(다른 줄은 그대로)."""
    chat = [i for i, r in enumerate(pick) if _fam(r) == "팀즈"]
    allow = int((len(pick) - len(chat)) * share / (1.0 - share) + 1e-9)
    if len(chat) <= allow:
        return pick
    keep = {chat[j] for j in _even_idx(len(chat), allow)}
    return [r for i, r in enumerate(pick) if _fam(r) != "팀즈" or i in keep]


def _fit_rows(rows, k, fmt, head_len, budget=PROMPT_BUDGET, k_min=20, share=None):
    """_fit_samples 의 행 판 — 고르게 퍼진 k 행을 고르고(share 를 주면 팀즈 줄을 그 몫까지만) 머리말 + 표본이 budget 을 넘으면
    표본을 고르게 줄인다(k_min 까지) → 줄 목록."""
    while True:
        pick = _sample_lines(rows, k, lambda r: r)
        if share is not None:
            pick = _trim_chat(pick, share)
        lines = [fmt(r) for r in pick]
        if k <= k_min or len(lines) <= k_min or head_len + sum(len(s) + 1 for s in lines) <= budget:
            return lines
        k = max(k_min, int(k * 0.85))


# l1(상위) 예시 값은 details.L1_META 에서 꺼낸다 — 상위 이름을 details 밖에 하드코딩하지 않는다(tools/check_l1.py)
TAXONOMY_EXAMPLE = json.dumps(
    {"models": [{"name": "프로젝트A", "match": ["proja"], "obs": "근거가 된 raw 조각", "product": "제품X",
                 "l1": next(iter(details.L1_META))},
                {"name": "공통", "match": [], "product": "공통", "l1": details.snap1("공통")}]},
    ensure_ascii=False, separators=(",", ":"))
CONSOLIDATE_EXAMPLE = '{"models":[{"name":"대표이름","match":["키워드"],"merged":["흡수된이름"]},{"name":"공통","match":[]}]}'


def taxonomy_prompt(rows, hints, pinned=()):
    # 팀즈 줄은 표본의 40% 까지(LM30 2026-10-27) — 전체에서 먼저 솎은 뒤 표본을 고른다
    rows, capped = _cap_chat(rows)
    # G3 — 표본 후보(고르게 퍼진 200행)만 관문에 통과시킨 사본에서 고른다(광고·고위험 잔여·카나리아 행 제외, 재정제)
    rows = g3_pick(rows, 100)

    def fmt(r):
        return f"- [{r['source']}] {who_label(r.get('who'), 12)} {(r.get('text') or '')[:80]}"
    lines = [
        "당신은 업무 로드율 분석의 설계자입니다. 아래는 한 엔지니어의 PC에서 수집한 raw 신호 표본입니다.",
        "이 사람의 업무 세계를 두 축의 엔티티 체계로 설계하세요.",
        "",
        "1. models = 상위 '과제' 목록  ← JSON 키는 models 로 유지 — 제품·과제·고객사 단위의 최상위 개체.",
        "   ★ raw 표본에서 실제로 관찰되는 것만 넣는다. 힌트 목록에 있어도 raw에 흔적이 없으면",
        "     제외하고, 힌트에 없어도 raw에서 상위 과제로 보이면 반드시 추가한다.",
        "   match 에는 그 과제를 식별할 소문자 키워드들, obs 에는 근거가 된 raw 한 조각.",
        "   같은 개체의 표기 변형(대소문자·축약·한/영)은 대표 이름 하나로 통일한다.",
        "   파일명 접두어(img·scan·doc)·확장자·날짜 같은 잡음 토큰은 과제가 아니다.",
        "   프로젝트가 아닌 것(공통 사무·팀 운영·사내 시스템)은 '공통' 하나로 묶는다.",
        "   ★ 계층 규율: models 는 **상위개체**(프로젝트·제품·과제코드)만. 'OO 설계'·",
        "     'OO 보고서 작성'·'OO 우선순위 수립' 같은 **중위 업무**(동사형 산출 활동)는",
        "     과제가 아니다 — 그 업무가 속한 상위 프로젝트를 과제로 세우고, 업무 자체는",
        "     신호 판정의 세부업무 축으로 내린다. 상위가 불분명하면 '공통' 소속.",
        "     코드 모듈·파일명 조각(run·check·mine·txt 같은 소문자 단어)도 과제가 아니다 —",
        "     그것들이 속한 **하나의 도구/제품 이름**으로 통합하라 (예: 여러 .py 모듈 작업",
        "     → 그 도구 이름 하나). 같은 산출물의 부품들을 과제로 쪼개면 로드가 흩어진다.",
        "   ★ 사람 이름·호칭(○○ 책임/님)·부서명·채팅방 이름, 근태·인사·발령·공지·교육 안내·설문 같은 사내 행정은",
        "     과제가 아니다 — models 에 넣지 말 것(행정은 '공통').",
        "   product = 그 과제가 속한 **실제 제품·제품군·과제코드** (raw 에서 식별될 때만).",
        "   내부 공통업무·행정이면 product 를 '공통' 으로. 못 정하겠으면 생략.",
        "   l1 = 그 과제의 업무 성격(상위) — 아래 중 택1:",
        *details.l1_def_lines("     "),
        "2. worktypes = 업무유형 4종 고정: 개발 / 사무 / 현장 / 협업",
        "",
        "출력은 JSON 하나만(설명·표·코드블록 없이). obs 는 40자 이내:",
        TAXONOMY_EXAMPLE,
        "",
    ]
    if pinned:
        lines.append("· 사용자 지정 과제 — 이 표기 그대로 **반드시 models 에 포함**하고,")
        lines.append("  raw에서 이들에 속하는 흔적의 식별 키워드를 match 에 보강할 것:")
        for p in pinned:
            d = f" — {p['desc'][:60]}" if p.get("desc") else ""
            k = f" (키워드: {', '.join(p.get('match') or [])})" if p.get("match") else ""
            lines.append(f"    · {p['name']}{d}{k}")
    if hints:
        lines.append("· 힌트(지난 분석에서 발견 등): " + ", ".join(hints[:25])
                     + " — 참고만 하고, 채택 여부는 raw 관찰로 판단할 것")
    lines += ["", "[raw 표본]"]
    head_len = sum(len(x) + 1 for x in lines)
    return "\n".join(lines + _fit_rows(rows, 100, fmt, head_len, share=(CHAT_SAMPLE_SHARE if capped else None)))


def consolidate_prompt(models, rows):
    """초안 과제 목록에서 '같은 실체가 다른 이름으로 갈린 것'을 통합하도록 한 번 더 묻는다.
    같은 raw 라도 실행마다 체계가 흔들려(예: 'AX' 와 'Agentic AI' 가 분리) 로드 배분이
    달라지던 문제(9d) 완화 — 왕복 1회를 더 쓰는 대신 실행 간 일관성을 얻는다.
    LM30(2026-10-27): 표기 변형만 합친다 — 예전 '상위/하위 관계면 합친다' 가 한 제품의 다른 갈래(시험·인증 등)를 한 과제로 묶었다."""
    names = [m["name"] for m in models]
    lines = [
        "아래는 한 엔지니어의 업무를 분류하기 위해 초안으로 뽑은 '상위 과제(제품·프로젝트)' 목록입니다.",
        "같은 실체가 다른 이름으로 갈린 것을 하나로 합쳐 최종 목록을 만들어 주세요.",
        "",
        "· 같은 과제의 표기 변형(띄어쓰기·대소문자·한/영 표기·약어와 풀어 쓴 이름)만 합친다 (대표 이름 하나 선택).",
        "· 같은 제품·고객사라도 일의 갈래가 다르고 raw 에서 따로 불리면 합치지 않는다.",
        "· 서로 다른 제품·과제는 합치지 않는다.",
        "· 프로젝트가 아닌 공통 사무·팀 운영은 '공통' 하나로.",
        "· merged 에는 그 이름으로 흡수된 초안 이름들을 적는다.",
        "",
        "출력은 JSON 하나만(설명·표·코드블록 없이):",
        CONSOLIDATE_EXAMPLE,
        "",
        "[초안 목록] " + ", ".join(names)[:1500],
        "",
        "[raw 표본]"]
    head_len = sum(len(x) + 1 for x in lines)
    rows, capped = _cap_chat(rows)             # 팀즈 줄은 표본의 40% 까지(LM30 2026-10-27)
    rows = g3_pick(rows, 40)                   # G3 — 표본은 관문을 통과한 사본에서
    return "\n".join(lines + _fit_rows(rows, 40, lambda r: f"- {(r.get('text') or '')[:70]}", head_len,
                                       share=(CHAT_SAMPLE_SHARE if capped else None)))


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
    draft(통합 전 초안 — taxonomy 결과): 대표에 product·l1 이 없으면 같은 이름 또는 merged 이름의 초안 값을 옮긴다.
    consolidate 응답 형식에는 product·l1 이 없어, 통합을 거치면 taxonomy 가 판정한 제품·상위가 사라졌다(진단 B)."""
    by = {}
    for d in draft or ():
        if isinstance(d, dict) and d.get("name"):
            by.setdefault(ukey2(d["name"]), d)
    out = []
    for m in models:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        mm = dict(m)
        mm["match"] = list(dict.fromkeys(
            [str(k).lower() for k in _as_list(m.get("match"))]
            + [str(k).lower() for k in _as_list(m.get("merged"))]))
        for key in ("product", "l1"):
            if mm.get(key):
                continue
            for nm in [m["name"]] + [str(x) for x in _as_list(m.get("merged"))]:
                v = (by.get(ukey2(nm)) or {}).get(key)
                if v:
                    mm[key] = v
                    break
        out.append(mm)
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
        for key in ("product", "l1"):
            if src.get(key):
                e[key] = src[key]
        out.append(e)
    return out + [{"name": "공통", "match": [], "obs": "규칙 폴백"}]


# 파일명 접두어·범용 토큰은 과제가 아니다 — 프롬프트 지시만으로는 새는 것이
# 실측 확인돼 코드에서도 걸러낸다 (entities 힌트 순환 오염 방지)
NOISE_MODEL = re.compile(
    r"^(img|image|scan|doc|docs|file|files|tmp|temp|misc|etc|기타|잡음|미지정|none|n/a)\d*$", re.I)


def _clean_product(v):
    """taxonomy 가 판정한 product — 문자열로 정규화, 길이 상한."""
    s = str(v or "").strip()
    return s[:40]


def sanitize_models(models, people=()):
    """taxonomy·discovered 결과에서 잡음 이름 제거 + 대소문자 중복 통합, '공통' 보장.
    pinned(사용자 지정)는 잡음 필터를 우회한다 — 사용자가 명시한 이름은 코드가 지우지 않는다.
    LM28(진단 B): 상투어·버전(규칙 과제명 잡음)·사람 이름(people = details.person_keys 키)·공지류(근태공지·인사발령 …)도
    과제가 아니다 — 이 관문이 taxonomy·지난 체계·폴백·발견 모든 경로에 걸린다. l1(상위)은 product 처럼 남기되 고정 범주로 스냅."""
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
            if m.get("product") is not None:
                m["product"] = _clean_product(m.get("product"))
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
    n = str(name or "").strip()
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


# 회의 안건(LM28 — 일정 본문을 core\meetnote 가 정제한 것). 회의 줄 끝에만 붙고, 머리말 안내 한 줄은 안건이 든 묶음에만 넣는다.
NOTE_SEP = " — 안건: "
NOTE_HINT = "· 회의 줄 끝의 '— 안건:' 은 그 일정 본문을 정제·요약한 것입니다 — 과제·세부업무를 고르는 참고로만 쓰세요."
NOTE_KEY_SEP = "|안건:"     # 판정 캐시 내용 키에 안건을 넣는 구분자 — 안건이 생기거나 바뀐 회의만 한 번 다시 판정한다


def row_line(r, idx):
    line = (f"#{idx} | {r['time'][:16]} | {r['source']} | "
            f"{who_label(r.get('who'), 16) or '-'} | {(r.get('text') or '')[:95]}")
    nt = " ".join(str(r.get("note") or "").split())
    return line + NOTE_SEP + nt if nt and _fam(r) == "회의" else line


def judge_prompt(chunk, start, models, first=True, seen_details=(), idxs=None):
    """청크 프롬프트 — 항상 머리말(기준·과제 목록·출력 형식)을 포함한다(first 는 호환용, 무시).
    예전 '계속입니다' 이어짐 프롬프트는 같은 채팅의 문맥에 기댔는데, 드라이버의 재시도 사다리가 새 채팅을
    열면 기준 없는 빈 채팅에 떨어져 답이 엉켰다. 머리말은 ~800자라 40행 청크도 예산(8,400) 안이다.
    idxs: 행의 절대 번호 목록(적응 분할 재시도처럼 연속이 아닐 때) — 없으면 start 부터 연속.
    응답 줄이기: 비업무는 [번호,"n"] 두 칸만, 세부업무는 짧은 명사구(글자 수 제한은 두지 않는다 — LM20 과 같다)."""
    head = [
        "당신은 업무 로드율 분석의 판정자입니다. 각 raw 신호를 직접 읽고 판정하세요.",
        "",
        "판정 형식: [번호, \"y\"|\"n\", \"과제\", \"유형\", \"세부업무\"] — 비업무(n)는 [번호,\"n\"] 두 칸만.",
        "· y/n : 업무 여부. 공지·알림(행정·교육·윤리·인사 시스템의 자동 알림·뉴스레터·시스템 발송),",
        "  광고·프로모션, 개인 용무, 의미 없는 잡음은 n. 과감하게 걸러낼 것.",
        "· 과제 : 아래 목록에서 고르되 목록의 표기를 그대로 쓴다(변형 금지). 목록에 없어도",
        "  원문에 상위 과제·제품명이 분명히 보이면 그 이름을 새로 쓴다(새 과제 발견) —",
        "  단, 이미 목록에 같은 개체의 다른 표기가 있으면 그 표기를 쓴다. 어느 쪽도 아니면 \"공통\".",
        "   → " + ", ".join(
            m["name"] + (f"({str(m.get('desc'))[:30]})" if m.get("desc") else "") for m in models),
        # LM30(2026-10-27) — 예전 '그 사람과 한 일이 속한 과제' 는 과제가 상대를 따라간다는 뜻으로 읽혔다(한 사람과 여러 일을 한다)
        "  ★ 사람 이름·호칭·부서·채팅방 이름은 과제가 아니다 — 그 줄의 내용이 가리키는 과제 — 같은 상대·같은 대화방이라도"
        " 줄마다 다를 수 있습니다. 모르면 \"공통\".",
        "  ★ 이 묶음의 줄만 보고 판정하세요 — 앞 묶음에서는 과제·세부업무 표기만 이어 쓰세요.",
        "  ★ 근태·인사·발령·공지·교육 안내는 과제가 아니다 — 단순 공지는 n, 내가 처리한 행정이면 \"공통\".",
        "· 유형 : 개발 / 사무 / 현장 / 협업 중 하나",
        "· 세부업무 : 짧은 명사구 — 같은 일은 같은 이름으로 (예: '설계 검토', '부품 발주',",
        "   '시험 결과 정리', '고객 대응', '주간보고'). 조사 붙은 조각('보고의' 등) 금지.",
    ]
    if any(str(r.get("note") or "").strip() and _fam(r) == "회의" for r in chunk):
        head.append(NOTE_HINT)
    if seen_details:
        head += ["★ 앞선 청크에서 이미 쓴 세부업무 이름 — 같은 일이면 새 이름을 만들지 말고 이 표기를",
                 "  그대로 재사용할 것(이름이 갈리면 로드율이 쪼개집니다):",
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


def signal_sig(r):
    """신호 행의 내용 신원 — '이어서 판정' 의 키. 행 인덱스는 mine 재추출마다 흔들리지만
    (시각|출처|원문 머리) 는 같은 사건이면 같다. agentic.row_sig 와 같은 사상(내용 기반 재개)."""
    return (f"{(r.get('time') or '')[:16]}|{(r.get('source') or '')[:12]}|"
            f"{' '.join((r.get('text') or '').split())[:120]}")


# ── 이어서 판정 캐시(LM28 진단 A) — report\judge_cache.json ─────────────────────────────
# 예전 재개는 같은 기간 tag 의 ai_judgments 에서만 판정을 회수했다. 기본 기간('올해')은 tag 가 날마다 바뀌어 매일 1월부터 다시
# 물었고(수천 행 × 왕복), 메일 라벨이 메일(수신)↔메일(수신전용)으로 바뀌면 같은 tag 안에서도 어긋났다.
# 캐시는 기간과 무관하게 내용 키(signal_sig2 의 sha1)로 판정만 남긴다 — 신호 원문은 남기지 않는다.
def signal_sig2(r):
    """'이어서 판정' 키 v2 — 시각(분)|출처 계열(괄호 앞)|원문 머리 120자. 라벨(메일(수신)/메일(수신전용))이 바뀌어도 같다."""
    return (f"{(r.get('time') or '')[:16]}|{str(r.get('source') or '').split('(')[0]}|"
            f"{' '.join((r.get('text') or '').split())[:120]}")


def _ckey(sig2):
    """캐시 키 — sig2 의 sha1 앞 20자(캐시 파일에 신호 원문이 남지 않는다)."""
    return hashlib.sha1(str(sig2 or "").encode("utf-8")).hexdigest()[:20]


def _sig2_from_legacy(sig):
    """v1 키(signal_sig — 출처 라벨 12자) → v2 키(출처 계열)."""
    t, s, x = (str(sig or "").split("|", 2) + ["", ""])[:3]
    return f"{t}|{s.split('(')[0]}|{x}"


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


def load_judge_cache(rep):
    r"""report\judge_cache.json → {"v": 파일의 판(없으면 1), "since": 캐시 시작 시각(epoch), "migrated": 옛 기록을 이미 옮겼나,
    "items": {키: {"w","m","t","d","at"}}}. 없거나 깨졌으면 빈 캐시(since 0·migrated False — 옛 판정 기록
    ai_judgments_*.json 을 한 번 이어받는다). v2(LM30 2026-10-27)부터 짧은 팀즈 대화의 판정은 쓰지 않는다 — 판과 무관하게
    main 이 그 줄의 항목을 건너뛰고 지운다(v1 의 같은 문장 묶음이 다른 방·다른 과제에서 옮겨 놓은 판정)."""
    try:
        with open(os.path.join(rep, JUDGE_CACHE), encoding="utf-8-sig") as f:
            o = json.load(f)
        if isinstance(o, dict) and isinstance(o.get("items"), dict):
            try:
                v = int(o.get("v") or 1)
            except (TypeError, ValueError):
                v = 1
            return {"v": v, "since": float(o.get("since") or 0), "migrated": bool(o.get("migrated")),
                    "items": o["items"]}
    except (OSError, ValueError, TypeError):
        pass
    return {"v": JUDGE_CACHE_V, "since": 0.0, "migrated": False, "items": {}}


def save_judge_cache(rep, cache, d0, prune=True):
    """판정 캐시 저장(원자 교체). prune: 분석 시작일(d0) − CACHE_KEEP_DAYS 보다 앞서 마지막으로 쓴 판정을 빼고, CACHE_MAX 를
    넘으면 오래 쓰지 않은 것부터 뺀다(묶음마다 하는 중간 저장은 prune=False). returns 저장했으면 True."""
    items = cache.setdefault("items", {})

    def _at(v):
        return str(v.get("at") or "") if isinstance(v, dict) else ""
    if prune:
        try:
            cut = (date.fromisoformat(str(d0)[:10]) - timedelta(days=CACHE_KEEP_DAYS)).isoformat()
        except ValueError:
            cut = ""
        if cut:
            for k in [k for k, v in items.items() if _at(v) < cut]:
                del items[k]
        if len(items) > CACHE_MAX:
            for k, _v in sorted(items.items(), key=lambda kv: _at(kv[1]))[:len(items) - CACHE_MAX]:
                del items[k]
    # migrated — 이 캐시가 저장된 뒤로는 판정마다 캐시에 남으므로 옛 판정 기록(ai_judgments_*.json)을 다시 읽지 않는다
    return _write_json_atomic(os.path.join(rep, JUDGE_CACHE),
                              {"v": JUDGE_CACHE_V, "since": cache.get("since") or 0, "migrated": True, "items": items})


def _legacy_judgments(rep, tag, since=0.0, limit=LEGACY_JUDGMENT_FILES):
    r"""캐시 이전 판의 판정 기록 → {캐시 키: 판정 항목}. report\ai_judgments_<tag>.json(이 기간)을 먼저, 그다음 다른 기간
    파일을 최신 수정 순으로 limit 개. 캐시가 '처음부터 판정'(--redo)으로 다시 시작된 시각(since)보다 오래된 파일은 읽지 않는다."""
    import glob

    def _mt(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0
    own = os.path.join(rep, f"ai_judgments_{tag}.json")
    _own_n = os.path.normcase(os.path.abspath(own))
    others = sorted((p for p in glob.glob(os.path.join(rep, "ai_judgments_*.json"))
                     if os.path.normcase(os.path.abspath(p)) != _own_n), key=_mt, reverse=True)[:limit]
    out = {}
    for p in [own] + others:
        if not os.path.isfile(p) or _mt(p) < float(since or 0):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                items = json.load(f).get("items") or {}
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        for v in (items.values() if isinstance(items, dict) else ()):
            if isinstance(v, dict) and v.get("sig") and "work" in v:
                out.setdefault(_ckey(_sig2_from_legacy(v["sig"])), v)
    return out


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


# ── 같은 내용 묶음·짧은 대화(LM28 진단 A) ──────────────────────────────────────────────
# 예전에는 스레드의 메일마다·팀즈 메시지마다 한 줄씩 보냈다(수천 행 → 왕복 수백 회 · 판정 예산 120분의 몇 배).
# 같은 내용(같은 계열·같은 앞 95자 — Copilot 이 보는 줄이 같다)은 대표 한 줄만 보내고 그 판정을 묶음 전체에 쓴다.
_GK_PREFIX = re.compile(r"^\s*((re|fw|fwd|답장|전달|회신|답변)\s*[:：]\s*)+", re.I)
_ACK_RX = re.compile(
    r"^(네+|넵+|예+|넹|응|ㅇㅇ|ㅇㅋ|오케이|ok(ay)?|감사(합니다|해요|드립니다)?|고맙습니다|확인(했습니다|했어요|완료)?|알겠습니다"
    r"|수고(하셨습니다|하세요)?|좋(습니다|아요)|ㅎ+|ㅋ+|ㅠ+|thanks?|thx|got it|noted)[\s.!~^]*$", re.I)
_MASK_TOKEN = re.compile(r"\[[^\]]{0,40}\]")       # 개인정보 가림 토큰([사람]·[전화] …)


def _fam(r):
    """출처 계열 — '메일(수신)' → '메일'."""
    return str((r or {}).get("source") or "").split("(")[0]


def _conv(r):
    """팀즈 줄의 대화 키(signals conv 열 — 대화방 이름의 소금 친 키, LM30 2026-10-27) · 팀즈가 아니거나 방을 모르면 ""."""
    return str((r or {}).get("conv") or "").strip() if _fam(r) == "팀즈" else ""


def _substantive(text):
    """업무를 가리킬 낱말이 하나라도 있는가 — extract._tokens 중 상투어·버전·날짜가 아닌 것(rule_name_ok)."""
    try:
        from extract import _tokens, rule_name_ok
    except ImportError:
        return bool(str(text or "").strip())
    return any(rule_name_ok(t) for t in _tokens(text))


def _has_content(text):
    """일을 가리키는 낱말이 있는가(LM30 2026-10-27) — extract.content_words: 상투어·버전·날짜에 더해 대화 낱말(맞장구·인사·호칭·
    시각·흔한 소통 낱말·'…습니다/…요/…까/…드린' 꼴)도 뺀다. extract 가 없으면 예전 _substantive."""
    try:
        from extract import content_words
    except ImportError:
        return _substantive(text)
    return bool(content_words(text))


def group_key(r):
    """같은 내용 묶음 키 → (계열, 정규화한 원문 앞 95자) 또는 None(혼자 보낸다).
    메일·회의는 RE/FW/회신 머리를 떼고, 파일은 규모 꼬리(' 외 N건' 등)를 뗀 뒤 소문자·앞뒤 구두점 정리. 숫자는 남긴다
    ('설계 검토 1' 과 '설계 검토 2' 는 다른 일). 커밋·수동기록, 6자 미만, 업무 낱말이 하나도 없는 원문은 묶지 않는다.
    팀즈(LM30 2026-10-27)는 같은 대화(conv)·같은 날 안에서만 묶는다 — 키에 대화 키와 날짜가 들어간다. 대화방을 모르는 팀즈 줄은
    묶지 않는다(예전에는 '자료 보내드렸습니다' 같은 줄이 방·사람·과제를 넘어 한 판정을 나눠 가졌다)."""
    fam = _fam(r)
    if fam in ("커밋", "수동기록"):
        return None
    t = " ".join(str(r.get("text") or "").split())
    if fam in ("메일", "회의"):
        t = _GK_PREFIX.sub("", t)
    elif fam == "파일":
        try:
            from extract import _SIG_SUFFIX_RE
            t = _SIG_SUFFIX_RE.sub("", t)
        except ImportError:
            pass
    t = t.lower().strip(" .-_~!?")
    if len(t) < 6 or not _substantive(t):
        return None
    if fam == "팀즈":
        cv = _conv(r)
        if not cv:
            return None
        return fam, f"{cv}|{str(r.get('time') or '')[:10]}|{t[:GROUP_KEY_CHARS]}"
    return fam, t[:GROUP_KEY_CHARS]


def is_lowinfo(r):
    """짧은 팀즈 대화인가 — Copilot 에 보내지 않고 같은 대화의 판정으로 채운다(실패가 아니다).
    가림 토큰·구두점을 뺀 글이 6자 미만이거나, 맞장구 정형이거나, 일을 가리키는 낱말이 하나도 없으면(_has_content).
    LM30(2026-10-27): '네 확인했습니다'·'자료 보내드렸습니다'·'[사람] 책임님 확인 부탁드립니다'·'오후에 잠깐 통화 가능하실까요' 처럼
    맞장구·호칭·시각·문장 끝 꼴뿐인 줄도 짧은 대화다 — 예전에는 이런 줄이 '업무 낱말 있음' 으로 같은 문장 묶음이 되어 방·사람·과제를
    넘어 한 판정을 나눠 가졌다. 판정 캐시 v2 는 이런 줄의 지난 판정을 쓰지 않는다."""
    if _fam(r) != "팀즈":
        return False
    t = " ".join(str(r.get("text") or "").split())
    core = re.sub(r"[\W_]+", "", _MASK_TOKEN.sub(" ", t))
    return len(core) < 6 or bool(_ACK_RX.match(t)) or not _has_content(t)


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


def recent_details(judged, prev_idxs=()):
    """청크에 동봉할 '앞서 쓴 세부업무 이름' — 직전 청크가 쓴 이름(빈도순)을 먼저, 그 다음 전체 빈도순.
    예전에는 전체를 가나다순으로 잘라 30개를 보냈다 — 이름이 200개면 'ㄱ~ㄴ' 만 가고 정작 직전
    청크의 이름은 빠져 청크마다 새 이름이 생겼다. 30개·600자 상한."""
    prev = Counter(judged[i]["detail"] for i in prev_idxs
                   if i in judged and judged[i].get("work") and judged[i].get("detail"))
    allc = Counter(j["detail"] for j in judged.values() if j.get("work") and j.get("detail"))
    out, size = [], 0
    for name, _ in list(prev.most_common()) + list(allc.most_common()):
        if name in out:
            continue
        if len(out) >= SEEN_MAX_NAMES or size + len(name) + 3 > SEEN_MAX_CHARS:
            break
        out.append(name)
        size += len(name) + 3
    return out


def meeting_notes(rows, cfg, d0, d1, data_dir=None):
    r"""회의 신호 행 번호 → 안건(LM28 — 사용자 요청 '일정 회의 내용도 참고하되 걸러서').
    core\meetnote.load_notes 가 data\outlook\calendar.csv(+추가PC)의 일정 본문을 정제·필터하고, 회의 행(출처 '회의')과는
    (날짜, 시작 HH:MM, 정제 제목) 으로만 맞댄다 — 회의가 아닌 행에는 붙지 않는다. 붙이기 전에 안건만 G3 관문(g3_rows)에 먼저
    넣어 통과한 것만 쓴다: 안건 때문에 행 관문이 회의 행을 통째로 규칙 판정으로 돌리지 않게(안건만 빠지고 회의는 그대로 간다).
    config.calendar.bodyToAI=false·본문 없음·읽기 실패면 {}. 출력은 건수만(안건·제목 원문 없음)."""
    try:
        import meetnote
    except ImportError:
        return {}
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
        nt = book.get(meetnote.note_key(rows[i].get("time"), rows[i].get("text")))
        if nt:
            cand[i] = nt
    if not cand:
        print(f"[judge] 회의 안건 {len(book)}건이 있지만 같은 시각·제목의 회의 신호가 없어 붙이지 않습니다")
        return {}
    kept, _why = g3_rows([{"text": nt, "_gi": i} for i, nt in cand.items()], ("text",))
    out = {it["_gi"]: it["text"] for it in kept if str(it.get("text") or "").strip()}
    print(f"[judge] 회의 안건(일정 본문 정제) {len(out)}건을 회의 판정의 참고로 붙입니다"
          + (f" · 개인정보 관문에서 뺀 안건 {len(cand) - len(out)}건" if len(cand) > len(out) else "")
          + f" · 거른 뒤 남은 일정 안건 {len(book)}건")
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
    # 회의 안건(LM28 — st['meet_notes'] = {회의 행 번호: 안건}, main 의 meeting_notes 가 관문을 미리 통과시킨 것)은 'note'
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


# ── AI 가 직접 못 본 행 채우기(LM28 진단 A) ──────────────────────────────────────────
# 예전에는 실패·중단으로 남은 행(실측 6,326행)이 모두 규칙 이름('공통/기타')으로 쌓였다. 가장 비슷한 AI 판정을 빌려 채우고
# 'AI(유사)' 로 표시한다 — 채운 판정은 판정 기록·캐시에 넣지 않아 다음 실행이 AI 에 다시 묻는다.
FILL_CONV_MIN = 30          # 대화 채우기 — 앞뒤 이 분 안의 같은 계열(팀즈) 판정 업무 행
FILL_TOKEN_SHARE = 0.6      # 규칙 토큰 채우기 — 한 과제가 그 토큰 판정 행의 이 비율 이상이고
FILL_TOKEN_MIN = 3          # … 이 행 수 이상일 때만
FILL_SIM_PER_TOKEN = 300    # 유사 채우기 — 낱말 하나가 가리키는 판정 행 상한
_T0 = datetime(2000, 1, 1)


def _tmin(r):
    """행 시각 → 분(거리 비교용) · 못 읽으면 None."""
    try:
        return (datetime.strptime(str(r.get("time") or "")[:16], "%Y-%m-%d %H:%M") - _T0).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None


def _who_key(r):
    return " ".join(str((r or {}).get("who") or "").split()).lower()


def fill_unjudged(rows, judged, targets, keys=None):
    """AI 가 직접 못 본 행을 비슷한 판정으로 채운다 → {행: (판정, 방법)} — 방법은 same·conv·token·sim.
    ① same — 같은 내용 묶음 키(group_key — 팀즈는 같은 대화·같은 날)인 판정 행 중 가장 흔한 판정(비업무 n 도 옮기는 유일한 단계)
    ② conv — 팀즈: 같은 대화(conv 열 — 방을 모르는 줄끼리는 '방 모름' 한 묶음)의 앞뒤 30분 안 판정 업무 행 중 가장 가까운 것(같으면
       앞의 것). LM30(2026-10-27) — 예전에는 방 경계 없이 같은 보낸이를 먼저 골라 다른 방·다른 과제의 판정을 빌렸다.
    ③ token — mine 규칙 토큰(project — 미지정·공통·상투어·대화 낱말 제외): 그 토큰 판정 행의 60% 이상(3행 이상)이 한 과제면 그 과제와
       그 과제의 가장 흔한 (유형, 세부업무)
    ④ sim — 드문 낱말(df ≤ max(30, 0.5%·N) · 대화 낱말 제외)의 IDF 합(Σ log(N/df))이 가장 큰 판정 행(합 ≥ log(N/30) · 같으면 가까운
       시각) — 그 행이 업무일 때만(비업무와 가장 닮았으면 채우지 않는다)
    ⑤ conv(같은 대화 넓게 — LM30 2026-10-27) — 방을 아는 팀즈 줄 중 아직 못 채운 것: 같은 대화의 같은 날 판정 업무 행 중 가장 가까운 것,
       그것도 없으면 그 대화에서 판정된 행의 60% 이상(3행 이상)이 한 과제일 때 그 과제(가장 흔한 유형·세부업무). 맞장구·호칭뿐인 짧은
       대화는 30분 안에 내용 있는 줄이 없을 때가 많다 — 다른 방의 판정을 빌리지 않고 같은 대화 안에서만 넓힌다.
    ②~⑤는 업무 판정만 옮기고 행을 버리지 않는다. 강한 행정 공지 제목은 ②~⑤로 채우지 않는다(규칙의 '공통/공지·근태').
    targets: 채울 후보(판정 없음·광고 아님·관문 아님 — 짧은 대화 포함). keys: group_key 목록(없으면 새로 만든다)."""
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
    work = {i: j for i, j in judged.items() if j.get("work")}
    if not left or not work:
        return out
    tm = {}

    def _t(i):
        if i not in tm:
            tm[i] = _tmin(rows[i])
        return tm[i]
    # 대화별 판정 업무 행(시각순) — 방을 모르는 줄('')끼리도 한 묶음(예전 판 signals·방 이름이 없는 수집기 — 그 안에서만 빌린다)
    by_conv = defaultdict(list)
    for i in work:
        if _fam(rows[i]) == "팀즈" and _t(i) is not None:
            by_conv[_conv(rows[i])].append((_t(i), i))
    for v in by_conv.values():
        v.sort()
    tt_conv = {k: [x[0] for x in v] for k, v in by_conv.items()}
    rest = []
    for i in left:                                            # ② conv — 같은 대화 · 앞뒤 30분
        ti = _t(i)
        cv = _conv(rows[i])
        tl, tt = by_conv.get(cv) or [], tt_conv.get(cv) or []
        if _fam(rows[i]) != "팀즈" or ti is None or not tl:
            rest.append(i)
            continue
        cands = tl[bisect.bisect_left(tt, ti - FILL_CONV_MIN):bisect.bisect_right(tt, ti + FILL_CONV_MIN)]
        if not cands:
            rest.append(i)
            continue
        j = min(cands, key=lambda c: (abs(c[0] - ti), c[1]))[1]
        out[i] = (dict(work[j], via="conv"), "conv")
    left = rest

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
    for i in left:                                            # ③ token
        p = _ptok(rows[i])
        c = cnt.get(p) if p else None
        if c:
            m, n = c.most_common(1)[0]
            if n >= FILL_TOKEN_MIN and n >= FILL_TOKEN_SHARE * tot[p]:
                wt, dt = wd[(p, m)].most_common(1)[0][0]
                out[i] = ({"work": True, "model": m, "worktype": wt, "detail": dt, "via": "token"}, "token")
                continue
        rest.append(i)
    left = rest
    if left:
        _fill_sim(rows, judged, left, out, _t)                # ④ sim
        left = [i for i in left if i not in out]
    if left:
        _fill_conv_wide(rows, judged, work, by_conv, left, out, _t)   # ⑤ 같은 대화 넓게
    return out


def _fill_sim(rows, judged, left, out, _t):
    """fill_unjudged ④ sim — 드문 낱말의 IDF 합이 가장 큰 판정 행(업무일 때만). 대화 낱말은 낱말로 치지 않는다(LM30 2026-10-27)."""
    try:
        from extract import _tokens, rule_name_ok, talk_word
    except ImportError:
        return
    n_all = len(rows)
    toks, df = [], Counter()
    for r in rows:
        ts = {t for t in _tokens(r.get("text") or "") if rule_name_ok(t) and not talk_word(t)}
        toks.append(ts)
        df.update(ts)
    lim = max(30.0, 0.005 * n_all)
    index = defaultdict(list)
    for i in sorted(judged):
        for t in toks[i]:
            if df[t] <= lim and len(index[t]) < FILL_SIM_PER_TOKEN:
                index[t].append(i)
    thr = math.log(n_all / 30.0)
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
        ti = _t(i)
        j = min((j for j, s in sc.items() if s >= best - 1e-9),
                key=lambda j: (abs(_t(j) - ti) if (ti is not None and _t(j) is not None) else float("inf"), j))
        if judged[j].get("work"):
            out[i] = (dict(judged[j], via="sim"), "sim")


def _fill_conv_wide(rows, judged, work, by_conv, left, out, _t):
    """fill_unjudged ⑤ — 방을 아는 팀즈 줄만: 같은 대화의 같은 날 판정 업무 행 중 가장 가까운 것(같으면 앞의 것), 없으면 그 대화에서
    판정된 행(업무·비업무)의 FILL_TOKEN_SHARE 이상·FILL_TOKEN_MIN 행 이상이 한 과제일 때 그 과제와 가장 흔한 (유형, 세부업무)."""
    tot = Counter(_conv(rows[i]) for i in judged if _fam(rows[i]) == "팀즈")
    major = {}

    def _major(cv):
        if cv not in major:
            c = Counter(str(work[i].get("model") or "") for _t0, i in by_conv.get(cv, ()))
            major[cv] = None
            if c:
                m, n = c.most_common(1)[0]
                if n >= FILL_TOKEN_MIN and n >= FILL_TOKEN_SHARE * tot[cv]:
                    wd = Counter((str(work[i].get("worktype") or ""), str(work[i].get("detail") or ""))
                                 for _t0, i in by_conv.get(cv, ()) if str(work[i].get("model") or "") == m)
                    wt, dt = wd.most_common(1)[0][0]
                    major[cv] = {"work": True, "model": m, "worktype": wt, "detail": dt}
        return major[cv]
    for i in left:
        cv = _conv(rows[i])
        if not cv or i in out:
            continue
        ti, day = _t(i), str(rows[i].get("time") or "")[:10]
        cands = [c for c in by_conv.get(cv, ()) if str(rows[c[1]].get("time") or "")[:10] == day] if ti is not None else []
        if cands:
            j = min(cands, key=lambda c: (abs(c[0] - ti), c[1]))[1]
            out[i] = (dict(work[j], via="conv"), "conv")
            continue
        mj = _major(cv)
        if mj:
            out[i] = (dict(mj, via="conv"), "conv")


# ── 피벗·공통업무·에피소드 ─────────────────────────────────────────────────
def build_pivots(kept, total_mm, tot=None):
    """과제↔유형↔세부업무 피벗. tot(LM28)를 주면 분모로 쓴다 — shareBasis=time 에서 행 weight 가 배분된 분이고 분모에
    '근무 중 미분류' 분이 들어갈 때(그 몫은 어느 과제에도 붙지 않는다)."""
    tot_w = tot or sum(float(r["weight"] or 0) for r in kept) or 1e-9

    def mm(w):
        return round(w / tot_w * total_mm, 3)

    by_model = defaultdict(lambda: {"w": 0.0, "wt": defaultdict(float), "dt": defaultdict(float)})
    by_wt = defaultdict(lambda: {"w": 0.0, "md": defaultdict(float), "dt": defaultdict(float)})
    detail_models = defaultdict(lambda: defaultdict(float))
    for r in kept:
        w = float(r["weight"] or 0)
        md, wt, dt = r.get("model") or "공통", r.get("worktype") or "사무", r.get("detail") or r.get("activity") or "기타"
        by_model[md]["w"] += w
        by_model[md]["wt"][wt] += w
        by_model[md]["dt"][dt] += w
        by_wt[wt]["w"] += w
        by_wt[wt]["md"][md] += w
        by_wt[wt]["dt"][dt] += w
        detail_models[dt][md] += w
    pv = {
        "by_model": {m: {"mm": mm(v["w"]),
                         "worktypes": {k: mm(x) for k, x in sorted(v["wt"].items(), key=lambda a: -a[1])},
                         "details": {k: mm(x) for k, x in sorted(v["dt"].items(), key=lambda a: -a[1])[:10]}}
                     for m, v in sorted(by_model.items(), key=lambda a: -a[1]["w"])},
        "by_worktype": {t: {"mm": mm(v["w"]),
                            "models": {k: mm(x) for k, x in sorted(v["md"].items(), key=lambda a: -a[1])},
                            "details": {k: mm(x) for k, x in sorted(v["dt"].items(), key=lambda a: -a[1])[:10]}}
                        for t, v in sorted(by_wt.items(), key=lambda a: -a[1]["w"])},
        # 공통업무: 2개 이상 과제에 걸친 세부업무 = 표준화·자동화 후보
        "common": sorted([{"detail": dt, "models": sorted(ms, key=lambda m: -ms[m]),
                           "mm": mm(sum(ms.values()))}
                          for dt, ms in detail_models.items()
                          if len([m for m in ms if m != "공통"]) >= 2],
                         key=lambda x: -x["mm"])[:12],
    }
    return pv


def build_episodes(kept, cfg=None):
    """업무의 시작·끝 근사 — 외부요청(오더 수신)→내 산출(발신·파일·커밋) 페어링 리드타임,
    자체진행은 같은 과제 신호의 연속 구간(3일 초과 공백이면 분리)으로 본다.
    LM28: units(단위업무 — 시작·종료 단서와 3단계 등급, config.episodeTop 개)·unit_grades·units_total 을 더한다(build_units)."""
    def ts(r):
        try:
            return datetime.strptime(r["time"][:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    DONE = ("메일(발신)", "메일(발신·일자)", "팀즈(발신)", "팀즈(발신·일자)", "파일", "파일(코드)", "파일(해석출력)", "커밋", "수동기록")
    ORDER = ("팀즈(오더)", "메일(수신)")
    by_model = defaultdict(list)
    for r in kept:
        t = ts(r)
        if t:
            by_model[r.get("model") or "공통"].append((t, r))
    # 에피소드 매칭 전용 상용구 — 어떤 업무 메일에도 나오는 단어라 '내용 연관'의 근거가
    # 못 된다. 실측: '드립니다' 하나가 교집합이라는 이유로 "브릿지키 송부"가
    # "근무지 확인 회신"과 페어됐다(회사 화면의 미스매칭 다수가 이 경로).
    EP_BOILER = {"드립니다", "드립니다.", "부탁", "요청", "확인", "공유", "전달", "안내",
                 "회신", "송부", "감사", "수고", "일정", "계획", "내용", "검토", "보고서",
                 "첨부", "참고", "회람", "안녕하세요", "재송부", "관련하여"}

    def _ep_tokens(s):
        # extract 의 정식 토크나이저 재사용 — RE:/FW: 접두·확장자·날짜·버전·숫자·조사·
        # 보일러플레이트(STOP)를 걸러낸다. 자체 약식 토큰화는 're'·'pptx'·'2026' 같은
        # 상용구를 '내용 연관'으로 오인해 무관 페어를 만들었다(검증 확정).
        from extract import _tokens
        return {t2 for t2 in _tokens(str(s or ""))
                if t2 not in _MERGE_STOP and t2 not in EP_BOILER}

    episodes, leads = [], []
    for md, lst in by_model.items():
        lst.sort(key=lambda x: x[0])
        # 오더→산출 리드타임
        # 같은 과제의 '다음 산출물'을 무조건 페어하면 무관한 파일 저장이 응답으로
        # 짝지어진다(실측: 미스매칭 다수). 내용 연관(공통 단어) 또는 같은 세부업무가
        # 확인된 산출만 페어하고, 못 찾으면 페어하지 않는다.
        for i, (t, r) in enumerate(lst):
            if r["source"] not in ORDER:
                continue
            # 받은 메일 전체가 오더는 아니다 — 요청 단서가 있는 직접 수신만(LM28 W2-05·REQ-06, 팀즈 오더는 그대로)
            if r["source"] == "메일(수신)" and not _ep_is_request(r.get("text")):
                continue
            req_t = _ep_tokens(r.get("text"))
            # detail 동일성 폴백은 detail 이 실질 토큰을 가질 때만 — '기타'·'자료 작성' 같은
            # 일반 범주는 수십 건이 공유하므로 그것만으로 페어하면 무관 산출이 붙는다(실측).
            det = r.get("detail") or ""
            det_ok = bool(_ep_tokens(det))
            done = next(
                ((t2, r2) for t2, r2 in lst[i + 1:]
                 if r2["source"] in DONE
                 and (t2 - t).total_seconds() < 86400 * 14
                 and ((req_t and req_t & _ep_tokens(r2.get("text")))
                      or (det_ok and det == r2.get("detail")))),
                None)
            if done:
                leads.append({"model": md, "req": r["text"][:60], "start": r["time"],
                              "done": done[1]["text"][:60], "end": done[1]["time"],
                              "lead_h": round((done[0] - t).total_seconds() / 3600, 1)})
        # 자체진행 에피소드(연속 구간)
        st = prev = None
        n = 0
        for t, _r in lst:
            if prev and (t - prev).days > 3:
                episodes.append({"model": md, "start": st.strftime("%Y-%m-%d"),
                                 "end": prev.strftime("%Y-%m-%d"), "signals": n})
                st, n = None, 0
            st = st or t
            prev = t
            n += 1
        if st:
            episodes.append({"model": md, "start": st.strftime("%Y-%m-%d"),
                             "end": prev.strftime("%Y-%m-%d"), "signals": n})
    # 같은 스레드의 RE: 변형들이 같은 산출과 중복 페어되면 표가 도배된다 —
    # (정규화 요청, 정규화 산출) 별로 리드가 가장 짧은 1건만 남긴다.
    def _core(txt):
        t2 = str(txt or "").strip().lower()
        for _ in range(4):
            t2 = re.sub(r"^\s*(re|fw|fwd|회신|전달|답장)\s*[:)\]]\s*", "", t2)
            t2 = re.sub(r"^\s*[\[(][^\])]{0,24}[\])]\s*", "", t2)
        return re.sub(r"\s+", " ", t2)[:60]

    best = {}
    for x in leads:
        k = (_core(x["req"]), _core(x["done"]))
        if k not in best or x["lead_h"] < best[k]["lead_h"]:
            best[k] = x
    leads = list(best.values())
    leads.sort(key=lambda x: -x["lead_h"])
    out = {"orders": leads[:20], "spans": sorted(episodes, key=lambda x: x["start"], reverse=True)[:20],
           "avg_lead_h": round(sum(x["lead_h"] for x in leads) / len(leads), 1) if leads else None}
    out.update(build_units(kept, cfg))          # LM28 — 단위업무(시작·종료 단서·3단계 등급), 기존 키는 그대로
    return out


# ── 단위업무(LM28 WP8 — REQ-06~10·24·34, A-25·26): 시작·종료 단서와 3단계 등급 ─────────────────────
# LM27 time/episodes 의 단서·등급 규칙을 신호 행(과제 × 세부업무) 위에서 근사한다 — 대화 상태기계·문서군 키 사슬·
# 확인 질문 큐·5분 슬롯은 들이지 않는다. 메일·팀즈 신호의 text 는 제목·요약(정제문)이다.
#   시작: S1 = 나에게 직접 온 메일(수신 — CC·수신전용 아님)의 요청 단서 또는 팀즈 오더 · S2p = 디지털 시작이 없으면
#         첫 진행 −30분(오프라인 지시 추정, REQ-07).
#   종료: E1 = 보고 단서가 있는 내 발신(중간 보고 제외, REQ-08) · E2h = 최종 이름 저장 또는 앞서 저장한 문서와 같은
#         이름(stem)의 PDF(REQ-09) · E2l = 같은 문서를 2번 이상 고친 뒤 3근무일 정체(revision 정체) · E3i = 5근무일 휴면 →
#         마지막 진행 +30분(REQ-10). 아무것도 아니면 진행 중(open).
#   등급(3단계, A-26 을 줄임): 확정 = 시작·종료 모두 디지털(S1 × E1) · 근거 = 종료가 문서 완료(E2h) 또는 진행 중인 S1 ·
#         추정 = 시작이나 종료가 추정(S2p·E2l·E3i, 진행 중인 S2p).
EP_REQ_RX = re.compile(
    r"[\[【](?:요청|의뢰|검토\s*요청|검토\s*의뢰|확인\s*요청|작성\s*요청|제출\s*요청|승인\s*요청|결재\s*요청|협조|협조\s*요청|"
    r"회신\s*요망|회신\s*요청|action|request|req|todo)[\]】]"
    r"|요청|의뢰|부탁|요망|해\s*주세요|주십시오|주시기\s*바랍|please|request|action\s*required|could\s*you|can\s*you", re.I)
EP_REP_RX = re.compile(
    r"[\[【](?:보고|결과|결과\s*보고|결과\s*공유|송부|공유|제출|완료|report|result|done)[\]】]"
    r"|보고|결과|송부|공유\s*드|공유드|제출|완료|첨부와\s*같이|report|result|attached|done|completed", re.I)
EP_INTERIM_RX = re.compile(r"중간|경과|진행\s*상황|1차|interim|progress", re.I)
EP_FINAL_WORDS = ("최종", "final", "v1.0", "확정", "완료", "제출")
EP_PROGRESS = ("메일(발신)", "메일(발신·일자)", "팀즈(발신)", "팀즈(발신·일자)", "파일", "파일(코드)", "파일(해석출력)", "커밋", "수동기록",
               "작업창", "작업창(IDE)")
EP_DORMANT_WD = 5           # 이 근무일 동안 진행이 없으면 끝(E3i — 마지막 진행 +30분, 추정)
EP_STALL_WD = 3             # 같은 문서를 2번 이상 고친 뒤 이 근무일 정체 → 끝(E2l — 마지막 저장, 추정)
EP_PAD_MIN = 30
EP_TOP_DEFAULT = 50         # config.episodeTop
_EP_STEM_TAIL = re.compile(r"[\s_\-.]*(?:v\d+(?:\.\d+)*|rev\.?\d+|r\d+|최종|final|수정본|수정|사본|copy|\(\d+\)|\d{6,8})$", re.I)
_EP_SG = {"S1": "A", "S2p": "C"}
_EP_EG = {"E1": "A", "E2h": "B", "E2l": "C", "E3i": "D"}


def _ep_stem(name):
    """문서 이름 → 문서군 줄기(A-25 fam 근사) — 확장자·판 표기(v2·rev3·최종·final·사본·copy·(1)·날짜)를 최대 5번 뗀다."""
    s = unicodedata.normalize("NFKC", str(name or "")).strip().lower()
    s = re.sub(r"(\.[a-z0-9]{1,5}){1,2}$", "", s)
    for _ in range(5):
        t = _EP_STEM_TAIL.sub("", s).strip(" _-.")
        if t == s:
            break
        s = t
    return s


def _ep_file(text):
    """파일 신호 text → (이름 소문자, 확장자)."""
    try:
        from extract import _sig_name
        nm = _sig_name(text)
    except ImportError:
        nm = str(text or "").split(" § ")[0].split(" | 폴더:")[0].strip().lower()
    return nm, os.path.splitext(nm)[1]


def _ep_is_request(text):
    return bool(EP_REQ_RX.search(text or "")) and not EP_REP_RX.search(text or "")


def _ep_is_report(text):
    return bool(EP_REP_RX.search(text or "")) and not EP_INTERIM_RX.search(text or "")


def _ep_grade(sc, ec):
    """(시작 단서, 종료 단서|None) → 3단계 등급."""
    if ec is None:
        return "근거" if sc == "S1" else "추정"
    g = max(_EP_SG[sc], _EP_EG[ec])
    return "확정" if g == "A" else ("근거" if g == "B" else "추정")


def _workdays_between(a, b):
    """a 다음 날 ~ b 날짜 사이 근무일 수(주말·공휴일 제외 — extract._is_off_day)."""
    try:
        from extract import _is_off_day
    except ImportError:
        def _is_off_day(d, _h):
            return d.isoweekday() > 5
    n, d = 0, a.date()
    end = b.date()
    while d < end:
        d = date.fromordinal(d.toordinal() + 1)
        if not _is_off_day(d, set()):
            n += 1
    return n


def build_units(kept, cfg=None):
    """판정된 신호 행 → {"units": [단위업무 …](config.episodeTop 개, 기본 50), "unit_grades": {등급: 수}, "units_total"}.
    단위업무 = 과제 × 세부업무 안에서 시작 단서 ~ 종료 단서(위 머리말). 신호가 많은 것부터 episodeTop 개를 남기고
    시작 시각 역순으로 싣는다."""
    from datetime import timedelta as _td2
    try:
        top = int((cfg or {}).get("episodeTop") or EP_TOP_DEFAULT)
    except (TypeError, ValueError, AttributeError):
        top = EP_TOP_DEFAULT
    top = max(1, min(1000, top))
    rows = []
    for r in kept:
        try:
            t = datetime.strptime(str(r.get("time") or "")[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        rows.append((t, r))
    if not rows:
        return {"units": [], "unit_grades": {}, "units_total": 0}
    as_of = max(t for t, _r in rows)
    by_key = defaultdict(list)
    for t, r in rows:
        by_key[(r.get("model") or "공통", r.get("detail") or r.get("activity") or "기타")].append((t, r))
    units = []

    def _fmt(t):
        return t.strftime("%Y-%m-%d %H:%M")

    for (md, dt), lst in by_key.items():
        lst.sort(key=lambda x: x[0])
        cur = None

        def _close(u, t_end, cue, by):
            u.update(end=_fmt(t_end), end_cue=cue, end_by=str(by or "")[:60],
                     status="closed" if cue in ("E1", "E2h") else "estimated",
                     grade=_ep_grade(u["start_cue"], cue),
                     lead_h=round(max(0.0, (t_end - u["_s"]).total_seconds()) / 3600.0, 1))
            units.append(u)

        def _quiet_end(u, t_now):
            """조용한 동안 끝났나 — 정체(E2l)·휴면(E3i) 판정, 끝났으면 닫고 True."""
            if u["_last"] is None:
                return False
            wd = _workdays_between(u["_last"], t_now)
            stalled = u["_last_stem"] and u["_stems"][u["_last_stem"]] >= 2
            if wd >= EP_DORMANT_WD or (stalled and wd >= EP_STALL_WD):
                if stalled:
                    _close(u, u["_last"], "E2l", u["_last_by"])
                else:
                    _close(u, u["_last"] + _td2(minutes=EP_PAD_MIN), "E3i", u["_last_by"])
                return True
            return False

        for t, r in lst:
            src, text = r.get("source") or "", r.get("text") or ""
            if cur and _quiet_end(cur, t):
                cur = None
            is_req = (src == "팀즈(오더)") or (src == "메일(수신)" and _ep_is_request(text))
            if is_req:
                if cur is None:
                    cur = {"model": md, "detail": dt, "start": _fmt(t), "start_cue": "S1", "start_by": text[:60],
                           "signals": 1, "_s": t, "_last": None, "_last_by": "", "_last_stem": "",
                           "_stems": Counter()}
                else:
                    cur["signals"] += 1              # 열린 업무에 온 추가 지시 — 같은 업무로 둔다
                continue
            if src not in EP_PROGRESS:
                continue
            if cur is None:
                s = t - _td2(minutes=EP_PAD_MIN)     # 디지털 시작이 없다 — 오프라인 지시 추정(S2p)
                cur = {"model": md, "detail": dt, "start": _fmt(s), "start_cue": "S2p", "start_by": text[:60],
                       "signals": 0, "_s": s, "_last": None, "_last_by": "", "_last_stem": "", "_stems": Counter()}
            cur["signals"] += 1
            cur["_last"], cur["_last_by"], cur["_last_stem"] = t, text, ""
            if src in ("메일(발신)", "팀즈(발신)") and _ep_is_report(text):
                _close(cur, t, "E1", text)
                cur = None
                continue
            if src.startswith("파일"):
                nm, ext = _ep_file(text)
                stem = _ep_stem(nm)
                if ext == ".pdf":
                    if stem and cur["_stems"].get(stem):
                        _close(cur, t, "E2h", text)      # 앞서 고친 문서의 PDF 내보내기 — 작성 완료
                        cur = None
                    continue
                if any(w in nm for w in EP_FINAL_WORDS):
                    _close(cur, t, "E2h", text)          # 최종 이름 저장
                    cur = None
                    continue
                if stem:
                    cur["_stems"][stem] += 1
                    cur["_last_stem"] = stem
        if cur and not _quiet_end(cur, as_of):
            cur.update(end=None, end_cue=None, end_by="", status="open", grade=_ep_grade(cur["start_cue"], None),
                       lead_h=None)
            units.append(cur)
    for u in units:
        for k in [k for k in u if k.startswith("_")]:
            del u[k]
    grades = Counter(u["grade"] for u in units)
    keep = sorted(units, key=lambda u: (-u["signals"], u["start"]))[:top]
    keep.sort(key=lambda u: u["start"], reverse=True)
    return {"units": keep, "unit_grades": dict(grades), "units_total": len(units)}


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


def load_detail_alias_map():
    """core/details 의 (과제, 세부업무)→대표 이름 캐시(config/detail_aliases.json).
    모듈이 없거나 깨져도 판정은 계속 — 빈 맵."""
    try:
        from details import load_detail_aliases
        amap = load_detail_aliases()
        return amap if isinstance(amap, dict) else {}
    except Exception:
        return {}


def merge_details(rows, amap=None):
    """같은 과제 안에서 사실상 같은 세부업무를 대표 이름 하나로 통합한다.
    AI가 청크마다 '공용 Capability 설계' / 'Capability 구조 설계'처럼 다르게 이름 붙이면
    (과제 × 세부업무) 격자가 곱셈으로 늘어나 로드율이 파편화된다 — LM4가 1행으로 주던 것이
    6행으로 쪼개지던 실측 결함. 가중치가 큰 이름을 대표로 삼는다. returns 병합된 행 수

    LM22: ① 괄호 꼬리가 다른 이름('레이아웃 검토(양산)' / '(선행)' / 꼬리 없음)은 토큰이 겹쳐도
    절대 병합하지 않는다 — 예전 토큰 규칙은 괄호를 구분자로 갈라 셋을 하나로 오병합했다(실측).
    ② 세부업무 병합 캐시(core/details — Copilot 이 '같은 묶음의 일'로 묶은 대표 이름)는 **여기서 쓰지
    않는다**(amap 을 명시해 넘길 때만). 그 캐시는 보완2 설계대로 워크플로우·Agentic·분석리포트의
    담당업무 축에만 적용하고, 판정 신호·대시보드·리뷰의 세부업무(하위) 이름은 LM20 과 같이 판정
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
    # 다른 이름('레이아웃 검토 회의')에 흡수시키면 signals/mm_rows 의 Level 3 가 캐시 키·대표와
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


def _mine_exclude(cfg):
    """mine.py 가 신호·시간 근거에 쓴 것과 같은 제외어 — 단일원 privacy.excluded_keywords(내장 EXCLUDE ∪
    config.excludePathKeywords). mine 을 임포트하지 않는다(모듈 최상위에서 sys.stdout 을 다시 감싸 이 프로세스의 출력을 끊는다)."""
    import privacy
    return privacy.excluded_keywords(cfg)


def _period_of(mj, tag):
    """mm_meta.period 또는 태그(YYYYMMDD-YYYYMMDD) → (date, date) / 못 읽으면 None"""
    per = mj.get("period") if isinstance(mj, dict) else None
    try:
        if isinstance(per, list) and len(per) >= 2:
            return date.fromisoformat(str(per[0])[:10]), date.fromisoformat(str(per[-1])[:10])
    except (TypeError, ValueError):
        pass
    m = re.match(r"^(\d{4})(\d{2})(\d{2})-(\d{4})(\d{2})(\d{2})$", str(tag or ""))
    if not m:
        return None
    try:
        return (date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                date(int(m.group(4)), int(m.group(5)), int(m.group(6))))
    except ValueError:
        return None


DROPPED_COLS = ["time", "source", "who", "project", "activity", "weight", "text",
                "model", "worktype", "detail", "judge"]


def dropped_path(rep, tag):
    """버린 신호 누적 장부 — report\\dropped_signals_<tag>.csv (signals_* 글롭에 걸리지 않는 이름).
    UI 오할당 제외는 judge 가 이미 버린 행을 CSV 에서 볼 수 없으므로, 재산정 때마다 '지금까지 버린 전부' 를
    여기서 읽어 함께 넘긴다(그래야 두 번째 제외가 첫 번째 제외분을 되살리지 않는다)."""
    return os.path.join(rep, f"dropped_signals_{tag}.csv")


def _read_dropped(rep, tag):
    p = dropped_path(rep, tag)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8-sig") as f:
            return [r for r in csv.DictReader(f) if isinstance(r, dict) and r.get("time")]
    except (OSError, csv.Error, ValueError):
        return []


def _write_dropped(rep, tag, rows):
    p = dropped_path(rep, tag)
    tmp = f"{p}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=DROPPED_COLS)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, "") for c in DROPPED_COLS})
        os.replace(tmp, p)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def rehours_meta(kept, dropped, tag, cfg, rep, data_dir=None, say=print):
    """A30 — 비업무('n') 판정·오할당 제외로 **버린 신호를 뺀 채** 투입시간·MM 을 다시 재어
    mm_meta_<tag>.json 을 갱신한다. 예전에는 mine 단계의 total_mm(모든 신호 기준)이 그대로 남아,
    버린 신호의 시간이 남은 행에 옮겨 붙었다('내 업무 아님'을 빼도 로드율이 그대로).

    kept/dropped: signals CSV 행(dict: time·source·text·weight·who…). 시간 재산정은
    extract.rehours_after_judge(kept 신호만으로 day_work_hours→mm_from_hours, 버린 파일 신호의 폴더는
    시간 근거에서도 제외)가 한다. write_outputs 가 갱신된 mm_meta.total_mm 을 읽으므로 그보다 먼저 부른다.
    누적: meta 가 이미 재산정본(rehours)이면 dropped_signals_<tag>.csv 의 이전 버림분을 합쳐 넘긴다 —
    mine 이 다시 돌면 meta 에 rehours 가 없으므로 장부는 새로 시작한다(옛 버림분이 새 신호를 지우지 않게).
    returns {"dropped_n"(누적),"dropped_h","before_mm","total_mm","avail_mm","load_pct","ai_n_time_kept"} — 버린 것이 없거나
    (구판 core 로) 함수가 없거나 meta 가 없거나 저장이 막히면 None(그때는 mine 값이 그대로 남는다).
    LM30(2026-10-18): mm_meta 저장이 성공하면 추이 선 day_hours_<tag>.json 과 출퇴근 파일 attendance_<tag>.json(이 PC 전용 —
    날짜별 시각은 mm_meta 에서 떼어 여기로만)도 같은 재산정 값으로 다시 쓴다 — 추이 선·MM 카드·투입 MM 이 같은 시간을 본다."""
    if not dropped:
        return None
    import extract
    fn = getattr(extract, "rehours_after_judge", None)
    if fn is None:
        say("        ※ extract.rehours_after_judge 없음(구판 core) — 비업무 제외분의 시간 재산정 생략")
        return None
    meta_p = os.path.join(rep, f"mm_meta_{tag}.json")
    try:
        with open(meta_p, encoding="utf-8-sig") as f:
            mj = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(mj, dict):
        return None
    per = _period_of(mj, tag)
    if not per:
        return None
    d0, d1 = per
    data_dir = data_dir or os.path.join(ROOT, "data")
    prev = _read_dropped(rep, tag) if mj.get("rehours") else []
    seen = set()
    dropped_all = []
    for r in list(prev) + list(dropped):
        k = (str(r.get("time") or "")[:16], r.get("source") or "", (r.get("text") or "")[:120])
        if k in seen:
            continue
        seen.add(k)
        dropped_all.append(r)
    try:
        res = fn(data_dir, kept, dropped_all, d0, d1, cfg, _mine_exclude(cfg))
    except Exception as e:  # noqa: BLE001 - 재산정 실패가 판정 결과 저장을 막지 않게(mine 값 유지)
        say(f"        ※ 비업무 제외분 시간 재산정 실패({type(e).__name__}: {str(e)[:80]}) — mine 값 유지")
        return None
    dropped = dropped_all
    if isinstance(res, (list, tuple)) and len(res) >= 4:       # (day_hours, info, total_mm, avail_mm)
        res = {"day_hours": res[0], "info": res[1], "total_mm": res[2], "avail_mm": res[3]}
    if not isinstance(res, dict) or res.get("total_mm") is None:
        return None
    try:
        total_mm = round(float(res.get("total_mm") or 0.0), 3)
        avail_mm = round(float(res.get("avail_mm") or 0.0), 3)
    except (TypeError, ValueError):
        return None
    before_mm = mj.get("total_mm")
    try:
        before_mm = float(before_mm) if before_mm is not None else None
    except (TypeError, ValueError):
        before_mm = None
    before_h = mj.get("worked_h")
    dh = res.get("day_hours") or {}
    day_hours = {}
    for k, v in (dh.items() if isinstance(dh, dict) else []):
        try:
            day_hours[k if isinstance(k, str) else k.isoformat()] = round(float(v or 0), 2)
        except (TypeError, ValueError, AttributeError):
            continue
    worked_h = round(sum(day_hours.values()), 1)
    dropped_h = res.get("dropped_h")
    try:
        dropped_h = float(dropped_h) if dropped_h is not None else float(before_h or 0) - worked_h
    except (TypeError, ValueError):
        dropped_h = 0.0
    mj["total_mm_before_rehours"] = before_mm
    mj["total_mm"], mj["avail_mm"] = total_mm, avail_mm
    mj["load_pct"] = round(total_mm / avail_mm * 100, 1) if avail_mm else 0.0
    if day_hours:
        mj["day_hours"] = day_hours
        mj["worked_h"] = worked_h
    if isinstance(res.get("months"), dict):
        mj["mm_months"] = res["months"]
    info = res.get("info")
    att_days = att_usual = att_agg = None
    if isinstance(info, dict):
        info = dict(info)
        info.pop("inferred_absence", None)        # date 키 — mine 도 저장 전에 뺀다
        # LM30(2026-10-18): 날짜별 출근·퇴근·평소 시각은 mm_meta(팀으로 올라간다)에 싣지 않는다 — mine 과 같이 떼어
        # report\attendance_<tag>.json 으로만(아래 저장 성공 뒤). LM30(2026-10-19): 근태 기록과 견준 합계(+@)도 같이(att_agg)
        try:
            import attendance as _att
            att_days, att_usual, att_agg = _att.take_local(info)
        except ImportError:                        # 구판 core — 칸만 버린다
            # LM30(2026-10-21) leave_local = 유급휴가 날짜(이 PC 전용)
            for _k in ("attendance_days", "attendance_usual", "attendance_agg", "attendance_hr", "attendance_legal", "leave_local"):
                info.pop(_k, None)
        mj["mm_basis"] = info
        if info.get("mm_lm29") is not None:
            mj["mm_lm29"] = info["mm_lm29"]       # 'LM29 방식이었다면 X MM' — mine.meta_doc 과 같은 최상위 키
        # LM30v1(2026-10-19) 법정 채움 MM — 규칙 표식·'LM30 방식이었다면 X MM'(mine.meta_doc 과 같은 최상위 키). 재산정 때 기준이
        # 바뀌었으면(measured) 옛 값을 남기지 않는다. 달마다 근태 기록 시간·+@ 나눔은 take_local 이 att_agg["legal"] 로 옮겼다
        for k in ("mm_rule", "mm_lm30"):
            if info.get(k) is not None:
                mj[k] = info[k]
            else:
                mj.pop(k, None)
        for k in ("coverage", "measure", "cfg_used", "tool_usage"):   # mine 과 같이 최상위에도 싣는다(팀 취합이 읽는다)
            if isinstance(info.get(k), dict):
                mj[k] = info[k]
        if isinstance(info.get("unobserved_days"), list):              # LM28 — mine.meta_doc 과 같이 최상위에도
            mj["unobserved_days"] = info["unobserved_days"]
    mj["rehours"] = True
    mj["dropped_n"] = len(dropped)
    mj["dropped_h"] = round(max(0.0, dropped_h), 2)
    mj["rehours_at"] = time.strftime("%Y-%m-%d %H:%M")
    # AI 가 비업무(n)로 뺐지만 시간 근거로는 남긴 신호 수 — extract.rehours_after_judge 의 time_kept_n(구판이면 0)
    try:
        mj["ai_n_time_kept"] = int(res.get("time_kept_n") or 0)
    except (TypeError, ValueError):
        mj["ai_n_time_kept"] = 0
    tmp = f"{meta_p}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mj, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, meta_p)
    except OSError as e:
        say(f"        ※ mm_meta 갱신 실패({type(e).__name__}) — 열린 프로그램을 닫고 재실행 (mine 값 유지)")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    # LM30(2026-10-18): 추이 선(day_hours_<tag>.json)·출퇴근 파일도 다시 잰 값으로 — 예전에는 mm_meta 만 바뀌어 판정 뒤
    # 대시보드의 추이 선과 MM 카드가 서로 다른 시간을 보였다. mm_meta 저장이 성공했을 때만 쓴다(실패면 셋 다 mine 값).
    if day_hours and not extract.save_day_hours(rep, tag, day_hours):
        say("        ※ 추이 선 갱신 실패(day_hours) — 다음 분석 때 다시 씁니다")
    if att_days is not None and hasattr(extract, "save_attendance"):
        extract.save_attendance(rep, tag, att_days, att_usual, att_agg if att_agg is not None else (info or {}).get("attendance"))
    _write_dropped(rep, tag, dropped)          # 누적 장부 — 다음 UI 제외가 이번 버림분을 함께 넘긴다
    return {"dropped_n": len(dropped), "dropped_h": mj["dropped_h"], "before_mm": before_mm,
            "total_mm": total_mm, "avail_mm": avail_mm, "load_pct": mj["load_pct"],
            "ai_n_time_kept": mj["ai_n_time_kept"]}


def _time_alloc(kept, mj, cfg):
    """mm.shareBasis="time" 이면 ({(과제, 세부업무)|UNCLASSIFIED: 몫}, {(과제, 세부업무): 분}, 미분류 분) — 아니면 ({}, {}, 0).
    그날 투입은 mm_meta.day_hours(재산정이 있으면 그 값). 신호 행: time·source·weight(signals CSV)."""
    try:
        import extract
        mc = extract.norm_cfg(cfg)[0]
    except Exception:  # noqa: BLE001 - 시간 몫을 못 만들면 LM24 가중치 몫으로
        return {}, {}, 0
    if mc.get("shareBasis") != "time" or timeshare is None:
        return {}, {}, 0
    day_min = {}
    for k, v in (mj.get("day_hours") or {}).items():
        try:
            day_min[date.fromisoformat(str(k)[:10])] = int(round(float(v or 0) * 60))
        except (TypeError, ValueError):
            continue
    rows = []
    for r in kept:
        try:
            t = datetime.strptime(str(r.get("time") or "")[:16], "%Y-%m-%d %H:%M")
            w = float(r.get("weight") or 0)
        except (TypeError, ValueError):
            continue
        rows.append((t, r.get("source") or "", w, (r["model"], r["detail"])))
    alloc, st = timeshare.allocate(day_min, rows, mc["signalMinutes"])
    tot = sum(alloc.values())
    if not tot:
        return {}, {}, 0
    print(f"        과제 몫 = 시간(shareBasis=time) · 근무 중 미분류 {st.get('unclassified_min', 0) / 60:.1f}h")
    return ({k: v / tot for k, v in alloc.items()}, {k: v for k, v in alloc.items() if k != UNCLASSIFIED},
            alloc.get(UNCLASSIFIED, 0))


def write_outputs(kept, tag, cfg, rep):
    """판정 완료 신호 → mm_rows CSV + pivots JSON (MM 총량 스케일).
    judge 본류와 retag(지정 반영 재분류) 양쪽에서 호출한다.
    총량은 mm_meta.total_mm — 비업무 제외가 있었으면 rehours_meta 가 먼저 갱신해 둔 값이다(A30)."""
    merged = merge_details(kept)
    if merged:
        print(f"        같은 일로 판정된 세부업무 {merged}건 통합 (행 파편화 방지)")
    # 과제 → 제품 매핑 (taxonomy 판정 결과) — retag 경로에서도 동일하게 쓰도록
    # entities 파일에서 직접 읽는다(시그니처 불변).
    # 상위(Level 1) 채움 재료(LM28 진단 B) — taxonomy 가 과제마다 판정한 l1(entities)·사람이 못 박은 상위(projects.json
    # level1). 정제(refine)가 돌지 않은 실행에서도 '큰 분류 > 과제 > 세부업무' 가 서게 한다(details.level1_fill).
    prod_map, l1_map, pin = {}, {}, {}
    try:
        ent = json.load(open(os.path.join(rep, f"entities_{tag}.json"), encoding="utf-8-sig"))
        for m in (ent.get("models") or []):
            if isinstance(m, dict) and m.get("name") and m.get("product"):
                prod_map[str(m["name"])] = str(m["product"]).strip()
            if isinstance(m, dict) and m.get("name") and m.get("l1"):
                _l1 = details.snap1(m.get("l1"))
                if _l1:
                    l1_map[ukey2(m["name"])] = _l1
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        import projmap
        for p in projmap.load_user_projects(ROOT):
            _l1 = details.snap1(p.get("level1"))
            if _l1:
                pin[ukey2(p["name"])] = _l1
    except Exception:  # noqa: BLE001 - 지정 상위를 못 읽어도 규칙 상위로 계속
        pin = {}

    def _product_for(md, dt):
        """제품 축: 실제 제품이면 그 이름, 공통이면 '공통 · <세부업무>' 로 세분화,
        판정이 없으면 과제명 그대로(그 이름이 곧 프로젝트 코드인 경우)."""
        p = (prod_map.get(md) or "").strip()
        if md == "공통" or p == "공통":
            return f"공통 · {dt}" if dt else "공통"
        return p or md
    meta_p = os.path.join(rep, f"mm_meta_{tag}.json")
    mj = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    # 투입 MM 을 항목별로 배분한다. 0이면 0 그대로 — 예전 `or 1` 폴백은 투입 0h인 기간을
    # 화면에는 0, CSV에는 1.00 MM 으로 내보내 두 산출물이 어긋나게 했다.
    tm = mj.get("total_mm")
    total_mm = float(tm) if tm is not None else float(mj.get("months") or 0)
    tot_w = sum(float(r["weight"] or 0) for r in kept) or 1e-9
    agg = defaultdict(lambda: {"w": 0.0, "days": set(), "src": Counter(), "wt": Counter()})
    for r in kept:
        a = agg[(r["model"], r["detail"])]
        a["w"] += float(r["weight"] or 0)
        a["days"].add(r["time"][:10])
        a["src"][r["source"]] += 1
        a["wt"][r.get("worktype") or "사무"] += 1
    # 과제 몫 — 기본 'weight'(LM24 가중치 비율). mm.shareBasis="time"(LM28 옵션)이면 mm_meta.day_hours(그날 투입)를
    # 분 단위로 (과제, 세부업무)에 나눈다(core\timeshare — 날마다 Σ = 투입). 넘친 몫은 '근무 중 미분류' 행.
    tshare, t_alloc, unc_min = _time_alloc(kept, mj, cfg)
    owner = cfg.get("owner") or os.environ.get("USERNAME", "")
    out_rows = []
    for (md, dt), a in sorted(agg.items(), key=lambda kv: -(tshare.get(kv[0], 0.0) if tshare else kv[1]["w"])):
        share = tshare.get((md, dt), 0.0) if tshare else a["w"] / tot_w
        srcs = len({s.split("(")[0] for s in a["src"]})
        # 상위 초안 — 지정 상위 > taxonomy l1 > 규칙(코드네임·영역 키워드) > 과제명이 곧 범주('공통')로 채운다.
        # AI 정제가 돌면 그 판정이 이 값을 덮는다. 예전에는 규칙만 써서 '공통' 과제도 상위가 빈칸이었다(진단 B).
        out_rows.append({"Function": cfg.get("function", ""),
                         "Level 1": details.level1_fill(md, dt, l1_map, pin, ROOT),
                         "제품": _product_for(md, dt),
                         "유형": a["wt"].most_common(1)[0][0], "Level 2": md, "Level 3": dt,
                         "이름": owner, "상세설명": "",
                         "share": round(share, 4), "mm": round(share * total_mm, 3),
                         "근거": " · ".join(f"{s}{n}" for s, n in a["src"].most_common()),
                         "확신도": "상" if (srcs >= 2 and len(a["days"]) >= 3) else
                                  ("중" if srcs >= 2 or len(a["days"]) >= 3 else "하"),
                         "활동일수": len(a["days"]),
                         # LM28 끝 열 — AX 연계 표식(MM 은 원래 영역)·분야(규칙). 기존 열·순서는 그대로
                         "ax": ax_flag(f"{md} {dt}"), "field": field_of(f"{md} {dt}")})
    if tshare and tshare.get(UNCLASSIFIED):
        share = tshare[UNCLASSIFIED]
        out_rows.append({"Function": cfg.get("function", ""), "Level 1": "", "제품": "", "유형": "",
                         "Level 2": UNCLASSIFIED, "Level 3": UNCLASSIFIED, "이름": owner,
                         "상세설명": "신호가 덮지 않은 근무 분 중 과제별 직접 분 비례 상한을 넘친 몫",
                         "share": round(share, 4), "mm": round(share * total_mm, 3), "근거": "", "확신도": "하",
                         "활동일수": 0, "ax": 0, "field": ""})
        out_rows.sort(key=lambda x: -x["share"])
    cols2 = ["Function", "Level 1", "제품", "유형", "Level 2", "Level 3", "이름", "상세설명",
             "share", "mm", "근거", "확신도", "활동일수", "ax", "field"]
    with open(os.path.join(rep, f"mm_rows_{tag}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols2)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    if tshare:
        # 피벗도 같은 시간 몫으로 — 행 가중치를 그 (과제, 세부업무)의 배분 분으로 바꾼 사본, 분모 = 미분류 포함 총 분
        cnt = Counter((r["model"], r["detail"]) for r in kept)
        tw = {k: (a["w"], float(t_alloc.get(k, 0)), cnt[k] or 1) for k, a in agg.items()}
        kept_pv = []
        for r in kept:
            aw, am, n = tw[(r["model"], r["detail"])]
            r2 = dict(r)
            r2["weight"] = am * float(r["weight"] or 0) / aw if aw > 0 else am / n
            kept_pv.append(r2)
        pv = build_pivots(kept_pv, total_mm, tot=float(sum(t_alloc.values()) + unc_min) or None)
    else:
        pv = build_pivots(kept, total_mm)
    pv["episodes"] = build_episodes(kept, cfg)
    with open(os.path.join(rep, f"pivots_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(pv, f, ensure_ascii=False, indent=1)
    return total_mm, pv


# ── [월별] 내러티브 ────────────────────────────────────────────────────────
def _nm_key(s):
    """과제 이름 비교 축 — 공백·구분자·대소문자 무시(core/details.ukey2 와 같은 규칙)."""
    return re.sub(r"[\s·・ㆍ‧/_\-()\[\]]+", "", str(s or "")).casefold()


NARRATIVE_EXAMPLE = ('{"summary":"이 달 요약 2~3문장","projects":[{"name":"프로젝트A",'
                     '"story":"무엇을 어떻게 했는지 1~2문장","worktypes":"개발 위주"}]}')
_NARR_ECHO = _nm_key("프로젝트A")    # NARRATIVE_EXAMPLE 의 예시 과제 이름 — 답에 나오면 에코라 항상 버린다
NARR_MIN_AI_ROWS = 10       # 한 달의 AI 판정 행이 이보다 적으면(그 달 행이 더 적으면 그 수) 코멘트를 새로 만들지 않는다
NARR_MIN_AI_SHARE = 0.3     # … 또는 그 달 행의 30% 미만이면 — 규칙 행 위주 표본으로 만든 코멘트가 좋은 코멘트를 덮지 않게
NARR_CHANGED = 0.25         # 이전 코멘트를 만들 때보다 AI 판정 행 수가 이 비율을 넘게 달라졌으면 '데이터가 바뀐 달'
_NARR_LAST = {}             # 마지막 narrate 의 계획 요약 {plan, low_ai, made} — --narrate-only 가 '다시 만들 달 없음'을 가린다


def _is_ai_row(r):
    """AI 가 판정한 행인가 — 'AI'(직접·재사용·같은 내용 묶음) · 'AI(유사)'(비슷한 판정으로 채움). '규칙' 은 아니다."""
    return str((r or {}).get("judge") or "").startswith("AI")


def _narr_name(name, real):
    """답의 과제 이름 → 그 달의 체계 표기(맞는 것이 없으면 None). real = {_nm_key(표기): 표기}.
    정확히 같으면 그 표기, 아니면 길이 2 이상 키끼리 포함 관계인 것 중 가장 긴 것('Agentic AI 과제' → 'Agentic AI').
    예전에는 정확히 같아야만 남겨, 이름이 조금만 달라도 과제 줄이 모두 빠지고 요약 한 줄만 남았다."""
    k = _nm_key(name)
    if not k or k == _NARR_ECHO:
        return None
    if k in real:
        return real[k]
    best = ""
    if len(k) >= 2:
        for rk in real:
            if len(rk) >= 2 and (rk in k or k in rk) and len(rk) > len(best):
                best = rk
    return real[best] if best else None


_MONTH_RX = re.compile(r"(20\d{2})\s*(?:[-./]|년)\s*(\d{1,2})(?!\d)")


def _narr_mixed(o, mk, names_by):
    """LM30(2026-10-21) — 한 채팅에 이어 물은 달의 리뷰 답에 다른 달이 섞였나: 요약·과제 줄에 다른 달(YYYY-MM · YYYY.M · YYYY년 M월)이
    보이거나, 이 달 AI 판정 행에는 없고 다른 달에만 있는 과제 이름(정확한 이름 키)을 댔으면 참. names_by = {달: {과제 이름}}."""
    try:
        y, m = int(str(mk)[:4]), int(str(mk)[5:7])
    except ValueError:
        return False
    projs = [p for p in _as_list((o or {}).get("projects")) if isinstance(p, dict)]
    texts = [str((o or {}).get("summary") or "")] + [str(p.get(k) or "") for p in projs for k in ("name", "story")]
    for t in texts:
        for a, b in _MONTH_RX.findall(t):
            if 1 <= int(b) <= 12 and (int(a), int(b)) != (y, m):
                return True
    here = {_nm_key(n) for n in (names_by or {}).get(mk, set())} | {_nm_key("공통")}
    others = {_nm_key(n) for k2, ns in (names_by or {}).items() if k2 != mk for n in ns} - here
    return any(_nm_key(p.get("name")) in others for p in projs if str(p.get("name") or "").strip())


def narrate(kept, total_mm, tag, force_all=False, max_consec=2, cap_min=20.0):
    r"""월별 리뷰 코멘트 → {달: 항목}(이번에 새로 만든 달만). 저장은 달마다 save_narratives(늘 이월 — 끊겨도
    이전 달이 가려지지 않는다)로 하고, 끝에 한 번 더 한다.
    ① 계획 — 그 달의 AI 판정 행(judge 가 'AI' 로 시작)이 NARR_MIN_AI_ROWS·NARR_MIN_AI_SHARE 에 못 미치면 보내지
       않고 이전 코멘트를 유지한다(earlier 표식). 나머지 순위: 0 이전 코멘트 없음 · 1 가장 최근 달 · 2 force_all
       이거나 n_ai 없음(예전 판 항목)이거나 AI 행 수가 NARR_CHANGED 넘게 바뀜. 그 밖(바뀌지 않은 달)은 보내지 않는다.
       같은 순위는 최근 달 먼저 — 예전에는 모든 달을 오래된 달부터 다시 만들어, 예산·연속 실패로 끊기면 늘 화면
       맨 위의 최근 달과 새로 데이터가 생긴 달이 비었다(제보: '월간 리뷰 코멘트가 사라짐').
       이월 표식(from_tag)만으로는 다시 만들지 않는다 — tag 가 날마다 바뀌어 이전 달은 늘 이월이므로, 그러면 매일
       모든 달을 다시 만든다. 데이터가 바뀌었는지는 n_ai 로 가린다.
    ② 예산 — 단계 예산과 cap_min(분 · None 이면 없음 — [리뷰 코멘트 재생성]) 중 이른 쪽. 연속 실패 max_consec 회면
       멈춘다(판정이 연속 실패로 중단된 실행은 1 — 한 달만 시험).
    ③ 표본은 AI 판정 행만 — 규칙 행(규칙 토큰·사람 이름 과제 위주)은 보내지 않는다.
    ④ 관문(G3)에 걸리면 걸린 줄을 빼고 한 번 더(20줄 이상 남을 때). ⑤ 과제 이름은 그 달의 체계 표기로 맞춘다.
    ⑥ 답의 과제가 전부 걸러졌는데 이전 코멘트에 과제 줄이 있으면 새 답을 버리고 이전 것을 유지한다.
    ⑦ 새 항목에는 n(그 달 신호 수)·n_ai·made(작성 시각) — 다음 실행의 '바뀐 달' 판단 근거."""
    import narratives as _nv
    by_month = defaultdict(list)
    for r in kept:
        by_month[str(r.get("time") or "")[:7]].append(r)
    out = {}
    _rep = os.path.join(ROOT, "report")
    months = _nv.period_months(tag)
    prev = _nv.load_merged(_rep, tag, months)
    valid = sorted(mk for mk in by_month
                   if re.match(r"^\d{4}-\d{2}$", mk) and (months is None or mk in months))
    latest = valid[-1] if valid else ""
    earlier, plan, low, same = set(), [], [], 0
    for mk in valid:
        rows = by_month[mk]
        ai_rows = [r for r in rows if _is_ai_row(r)]
        if len(ai_rows) < min(NARR_MIN_AI_ROWS, len(rows)) or len(ai_rows) < NARR_MIN_AI_SHARE * len(rows):
            low.append(mk)
            print(f"        {mk} AI 판정 행이 적어(AI {len(ai_rows)}/전체 {len(rows)}) "
                  + ("이전 코멘트를 유지합니다" if mk in prev else "코멘트를 만들지 않습니다"))
            if mk in prev:
                earlier.add(mk)
            continue
        pv = prev.get(mk)
        if pv is None:
            pri = 0
        elif mk == latest:
            pri = 1
        else:
            try:
                n0 = int(pv.get("n_ai"))
            except (TypeError, ValueError):
                n0 = None
            if not (force_all or n0 is None or abs(len(ai_rows) - n0) > NARR_CHANGED * max(n0, 1)):
                same += 1
                continue                         # 바뀌지 않은 달 — 이전 코멘트 그대로(보내지 않는다)
            pri = 2
        plan.append((pri, mk, rows, ai_rows))
    plan.sort(key=lambda x: x[1], reverse=True)          # 같은 순위는 최근 달 먼저(안정 정렬 두 번)
    plan.sort(key=lambda x: x[0])
    plan_months = [p[1] for p in plan]
    _NARR_LAST.clear()
    _NARR_LAST.update(plan=list(plan_months), low_ai=list(low), made=[])
    _pc = Counter(p[0] for p in plan)
    print(f"        월별 코멘트 계획 {len(plan)}개월(빠진 달 {_pc[0]} · 최근 달 {_pc[1]} · 다시 만들 달 {_pc[2]})"
          + (f" · 바뀌지 않아 그대로 둔 달 {same}" if same else "")
          + (f" · AI 판정이 적은 달 {len(low)}" if low else "")
          + (" · 모든 달 다시 만들기" if force_all else ""))

    def _flag():
        # 이번 실행에서 새로 만들지 못한 달 — 아직 차례가 오지 않은 달도 넣는다(여기서 끊기면 그대로가 맞다)
        return earlier | {m for m in plan_months if m not in out}
    # 월별 코멘트는 판정 뒤에 오므로 예산의 첫 희생자가 된다 — 판정이 예산을 다 썼어도 최소 몫을 준다
    # (제보: '월간 코멘트가 빠짐' · '진행되다가 안 됨'). 코멘트는 왕복 1회로 한 달이 끝난다.
    # cap_min — 판정 실행 안에서는 상한(기본 20분)을 둬 정제·Agentic 과 같이 쓰는 전체 마감을 덜 먹는다.
    _dl, _bud = _stage_budget(floor_min=20.0)
    if cap_min:
        _cap = time.monotonic() + float(cap_min) * 60.0
        if _dl is None or _cap < _dl:
            _dl, _bud = _cap, float(cap_min)
    _consec = 0
    _n = max(len(plan), 1)
    # LM30(2026-10-21) — 한 실행의 월별 리뷰는 한 채팅(review_chat — 첫 달이 연 채팅에 다음 달을 이어서). 다른 달에만 있는 과제 이름(달별
    # AI 판정 행의 과제)은 '다른 달이 섞였나'를 가르는 데 쓴다(_narr_mixed).
    review_chat = [False]
    names_by = {m: {str(r.get("model")) for r in by_month[m] if _is_ai_row(r) and r.get("model")} for m in valid}
    for _i, (_pri, mk, rows, ai_rows) in enumerate(plan):
        # 예산·연속 실패 관문 — 예전에는 달마다 새 채팅으로 끝까지 시도했고, 그 사이에 부모의 단계 상한에
        # 걸리면 **성공한 달까지 통째로 사라졌다**(저장이 마지막에 한 번뿐이었다).
        if _dl is not None and time.monotonic() > _dl:
            print(f"        시간 예산 {_bud:.0f}분을 넘겨 남은 {len(plan) - _i}개월 코멘트는 만들지 "
                  "않았습니다 — 여기까지는 저장했고 [리뷰 코멘트 재생성]으로 이어서 만들 수 있습니다")
            break
        if _consec >= max_consec:
            print(f"        {_consec}개월 연속 실패 — 남은 {len(plan) - _i}개월은 보내지 않습니다 "
                  "([AI 연결 진단]으로 Copilot 상태를 확인한 뒤 [리뷰 코멘트 재생성])")
            break
        progress("월별 리뷰", _i, _n)
        head = [
            f"당신은 업무 리뷰 작성자입니다. {mk} 한 달의 판정된 업무 신호가 아래에 있습니다.",
            # LM30 — 한 채팅에 달마다 이어 묻는다. 이 질문은 이 달만이다(앞 질문·답은 다른 달 — 섞지 않게 못 박는다)
            f"이 질문은 {mk} 한 달만 다룹니다. 이 대화의 앞선 질문과 답(다른 달)은 참고하지 말고, 이 질문의 [신호] 목록만 근거로 쓰세요.",
            "과제별로 사용자가 어떤 업무에 리소스를 기여했는지, 업무유형(개발/사무/현장/협업)",
            "배분이 어땠는지 서술하세요. 불필요한 정보는 빼고 업무 내용만.",
            # 이 한 줄이 필요한 이유: 예전에는 달마다 같은 채팅을 이어 써서 앞선 달·판정 청크의
            # 신호가 문맥에 남았고, 그 내용이 과거 달 리뷰에 섞여 나왔다(제보). 채팅을 분리한
            # 뒤에도 드라이버가 새 채팅 열기에 실패하면 같은 일이 생기므로 프롬프트에도 못 박는다.
            f"아래 [신호] 목록에 있는 것만 근거로 쓰세요. 목록에 없는 과제·활동은 {mk} 의 일이 "
            "아니므로 쓰지 마세요.",
            "",
            "출력은 JSON 하나만(설명·표·코드블록 없이). story 는 120자 이내:",
            NARRATIVE_EXAMPLE,
            "", "[신호]"]
        head_len = sum(len(x) + 1 for x in head)
        # 한 달 신호가 90건을 넘으면 예전엔 **앞 90건**(월초에 치우침)을 보냈고, 제목이 길면 9,500~10,100자로
        # 한도를 넘겨 2조각으로 나뉘었다(실측). 달 전체에 고르게 퍼진 표본을 예산 안에서 보낸다.
        # 시각에 **연도를 포함**한다 — 예전에는 'MM-DD HH:MM' 이라 다른 달 문맥이 남았을 때
        # 모델이 어느 달 것인지 구분할 근거가 프롬프트 안에 없었다.
        # G3 — 표본 후보(고르게 퍼진 180행)만 관문에 통과시킨 사본에서 고른다. 표본은 **AI 판정 행만** — 판정이
        # 실패한 실행에서는 규칙 행(규칙 토큰·사람 이름 과제)이 달 표본을 채워 엉뚱한 코멘트가 좋은 코멘트를 덮었다.
        lines = _fit_samples(g3_pick(ai_rows, 90), 90, lambda r: (
            f"- {r['time'][:16]} [{r['source']}] {r.get('model', '')}/{r.get('worktype', '')} "
            f"{who_label(r.get('who'), 10)} {(r.get('text') or '')[:80]}"), head_len)
        if not lines:
            print(f"        {mk} 내러티브 — 관문을 통과한 신호가 없어 보내지 않습니다(이전 코멘트 유지)")
            continue
        prompt = "\n".join(head + lines)
        # ★ 첫 달은 **새 채팅**에서 묻는다. 예전에는 fresh 를 주지 않아 '같은 채팅에서 이어서' 가 됐고,
        # narrate 는 judge.main 끝에서 돌므로 그 채팅에는 이미 **분석 기간 전체**(최근 달 포함)의 판정
        # 청크가 들어 있었다. 그래서 6월 리뷰에 8~9월 일이 적히는 일이 생겼다(제보).
        # LM30(2026-10-21) — 다음 달부터는 그 리뷰 채팅에 이어 묻는다(fresh=None — 앞 달이 실패·해석 실패면 copilot_send 가 새 채팅). 예전에는
        # 달마다 새 채팅이라 첫 실행·폴더를 합친 실행에서 리뷰 채팅만 10개씩 대화 목록에 쌓였다(사용자 제보). 섞임은 프롬프트의 '이 달만' 줄로
        # 막고, 그래도 답에 다른 달(다른 YYYY-MM · 이 달에는 없고 다른 달에만 있는 과제)이 보이면 그 달만 새 채팅에서 한 번 더 묻는다.
        fr = None if review_chat[0] else True
        o = None
        for _try in (0, 1):
            res = copilot_send(prompt, tag, f"narr_{mk}", fresh=fr)
            if res.get("phase") == "blocked":
                # 최종 검사는 프롬프트 전체(과제명·상대 표기 포함)를 본다 — 표본 단계는 text 열만 정제하므로 한 줄
                # 때문에 그 달 전체가 막히던 경로(LM24 에 없던 것). 걸린 줄만 빼고 한 번 더 보낸다.
                ok_lines = [ln for ln in lines if g3_prompt(ln)]
                if 20 <= len(ok_lines) < len(lines):
                    print(f"        {mk} 내러티브 — 관문에 걸린 신호 {len(lines) - len(ok_lines)}줄을 빼고 다시 보냅니다")
                    res = copilot_send("\n".join(head + ok_lines), tag, f"narr_{mk}", fresh=fr)
            if res.get("phase") == "blocked" or not res.get("ok"):
                break
            review_chat[0] = True                  # 리뷰 채팅이 열렸다 — 다음 달은 이어서
            o = rfind_json(res.get("reply", ""), "summary", skip=(NARRATIVE_EXAMPLE,)) \
                or repair_json(res.get("reply", ""), "summary", skip=(NARRATIVE_EXAMPLE,))
            if (_try == 0 and fr is None and o and str(o.get("summary") or "").strip()
                    and _narr_mixed(o, mk, names_by)):
                print(f"        {mk} 리뷰에 다른 달 내용이 섞여 새 채팅에서 이 달만 한 번 더 묻습니다")
                fr = True
                continue
            break
        if res.get("phase") == "blocked":
            # 개인정보 관문 — 보내지 않았다. 실패가 아니므로 연속 실패에 넣지 않는다(이전 코멘트 유지)
            print(f"        {mk} 내러티브 — 개인정보 관문에 걸려 보내지 않았습니다(이전 코멘트 유지)")
            continue
        if res.get("ok"):
            if o and str(o.get("summary") or "").strip():
                # 답이 든 과제 이름이 **그 달에 실제로 있는 이름**인지 확인한다. 예전에는 아무 검증이
                # 없어, 프롬프트 예시의 '프로젝트A' 같은 것이 그대로 리뷰에 실릴 수 있었다(같은 계열의
                # 에코 사고가 rfind_json 주석에 실측으로 남아 있다). 없는 이름은 그 항목만 버리고,
                # 남긴 항목은 체계 표기로 맞춘다(보낸 표본 = AI 판정 행의 과제 + '공통').
                real = {_nm_key(n): n for n in ({r.get("model") for r in ai_rows if r.get("model")} | {"공통"})}
                keep, drop, _seen = [], [], set()
                for p in _as_list(o.get("projects")):
                    if not isinstance(p, dict):
                        continue
                    nm = _narr_name(p.get("name"), real)
                    if nm and nm not in _seen:
                        _seen.add(nm)
                        keep.append(dict(p, name=nm))
                    elif not nm and str(p.get("name") or "").strip():
                        drop.append(str(p.get("name")).strip())
                if drop:
                    print(f"        {mk} 리뷰에서 이 달에 없는 과제 {len(drop)}건 제외: "
                          + ", ".join(drop[:3]) + (" …" if len(drop) > 3 else ""))
                if not keep and drop and (prev.get(mk) or {}).get("projects"):
                    # 과제 줄이 모두 빠진 새 답(요약 한 줄)으로 과제 줄이 있는 이전 코멘트를 덮지 않는다
                    print(f"        {mk} 내러티브 — 답의 과제가 이 달 과제와 하나도 맞지 않아 이전 코멘트를 유지합니다")
                    earlier.add(mk)
                    _consec = 0
                    continue
                o["projects"] = keep
                o.update(n=len(rows), n_ai=len(ai_rows), made=time.strftime("%Y-%m-%d %H:%M"))
                out[mk] = o
                _consec = 0
                save_narratives(out, _rep, tag, earlier=_flag(), quiet=True)   # 달마다 즉시 저장(늘 이월) — 끊겨도 이 달은 남는다
                print(f"        {mk} 내러티브 ✓" + (" (잘린 응답 일부 복구)" if res.get("cut") else ""))
                continue
            note_bad_reply()
            _why, _how, _fatal = "응답에서 코멘트 JSON 을 찾지 못함", "", False
        else:
            # explain_failure 는 (사유, 조치, fatal) 세 값을 돌려준다(core/details.py)
            _why, _how, _fatal = explain_failure(res) if isinstance(res, dict) else ("", "", False)
        _consec += 1
        print(f"        {mk} 내러티브 실패 — 건너뜀" + (f" ({_why[:60]})" if _why else ""))
        if _fatal:
            print("        사람이 손대야 풀리는 상태입니다 — 남은 달은 보내지 않습니다: " + _how[:80])
            break
    progress("월별 리뷰", _n, _n)
    _NARR_LAST["made"] = sorted(out)
    # 끝 저장 — 새로 만들지 못한 달(AI 판정 부족·실패·관문·덮어쓰기 방지·남은 차례)에 earlier 표식을 남긴다.
    # 표식할 것도 새 달도 없으면 호출자의 save_narratives(이월만)에 맡긴다. 이월 요약 줄은 호출자의 저장이 한 번 찍는다.
    if out or (_flag() & set(prev)):
        save_narratives(out, _rep, tag, earlier=_flag(), quiet=True)
    return out


def _stage_budget(floor_min=15.0):
    r"""core.budget.stage_budget 위임 — v3 에서 3벌 사본을 한 벌로 모았다(구조 감사:
    사본 유사도 0.925~1.000 · 정책 수정이 한 곳씩 빠지던 원인). 시그니처는 관행 유지."""
    from budget import stage_budget
    return stage_budget(floor_min=floor_min, root=ROOT, now=time.time, mono=time.monotonic)


def save_narratives(nar, rep, tag, carry=True, earlier=(), quiet=False):
    r"""월별 내러티브 저장 — core/narratives.save 위임(제보: '월별 코멘트가 빠짐' · '월간 리뷰 코멘트가 사라짐').
    매 저장(달마다 하는 중간 저장 포함)이 늘 ① 같은 tag 의 기존 달 + 다른 기간(tag) 파일에서 빠진 달을 이월하고
    ② 기간 밖의 달은 거르고 ③ 원자적으로 쓴다(깨진 자기 파일은 .corrupt 로 보존). 하나도 없으면 쓰지 않는다.
    예전에는 중간 저장이 이월 없이(carry=False) 오늘 파일을 만들어, narrate 가 도는 동안·끊긴 뒤에 이전 달이
    화면에서 가려졌다. carry 는 호환용 인자(무시 — 이제 항상 이월한다).
    earlier: 이번 실행에서 새로 만들지 못한 달 — 기존 코멘트가 있으면 earlier=True 표식(화면 '이전 실행 코멘트').
    quiet: '0개'·이월 요약 줄을 찍지 않는다(narrate 안의 달마다 저장 — 요약은 호출자의 마지막 저장이 한 번 찍는다).
    반환: 저장했으면 True."""
    import narratives as _nv
    return _nv.save(rep, tag, nar or {}, months=_nv.period_months(tag), earlier=earlier, quiet=quiet)


def main():
    import extract
    d0, d1 = arg("--from"), arg("--to")
    # 80행은 입력 한도(9,000자)를 넘긴다 — 40행 ≈ 6,500자가 안전값(실측). 넘치면 드라이버가
    # 조각으로 나눠 보내지만 왕복이 그만큼 늘어난다.
    chunk_n = chunk_default("judgeChunk", 40)
    tag = f"{d0.replace('-','')}-{d1.replace('-','')}"
    rep = os.path.join(ROOT, "report")
    sp = os.path.join(rep, f"signals_{tag}.csv")
    if not os.path.exists(sp):
        print(f"[judge] 입력 없음 — 먼저 mine.py 실행 ({sp})")
        return 1
    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))
    if not rows:
        print("[judge] 신호 0건")
        return 1

    # 9a — 리뷰 코멘트만 다시 생성. 다른 PC로 옮기면 report\ 를 복사하지 않으므로
    # 월별 코멘트가 비어 보인다. 판정된 signals 만 있으면 되살릴 수 있다.
    # [리뷰 코멘트 재생성] 기본은 빠진 달·최근 달·데이터가 바뀐 달만, --all 이면 모든 달을 다시 만든다.
    if "--narrate-only" in sys.argv:
        kept = [r for r in rows if (r.get("judge") or "").strip()]
        if not kept:
            print("[judge] AI 판정 결과가 없습니다 — 'AI 판정'을 켜고 분석을 먼저 돌리세요")
            return 1
        # '규칙' 행만으로는 만들지 않는다 — AI 판정이 전부 실패한 실행(rc 3)도 signals 를 judge='규칙' 으로 다시
        # 쓰므로, 예전에는 그 뒤 이 버튼이 모든 달을 규칙 토큰으로 다시 만들어 좋은 코멘트를 덮었다.
        ai_n = sum(1 for r in kept if _is_ai_row(r))
        if not ai_n:
            print("[judge] AI 판정된 신호가 없습니다 — 규칙 결과로는 코멘트를 만들지 않습니다(기존 코멘트 유지)")
            save_narratives({}, rep, tag)          # 이월만(다른 기간 파일의 코멘트를 이 기간으로) — 왕복 없음
            return 1
        meta_p = os.path.join(rep, f"mm_meta_{tag}.json")
        mj = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
        total_mm = float(mj.get("total_mm") or 0)
        force_all = "--all" in sys.argv
        print(f"[judge] 리뷰 코멘트 재생성 — 판정 신호 {len(kept)}건(AI 판정 {ai_n}건) · "
              + ("모든 달 다시 만들기" if force_all else "빠진 달·최근 달·데이터가 바뀐 달만"))
        nar = narrate(kept, total_mm, tag, force_all=force_all, cap_min=None)
        saved = save_narratives(nar, rep, tag)
        if not _NARR_LAST.get("plan"):
            print("[judge] 다시 만들 달이 없습니다 — "
                  + ("AI 판정 행이 적은 달은 이전 코멘트를 그대로 둡니다" if _NARR_LAST.get("low_ai")
                     else "모든 달의 코멘트가 최신입니다(모두 다시 만들려면 전체 다시 만들기)"))
            return 0
        print(f"[judge] 월별 코멘트 {len(nar)}/{len(_NARR_LAST['plan'])}개월 새로 만듦 · "
              + ("저장(나머지 달은 이전 코멘트 유지)" if saved else "기존 파일 유지"))
        chat_note()
        return 0 if nar else 1
    from stage_state import open_stage
    _ss = open_stage(rep, tag, "judge")        # v3 상태 파일 — 하트비트·진행·중단 사유(구조 감사 4계층)
    cfg = extract.load_cfg()
    known = cfg.get("projects") or []
    model_name = (cfg.get("copilotAuto") or {}).get("model", "GPT-5.6")

    # 사용자 지정 프로젝트(UI에서 입력) — 힌트가 아니라 고정 엔티티로 체계에 항상 포함
    import projmap
    pinned = [{"name": p["name"], "match": p.get("match") or [], "desc": p.get("desc", ""),
               "obs": "사용자 지정", "pinned": True}
              for p in projmap.load_user_projects(ROOT)]
    pinned_l = {p["name"].lower() for p in pinned}
    # LM28 진단 B — 과제명 관문 재료: 사람 이름 키(signals 의 who 열에서만 뽑는다 — 코드에 이름을 두지 않는다)·지정 과제 키
    people = details.person_keys(r.get("who") for r in rows)
    pinned_keys = {ukey2(p["name"]) for p in pinned}

    # 지난 분석에서 발견된 과제도 힌트로 (실행 간 일관성) — 채택 여부는 이번 raw 관찰이 결정.
    # 규칙 폴백 체계("fallback": true)는 건너뛰고 첫 정상 체계를 쓴다 — 사람 이름·공지류는 관문(sanitize_models)이 뺀다.
    import glob as _glob
    prev_ms, prev_path = _load_prev_entities(rep, people)
    prev_models = [m["name"] for m in prev_ms if m["name"] != "공통"]
    hints = [h for h in dict.fromkeys(list(known) + prev_models) if h.lower() not in pinned_l]

    # [재개·묶음] — 체계 왕복보다 먼저(LM28 진단 A). 지난 판정(다른 날짜 기간 포함)을 내용 키로 회수하고, 같은 내용은 대표
    # 한 줄만 보낸다. 보낼 것이 없고 지난 정상 체계가 있으면 체계·통합 왕복도 건너뛴다.
    # (v3 '이어서 판정' 은 같은 tag 파일에서만 회수해, 기간 끝날짜가 날마다 바뀌는 기본 기간에서는 매일 처음부터 다시 물었다.)
    today = time.strftime("%Y-%m-%d")
    # 회의 안건(LM28 — config.calendar.bodyToAI): 안건이 붙은 회의 행은 내용 키에 안건을 넣는다 — 안건이 생기거나 바뀐 회의만
    # 한 번 다시 판정하고, 안건이 없는 행의 키(그리고 그 캐시)는 그대로다. 캐시 파일에는 키의 sha1 만 남는다(안건 원문 없음)
    notes = meeting_notes(rows, cfg, d0, d1)
    ckeys = [_ckey(signal_sig2(r) + (NOTE_KEY_SEP + notes[i] if i in notes else "")) for i, r in enumerate(rows)]
    judged, n_fail, n_partial, last_err = {}, 0, 0, ""
    redo = "--redo" in sys.argv                   # 처음부터 판정 — 캐시를 새로 시작한다(옛 판정 기록도 잇지 않는다)
    cache = {"v": JUDGE_CACHE_V, "since": time.time(), "migrated": True, "items": {}} if redo else load_judge_cache(rep)
    citems = cache["items"]
    # 짧은 팀즈 대화(LM30 2026-10-27 — 맞장구·호칭·시각·문장 끝 꼴뿐인 줄)는 판정 캐시를 쓰지 않는다(v2). 예전 같은 문장 묶음이
    # 다른 방·다른 과제의 판정을 옮겨 놓았을 수 있어, 그 항목은 지우고 아래에서 같은 대화의 판정으로 다시 채운다(왕복 없음).
    generic = {i for i, r in enumerate(rows) if is_lowinfo(r)}
    n_exact = n_named = n_generic_old = 0
    if not redo:
        # 캐시 이전 판의 판정 기록은 캐시가 처음 생길 때 한 번만 이어받는다(그 뒤의 판정은 모두 캐시에 있다)
        legacy = {} if cache.get("migrated") else _legacy_judgments(rep, tag, cache.get("since") or 0.0)
        for i in range(len(rows)):
            if i in generic:
                if citems.pop(ckeys[i], None) is not None or ckeys[i] in legacy:
                    n_generic_old += 1
                continue
            e = citems.get(ckeys[i])
            j = _from_cache(e)
            from_legacy = j is None
            if from_legacy:
                j = _from_cache(legacy.get(ckeys[i]))
                if j is None:
                    continue
            if j["work"] and not _cached_name_ok(j["model"], people, pinned_keys):
                n_named += 1                      # 사람 이름·공지류 과제로 판정된 옛 판정 — 다시 묻는다(진단 B)
                continue
            if from_legacy:
                citems[ckeys[i]] = _cache_entry(j, today)     # 캐시 이전 판의 기록 → 캐시로 옮긴다
            else:
                e["at"] = today                   # 마지막으로 쓴 날 — 상한을 넘기면 오래 안 쓴 것부터 뺀다
            judged[i] = dict(j, via="cache")
        n_exact = len(judged)
    # G3 — 광고 의심(signals flag 'ad') 행은 Copilot 에 보내지 않고 비업무로 둔다(LM24 에서 AI 가 'n' 으로 거르던 것)
    ad_idx = {i for i, r in enumerate(rows) if i not in judged and is_ad_row(r)}
    if ad_idx:
        print(f"[judge] 광고 의심 신호 {len(ad_idx)}건은 보내지 않고 비업무로 둡니다(개인정보 관문 G3)")
    gkeys = [group_key(r) for r in rows]
    for i, nt in notes.items():                   # 안건이 붙은 회의는 안건까지 같아야 한 묶음이다(Copilot 이 보는 줄이 같게)
        if gkeys[i] is not None:
            gkeys[i] = (gkeys[i][0], gkeys[i][1] + NOTE_SEP + nt)
    # (a) 같은 내용 재사용 — 지난 판정이 있는 묶음 키의 새 행(옛 스레드의 새 회신 등)은 왕복 없이 그 판정을 쓴다.
    #     팀즈는 쓰지 않는다(LM30 2026-10-27 — 같은 문장이 다른 날·다른 일로 오가는 대화라 지난 판정을 옮기면 과제가 하나로 묶였다)
    by_key = defaultdict(Counter)
    for i, j in judged.items():
        if gkeys[i] is not None:
            by_key[gkeys[i]][_jt(j)] += 1
    n_keyed = 0
    for i in range(len(rows)):
        if i in judged or i in ad_idx or gkeys[i] is None or gkeys[i] not in by_key or _fam(rows[i]) == "팀즈":
            continue
        judged[i] = dict(_jd(by_key[gkeys[i]].most_common(1)[0][0]), via="reuse")
        citems[ckeys[i]] = _cache_entry(judged[i], today)
        n_keyed += 1
    # (b) 짧은 팀즈 대화(인사·맞장구·호칭·시각·문장 끝 꼴뿐)는 보내지 않는다 — 실패가 아니다(아래에서 같은 대화의 판정으로 채운다)
    lowinfo = {i for i in generic if i not in judged and i not in ad_idx}
    # (c) 남은 행은 같은 내용끼리 묶어 대표만 보낸다(대표의 판정을 구성원 전체에)
    todo = [i for i in range(len(rows)) if i not in judged and i not in ad_idx and i not in lowinfo]
    reps, members = group_reps(rows, todo, gkeys)
    n_members = sum(len(v) for v in members.values())
    n_reused = n_exact + n_keyed
    if n_reused or n_named:
        print(f"[judge] 이어서 판정 — 지난 실행(다른 날짜 포함) {n_reused}건 재사용"
              + (f"(같은 내용 {n_keyed}건 포함)" if n_keyed else "")
              + (f" · 사람 이름·공지류 과제로 판정된 {n_named}건은 다시 판정" if n_named else "")
              + f" · 남은 {len(todo)}건")
    if n_generic_old:
        print(f"        짧은 팀즈 대화의 지난 판정 {n_generic_old}건은 다시 쓰지 않고 같은 대화에서 채웁니다(판정 캐시 v2 — 왕복 없음)")
    if lowinfo:
        print(f"        짧은 팀즈 대화(인사·맞장구·호칭·시각뿐) {len(lowinfo)}건은 보내지 않고 같은 대화의 판정으로 채웁니다")
    if members:
        print(f"        같은 내용 묶음 — 대표 {len(members)}줄이 {len(members) + n_members}행을 대신합니다"
              f"(보낼 줄 {len(reps)})")
    # 체계·통합 표본은 같은 내용을 한 줄로(광고·짧은 대화 제외) — 팀즈 잡담·스레드 회신이 표본을 덮지 않게(진단 B)
    _sreps, _sm = group_reps(rows, [i for i in range(len(rows)) if i not in ad_idx and i not in lowinfo], gkeys)
    sample_rows = [rows[i] for i in _sreps] or rows
    st = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_rows": 0, "omitted_rows": 0,
          "notes": [], "last_err": "", "soft": False, "aborted": False, "gated_rows": 0,
          "gated_idx": set(), "omitted_idx": set(), "group_rows": 0, "abort_kind": "", "abort_reason": "",
          "meet_notes": notes}                    # 회의 안건 {행 번호: 안건} — judge_rows 가 그 회의 줄에만 붙인다

    # [0] 엔티티 체계 — 지정은 항상 포함(코드로 강제), 나머지는 AI가 raw에서 자동 발견
    n_chunks = -(-len(reps) // chunk_n)
    res, _fatal0, used_fallback, reused_tax = {}, False, False, False
    models = []
    if not reps and prev_ms:
        # 보낼 신호가 없다(전부 재사용·짧은 대화·광고) — 체계·통합 왕복을 하지 않고 지난 정상 체계를 쓴다
        models = sanitize_models(pinned + prev_ms, people)
        tax_ok, reused_tax = True, True
        print(f"[judge] 보낼 신호가 없어 체계 수립 왕복을 건너뜁니다 — 지난 체계 재사용({os.path.basename(prev_path)})")
        print("        모델: " + ", ".join(m["name"] for m in models[:10]))
    else:
        progress("AI 판정", 0, n_chunks + 1)
        print(f"[judge] 0/{n_chunks + 1} 엔티티 체계 수립 왕복 (모델 {model_name}"
              + (f" · 지정 {len(pinned)}개" if pinned else "") + ") — 응답까지 수십 초 걸립니다")
        res = copilot_send(taxonomy_prompt(sample_rows, hints, pinned), tag, "taxonomy")
        # 이 왕복이 사실상 프로브다 — 로그인이 안 됐으면 여기서 이미 드러난다. 다만 **한 번으로
        # 단정하지는 않는다**(아래 주석). 규칙 판정은 어떤 경우에도 돌아 signals·mm_rows·보고서가
        # 나오므로, 사용자는 결과를 받고 로그인 뒤 [재분석만]으로 이으면 된다.
        _why0, _how0, _fatal0 = explain_failure(res)
        tax_ok = bool(res.get("ok"))          # 체계 왕복 성공 여부 — entities 저장 관문이 본다
        if _fatal0:
            print(f"[judge] 체계 수립 왕복이 실패했습니다 — {_why0}")
            print(f"        {_how0}")
            print("        규칙 판정으로 신호·MM·보고서는 그대로 만듭니다. 로그인 뒤 [재분석만]을 누르면 "
                  "AI 판정만 이어서 합니다.")
        if res.get("ok"):
            o = (rfind_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,))
                 or repair_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,)))
            models = [m for m in _as_list(o.get("models"))
                      if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"].strip()]
            if not models:
                note_bad_reply()
        # AI가 지정 과제의 match를 보강했으면 병합해 pinned에 흡수 (표기·설명은 사용자 것이 우선)
        for m in models:
            for p in pinned:
                if str(m.get("name", "")).strip().lower() == p["name"].lower():
                    p["match"] = list(dict.fromkeys(p["match"] + [str(k).lower() for k in _as_list(m.get("match"))]))
        # 9d — 초안이 2개를 넘으면 한 번 더 물어 같은 실체를 통합한다(--fast 로 생략 가능)
        if len(models) > 2 and "--fast" not in sys.argv:
            progress("AI 판정", 0, n_chunks + 2)
            print("[judge] 0b 과제 체계 통합 왕복 (같은 실체가 갈리는 것 방지)")
            draft = sanitize_models(models, people)
            rc = copilot_send(consolidate_prompt(draft, sample_rows), tag, "consolidate")
            if rc.get("ok"):
                o2 = rfind_json(rc.get("reply", ""), "models", skip=(CONSOLIDATE_EXAMPLE,))
                cand = [m for m in _as_list(o2.get("models")) if isinstance(m, dict) and m.get("name")]
                if cand and len(cand) <= len(models):
                    merged_names = [m["name"] for m in cand]
                    print("        통합 후: " + ", ".join(merged_names[:10]))
                    for _ln in merge_log_lines(cand):      # 무엇을 무엇에 합쳤는지(LM30 2026-10-27) — 과병합을 로그로 찾게
                        print("        " + _ln)
                    models = apply_merges(cand, draft)     # 통합 응답에 없는 product·l1 은 초안에서 옮긴다
                else:
                    print("        통합 결과가 유효하지 않아 초안 유지")
            else:
                print("        통합 왕복 실패 — 초안 유지")
        models = sanitize_models(pinned + models, people)   # 지정이 앞 → 중복 시 사용자 표기가 대표
        # AI가 새 과제를 하나도 못 주면(왕복 실패든, 성공했지만 산문 응답으로 파싱 실패든) 규칙 폴백 —
        # 지정 + 지난 정상 체계 + 걸러진 규칙 토큰. entities 에 "fallback": true 를 남겨 다음 실행·mine 이 되먹지 않게 한다.
        ai_added = any(not m.get("pinned") and m["name"] != "공통" for m in models)
        if not ai_added and not (res.get("ok") and rfind_json(res.get("reply", ""), "models",
                                                             skip=(TAXONOMY_EXAMPLE,))):
            models = sanitize_models(pinned + fallback_models(rows, known, people, prev_ms), people)
            used_fallback = True
            print("        체계 수립 실패(왕복 또는 응답 파싱) — 지정+지난 체계+규칙 발견 후보로 폴백")
        else:
            print("        모델: " + ", ".join(m["name"] for m in models[:10]))
    # entities 파일은 판정이 끝난 뒤에 쓴다 — 판정이 0건(왕복 전부 실패)이면 기존 파일을
    # 규칙 폴백 체계로 덮지 않고 보존한다(F3)
    ent_p = os.path.join(rep, f"entities_{tag}.json")
    ent_obj = {"models": models, "worktypes": WORKTYPES, "hints_used": hints}
    if used_fallback:
        ent_obj["fallback"] = True                # 규칙 폴백 체계 — 지난 체계로 되먹이지 않는다(details.entities_is_fallback)
    if reused_tax:
        ent_obj["reused_from"] = os.path.basename(prev_path)
    ent_prev = os.path.exists(ent_p)

    # [1..N] 신호 판정 — 대표 행만, 행 수(chunk_n)와 글자 예산 둘 다로 자른다. 머리말 길이는 과제 목록과
    # '앞서 쓴 이름' 목록 상한을 포함해 잰다.
    # 회의 안건이 있으면 그 줄 길이(안건 포함)와 머리말 안내 한 줄까지 예산에 넣는다(넘치면 드라이버가 나눠 왕복이 늘어난다)
    head_len = len(judge_prompt([], 0, models)) + SEEN_MAX_CHARS + 160 + (len(NOTE_HINT) + 1 if notes else 0)
    plan = pack_chunks([dict(rows[i], note=notes[i]) if i in notes else rows[i] for i in reps], chunk_n, head_len)
    chunks = [reps[s:s + n] for s, n in plan]          # 청크마다 대표 행 번호(원본 행 인덱스)
    if len(chunks) != n_chunks and not n_reused:
        print(f"        글자 예산({PROMPT_BUDGET:,}자)에 맞춰 청크 {n_chunks}→{len(chunks)}개"
              f" (머리말 {head_len:,}자 · 행 최대 {max((n for _s, n in plan), default=0)}개)")
    n_skip = 0                                 # 개인정보 관문에 막혀 보내지 않은 청크(연속 실패 계수 밖)
    if _fatal0:
        # ★ 체계 수립 왕복 **한 번**으로 '사람이 손대야 풀리는 실패' 라고 단정하지 않는다.
        # 일시적 실패(입력창을 아직 못 찾음 등)도 같은 얼굴로 오는데, 예전 판본은 그 한 번에
        # AI 판정 전체를 건너뛰었다 — 그러면 정제가 생략되고 run.py 가 이미 .stale 로 개명한
        # 정제본이 돌아오지 않아 **상위과제 분류가 빈칸**이 됐다(실측 제보·재현).
        # 그래서 청크를 하나만 더 보내 확인한다. 그것도 같은 실패면 청크 루프 끝의 관문이
        # aborted 로 접는다: 진짜 로그인 필요 PC 는 왕복 2회(약 1분, 예전 49회·28분)로 끝나고,
        # 일시적 실패였으면 예전처럼 끝까지 판정된다.
        print("        확인을 위해 첫 청크 하나만 보내 봅니다 — 같은 실패면 거기서 접습니다.")
    consec, prev_idxs = 0, ()
    _dl, _bud = _stage_budget()
    _budget_stop = ""
    for ci, idxs in enumerate(chunks):
        n = len(idxs)
        # 예산 관문 — **스스로** 멈추고 아래 저장·내러티브 경로를 그대로 탄다(종료코드 0).
        # 예전에는 부모의 상한에 끊겨 종료코드가 0 이 아니었고, 그러면 run.py 가 정제·Agentic·
        # 워크플로우를 전부 건너뛰고 월별 코멘트도 만들지 못했다(제보).
        if _dl is not None and _budget_stop == "" and time.monotonic() > _dl:
            if _ss is not None:
                _ss.note_resume(pending=len(plan) - ci)
            _budget_stop = (f"시간 예산 {_bud:.0f}분을 넘겨 남은 {len(plan) - ci}청크를 보내지 "
                            "않았습니다 — 여기까지의 판정을 저장하고 월별 코멘트까지 만든 뒤 끝냅니다"
                            "(다시 실행하면 남은 신호만 이어서 판정합니다 · config.aiStageBudgetMin)")
            print(f"[judge] {_budget_stop}")
            if not st["abort_kind"]:
                st["abort_kind"], st["abort_reason"] = "budget", _budget_stop
            save_judge_cache(rep, cache, d0, prune=False)
        if _budget_stop:
            st["failed_rows"] += n
            n_fail += 1
            continue
        progress("AI 판정", ci + 1, len(chunks) + 1)
        if st["aborted"]:
            st["failed_rows"] += n
            n_fail += 1
            continue
        _cover = sum(len(members.get(i, ())) for i in idxs)
        print(f"[judge] {ci+1}/{len(chunks)} 신호 판정 왕복 (#{idxs[0]}~#{idxs[-1]}"
              + (f" · 같은 내용 {_cover}행 포함" if _cover else "") + ")")
        st["notes"] = []
        st["_skipped"] = False
        _g0 = st["gated_rows"]
        got = judge_rows(idxs, rows, models, recent_details(judged, prev_idxs), tag, f"chunk{ci+1}", 0, st)
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
            # 묶음마다 캐시에 저장 — 중간에 끊겨도(감시기 종료·예외) 여기까지의 판정은 다음 실행이 다시 묻지 않는다
            for i in got:
                for m in (i, *(members.get(i, ()))):
                    citems[ckeys[m]] = _cache_entry(judged[m], today)
            save_judge_cache(rep, cache, d0, prune=False)
        elif st.get("_skipped"):
            # 개인정보 관문(G3)에 막혀 보내지 않았다 — 실패가 아니므로 연속 실패 계수에 넣지 않는다(그 행만 규칙 판정)
            n_skip += 1
        else:
            consec += 1
            n_fail += 1
            last_err = st.get("last_err") or last_err
        note = ("" if not st["notes"] else " · " + " / ".join(st["notes"][:4]))
        print(f"        판정 {len(got)}/{n}건" + (f"(+같은 내용 {_n_mem}행)" if _n_mem else "") + note)
        if st.get("fatal"):
            # 사람이 손대야 풀리는 상태(로그인 만료·강한 사용량 제한 등) — 6청크를 기다릴 이유가 없다. 바로 규칙 판정으로 넘긴다.
            st["aborted"] = True
            st["abort_kind"] = st.get("fatal_kind") or "fatal"
            st["abort_reason"] = st["fatal"]
            print(f"        {st['fatal']}")
            print("        남은 청크는 규칙 판정으로 둡니다 — 해결한 뒤 [재분석만]을 누르면 AI 판정만 이어서 합니다.")
            save_judge_cache(rep, cache, d0, prune=False)
        elif consec >= ABORT_FAIL_CHUNKS:
            st["aborted"] = True
            st["abort_kind"] = "content"
            st["abort_reason"] = (f"연속 {consec}청크 0건"
                                  + (f" — {st.get('last_err')}" if st.get("last_err") else ""))[:300]
            print(f"        연속 {consec}청크 0건 — 남은 청크는 규칙 판정으로 둡니다"
                  "(Copilot 상태를 확인한 뒤 재실행하면 이어서 판정됩니다)")
            save_judge_cache(rep, cache, d0, prune=False)
        elif consec >= SOFT_FAIL_CHUNKS and not st["soft"]:
            st["soft"] = True
            print(f"        연속 {consec}청크 0건 — 적응 재시도(반분·빠진 행)를 끄고 1회씩만 시도합니다")
    if _fatal0 and not chunks and not st.get("fatal"):
        # 체계 왕복이 사람이 손댈 실패(로그인 만료·강한 사용량 제한)였고 확인할 묶음이 없다 — 월별 코멘트도 보내지 않는다
        st["fatal"] = f"{_why0} — {_how0}"
        st["aborted"] = True
        st["abort_kind"], st["abort_reason"] = _abort_kind_of(res), st["fatal"]
    if st["aborted"]:
        print(f"        중단으로 건너뛴 청크 포함 0건 청크 {n_fail}/{len(chunks)}")
    if n_skip or st["gated_rows"]:
        print(f"        개인정보 관문(G3): 보내지 않은 청크 {n_skip}개 · 규칙 판정으로 둔 행 {st['gated_rows']}건"
              " (연속 실패로 세지 않음)")
    save_judge_cache(rep, cache, d0)              # 끝 저장 — 가지치기(오래 안 쓴 판정·상한) 포함

    # AI 가 직접 못 본 행 채우기(진단 A) — 같은 내용·같은 대화·규칙 토큰·비슷한 판정 순. 관문 행·광고는 채우지 않는다.
    # 채운 판정은 판정 기록(items)·캐시에 넣지 않는다(다음 실행이 AI 에 다시 묻는다).
    gated = st["gated_idx"]
    unseen = [i for i in range(len(rows)) if i not in judged and i not in ad_idx and i not in gated]
    fills = fill_unjudged(rows, judged, unseen, gkeys)
    filled_n = Counter(how for _j, how in fills.values())

    # 판정 반영 — 한 곳에서(진단 B): AI 유래 과제명은 final_model(사람 이름·공지류·잡음 → '공통'), 사람 이름 세부업무는 활동명.
    # 미판정 행은 match 키워드로 매핑(강한 행정 공지 제목은 '공통/공지·근태' · 짧은 팀즈 대화는 협업).
    shutil.copy2(sp, os.path.join(rep, f"signals_{tag}_rules.csv"))
    kept, dropped_rows = [], []
    for i, r in enumerate(rows):
        j = judged.get(i)
        if j is None and i in fills:
            j = fills[i][0]
        if j is None and i in ad_idx:
            r["judge"] = "ad"
            dropped_rows.append(r)          # 광고 의심 — 비업무(시간 재산정에서도 뺀다)
            continue
        if j is None:
            if details.is_notice_subject(r.get("text")):
                r.update(model="공통", worktype="사무", detail="공지·근태", judge="규칙")
            else:
                r.update(model=rule_model(r, models), worktype=("협업" if i in lowinfo else "사무"),
                         detail=r.get("activity") or "기타", judge="규칙")
            r["via"] = "rule"
            kept.append(r)
        elif not j["work"]:
            r["judge"] = "AI-n"
            dropped_rows.append(r)          # 비업무 — 시간 재산정(rehours_meta)에서도 뺀다(본인 발신 시각 근거는 extract 가 남긴다)
        else:
            dt = j["detail"] or r.get("activity") or "기타"
            if details.is_person_name(dt, people):
                dt = r.get("activity") or "기타"
            r.update(model=final_model(j["model"], models, people, pinned_keys), worktype=j["worktype"] or "사무",
                     detail=dt, judge=("AI(유사)" if j.get("via") in ("conv", "token", "sim") else "AI"),
                     # 과제를 받은 길(LM30 2026-10-27 — 이 PC 화면의 근거 한 줄용 · 팀 반출에서 뺀다): ai 직접 · group 같은 문장 묶음 ·
                     # cache 지난 판정 · reuse 지난 판정의 같은 문장 · same/conv/token/sim 채움
                     via=str(j.get("via") or "ai"))
            kept.append(r)
    rule_rows = sum(1 for r in kept if r.get("judge") == "규칙")
    # 실패 행 다시 세기 — 판정 없음 − 광고 − 관문 − 짧은 대화 − 모델이 빠뜨린 행(대표가 실패하면 구성원도 실패다)
    _unj = {i for i in range(len(rows)) if i not in judged and i not in ad_idx}
    st["omitted_rows"] = len(_unj & st["omitted_idx"])
    st["failed_rows"] = len(_unj - gated - lowinfo - st["omitted_idx"])
    st["gated_rows"] = max(int(st["gated_rows"]), len(_unj & gated))
    if fills:
        print(f"        AI 가 직접 못 본 행 {len(unseen)}건 중 {len(fills)}건을 비슷한 판정으로 채움(같은 내용 "
              f"{filled_n['same']} · 대화 {filled_n['conv']} · 규칙 토큰 {filled_n['token']} · 비슷한 신호 {filled_n['sim']})")
    # 사용자 지정 규칙 자동 재적용 — AI가 '공통'·자동발견으로 판정한 신호라도 지정
    # 프로젝트의 이름·키워드가 원문에 직격이면 지정으로 귀속 (재분석해도 지정이 무음 소실되지 않게)
    if pinned:
        rn, rby, _rev = projmap.retag_rows(kept, projmap.load_user_projects(ROOT))
        if rn:
            print("        지정 규칙 자동 적용: "
                  + " · ".join(f"{k} {v}건" for k, v in sorted(rby.items(), key=lambda x: -x[1])))
    # 유사 세부업무 통합을 signals 저장 '전에' 끝낸다 — 리뷰 탭(signals)과 대시보드(mm_rows)의
    # 세부업무 이름이 갈리지 않게. write_outputs 가 다시 불러도 결과는 같다(멱등).
    merge_details(kept)
    # flag(G2 광고 의심 표식 — mine 이 끝 열에 둔다)는 되쓸 때도 끝에 남긴다(관문·팀 반출이 읽는다).
    # conv(팀즈 대화 키)·via(과제를 받은 길)는 이 PC 안에서만 — 팀 반출·내보내기는 열째 뺀다(privacy.TEAM_DROP_COLS, LM30 2026-10-27)
    cols = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge", "flag", "conv", "via"]
    with open(sp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in kept:
            r["project"] = r.get("model", r.get("project", ""))
            r["activity"] = r.get("detail", r.get("activity", ""))
            w.writerow({c: r.get(c, "") for c in cols})
    # 판정 중 새로 발견된 과제(체계에 없던 이름) → entities에 discovered로 기록,
    # 다음 실행의 taxonomy 힌트로 자동 순환된다. 비교는 대소문자 무시(중복 계상 방지).
    # 비교는 ukey2 — .lower() 로만 보면 '설계검토' 가 '설계 검토' 의 옆에 새 과제로 적립되고,
    # 그것이 다음 실행의 taxonomy 힌트가 되어 분할이 영구화된다(재분석해도 낫지 않던 이유).
    # 발견 목록은 **최종 반영값**(kept 의 AI 유래 행)에서 만든다 — final_model 이 '공통' 으로 돌린 사람 이름·공지류는 들어올 수 없다.
    model_names_l = {ukey2(m["name"]) for m in models}
    discovered = sorted({str(r.get("model") or "").strip() for r in kept
                         if _is_ai_row(r) and str(r.get("model") or "").strip()
                         and str(r.get("model")).strip() != "공통"
                         and ukey2(str(r.get("model")).strip()) not in model_names_l
                         and not NOISE_MODEL.match(str(r.get("model")).strip())})
    if discovered:
        print("        판정 중 새 과제 발견: " + ", ".join(discovered))
        ent_obj["models"] = sanitize_models(
            ent_obj["models"] + [{"name": d, "match": [d.lower()], "obs": "판정 중 발견"}
                                 for d in discovered], people)
        ent_obj["discovered"] = discovered
    if (judged and tax_ok) or not ent_prev:
        with open(ent_p, "w", encoding="utf-8") as f:
            json.dump(ent_obj, f, ensure_ascii=False, indent=1)
    elif not tax_ok:
        # 체계 왕복이 실패한 실행 — 청크는 규칙 폴백 체계로 판정됐다. 그 체계로 entities 를 덮으면 다음 실행의
        # 힌트(prev_models)가 폴백 이름으로 퇴화한다(감사 지적). 발견된 새 과제만 기존 체계에 보탠다.
        if discovered:
            try:
                ent_prev_obj = json.load(open(ent_p, encoding="utf-8-sig"))
                ent_prev_obj["models"] = sanitize_models(
                    list(ent_prev_obj.get("models") or []) + [{"name": d, "match": [d.lower()], "obs": "판정 중 발견"}
                                                              for d in discovered], people)
                with open(ent_p, "w", encoding="utf-8") as f:
                    json.dump(ent_prev_obj, f, ensure_ascii=False, indent=1)
            except (OSError, ValueError, TypeError):
                pass
        print("        체계 수립 왕복 실패 — 기존 entities 파일을 보존합니다(규칙 폴백 체계로 덮지 않음)")
    else:
        print("        판정 0건 — 기존 entities 파일을 보존합니다(규칙 폴백 체계로 덮지 않음)")

    dropped = len(dropped_rows)
    _tms = details.teams_via_counts(kept)           # 팀즈 근거가 과제를 받은 길(LM30 2026-10-27 — 구조 줄·판정 기록)
    # failed_chunks = 0건으로 끝난 청크(왕복 실패·JSON 없음 모두 — 예전엔 JSON 없음이 빠져 0 으로 보였다),
    # partial_chunks = 일부만 판정된 청크, failed_rows = AI 가 직접 못 본 행(판정 없음 − 광고 − 관문 − 짧은 대화 − 빠뜨림,
    # 비슷한 판정으로 채운 행 포함), omitted_rows = 온전한 답인데 모델이 빠뜨린 행, repaired = 잘린 답을 복구한 왕복,
    # retries = 적응 분할 재왕복, roundtrips = 총 왕복(쉬고 다시 보낸 것 포함).
    # LM28 진단 A — cache_reused(지난 실행 재사용, 같은 내용 키 포함)·group_rows(대표 판정을 받은 구성원)·reps(보낸 대표 줄)·
    # lowinfo_rows(보내지 않은 짧은 대화)·unseen_rows(AI 가 직접 못 본 행 = 채우기 대상: 판정 없음 − 광고 − 관문, 짧은 대화 포함)·
    # filled_rows(그중 비슷한 판정으로 채움 — 방법별)·rule_rows(규칙 판정으로 남은 행 전체 — 관문 행 포함)·
    # abort_kind(throttle·login·fatal·content·budget·'')·abort_reason·cooldowns(쉬고 다시 보낸 횟수)·model_fallback.
    # items 에는 AI 판정(재사용·같은 내용 포함)만 — 채운 판정은 넣지 않는다.
    with open(os.path.join(rep, f"ai_judgments_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump({"model": model_name, "total": len(rows), "judged": len(judged),
                   "dropped_nonwork": dropped, "chunks": len(chunks), "failed_chunks": n_fail,
                   "partial_chunks": n_partial, "failed_rows": st["failed_rows"],
                   "omitted_rows": st["omitted_rows"], "repaired": st["repaired"],
                   "retries": st["retries"], "roundtrips": st["roundtrips"],
                   "aborted": st["aborted"], "chunk_rows": chunk_n, "prompt_budget": PROMPT_BUDGET,
                   # G3 — 관문에 막혀 보내지 않은 청크·규칙으로 둔 행·광고 의심으로 비업무 처리한 행(실패 아님)
                   "skipped_chunks": n_skip, "gated_rows": st["gated_rows"], "ad_rows": len(ad_idx),
                   "meeting_notes": len(notes),          # 안건(일정 본문 정제)을 붙인 회의 행 수 — 건수만(LM28)
                   "cache_reused": n_reused, "cache_key_reused": n_keyed, "group_rows": st["group_rows"],
                   "reps": len(reps), "lowinfo_rows": len(lowinfo), "unseen_rows": len(unseen),
                   "filled_rows": {k: int(filled_n.get(k, 0)) for k in ("same", "conv", "token", "sim")},
                   "rule_rows": rule_rows, "abort_kind": st["abort_kind"], "abort_reason": st["abort_reason"],
                   "cooldowns": _COOLDOWNS[0], "model_fallback": _MODEL_FALLBACK[0] or "",
                   "rotations": _ROTATIONS[0],          # LM30 — chatTurns 회전(새 채팅으로 넘어간) 횟수
                   # LM30(2026-10-27) 팀즈 근거가 과제를 받은 길 — 업무 행 수 · 같은 문장 묶음(대표·같은 내용 채움) · 지난 판정 ·
                   # 짧은 대화라 다시 쓰지 않은 지난 판정(판정 캐시 v2)
                   "cache_version": JUDGE_CACHE_V, "teams": dict(_tms, generic_cache_dropped=n_generic_old),
                   "items": {str(k): dict(v, sig=signal_sig(rows[k])) for k, v in judged.items()
                             if 0 <= k < len(rows)}}, f, ensure_ascii=False, indent=1)

    # A30 — 비업무로 버린 신호의 시간을 총량에서도 뺀다(mm_meta 갱신). write_outputs 보다 먼저.
    rh = rehours_meta(kept, dropped_rows, tag, cfg, rep, os.path.join(ROOT, "data"))
    if rh:
        _bef = f"{rh['before_mm']:.2f}" if rh.get("before_mm") is not None else "?"
        _tk = int(rh.get("ai_n_time_kept") or 0)
        print(f"        비업무 제외 {rh['dropped_n']}건 · −{rh['dropped_h']:.1f}h → 투입 {_bef}→"
              f"{rh['total_mm']:.2f} MM (로드율 {rh['load_pct']:.0f}%) — 시간 재산정 반영"
              + (f" · AI 비업무 발신 {_tk}건은 배분에서만 빼고 시간 근거로 유지" if _tk > 0 else ""))
    # MM + mm_rows + 피벗 (retag.py와 공용 — write_outputs)
    total_mm, pv = write_outputs(kept, tag, cfg, rep)
    cov = len(judged) / len(rows) * 100
    print(f"[judge] 판정 {len(judged)}/{len(rows)}건({cov:.0f}%) · 비업무 제외 {dropped}건"
          + (f" · −{rh['dropped_h']:.1f}h" if rh else "")
          + f" · 과제 {len(pv['by_model'])}개 · 공통업무 {len(pv['common'])}건 · 총 {total_mm:.2f} MM")
    if n_fail or n_partial or st["repaired"] or st["retries"]:
        print(f"        왕복 {st['roundtrips']}회(청크 {len(chunks)} · 재시도 {st['retries']}) · "
              f"잘린 응답 복구 {st['repaired']}회 · 실패 청크 {n_fail} · 부분 청크 {n_partial} · "
              f"실패로 규칙에 남은 행 {st['failed_rows']} · 모델이 빠뜨린 행 {st['omitted_rows']}")
    # 사진 한 장으로 판정 구조를 읽는 줄(현장 확인용) — 재사용·묶음·짧은 대화·왕복·대기·채움·규칙·중단 갈래
    print(f"[judge] 구조: 신호 {len(rows)} · 재사용 {n_reused} · 같은 내용 대표 {len(reps)}(→{len(reps) + n_members}행) · "
          f"짧은 대화 {len(lowinfo)} · 왕복 {st['roundtrips']} · 대기 {_COOLDOWNS[0]}회 · 채움 {len(fills)} · "
          f"규칙 {rule_rows} · 중단 {st['abort_kind'] or '없음'}"
          + (f" · 채팅 회전 {_ROTATIONS[0]}회(chatTurns {chat_turns()}번마다 새 채팅)" if _ROTATIONS[0] else "")
          + (f" · 대체 모델 {_MODEL_FALLBACK[0]}" if _MODEL_FALLBACK[0] else "")
          # LM30(2026-10-27) 팀즈 근거 중 같은 문장이라 함께 들어온 줄·지난 판정을 다시 쓴 줄(리뷰 화면 과제별 한 줄과 같은 수)
          + (f" · 팀즈 {_tms['rows']}건 중 같은 문장 {_tms['same']} · 지난 판정 {_tms['reused']}" if _tms["rows"] else ""))

    if not judged:
        # 판정이 한 건도 없다 — 왕복이 전부 실패했거나 응답을 하나도 해석하지 못했다. 예전에는
        # 여기서도 0 을 돌려줘 run.py 가 'AI 판정 ok' 로 적고 정제·Agentic·워크플로우까지 진행했고,
        # 내러티브 왕복 N 회가 또 실패하며 ai_narratives 를 {} 로 덮었다(F3). 화면은 규칙 임시
        # 결과(signals/mm_rows)로 두고, 사유는 마지막 줄 JSON 으로 run.py 에 넘긴다.
        if n_fail == len(chunks) and last_err and not st["repaired"]:
            err = "AI 판정 실패(왕복 전부 실패)"
        else:
            err = (f"AI 판정 0건(청크 {len(chunks)}개 전부 0건 · 왕복 {st['roundtrips']}회"
                   + (f" · 개인정보 관문으로 보내지 않은 청크 {n_skip}개" if n_skip else "")
                   + ((" · " + {"throttle": "Copilot 사용량 제한으로 중단", "login": "Copilot 로그인 만료로 중단",
                                "fatal": "사람이 손대야 풀리는 상태로 중단"}.get(st.get("abort_kind") or "",
                                                                       "연속 실패로 중단"))
                      if st["aborted"] else "") + ")")
        # 성공 왕복의 프롬프트 파일은 지워진다(V-06) — 남아 있는 실패 청크 파일 하나를 안내한다
        left = sorted(_glob.glob(os.path.join(rep, f"judge_chunk*_{tag}.md")))
        hint = last_err or (f"report\\{os.path.basename(left[0])} 를 Copilot 에 직접 붙여 응답 형식을 확인하세요" if left
                            else "Copilot 응답 형식을 [AI 연결 진단]으로 확인하세요")
        print(f"[judge] {err} — {hint}")
        print("        signals/mm_rows 는 규칙 판정으로 두고 entities 기존 파일은 보존합니다 — 월별 코멘트는 새로 "
              "만들지 않고 이전 코멘트를 이 기간으로 이월합니다")
        # 이월만(왕복 없음) — 예전에는 rc 3 이면 이 기간 파일이 아예 없어 리포트·팀 묶음(정확한 tag 파일만 읽음)의
        # 월별 코멘트 절이 통째로 빠졌다. 마지막 줄 JSON 규약을 지키려고 JSON 줄보다 먼저 저장한다.
        save_narratives({}, rep, tag)
        chat_note()
        print(json.dumps({"ok": False, "error": err, "hint": hint, "judged": 0,
                          "chunks": len(chunks), "failed_chunks": n_fail}, ensure_ascii=False))
        if _ss is not None:
            _ss.finish("failed", stop_kind="fatal", reason=err, error=err, hint=hint)
        return 3

    # [월별] 내러티브 — 판정이 막힌 실행에서는 같은 Copilot 에 달마다 새 채팅을 열어 봐야 실패만 쌓인다(예전에는
    # '연속 실패로 중단' 직후에도 검사 없이 돌아 최대 약 60분을 쓰고 새 코멘트 0개 — 정제·Agentic 과 같이 쓰는 전체
    # 마감에서 빠졌다). fatal(로그인 만료·강한 사용량 제한 등 사람이 손대야 풀리는 상태)이면 보내지 않고 이월만,
    # 연속 실패로 중단됐으면 한 달만 시험하고 실패하면 바로 멈춘다.
    if "--no-narrate" not in sys.argv:
        if st.get("fatal"):
            print("[judge] 사람이 손대야 풀리는 상태라 이번 실행은 월별 코멘트를 새로 만들지 않습니다 — 이전 코멘트 유지"
                  "([리뷰 코멘트 재생성]으로 이어서)")
            nar = {}
        else:
            print("[judge] 월별 리뷰 내러티브 생성 중…"
                  + (" (판정이 연속 실패로 중단돼 한 달만 시험합니다 — 실패하면 바로 멈춤)" if st.get("aborted") else ""))
            progress("월별 리뷰", 0, 1)
            nar = narrate(kept, total_mm, tag, max_consec=(1 if st.get("aborted") else 2))
        save_narratives(nar, rep, tag)              # 멱등 — narrate 가 이미 저장했어도 이월·표식은 그대로
    chat_note()
    # v3 rc 규약: 부분(예산 중단·실패 잔여)은 2 — '이어서' 가 데이터가 된다. 완주는 0.
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
