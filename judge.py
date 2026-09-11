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
  pivots_*.json          과제→유형/세부 · 유형→과제 양방향 + 공통업무(Agentic AI 후보) + 에피소드
  ai_narratives_*.json   월별 리뷰 서술

  python judge.py --from ... --to ... [--chunk 40] [--no-narrate]
  (청크 기본값은 config.copilotAuto.judgeChunk 로도 바꿀 수 있다 — --chunk 가 우선)

종료 코드: 0 정상 · 1 입력 없음 · 3 판정 0건(왕복 전부 실패 등 — 마지막 줄 JSON {"ok":false,
"error","hint"}; signals/mm_rows 는 규칙 판정으로 쓰되 entities·ai_narratives 기존 파일은 보존,
월별 내러티브 왕복은 하지 않는다 — run.py 가 이 코드를 보고 정제·Agentic·워크플로우를 건너뛴다).

프롬프트의 상대(who) 열은 기본적으로 주소의 도메인만('@corp.co') 싣는다 — 사람 이름·주소를
Copilot 에 보내지 않는 원칙. config.copilotAuto.sendSenderAddress=true 일 때만 주소 그대로.

copilot_send(prompt, tag, name, fresh=None) 은 다른 모듈(refine·agentic·flow·team_refine·
core/details)이 공유하는 Copilot 왕복 1회 접점이다 — 드라이버(tools/copilot_auto.py)가
긴 프롬프트 분할·[[전송끝]] 서약을 처리하므로 여기서는 왕복 예산만 조각 수에 맞춘다.
프롬프트 파일(report\\judge_<name>_<tag>.md)은 성공한 왕복이면 회수 직후 지우고, 실패한 왕복·해석 못 한
답(note_bad_reply)의 것만 남긴다 — 그 파일이 '직접 붙여넣기' 안내 대상이다.
"""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
from details import explain_failure  # noqa: E402  - 로그인 필요 등 "사람이 손대야 풀리는" 실패 판정
from details import ukey2  # noqa: E402  - 과제 신원 축(공백·구분자·대소문자 무시, 괄호 꼬리 보존)
from progress import progress  # noqa: E402
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
MAX_SPLIT_DEPTH = 3         # 40 → 20 → 10 → 5
MIN_RETRY_ROWS = 3          # 부분 성공(잘린 답 복구) 뒤 빠진 행이 이 수 이상이면 그 행만 다시 묻는다
SOFT_FAIL_CHUNKS = 3        # 연속으로 이만큼 청크가 0건이면 적응 재시도를 끄고 1회씩만 시도
ABORT_FAIL_CHUNKS = 6       # 연속으로 이만큼 0건이면 남은 청크를 규칙으로 둔다(수 시간 공회전 방지)
SEEN_MAX_NAMES = 30         # 청크에 동봉하는 '앞서 쓴 세부업무 이름' 상한
SEEN_MAX_CHARS = 600


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


def roundtrip_timeout(n_parts=1):
    """자식(copilot_auto)의 재시도 사다리 예산에 맞춘 타임아웃 — 부모가 짧으면
    '정상 재시도 중'을 죽여버린다. 드라이버가 긴 프롬프트를 조각으로 나눠 보내면 왕복이
    조각 수만큼 늘어나므로 예산도 그만큼 곱한다(n_parts)."""
    try:
        sec = float(_copilot_cfg().get("replyTimeoutSec") or 300)
    except (ValueError, TypeError):
        sec = 300.0
    n = max(1, int(n_parts or 1))
    return max(900.0, sec * 3 + 180) * n


_FIRST_SEND = [True]        # 판정 세션의 첫 왕복인지 (새 채팅으로 시작)
_NEED_FRESH = [False]       # 직전 왕복이 실패했거나 답을 해석 못 했다 — 다음 왕복은 새 채팅에서
_TURNS = [0]                # 지금 채팅에서 성공한 왕복 수 — config.copilotAuto.chatTurns 에 닿으면 다음 왕복은 새 채팅
_CHAT_TURNS = [None]        # chatTurns 캐시 (None = 아직 안 읽음)
CHAT_TURNS_DEFAULT = 12     # 한 채팅에 이어 보내는 왕복 상한. 0 = 묶음마다 새 채팅(LM22 1차 방식)


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
    그리고 방금 지운 프롬프트 파일(report\\judge_<name>_<tag>.md)은 되살린다(V-06)."""
    _NEED_FRESH[0] = True
    _restore_prompt()
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


def copilot_send(prompt_text, tag, name, fresh=None):
    """Copilot 왕복 1회 — 프롬프트를 report\\judge_{name}_{tag}.md 로 쓰고 드라이버를
    자식 프로세스로 부른다(분할·서약은 드라이버 몫). 반환 {"ok","reply",...,"error","hint"}.
    fresh: True = 새 채팅에서 시작, None(기본) = **같은 채팅에서 이어서** — 이 프로세스의 첫 성공 왕복까지만 새 채팅
           (+ 직전 왕복이 실패/해석 불가·끊김이면 새 채팅, + 한 채팅의 왕복이 config.copilotAuto.chatTurns 에 닿으면 새 채팅,
           chatTurns=0 이면 매번 새 채팅), False = 무조건 이어서.
           판정·정제·Agentic·워크플로우의 묶음(청크)은 모두 None 으로 보내 앞 묶음의 문맥(과제·세부업무 표기)을 잇는다 —
           묶음마다 새 채팅을 열면 Copilot 의 기억이 끊겨 표기가 흔들렸다(제보). 프롬프트는 여전히 혼자서 완결이라 드라이버가
           재시도로 새 채팅을 열어도 답이 나온다.
    반환 dict 의 cut=True 는 답이 생성 중단 문구로 끝났다는 뜻 — 잘린 JSON 복구 대상.
    프롬프트 파일은 **성공한 왕복이면 회수 직후 지운다**(V-06: 실행당 64~83개가 report\\ 에 누적돼 신호 원문
    사본이 쌓였다) — 실패한 왕복(왕복 자체 실패, 답에 JSON 꼴이 없음)의 것만 남겨 '직접 붙여넣기' 안내에 쓴다.
    답은 왔지만 호출자가 해석하지 못한 경우는 note_bad_reply() 가 방금 지운 파일을 되살린다."""
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
    n_parts = len(prompt_text or "") // PART_PROMPT + 1        # 드라이버의 분할 수 추정
    try:
        cmd = [sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"), "--send", pf]
        limit = chat_turns()
        want_fresh = (fresh is True
                      or (fresh is None and (_FIRST_SEND[0] or _NEED_FRESH[0] or limit <= 0 or _TURNS[0] >= limit)))
        if want_fresh:
            # 판정의 첫 왕복은 새 채팅에서 — 수집 단계의 실패 대화가 판정을 오염시키지 않게.
            # 직전 왕복이 실패했을 때도 새 채팅 — 끊긴 생성·오류 문구가 남은 채팅은 다음 답을 오염시킨다.
            # 한 채팅의 왕복이 chatTurns 에 닿아도 새 채팅 — 너무 길어진 대화는 답이 끊기거나 앞 답을 되풀이한다.
            cmd.append("--fresh")
            _TURNS[0] = 0
        # LM_STAGE — 드라이버가 report\copilot_trace.jsonl 에 '어느 단계의 왕복인지' 를 남기게 한다.
        # 이름만 넘긴다(chunk3·narr_2026-06·wf1 …). 프롬프트 원문은 계측에 들어가지 않는다.
        out = subprocess.run(cmd, capture_output=True, timeout=roundtrip_timeout(n_parts),
                             cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                                LM_STAGE=str(name or "")[:40]),
                             creationflags=NO_WIN)
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
    if res.get("phase") == "stub" and not _STUB_NOTED[0]:
        _STUB_NOTED[0] = True
        print("        ※ LM_COPILOT_STUB 스텁 응답 — 테스트 전용, 실제 Copilot 판정이 아닙니다")
    if res.get("ok"):
        _FIRST_SEND[0] = False       # 성공했을 때만 소진 — 실패하면 다음도 새 채팅
        _NEED_FRESH[0] = bool(res.get("cut"))   # 끊긴 답이 남은 채팅도 다음엔 새 채팅
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


def _squash(s):
    return re.sub(r"\s+", "", str(s or ""))


def rfind_json(reply, want_key, skip=()):
    """답 뒤쪽부터 '{' 를 거슬러 올라가며 want_key 를 가진 첫 완전한 JSON 객체를 찾는다.
    skip: 프롬프트에 실은 **출력 형식 예시** 문자열들 — 앵커 실패(fulltext)로 답에 프롬프트 에코가
    섞이면 예시가 '답'으로 해석돼 예시의 번호·이름이 판정에 들어갔다(실측: 판정 0·1행이 '프로젝트A/
    광학 설계', 정제는 Level 3 '...'). 공백을 뺀 원문이 예시와 같으면 건너뛴다."""
    reply = str(reply or "")
    skip_n = {_squash(s) for s in (skip or ()) if s}
    i = reply.rfind("{")
    n = 0
    while i != -1 and n < 600:
        try:
            o, end = _DEC.raw_decode(reply, i)
            if isinstance(o, dict) and want_key in o:
                if not skip_n or _squash(reply[i:end]) not in skip_n:
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
    skip_n = {_squash(s) for s in (skip or ()) if s}
    key = f'"{want_key}"'
    k = reply.rfind(key)
    tries = 0
    while k != -1 and tries < 50:
        i = reply.rfind("{", 0, k)
        if i != -1 and not reply[i + 1:k].strip():       # '{' 바로 뒤가 키 = 최상위 객체 시작
            o, raw = _close_truncated(reply, i)
            if isinstance(o, dict) and want_key in o and (not skip_n or _squash(raw) not in skip_n):
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
    """정규식 경로의 예시 방어(V-04) — 답 전체(공백 제거)가 프롬프트 예시와 같으면 전부 버리고, 그 밖에는 예시의
    두 행([0,"y","프로젝트A","개발","광학 설계"] 뒤 [1,"n"])이 **그 순서로 붙어 예시처럼 `]}` 로 닫힌 경우**(프롬프트
    에코)만 그 둘을 버린다. 예전에는 예시와 같은 행을 낱개로 버려 진짜 [1,"n"]·[0,"y","프로젝트A",…] 가 사라졌다."""
    if _squash(reply) in {_squash(s) for s in JUDGE_EXAMPLES}:
        return []
    e0, e1 = JUDGE_EXAMPLE_ROWS
    keep, i = [], 0
    while i < len(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if (rows[i] == e0 and nxt is not None and nxt[:2] == e1 and not any(nxt[2:])):
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


TAXONOMY_EXAMPLE = ('{"models":[{"name":"프로젝트A","match":["proja"],"obs":"근거가 된 raw 조각","product":"제품X"},'
                    '{"name":"공통","match":[],"product":"공통"}]}')
CONSOLIDATE_EXAMPLE = '{"models":[{"name":"대표이름","match":["키워드"],"merged":["흡수된이름"]},{"name":"공통","match":[]}]}'


def taxonomy_prompt(rows, hints, pinned=()):
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
        "   product = 그 과제가 속한 **실제 제품·제품군·과제코드** (raw 에서 식별될 때만).",
        "   내부 공통업무·행정이면 product 를 '공통' 으로. 못 정하겠으면 생략.",
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
    return "\n".join(lines + _fit_samples(rows, 100, fmt, head_len))


def consolidate_prompt(models, rows):
    """초안 과제 목록에서 '같은 실체가 다른 이름으로 갈린 것'을 통합하도록 한 번 더 묻는다.
    같은 raw 라도 실행마다 체계가 흔들려(예: 'AX' 와 'Agentic AI' 가 분리) 로드 배분이
    달라지던 문제(9d) 완화 — 왕복 1회를 더 쓰는 대신 실행 간 일관성을 얻는다."""
    names = [m["name"] for m in models]
    lines = [
        "아래는 한 엔지니어의 업무를 분류하기 위해 초안으로 뽑은 '상위 과제(제품·프로젝트)' 목록입니다.",
        "같은 실체가 다른 이름으로 갈린 것을 하나로 합쳐 최종 목록을 만들어 주세요.",
        "",
        "· 상위/하위 관계이거나 같은 프로그램의 축약·확장이면 합친다 (대표 이름 하나 선택).",
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
    return "\n".join(lines + _fit_samples(rows, 40, lambda r: f"- {(r.get('text') or '')[:70]}", head_len))


def apply_merges(models):
    """consolidate 결과의 merged 를 match 키워드로 흡수 — 판정 단계에서 옛 이름이 나와도
    대표 이름으로 정규화되도록 한다."""
    out = []
    for m in models:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        mm = dict(m)
        mm["match"] = list(dict.fromkeys(
            [str(k).lower() for k in _as_list(m.get("match"))]
            + [str(k).lower() for k in _as_list(m.get("merged"))]))
        out.append(mm)
    return out


def fallback_models(rows, known):
    """taxonomy 왕복 실패 시 — 등록 프로젝트 + 규칙 귀속에서 자주 나온 프로젝트를 후보로"""
    freq = Counter(r.get("project") for r in rows
                   if r.get("project") and r["project"] not in ("미지정", "공통"))
    auto = [p for p, n in freq.most_common(8) if n >= 2]
    names = list(dict.fromkeys(list(known or []) + auto))
    return [{"name": p, "match": [p.lower()]} for p in names] + [{"name": "공통", "match": []}]


# 파일명 접두어·범용 토큰은 과제가 아니다 — 프롬프트 지시만으로는 새는 것이
# 실측 확인돼 코드에서도 걸러낸다 (entities 힌트 순환 오염 방지)
NOISE_MODEL = re.compile(
    r"^(img|image|scan|doc|docs|file|files|tmp|temp|misc|etc|기타|잡음|미지정|none|n/a)\d*$", re.I)


def _clean_product(v):
    """taxonomy 가 판정한 product — 문자열로 정규화, 길이 상한."""
    s = str(v or "").strip()
    return s[:40]


def sanitize_models(models):
    """taxonomy·discovered 결과에서 잡음 이름 제거 + 대소문자 중복 통합, '공통' 보장.
    pinned(사용자 지정)는 잡음 필터를 우회한다 — 사용자가 명시한 이름은 코드가 지우지 않는다."""
    out, seen = [], set()
    for m in models:
        name = str(m.get("name") or "").strip() if isinstance(m, dict) else str(m).strip()
        if not name or (NOISE_MODEL.match(name) and not (isinstance(m, dict) and m.get("pinned"))):
            continue
        # 신원 축은 ukey2 — 예전에는 .lower() 뿐이라 '광학 설계'/'광학설계'/'광학-설계' 가 서로 다른
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

            out.append(m)
        else:
            out.append({"name": name, "match": [k]})
    if not any(m["name"] == "공통" for m in out):
        out.append({"name": "공통", "match": []})
    return out


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


def rule_model(r, models):
    """미판정(청크 실패) 행을 taxonomy의 match 키워드로 과제 축에 매핑 —
    규칙 토큰('agentic' 조각 등)이 과제명 네임스페이스에 그대로 섞이는 것 방지"""
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
        keys = [m["name"].lower()] + [str(k).lower() for k in _as_list(m.get("match"))]
        if _kw_hit is not None:
            if any(k and _kw_hit(k, toks) for k in keys):
                return m["name"]
        elif any(k and len(k) >= 2 and k in low for k in keys):
            return m["name"]
    return "공통"


# ── [1..N] 신호 판정 ───────────────────────────────────────────────────────
JUDGE_EXAMPLE_ROWS = [[0, "y", "프로젝트A", "개발", "광학 설계"], [1, "n"]]
JUDGE_EXAMPLE = json.dumps({"j": JUDGE_EXAMPLE_ROWS}, ensure_ascii=False, separators=(",", ":"))
JUDGE_EXAMPLE_OLD = '{"j":[[0,"y","프로젝트A","개발","광학 설계"],[1,"n","","",""]]}'   # 구판 프롬프트 에코 방어
JUDGE_EXAMPLES = (JUDGE_EXAMPLE, JUDGE_EXAMPLE_OLD)


def row_line(r, idx):
    return (f"#{idx} | {r['time'][:16]} | {r['source']} | "
            f"{who_label(r.get('who'), 16) or '-'} | {(r.get('text') or '')[:95]}")


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
        "· y/n : 업무 여부. 공지·알림(정부24·인화원·윤리사무국·innoHR·뉴스레터·시스템),",
        "  광고·프로모션, 개인 용무, 의미 없는 잡음은 n. 과감하게 걸러낼 것.",
        "· 과제 : 아래 목록에서 고르되 목록의 표기를 그대로 쓴다(변형 금지). 목록에 없어도",
        "  원문에 상위 과제·제품명이 분명히 보이면 그 이름을 새로 쓴다(새 과제 발견) —",
        "  단, 이미 목록에 같은 개체의 다른 표기가 있으면 그 표기를 쓴다. 어느 쪽도 아니면 \"공통\".",
        "   → " + ", ".join(
            m["name"] + (f"({str(m.get('desc'))[:30]})" if m.get("desc") else "") for m in models),
        "· 유형 : 개발 / 사무 / 현장 / 협업 중 하나",
        "· 세부업무 : 짧은 명사구 — 같은 일은 같은 이름으로 (예: '광학 설계', 'BOM 발주',",
        "   '입고검사', '고객 대응', '주간보고'). 조사 붙은 조각('보고의' 등) 금지.",
    ]
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


def judge_rows(idxs, rows, models, seen, tag, label, depth, st):
    """행 묶음 하나를 판정한다(적응 분할). returns {번호: 판정}.
    · 완전한 JSON → 그대로(모델이 빠뜨린 행은 omitted_rows — 재왕복 없이 규칙).
    · 잘린 답(cut·복구·정규식) → 복구된 행은 쓰고, 빠진 행이 MIN_RETRY_ROWS 이상이면 그 행만 다시 묻는다.
    · 통째 실패(왕복 실패·JSON 없음) → 2*MIN_SPLIT 행 이상이면 반으로 나눠 각각 재시도(깊이 MAX_SPLIT_DEPTH).
    · st: roundtrips·repaired·retries·failed_rows·omitted_rows·notes·last_err·soft(재시도 끔) 누적."""
    idxs = list(idxs)
    chunk = [rows[i] for i in idxs]
    # 묶음은 같은 채팅에서 이어 보낸다(fresh=None — 첫 왕복·실패 뒤·chatTurns 마다만 새 채팅). 프롬프트는 혼자서 완결이라
    # 새 채팅에 떨어져도 답이 나오고, 이어지면 앞 묶음의 표기를 Copilot 이 기억한다
    res = copilot_send(judge_prompt(chunk, idxs[0], models, seen_details=seen, idxs=idxs),
                       tag, label)
    st["roundtrips"] += 1
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
            st["failed_rows"] += len(idxs)
            return got
    missing = [i for i in idxs if i not in got]
    if not missing:
        return got
    incomplete = (not res.get("ok")) or (not got) or bool(info.get("repaired")) or bool(res.get("cut"))
    if not incomplete:
        st["omitted_rows"] += len(missing)          # 온전한 답인데 모델이 빠뜨림 — 규칙으로
        return got
    if st.get("soft") or depth >= MAX_SPLIT_DEPTH:
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


# ── 피벗·공통업무·에피소드 ─────────────────────────────────────────────────
def build_pivots(kept, total_mm):
    tot_w = sum(float(r["weight"] or 0) for r in kept) or 1e-9

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
        # 공통업무: 2개 이상 과제에 걸친 세부업무 = 표준화·Agentic AI 자동화 후보
        "common": sorted([{"detail": dt, "models": sorted(ms, key=lambda m: -ms[m]),
                           "mm": mm(sum(ms.values()))}
                          for dt, ms in detail_models.items()
                          if len([m for m in ms if m != "공통"]) >= 2],
                         key=lambda x: -x["mm"])[:12],
    }
    return pv


def build_episodes(kept):
    """업무의 시작·끝 근사 — 외부요청(오더 수신)→내 산출(발신·파일·커밋) 페어링 리드타임,
    자체진행은 같은 과제 신호의 연속 구간(3일 초과 공백이면 분리)으로 본다."""
    def ts(r):
        try:
            return datetime.strptime(r["time"][:16], "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    DONE = ("메일(발신)", "메일(발신·일자)", "팀즈(발신)", "파일", "파일(코드)", "파일(해석출력)", "커밋", "수동기록")
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
    return {"orders": leads[:20], "spans": sorted(episodes, key=lambda x: x["start"], reverse=True)[:20],
            "avg_lead_h": round(sum(x["lead_h"] for x in leads) / len(leads), 1) if leads else None}


_MERGE_STOP = {"관리", "업무", "작업", "진행", "기타", "관련", "대응", "지원", "및",
               "수립", "정의", "정리", "구조", "구성"}


def _detail_tokens(name):
    return {t for t in re.split(r"[\s_\-·/()\[\],]+", str(name or "").lower())
            if len(t) >= 2 and t not in _MERGE_STOP}


def _detail_note(name):
    """세부업무 이름 끝의 괄호 꼬리 — '수광부 해석(양산)' → '양산'. 실제 구분 표기라
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
    """mine.py 가 신호·시간 근거에 쓴 것과 같은 제외어 — mine.EXCLUDE ∪ config.excludePathKeywords.
    mine 을 임포트하지 않는다(모듈 최상위에서 sys.stdout 을 다시 감싸 이 프로세스의 출력을 끊는다) —
    소스에서 EXCLUDE 리터럴만 ast 로 읽고, 못 읽으면 설정 목록만 쓴다."""
    import ast
    import extract
    base = []
    try:
        tree = ast.parse(open(os.path.join(ROOT, "mine.py"), encoding="utf-8").read())
        for node in tree.body:
            if (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EXCLUDE"):
                base = [str(x) for x in ast.literal_eval(node.value)]
                break
    except (OSError, SyntaxError, ValueError, TypeError):
        base = []
    return sorted(set(base) | {str(k) for k in extract.cfg_list(cfg, "excludePathKeywords")
                               if str(k).strip()})


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
    returns {"dropped_n"(누적),"dropped_h","before_mm","total_mm","avail_mm","load_pct"} — 버린 것이 없거나
    (구판 core 로) 함수가 없거나 meta 가 없거나 저장이 막히면 None(그때는 mine 값이 그대로 남는다)."""
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
    if isinstance(info, dict):
        info = dict(info)
        info.pop("inferred_absence", None)        # date 키 — mine 도 저장 전에 뺀다
        mj["mm_basis"] = info
        for k in ("coverage", "measure", "cfg_used", "tool_usage"):   # mine 과 같이 최상위에도 싣는다(팀 취합이 읽는다)
            if isinstance(info.get(k), dict):
                mj[k] = info[k]
    mj["rehours"] = True
    mj["dropped_n"] = len(dropped)
    mj["dropped_h"] = round(max(0.0, dropped_h), 2)
    mj["rehours_at"] = time.strftime("%Y-%m-%d %H:%M")
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
    _write_dropped(rep, tag, dropped)          # 누적 장부 — 다음 UI 제외가 이번 버림분을 함께 넘긴다
    return {"dropped_n": len(dropped), "dropped_h": mj["dropped_h"], "before_mm": before_mm,
            "total_mm": total_mm, "avail_mm": avail_mm, "load_pct": mj["load_pct"]}


def write_outputs(kept, tag, cfg, rep):
    """판정 완료 신호 → mm_rows CSV + pivots JSON (MM 총량 스케일).
    judge 본류와 retag(지정 반영 재분류) 양쪽에서 호출한다.
    총량은 mm_meta.total_mm — 비업무 제외가 있었으면 rehours_meta 가 먼저 갱신해 둔 값이다(A30)."""
    merged = merge_details(kept)
    if merged:
        print(f"        같은 일로 판정된 세부업무 {merged}건 통합 (행 파편화 방지)")
    # 과제 → 제품 매핑 (taxonomy 판정 결과) — retag 경로에서도 동일하게 쓰도록
    # entities 파일에서 직접 읽는다(시그니처 불변).
    prod_map = {}
    try:
        ent = json.load(open(os.path.join(rep, f"entities_{tag}.json"), encoding="utf-8-sig"))
        for m in (ent.get("models") or []):
            if isinstance(m, dict) and m.get("name") and m.get("product"):
                prod_map[str(m["name"])] = str(m["product"]).strip()
    except (OSError, ValueError):
        pass

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
    owner = cfg.get("owner") or os.environ.get("USERNAME", "")
    out_rows = []
    for (md, dt), a in sorted(agg.items(), key=lambda kv: -kv[1]["w"]):
        share = a["w"] / tot_w
        srcs = len({s.split("(")[0] for s in a["src"]})
        out_rows.append({"Function": cfg.get("function", ""), "Level 1": "",
                         "제품": _product_for(md, dt),
                         "유형": a["wt"].most_common(1)[0][0], "Level 2": md, "Level 3": dt,
                         "이름": owner, "상세설명": "",
                         "share": round(share, 4), "mm": round(share * total_mm, 3),
                         "근거": " · ".join(f"{s}{n}" for s, n in a["src"].most_common()),
                         "확신도": "상" if (srcs >= 2 and len(a["days"]) >= 3) else
                                  ("중" if srcs >= 2 or len(a["days"]) >= 3 else "하"),
                         "활동일수": len(a["days"])})
    cols2 = ["Function", "Level 1", "제품", "유형", "Level 2", "Level 3", "이름", "상세설명",
             "share", "mm", "근거", "확신도", "활동일수"]
    with open(os.path.join(rep, f"mm_rows_{tag}.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols2)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    pv = build_pivots(kept, total_mm)
    pv["episodes"] = build_episodes(kept)
    with open(os.path.join(rep, f"pivots_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump(pv, f, ensure_ascii=False, indent=1)
    return total_mm, pv


# ── [월별] 내러티브 ────────────────────────────────────────────────────────
def _nm_key(s):
    """과제 이름 비교 축 — 공백·구분자·대소문자 무시(core/details.ukey2 와 같은 규칙)."""
    return re.sub(r"[\s·・ㆍ‧/_\-()\[\]]+", "", str(s or "")).casefold()


NARRATIVE_EXAMPLE = ('{"summary":"이 달 요약 2~3문장","projects":[{"name":"프로젝트A",'
                     '"story":"무엇을 어떻게 했는지 1~2문장","worktypes":"개발 위주"}]}')


def narrate(kept, total_mm, tag):
    by_month = defaultdict(list)
    for r in kept:
        by_month[r["time"][:7]].append(r)
    out = {}
    for _i, mk in enumerate(sorted(by_month)):
        progress("월별 리뷰", _i, len(by_month))
        rows = by_month[mk]
        head = [
            f"당신은 업무 리뷰 작성자입니다. {mk} 한 달의 판정된 업무 신호가 아래에 있습니다.",
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
        lines = _fit_samples(rows, 90, lambda r: (
            f"- {r['time'][:16]} [{r['source']}] {r.get('model', '')}/{r.get('worktype', '')} "
            f"{who_label(r.get('who'), 10)} {(r.get('text') or '')[:80]}"), head_len)
        prompt = "\n".join(head + lines)
        # ★ 달마다 **새 채팅**에서 묻는다. 예전에는 fresh 를 주지 않아 '같은 채팅에서 이어서' 가 됐고,
        # narrate 는 judge.main 끝에서 돌므로 그 채팅에는 이미 **분석 기간 전체**(최근 달 포함)의 판정
        # 청크가 들어 있었다. 그래서 6월 리뷰에 8~9월 일이 적히는 일이 생겼다(제보).
        # 판정 청크는 앞 묶음의 과제 표기를 이어받는 이득이 있어 같은 채팅을 쓰지만, 월별 리뷰는
        # 프롬프트가 혼자서 완결이라 이어받을 이득이 없고 오염만 남는다.
        res = copilot_send(prompt, tag, f"narr_{mk}", fresh=True)
        if res.get("ok"):
            o = rfind_json(res.get("reply", ""), "summary", skip=(NARRATIVE_EXAMPLE,)) \
                or repair_json(res.get("reply", ""), "summary", skip=(NARRATIVE_EXAMPLE,))
            if o and str(o.get("summary") or "").strip():
                # 답이 든 과제 이름이 **그 달에 실제로 있는 이름**인지 확인한다. 예전에는 아무 검증이
                # 없어, 프롬프트 예시의 '프로젝트A' 같은 것이 그대로 리뷰에 실릴 수 있었다(같은 계열의
                # 에코 사고가 rfind_json 주석에 실측으로 남아 있다). 없는 이름은 그 항목만 버린다.
                real = {_nm_key(r.get("model")) for r in rows if r.get("model")} | {_nm_key("공통")}
                keep, drop = [], []
                for p in (o.get("projects") or []):
                    if isinstance(p, dict) and _nm_key(p.get("name")) in real:
                        keep.append(p)
                    elif isinstance(p, dict) and str(p.get("name") or "").strip():
                        drop.append(str(p.get("name")).strip())
                if drop:
                    print(f"        {mk} 리뷰에서 이 달에 없는 과제 {len(drop)}건 제외: "
                          + ", ".join(drop[:3]) + (" …" if len(drop) > 3 else ""))
                o["projects"] = keep
                out[mk] = o
                print(f"        {mk} 내러티브 ✓" + (" (잘린 응답 일부 복구)" if res.get("cut") else ""))
                continue
            note_bad_reply()
        print(f"        {mk} 내러티브 실패 — 건너뜀")
    progress("월별 리뷰", len(by_month), len(by_month))
    return out


def save_narratives(nar, rep, tag):
    """월별 내러티브 저장 — 한 달도 못 만들었으면(왕복 전부 실패) 기존 파일을 빈 {} 로 덮지 않고
    보존한다(F3: 지난 실행의 내러티브가 통째로 사라지던 결함). 반환: 저장했으면 True."""
    p = os.path.join(rep, f"ai_narratives_{tag}.json")
    if not nar and os.path.exists(p):
        print("        월별 내러티브 0개 — 기존 ai_narratives 파일을 보존합니다(덮어쓰지 않음)")
        return False
    with open(p, "w", encoding="utf-8") as f:
        json.dump(nar, f, ensure_ascii=False, indent=1)
    return True


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
    if "--narrate-only" in sys.argv:
        kept = [r for r in rows if (r.get("judge") or "").strip()]
        if not kept:
            print("[judge] AI 판정 결과가 없습니다 — 'AI 판정'을 켜고 분석을 먼저 돌리세요")
            return 1
        meta_p = os.path.join(rep, f"mm_meta_{tag}.json")
        mj = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
        total_mm = float(mj.get("total_mm") or 0)
        print(f"[judge] 리뷰 코멘트 재생성 — 판정 신호 {len(kept)}건")
        nar = narrate(kept, total_mm, tag)
        saved = save_narratives(nar, rep, tag)
        print(f"[judge] 월별 코멘트 {len(nar)}개 " + ("저장" if saved else "— 기존 파일 유지"))
        return 0 if nar else 1
    cfg = extract.load_cfg()
    known = cfg.get("projects") or []
    model_name = (cfg.get("copilotAuto") or {}).get("model", "GPT-5.6")

    # 사용자 지정 프로젝트(UI에서 입력) — 힌트가 아니라 고정 엔티티로 체계에 항상 포함
    import projmap
    pinned = [{"name": p["name"], "match": p.get("match") or [], "desc": p.get("desc", ""),
               "obs": "사용자 지정", "pinned": True}
              for p in projmap.load_user_projects(ROOT)]
    pinned_l = {p["name"].lower() for p in pinned}

    # 지난 분석에서 발견된 과제도 힌트로 (실행 간 일관성) — 채택 여부는 이번 raw 관찰이 결정
    import glob as _glob
    prev_models = []
    prev = sorted(_glob.glob(os.path.join(rep, "entities_*.json")), key=os.path.getmtime)
    if prev:
        try:
            po = json.load(open(prev[-1], encoding="utf-8"))
            prev_models = [m["name"] for m in sanitize_models(po.get("models", []))
                           if m["name"] != "공통"]
        except (OSError, ValueError):
            pass
    hints = [h for h in dict.fromkeys(list(known) + prev_models) if h.lower() not in pinned_l]

    # [0] 엔티티 체계 — 지정은 항상 포함(코드로 강제), 나머지는 AI가 raw에서 자동 발견
    n_chunks = -(-len(rows) // chunk_n)
    progress("AI 판정", 0, n_chunks + 1)
    print(f"[judge] 0/{n_chunks + 1} 엔티티 체계 수립 왕복 (모델 {model_name}"
          + (f" · 지정 {len(pinned)}개" if pinned else "") + ") — 응답까지 수십 초 걸립니다")
    res = copilot_send(taxonomy_prompt(rows, hints, pinned), tag, "taxonomy")
    # 이 왕복이 사실상 프로브다 — 로그인이 안 됐으면 여기서 이미 드러난다. 다만 **한 번으로
    # 단정하지는 않는다**(아래 주석). 규칙 판정은 어떤 경우에도 돌아 signals·mm_rows·보고서가
    # 나오므로, 사용자는 결과를 받고 로그인 뒤 [재분석만]으로 이으면 된다.
    _why0, _how0, _fatal0 = explain_failure(res)
    if _fatal0:
        print(f"[judge] 체계 수립 왕복이 실패했습니다 — {_why0}")
        print(f"        {_how0}")
        print("        규칙 판정으로 신호·MM·보고서는 그대로 만듭니다. 로그인 뒤 [재분석만]을 누르면 "
              "AI 판정만 이어서 합니다.")
    models = []
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
        rc = copilot_send(consolidate_prompt(sanitize_models(models), rows), tag, "consolidate")
        if rc.get("ok"):
            o2 = rfind_json(rc.get("reply", ""), "models", skip=(CONSOLIDATE_EXAMPLE,))
            cand = [m for m in _as_list(o2.get("models")) if isinstance(m, dict) and m.get("name")]
            if cand and len(cand) <= len(models):
                merged_names = [m["name"] for m in cand]
                print("        통합 후: " + ", ".join(merged_names[:10]))
                models = apply_merges(cand)
            else:
                print("        통합 결과가 유효하지 않아 초안 유지")
        else:
            print("        통합 왕복 실패 — 초안 유지")
    models = sanitize_models(pinned + models)   # 지정이 앞 → 중복 시 사용자 표기가 대표
    # AI가 새 과제를 하나도 못 주면(왕복 실패든, 성공했지만 산문 응답으로 파싱 실패든) 규칙 폴백
    ai_added = any(not m.get("pinned") and m["name"] != "공통" for m in models)
    if not ai_added and not (res.get("ok") and rfind_json(res.get("reply", ""), "models", skip=(TAXONOMY_EXAMPLE,))):
        models = sanitize_models(pinned + fallback_models(rows, known))
        print("        체계 수립 실패(왕복 또는 응답 파싱) — 지정+규칙 발견 후보로 폴백")
    else:
        print("        모델: " + ", ".join(m["name"] for m in models[:10]))
    # entities 파일은 판정이 끝난 뒤에 쓴다 — 판정이 0건(왕복 전부 실패)이면 기존 파일을
    # 규칙 폴백 체계로 덮지 않고 보존한다(F3)
    ent_p = os.path.join(rep, f"entities_{tag}.json")
    ent_obj = {"models": models, "worktypes": WORKTYPES, "hints_used": hints}
    ent_prev = os.path.exists(ent_p)

    # [1..N] 신호 판정 — 행 수(chunk_n)와 글자 예산 둘 다로 자른다. 머리말 길이는 과제 목록과
    # '앞서 쓴 이름' 목록 상한을 포함해 잰다.
    head_len = len(judge_prompt([], 0, models)) + SEEN_MAX_CHARS + 160
    plan = pack_chunks(rows, chunk_n, head_len)
    chunks = [rows[s:s + n] for s, n in plan]
    if len(chunks) != n_chunks:
        print(f"        글자 예산({PROMPT_BUDGET:,}자)에 맞춰 청크 {n_chunks}→{len(chunks)}개"
              f" (머리말 {head_len:,}자 · 행 최대 {max(n for _s, n in plan)}개)")
    judged, n_fail, n_partial, last_err = {}, 0, 0, ""
    st = {"roundtrips": 0, "repaired": 0, "retries": 0, "failed_rows": 0, "omitted_rows": 0,
          "notes": [], "last_err": "", "soft": False, "aborted": False}
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
    for ci, (start, n) in enumerate(plan):
        progress("AI 판정", ci + 1, len(chunks) + 1)
        idxs = list(range(start, start + n))
        if st["aborted"]:
            st["failed_rows"] += n
            n_fail += 1
            continue
        print(f"[judge] {ci+1}/{len(chunks)} 신호 판정 왕복 (#{start}~#{start+n-1})")
        st["notes"] = []
        got = judge_rows(idxs, rows, models, recent_details(judged, prev_idxs), tag, f"chunk{ci+1}", 0, st)
        judged.update(got)
        prev_idxs = idxs
        if got:
            consec = 0
            if len(got) < n:
                n_partial += 1
        else:
            consec += 1
            n_fail += 1
            last_err = st.get("last_err") or last_err
        note = ("" if not st["notes"] else " · " + " / ".join(st["notes"][:4]))
        print(f"        판정 {len(got)}/{n}건{note}")
        if st.get("fatal"):
            # 사람이 손대야 풀리는 상태 — 6청크를 기다릴 이유가 없다. 바로 규칙 판정으로 넘긴다.
            st["aborted"] = True
            print(f"        {st['fatal']}")
            print("        남은 청크는 규칙 판정으로 둡니다 — 해결한 뒤 [재분석만]을 누르면 AI 판정만 이어서 합니다.")
        elif consec >= ABORT_FAIL_CHUNKS:
            st["aborted"] = True
            print(f"        연속 {consec}청크 0건 — 남은 청크는 규칙 판정으로 둡니다"
                  "(Copilot 상태를 확인한 뒤 재실행하면 이어서 판정됩니다)")
        elif consec >= SOFT_FAIL_CHUNKS and not st["soft"]:
            st["soft"] = True
            print(f"        연속 {consec}청크 0건 — 적응 재시도(반분·빠진 행)를 끄고 1회씩만 시도합니다")
    if st["aborted"]:
        print(f"        중단으로 건너뛴 청크 포함 0건 청크 {n_fail}/{len(chunks)}")

    # 판정 반영 — 과제명은 체계의 대표 표기로 정규화, 미판정 행은 match 키워드로 매핑
    shutil.copy2(sp, os.path.join(rep, f"signals_{tag}_rules.csv"))
    kept, dropped_rows = [], []
    for i, r in enumerate(rows):
        j = judged.get(i)
        if j is None:
            r.update(model=rule_model(r, models), worktype="사무",
                     detail=r.get("activity") or "기타", judge="규칙")
            kept.append(r)
        elif not j["work"]:
            dropped_rows.append(r)          # 비업무 — 시간 재산정(rehours_meta)에서도 뺀다
        else:
            r.update(model=to_model(j["model"], models) or "공통", worktype=j["worktype"] or "사무",
                     detail=j["detail"] or r.get("activity") or "기타", judge="AI")
            kept.append(r)
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
    cols = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge"]
    with open(sp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in kept:
            r["project"] = r.get("model", r.get("project", ""))
            r["activity"] = r.get("detail", r.get("activity", ""))
            w.writerow({c: r.get(c, "") for c in cols})
    # 판정 중 새로 발견된 과제(체계에 없던 이름) → entities에 discovered로 기록,
    # 다음 실행의 taxonomy 힌트로 자동 순환된다. 비교는 대소문자 무시(중복 계상 방지).
    # 비교는 ukey2 — .lower() 로만 보면 '광학설계' 가 '광학 설계' 의 옆에 새 과제로 적립되고,
    # 그것이 다음 실행의 taxonomy 힌트가 되어 분할이 영구화된다(재분석해도 낫지 않던 이유).
    model_names_l = {ukey2(m["name"]) for m in models}
    discovered = sorted({j["model"].strip() for j in judged.values()
                         if j["work"] and j["model"].strip()
                         and ukey2(j["model"].strip()) not in model_names_l
                         and not NOISE_MODEL.match(j["model"].strip())})
    if discovered:
        print("        판정 중 새 과제 발견: " + ", ".join(discovered))
        ent_obj["models"] = sanitize_models(
            ent_obj["models"] + [{"name": d, "match": [d.lower()], "obs": "판정 중 발견"}
                                 for d in discovered])
        ent_obj["discovered"] = discovered
    if judged or not ent_prev:
        with open(ent_p, "w", encoding="utf-8") as f:
            json.dump(ent_obj, f, ensure_ascii=False, indent=1)
    else:
        print("        판정 0건 — 기존 entities 파일을 보존합니다(규칙 폴백 체계로 덮지 않음)")

    dropped = len(dropped_rows)
    # failed_chunks = 0건으로 끝난 청크(왕복 실패·JSON 없음 모두 — 예전엔 JSON 없음이 빠져 0 으로 보였다),
    # partial_chunks = 일부만 판정된 청크, failed_rows = 실패로 규칙에 남은 행, omitted_rows = 온전한 답인데
    # 모델이 빠뜨린 행, repaired = 잘린 답을 복구한 왕복, retries = 적응 분할 재왕복, roundtrips = 총 왕복.
    with open(os.path.join(rep, f"ai_judgments_{tag}.json"), "w", encoding="utf-8") as f:
        json.dump({"model": model_name, "total": len(rows), "judged": len(judged),
                   "dropped_nonwork": dropped, "chunks": len(chunks), "failed_chunks": n_fail,
                   "partial_chunks": n_partial, "failed_rows": st["failed_rows"],
                   "omitted_rows": st["omitted_rows"], "repaired": st["repaired"],
                   "retries": st["retries"], "roundtrips": st["roundtrips"],
                   "aborted": st["aborted"], "chunk_rows": chunk_n, "prompt_budget": PROMPT_BUDGET,
                   "items": {str(k): v for k, v in judged.items()}}, f, ensure_ascii=False, indent=1)

    # A30 — 비업무로 버린 신호의 시간을 총량에서도 뺀다(mm_meta 갱신). write_outputs 보다 먼저.
    rh = rehours_meta(kept, dropped_rows, tag, cfg, rep, os.path.join(ROOT, "data"))
    if rh:
        _bef = f"{rh['before_mm']:.2f}" if rh.get("before_mm") is not None else "?"
        print(f"        비업무 제외 {rh['dropped_n']}건 · −{rh['dropped_h']:.1f}h → 투입 {_bef}→"
              f"{rh['total_mm']:.2f} MM (로드율 {rh['load_pct']:.0f}%) — 시간 재산정 반영")
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

    if not judged:
        # 판정이 한 건도 없다 — 왕복이 전부 실패했거나 응답을 하나도 해석하지 못했다. 예전에는
        # 여기서도 0 을 돌려줘 run.py 가 'AI 판정 ok' 로 적고 정제·Agentic·워크플로우까지 진행했고,
        # 내러티브 왕복 N 회가 또 실패하며 ai_narratives 를 {} 로 덮었다(F3). 화면은 규칙 임시
        # 결과(signals/mm_rows)로 두고, 사유는 마지막 줄 JSON 으로 run.py 에 넘긴다.
        if n_fail == len(chunks) and last_err and not st["repaired"]:
            err = "AI 판정 실패(왕복 전부 실패)"
        else:
            err = (f"AI 판정 0건(청크 {len(chunks)}개 전부 0건 · 왕복 {st['roundtrips']}회"
                   + (" · 연속 실패로 중단" if st["aborted"] else "") + ")")
        # 성공 왕복의 프롬프트 파일은 지워진다(V-06) — 남아 있는 실패 청크 파일 하나를 안내한다
        left = sorted(_glob.glob(os.path.join(rep, f"judge_chunk*_{tag}.md")))
        hint = last_err or (f"report\\{os.path.basename(left[0])} 를 Copilot 에 직접 붙여 응답 형식을 확인하세요" if left
                            else "Copilot 응답 형식을 [AI 연결 진단]으로 확인하세요")
        print(f"[judge] {err} — {hint}")
        print("        signals/mm_rows 는 규칙 판정으로 두고, 월별 내러티브·entities 기존 파일은 보존합니다")
        print(json.dumps({"ok": False, "error": err, "hint": hint, "judged": 0,
                          "chunks": len(chunks), "failed_chunks": n_fail}, ensure_ascii=False))
        return 3

    # [월별] 내러티브
    if "--no-narrate" not in sys.argv:
        print("[judge] 월별 리뷰 내러티브 생성 중…")
        progress("월별 리뷰", 0, 1)
        nar = narrate(kept, total_mm, tag)
        save_narratives(nar, rep, tag)
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    sys.exit(main())
