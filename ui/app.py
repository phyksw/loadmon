# -*- coding: utf-8 -*-
"""
app.py — AgentFinder32 로컬 화면(표준 라이브러리만).

  python ui\\app.py          또는  AgentFinder32-UI.bat 더블클릭

탭: Agentic AI 후보(기본) · 워크플로우 · 업무 분류 · 수집·제외 현황 · 공유 · 내 데이터.
127.0.0.1 에서만 열린다. 화면은 bat 을 실행한 사용자만 연다 — bat 이 연 주소(/?k=시작 열쇠)로 들어온 브라우저만 세션 쿠키(af32s)를
받고, 쿠키가 없는 요청은 GET 까지 모두 403 이다. 모든 요청은 Host 를 확인하고, POST 는 JSON 형식·Origin·화면 열쇠(X-AF32-UI)를 확인한다.
공유·모두 지우기 POST 는 바로 앞의 GET·미리보기가 준 일회용 표(nonce)도 확인한다.
화면은 묻는 단계 없이 처음부터 탭을 보인다 — 맨 위에 consent.PAPER_CONSENT_LINE 한 줄과 [안내](읽기만 하는 안내 · [닫기]뿐)가 늘
보인다. 열지 않는 것은 둘뿐이다: 다른 Windows 사용자의 자료·주인을 모르는 자료(읽기 전용 화면 — [열지 않고 지우기]만)와 모두
지우기가 끝나지 않은 폴더(다음 시작 때 마저 지운다). 그때는 분석 자료를 내주지 않는다(403).
AI 는 회사 M365 Copilot 왕복만 쓴다. 조직장 서버로 보내는 것은 [공유] 탭에서 사람이 고르고 확인한 것뿐이다.
시작 순서: install.startup_check(설치 위치·옛 LoadMonitor 파일) → retention.purge_legacy → 끝나지 않은 모두 지우기 마치기 →
retention.purge → 내 자료일 때만 retention.sync_task(매일 정리 예약 작업을 설정에 맞춘다).
"""
import csv
import glob
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:          # judge·agentic·teamup 등 루트 모듈 임포트용
    sys.path.insert(0, ROOT)      # (ui\app.py 로 실행하면 sys.path[0]이 ui\ 라 루트가 안 잡힌다)
from progress import parse as parse_progress  # noqa: E402  (core 경로 등록 뒤에 임포트)
import afcfg  # noqa: E402  — 설정 기본값·하한 단일원(D22)
import consent  # noqa: E402  — 안내 · 내 자료 확인 · 모두 지우기(D12 — 모듈·함수 이름은 예전 그대로)
import install  # noqa: E402  — 설치 위치·옛 파일 검사(D20·D21)·설치 식별(D17)
import lmname  # noqa: E402  — AF32 이름 단일원(포트·Edge 프로필·%TEMP% 접두·화면 제목)
import period  # noqa: E402  — 분석 기간 단일원(D2)
import retention  # noqa: E402  — 보관기한·자동 삭제(D13·D20)

REPORT = os.path.join(ROOT, "report")
DATA = os.path.join(ROOT, "data")
SHARE_DIR = os.path.join(REPORT, "share")
TEAMUP = os.path.join(ROOT, "teamup.py")
NO_WIN = 0x08000000
VERSION = "AF32 v1.0"
LOCK = threading.Lock()
REPORT_LOCK = threading.Lock()       # [내 리포트 만들기] 직렬화 — report_out 이 report\ 를 읽는 동안 다른 작업이 다시 쓰지 않게
JOB = {"running": False, "log": [], "step": "", "started": 0.0, "pid": 0,
       "phase": "", "done": 0, "total": 0, "phase_started": 0.0, "last_out": 0.0}
UI_TOKEN = secrets.token_urlsafe(24)  # 화면 열쇠 — 프로세스마다 새로. PAGE 에 심어 보내고 POST 의 X-AF32-UI 로 돌려받는다
# 화면 세션 — 화면은 bat 을 실행한 사용자만 연다. main() 이 여는(또는 찍는) 주소 /?k=<시작 열쇠> 로 들어온 브라우저만 세션 쿠키
# af32s(HttpOnly · SameSite=Strict · Path=/)를 받는다. 쿠키가 없는 요청은 GET 까지 모두 403 — 같은 PC 의 다른 계정·프로그램은
# 화면 열쇠(PAGE)도 분석 결과도 받지 못한다. 시작 열쇠는 이 프로세스와 data\ui_session.json(두 번째 bat 실행이 열린 화면으로
# 잇는다 · 날짜만)에만 있다.
# /?k= 의 답은 303 이 아니라 쿠키를 주고 / 로 옮겨 가는 작은 화면이다(launch_page) — bat 이 연 주소는 브라우저 밖에서 온 이동이라
# 브라우저에 따라 SameSite=Strict 쿠키를 그 이동(과 이어지는 303)에 싣지 않을 수 있다. 화면 안에서 다시 옮겨 가면 늘 싣는다.
# 쿠키는 포트를 가리지 않는다(127.0.0.1 의 모든 포트가 같은 쿠키를 쓴다) — 설치 폴더 둘의 화면을 함께 열어도 서로 지우지 않게,
# 쿠키 값에는 이미 있던 다른 화면의 세션 값도 점(.)으로 이어 둔다(SESSION_KEEP 개까지 · 내 값이 그 안에 있으면 통과).
SESSION_COOKIE = "af32s"
LAUNCH_KEY = secrets.token_urlsafe(32)   # 시작 열쇠 — /?k= 로 들어오면 세션 쿠키를 준다(이 프로세스가 사는 동안)
SESSION_ID = secrets.token_urlsafe(32)   # 세션 쿠키 값 — 시작 열쇠로 들어온 브라우저에만
SESSION_KEEP = 4                         # 쿠키 하나에 함께 두는 세션 값 수(내 것 포함)
SESSION_FILE = "ui_session.json"         # data\ 아래 {product, port, pid, key, date} — main() 이 쓰고 끝날 때 지운다
SESSION_FILE_ON = [False]                # main() 이 열쇠 파일을 썼나 — 자료를 모두 지운 뒤에도 서버가 살아 있으면 다시 쓴다
KEY_RX = re.compile(r"[A-Za-z0-9_-]{20,128}")
PAGE_PATHS = ("/", "/index.html", "/guide", "/docs")   # 세션이 없을 때 안내 HTML 로 답하는 경로(그 밖은 JSON 403)
NONCE_TTL = 600.0                    # 일회용 표 수명(초) — 공유·모두 지우기 POST
NONCE_MAX = 256
NONCES = {}                          # 표 → (용도, 만료 시각, 덧붙인 값)
NONCE_LOCK = threading.Lock()
BODY_MAX = 262144                    # POST 본문 상한(바이트) — 넘으면 본문을 읽지 않고 400(bad json)
DRAIN_MAX = 1 << 20                  # 너무 큰 본문은 이만큼까지만 읽어 버린다(브라우저가 응답 대신 끊김을 보지 않게)
STARTUP = {"blocked": "", "legacy": None, "purge": None}
NOTICES = []                         # 화면에 한 번만 알릴 글(옛 자료 정리 건수 등) — /api/status 가 한 번 싣고 비운다
NOTICE_LOCK = threading.Lock()
BLOCKED_SEC = 600.0                  # 시작 검사에 걸린 화면을 띄워 두는 시간(초) — 그 뒤 스스로 끝난다


def kill_job():
    """실행 중인 분석 프로세스 트리(run→mine/judge→copilot_auto)를 통째로 종료.
    taskkill 대신 Job 째(core\\proc.kill_tree — 띄울 때 proc.attach 로 넣어 둔다). Job 에서 이탈한 전용 Edge 는
    남고, 그 Edge 는 close_edge(CDP)가 닫는다(P6)."""
    with LOCK:
        pid = JOB.get("pid") or 0
    if pid:
        try:
            import proc as _proc
            _proc.kill_tree(pid)
        except Exception:  # noqa: BLE001 - 종료 실패가 [중지] 응답을 막지 않는다
            pass
        with LOCK:
            JOB["pid"] = 0


def _ca_mod():
    r"""tools\copilot_auto(같은 프로세스 — 처음 쓸 때 한 번 불러온다)."""
    tools = os.path.join(ROOT, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import copilot_auto
    return copilot_auto


def close_edge(reason="ui", tidy=True, budget=None):
    r"""우리가 띄운 전용 Edge 만 CDP Browser.close 로 닫는다(tools\copilot_auto.close_own_edge — owner.json 표식).
    프로세스를 띄우지 않는다. 로그인 대기 중이거나 keepEdgeOpen 이면 닫지 않고, 사람이 띄운 Edge·다른 판의 Edge 는 표식이 없어
    건드리지 않는다(P6). tidy=False — 닫기 전 Copilot 채팅 정리를 건너뛴다(콘솔 창 닫기 — 윈도가 몇 초만 준다).
    budget — 닫기 전 정리(이 도구가 연 채팅 다시 지우기 — sweep_owned)의 상한(초). 없으면 copilot_auto.SWEEP_SEC."""
    try:
        copilot_auto = _ca_mod()
        if not tidy:
            return copilot_auto.close_own_edge(None, reason, tidy=False)
        if budget is not None:
            return copilot_auto.close_own_edge(None, reason, budget=budget)
        return copilot_auto.close_own_edge(None, reason)
    except Exception as e:  # noqa: BLE001 - 정리 실패가 화면·종료를 막지 않는다
        return {"closed": False, "why": f"error:{type(e).__name__}"}


UI_SWEEP_SEC = 60          # [중지]·화면 종료가 기다려 주는 채팅 정리 상한(초 · copilot_auto.SWEEP_UI_SEC 와 같다)
CHAT_SWEEP_SEC = 300       # [이 도구가 연 Copilot 채팅 지우기] 의 상한(초 · copilot_auto.SWEEP_BUTTON_SEC 와 같다)
CHAT_SWEEP_NOTE = ("기록에 없는 채팅(예전 판이 연 것·직접 붙여 넣은 것)은 이 도구가 연 것인지 확인할 수 없어 그대로 두었습니다")


def chat_job_run():
    r"""화면 작업([Agentic AI 후보 발굴]·[워크플로우 재분석])의 실행 열쇠. 자식 프로세스에 AF32_CHAT_RUN 으로 넘기면 그 작업이 연
    Copilot 채팅이 한 실행으로 묶인다(끝 한 줄 — job_chat_end). 날짜 + PID + 임의 값 — 시각은 넣지 않는다(채팅 기록에 남는다 · D10,
    run.start_run_id 와 같은 꼴)."""
    return f"job-{time.strftime('%Y%m%d')}-{os.getpid()}-{secrets.token_hex(3)}"


def job_chat_end(run, label=""):
    r"""화면 작업이 끝난 뒤: 이 도구가 연 Copilot 채팅을 다시 지우고(copilot_auto.sweep_owned — 같은 프로세스 · 상한 UI_SWEEP_SEC·3)
    그 작업의 한 줄('Copilot 채팅: 이번 실행에서 연 N개 · 지운 M개 · 남긴 K개 (까닭: …)')을 진행 로그에 남긴다 → 그 줄 | "".
    전용 Edge 가 꺼져 있으면 띄우지 않는다(남은 채팅은 다음 정리가 지운다). 예외를 내지 않는다."""
    try:
        ca = _ca_mod()
        ca.sweep_owned(None, budget=UI_SWEEP_SEC * 3, why="job", run=run)
        rep = ca.chat_run_report(None, run=run)
        if not ca.chat_run_busy(rep):
            return ""
        line = str(rep.get("line") or "")
        if line:
            log((f"[{label}] " if label else "") + line)
        return line
    except Exception as e:  # noqa: BLE001 - 정리 실패가 작업 결과를 바꾸지 않는다
        log(f"[Copilot 채팅] 정리를 건너뜀({type(e).__name__})")
        return ""


def chat_sweep_now():
    r"""[이 도구가 연 Copilot 채팅 지우기]: 기록(owned[])에 있는 채팅만 다시 지운다(copilot_auto.sweep_owned — 같은 프로세스).
    전용 Edge 가 꺼져 있으면 띄우되 로그인은 하지 않는다(로그인 화면이면 아무것도 하지 않고 안내) · 이 버튼이 띄운 Edge 만 끝나고 닫는다.
    → {"ok", "line", "note", "login", "code", "deleted", "kept", "left"} (숫자·사유만)."""
    ca = _ca_mod()
    run = "btn-" + chat_job_run()[4:]
    rep = ca.sweep_owned(None, budget=CHAT_SWEEP_SEC, why="button", launch=True, run=run, lock_wait=30)
    out = {"ok": True, "code": str(rep.get("code") or ""), "login": bool(rep.get("login")),
           "deleted": int(rep.get("deleted") or 0), "kept": int(rep.get("kept") or 0), "left": int(rep.get("left") or 0),
           "note": CHAT_SWEEP_NOTE}
    code, tried = out["code"], int(rep.get("tried") or 0)
    if code == "none" and not tried:
        out["line"] = "Copilot 채팅: 이 도구의 기록에 지울 채팅이 없습니다"
    elif out["login"] and not tried:
        out["ok"] = False
        out["line"] = "전용 Edge 창에서 로그인한 뒤 다시 누르세요(이 도구는 로그인하지 않습니다 — 아무것도 지우지 않았습니다)"
    elif code == "busy":
        out["ok"] = False
        out["line"] = "다른 작업이 전용 Edge 를 쓰고 있습니다 — 끝난 뒤 다시 누르세요"
    elif code in ("noedge", "notab") and not tried:
        out["ok"] = False
        out["line"] = "전용 Edge 의 Copilot 창을 열지 못했습니다 — [AI 연결 진단]으로 상태를 확인한 뒤 다시 누르세요"
    elif code == "off":
        out["line"] = "Copilot 채팅 지우기가 설정으로 꺼져 있습니다(config.json 의 copilotAuto.deleteChats)"
    else:
        r2 = ca.chat_run_report(None, run=run, button=True)
        out["line"] = str(r2.get("line") or "")
        if code == "hold":
            out["line"] += " · 지운 뒤 확인이 되지 않아 더 지우지 않았습니다"
        if out["login"]:
            out["line"] += " · 그 사이 로그인이 풀려 남은 채팅은 지우지 못했습니다(전용 Edge 창에서 로그인한 뒤 다시 누르세요)"
    if rep.get("launched"):
        try:
            ca.close_own_edge(None, "chat_sweep", tidy=False)       # 이 버튼이 띄운 Edge 만 닫는다(이미 정리했다)
        except Exception:  # noqa: BLE001
            pass
    return out


def cleanup_children():
    with LOCK:
        was_run = bool(JOB["running"] and JOB.get("pid")) and str(JOB.get("step") or "") == RUN_STEP
    try:
        kill_job()
    except Exception:
        pass
    if was_run:
        drop_raw_now(check=False)            # 멈춘 [분석 실행]이 남긴 원자료(COM)를 지운다
    try:
        close_edge("ui_exit", budget=UI_SWEEP_SEC)
    except Exception:
        pass


# atexit.register(cleanup_children) 는 main() 안에서만 — 모듈을 임포트하는 쪽(시험)이 끝날 때 전용 Edge 를 건드리지 않게.
PORT = [0]


# ── 창을 닫으면 작업도 멈춘다(창 닫힘 판정) ─────────────────────────────────────────────────────────
# 화면은 10초마다 /api/alive 로 '이 탭이 살아 있다'(탭 id·visibilityState)를 알리고, 닫히거나 떠날 때(pagehide) /api/bye 를
# keepalive fetch 로 보낸다. 판정 스레드(main 에서만)가 ui_close_decision 으로 판정해 'exit' 면 [중지]+종료 정리와 같은 길(kill_job ·
# 전용 Edge 닫기 — 채팅 정리 포함)로 작업을 멈추고 서버를 끝낸다. 조직장 팀 서버(teamserver.py)는 Job 밖이라 산다.
#   · 첫 /api/alive 전에는 판정하지 않는다(armed) — --no-browser·AF32_NO_BROWSER·시험은 저절로 끝나지 않는다.
#   · 작별 뒤 CLOSE_GRACE 초는 기다린다 — 새로고침(F5)·이동은 작별 직후 새 탭이 다시 알린다.
#   · 모든 탭이 CLOSE_SILENCE 초 넘게 조용하면 닫힌 것으로 본다(브라우저째 강제 종료 — 작별이 못 온다).
#   · 잠든 탭은 'frozen', 알림 창이 열린 탭은 'dialog' 를 알린다 — CLOSE_ASLEEP 초까지 살아 있다고 본다.
#   · 작별한 탭 id 는 기억해 둔다(gone) — 늦게 온 '숨김' 신호가 닫힌 탭을 되살리지 않게.
#   · PC 가 잠들었다 깨면(판정 루프가 CLOSE_RESUME_GAP 넘게 늦게 깸) 그동안 탭도 멈춰 있었다 — 시각을 그만큼 민다.
#   · 사람이 화면을 볼 수 없는 동안(화면 보호기 · 잠금 · AWAY_IDLE_SEC 넘게 입력 없음 — _screen_away)의 조용함은 세지 않는다.
#   · 도는 작업이 없으면 조용함만으로는 CLOSE_SILENCE_IDLE(30분) 뒤에야 끝낸다.
# 끄기: config.json 의 uiAutoExit=false(예전처럼 창을 닫아도 서버·작업이 계속 돈다).
CLOSE_GRACE = 20.0
CLOSE_SILENCE = 180.0
CLOSE_SILENCE_IDLE = 1800.0         # 도는 작업·리포트 만들기가 없을 때의 조용함 상한(초) — ui_close_decision(busy=False)
CLOSE_ASLEEP = 4 * 3600.0
CLOSE_EVERY = 5.0
CLOSE_RESUME_GAP = 30.0
CLOSE_LOCK = threading.Lock()
UI_CLOSE = {"tabs": {}, "vis": {}, "gone": {}, "bye": 0.0, "armed": False}
CLOSE_LINE_BUSY = "[ui] 화면 창이 닫혀 실행 중인 작업을 멈추고 서버를 끝냅니다"
CLOSE_LINE_IDLE = "[ui] 화면 창이 닫혀 서버를 끝냅니다"
CLOSE_VIS = ("visible", "hidden", "frozen", "dialog")    # /api/alive 가 받는 탭 상태(그 밖은 visible) — dialog = 알림 창이 열려 있음
CLOSE_WHY_KO = {"bye": "창 닫힘", "silence": f"{int(CLOSE_SILENCE // 60)}분 넘게 화면 신호 없음",
                "silence_idle": f"{int(CLOSE_SILENCE_IDLE // 60)}분 넘게 화면 신호 없음(도는 작업 없음)",
                "dialog": "알림 창이 열려 있음", "asleep": "탭이 잠듦"}
AWAY_IDLE_SEC = 180.0               # 키보드·마우스 입력이 이만큼(초) 없으면 사람이 화면을 보지 않는 것으로 본다(_screen_away)
STOP_STAGE = "중단(창 닫힘)"         # last_run.json 단계 이름 — 다음 화면이 '마지막 단계: 중단(창 닫힘)' 으로 말한다(run.py 와 같다)
EDGE_FAST_SEC = 2.5                 # 콘솔 창 닫기 때 전용 Edge 닫기를 기다리는 상한(윈도는 처리기에 약 5초를 준다)


def _close_cfg(c=None):
    """판정 설정 — {on, grace, silence, silence_idle, asleep, away}. on 은 config.json 의 uiAutoExit(기본 true)."""
    c = cfg() if c is None else c
    return {"on": _cfg_bool((c or {}).get("uiAutoExit"), True), "grace": CLOSE_GRACE,
            "silence": CLOSE_SILENCE, "silence_idle": CLOSE_SILENCE_IDLE, "asleep": CLOSE_ASLEEP, "away": True}


def _ui_busy():
    """지금 멈출 것이 있나(화면에서 띄운 작업이 돌거나 [내 리포트 만들기]가 도는 중) → 창 닫힘 판정의 busy."""
    with LOCK:
        busy = bool(JOB["running"])
    return busy or REPORT_LOCK.locked()


# 끝내면 안 되는 작업 — 모두 지우기·자료 지우기는 중간에 끊기면 서버 사본·이 PC 의 자료가 반쯤 남는다. 도는 동안에는 창을 닫아도
# 서버를 끝내지 않고(ui_close_decision hold) [서버 종료]는 409, 서버가 끝날 때는 끝날 때까지 기다린다(wait_critical).
WIPE_STEP = "모두 지우기"            # [모두 지우기(서버 사본 포함)](POST /api/consent/withdraw)의 JOB 단계 이름
CRITICAL_STEPS = (WIPE_STEP, "자료 지우기")
CRITICAL_WAIT_SEC = 600.0
RUN_STEP = "분석 실행"               # [분석 실행](run.py — COM 원자료를 만드는 유일한 화면 작업)의 JOB 단계 이름


def run_active():
    r"""이 설치 폴더의 분석(run.py — data\run.lock · 수집기)이 돌고 있나(retention.run_active). 알 수 없으면 False —
    지우기를 막지 않는 쪽이 개인정보에 안전하다(consent._busy 와 같은 규칙)."""
    try:
        return bool(retention.run_active(ROOT))
    except Exception:  # noqa: BLE001 - 판정 실패가 지우기를 막지 않는다
        return False


def _raw_files():
    r"""data\outlook\raw 바로 아래의 보통 파일(COM 원자료 — 바깥 사람 이름·주소가 든다 · retention.raw_left: 연결은 따라가지
    않는다). 없으면 []."""
    try:
        return list(retention.raw_left(ROOT))
    except Exception:  # noqa: BLE001 - 읽지 못하면 없는 것으로(다음 분석 시작이 지운다)
        return []


def _others_data():
    """이 폴더의 자료가 다른 Windows 사용자의 것(또는 주인을 모르는 것)인가 — 그 자료는 지금 사용자가 [열지 않고 지우기]를
    고를 때만 지운다(D17). 상태를 읽지 못하면 참(건드리지 않는 쪽)."""
    try:
        return bool(consent.status(ROOT, cfg()).get("other_user"))
    except Exception:  # noqa: BLE001
        return True


def owner_msg(st):
    """열지 않는 자료를 만났을 때의 한 줄 — 설치 정보가 없어 주인을 모르는 자료(unknown_owner — 내 자료일 수도 있다)면 그렇게,
    아니면 다른 사용자의 자료라고 말한다(core\\install 의 문장 그대로)."""
    if (st or {}).get("unknown_owner"):
        return str(getattr(install, "UNKNOWN_OWNER_MSG", "") or install.OTHER_USER_MSG)
    return install.OTHER_USER_MSG


def paper_line():
    """화면 맨 위에 늘 보이는 한 줄 — core/consent.py 의 문장 그대로(PAPER_CONSENT_LINE · 안내문 '내 권리' 절의 첫 줄과 같다).
    화면은 그 문장을 보이기만 한다 — 묻지도 기록하지도 않는다."""
    return str(consent.PAPER_CONSENT_LINE)


def gate_refusal(st):
    """열지 않는 까닭 → 403 본문 {"ok": False, "error": "consent_required", "reason", "msg"}(error 이름은 예전 그대로).
    reason 은 consent.require 와 같다: 'other_user'(다른 사용자의 자료·주인을 모르는 자료 — owner_msg) · 'withdrawn'(모두 지우기가
    끝나지 않았다 — consent.WIPING_MSG). 상태를 읽지 못했으면 'error'. 사람에게 묻는 단계가 없으므로 그 밖의 까닭은 없다."""
    st = st or {}
    if st.get("other_user") or st.get("unknown_owner"):
        return {"ok": False, "error": "consent_required", "reason": "other_user", "msg": owner_msg(st)}
    if st.get("withdrawal_state") == consent.WD_IN_PROGRESS:
        return {"ok": False, "error": "consent_required", "reason": "withdrawn", "msg": consent.WIPING_MSG}
    return {"ok": False, "error": "consent_required", "reason": "error",
            "msg": "자료 상태를 확인하지 못했습니다 — 창을 닫고 다시 실행하세요"}


def drop_raw_now(check=True):
    r"""남은 COM 원자료(data\outlook\raw\*)를 지운다(retention.drop_raw). 멈춘 [분석 실행]·창 닫힘 뒤에는 바로(check=False),
    화면 시작 때는 내 자료이고 이 폴더의 다른 분석(AgentFinder32.bat 의 run.py)이 돌지 않을 때만(check=True — run_active).
    → 지운 수 | None(지울 것이 없음·건너뜀·실패). 예외를 내지 않는다."""
    if not _raw_files():
        return None
    try:
        if check and _others_data():
            return None
        if check and run_active():
            log("[정리] 다른 분석이 돌고 있어 남은 원자료는 그 분석이 정리하게 둡니다")
            return None
        n = int(retention.drop_raw(ROOT) or 0)
    except Exception as e:  # noqa: BLE001 - 정리 실패가 멈춤·시작을 막지 않는다(다음 실행 시작이 다시 지운다)
        log(f"[정리] 남은 원자료를 지우지 못했습니다({type(e).__name__}) — 다음 분석 시작 때 다시 지웁니다")
        return None
    if n:
        log(f"[정리] 멈춘 수집이 남긴 원자료 {n}개를 지웠습니다(바깥 사람 이름·주소가 든 임시 파일)")
    return n


def _critical_busy():
    """모두 지우기·자료 지우기가 도는 중인가(CRITICAL_STEPS)."""
    with LOCK:
        return bool(JOB["running"]) and str(JOB.get("step") or "") in CRITICAL_STEPS


def wiping_now():
    """[모두 지우기(서버 사본 포함)]가 지금 이 서버에서 도는 중인가(JOB 단계 WIPE_STEP) — 화면이 '지금 지우고 있다'와 '지난번에
    마치지 못했다'를 가려 말한다."""
    with LOCK:
        return bool(JOB["running"]) and str(JOB.get("step") or "") == WIPE_STEP


def wait_critical(limit=CRITICAL_WAIT_SEC, every=0.5, say=None):
    """서버가 끝나기 전에 — 모두 지우기·자료 지우기가 끝날 때까지(limit 초까지) 기다린다 → 끝났나."""
    t_end = time.monotonic() + float(limit)
    told = False
    while _critical_busy() and time.monotonic() < t_end:
        if not told and say is not None:
            try:
                say("[ui] 자료 지우기가 끝날 때까지 기다립니다 — 창을 닫지 마세요")
            except Exception:  # noqa: BLE001
                pass
            told = True
        time.sleep(every)
    return not _critical_busy()


def _screen_away():
    """지금 사람이 화면을 볼 수 없나 → 참/거짓. ① 화면 보호기가 도는 중(SPI_GETSCREENSAVERRUNNING) ② 잠금·끊긴 원격(입력 데스크톱을
    열 수 없음 — OpenInputDesktop) ③ AWAY_IDLE_SEC 넘게 키보드·마우스 입력 없음(GetLastInputInfo). ctypes 로만(프로세스를 띄우지
    않는다 · 관리자 권한 없음). 윈도가 아니거나 읽기 오류면 거짓."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.WinDLL("user32")
        k32 = ctypes.WinDLL("kernel32")
        running = wintypes.BOOL(False)
        if u32.SystemParametersInfoW(0x0072, 0, ctypes.byref(running), 0) and running.value:
            return True
        u32.OpenInputDesktop.restype = wintypes.HANDLE
        u32.OpenInputDesktop.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        u32.CloseDesktop.argtypes = (wintypes.HANDLE,)
        h = u32.OpenInputDesktop(0, False, 0x0100)          # DESKTOP_SWITCHDESKTOP — 잠긴 화면이면 열 수 없다(NULL)
        if not h:
            return True
        u32.CloseDesktop(h)

        class _LastInput(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
        li = _LastInput(ctypes.sizeof(_LastInput), 0)
        k32.GetTickCount.restype = wintypes.DWORD
        if u32.GetLastInputInfo(ctypes.byref(li)):
            idle_ms = (k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF
            return idle_ms >= AWAY_IDLE_SEC * 1000
        return False
    except Exception:  # noqa: BLE001 - 모르면 예전 그대로(조용함을 센다)
        return False


def ui_close_decision(now, tabs, last_bye, armed, cfg=None, busy=True, hold=False):
    """창 닫힘 판정(순수 함수) → ("keep"|"exit", 사유).
    tabs = {탭 id: 마지막 신호 시각} 또는 {탭 id: (시각, 상태)} — 상태 visible·hidden·frozen·dialog(작별한 탭은 이미 빠져 있다).
    last_bye = 마지막 작별 시각(없으면 0) · armed = 첫 신호를 받았나 · cfg = {on, grace, silence, silence_idle, asleep}(_close_cfg).
    busy = 멈출 작업이 있나(_ui_busy). 거짓이면 조용함 상한이 silence_idle(30분)이고, 알림 창이 열린 탭(dialog)은 잠든 탭처럼 둔다.
    hold = 끝내면 안 되는 작업(모두 지우기·자료 지우기 — _critical_busy)이 도는가 — 그동안은 창을 닫아도 끝내지 않는다.
    사유: off · hold · not_armed · alive · asleep · dialog · grace · bye · silence · silence_idle."""
    c = {"on": True, "grace": CLOSE_GRACE, "silence": CLOSE_SILENCE, "silence_idle": CLOSE_SILENCE_IDLE,
         "asleep": CLOSE_ASLEEP}
    c.update(cfg or {})
    if not c["on"]:
        return "keep", "off"
    if hold:
        return "keep", "hold"
    if not armed:
        return "keep", "not_armed"
    quiet = c["silence"] if busy else max(c["silence"], c["silence_idle"])
    last = 0.0
    for v in (tabs or {}).values():
        t, vis = (v[0], v[1]) if isinstance(v, (tuple, list)) else (v, "visible")
        t = float(t or 0.0)
        last = max(last, t)
        age = now - t
        if age < quiet:
            return "keep", "alive"
        if vis in ("frozen", "dialog") and age < c["asleep"]:
            return "keep", ("dialog" if vis == "dialog" else "asleep")
    if last_bye and now - last_bye < c["grace"]:
        return "keep", "grace"
    if last_bye and last_bye >= last:
        return "exit", "bye"
    return "exit", ("silence" if busy else "silence_idle")


def _close_why_ko(why, tabs=None):
    """끝낸 까닭(한국어) — CLOSE_WHY_KO. 조용함으로 끝냈는데 알림 창이 열린 탭(dialog)이 있었으면 그것도 붙인다."""
    s = CLOSE_WHY_KO.get(why, str(why))
    if why != "bye" and any(isinstance(v, (tuple, list)) and len(v) > 1 and v[1] == "dialog"
                            for v in (tabs or {}).values()):
        s += f" · {CLOSE_WHY_KO['dialog']}({int(CLOSE_ASLEEP // 3600)}시간 넘게)"
    return s


def ui_tab_alive(tab, vis="visible", now=None):
    """/api/alive — 탭이 살아 있다. 첫 신호에 판정을 켠다(armed). 작별한 탭 id 의 늦은 신호는 버린다. → 받았나"""
    tab = str(tab or "").strip()[:64]
    if not tab:
        return False
    vis = vis if vis in CLOSE_VIS else "visible"
    with CLOSE_LOCK:
        if tab in UI_CLOSE["gone"]:
            return False
        tabs = UI_CLOSE["tabs"]
        tabs[tab] = time.time() if now is None else now
        UI_CLOSE["vis"][tab] = vis
        UI_CLOSE["armed"] = True
        while len(tabs) > 64:                   # 표가 끝없이 자라지 않게 — 가장 오래 조용한 탭부터 버린다
            old = min(tabs, key=tabs.get)
            tabs.pop(old, None)
            UI_CLOSE["vis"].pop(old, None)
    return True


def ui_tab_bye(tab, now=None):
    """/api/bye — 탭이 닫히거나 떠났다(pagehide). 그 탭을 빼고(id 는 gone 에 기억) 작별 시각을 남긴다."""
    tab = str(tab or "").strip()[:64]
    t = time.time() if now is None else now
    with CLOSE_LOCK:
        if tab:
            UI_CLOSE["tabs"].pop(tab, None)
            UI_CLOSE["vis"].pop(tab, None)
            gone = UI_CLOSE["gone"]
            gone[tab] = t
            while len(gone) > 256:
                gone.pop(min(gone, key=gone.get), None)
        UI_CLOSE["bye"] = t
    return True


def _close_snapshot():
    with CLOSE_LOCK:
        tabs = {k: (t, UI_CLOSE["vis"].get(k, "visible")) for k, t in UI_CLOSE["tabs"].items()}
        return tabs, UI_CLOSE["bye"], UI_CLOSE["armed"]


def _close_shift(gap, bye=True):
    """PC 가 잠들었다 깼다 — 그동안 탭도 멈춰 있었으므로 모든 시각을 gap 만큼 민다(깨자마자 '조용함' 으로 끝내지 않게).
    bye=False(화면을 볼 수 없는 동안): 탭 시각만 민다 — 그동안 창을 닫았으면(작별) 그대로 CLOSE_GRACE 뒤 끝난다."""
    with CLOSE_LOCK:
        for k in list(UI_CLOSE["tabs"]):
            UI_CLOSE["tabs"][k] += gap
        if bye and UI_CLOSE["bye"]:
            UI_CLOSE["bye"] += gap


def _mark_last_run_stopped(job_started, note, report_dir=None):
    r"""작업을 멈췄으면 report\last_run.json 에 '중단(창 닫힘)' 단계를 붙인다 → 붙였나.
    이 작업(run.py)이 쓴 기록일 때만 — 작업 시작 뒤에 고쳐졌고 아직 끝나지 않은(finished 없음) 것. 깨진 파일이면 두고,
    바꿔 쓰기는 임시 파일 → os.replace."""
    p = os.path.join(report_dir or REPORT, "last_run.json")
    try:
        if not job_started or os.path.getmtime(p) < job_started - 2:
            return False
        with open(p, encoding="utf-8-sig") as f:
            lr = json.load(f)
        if not isinstance(lr, dict) or lr.get("finished") or not lr.get("started"):
            return False
        st = [x for x in (lr.get("stages") or []) if isinstance(x, dict) and x.get("name") != STOP_STAGE]
        st.append({"name": STOP_STAGE, "ok": False, "sec": 0.0, "note": str(note or "")[:300]})
        lr["stages"] = st
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lr, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _write_ui_exit(why, busy, tabs=None, now=None, report_dir=None):
    r"""화면 서버가 스스로 끝난 까닭을 report\ui_exit.json 에 남긴다(콘솔은 곧 닫혀 그 줄이 사라진다).
    {product, t, why, why_ko, busy, tabs[{age_s, vis}]} — 탭 id·글은 없다. 실패는 삼킨다.
    사람이 화면 앞에 있었는지(키보드·마우스 입력·잠금 — _screen_away)는 남기지 않는다: 그 판단은 창 닫힘 판정에만 쓰고 버린다."""
    now = time.time() if now is None else now
    rows = []
    for v in (tabs or {}).values():
        t, vis = (v[0], v[1]) if isinstance(v, (tuple, list)) else (v, "visible")
        try:
            rows.append({"age_s": int(max(0.0, now - float(t or 0.0))), "vis": str(vis)[:8]})
        except (TypeError, ValueError):
            continue
    rec = {"product": lmname.PRODUCT, "t": time.strftime("%Y-%m-%d"), "why": str(why), "why_ko": _close_why_ko(why, tabs),
           "busy": bool(busy), "tabs": rows[:16]}
    try:
        p = os.path.join(report_dir or REPORT, "ui_exit.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except OSError:
        pass
    return rec


def prev_ui_exit(report_dir=None, mark=True):
    r"""지난번 화면이 스스로 끝났으면(report\ui_exit.json — _write_ui_exit) 그 까닭·시각 한 줄 → 문자열(없으면 "").
    다시 켤 때 진행 로그·콘솔에 한 번 남긴다. 한 번 알린 기록에는 seen 을 붙여 다음 시작부터는 말하지 않는다."""
    p = os.path.join(report_dir or REPORT, "ui_exit.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(rec, dict) or rec.get("seen"):
        return ""
    why = str(rec.get("why_ko") or rec.get("why") or "까닭 모름")[:120]
    t = str(rec.get("t") or "")[:10]
    line = ("[ui] 지난번에는 화면이 스스로 끝났습니다 — 까닭: " + why + (f" ({t})" if t else "")
            + (" · 그때 돌던 작업도 멈췄습니다" if rec.get("busy") else ""))
    if mark:
        try:
            rec["seen"] = time.strftime("%Y-%m-%d")
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
        except OSError:
            pass
    return line


def ui_close_exit(server, why, out=None, tabs=None, now=None):
    """판정이 'exit' — 콘솔에 한 줄을 남기고, 도는 작업을 [중지]와 같은 길로 멈추고(Job 째), 전용 Edge 를 닫고, 서버를 끝낸다.
    조직장 팀 서버(teamserver.py)는 Job 밖이라 그대로 산다. 까닭을 멈춘 작업의 last_run 단계 글과 report\\ui_exit.json 에 남긴다."""
    say = out or (lambda s: print(s, flush=True))
    with LOCK:
        busy = bool(JOB["running"])
        had_pid = bool(JOB.get("pid"))
        started = float(JOB.get("started") or 0.0)
        was_run = str(JOB.get("step") or "") == RUN_STEP
    why_ko = _close_why_ko(why, tabs)
    line = (CLOSE_LINE_BUSY if busy else CLOSE_LINE_IDLE) + f" ({why_ko})"
    try:
        say(line)
    except Exception:  # noqa: BLE001 - 콘솔이 이미 없어도 정리는 한다
        pass
    log(line[len("[ui] "):])
    _write_ui_exit(why, busy, tabs, now)
    for fn in (kill_job, proc.kill_all, lambda: close_edge("ui_close", budget=UI_SWEEP_SEC)):
        try:
            fn()
        except Exception:  # noqa: BLE001 - 정리 하나가 실패해도 종료는 한다
            pass
    if busy and had_pid and was_run:
        drop_raw_now(check=False)            # 멈춘 [분석 실행]이 남긴 원자료(COM)를 지운다(retention.drop_raw)
    if busy and had_pid:
        _mark_last_run_stopped(started, f"화면 창이 닫혀({why_ko}) 실행 중이던 작업을 멈췄습니다 — 지금까지의 결과는 "
                                        "report\\에 남아 있습니다")
    if server is not None:
        threading.Thread(target=server.shutdown, daemon=True).start()


def close_watch(server, c=None, every=CLOSE_EVERY, stop=None):
    """판정 루프(main 이 데몬 스레드로 띄운다) — every 초마다 판정, 'exit' 면 ui_close_exit 후 끝난다. stop: 시험용 Event."""
    c = _close_cfg() if c is None else c
    prev = time.time()
    while not (stop is not None and stop.is_set()):
        time.sleep(every)
        now = time.time()
        gap = now - prev
        if gap > every + CLOSE_RESUME_GAP:
            _close_shift(gap - every)
        elif c.get("away") and _screen_away():
            _close_shift(gap, bye=False)        # 화면을 볼 수 없는 동안의 조용함은 세지 않는다
        prev = now
        tabs, bye, armed = _close_snapshot()
        verdict, why = ui_close_decision(now, tabs, bye, armed, c, busy=_ui_busy(), hold=_critical_busy())
        if verdict == "exit":
            ui_close_exit(server, why, tabs=tabs, now=now)
            return why
    return None


def awake_watch(stop=None, every=15.0, conf=None):
    """화면에서 띄운 작업이 도는 동안 PC 가 절전(잠자기)에 들어가지 않게 한다(proc.keep_awake — 이 스레드 기준 · 화면 꺼짐·
    화면 보호기·잠금은 그대로). 작업이 끝나면 놓는다. config.keepAwakeDuringRun=false 면 걸지 않는다. stop·conf: 시험용."""
    held = False
    while True:
        with LOCK:
            busy = bool(JOB["running"])
        c = conf if conf is not None else cfg()
        want = busy and _cfg_bool((c or {}).get("keepAwakeDuringRun"), True)
        if want != held:
            proc.keep_awake(want)
            held = want
        if stop is not None and stop.wait(every):
            break
        if stop is None:
            time.sleep(every)
    if held:
        proc.keep_awake(False)
    return held


def console_close_cleanup(ev=None, budget=EDGE_FAST_SEC):
    """콘솔 창(AgentFinder32-UI.bat)을 닫을 때(core\\proc.on_console_close) — 윈도가 주는 몇 초 안에 끝나는 것만 한다.
    Job 을 끝내고, Job 밖에 남는 전용 Edge 를 채팅 정리 없이(tidy=False) 닫는다 — budget 초까지만 기다린다. 예외를 내지 않는다."""
    try:
        with LOCK:
            busy = bool(JOB["running"])
            had_pid = bool(JOB.get("pid"))
            started = float(JOB.get("started") or 0.0)
            was_run = str(JOB.get("step") or "") == RUN_STEP
        for fn in (kill_job, proc.kill_all):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        if busy and had_pid and was_run:
            drop_raw_now(check=False)        # 멈춘 [분석 실행]이 남긴 원자료(COM) — 파일 몇 개라 몇 초 안에 끝난다
        if busy and had_pid:
            _mark_last_run_stopped(started, "콘솔 창이 닫혀 실행 중이던 작업을 멈췄습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
        SESSION_FILE_ON[0] = False
        remove_session_file()                # 시작 열쇠 파일 — 이 서버는 곧 끝난다
        proc.run_within(lambda: close_edge("console_close", tidy=False), budget)
    except BaseException:  # noqa: BLE001 - 처리기는 예외를 내지 않는다(윈도 스레드 위에서 돈다)
        pass


def agentic_view(a):
    """agentic_<tag>.json → 화면(Agentic AI 탭)에 보낼 꼴 — 후보만(agentic.needs_only). 읽지 못하면 매칭·오할당 키만 직접 지운다."""
    try:
        import agentic
        return agentic.needs_only(a)
    except Exception:  # noqa: BLE001 - 모듈 하나 때문에 탭이 죽지 않게
        return {k: v for k, v in (a or {}).items() if k not in ("match", "misassigned", "mm_recalc", "axes")}


def log(msg):
    with LOCK:
        JOB["log"].append(time.strftime("[%H:%M:%S] ") + msg)
        del JOB["log"][:-400]


def cfg_and_warnings():
    r"""실효 설정과 경고(core\afcfg.load_effective — D22 하한 적용). 읽지 못하면 기본값."""
    try:
        c, w = afcfg.load_effective(ROOT)
        return (c if isinstance(c, dict) else {}), list(w or [])
    except Exception:  # noqa: BLE001 - 설정 한 파일 때문에 화면 전체가 죽지 않게
        c, w = afcfg.effective({})
        return c, list(w or [])


def cfg():
    """실효 설정(afcfg.effective — 하한을 적용한 값)."""
    return cfg_and_warnings()[0]


def add_notice(kind, text):
    """화면에 한 번만 알릴 글을 쌓는다(/api/status 가 한 번 싣고 비운다)."""
    with NOTICE_LOCK:
        NOTICES.append({"kind": str(kind), "text": str(text)[:400]})
        del NOTICES[:-8]


def take_notices():
    with NOTICE_LOCK:
        out = list(NOTICES)
        NOTICES.clear()
    return out


def issue_nonce(purpose, extra=None, now=None):
    """일회용 표(공유·모두 지우기 POST 용) — 용도에 묶이고 NONCE_TTL 초 뒤 무효. 덧붙인 값(extra)은 서버에만 남는다."""
    t = time.time() if now is None else now
    n = secrets.token_urlsafe(18)
    with NONCE_LOCK:
        for k in [k for k, v in NONCES.items() if v[1] < t]:
            NONCES.pop(k, None)
        while len(NONCES) >= NONCE_MAX:
            NONCES.pop(min(NONCES, key=lambda k: NONCES[k][1]), None)
        NONCES[n] = (str(purpose), t + NONCE_TTL, extra)
    return n


def take_nonce(n, purposes, now=None):
    """표를 쓴다(한 번만 — 맞든 틀리든 지운다) → (맞나, 덧붙인 값). purposes = 받는 용도들."""
    t = time.time() if now is None else now
    if not isinstance(n, str) or not n:
        return False, None
    with NONCE_LOCK:
        v = NONCES.pop(n, None)
    if not v or v[1] < t or v[0] not in tuple(purposes):
        return False, None
    return True, v[2]


# ── 화면 세션(시작 열쇠 → 쿠키) ───────────────────────────────────────────────────────────────
def launch_url(port, key=None):
    """bat 이 여는 주소 — http://127.0.0.1:<port>/?k=<시작 열쇠>. 이 주소로 들어온 브라우저만 세션 쿠키를 받는다."""
    return f"http://127.0.0.1:{int(port)}/?k={key or LAUNCH_KEY}"


def session_path(data_dir=None):
    r"""data\ui_session.json — 두 번째 bat 실행이 열린 화면으로 잇는 시작 열쇠 파일."""
    return os.path.join(data_dir or DATA, SESSION_FILE)


def write_session_file(port, data_dir=None):
    r"""data\ui_session.json = {product, port, pid, key(시작 열쇠), date(날짜만)} → 경로 | ""(못 씀).
    설치 폴더의 권한 정리(install.protect_root — 다른 계정은 읽지 못함) 안에 둔다. 서버가 끝나면 remove_session_file 이 지운다."""
    p = session_path(data_dir)
    rec = {"product": lmname.PRODUCT, "port": int(port), "pid": os.getpid(), "key": LAUNCH_KEY,
           "date": time.strftime("%Y-%m-%d")}
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, p)
        return p
    except OSError:
        return ""


def read_session_file(data_dir=None):
    r"""data\ui_session.json → {port, pid, key, date} | None(없음·깨짐·AgentFinder32 화면 포트가 아님)."""
    d = _read_json(session_path(data_dir))
    if not d or d.get("product") != lmname.PRODUCT:
        return None
    port, key = _int(d.get("port")), str(d.get("key") or "")
    if port not in lmname.UI_PORTS or not KEY_RX.fullmatch(key):
        return None
    return {"port": port, "pid": _int(d.get("pid"), 0), "key": key, "date": str(d.get("date") or "")[:10]}


def remove_session_file(data_dir=None):
    r"""서버가 끝날 때 — data\ui_session.json 이 이 프로세스의 것(같은 시작 열쇠)일 때만 지운다 → 지웠나."""
    p = session_path(data_dir)
    d = _read_json(p)
    if not d or str(d.get("key") or "") != LAUNCH_KEY:
        return False
    try:
        os.remove(p)
        return True
    except OSError:
        return False


def probe_ui(port, key, timeout=2.0):
    """127.0.0.1:<port> 가 그 시작 열쇠를 아는 AgentFinder32 화면인가 — GET /?k=<열쇠> 에 세션 쿠키(Set-Cookie af32s=)로 답하면 참.
    127.0.0.1 밖으로는 붙지 않는다. 열쇠를 모르는 서버(다른 판·다른 프로그램)는 거짓."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            s.sendall((f"GET /?k={key} HTTP/1.1\r\nHost: 127.0.0.1:{int(port)}\r\nConnection: close\r\n"
                       "Content-Length: 0\r\n\r\n").encode("ascii"))
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 16384:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except (OSError, ValueError, UnicodeError):
        return False
    lines = buf.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace").split("\r\n")
    parts = lines[0].split() if lines else []
    if len(parts) < 2 or parts[1] != "200":
        return False
    return any(ln.lower().startswith("set-cookie:") and ln.split(":", 1)[1].strip().startswith(SESSION_COOKIE + "=")
               for ln in lines[1:])


def _ui_process_alive(pid):
    r"""그 pid 가 지금 살아 있는 화면 프로세스(파이썬이 ui\app.py 를 돌리는 것)인가. 열쇠 파일만 남고 프로세스는 끝난 뒤 그 포트를
    다른 프로그램이 잡았을 수 있다 — 살아 있는 화면 프로세스가 확인될 때만 그 포트에 시작 열쇠를 보낸다. 모르면 거짓."""
    try:
        alive, exe, cmd = proc.process_info(int(pid))
    except Exception:  # noqa: BLE001 - 모르면 새 화면을 띄운다
        return False
    if alive is not True:
        return False
    if exe and not os.path.basename(str(exe)).lower().startswith(("python", "py.exe")):
        return False
    return (not cmd) or "app.py" in str(cmd).lower()


def running_ui(data_dir=None):
    r"""이 설치 폴더의 화면이 이미 떠 있나 — data\ui_session.json 의 pid 가 살아 있는 화면 프로세스이고 그 포트가 그 시작 열쇠로
    답하면 {port, pid, key, date}, 아니면 None. 두 번째 bat 실행은 새 서버를 띄우지 않고 그 화면을 연다."""
    d = read_session_file(data_dir)
    if not d or d["key"] == LAUNCH_KEY or not _ui_process_alive(d["pid"]):
        return None
    return d if probe_ui(d["port"], d["key"]) else None


NO_SESSION_MSG = ("이 화면은 이 PC 에서 AgentFinder32-UI.bat 을 실행한 사용자만 엽니다 — AgentFinder32-UI.bat 을 다시 실행하면 "
                  "열린 화면으로 이어집니다")
NO_SESSION_HINT = "다시 실행해도 이 글이 보이면 브라우저가 127.0.0.1 의 쿠키를 막고 있는지 확인하세요"
PAGE_SHELL = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{t}</title>{head}</head>"
              "<body style=\"font-family:'Malgun Gothic',sans-serif;background:#f2f4f7;padding:40px\">"
              "<div style='max-width:760px;margin:0 auto;background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:22px'>"
              "<h2 style='font-size:17px'>{t}</h2>{body}</div></body></html>")


def no_session_page():
    """세션 쿠키 없이 화면(/·/guide)을 열었을 때 — 까닭만(화면 열쇠·자료 없음)."""
    body = ("<p style='font-size:13.5px;line-height:1.8;margin-top:10px'>" + html.escape(NO_SESSION_MSG) + "</p>"
            "<p style='font-size:12px;color:#8b929b;margin-top:10px'>" + html.escape(NO_SESSION_HINT) + "</p>")
    return PAGE_SHELL.format(t=html.escape(lmname.DISPLAY_TITLE), head="", body=body).encode("utf-8")


def launch_page():
    """GET /?k=<시작 열쇠> 의 답 — 세션 쿠키와 함께 보내는 작은 화면. 스스로 / 로 옮겨 간다(주소창·뒤로 가기에 시작 열쇠가 남지
    않게 location.replace · 스크립트가 꺼져 있으면 meta refresh). 화면 열쇠·자료는 없다."""
    head = "<meta http-equiv='refresh' content='0;url=/'>"
    body = ("<p style='font-size:13.5px;line-height:1.8;margin-top:10px'>화면을 여는 중입니다 — 열리지 않으면 "
            "<a href='/'>여기</a>를 누르세요.</p><script>location.replace('/');</script>")
    return PAGE_SHELL.format(t=html.escape(lmname.DISPLAY_TITLE), head=head, body=body).encode("utf-8")


def _rows(path):
    """결과 CSV 를 관대하게 읽는다 — 한 파일 때문에 화면 전체가 죽지 않게(UnicodeDecodeError 는 ValueError 계열)."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError, csv.Error):
        return []


def _read_json(path):
    """JSON 파일 → dict | None(없거나 깨졌거나 dict 가 아니면)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def _mtime(p):
    """다른 작업과 경합해도 죽지 않는 mtime — 파일이 사라졌으면 0"""
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _has_collected():
    r"""data\outlook\ 에 수집물이 있는가 — '수집은 했는데 분석을 안 했다' 를 가리기 위한 것."""
    try:
        d = os.path.join(DATA, "outlook")
        return any(n.endswith(".csv") and os.path.getsize(os.path.join(d, n)) > 200 for n in os.listdir(d))
    except OSError:
        return False


def _int(v, dflt=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return dflt


def _clean_text(s, n=60):
    """사람이 적은 짧은 글 — 제어 문자를 빼고 공백을 접어 n 자까지."""
    s = "".join(ch for ch in str(s or "") if ch >= " " and ch != "\x7f")
    return " ".join(s.split())[:n]


def _stage_note(stage):
    """최근 실행(last_run.json)에서 해당 단계의 결과 한 줄 - 탭이 비어 있을 때 이유를 말한다."""
    lr = _read_json(os.path.join(REPORT, "last_run.json"))
    if not isinstance(lr, dict):
        return ""
    st = {x.get("name"): x for x in (lr.get("stages") or []) if isinstance(x, dict)}
    s = st.get(stage)
    if not s:
        if st.get("AI 판정") is None and lr.get("started"):
            return "최근 실행은 AI 판정 단계에 도달하지 못했습니다"
        return "최근 실행에 이 단계 기록이 없습니다 (AI 분석을 끄고 실행했을 수 있음)"
    if s.get("ok"):
        return f"최근 실행에서 정상 완료 ({lr.get('finished') or lr.get('started') or ''})"
    return f"최근 실행에서 실패: {s.get('note') or '사유 미기록'}"


def _stage_kind(stage, tag=None):
    r"""그 단계가 왜 결과를 남기지 못했나 — 화면이 '다음에 무엇을 하라' 를 고를 수 있게 갈래를 준다.
    stalled(정체로 중단) · budget(시간 예산) · skipped(앞 단계 실패로 건너뜀) · failed(왕복 실패) · throttle(Copilot 사용량 제한) ·
    gate(개인정보 관문 — 조치 불필요) · none(기록 없음) · ok(정상 완료로 기록됨 — 결과 파일이 없으면 기간이 다른 것이다).
    상태 파일(stage_state)이 있으면 데이터로 답하고, 한국어 note 분류는 옛 기록용 폴백으로만 남는다."""
    _sid = {"AI 판정": "judge", "AI 정제": "refine", "Agentic 니즈 발굴": "agentic",
            "워크플로우 분석": "flow"}.get(stage)
    if _sid:
        try:
            from stage_state import read_latest, read_state
            st3 = (read_state(REPORT, tag, _sid) if tag else None) or read_latest(REPORT, _sid)
        except Exception:  # noqa: BLE001
            st3 = None
        if st3 is not None:
            _stv = str(st3.get("state") or "")
            _kind = str((st3.get("stop") or {}).get("kind") or "")
            if _stv == "done":
                return "ok"
            if _stv in ("partial", "failed"):
                return {"budget": "budget", "stall": "stalled", "login": "failed", "lock": "failed",
                        "fatal": "failed", "fail": "failed", "gain": "failed",
                        "throttle": "throttle", "gate": "gate"}.get(_kind, "failed")
    note = _stage_note(stage)
    if not note:
        return "none"
    if "정상 완료" in note:
        return "ok"
    if "기록이 없" in note or "도달하지 못" in note:
        return "none"
    if "중단" in note:
        return "stalled"
    if "시간 예산" in note:
        return "budget"
    if "건너뜀" in note or "건너뛰" in note:
        return "skipped"
    return "failed"


def _stage_why(tag, stage):
    r"""상태 파일(report\stage_state_<tag>_<stage>.json)이 남긴 중단 사유 → {stage_reason, stage_error, stage_stop_kind}
    (값이 있는 키만). 결과 파일이 없거나 흐름이 비었을 때 화면이 '왜' 를 먼저 말하게 한다."""
    out = {}
    if not tag:
        return out
    try:
        from stage_state import read_state
        st = read_state(REPORT, tag, stage) or {}
    except Exception:  # noqa: BLE001 - 상태 파일 판독 실패가 탭을 막지 않게
        st = {}
    stop = st.get("stop") if isinstance(st.get("stop"), dict) else {}
    err = st.get("error") if isinstance(st.get("error"), dict) else {}
    if str(stop.get("reason") or "").strip():
        out["stage_reason"] = str(stop["reason"]).strip()[:300]
    if str(stop.get("kind") or "").strip():
        out["stage_stop_kind"] = str(stop["kind"]).strip()
    e = str(err.get("error") or "").strip()
    if e:
        hn = str(err.get("hint") or "").strip()
        out["stage_error"] = (e + (" — " + hn if hn else ""))[:500]
    return out


REEXTRACTED = "판정 이후 재추출됨"


def _signals_judged(tag):
    r"""signals_<tag>.csv 가 판정 축인가 — 머리글에 judge/model 열이 있으면 True(judge·업무 빼기·재분류가 쓴 것),
    없으면 False(mine 이 다시 쓴 규칙 축), 파일이 없으면 None. mtime 이 아니라 내용으로 본다."""
    p = os.path.join(REPORT, f"signals_{tag}.csv")
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            head = f.readline()
    except OSError:
        return None
    cols = [c.strip().strip('"').strip() for c in head.strip().split(",")]
    return ("judge" in cols) or ("model" in cols)


def _reextracted(tag):
    """판정 뒤 업무 분류가 다시 추출됐는가(V-01) — signals 가 규칙 축(judge 열 없음)이면 True."""
    return _signals_judged(tag) is False


def _judged_info(tag):
    r"""(판정 반영 여부, 판정 건수, 대상 건수, 판정 기록 요약) — report\ai_judgments_<tag>.json 기준.
    judge.py 가 성공 경로 끝에서 쓰는 ai_judgments 의 judged(건수) > 0 이 기준이다. 파일이 없거나 깨졌거나 0 건이면 False —
    그 화면의 과제·세부업무는 규칙이 뽑은 임시 이름이다. 네 번째 값은 파일에 있는 실패·부분·중단·재사용 키만 담은 dict.
    판정 뒤에 업무 분류가 다시 추출됐으면 judged=False 에 reextracted/reason 을 싣는다(V-01)."""
    if not tag:
        return False, None, None, {}
    aj = os.path.join(REPORT, f"ai_judgments_{tag}.json")
    if not os.path.exists(aj) and os.path.exists(aj + ".stale"):
        return False, None, None, {"reextracted": True, "reason": REEXTRACTED}
    try:
        with open(aj, encoding="utf-8-sig") as f:
            j = json.load(f)
        n, total = int(j.get("judged") or 0), int(j.get("total") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return False, None, None, {}
    issues = {}
    for k in ("failed_rows", "partial_chunks", "repaired", "omitted_rows",
              "cache_reused", "group_rows", "reps", "lowinfo_rows", "unseen_rows", "rule_rows", "cooldowns"):
        if k in j:
            try:
                issues[k] = int(j.get(k) or 0)
            except (TypeError, ValueError):
                pass
    if "aborted" in j:
        issues["aborted"] = bool(j.get("aborted"))
    for k in ("abort_kind", "abort_reason", "model_fallback"):
        if isinstance(j.get(k), str):
            issues[k] = j[k].strip()[:200]
    fr = j.get("filled_rows")
    if isinstance(fr, dict):
        by = {}
        for kk, vv in fr.items():
            try:
                by[str(kk)] = int(vv or 0)
            except (TypeError, ValueError):
                pass
        issues["filled_rows"] = sum(by.values())
        issues["filled_by"] = by
    elif fr is not None:
        try:
            issues["filled_rows"] = int(fr or 0)
        except (TypeError, ValueError):
            pass
    if _reextracted(tag):
        issues.update(reextracted=True, reason=REEXTRACTED)
        return False, n, total, issues
    return n > 0, n, total, issues


STUB_MARK = "AF32_COPILOT_STUB"


def _stub_note(lastrun):
    """최근 실행이 스텁(AF32_COPILOT_STUB) 응답으로 판정했으면 그 단계의 note(아니면 ""). 화면 상단 배너로 드러낸다(시험 전용)."""
    if not isinstance(lastrun, dict):
        return ""
    for s in (lastrun.get("stages") or []):
        if isinstance(s, dict) and STUB_MARK in str(s.get("note") or ""):
            return str(s.get("note") or "")[:200]
    return ""


# ── 기간(tag) 고르기 — report\run_meta_<tag>.json 에 product AgentFinder32 가 있는 기간만 쓴다(D20) ─────────────────────
TAG_FILE_RE = re.compile(r"^run_meta_(\d{8}-\d{8})\.json$")
_META_OK = {}          # 경로 → (mtime, product 맞나) — /api/status 가 1초마다 불러도 같은 파일을 다시 읽지 않게


def _meta_ok(p):
    mt = _mtime(p)
    hit = _META_OK.get(p)
    if hit and hit[0] == mt:
        return hit[1]
    o = _read_json(p)
    ok = bool(o) and o.get("product") == lmname.PRODUCT
    _META_OK[p] = (mt, ok)
    if len(_META_OK) > 256:
        _META_OK.clear()
    return ok


def af32_tags(report_dir=None):
    r"""{tag: run_meta mtime} — report\run_meta_<tag>.json 이 AgentFinder32 산출물인 기간만. 옛 판·다른 도구의 결과는 읽지 않는다."""
    out = {}
    for p in glob.glob(os.path.join(report_dir or REPORT, "run_meta_*.json")):
        m = TAG_FILE_RE.match(os.path.basename(p))
        if m and _meta_ok(p):
            out[m.group(1)] = _mtime(p)
    return out


def latest_tag(report_dir=None):
    """가장 최근 AgentFinder32 분석 기간 'YYYYMMDD-YYYYMMDD'(없으면 "")."""
    tags = af32_tags(report_dir)
    return max(tags, key=lambda t: (tags[t], t)) if tags else ""


def tag_dates(tag):
    """'YYYYMMDD-YYYYMMDD' → ('YYYY-MM-DD', 'YYYY-MM-DD') | ("", "")."""
    t = str(tag or "")
    if len(t) == 17 and t[8] == "-" and t[:8].isdigit() and t[9:].isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}", f"{t[9:13]}-{t[13:15]}-{t[15:]}"
    return "", ""


def run_meta(tag):
    """report\\run_meta_<tag>.json(AgentFinder32 것만) → dict | {}."""
    if not tag:
        return {}
    o = _read_json(os.path.join(REPORT, f"run_meta_{tag}.json"))
    return o if (o and o.get("product") == lmname.PRODUCT) else {}


def latest_signals():
    r"""지금 화면이 보는 기간의 report\signals_<tag>.csv — 없으면 ""."""
    tag = latest_tag()
    p = os.path.join(REPORT, f"signals_{tag}.csv") if tag else ""
    return p if p and os.path.exists(p) else ""


def _other_tag(prefix, tag):
    r"""그 종류(agentic_·workflow_)의 결과가 다른 AgentFinder32 기간에만 있으면 그 기간(가장 최근) — 없으면 ""."""
    tags = af32_tags()
    cand = [t for t in tags if t != tag and os.path.exists(os.path.join(REPORT, f"{prefix}{t}.json"))]
    return max(cand, key=lambda t: (tags[t], t)) if cand else ""


def _age(ts):
    if not ts:
        return "없음"
    d = time.time() - ts
    return f"{d/60:.0f}분 전" if d < 5400 else (f"{d/3600:.0f}시간 전" if d < 172800 else f"{d/86400:.0f}일 전")


def _cfg_bool(v, dflt=True):
    if isinstance(v, bool):
        return v
    if v is None:
        return dflt
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _fresh_refined(plain, ref):
    """정제본을 써도 되는가 — core/details._fresh_refined 와 같은 규칙(정제본 mtime ≥ 원본 mtime)."""
    if not os.path.exists(ref):
        return False
    try:
        return (not os.path.exists(plain)) or os.path.getmtime(ref) >= os.path.getmtime(plain)
    except OSError:
        return True


def result_file(tag=None):
    r"""화면에 띄울 결과 행 파일(report\work_rows_<tag>[_refined].csv) — 지금 기간의 것만. 정제본은 원본보다 새것일 때만
    (core\details.rows_path 와 같은 mtime 규칙 — V-01). 없으면 ""."""
    tag = latest_tag() if tag is None else tag
    if not tag:
        return ""
    base = os.path.join(REPORT, f"work_rows_{tag}.csv")
    ref = os.path.join(REPORT, f"work_rows_{tag}_refined.csv")
    if _fresh_refined(base, ref):
        return ref
    return base if os.path.exists(base) else ""


ROW_HIDE = ("share", "mm", "제품", "이름", "활동일수", "evidence")   # 화면에 보내지 않는 열(share = 안쪽 정렬용 상대 무게)


def result_rows(tag=None):
    """(파일 이름, 행 목록) — 근거건수 많은 순. 근거건수는 정수로 확정한다(비숫자 값 하나로 정렬이 죽지 않게)."""
    p = result_file(tag)
    rows = _rows(p) if p else []
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k and k not in ROW_HIDE}
        r["근거건수"] = _int(str(r.get("근거건수") or "0").strip(), 0) or 0
        out.append(r)
    out.sort(key=lambda r: -r["근거건수"])
    return (os.path.basename(p) if p else ""), out


def _l1_tools():
    """(snap1, l1_meta_payload) — core\\details 의 상위(Level 1) 단일원. 못 읽으면 그대로 두는 함수."""
    try:
        import details as _dl
        return _dl.snap1, _dl.l1_meta_payload
    except Exception:  # noqa: BLE001 - 상위 이름 정리는 덤 — 화면을 막지 않는다
        return (lambda s: ""), (lambda: {})


def taxonomy(tag=None):
    r"""업무 분류 탭(GET /api/review?g=all) — 상위(Level 1) → 과제(Level 2) → 세부업무(Level 3) 와 근거건수, 업무 유형별 근거건수,
    공통 업무, 과제 체계(entities). 시간·사람·원문 근거·기간 묶음은 싣지 않는다."""
    tag = latest_tag() if tag is None else tag
    fn, rows = result_rows(tag)
    snap1, meta_fn = _l1_tools()
    l1meta = meta_fn() or {}
    groups = {}
    for r in rows:
        l1 = snap1(r.get("Level 1")) or str(r.get("Level 1") or "").strip() or "미분류"
        l2 = str(r.get("Level 2") or "").strip() or "공통"
        g = groups.setdefault(l1, {"name": l1, "count": 0, "tasks": {}})
        t = g["tasks"].setdefault(l2, {"name": l2, "count": 0, "details": []})
        n = r["근거건수"]
        g["count"] += n
        t["count"] += n
        t["details"].append({"name": str(r.get("Level 3") or "").strip(), "count": n,
                             "worktype": str(r.get("유형") or "").strip(), "activity": str(r.get("활동") or "").strip(),
                             "desc": str(r.get("상세설명") or "").strip()[:300], "basis": str(r.get("근거") or "").strip()[:80],
                             "conf": str(r.get("확신도") or "").strip(), "ax": str(r.get("ax") or "").strip() in ("1", "true", "True"),
                             "field": str(r.get("field") or "").strip()})

    def _order(name):
        m = l1meta.get(name) or {}
        return (_int(m.get("order"), 99), name)
    levels = []
    for l1 in sorted(groups, key=_order):
        g = groups[l1]
        tasks = sorted(g["tasks"].values(), key=lambda t: -t["count"])
        for t in tasks:
            t["details"].sort(key=lambda d: -d["count"])
        levels.append({"name": l1, "count": g["count"], "color": (l1meta.get(l1) or {}).get("color") or "#8b929b",
                       "tasks": tasks})
    out = {"gran": "all", "tag": tag, "file": fn, "levels": levels, "rows": len(rows)}
    pv = _read_json(os.path.join(REPORT, f"pivots_{tag}.json")) if tag else None
    if pv:
        bw = pv.get("by_worktype") if isinstance(pv.get("by_worktype"), dict) else {}
        out["by_worktype"] = {str(k): _int(v, 0) for k, v in bw.items() if _int(v) is not None}
        out["common"] = [{"name": str(c.get("name") or ""), "worktype": str(c.get("worktype") or ""),
                          "count": _int(c.get("근거건수"), 0)}
                         for c in (pv.get("common") or []) if isinstance(c, dict) and c.get("name")][:20]
    en = _read_json(os.path.join(REPORT, f"entities_{tag}.json")) if tag else None
    if en:
        out["entities"] = {"models": [{"name": str(m.get("name") or ""), "l1": str(m.get("l1") or ""),
                                       "match": [str(x) for x in (m.get("match") or [])][:8], "obs": str(m.get("obs") or "")[:200]}
                                      for m in (en.get("models") or []) if isinstance(m, dict) and m.get("name")],
                           "discovered": [str(x) for x in (en.get("discovered") or [])],
                           "hints_used": [str(x) for x in (en.get("hints_used") or [])],
                           "fallback": bool(en.get("fallback")), "reused_from": str(en.get("reused_from") or "")}
    return out


# ── 수집 현황(원장) ──────────────────────────────────────────────────────────────────────
# 숫자는 한 원천(data\coverage_ledger.json)에서만 센다. '불가' 는 실측 전이라 '의심' 으로 적고, 이 PC 인지 모르면 PC 이름을 지어내지
# 않고 출처만 적는다. 메일·일정 세 축만 본다.
AXIS_KO = {"mail_in": "받은 메일", "mail_out": "보낸 메일", "cal": "일정"}
SRC_KO = {"com": "Outlook 앱", "owa": "Outlook 웹", "copilot": "M365 Copilot", "legacy": "예전 수집분"}


def _ledger_path(rt=None):
    r"""일자×축 원장 경로(core\coverage — data\coverage_ledger.json)"""
    return os.path.join(rt or DATA, "coverage_ledger.json")


def _ledger(rt=None):
    r"""원장 읽기(판·PC 검사 없이 — 화면은 있는 그대로 보여 준다). 모듈이 없거나 깨졌으면 None."""
    try:
        import coverage as _cv
        p = _ledger_path(rt)
        if not os.path.exists(p):
            return None
        return _cv.Ledger.load(p)
    except Exception:  # noqa: BLE001 - 카드 하나가 화면을 죽이지 않게
        return None


def _here_host(data_dir=None):
    r"""이 설치의 원장 표식 'i:' + install_id 앞 12자(run.open_ledger 와 같은 값) — data\install.json 을 읽기만 한다
    (없거나 깨졌으면 '' · 만들지 않는다). 레지스트리 등 PC 식별자는 읽지 않는다."""
    iid = str((_read_json(os.path.join(data_dir or DATA, install.INSTALL_FILE)) or {}).get("install_id") or "")
    return "i:" + iid[:12] if re.fullmatch(r"[0-9a-f]{32}", iid) else ""


def collect_status_payload(d0="", d1="", data_dir=None, report_dir=None, here_id=None):
    r"""수집 현황 카드 재료 — {"ledger": {...}|None, "stages": [...], "owa": {...}|None, "as_of": 로컬 시각}.
    ledger.axes[축] = {ok, zero_ok, partial, unobserved, na, verified, unverified, days, srcs:[출처 이름]} — 기간
    [d0, min(d1, 오늘)] 의 날 수(날짜 목록 없이 수만 — coverage.Ledger.summary·verified_counts).
    ledger.pc = '이 PC' | '' — 원장 host 가 이 설치의 표식(_here_host)과 같을 때만. stages = last_run.json 의 수집기 단계(rc 가 있는 것).
    owa = data\outlook\src\mail_source_owa.json 의 date_only/mail_rows."""
    from datetime import date
    data_dir = data_dir or DATA
    report_dir = report_dir or REPORT
    out = {"ledger": None, "stages": [], "owa": None, "as_of": time.strftime("%Y-%m-%d %H:%M")}
    lp = _ledger_path(data_dir)
    led = _ledger(data_dir)
    if led is not None:
        today = date.today().isoformat()
        days_all = sorted(led.days)
        a = str(d0 or (days_all[0] if days_all else today))[:10]
        b = min(str(d1 or today)[:10], today)
        try:
            summ = led.summary(a, b)
            vc = led.verified_counts(a, b)
        except Exception:  # noqa: BLE001 - 날짜가 이상하면 카드만 비운다
            summ, vc = {}, {}
        axes = {}
        for ax in AXIS_KO:
            c = summ.get(ax) or {}
            n = sum(c.values())
            ok, zo, pa, na = c.get("ok", 0), c.get("zero_ok", 0), c.get("partial", 0), c.get("na", 0)
            srcs = sorted({s for day in led.days if a <= day <= b
                           for s in ((led.days.get(day) or {}).get(ax) or {})})
            v = vc.get(ax) or {}
            axes[ax] = {"label": AXIS_KO[ax], "days": n, "ok": ok, "zero_ok": zo, "partial": pa, "na": na,
                        "unobserved": max(0, n - ok - zo - pa - na),
                        "verified": int(v.get("verified") or 0), "unverified": int(v.get("unverified") or 0),
                        "srcs": [SRC_KO.get(s, s) for s in srcs]}
        host = str((_read_json(lp) or {}).get("host") or "")
        me = _here_host(data_dir) if here_id is None else here_id
        last = {SRC_KO.get(k, k): {"rc": v.get("rc"), "reason": v.get("reason", ""), "at": v.get("at", "")}
                for k, v in (led.last or {}).items() if isinstance(v, dict)}
        out["ledger"] = {"period": [a, b], "axes": axes, "last": last,
                         "pc": "이 PC" if (host and me and host == me) else ""}
    lr = _read_json(os.path.join(report_dir, "last_run.json")) or {}
    for x in (lr.get("stages") or []):
        if isinstance(x, dict) and x.get("rc") is not None:
            cnt = x.get("counts") if isinstance(x.get("counts"), dict) else {}
            keep = {k: v for k, v in cnt.items() if isinstance(v, (int, float, str, bool)) and len(str(v)) <= 24}
            out["stages"].append({"name": str(x.get("name") or ""), "ok": bool(x.get("ok")), "rc": x.get("rc"),
                                  "reason": str(x.get("reason") or ""), "note": str(x.get("note") or "")[:160],
                                  "counts": dict(list(keep.items())[:8])})
    ms = _read_json(os.path.join(data_dir, "outlook", "src", "mail_source_owa.json"))
    if ms:
        mr, dn = _int(ms.get("mail_rows"), 0), _int(ms.get("date_only"), 0)
        out["owa"] = {"mail_rows": mr, "date_only": dn, "ratio": round(dn / mr, 3) if mr else 0.0}
    return out


def collect_summary_payload():
    r"""수집·제외 현황 탭(GET /api/collect_summary) — data\outlook\collect_summary.json(§5.3 — 이 PC 에만 · 공유하지 않음)과
    지금 기간 run_meta 의 기간·셈·제외 건수, 설정 경고. 내용(제목·주소)은 없다 — 건수뿐."""
    s = _read_json(os.path.join(DATA, "outlook", "collect_summary.json"))
    summary = None
    if s and s.get("product") == lmname.PRODUCT:
        summary = {k: s.get(k) for k in ("period", "clamped", "channels", "kept", "excluded", "internal_domains")}
    tag = latest_tag()
    rm = run_meta(tag)
    meta = {k: rm.get(k) for k in ("tag", "period", "clamped", "generated", "signals", "counted", "excluded",
                                   "config_warnings")} if rm else None
    c, warns = cfg_and_warnings()
    return {"ok": True, "summary": summary, "run_meta": meta, "tag": tag, "config_warnings": warns,
            "restricted": restricted_info(c)}


def restricted_info(c=None):
    r"""제한 고객 목록(config\restricted_customers.json — 운영 담당이 배포) 확인 값 — 이름은 싣지 않는다.
    → {"ok": True, "confirmed": 'YYYY-MM-DD'(목록을 확인한 날), "age_days", "sha8"(파일 sha256 앞 8자 — 배포본과 맞춰 보는 지문)}
      | {"ok": False, "reason"('missing'·'invalid'…), "msg"}(없거나 형식이 틀림 — 분석·공유를 하지 않는다).
    값은 privacy.Restricted.info()(확인 날짜·지문 — 개인 리포트의 분석 개요와 같은 값)에서 온다."""
    from datetime import date
    try:
        import privacy
        r = privacy.load_restricted(cfg() if c is None else c, ROOT)
        info = r.info() if callable(getattr(r, "info", None)) else {}
    except Exception as e:  # noqa: BLE001 - RestrictedListError(detail 'missing'·'invalid')와 그 밖의 읽기 실패
        return {"ok": False, "reason": str(getattr(e, "detail", "") or type(e).__name__),
                "msg": str(getattr(e, "message", "") or "제한 고객 목록을 읽지 못했습니다 — 분석·공유를 하지 않습니다")[:300]}
    conf = str(info.get("confirmed") or getattr(r, "confirmed", "") or "")[:10]
    try:
        age = (date.today() - date.fromisoformat(conf)).days
    except ValueError:
        age = None
    return {"ok": True, "confirmed": conf, "age_days": age,
            "sha8": str(info.get("sha8") or getattr(r, "sha256", "") or "")[:8]}


def reset_cursors_local(data_dir=None):
    r"""[커서 초기화] — run.py --reset-cursors 와 같은 일을 이 프로세스에서: COM 달별 완료 표·옛 표를 지우고 원장의 모든 축을
    not_attempted 로. 수집한 행(CSV)은 그대로. 원장의 판(ver)·PC(host)는 보존한다. → (지운 파일 목록, 원장 초기화 여부)"""
    data_dir = data_dir or DATA
    gone = []
    for rel in (("outlook", "src", "coverage_com.json"),):
        p = os.path.join(data_dir, *rel)
        try:
            os.remove(p)
            gone.append("\\".join(rel))
        except OSError:
            pass
    ok = False
    lp = _ledger_path(data_dir)
    if os.path.exists(lp):
        try:
            import coverage as _cv
            raw = _read_json(lp) or {}
            led = _cv.Ledger.load(lp, ver=str(raw.get("ver") or ""), host=str(raw.get("host") or ""))
            led.reset()
            ok = led.save()
        except Exception:  # noqa: BLE001 - 초기화 실패는 결과로 알린다
            ok = False
    return gone, ok


# ── 기간(D2) — 화면의 기간은 언제나 서버가 core\period 로 다시 맞춘다 ─────────────────────────────────────
def clamp_period(d0=None, d1=None, c=None):
    """화면이 보낸 기간 → period.clamp → ('YYYY-MM-DD', 'YYYY-MM-DD', info, 알림 글). 날짜 형식이 틀리면 ValueError(한국어)."""
    c = cfg() if c is None else c
    a, b, info = period.clamp(d0 or None, d1 or None, c)
    return a.isoformat(), b.isoformat(), info, period.notice_text(info, a, b, c)


def period_payload(q):
    """GET /api/period — ?months=1|3 이면 기본 기간, ?from=&to= 면 맞춘 기간과 알림 글."""
    c = cfg()
    mx = period.max_days(c)
    rule = f"어제까지, 최대 {mx}일을 분석합니다 — 오늘은 넣지 않습니다"
    f0, t0 = (q.get("from") or [""])[0], (q.get("to") or [""])[0]
    if f0 or t0:
        a, b, info, note = clamp_period(f0, t0, c)
        return {"ok": True, "from": a, "to": b, "tag": period.tag_of(a, b), "max_days": mx, "clamped": bool(info["clamped"]),
                "requested": info["requested"], "notice": note, "rule": rule}
    months = 1 if (q.get("months") or ["3"])[0] == "1" else 3
    a, b = period.default(c, months)
    return {"ok": True, "from": a.isoformat(), "to": b.isoformat(), "tag": period.tag_of(a, b), "months": months,
            "max_days": mx, "clamped": False, "notice": "", "rule": rule}


def web_read(d0, d1, timeout=1500):
    r"""[Outlook 웹 읽기] — run.py --web-only mail --from d0 --to d1 → 화면 응답 dict. Job 으로 감싸 [중지]·시간 초과 때 트리째
    끊는다. 마지막 줄들의 'AF32STATUS {…}' 는 사람용 요약에서 뺀다(수집기 계약 줄)."""
    tag = "Outlook 웹"
    cmd = [sys.executable, os.path.join(ROOT, "run.py"), "--from", d0, "--to", d1, "--web-only", "mail"]
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                             creationflags=NO_WIN)
    except OSError as e:
        return {"ok": False, "rc": -1, "error": f"실행 실패({type(e).__name__})", "period": [d0, d1]}
    job = proc.attach(p)
    with LOCK:
        JOB["pid"] = p.pid
    try:
        out, _ = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        proc.kill_tree(p.pid)
        try:
            p.communicate(timeout=10)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        proc.release(job, p.pid)
        log(f"[{tag}] {timeout // 60}분 안에 끝나지 않아 끊었습니다")
        return {"ok": False, "rc": -1, "error": f"{timeout // 60}분 내 끝나지 않음", "period": [d0, d1]}
    proc.release(job, p.pid)
    lines = [ln.rstrip() for ln in (out or b"").decode("utf-8", "replace").splitlines()
             if ln.strip() and not ln.lstrip().startswith("AF32STATUS ")]
    for ln in lines[-12:]:
        log(f"[{tag}] {ln[:200]}")
    tail = lines[-4:]
    why = {0: "", 2: "로그인 필요 — 전용 Edge 창에서 회사 계정으로 1회 로그인한 뒤 다시 누르세요",
           3: "모두 지우기가 끝나지 않아 읽지 않았습니다", 4: "시작 조건이 맞지 않아 읽지 않았습니다 — 진행 로그를 보세요"}.get(
        rc, "일부 실패 — 진행 로그를 보세요")
    return {"ok": rc == 0, "rc": rc, "period": [d0, d1], "login": rc == 2, "error": why,
            "summary": " / ".join(t.strip() for t in tail)[:600]}


RUN_RC_KO = {0: "=== 완료 ===",
             2: "=== 일부만 끝났습니다(로그인 필요 또는 일부 실패) — 위 로그를 확인하세요 ===",
             3: "=== 모두 지우기가 끝나지 않아 분석하지 않았습니다 — 위 로그를 확인하세요 ===",
             4: "=== 시작 조건이 맞지 않아 멈췄습니다 — 위 안내(제한 고객 목록·사내 메일 도메인·설치 위치·자료의 주인)를 확인하세요 ==="}


def run_job(d0, d1, ai, skip, note="", req=None):
    """[분석 실행] — run.py --from --to [--ai] [--skip-collect] 를 Job 으로 감싸 돌리고 진행률을 JOB 에 흘린다.
    기간은 부르는 쪽이 이미 period.clamp 로 맞춰 보였다(d0·d1). run.py 에는 화면이 받은 기간(req — 비었으면 d0·d1)을 그대로
    넘긴다 — run.py 가 같은 규칙으로 다시 맞추면서 '줄였음'을 run_meta·last_run 에 남긴다(D2)."""
    try:
        r0, r1 = (str((req or (None, None))[0] or "").strip(), str((req or (None, None))[1] or "").strip())
        cmd = [sys.executable, os.path.join(ROOT, "run.py"), "--from", r0 or d0, "--to", r1 or d1]
        if ai:
            cmd.append("--ai")
        if skip:
            cmd.append("--skip-collect")
        if note:
            log(note)
        log(f"실행: {d0} ~ {d1}" + (" · AI 분석" if ai else "") + (" · 다시 읽지 않고 분석만" if skip else ""))
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        job = proc.attach(p)                 # Job(KILL_ON_JOB_CLOSE+BREAKAWAY_OK) — 전용 Edge 는 이탈해 산다
        with LOCK:
            JOB["pid"] = p.pid

        def _on(line):
            line = line.rstrip()
            if not line:
                return
            pg = parse_progress(line)
            if pg:
                ph, done, total = pg
                with LOCK:
                    if JOB["phase"] != ph:
                        JOB["phase_started"] = time.time()
                    JOB.update(phase=ph, done=done, total=total)
                return                           # 진행률 줄은 로그를 채우지 않는다
            log(line)
            if line.startswith("──"):
                with LOCK:
                    JOB["step"] = line.strip("─ ")
                    JOB.update(phase="", done=0, total=0)

        # 정체 검사 — 무출력이 한도를 넘으면 트리를 끊고 이유를 로그에 남긴다
        stopped = watch_child(p, _on, "분석 실행")
        p.wait()
        proc.release(job, p.pid)             # 남은 손자(고아)까지 정리 — 이미 닫혔으면 아무것도 안 한다
        if stopped:
            log(stopped)
            log("=== 중단(정체 감지) — [AI 연결 진단]으로 Copilot 창 상태를 확인한 뒤 다시 실행하세요 ===")
        else:
            log(RUN_RC_KO.get(p.returncode, f"=== 종료(코드 {p.returncode}) — 로그 확인 ==="))
    except Exception as e:
        log(f"오류: {e}")
    finally:
        with LOCK:
            JOB["running"] = False
            JOB["step"] = ""
            JOB["pid"] = 0
            JOB.update(phase="", done=0, total=0)


def _refine_map(tag):
    r"""report\refine_map_<tag>.json(refine 이 남긴 정제 행 → 원본 (Level 2, Level 3) 목록) → {"L2/L3": [(oL2, oL3), …]}.
    정제본이 없으면 빈 dict — 매핑은 그 정제본에만 유효하다(V-02)."""
    p = os.path.join(REPORT, f"refine_map_{tag}.json")
    if not os.path.exists(p) or not os.path.exists(os.path.join(REPORT, f"work_rows_{tag}_refined.csv")):
        return {}
    o = _read_json(p)
    mp = o.get("map") if isinstance(o, dict) else None
    out = {}
    for k, v in (mp.items() if isinstance(mp, dict) else []):
        pairs = [(str(it[0] or "").strip(), str(it[1] or "").strip())
                 for it in (v if isinstance(v, list) else []) if isinstance(it, (list, tuple)) and len(it) >= 2]
        if pairs:
            out[str(k).strip()] = pairs
    return out


def _name_axes():
    """느슨한 이름 비교 축(core/details.fold·ukey3)과 세부업무 병합 캐시."""
    from details import fold, load_detail_aliases, ukey3
    try:
        amap = load_detail_aliases()
    except Exception:  # noqa: BLE001 - 깨진 캐시가 업무 빼기를 막지 않게
        amap = {}
    return fold, ukey3, amap


def _cache_path(name):
    r"""사람마다의 캐시 파일 경로(data\cache\<name> — core\details.cache_path 단일원)."""
    import details
    return details.cache_path(name, root=ROOT)


def exclude_work(row_key):
    r"""[분석에서 빼기] — '과제/세부업무' 행의 근거 신호를 결과에서 빼고 업무 분류를 다시 센다(judge.write_outputs).
    뺀 이력은 data\cache\excluded_work.json 에 남아 다음 분석에도 적용된다(다음 판정이 다시 넣지 않게 하는 마지막 방어선).
    화면 행은 정제본 이름이라 signals 의 (model, detail) 와 다를 수 있다(V-02) — refine_map 으로 정제 행 → 원본 쌍을 풀고, 없으면
    fold/ukey3·세부업무 병합 캐시로 느슨하게 맞추며, 그래도 없으면 같은 과제의 후보 이름을 error 에 실어 안내한다."""
    sp = latest_signals()
    key = str(row_key or "").strip()
    if not sp or not key:
        return {"ok": False, "error": "no signals" if not sp else "bad row"}
    tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
    ep = _cache_path("excluded_work.json")          # 고치기 전에 먼저 — 경로를 못 정하면 아무것도 바꾸지 않는다
    try:
        with open(sp, encoding="utf-8-sig", errors="replace") as f:
            rd = csv.DictReader(f)
            cols = [c for c in (rd.fieldnames or []) if c]
            rows = list(rd)
    except (OSError, ValueError, csv.Error):
        return {"ok": False, "error": "signals 를 읽지 못했습니다"}

    def _pair(r):
        return ((r.get("model") or r.get("project") or "").strip(),
                (r.get("detail") or r.get("activity") or "").strip())
    targets = set(_refine_map(tag).get(key) or [])
    if "/" in key:
        md, dt = (x.strip() for x in key.split("/", 1))
        targets.add((md, dt))
    if not targets:
        return {"ok": False, "error": "bad row"}
    hit = [r for r in rows if _pair(r) in targets]
    how = "exact"
    if not hit:
        fold, ukey3, amap = _name_axes()

        def _axes(a, b, use_map):
            ks = {(fold(a), fold(b)), (fold(a), ukey3(b))}
            rep = amap.get((a, b)) if use_map else None
            if rep:
                ks |= {(fold(a), fold(rep)), (fold(a), ukey3(rep))}
            return ks
        # 1단계: 표기 변형만. 2단계: 그래도 없을 때만 세부업무 병합 캐시까지(같은 묶음의 다른 행까지 지우지 않게)
        for use_map in (False, True):
            want = set()
            for a, b in targets:
                want |= _axes(a, b, use_map)
            hit = [r for r in rows if _axes(*_pair(r), use_map) & want]
            if hit:
                break
        how = "loose"
    if not hit:
        fold = _name_axes()[0]
        mds = {fold(a) for a, _b in targets}
        cands = sorted({f"{a}/{b}" for a, b in {_pair(r) for r in rows} if fold(a) in mds})[:6]
        log(f"[빼기] '{key}' — 근거 신호에 맞는 행 없음" + (f" · 같은 과제 후보 {len(cands)}개" if cands else ""))
        return {"ok": False, "candidates": cands,
                "error": "행을 찾지 못함 — " + (f"같은 과제의 후보: {' · '.join(cands)}" if cands else
                                          "근거 신호에 같은 과제가 없습니다(이미 뺐거나 다시 분류돼 이름이 바뀜) — [분석 실행] 뒤 다시")}
    hit_ids = {id(r) for r in hit}
    keep = [r for r in rows if id(r) not in hit_ids]
    removed = len(hit)
    tmp = sp + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in keep:
            w.writerow({c: r.get(c, "") for c in cols})
    os.replace(tmp, sp)
    try:
        from judge import write_outputs
        write_outputs(keep, tag, cfg(), REPORT)
    except Exception as e:  # noqa: BLE001 - 다시 세기 실패는 까닭과 함께 돌려준다
        log(f"[빼기] 업무 분류 다시 세기 실패: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"다시 세지 못함({type(e).__name__}) — 근거는 뺐으니 [분석 실행]으로 다시 세세요"}
    for n in (f"work_rows_{tag}_refined.csv", f"refine_map_{tag}.json"):   # 정제본과 그 매핑은 함께 무효화
        rf = os.path.join(REPORT, n)
        if os.path.exists(rf):
            os.remove(rf)
    try:
        with open(ep, encoding="utf-8-sig") as f:
            hist = json.load(f)
        hist = hist if isinstance(hist, list) else []
    except (OSError, ValueError):
        hist = []
    hist.append({"row": key, "when": time.strftime("%Y-%m-%d"), "signals": removed, "matched": how,
                 "pairs": sorted(f"{a}/{b}" for a, b in {_pair(r) for r in hit})})
    os.makedirs(os.path.dirname(ep), exist_ok=True)
    with open(ep, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    log(f"[빼기] '{key}' — 근거 {removed}건을 분석에서 뺐습니다"
        + (f" (원본 {len(targets)}쌍 · {'정확' if how == 'exact' else '느슨'} 일치)" if len(targets) > 1 or how != "exact" else "")
        + " · 업무 분류를 다시 셌습니다")
    return {"ok": True, "removed": removed, "matched": how, "pairs": len(targets)}


# ── 화면에서 띄우는 Agentic AI 후보 발굴·워크플로우 재분석 ─────────────────────────────────
# [분석 실행]과 같은 방식으로 스레드에서 돌리며 [progress] 를 진행 바에 흘리고, 마지막 줄 JSON(ok/error/hint)을 MANUAL 에 남겨
# GET /api/agentic·/api/workflow 가 화면에 전한다.
TOOL_JOBS = {"agentic": ("agentic.py", "Agentic AI 후보 발굴"), "flow": ("flow.py", "워크플로우 분석")}
MANUAL = {}                       # kind → 마지막 화면 실행 결과 {ok,error,hint,at,sec,tag,...}


def _tag_args():
    """화면이 보고 있는 기간 → (tag, ['--from', d0, '--to', d1]) (없으면 ("", []))."""
    t = latest_tag()
    a, b = tag_dates(t)
    return (t, ["--from", a, "--to", b]) if a else (t, [])


# 정체 검사기 한 벌 — core/watch 임포트(복제 금지 · tools\check_l1.py 계약)
import proc  # noqa: E402  — 자식은 Job 에 넣고 끊을 때 Job 째(taskkill 을 띄우지 않는다 · P6)
import watch as _watch_mod  # noqa: E402
from watch import stage_limits as _core_stage_limits  # noqa: E402
from watch import watch_child as _core_watch_child  # noqa: E402

# 이 프로세스 안에서만 정체 검사기의 종료를 Job 으로 바꾼다(run.py 와 같은 방식) — 전용 Edge 는 Job 에서 이탈해 산다
_watch_mod.kill_tree = proc.kill_tree
kill_tree = proc.kill_tree  # 기존 호출부 이름 유지


def _stage_limits():
    return _core_stage_limits(cfg())


_WATCH_STATE_PATH = {"p": None}      # 다음 watch_child 가 볼 상태 파일 — tool_job 이 세팅


def watch_child(p, on_line, label, beat_sec=120):
    def _on(ln):                    # 화면의 "마지막 소식 N초 전" — 자식 출력 시각을 JOB 에 남긴다
        try:
            with LOCK:
                JOB["last_out"] = time.time()
        except Exception:  # noqa: BLE001
            pass
        on_line(ln)
    return _core_watch_child(p, _on, label, beat_sec=beat_sec, cfg_dict=cfg(),
                             state_path=_WATCH_STATE_PATH.get("p"))


def tool_job(kind, extra=()):
    """agentic.py / flow.py 를 스레드에서 끝까지 돌리고 결과를 MANUAL[kind] 에 남긴다(run_job 과 같은 프로토콜).
    기간을 명시한다 — 인자가 없으면 두 스크립트가 화면과 어긋난 기간에 쓸 수 있다."""
    script, step = TOOL_JOBS[kind]
    t0 = time.time()
    tag, targs = _tag_args()
    _WATCH_STATE_PATH["p"] = (os.path.join(REPORT, f"stage_state_{tag}_{kind}.json") if tag else None)
    res = {"ok": False, "error": "실행 실패", "hint": ""}
    run = chat_job_run()                 # 이 작업이 연 Copilot 채팅을 한 실행으로 묶는다(끝 한 줄 — job_chat_end)
    try:
        cmd = [sys.executable, os.path.join(ROOT, script)] + targs + list(extra)
        log(f"[{step}] 시작 — 기간 {tag or '(최신)'}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", AF32_CHAT_RUN=run),
                             creationflags=NO_WIN)
        job = proc.attach(p)
        with LOCK:
            JOB["pid"] = p.pid
        box = {"last": None, "tail": ""}

        def _on(line):
            line = line.rstrip()
            if not line:
                return
            pg = parse_progress(line)
            if pg:
                ph, done, total = pg
                with LOCK:
                    if JOB["phase"] != ph:
                        JOB["phase_started"] = time.time()
                    JOB.update(phase=ph, done=done, total=total)
                return
            if line.startswith("{") and line.rstrip().endswith("}"):
                try:
                    o = json.loads(line)
                    if isinstance(o, dict):
                        box["last"] = o
                        return
                except ValueError:
                    pass
            box["tail"] = line
            log(line)

        stopped = watch_child(p, _on, step)
        p.wait()
        proc.release(job, p.pid)
        last, tail = box["last"], box["tail"]
        if stopped:
            res = {"ok": False, "error": "중단(정체 감지)", "hint": stopped}
            log(stopped)
        elif last is None:
            res = {"ok": False, "error": "출력 해석 실패",
                   "hint": (tail[:200] if tail else f"종료 코드 {p.returncode}") + " — 진행 로그를 확인하세요"}
        else:
            res = last
            if p.returncode == 2:
                res["partial"] = True           # rc 규약: 2 = 부분(성공) — 다음 실행이 이어서
            elif p.returncode != 0 and res.get("ok"):
                res["ok"] = False
        log(f"=== {step} " + ("완료" if res.get("ok") else f"실패: {str(res.get('error') or '')[:80]}"
                                + (f" — {str(res.get('hint') or '')[:120]}" if res.get("hint") else "")) + " ===")
        cl = job_chat_end(run, step)
        if cl:
            res["chats_line"] = cl
    except Exception as e:  # noqa: BLE001 - 어떤 예외도 JOB 을 '실행 중'으로 남기면 안 된다
        res = {"ok": False, "error": f"실행 오류({type(e).__name__})", "hint": str(e)[:150]}
        log(f"오류: {e}")
    finally:
        res = dict(res, at=time.strftime("%Y-%m-%d %H:%M"), sec=round(time.time() - t0), kind=kind, tag=tag)
        with LOCK:
            MANUAL[kind] = res
            JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)


def make_report():
    r"""[내 리포트 만들기] — report_out.py --from --to --variant local(지금 기간) → {ok, files, tag} | {ok: False, error, hint}.
    개인 리포트는 이 PC 의 report\ 에만 남는다(보관기한 htmlDays). 공유는 [공유] 탭에서만 한다."""
    tag = latest_tag()
    a, b = tag_dates(tag)
    if not a:
        return {"ok": False, "error": "no result"}
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "report_out.py"), "--from", a, "--to", b,
                            "--variant", "local"], capture_output=True, timeout=300, cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
    except (subprocess.SubprocessError, OSError) as e:
        return {"ok": False, "error": "리포트 생성 실패", "hint": f"{type(e).__name__}"}
    txt = (p.stdout or b"").decode("utf-8", "replace").strip()
    res = None
    for ln in reversed(txt.splitlines()):
        if ln.strip().startswith("{"):
            try:
                res = json.loads(ln)
                break
            except ValueError:
                continue
    for ln in txt.splitlines():
        if ln and not ln.strip().startswith("{"):
            log("[리포트] " + ln[:200])
    if not isinstance(res, dict):
        err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return {"ok": False, "error": "리포트 생성 실패", "hint": (err[-1][:200] if err else f"종료 코드 {p.returncode}")}
    files = [x for x in (res.get("html"),) if x] or list(res.get("files") or [])
    out = {"ok": bool(res.get("ok")), "tag": res.get("tag") or tag,
           "files": [os.path.basename(str(x)) for x in files], "error": res.get("error") or "", "hint": res.get("hint") or ""}
    if out["ok"]:
        log(f"[리포트] {', '.join(out['files']) or '만들었습니다'} — 이 파일은 PC 밖으로 보내지 않습니다")
    return out


# ── 공유(D14 · spec §7) — teamup.py 를 자식으로 부르고 마지막 JSON 한 줄을 읽는다 ─────────────────────────────
SECRET_KEYS = ("token", "join", "key", "salt", "secret", "password")
# [보내기]가 teamup --share 를 기다리는 상한(초). teamup 이 정상으로 기다릴 수 있는 가장 긴 시간보다 길어야 한다 — 서버가 받은 뒤
# 영수증을 쓰기 전에 끊으면 그 사본은 영수증이 없어 [보낸 공유 모두 거두기]·[모두 지우기(서버 사본 포함)]로 지울 수 없다(R3). 설정 share.* 가 가장 클 때
# (teamup.wait_limits 의 상한 — pingTries 3 × pingTimeoutSec 10초 + 사이 쉼 2 × 1초 + 요청 3개(개인 리포트 · 앞서 보낸 익명 기여분
# 지우기 · 익명 기여분) × timeoutSec 90초 = 302초)에 파이썬 시작·공유본 다시 만들기 30초를 더한다. 화면은 teamup 모듈을 지우기에만 쓴다.
SHARE_WAIT_SEC = 3 * 10 + 2 * 1 + 3 * 90 + 30


def _scrub_secrets(o, depth=0):
    """화면으로 보내기 전에 영수증 토큰·참여 코드 같은 비밀 값을 뺀다(키 이름으로)."""
    if depth > 6:
        return None
    if isinstance(o, dict):
        return {k: _scrub_secrets(v, depth + 1) for k, v in o.items()
                if not any(s in str(k).lower() for s in SECRET_KEYS)}
    if isinstance(o, list):
        return [_scrub_secrets(v, depth + 1) for v in o[:200]]
    return o


def teamup_call(args, *, timeout=60, join=None):
    r"""python teamup.py <args> → 마지막 JSON 한 줄 dict({"ok","code","msg",...}). 참여 코드는 인자가 아니라 환경 변수 AF32_JOIN 으로만.
    실패해도 dict(code: timeout·spawn·no_json)를 돌려준다. 자식 출력의 다른 줄은 진행 로그에 남기지 않는다(주소·이름이 섞일 수 있다)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    env.pop("AF32_JOIN", None)
    if join:
        env["AF32_JOIN"] = str(join)
    try:
        p = subprocess.run([sys.executable, TEAMUP] + [str(a) for a in args], capture_output=True, timeout=timeout,
                           cwd=ROOT, env=env, creationflags=NO_WIN)
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "timeout", "msg": f"{int(timeout)}초 안에 끝나지 않았습니다 — 다시 보내지 않습니다"}
    except OSError as e:
        return {"ok": False, "code": "spawn", "msg": f"공유 프로그램을 실행하지 못했습니다({type(e).__name__})"}
    txt = (p.stdout or b"").decode("utf-8", "replace")
    for ln in reversed(txt.splitlines()):
        s = ln.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                o = json.loads(s)
            except ValueError:
                continue
            if isinstance(o, dict):
                o.setdefault("ok", p.returncode == 0)
                o.setdefault("code", "ok" if o["ok"] else "error")
                o["rc"] = p.returncode
                return o
    err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return {"ok": False, "code": "no_json", "rc": p.returncode,
            "msg": "공유 프로그램이 결과를 주지 못했습니다" + (f" — {err[-1][:160]}" if err else "")}


def _ta():
    r"""조직장 서버 주소 단일원(core\teamaddr — config\af32_team_server.json)."""
    import teamaddr
    return teamaddr


def addr_info():
    r"""조직장 서버 주소(core\teamaddr.Addr) → {host, port, scheme, url, has_join, join_hint, saved_at, warnings}.
    참여 코드 원문은 화면에 보내지 않는다(앞 4자만 — teamaddr.join_hint)."""
    try:
        ta = _ta()
        a = ta.load(ROOT)
        return {"host": a.host, "port": a.port if a.host else None, "scheme": a.scheme, "url": a.url,
                "has_join": bool(a.join), "join_hint": ta.join_hint(a.join), "saved_at": a.saved_at,
                "warnings": list(a.warnings), "default_port": ta.DEFAULT_PORT}
    except Exception as e:  # noqa: BLE001 - 주소 파일이 깨졌으면 비어 있는 것으로
        return {"host": "", "port": None, "scheme": "http", "url": "", "has_join": False, "join_hint": "", "saved_at": "",
                "warnings": [f"주소를 읽지 못했습니다({type(e).__name__})"], "default_port": lmname.TEAM_DEFAULT_PORT}


def addr_join():
    """저장한 참여 코드(teamup 에 환경 변수 AF32_JOIN 으로만 넘긴다) — 없으면 ""."""
    try:
        return str(_ta().load(ROOT).join or "")
    except Exception:  # noqa: BLE001
        return ""


def _receipts():
    r"""data\share_receipts.json 의 영수증 목록(dict 들) — 없으면 []."""
    try:
        with open(os.path.join(DATA, "share_receipts.json"), encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(o, dict):
        o = o.get("receipts") if isinstance(o.get("receipts"), list) else []
    return [x for x in o if isinstance(x, dict)] if isinstance(o, list) else []


def receipts_view():
    """영수증 요약(화면용 — 토큰 없이): [{server, org_label, part, sent, expires, unsure}].
    unsure = 서버가 받았는지 아직 모른다(영수증의 "pending" — 답을 받지 못한 보내기 · [보낸 공유 모두 거두기]로 지울 수 있다)."""
    out = []
    for r in _receipts():
        out.append({"server": str(r.get("server") or ""), "org_label": str(r.get("org_label") or ""),
                    "part": str(r.get("part") or ""), "sent": str(r.get("sent") or "")[:10],
                    "expires": str(r.get("expires") or "")[:10], "unsure": bool(r.get("pending"))})
    return out


def pending_view():
    """모두 지울 때 조직장 서버에서 아직 못 지운 공유(영수증에 "withdraw": true) — [{server, org_label, part, expires}].
    다음에 시작할 때마다 다시 지우고, 서버 보관기한이 지나면 서버가 지운다."""
    return [{"server": str(r.get("server") or ""), "org_label": str(r.get("org_label") or ""),
             "part": str(r.get("part") or ""), "expires": str(r.get("expires") or "")[:10]}
            for r in _receipts() if r.get("withdraw")]


CONTACT_NEUTRAL = "문의나 이의는 이 도구를 배포한 운영 담당에게 할 수 있습니다."


def contact_info(c=None):
    """문의·이의 창구(설정 privacy.contact {name, channel} — 운영 담당이 채운다) → {"name", "channel", "line"}.
    line 은 안내문 '내 권리' 절의 문의·이의 문장 그대로(consent.contact_line — 창구가 비었으면 '이 도구를 배포한 운영 담당').
    [내 데이터] 탭과 모두 지우기를 마치지 못한 화면이 보인다."""
    c = cfg() if c is None else c
    try:
        name, channel = consent.contact_info(c)
        line = consent.contact_line(c)
    except Exception:  # noqa: BLE001 - 설정이 깨졌어도 물어볼 곳은 보인다
        name, channel, line = "", "", CONTACT_NEUTRAL
    return {"name": str(name or ""), "channel": str(channel or ""), "line": str(line or CONTACT_NEUTRAL)}


def share_lines():
    """[공유] 탭·확인 창이 안내문과 같은 말로 보이는 문장(core\\consent 의 상수) — 공유 가리기가 지키는 것(mask)·남을 수 있는 것
    (check)·표시한 항목(flag)·익명 기여분이 조직장 PC 에 남는 꼴(team_file)."""
    return {"mask": consent.SHARE_MASK_LINE, "check": consent.SHARE_CHECK_LINE, "flag": consent.SHARE_FLAG_LINE,
            "team_file": consent.TEAM_FILE_LINE}


def purge_status_view():
    r"""마지막 자동 정리 기록(retention.py --purge — 매일 정리 작업·AgentFinder32.bat 시작이 data\purge_status.json 에 남긴다 ·
    retention.read_purge_status: AgentFinder32 표식이 있는 것만) → {date, deleted, errors(못 지운 수), withdrawal_left(모두 지운 뒤
    서버에서 아직 못 지운 공유 수 | None)} | None(기록 없음). 날짜와 건수만 싣는다(못 지운 경로는 싣지 않는다)."""
    try:
        d = retention.read_purge_status(ROOT)
    except Exception:  # noqa: BLE001 - 기록 하나가 탭을 막지 않게
        d = None
    if not isinstance(d, dict):
        return None
    errs, left = d.get("errors"), d.get("withdrawal_left")
    return {"date": str(d.get("date") or "")[:10], "deleted": _int(d.get("deleted"), 0) or 0,
            "errors": len(errs) if isinstance(errs, list) else (_int(errs, 0) or 0),
            "withdrawal_left": None if left is None else (_int(left, 0) or 0)}


# ── 연결 확인·보내기 확인 창(L5-11) ──────────────────────────────────────────────────────────────
# [공유] 탭은 열 때 조직장 서버에 붙지 않는다 — 저장한 주소와 영수증(이 PC 의 파일)만 보인다. 서버에 붙는 것은 [연결 확인]·[보내기…]
# (확인 창을 채울 새 hello)·거두기·모두 지우기뿐이다. 확인 창은 그 hello 가 말한 값만 보이고(이 PC 의 설정으로 채우지 않는다), 보인 값은
# 일회용 표(share_check)에 묶여 보내기 표(report\share\ticket_<nonce>.json)에 그대로 적힌다 — teamup 은 그 표를 새 hello 와 맞춘다.
def share_check():
    r"""[연결 확인]·[보내기…] — teamup --ping(조직장 서버 hello 한 번 · 보내지 않는다) → {"teamup", "server", "check_nonce"}.
    server = 확인 창에 보일 값 {server(주소), server_id, org_label, transport, serverPersonalDays, serverTeamDays,
    personalOverHttp, minGroupSize, minCellSize} — 조직·전송 방식·두 보관기한을 모두 확인했을 때만, 아니면 None(확인 창을 열지
    않는다). 그 값은 일회용 표(share_check)에만 묶어 둔다 — /api/share 가 보내기 표에 적는다."""
    res = _scrub_secrets(teamup_call(["--ping"], timeout=60))
    srv = None
    if res.get("ok") and res.get("reachable") is not False:
        url = str(res.get("address") or res.get("server") or "")
        tr = str(res.get("transport") or "")
        pd, td = _int(res.get("serverPersonalDays")), _int(res.get("serverTeamDays"))
        org = str(res.get("org_label") or "")
        if url and org.strip() and tr in ("http", "https") and pd and pd > 0 and td and td > 0:
            srv = {"server": url, "server_id": str(res.get("server_id") or ""), "org_label": org, "transport": tr,
                   "serverPersonalDays": pd, "serverTeamDays": td, "personalOverHttp": bool(res.get("personalOverHttp")),
                   "minGroupSize": _int(res.get("minGroupSize")), "minCellSize": _int(res.get("minCellSize"))}
    code = "ok" if srv else (str(res.get("code") or "") if not res.get("ok") else "unchecked")
    msg = "" if srv else (str(res.get("msg") or "")[:300] if not res.get("ok") else
                          "조직장 서버가 조직·전송 방식·서버 보관기한을 알려 주지 않았습니다")
    nonce = issue_nonce("share_check", {"server": srv, "code": code or "unchecked", "msg": msg})
    return {"teamup": res, "server": srv, "check_nonce": nonce, "check_code": code or "unchecked", "check_msg": msg}


TICKET_RX = re.compile(r"ticket_[0-9a-f]{32}\.json")


def write_ticket(extra, srv, include, parts):
    r"""보내기 표(일회용 · C9) — report\share\ticket_<32 hex>.json → 경로. teamup --share --ticket 이 읽자마자 지우고, 미리보기
    파일(preview_sha256)·고른 항목(ids)·갈래(parts)·새 hello(server·server_id·org_label·transport·server_days)와 하나라도 다르면
    보내지 않는다(30분이 지난 표도 — 파일 시각). 날짜만 적는다(D10). 참여 코드·토큰은 싣지 않는다.
    {product, kind:"share_ticket", created, preview_file, preview_sha256, tag, ids[항목 id], parts["personal"|"team"],
     server, server_id, org_label, transport, server_days{personal, team}}"""
    os.makedirs(SHARE_DIR, exist_ok=True)
    p = os.path.join(SHARE_DIR, f"ticket_{secrets.token_hex(16)}.json")
    rec = {"product": lmname.PRODUCT, "kind": "share_ticket", "created": time.strftime("%Y-%m-%d"),
           "preview_file": str(extra.get("preview_file") or ""),
           "preview_sha256": str(extra.get("sha256") or "").strip().lower(), "tag": str(extra.get("tag") or ""),
           "ids": [str(x) for x in include], "parts": list(parts),
           "server": srv.get("server"), "server_id": srv.get("server_id"), "org_label": srv.get("org_label"),
           "transport": srv.get("transport"),
           "server_days": {"personal": srv.get("serverPersonalDays"), "team": srv.get("serverTeamDays")}}
    with open(p, "x", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return p


def _drop_ticket(p):
    """보내기 표가 남았으면 지운다(teamup 이 쓰고 지웠어야 한다 — 실행하지 못했거나 끊겼을 때)."""
    try:
        if p and TICKET_RX.fullmatch(os.path.basename(p)) and _in_share_dir(p):
            os.remove(p)
    except OSError:
        pass


PART_KO = {"personal": "개인 리포트", "team": "익명 팀 집계"}
UNKNOWN_SENT = "보냈는지 확인하지 못했습니다 — [보낸 공유 모두 거두기]로 지울 수 있습니다"


def share_say(res, parts):
    r"""보내기 결과 한 줄(진행 로그·[공유] 탭) — 한쪽만 간 경우(개인 리포트만 · 익명 팀 집계만)는 그렇다고 말한다(L5-12).
    서버가 받았는지 모르는 갈래(teamup 결과의 "unsure": [갈래] · "unknown")는 '보냈는지 확인하지 못했습니다'로 — 그 영수증은
    남아 있어 [보낸 공유 모두 거두기]로 지울 수 있다. 지우고 새로 보내지 못한 앞선 익명 기여분(team_removed)도 말한다.
    다시 보내지 않는다는 말을 늘 붙인다."""
    tail = " (자동으로 다시 보내지 않습니다)"
    sent = [p for p in ("personal", "team") if p in (res.get("sent") or [])]
    why = str(res.get("msg") or res.get("code") or "")[:400]
    if res.get("ok"):
        return "보냈습니다" + (f" — {why}" if why else "")
    if str(res.get("code") or "") == "timeout":
        return UNKNOWN_SENT + tail
    marked = [p for k in ("unsure", "pending") if isinstance(res.get(k), list) for p in res[k]]
    unsure = [p for p in parts if p not in sent and (p in marked or (res.get("unknown") and not marked))]
    miss = [p for p in parts if p not in sent and p not in unsure]
    srv = str(res.get("server") or "")
    gone = _int(res.get("team_removed"), 0) or 0
    if unsure:
        head = (f"{PART_KO[sent[0]]}는 보냈고 {PART_KO[unsure[0]]}는 " if sent else f"{PART_KO[unsure[0]]}를 ")
        s = (head + "보냈는지 확인하지 못했습니다" + (f" — {srv}" if srv else "")
             + " · [보낸 공유 모두 거두기]로 지울 수 있습니다"
             + (f" · {PART_KO[miss[0]]}는 보내지 않았습니다" if miss else ""))
    elif sent and miss:
        s = (f"{PART_KO[sent[0]]}는 보냈고 {PART_KO[miss[0]]}는 보내지 못했습니다"
             + (f" — {srv}" if srv else "") + (f" · {why}" if why else "")
             + " · [보낸 공유 모두 거두기]로 거둘 수 있습니다")
    else:
        s = f"보내지 못했습니다 — {why}"
    if gone and "앞서 보낸 익명 팀 집계 기여분" not in s:
        s += f" · 앞서 보낸 익명 팀 집계 기여분 {gone}건은 지웠습니다 — 다시 넣으려면 익명 팀 집계를 골라 보내세요"
    return s + tail


def _in_share_dir(p):
    try:
        a = os.path.normcase(os.path.realpath(p))
        b = os.path.normcase(os.path.realpath(SHARE_DIR))
        return a.startswith(b + os.sep)
    except (OSError, ValueError, TypeError):
        return False


def _share_file(res, keys, default):
    r"""teamup 결과가 알려 준 파일 경로(keys 중 첫 값) 또는 기본 경로 — report\share\ 안의 것만."""
    for k in keys:
        v = res.get(k)
        if isinstance(v, str) and v.strip():
            p = v if os.path.isabs(v) else os.path.join(ROOT, v)
            if _in_share_dir(p):
                return p
    return default


def share_preview(body):
    r"""POST /api/share/preview — teamup --preview → 항목(체크 상자용)과 공유본 HTML(화면이 sandbox iframe 에 넣는다).
    보낼 때 쓸 일회용 표에 미리보기 파일·해시·고른 부분을 묶어 서버에만 둔다(화면이 경로·해시를 바꿔 보낼 수 없다)."""
    tag = latest_tag()
    if not tag:
        return 409, {"ok": False, "code": "no_result", "msg": "분석 결과가 없습니다 — 먼저 [분석 실행]"}
    personal, team = bool(body.get("personal")), bool(body.get("team"))
    if not (personal or team):
        return 400, {"ok": False, "code": "nothing", "msg": "보낼 것을 하나 이상 고르세요(개인 리포트 · 익명 팀 집계)"}
    owner, func = _clean_text(body.get("owner"), 40), _clean_text(body.get("function"), 40)
    if personal and not owner:
        return 400, {"ok": False, "code": "no_owner", "msg": "개인 리포트에 적을 이름을 적으세요"}
    args = ["--preview", "--tag", tag] + (["--personal"] if personal else []) + (["--team"] if team else [])
    if owner:
        args += ["--owner", owner]
    if func:
        args += ["--function", func]
    res = teamup_call(args, timeout=180)
    if not res.get("ok"):
        return 200, _scrub_secrets(dict(res, ok=False))
    pj = _share_file(res, ("preview_file", "preview_json", "json", "file"), os.path.join(SHARE_DIR, f"preview_{tag}.json"))
    # 공유본 HTML 은 개인 리포트를 고를 때만 생긴다 — 익명 팀 집계만 고르면 지난 미리보기 HTML 을 보이지 않는다
    ph = _share_file(res, ("preview_html", "html_file", "html"), os.path.join(SHARE_DIR, f"preview_{tag}.html")) if personal else ""
    try:
        with open(pj, "rb") as f:
            raw = f.read()
    except OSError:
        return 200, {"ok": False, "code": "no_preview", "msg": "미리보기 파일을 읽지 못했습니다 — 다시 만드세요"}
    sha = str(res.get("sha256") or "") or hashlib.sha256(raw).hexdigest()
    try:
        pv = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        pv = {}
    items = res.get("items") if isinstance(res.get("items"), list) else (pv.get("items") if isinstance(pv, dict) else None)
    items = [x for x in (items or []) if isinstance(x, dict) and str(x.get("id") or "")]
    page = ""
    if ph:
        try:
            with open(ph, encoding="utf-8-sig") as f:
                page = f.read()
        except OSError:
            page = ""
    ids = [str(x.get("id")) for x in items]
    nonce = issue_nonce("share", {"preview_file": pj, "sha256": sha, "tag": tag, "personal": personal, "team": team,
                                  "ids": ids})
    return 200, {"ok": True, "tag": tag, "items": _scrub_secrets(items), "html": page, "sha256": sha,
                 "personal": personal, "team": team, "nonce": nonce, "blocked": _int(res.get("blocked"), 0),
                 "period": str(res.get("period") or ""), "preview_file": os.path.relpath(pj, ROOT),
                 "msg": str(res.get("msg") or "")}


def share_send(body, extra):
    r"""POST /api/share — 미리보기(일회용 'share' 표의 값)에서 고른 항목만, 확인 창이 보인 서버 값(일회용 'share_check' 표 —
    [보내기…]가 받은 새 hello)으로 보내기 표(report\share\ticket_*.json)를 쓰고 teamup --share --ticket 으로 보낸다(C9).
    실패해도 다시 보내지 않는다. 한쪽만 갔으면 그렇게 말한다(say)."""
    personal = bool(body.get("personal")) and bool(extra.get("personal"))
    team = bool(body.get("team")) and bool(extra.get("team"))
    if body.get("confirm") is not True:
        return 400, {"ok": False, "code": "no_confirm", "msg": "확인 창에서 [보내기]를 눌러야 보냅니다"}
    if not (personal or team):
        return 400, {"ok": False, "code": "nothing", "msg": "보낼 것을 하나 이상 고르세요"}
    allowed = list(extra.get("ids") or [])
    inc = [str(x) for x in (body.get("include") or []) if str(x) in allowed] if isinstance(body.get("include"), list) else []
    if allowed and not inc:
        return 400, {"ok": False, "code": "nothing", "msg": "보낼 항목을 하나 이상 고르세요"}
    if not _in_share_dir(extra.get("preview_file") or ""):
        return 400, {"ok": False, "code": "no_preview", "msg": "미리보기를 다시 만드세요"}
    # 확인 창이 보인 값 — [보내기…]가 방금 받은 hello(share_check 표). 표가 없거나 이미 썼으면 보내지 않는다.
    ok, chk = take_nonce(body.get("check"), ("share_check",))
    if not ok:
        return 403, dict(NONCE_BAD)
    parts = [p for p, on in (("personal", personal), ("team", team)) if on]
    srv = (chk or {}).get("server")
    if not isinstance(srv, dict) or not srv.get("server"):
        code = str((chk or {}).get("code") or "unchecked")
        msg = ("조직장 서버를 확인하지 못해 보내지 않았습니다 — "
               + (str((chk or {}).get("msg") or "") or "[연결 확인]으로 다시 확인하세요"))
        say = msg + " (자동으로 다시 보내지 않습니다)"
        log("[공유] " + say)
        return 200, {"ok": False, "code": code if code != "ok" else "unchecked", "msg": msg, "sent": [], "say": say}
    join = addr_join()
    if not join:
        return 200, {"ok": False, "code": "bad_join", "msg": "참여 코드가 없습니다 — AgentFinder32-팀서버주소.bat 으로 조직장이 알려 준 주소와 참여 코드를 저장하세요"}
    try:
        ticket = write_ticket(extra, srv, inc, parts)
    except OSError as e:
        return 200, {"ok": False, "code": "no_preview", "msg": f"보내기 표를 쓰지 못했습니다({type(e).__name__}) — 보내지 않았습니다"}
    # teamup --share 를 그 자신의 정상 최장 대기보다 먼저 끊지 않는다(SHARE_WAIT_SEC — 설정이 가장 클 때 기준)
    args = ["--share", "--ticket", ticket, "--preview-file", extra["preview_file"], "--sha256", str(extra.get("sha256") or "")]
    args += (["--include"] + inc) if inc else []
    args += (["--personal"] if personal else []) + (["--team"] if team else [])
    log("[공유] 고른 항목을 조직장 서버로 보냅니다 — " + " · ".join(PART_KO[p] for p in parts) + f" · 항목 {len(inc)}개")
    try:
        res = teamup_call(args, timeout=SHARE_WAIT_SEC, join=join)
    finally:
        _drop_ticket(ticket)                 # teamup 이 쓰고 지운다 — 끊겼거나 못 띄웠으면 여기서
    say = share_say(res, parts)
    log("[공유] " + say)
    return 200, dict(_scrub_secrets(res), say=say)


RUN_BUSY_HINT = ("이 폴더에서 분석·수집 작업(AgentFinder32.bat 등)이 돌고 있습니다 — 그 작업이 끝난 뒤 다시 누르세요. "
                 "끝나지 않으면 AgentFinder32-강제종료.bat 으로 멈춘 뒤 다시 누를 수 있습니다")


class RunBusy(Exception):
    """이 설치 폴더의 분석·수집(화면 밖 — AgentFinder32.bat 의 run.py 등)이 돌고 있어 지우지 않았다(retention.run_active).
    처리기는 409 busy 로 답한다(consent.WithdrawBusy 와 같은 뜻 — /api/purge 의 지우기에서 쓴다)."""


def withdraw_sequence():
    r"""[모두 지우기(서버 사본 포함)](spec §6.2 — 부르는 쪽이 JOB 을 잡았다) — core\consent 의 순서 그대로:
    ① consent.begin_withdrawal — 이 폴더의 분석·수집이 돌면 consent.WithdrawBusy(아무것도 지우지 않았다 — 처리기가 409).
       아니면 지우기 기록(data\withdrawal.json 'in_progress')을 먼저 쓰고 영수증에 표시를 붙인다. 이때부터 끊겨도(창·PC 가
       꺼져도) 다음 시작 때 consent.resume_withdrawal 이 마저 지운다.
    ② teamup.withdraw_all(각 영수증을 그 서버에서) → ③ sweep_for_wipe(이 도구가 연 Copilot 채팅 — 전용 Edge 가 꺼져 있으면 띄워서 ·
       우리 Edge 닫기) → ④ consent.withdraw(남은 채팅 수 기록 → 큰 자료 → 설치 정보 → 매일 정리 작업 지우기 → 'done').
    ②③ 이 실패해도 ④ 는 한다. 서버에서 못 지운 영수증은 표시한 채 남아 시작할 때마다 다시 지운다.
    다 지운 뒤('done')에는 이 화면을 그대로 이어 쓴다 — 다음 요청이 새 설치 정보를 만든다(처음 설치한 상태)."""
    c = cfg()
    consent.begin_withdrawal(ROOT, c)
    server = None
    try:
        import teamup
        r = teamup.withdraw_all(ROOT, c, timeout=10)
        server = r if isinstance(r, dict) else {"ok": bool(r)}
    except Exception as e:  # noqa: BLE001 - 서버 사본 지우기 실패는 영수증이 남아 다음 시작 때 다시 한다
        server = {"ok": False, "error": type(e).__name__}
    left = receipts_view()
    edge = sweep_for_wipe(close_reason="withdraw")
    res = consent.withdraw(ROOT, c, server_withdrawal=_scrub_secrets(server), chats_left=edge.get("left"))
    n_chats = max(_int(res.get("chats_left"), 0) or 0, _int(edge.get("left"), 0) or 0)
    exp = max((x["expires"] for x in left if x.get("expires")), default="")
    # 결과 문장 — 지운 수·못 지운 수·마치지 못한 지우기·서버에서 지운 공유 수·Copilot 채팅은 core\consent 의 말 그대로
    # (withdraw_message — CLI 와 같다). 서버에 남은 공유는 화면이 서버 보관기한까지 말한다(그 줄은 여기서 붙인다 —
    # pending_receipts=0 으로 넘긴다)
    removed = _int((server or {}).get("removed"), 0) or 0
    msg = consent.withdraw_message(dict(res, pending_receipts=0, chats_left=n_chats, edge={"sweep": edge.get("sweep")},
                                        server={"removed": removed}))
    if left:
        msg += (" · 조직장 서버에서 아직 지우지 못했습니다"
                + (f" (서버 보관기한 {exp} 에 자동 삭제)" if exp else "") + " — 다음에 시작할 때 다시 지웁니다")
    return {"ok": True, "msg": msg, "deleted": int(res.get("deleted") or 0), "n_errors": len(res.get("errors") or []),
            "errors": (res.get("errors") or [])[:20], "pending_receipts": len(left), "server_expiry": exp,
            "task_removed": res.get("task_removed"), "withdrawn_at": res.get("withdrawn_at"),
            "edge": {k: edge[k] for k in ("sweep", "close", "error") if k in edge}, "chats_left": n_chats,
            "server_removed": removed, "state": res.get("state")}


CHATS_LEFT_CODES = ("noedge", "login", "notab", "hold", "busy", "error")
# 채팅 지우기를 설정으로 꺼 둔 때의 말 — core\consent 의 문장 그대로(CLI 와 같다)
CHATS_OFF_LINE = str(getattr(consent, "CHATS_OFF_MSG", "") or
                     "Copilot 채팅 지우기가 설정(copilotAuto.deleteChats)으로 꺼져 있어 이 도구가 연 채팅을 지우지 않았습니다 — "
                     "Copilot 대화 목록에서 직접 지울 수 있습니다")


def chats_msg(n, off=False):
    """지우지 못한 Copilot 채팅 안내 한 문장(없으면 "") — n 개(consent.CHATS_LEFT_MSG — 안내·CLI 와 같은 말).
    설정으로 지우기를 꺼 두었으면 그 까닭을 말한다(CHATS_OFF_LINE). 모두 지우기의 결과·시작 때 이어 마친 지우기·[내 데이터] 탭이 쓴다."""
    if off:
        return CHATS_OFF_LINE
    return consent.CHATS_LEFT_MSG.format(n=int(n)) if n else ""


def chats_line(n, off=False):
    """chats_msg 를 결과 문장 뒤에 붙일 꼴로(' · …' · 없으면 "")."""
    m = chats_msg(n, off)
    return (" · " + m) if m else ""


def sweep_for_wipe(close_reason="withdraw"):
    r"""모두 지우기 전에 이 도구가 연 Copilot 채팅을 지운다 — 기록(owned[])이나 보낸 지금 채팅이 있으면 전용 Edge 가
    꺼져 있어도 띄워서(launch — 로그인은 하지 않는다) 지우고, 우리 Edge 를 닫는다(copilot_auto.sweep_owned · close_own_edge — C6).
    지울 기록이 없으면 Edge 를 띄우지 않는다. 기록은 곧 지워지므로(전용 Edge 기록 파일) 못 지운 수를 돌려준다 — 부르는 쪽이
    결과 문장에 붙이고 consent.withdraw(chats_left=) 가 지우기 기록(data\withdrawal.json)에 남긴다.
    → {"sweep": 정리 코드, "close": 닫기 결과, "left": 못 지운 채팅 수 | None(정리를 못 불렀다 — 기록에서 센다), "off": 설정으로 끔}."""
    out = {"left": None, "off": False}
    try:
        ca = _ca_mod()
        rep = ca.sweep_owned(None, budget=CHAT_SWEEP_SEC, why="withdraw", launch=True, lock_wait=30) or {}
        code, n_left = str(rep.get("code") or ""), _int(rep.get("left"), 0) or 0
        out["sweep"] = code
        if code in CHATS_LEFT_CODES:
            n_left = max(n_left, 1)          # 지울 것이 있었는데(그렇지 않으면 none) 손대지 못했다
        out.update(left=n_left, off=code == "off")
        # 닫을 때는 다시 정리하지 않는다(tidy=False — 방금 했다 · consent.cli_withdraw 와 같다)
        out["close"] = str((ca.close_own_edge(None, reason=close_reason, force=True, tidy=False) or {}).get("why") or "")
    except Exception as e:  # noqa: BLE001 - Edge 정리 실패가 지우기를 막지 않는다
        out["error"] = type(e).__name__
    return out


def keep_session_file():
    r"""자료를 모두 지운 뒤에도 서버가 살아 있으면 열쇠 파일(data\ui_session.json)을 다시 쓴다 — 두 번째 bat 실행이 이 화면으로
    이어지게. main() 이 열쇠 파일을 쓴 서버에서만 한다(시작 거부 화면·같은 프로세스 시험에서는 쓰지 않는다)."""
    if SESSION_FILE_ON[0] and not os.path.exists(session_path()):
        write_session_file(PORT[0])


def purge_everything(other_user=False):
    r"""/api/purge all — 읽기 전용 화면의 [열지 않고 지우기](다른 사용자의 자료·주인을 모르는 자료)가 부른다. 내 자료에도 쓸 수
    있다(설치 정보까지 모두 지운다). 부르는 쪽이 JOB 을 잡았다. → 응답 dict.
    · 내 자료에 조직장 서버로 보낸 공유(영수증)가 있으면 모두 지우기 순서(withdraw_sequence — 서버 사본 먼저)로 지운다: 영수증을
      지우면 서버 사본을 지울 길이 없어진다.
    · 다른 사용자의 자료면 그 영수증의 서버 사본을 지우기만 하고(teamup.withdraw_all) Copilot 채팅은 건드리지 않는다(그 전용 Edge 는
      그 사람의 로그인이다). 서버에서 못 지운 영수증이 남으면 지우지 않고 표시를 붙여 둔다(consent.withdraw — 시작할 때마다
      다시 지운다 · retention.py --purge-all 과 같다).
    · 영수증이 없으면 이 도구가 연 Copilot 채팅부터 지우고(내 자료일 때) 모두 지운다. 끝에 매일 정리 작업을 지운다.
    이 폴더의 분석·수집이 돌면 RunBusy 또는 consent.WithdrawBusy(아무것도 지우지 않았다 — 처리기가 409)."""
    c = cfg()
    recs = _receipts()
    if recs and not other_user:
        return dict(withdraw_sequence(), scope="all", withdrawn=True)
    if run_active():
        raise RunBusy()
    server, edge, res = None, {}, None
    if recs:
        try:
            import teamup
            server = teamup.withdraw_all(ROOT, c, timeout=10)
            server = server if isinstance(server, dict) else {"ok": bool(server)}
        except Exception as e:  # noqa: BLE001 - 서버 사본 지우기 실패가 이 PC 의 지우기를 막지 않는다
            server = {"ok": False, "left": len(recs), "error": type(e).__name__}
    if not other_user:
        edge = sweep_for_wipe(close_reason="purge_all")
    close_edge("purge_all", tidy=False)        # 전용 Edge 프로필까지 지우므로 먼저 닫는다(채팅 정리 없이)
    if _receipts():                            # 서버에서 못 지운 영수증 — 표시해 남기고 나머지를 지운다(다음 시작 때 다시 지운다)
        res = consent.withdraw(ROOT, c, server_withdrawal=_scrub_secrets(server))
    else:
        res = retention.purge_all(ROOT, keep_consent=False, keep_edge=False)
        try:
            retention.unregister_task(ROOT)   # 매일 정리 작업도 지운다 — 지울 자료가 없다
        except Exception:  # noqa: BLE001
            pass
    errs = list(res.get("errors") or [])
    out = {"ok": True, "scope": "all", "deleted": int(res.get("deleted") or 0), "n_errors": len(errs), "errors": errs[:20]}
    msg = f"이 PC 의 자료 {out['deleted']:,}개를 지웠습니다"
    if isinstance(server, dict):
        n_left = len(_receipts())
        out["server"] = {"removed": _int(server.get("removed"), 0) or 0, "left": n_left}
        msg += (f" · 조직장 서버의 공유 {out['server']['removed']}건을 지웠습니다" if not n_left else
                f" · 조직장 서버의 공유 {n_left}건은 아직 지우지 못했습니다 — 다음에 시작할 때 다시 지웁니다")
    n_chats = _int(edge.get("left"), 0) or 0
    out["msg"] = msg + chats_line(n_chats, off=bool(edge.get("off")))
    out["chats_left"] = n_chats
    return out


def retry_server_withdrawals():
    r"""모두 지운 뒤 서버에서 못 지운 공유(data\share_receipts.json 에 표시해 남긴 것)가 있으면 시작할 때 다시 지운다(spec §6.2 —
    teamup.retry_withdrawals: data\withdrawal.json 이 있고 표시한 영수증이 남았을 때만 · 할 일이 없으면 None). 예외를 내지 않는다."""
    try:
        if not _receipts():
            return None
        import teamup
        r = teamup.retry_withdrawals(ROOT, cfg(), timeout=5)
        if r is None:
            return None
        left = [x for x in (r.get("pending") or []) if isinstance(x, dict)] if isinstance(r, dict) else []
        if left:
            exp = max((str(x.get("expires") or "") for x in left if x.get("expires")), default="")
            log("[지우기] 조직장 서버에서 아직 지우지 못한 공유가 있습니다" + (f" (서버 보관기한 {exp} 에 자동 삭제)" if exp else "")
                + " — 다음에 시작할 때 다시 지웁니다")
        else:
            log("[지우기] 조직장 서버에 남아 있던 공유를 지웠습니다")
        return len(left)
    except Exception as e:  # noqa: BLE001 - 시작을 막지 않는다
        log(f"[지우기] 서버 사본 다시 지우기를 건너뜀({type(e).__name__})")
        return None


def resume_withdrawal():
    r"""지난번 모두 지우기가 끝나지 않았으면(data\withdrawal.json 의 state 가 'in_progress' — 창·PC 가 그 사이에 꺼졌거나 다른
    프로그램이 연 파일이 남았다) 이어서 마친다(consent.resume_withdrawal — 이 PC 의 자료·설치 정보·매일 정리 작업. 서버 사본은
    표시해 둔 영수증으로 retry_server_withdrawals 가 다시 지운다). 다 지우면 이 폴더는 처음 설치한 상태로 곧바로 쓸 수 있다.
    → 그 결과 dict | None(할 일이 없음) | False(하지 못함). 예외를 내지 않는다."""
    try:
        r = consent.resume_withdrawal(ROOT, cfg())
    except Exception as e:  # noqa: BLE001 - 시작을 막지 않는다(다음 시작 때 다시)
        log(f"[지우기] 끝나지 않은 모두 지우기를 이어서 하지 못했습니다({type(e).__name__}) — 다음에 시작할 때 다시 합니다")
        return False
    if r is None:
        return None
    r = r if isinstance(r, dict) else {}
    n = _int(r.get("deleted"), 0) or 0
    if r.get("state") == consent.WD_IN_PROGRESS:
        line = (f"지난번에 끝나지 않은 모두 지우기를 이어서 이 PC 의 자료 {n:,}개를 지웠지만 아직 다 지우지 못했습니다 — "
                "파일을 연 프로그램을 닫으면 다음에 시작할 때 마저 지웁니다")
    else:
        line = f"지난번에 끝나지 않은 모두 지우기를 이어서 마쳤습니다 — 이 PC 의 자료 {n:,}개를 지웠습니다"
    line += chats_line(_int(r.get("chats_left"), 0) or 0)
    log("[지우기] " + line)
    add_notice("withdraw", line)
    try:
        print("[ui] " + line, flush=True)
    except (OSError, ValueError):            # 콘솔에 찍지 못해도(닫힌 콘솔·글자 변환) 시작은 계속한다
        pass
    return r


GUARD_LOCK = threading.Lock()


def restricted_guard(at_start=False):
    r"""제한 고객 목록이 지난 분석 뒤에 바뀌었으면(retention.restricted_stale — run_meta 의 restricted_sha256 이 없거나 다름) 그 분석으로
    만든 자료(raw·intermediate·result·html·share)를 지운다 — run.py 시작과 같다(D9). 화면 시작 · [후보 발굴]·[워크플로우 재분석] 전 ·
    결과 탭·공유 미리보기 앞에서 부른다. 화면 작업이나 다른 분석이 도는 동안·목록을 읽지 못하면 하지 않는다. 다른 사용자의 자료는
    건드리지 않는다(D17 — at_start 일 때만 물어본다: 결과 경로는 내 자료에서만 열린다). → 지웠나.
    한 번에 하나만 돈다(GUARD_LOCK — 결과 탭 여럿이 함께 열려도 두 번 지우거나 두 번 알리지 않는다)."""
    with GUARD_LOCK:
        return _restricted_guard(at_start)


def _restricted_guard(at_start):
    tag = latest_tag()
    if not tag or _ui_busy():                # 화면 작업·리포트 만들기가 report\ 를 읽고 쓰는 동안에는 지우지 않는다
        return False
    try:
        import privacy
        r = privacy.load_restricted(cfg(), ROOT)
        stale = bool(retention.restricted_stale(ROOT, tag, r))
    except Exception:  # noqa: BLE001 - 목록이 없거나 깨졌으면 분석·공유가 이미 거절한다
        return False
    if not stale or (at_start and _others_data()) or run_active():
        return False
    try:
        res = retention.purge_classes(ROOT)
    except Exception as e:  # noqa: BLE001
        log(f"[제한 고객] 지난 분석 자료를 지우지 못했습니다({type(e).__name__})")
        return False
    with LOCK:
        MANUAL.clear()
    _META_OK.clear()
    line = (f"제한 고객 목록이 바뀌어 지난 분석 자료 {int(res.get('deleted') or 0):,}개를 지웠습니다 — "
            "[분석 실행]으로 다시 분석하세요")
    log("[제한 고객] " + line)
    add_notice("restricted", line)
    return True


RESTRICTED_GONE = {"ok": False, "code": "no_result", "error": "제한 고객 목록이 바뀌었습니다",
                   "msg": "제한 고객 목록이 바뀌어 지난 분석 자료를 지웠습니다 — [분석 실행]으로 다시 분석한 뒤 하세요",
                   "hint": "제한 고객 목록이 바뀌어 지난 분석 자료를 지웠습니다 — [분석 실행]으로 다시 분석하세요"}


def sync_daily_task():
    r"""매일 정리 예약 작업을 설정(retention.scheduledPurge)에 맞춘다(retention.sync_task — 켜져 있으면 모은 자료가 있고 작업이
    없을 때 만들고, 꺼져 있으면 있을 때 지운다 · 하루 한 번만 작업 스케줄러에 묻는다). 모은 자료가 없는 설치에서는 화면을 열기만
    해서는 작업을 만들지 않는다(분석을 시작할 때 run.py 가 만든다). 내 자료이고 모두 지우는 중이 아닐 때만 한다 — 다른 사용자의
    자료·주인을 모르는 자료에는 작업을 만들지도 지우지도 않는다. 맞추지 못했으면 그 까닭(sync_task 의 message)을 화면에 한 번 알린다.
    화면 시작(startup)이 부른다 — 화면에서 모두 지운 뒤에는 부르지 않는다(지운 작업은 다음 분석 시작이 다시 만든다 · 모은 자료가
    있으면 다음 화면 시작도).
    → sync_task 의 답 {"task", "message"} | None(하지 않았다). 예외를 내지 않는다."""
    try:
        c = cfg()
        if not consent.status(ROOT, c).get("accepted"):
            return None
        r = retention.sync_task(ROOT, c)
    except Exception as e:  # noqa: BLE001 - 예약 작업 맞추기가 시작을 막지 않는다(화면을 열 때와 분석 시작·끝에도 지운다)
        log(f"[정리] 매일 정리 작업을 맞추지 못했습니다({type(e).__name__})")
        return None
    r = r if isinstance(r, dict) else {}
    msg = str(r.get("message") or "").strip()
    if msg:
        log("[정리] " + msg)
        add_notice("task", msg)
    return r


def startup():
    r"""시작 순서(spec §6.2): install.startup_check(설치 위치 D21 → 옛 LoadMonitor 프로그램 파일 D20) → retention.purge_legacy →
    끝나지 않은 모두 지우기 마치기 → retention.purge → 제한 고객 목록이 바뀌었으면 지난 분석 지우기 → 남은 COM 원자료 지우기(다른
    분석이 돌지 않을 때) → 매일 정리 예약 작업 맞추기(내 자료일 때만 — sync_daily_task · 이번 시작이 모두 지우기를 마저 했으면
    하지 않는다: 방금 지운 작업을 곧바로 다시 만들지 않는다) → (모두 지운 뒤 남은 서버 사본 다시 지우기 — 따로 스레드).
    사람에게 묻는 단계는 없다. → 막을 까닭(한국어) 또는 ""."""
    msg = install.startup_check(ROOT)
    if msg:
        STARTUP["blocked"] = msg
        return msg
    try:
        lg = retention.purge_legacy(ROOT)
    except Exception as e:  # noqa: BLE001 - 정리 실패는 알리고 시작한다
        lg = {"deleted": 0, "errors": [{"why": type(e).__name__}]}
    n = int(lg.get("deleted") or 0)
    STARTUP["legacy"] = n
    if n:
        line = f"이 폴더에 남아 있던 예전 LoadMonitor 자료 {n:,}개를 지웠습니다"
        log("[정리] " + line)
        add_notice("legacy", line)
        print("[ui] " + line, flush=True)
    resumed = resume_withdrawal()
    try:
        pr = retention.purge(ROOT, cfg())
    except Exception as e:  # noqa: BLE001
        pr = {"deleted": 0, "errors": [{"why": type(e).__name__}]}
    STARTUP["purge"] = {"deleted": int(pr.get("deleted") or 0), "errors": len(pr.get("errors") or [])}
    if pr.get("deleted"):
        log(f"[보관기한] 기한이 지난 파일 {int(pr['deleted']):,}개를 지웠습니다")
    if pr.get("errors"):
        log(f"[보관기한] {len(pr['errors'])}개는 지우지 못했습니다 — 다음 정리 때 다시 지웁니다")
    restricted_guard(at_start=True)
    drop_raw_now(check=True)
    if not resumed:                          # 이번 시작이 모두 지우기를 마저 했으면 그 작업을 다시 만들지 않는다 — 다음 시작이 만든다
        sync_daily_task()
    threading.Thread(target=retry_server_withdrawals, daemon=True, name="af32-withdraw-retry").start()
    return ""


def busy_hint(step):
    """지금 할 수 없는 까닭(409 hint) — 무엇이 돌고 있는지 이름을 넣는다."""
    s = re.sub(r"\s+", " ", str(step or "")).strip()
    s = re.split(r" \(| — | - ", s)[0].strip()[:40] or "분석 실행"
    return f"지금 '{s}' 작업이 돌고 있습니다 — 위 상태가 '대기'로 바뀐 뒤 다시 누르세요"


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__AF32_TITLE__</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic',system-ui,sans-serif;background:#f2f4f7;color:#12151a;padding:22px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:20px;letter-spacing:-0.3px}h1 small{font-size:11px;color:#8b929b;font-weight:400;margin-left:8px}
.purpose{background:#eef4fd;border:1px solid #b9d3f2;color:#1c4e8a;border-radius:6px;padding:8px 12px;font-size:12.5px;margin:8px 0 12px;line-height:1.6}
.paper{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px;color:#4a5159;margin:-4px 0 12px;padding:0 2px;line-height:1.6}
.paper button{padding:3px 12px}
.card{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}
.card h2{font-size:13px;margin-bottom:10px;color:#2c333b}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px}
input[type=date],input[type=text],input[type=number],input[type=password],input:not([type]){padding:5px 8px;border:1px solid #c9cfd8;border-radius:5px;font:inherit;font-size:12px}
.chip{border:1px solid #c9cfd8;background:#fff;border-radius:14px;padding:4px 12px;font-size:11.5px;cursor:pointer;color:#4a5159}
.chip:hover,.chip.on{border-color:#2a78d6;color:#2a78d6;background:#f0f6fd}
button.run{background:#2a78d6;color:#fff;border:0;border-radius:5px;padding:9px 24px;font-size:13.5px;font-weight:700;cursor:pointer;font-family:inherit}
button.run:disabled{background:#c9cfd8;cursor:default}
button.ghost{background:#fff;color:#4a5159;border:1px solid #c9cfd8;border-radius:5px;padding:6px 12px;font-size:12px;cursor:pointer;font-family:inherit}
button.ghost:disabled{opacity:.45;cursor:default}
button.danger{color:#c0122f;border-color:#f0cdd5}
#log{background:#12151a;color:#d6dbe1;border-radius:5px;padding:10px 12px;height:170px;overflow-y:auto;
 font-family:Consolas,monospace;font-size:11px;line-height:1.55;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;border-bottom:2px solid #e4e7eb;font-size:11px}
td{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}
.note{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}
.dim{color:#8b929b}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:0}
.state{font-size:12px;color:#5a626b;font-weight:400}
details{margin-bottom:12px}
details summary{cursor:pointer;font-size:13px;font-weight:700;color:#2c333b;padding:12px 16px;
 background:#fff;border:1px solid #e4e7eb;border-radius:8px;list-style:none}
details summary::before{content:"▸ ";color:#8b929b}
details[open] summary{border-radius:8px 8px 0 0}details[open] summary::before{content:"▾ "}
details .body{background:#fff;border:1px solid #e4e7eb;border-top:0;border-radius:0 0 8px 8px;padding:14px 16px}
.tag{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}
.banner{border-radius:6px;padding:9px 14px;margin:0 0 12px;font-size:12.5px;line-height:1.6}
.b-info{background:#eaf2fd;border:1px solid #b9d3f2;color:#1c4e8a}
.b-warn{background:#fdf3e6;border:1px solid #f0d9b0;color:#8a5a00}
.b-bad{background:#fdecee;border:1px solid #f0b8c2;color:#8a1020}
.overlay{position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(18,21,26,.55);z-index:100;overflow:auto;padding:28px 12px}
.ovbox{background:#fff;border-radius:10px;max-width:860px;margin:0 auto;padding:20px 24px;box-shadow:0 10px 40px rgba(0,0,0,.25)}
.ovbox h2{font-size:16px;margin-bottom:6px}
.notice h3{font-size:13px;margin:14px 0 4px;color:#1c4e8a}
.notice ul{margin:0 0 0 18px;font-size:12.5px;line-height:1.75}
.notice table{margin-top:6px}
.btns{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px;position:sticky;bottom:0;background:#fff;padding-top:10px}
.item{display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-bottom:1px solid #f0f2f5;font-size:12px}
.item.flagged{background:#fff8ec;border-left:3px solid #e08a00;padding-left:6px}
</style></head><body><div class="wrap">
<h1>__AF32_TITLE__<small id="ver">이 PC 안에서만 동작합니다 · AI 는 회사 M365 Copilot 만 씁니다</small></h1>
<div class="purpose" id="purpose">이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다. 사람을 평가하거나 근태·업무량을 보는 데 쓰지 않습니다.</div>
<div class="paper" id="paper"><span id="paper_line">__AF32_PAPER__</span>
 <button class="ghost" id="nt_open" title="무엇을 읽고 어디에 얼마나 두는지 적은 안내를 엽니다 — 읽기만 합니다">안내</button></div>
<div id="notices"></div>
<div id="stub_banner" class="banner b-warn" style="display:none"></div>

<div id="readonly" style="display:none">
 <div class="card"><h2 id="ro_title"></h2>
  <div class="note" id="ro_head" style="font-size:12px;color:#4a5159"></div>
  <div class="note" id="ro_pending" style="display:none;font-size:12px;color:#8a5a00"></div>
  <div class="row" style="margin-top:10px">
   <button class="run" id="ro_wipe" style="background:#c0122f;display:none">열지 않고 지우기</button>
   <button class="ghost danger" id="ro_withdraw" style="display:none" title="조직장 서버에 보낸 공유를 먼저 지우고, 이 도구가 연 Copilot 채팅과 이 PC 의 자료를 모두 지웁니다">모두 지우기(서버 사본 포함)</button>
   <span class="state" id="ro_msg"></span></div>
  <div class="note" id="ro_contact" style="font-size:12px;color:#4a5159"></div></div>
</div>

<div id="app" style="display:none">
<div class="card"><div class="row">
 <span class="chip" data-m="1">1개월</span><span class="chip on" data-m="3">3개월</span>
 <label>시작 <input type="date" id="from"></label><label>끝 <input type="date" id="to"></label>
 <label title="회사 M365 Copilot 으로 업무를 분류하고 Agentic AI 후보를 찾습니다"><input type="checkbox" id="ai" checked> AI 분석</label>
 <label title="메일·일정을 다시 읽지 않고 이미 모은 자료로 분석만 합니다"><input type="checkbox" id="skip"> 다시 읽지 않고 분석만</label>
 <button class="run" id="go" title="Outlook 메일·일정 목록을 읽고 분석합니다 — 조직장에게 보내지 않습니다">분석 실행</button>
 <button class="run" id="stop" style="background:#c0122f;display:none">중지</button>
 <span class="state" id="state">대기 중</span>
</div>
<div class="note" id="pnote"></div>
<div class="row" style="margin-top:8px">
 <button class="ghost" id="owa" title="전용 Edge 창에서 내가 로그인한 Outlook 웹의 메일·일정 목록만 읽습니다">Outlook 웹 읽기</button>
 <button class="ghost" id="diag">AI 연결 진단</button>
 <button class="ghost" id="cdiag">수집 진단</button>
 <button class="ghost" id="chatsweep" title="이 도구가 열고 기록해 둔 Copilot 채팅만 다시 지웁니다 — 사람이 쓰던 채팅은 건드리지 않습니다">이 도구가 연 Copilot 채팅 지우기</button>
 <button class="ghost" id="report" title="이 PC 에만 두는 개인 리포트(HTML)를 만듭니다">내 리포트 만들기</button>
 <button class="ghost" id="openf">결과 폴더 열기</button>
 <span style="flex:1"></span>
 <button class="ghost" id="quit">서버 종료</button>
</div>
<div id="prog" style="display:none;margin-top:10px">
 <div style="display:flex;justify-content:space-between;font-size:11.5px;color:#4a5159;margin-bottom:4px">
  <span id="pg_label"></span><span id="pg_time" style="color:#8b929b"></span></div>
 <div style="height:8px;background:#eef0f3;border-radius:4px;overflow:hidden">
  <i id="pg_bar" style="display:block;height:100%;width:0%;background:#2a78d6;transition:width .4s"></i></div>
 <div class="note" style="margin-top:5px" id="pg_hint"></div>
</div>
<div class="note" id="chatline" style="display:none;margin-top:6px"></div></div>

<div class="row" id="tabs" style="margin-bottom:12px">
 <span class="chip on" data-t="agentic">Agentic AI 후보</span>
 <span class="chip" data-t="flow">워크플로우</span>
 <span class="chip" data-t="tax">업무 분류</span>
 <span class="chip" data-t="collect">수집·제외 현황</span>
 <span class="chip" data-t="share">공유</span>
 <span class="chip" data-t="mine">내 데이터</span>
</div>
<div id="judged_warn" class="banner b-warn" style="display:none"></div>

<div class="tab" id="tab-agentic"><div id="rv-agentic"></div></div>
<div class="tab" id="tab-flow" style="display:none"><div id="rv-flow"></div></div>
<div class="tab" id="tab-tax" style="display:none"><div id="rv-tax"></div>
 <div class="card"><h2>과제 이름 지정 <span class="state">비워 두면 AI 가 목록에서 스스로 찾습니다 · 이 PC 에서만 씁니다</span></h2>
  <table id="pjtbl"></table>
  <div class="row" style="margin-top:8px">
   <button class="ghost" id="pjadd">+ 과제 추가</button>
   <button class="ghost" id="pjsave">저장</button>
   <button class="ghost" id="pjretag" style="border-color:#2a78d6;color:#2a78d6">저장 + 지정 반영 재분류</button>
   <span class="state" id="pjmsg"></span></div>
  <div class="note">지정한 과제는 AI 분류 체계에 늘 들어갑니다. <b>재분류</b>는 '공통'·자동 발견으로 분류된 근거 중 이름·키워드가 들어 있거나
  관련 단어가 2개 이상 맞는 것을 지정 과제로 옮깁니다(Copilot 을 쓰지 않습니다). 과제 이름은 공유 자료에 넣지 않습니다.</div></div>
</div>
<div class="tab" id="tab-collect" style="display:none"><div id="rv-collect"></div>
 <div class="card"><h2>날짜별 수집 기록 <span class="state" id="cvstate"></span></h2>
  <div id="cvbody"><div class="note">불러오는 중…</div></div>
  <div class="row" style="margin-top:8px">
   <button class="ghost" id="cvrefresh">새로고침</button>
   <button class="ghost" id="cvreset" title="다음 [분석 실행]이 기간 전체를 처음부터 다시 읽게 합니다(모은 자료는 지우지 않음)">커서 초기화</button>
   <span class="state" id="cvmsg"></span></div>
  <div class="note">날 수는 한 원천(data 폴더의 coverage_ledger.json)에서 셉니다. <b>읽음</b>=확인된 날(0건 확인 포함) · <b>일부</b>=읽었지만 끝까지
  확인하지 못한 날 · <b>미관측</b>=읽지 못한 날. 날짜 목록 없이 날 수만 보입니다.</div></div>
</div>
<div class="tab" id="tab-share" style="display:none">
 <div class="card"><h2>조직장에게 공유 <span class="state">선택 사항입니다 — 공유하지 않아도 불이익이 없습니다</span></h2>
  <div class="note" style="font-size:12px;color:#4a5159">공유는 이 탭에서만 합니다. 자동으로 보내지 않고, 보내지 못해도 다시 보내지 않습니다.
  보낼 내용을 미리 보고 항목별로 고른 뒤, 받는 서버·조직·전송 방식·서버 보관기한을 확인하고 보냅니다. 개인 리포트는 조직장만 열람합니다.</div>
  <div id="sh_status" style="margin-top:8px"><div class="note">불러오는 중…</div></div>
  <div class="row" style="margin-top:8px"><button class="ghost" id="sh_check" title="조직장 서버에 한 번 연결해 조직 이름·전송 방식·서버 보관기한을 받아 옵니다 — 아무것도 보내지 않습니다">연결 확인</button>
   <span class="state" id="sh_cmsg">이 탭을 열어도 조직장 서버에 연결하지 않습니다 — [연결 확인]·[보내기…]·거두기를 누를 때만 연결합니다</span></div></div>
 <div class="card"><h2>조직장 서버 주소</h2>
  <div id="sh_addr" style="font-size:12.5px"><div class="note">불러오는 중…</div></div>
  <div class="note">주소와 참여 코드는 조직장이 알려 줍니다. 저장·변경은 <b>AgentFinder32-팀서버주소.bat</b> 에서만 합니다 — 참여 코드는 이 PC 의 config 폴더에만 두고, 화면에는 앞 4자만 보입니다.</div></div>
 <div class="card"><h2>보낼 내용 고르기</h2>
  <div class="row"><label>이름 <input id="sh_owner" style="width:140px"></label><label>파트 <input id="sh_func" style="width:140px"></label>
   <span class="state">개인 리포트에 이 이름과 파트를 적습니다</span></div>
  <div style="margin-top:10px;font-size:12.5px"><label><input type="checkbox" id="sh_personal"> <span id="sh_personal_l">내 개인 리포트를 〈조직장〉에게 공유합니다 (조직장만 열람)</span></label></div>
  <div style="margin-top:4px;font-size:12.5px"><label><input type="checkbox" id="sh_team"> 익명 팀 집계에 내 Agentic AI 후보를 포함합니다</label></div>
  <div class="row" style="margin-top:10px"><button class="ghost" id="sh_prev">미리보기 만들기</button><span class="state" id="sh_pmsg"></span></div>
  <div class="note" id="sh_mask" style="font-size:12px;color:#4a5159"></div>
  <div id="sh_items" style="margin-top:8px"></div>
  <div class="note" id="sh_fnote" style="display:none"></div>
  <iframe id="sh_frame" sandbox="" referrerpolicy="no-referrer" title="보낼 개인 리포트 미리보기" style="display:none;width:100%;height:520px;border:1px solid #e4e7eb;border-radius:6px;background:#fff;margin-top:8px"></iframe>
  <div class="row" style="margin-top:10px"><button class="run" id="sh_send" disabled>보내기…</button><span class="state" id="sh_smsg"></span></div></div>
 <div class="card"><h2>보낸 공유</h2><div id="sh_receipts"><div class="note">보낸 공유가 없습니다.</div></div>
  <div class="row" style="margin-top:8px"><button class="ghost danger" id="sh_wd">보낸 공유 모두 거두기</button><span class="state" id="sh_wmsg"></span></div>
  <div class="note">거두면 조직장 서버에서 내 개인 리포트와 익명 팀 집계 기여분을 지웁니다. 서버에 닿지 않으면 서버 보관기한이 지나 자동으로 지워집니다.</div></div>
</div>
<div class="tab" id="tab-mine" style="display:none">
 <div class="card"><h2>내 자료</h2><div id="mi_state" class="state"></div>
  <div class="note" id="mi_paper" style="font-size:12px;color:#4a5159"></div>
  <details style="margin-top:10px"><summary>안내문 전체 보기</summary><div class="body notice" id="mi_notice"></div></details></div>
 <div class="card"><h2>보관기한 <span class="state">기한이 지나면 자동으로 지웁니다</span></h2><table id="mi_ret"></table><div class="note" id="mi_task"></div>
  <div id="mi_rcpt"></div></div>
 <div class="card"><h2>내 자료 지우기</h2>
  <div class="row">
   <button class="ghost" id="mi_expired">기한 지난 자료 지우기</button>
   <button class="ghost danger" id="mi_all">모은 자료 모두 지우기</button>
   <button class="ghost danger" id="mi_withdraw" title="조직장 서버에 보낸 공유를 먼저 지우고, 이 도구가 연 Copilot 채팅과 이 PC 의 자료를 모두 지웁니다">모두 지우기(서버 사본 포함)</button></div>
  <div class="note"><b>모은 자료 모두 지우기</b>는 이 PC 의 모은 자료와 분석 결과·리포트만 지웁니다. <b>모두 지우기(서버 사본 포함)</b>는 조직장 서버에 공유한 사본을 지우고,
  이 도구가 연 Copilot 채팅을 지우고, 이 PC 의 모은 자료·결과·설치 정보를 모두 지웁니다. 지운 뒤에는 처음 설치한 상태로 이어서 쓸 수 있습니다.
  분석이 도는 동안에는 지울 수 없습니다.</div>
  <div class="note" id="mi_msg" style="font-size:12px;color:#4a5159"></div></div>
</div>

<details id="dlog"><summary>진행 로그 <span class="state" id="step"></span></summary>
 <div class="body"><div id="log">대기 중…</div></div></details>
</div>

<div id="sbar" style="position:fixed;left:0;right:0;bottom:0;background:#12151a;color:#d6dbe1;
 font-size:11.5px;padding:6px 16px;display:flex;gap:18px;align-items:center;z-index:50;
 border-top:1px solid #2a2f36;flex-wrap:wrap">
 <span style="display:inline-flex;align-items:center;gap:6px">
  <i id="sb_dot" style="width:8px;height:8px;border-radius:50%;background:#4fc47f;display:inline-block"></i>
  <b id="sb_state">대기</b></span>
 <span id="sb_prog" style="display:none;align-items:center;gap:8px">
  <span id="sb_phase"></span>
  <span style="width:130px;height:6px;background:#2a2f36;border-radius:3px;overflow:hidden;display:inline-block">
   <i id="sb_bar" style="display:block;height:100%;width:0%;background:#4f8ef7"></i></span>
  <span id="sb_eta" style="color:#8b929b"></span></span>
 <span id="sb_last" style="color:#8b929b"></span>
 <span style="flex:1"></span>
 <span id="sb_ver" style="color:#5a626b"></span>
</div>
<div style="height:44px"></div>
</div>

<div id="notice" class="overlay" style="display:none"><div class="ovbox">
 <h2>안내</h2>
 <div class="purpose" style="margin:6px 0 4px">이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다. 사람을 평가하거나 근태·업무량을 보는 데 쓰지 않습니다.</div>
 <div id="nt_body" class="notice"></div>
 <div class="btns"><button class="ghost" id="nt_close" style="padding:9px 20px;font-size:13px">닫기</button>
  <span class="state" id="nt_msg"></span></div>
</div></div>

<div id="confirm" class="overlay" style="display:none"><div class="ovbox" style="max-width:620px">
 <h2>조직장 서버로 보냅니다</h2>
 <div id="cf_body" style="font-size:12.5px;line-height:1.8;margin-top:8px"></div>
 <div class="btns"><button class="run" id="cf_yes">보내기</button><button class="ghost" id="cf_no" style="padding:9px 20px">취소</button></div>
</div></div>

<script>
const $=id=>document.getElementById(id);
const TOKEN="__AF32_UI__";
const NL="\\n";
const PAL=["#2a78d6","#0e8c7a","#a61b4a","#e08a00","#6c4fb8","#3d8f3d","#c05a78","#4a7f9e","#8a6d3b","#556270"];
const WTCOL={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
const AGENT_C={"상":"#1d8a4a","중":"#c98a00","하":"#8b929b"};
const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
const num=v=>{const n=Number(v);return Number.isFinite(n)?n:0;};
// 서버 호출 — POST 는 JSON 형식·화면 열쇠(X-AF32-UI)를 함께 보낸다. 403 consent_required(닫힌 폴더 — 다른 사용자의 자료·끝나지 않은
// 모두 지우기)면 상태를 다시 읽어 읽기 전용 화면으로 바꾼다.
async function api(path,opt){
 opt=opt||{};
 const method=opt.method||(opt.body!==undefined?"POST":"GET");
 const init={method:method,headers:{},cache:"no-store"};
 if(method!=="GET"){init.headers["Content-Type"]="application/json";init.headers["X-AF32-UI"]=TOKEN;
  init.body=JSON.stringify(opt.body===undefined?{}:opt.body);if(opt.keepalive)init.keepalive=true;}
 let r=null,d={};
 try{r=await fetch(path,init);}catch(e){return {ok:false,_http:0,error:"서버와 연결이 끊겼습니다 — 창을 닫고 다시 실행하세요"};}
 try{d=await r.json();}catch(e){d={};}
 if(!d||typeof d!=="object"||Array.isArray(d))d={value:d};
 d._http=r.status;
 if(r.status===403&&d.error==="no_session")noSession();
 if(r.status===403&&d.error==="consent_required"&&!opt.quiet)consentLoad();
 return d;
}
// 세션 쿠키가 없다(서버를 다시 띄웠다) — 이 탭은 더 쓸 수 없다. bat 을 다시 실행하면 열린 화면으로 이어진다
function noSession(){
 if(window.__afNoSess)return;window.__afNoSess=1;
 const el=document.createElement("div");el.className="banner b-bad";
 el.textContent="화면 연결이 끊겼습니다 — AgentFinder32-UI.bat 을 다시 실행하면 열린 화면으로 이어집니다";
 $("notices").appendChild(el);
}
// ── 시작 상태 — 사람에게 묻는 단계는 없다. 내 자료면 처음부터 탭을 보인다. 닫는 것은 다른 사용자의 자료·주인을 모르는 자료
//    (열지 않고 지우기만)와 끝나지 않은 모두 지우기(다음 시작 때 마저 지운다)뿐이다 ──
let CONSENT=null, APP_ON=false, WIPING=false, RO_NOW=false;
function noticeHTML(n,order){
 return (order||[]).map(k=>{const s=(n||{})[k];if(!s)return "";
  let h=`<h3>${esc(s.title)}</h3><ul>`+(s.lines||[]).map(x=>`<li>${esc(x)}</li>`).join("")+"</ul>";
  if(s.rows&&s.rows.length)h+='<table><tr><th>무엇</th><th>어디</th><th style="width:90px">보관</th></tr>'
   +s.rows.map(r=>`<tr><td>${esc(r.item)}</td><td>${esc(r.where)}</td><td>${num(r.days)}일</td></tr>`).join("")+"</table>";
  return h;}).join("");
}
// 읽기 전용 화면 — 제목·까닭·아직 남은 것·문의 줄과 단추 둘 중 하나(열지 않고 지우기 | 모두 지우기)
function roShow(title,head,left,contact,wipe,all){
 $("ro_title").textContent=title;$("ro_head").textContent=head;
 $("ro_pending").textContent=left||"";$("ro_pending").style.display=left?"":"none";
 $("ro_contact").textContent=contact||"";
 $("ro_wipe").style.display=wipe?"":"none";$("ro_withdraw").style.display=all?"":"none";
 $("readonly").style.display="";
}
let CS_BUSY=false;
async function consentLoad(){
 if(CS_BUSY)return;CS_BUSY=true;
 try{const d=await api("/api/consent",{quiet:true});
  if(!d.ok){if(!APP_ON)roShow("화면을 열지 못했습니다",d.error||"상태를 불러오지 못했습니다 — 창을 닫고 다시 실행하세요","","",false,false);return;}
  CONSENT=d;showState(d);}
 finally{CS_BUSY=false;}
}
function showState(d){
 const st=d.state||{};
 const warn=(d.config_warnings||[]);
 const nb=$("notices");
 const cw=warn.length?`<div class="banner b-warn">설정 값 일부를 규칙에 맞게 고쳐 썼습니다 — ${warn.map(esc).join(" · ")}</div>`:"";
 nb.querySelectorAll(".cfgwarn").forEach(x=>x.remove());
 if(cw){const w=document.createElement("div");w.className="cfgwarn";w.innerHTML=cw;nb.appendChild(w);}
 RO_NOW=false;
 if(st.accepted){
  $("readonly").style.display="none";$("app").style.display="";
  if(!APP_ON){APP_ON=true;appStart();}
  mineState();return;
 }
 APP_ON=false;$("app").style.display="none";
 if(st.other_user||st.unknown_owner){
  // 설치 정보가 없어 주인을 모르는 자료(내 자료일 수도 있다)는 '다른 사용자의 자료'라고 말하지 않는다
  roShow(st.unknown_owner?"누구의 자료인지 확인할 수 없습니다":"다른 사용자의 자료입니다",
   (d.other_user_msg||"다른 사용자의 자료입니다 — 열지 않고 지웁니다")
   +(st.unknown_owner?" — 이 폴더에 설치 정보 없이 남은 자료가 있습니다. 열지 않고 지운 뒤 다시 시작합니다."
    :" — 이 폴더의 자료는 지금 Windows 계정의 것이 아닙니다. 열지 않고 지운 뒤 다시 시작합니다."),"","",true,false);
  return;
 }
 // 모두 지우기가 끝나지 않았다 — 지금 지우는 중이면 기다리게 하고, 지난번에 마치지 못한 것이면 다시 누를 수 있게 한다.
 // 아직 남은 것: 서버에서 못 지운 공유(다음 시작 때 다시 지운다)와 지우지 못한 Copilot 채팅 수
 RO_NOW=!!d.wiping_now||WIPING;
 roShow(d.wiping_msg||"자료를 지우는 중입니다",
  RO_NOW?"지금 지우고 있습니다 — 끝날 때까지 창을 닫지 마세요."
   :"지난번 모두 지우기를 아직 마치지 못했습니다 — 다음에 시작할 때 마저 지웁니다. 지금 지우려면 [모두 지우기(서버 사본 포함)]를 누를 수 있습니다.",
  [pendingLine(d.pending),d.chats_line||""].filter(Boolean).join(" · "),(d.contact&&d.contact.line)||"",false,!RO_NOW);
}
$("ro_wipe").onclick=async()=>{
 const unk=!!(CONSENT&&CONSENT.state&&CONSENT.state.unknown_owner);
 if(!confirm("이 폴더의 자료("+(unk?"주인을 확인할 수 없는 것":"다른 사용자의 것")+")를 열지 않고 모두 지웁니다."+NL+"조직장 서버에 보낸 공유가 있으면 서버에서도 지웁니다. 계속할까요?"))return;
 $("ro_wipe").disabled=true;$("ro_msg").textContent="지우는 중…";
 const d=await api("/api/purge",{body:{scope:"all"}});
 $("ro_wipe").disabled=false;
 $("ro_msg").textContent=d.ok?"":busyText(d,d.error||"지우지 못했습니다");
 // 곧 화면이 바뀐다 — 결과(서버 사본을 지웠는지·못 지운 것)를 맨 위에 남긴다
 if(d.ok)addNotice("info",(d.msg||`지웠습니다 — ${num(d.deleted)}개`)+(d.n_errors?` · 못 지운 것 ${num(d.n_errors)}개(다른 프로그램이 열고 있음 — 닫고 다시)`:""));
 await consentLoad();
};
// 모두 지운 뒤에도 서버에 남은 사본(다음 시작 때 다시 지운다) — 서버 보관기한이 지나면 서버가 지운다
function pendingLine(p){
 p=Array.isArray(p)?p:[];if(!p.length)return "";
 const exp=p.map(x=>String(x.expires||"")).filter(Boolean).sort().pop()||"";
 return `조직장 서버에서 아직 지우지 못한 공유 ${p.length}건 — 다음에 시작할 때 다시 지웁니다${exp?` (서버 보관기한 ${exp} 에 자동 삭제)`:""}`;
}
// [모두 지우기(서버 사본 포함)] — 조직장 서버의 사본 → 이 도구가 연 Copilot 채팅 → 이 PC 의 자료·설치 정보. 끝나면 결과(무엇을
// 지웠고 무엇이 남았나)를 맨 위에 남기고 처음 설치한 상태로 이어 간다. 지난번에 마치지 못한 지우기도 이 단추로 다시 한다
async function wipeAll(msgEl){
 if(WIPING)return;
 if(!confirm("모두 지웁니다."+NL+NL+"· 조직장 서버에 보낸 공유를 먼저 지웁니다"+NL+"· 이 도구가 연 Copilot 채팅을 지웁니다"+NL+"· 이 PC 의 모은 자료·결과·설치 정보를 모두 지웁니다"+NL+NL+"계속할까요?"))return;
 WIPING=true;msgEl.textContent="지우는 중…";
 let d={};
 try{const c=await api("/api/consent",{quiet:true});
  d=await api("/api/consent/withdraw",{body:{nonce:c.nonce}});}
 finally{WIPING=false;}
 if(d._http===409){msgEl.textContent=busyText(d,"작업이 도는 중에는 지우지 않습니다");consentLoad();return;}
 if(!d.ok){msgEl.textContent=d.msg||d.error||"지우지 못했습니다";consentLoad();return;}
 msgEl.textContent="";
 addNotice("info",d.msg||"모두 지웠습니다");window.scrollTo(0,0);
 APP_ON=false;loaded={};shInvalidate();SH.items=[];SH.html="";
 await consentLoad();
}
$("ro_withdraw").onclick=()=>wipeAll($("ro_msg"));
// [안내] — 읽기만 하는 안내(무엇을 읽고 어디에 얼마나 두는지). 이 창에서 누를 것은 [닫기]뿐이다
async function noticeOpen(){
 $("nt_msg").textContent="";$("notice").style.display="";
 const fresh=await api("/api/consent",{quiet:true});
 const d=fresh.ok?fresh:CONSENT;
 if(!d||!d.notice){$("nt_body").innerHTML="";$("nt_msg").textContent=fresh.error||"안내를 불러오지 못했습니다";return;}
 $("nt_body").innerHTML=noticeHTML(d.notice,d.order);
}
$("nt_open").onclick=noticeOpen;
$("nt_close").onclick=()=>{$("notice").style.display="none";};
function addNotice(kind,text){
 const nb=$("notices"),el=document.createElement("div");
 el.className="banner "+(kind==="warn"?"b-warn":"b-info");
 el.innerHTML=esc(text)+' <button class="ghost" style="padding:1px 8px;font-size:11px;margin-left:6px">닫기</button>';
 el.querySelector("button").onclick=()=>el.remove();nb.appendChild(el);
}
// ── 기간(D2) — 서버(core\\period)가 맞춘 값만 쓴다 ──
async function setMonths(m){
 const d=await api("/api/period?months="+m);
 if(!d.ok)return;
 $("from").value=d.from;$("to").value=d.to;
 document.querySelectorAll("[data-m]").forEach(c=>c.classList.toggle("on",c.dataset.m===String(m)));
 $("pnote").textContent=d.rule||"";
}
async function clampInputs(){
 const d=await api("/api/period?from="+encodeURIComponent($("from").value)+"&to="+encodeURIComponent($("to").value));
 if(!d.ok){$("pnote").textContent=d.error||"날짜를 읽지 못했습니다";return;}
 $("from").value=d.from;$("to").value=d.to;
 document.querySelectorAll("[data-m]").forEach(c=>c.classList.remove("on"));
 $("pnote").textContent=d.notice||d.rule||"";
}
document.querySelectorAll("[data-m]").forEach(c=>c.onclick=()=>setMonths(c.dataset.m));
$("from").onchange=clampInputs;$("to").onchange=clampInputs;
// 409 의 사유(hint)를 그대로 보여 준다
function busyText(d,dflt){return (d&&(d.hint||d.msg))||dflt;}
let timer=null, wasRunning=false;
const fmt=x=>x==null?"":(x<60?`${x}초`:(x<3600?`${Math.floor(x/60)}분 ${x%60}초`:`${Math.floor(x/3600)}시간 ${Math.floor(x%3600/60)}분`));
async function poll(){
 const s=await api("/api/status",{quiet:true});
 if(!s||s._http!==200){$("state").textContent="서버 연결 끊김 — 창을 닫고 다시 실행하세요";return;}
 (s.notices||[]).forEach(n=>addNotice(n.kind==="legacy"?"info":"warn",n.text));
 // 폴더가 닫혔거나(다른 창에서 지우기를 시작했다) 다시 열렸으면 상태를 새로 읽는다 — 이 창이 지우는 동안에는 그 끝에서 읽는다
 if(CONSENT&&!WIPING&&((typeof s.consented==="boolean"&&APP_ON!==s.consented)||(RO_NOW&&!s.running)))consentLoad();
 $("log").textContent=(s.log||[]).join(NL)||"…";$("log").scrollTop=$("log").scrollHeight;
 $("step").textContent=s.step||"";
 if(s.running){
  $("prog").style.display="";
  const pct=s.total?Math.round(s.done/s.total*100):null;
  $("pg_bar").style.width=(pct==null?8:pct)+"%";
  $("pg_bar").style.background=pct==null?"#c9cfd8":"#2a78d6";
  const coolPh=s.phase==="Copilot 대기";
  $("pg_label").textContent=coolPh?"Copilot 대기 중(사용량 제한 — 쉬었다 이어 보냄)"
   :(s.phase?`${s.phase} ${s.done}/${s.total}${pct!=null?` (${pct}%)`:""}`:(s.step||"준비 중…"));
  $("pg_time").textContent=`경과 ${fmt(s.elapsed)}`+(s.eta!=null?` · 남은 시간 약 ${fmt(s.eta)}`:"");
  const aiPhase=s.phase&&/^(AI|워크플로우|Agentic)/.test(s.phase);
  const idle=(s.idle==null?null:s.idle);
  $("pg_hint").textContent=coolPh?"Copilot 이 잠시 응답을 제한해 1~2분 쉬었다가 같은 묶음을 다시 보냅니다. 창을 닫지 말고 두세요 — 이미 판정한 것은 저장돼 있습니다."
   :!aiPhase?""
   :("Copilot 왕복 한 번에 1~15분 걸립니다."+(idle!=null?` 마지막 소식 ${fmt(idle)} 전 —`:"")
     +(idle!=null&&idle>=120?" 아직 끊지 않았습니다(무출력이 계속되면 자동 중단합니다).":" 진행 중입니다.")
     +" 창을 닫지 말고 두세요 · 멈추려면 [중지].");
  $("pg_hint").style.color=(idle!=null&&idle>=120)?"#c0122f":"";
 }else{$("prog").style.display="none";}
 $("sb_dot").style.background=s.running?"#e08a00":"#4fc47f";
 $("sb_state").textContent=s.running?(s.step||"실행 중"):"대기";
 if(s.running&&s.total){
  $("sb_prog").style.display="inline-flex";
  $("sb_phase").textContent=s.phase==="Copilot 대기"?"Copilot 대기 중(사용량 제한)":`${s.phase||""} ${s.done}/${s.total}`;
  $("sb_bar").style.width=Math.round(s.done/s.total*100)+"%";
  $("sb_eta").textContent=(s.eta!=null?`남은 약 ${fmt(s.eta)}`:`경과 ${fmt(s.elapsed)}`);
 }else if(s.running){
  $("sb_prog").style.display="inline-flex";$("sb_phase").textContent="준비 중";$("sb_bar").style.width="8%";
  $("sb_eta").textContent=`경과 ${fmt(s.elapsed)}`;
 }else{$("sb_prog").style.display="none";}
 $("sb_last").textContent=s.last_run?`마지막 분석 ${s.last_run} (${s.last_tag})`:"분석 결과 없음";
 $("sb_ver").textContent=s.version||"";
 const busy=!!s.running;
 ["go","owa","cvreset","chatsweep","report","mi_expired","mi_all","mi_withdraw","ro_withdraw","ro_wipe","sh_send","sh_wd","sh_prev"].forEach(id=>{const b=$(id);if(b){
  if(busy){b.dataset.busy="1";b.disabled=true;}else if(b.dataset.busy){delete b.dataset.busy;b.disabled=(id==="sh_send")?!SH.ready:false;}}});
 $("stop").style.display=busy?"":"none";
 leaveGuard(busy);
 $("state").textContent=busy?"실행 중…":"대기 중";
 if(busy)$("dlog").open=true;
 if(!busy&&timer){clearInterval(timer);timer=null;}
 if(wasRunning&&!busy&&APP_ON){loaded={};refreshDash();cvLoad();loadTab(curTab);}
 wasRunning=busy;
}
// ── 상단 단추 ──
$("go").onclick=async()=>{
 const b={from:$("from").value,to:$("to").value,ai:$("ai").checked,skip:$("skip").checked};
 const d=await api("/api/run",{body:b});
 if(d._http===409){alert(busyText(d,"이미 실행 중입니다"));return;}
 if(!d.ok){alert(d.error||"시작하지 못했습니다");return;}
 $("from").value=d.from;$("to").value=d.to;if(d.notice)$("pnote").textContent=d.notice;
 $("go").disabled=true;if(!timer)timer=setInterval(poll,1000);poll();
};
$("stop").onclick=async()=>{
 if(!confirm("실행 중인 작업을 멈출까요? 지금까지의 결과는 남습니다."))return;
 $("stop").disabled=true;await api("/api/stop",{body:{}});$("stop").disabled=false;$("stop").style.display="none";
 if(timer){clearInterval(timer);timer=null;}poll();
};
$("owa").onclick=async()=>{
 const f=$("from").value,t=$("to").value;
 if(!confirm("Outlook 웹을 전용 Edge 창으로 열어 내 메일·일정 목록을 읽습니다."+NL+"처음이면 그 창에서 회사 계정을 한 번 선택·로그인해야 합니다."+NL+NL+"기간: "+f+" ~ "+t+NL+"계속할까요?"))return;
 $("owa").disabled=true;$("state").textContent="Outlook 웹 읽는 중… (수 분)";if(!timer)timer=setInterval(poll,1000);
 const d=await api("/api/owa",{body:{from:f,to:t}});
 $("owa").disabled=false;$("state").textContent="대기 중";
 if(d._http===409){alert(busyText(d,"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요"));return;}
 if(d.rc===2){alert("로그인이 필요합니다."+NL+"지금 열린 전용 Edge 창에서 회사 계정을 선택·로그인한 뒤 [Outlook 웹 읽기]를 다시 누르세요.");return;}
 alert((d.ok?"읽기 완료 — ":"읽기 일부 실패 — ")+(d.summary||d.error||"")+NL+NL+"[다시 읽지 않고 분석만]으로 분석하면 반영됩니다.");
 cvLoad();
};
$("diag").onclick=async()=>{
 $("diag").disabled=true;$("state").textContent="AI 연결 진단 중… (최대 몇 분)";
 const d=await api("/api/diag",{body:{}});
 $("diag").disabled=false;$("state").textContent="대기 중";
 const L=[];
 L.push(d.ok?"Copilot 왕복 성공 — AI 분석을 쓸 수 있습니다":"Copilot 왕복 실패");
 if(d.phase)L.push("단계: "+d.phase);
 if(d.error)L.push("오류: "+d.error);
 if(d.hint)L.push("조치: "+d.hint);
 if(d.model)L.push("모델: "+d.model);
 if(d.chats)L.push("Copilot 채팅 정리: "+d.chats);
 if(!d.ok)L.push(NL+"대개는 전용 Edge 창에서 회사 계정으로 다시 로그인하면 해결됩니다.");
 alert(L.join(NL));
};
$("cdiag").onclick=async()=>{
 $("cdiag").disabled=true;$("state").textContent="수집 진단 중… (최대 몇 분)";
 const d=await api("/api/collectdiag",{body:{}});
 $("cdiag").disabled=false;$("state").textContent="대기 중";
 if(!d.ok){alert("수집 진단 실패 — "+(d.error||""));return;}
 alert("수집 진단 결과 (report 폴더의 collect_diag.txt — 메일 내용은 가립니다)"+NL+NL+((d.verdict||[]).join(NL)||"판정 없음"));
};
$("chatsweep").onclick=async()=>{
 if(!confirm("이 도구가 열고 기록해 둔 Copilot 채팅만 대화 목록에서 지웁니다(최대 5분)."+NL+"사람이 쓰던 채팅과 기록에 없는 채팅은 건드리지 않습니다."+NL+NL+"계속할까요?"))return;
 const b=$("chatsweep");b.disabled=true;$("state").textContent="Copilot 채팅 지우는 중… (최대 5분)";
 if(!timer)timer=setInterval(poll,1000);
 const d=await api("/api/chat_sweep",{body:{}});
 b.disabled=false;$("state").textContent="대기 중";
 if(d._http===409){alert(busyText(d,"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요"));return;}
 if(d.line){window.__chatBtn=d.line;const el=$("chatline");el.textContent=d.line;el.style.display="";}
 alert((d.line||"Copilot 채팅 지우기를 마치지 못했습니다 — 진행 로그를 확인하세요")+(d.note?NL+NL+d.note:""));
};
$("report").onclick=async()=>{
 $("report").disabled=true;$("state").textContent="내 리포트 만드는 중…";
 const d=await api("/api/report",{body:{}});
 $("report").disabled=false;$("state").textContent="대기 중";
 if(d.ok){
  if(confirm("내 리포트를 만들었습니다 — 이 파일은 PC 밖으로 보내지 않습니다(공유는 [공유] 탭에서만)."+NL+NL+(d.files||[]).join(NL)+NL+NL+"결과 폴더를 열까요?"))
   api("/api/openfolder",{body:{}});
 }else alert(d.error==="no result"?"분석 결과가 없습니다 — 먼저 [분석 실행]":(d._http===409?busyText(d,"다른 작업이 도는 중입니다"):"리포트를 만들지 못했습니다"+(d.hint?" — "+d.hint:"")));
};
$("openf").onclick=()=>api("/api/openfolder",{body:{}});
$("quit").onclick=async()=>{if(!confirm("서버를 종료할까요?"))return;const d=await api("/api/quit",{body:{}});
 if(d._http===409){alert(busyText(d,"작업이 끝난 뒤 다시 누르세요"));return;}
 document.body.innerHTML="<p style='font-family:sans-serif;padding:40px'>종료되었습니다. 창을 닫으세요.</p>";};
// ── 탭 ──
let loaded={}, curTab="agentic";
function loadTab(id){
 const fail=(k,e)=>{loaded[k]=0;const el=$("rv-"+k);
  if(el)el.innerHTML='<div class="card"><div class="note">표시 실패('+esc(String(e&&e.message||e))+') — 탭을 다시 누르면 다시 읽습니다.</div></div>';};
 const fn={agentic:loadAgentic,flow:loadFlow,tax:loadTax,collect:loadCollect,share:loadShare,mine:loadMine}[id];
 if(fn&&!loaded[id]){loaded[id]=1;fn().catch(e=>fail(id,e));}
}
document.querySelectorAll("#tabs [data-t]").forEach(c=>c.onclick=()=>{
 document.querySelectorAll("#tabs [data-t]").forEach(x=>x.classList.toggle("on",x===c));
 document.querySelectorAll(".tab").forEach(t=>t.style.display="none");
 curTab=c.dataset.t;$("tab-"+curTab).style.display="";
 if(curTab==="share"||curTab==="mine")loaded[curTab]=0;
 loadTab(curTab);
});
// 화면 작업(Agentic AI 후보 발굴·워크플로우)은 서버 스레드에서 돈다 — 끝날 때까지 /api/status 를 보며 기다린다
async function waitIdle(){
 for(;;){await new Promise(r=>setTimeout(r,2000));
  const s=await api("/api/status",{quiet:true});if(!s||!s.running)return;}
}
function manualLine(m){
 if(!m)return "";
 const when=m.at?` (${esc(m.at)}${m.sec!=null?` · ${m.sec}초`:""})`:"";
 if(m.ok){const extra=[];if(m.failed_chunks)extra.push(`${m.failed_chunks}/${m.chunks||"?"} 묶음 실패`);
  if(m.salvaged_chunks)extra.push(`잘린 답 복구 ${m.salvaged_chunks}묶음`);if(m.note)extra.push(esc(m.note));
  return `<div class="note" style="margin-top:6px">최근 화면 실행${when}: 완료${extra.length?" — "+extra.join(" · "):""}</div>`;}
 return `<div class="note" style="margin-top:6px;color:#c0122f"><b>최근 화면 실행${when}: 실패</b> — ${esc(String(m.error||""))}${m.hint?`<br>→ ${esc(String(m.hint))}`:""}</div>`;
}
async function startTool(path){
 const d=await api(path,{body:{}});
 if(d._http===409)return {ok:false,busy:true,error:"다른 작업 실행 중",hint:d.hint||""};
 return d;
}
function whyEmpty(kind,redo){
 const b=redo||"위 단추";
 return {
  stalled:` — <b>정체로 중단</b>됐습니다. [AI 연결 진단]으로 Copilot 창 상태를 확인한 뒤 ${b}으로 남은 것만 이어서 하세요.`,
  budget:` — <b>시간 예산</b>에 닿아 남은 묶음을 보내지 않았습니다. ${b}을 누르면 남은 것만 이어서 합니다.`,
  skipped:` — 앞 단계(AI 판정) 실패로 <b>건너뛰었습니다</b>. 판정을 먼저 성공시킨 뒤 ${b}을 누르세요.`,
  failed:` — 왕복이 실패했습니다(위 사유). [AI 연결 진단] 확인 후 ${b}.`,
  throttle:` — <b>Copilot 사용량 제한</b>으로 멈췄습니다. 1~2시간 뒤 ${b} — 이미 한 것은 이어서 씁니다.`,
  gate:` — 개인정보 관문에 걸린 업무는 보내지 않았습니다 — <b>조치 불필요</b>.`,
  ok:` — 최근 실행은 정상 완료로 기록돼 있습니다. 결과가 안 보이면 <b>화면이 보는 기간과 결과 기간이 다른</b> 경우입니다.`,
  none:""
 }[kind||"none"]||"";
}
// ── 판정 배너·스텁 배너(/api/dash) ──
let DASH=null;
async function refreshDash(){
 const d=await api("/api/dash");if(d._http!==200)return;DASH=d;
 const sb=$("stub_banner");
 if(d.stub||d.stub_env){sb.style.display="";sb.innerHTML="<b>시험용 가짜 Copilot 응답(AF32_COPILOT_STUB)으로 판정한 결과입니다</b> — 실제 판정이 아닙니다."+(d.stub_note?" ("+esc(d.stub_note)+")":"");}
 else sb.style.display="none";
 const jw=$("judged_warn");
 if(d.rows&&d.rows.length&&!d.judged){
  const is=d.judged_issues||{};
  jw.style.display="";
  jw.innerHTML=is.reextracted?`<b>${esc(is.reason||"판정 이후 재추출됨")}</b> — 지금 보이는 업무 분류는 규칙 결과입니다. [분석 실행](AI 분석 포함)으로 다시 판정하세요.`
   :"<b>AI 판정 전(또는 실패)</b> — 지금 보이는 업무 이름은 규칙이 임시로 뽑은 것입니다. [분석 실행]에서 <b>AI 분석</b>을 켜고 다시 돌리세요."
    +(is.abort_reason?` <span class="dim">(${esc(is.abort_reason)})</span>`:"");
 }else jw.style.display="none";
}
// ── Agentic AI 후보 탭 ──
function agCarry(a,pend){
 if(!a)return "";
 const STOP_KO={budget:"시간 예산에 닿음 — [이어서 발굴]",throttle:"Copilot 사용량 제한 — 1~2시간 뒤 [이어서 발굴]",
  login:"Copilot 로그인 만료 — [AI 연결 진단]에서 다시 로그인한 뒤 [이어서 발굴]",fatal:"사람이 손대야 풀리는 상태 — 아래 사유 확인",
  fail:"왕복 실패 — [AI 연결 진단] 확인 후 [이어서 발굴]",gate:"개인정보 관문 — 조치 불필요"};
 let h="";
 if(a.carried_from)h+=`<div class="note" style="color:#8a5a00"><b>${esc(a.carried_from)}</b> 기간 결과를 이어받음${a.matched_since?` (발굴 시작 ${esc(a.matched_since)})`:""}</div>`;
 if(pend&&STOP_KO[a.stop_kind])h+=`<div class="note">멈춘 이유: ${STOP_KO[a.stop_kind]}${a.cooldowns?` · Copilot 대기 ${num(a.cooldowns)}회`:""}</div>`;
 return h;
}
async function loadAgentic(){
 const el=$("rv-agentic");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await api("/api/agentic");
 const a=d.analysis||null;
 const pend=a&&a.rows_pending?a.rows_pending:0;
 const news=(a&&a.new)||[];
 let h=`<div class="card"><h2>Agentic AI 전환 후보 <span class="state">[분석 실행](AI 분석) 뒤 자동으로 찾습니다</span></h2>
  <div class="note" style="margin:0 0 8px">내 반복 업무에서 Agentic AI 로 바꿀 만한 업무를 찾습니다. 사람을 평가하는 데 쓰지 않습니다.</div>
  <div class="row" style="margin-bottom:8px">
   <button class="${a?"ghost":"run"}" id="agrun" style="padding:7px 18px;font-size:12.5px">${pend?`이어서 발굴(남은 ${pend}행)`:"후보 발굴 실행"}</button>
   <span class="state" id="agmsg">${d.running?"후보 발굴 진행 중… (진행률은 상단 진행 바)":"묶음마다 Copilot 왕복 1회 — 수십 초~수 분"}</span>
  </div>${d.file_error?`<div class="note" style="color:#c0122f">${esc(d.file_error)}</div>`:""}${manualLine(d.manual)}`;
 if(!a){const stBits=[d.stage_reason,d.stage_error].filter((x,i,arr)=>x&&arr.indexOf(x)===i);
  if(stBits.length)h+=`<div class="note" style="color:#c0122f">최근 실행이 남긴 사유: ${stBits.map(x=>esc(x)).join(" · ")}</div>`;
  h+=`<div class="note">아직 후보 결과가 없습니다${d.tag?` (기간 ${esc(d.tag)})`:""}${d.other_tag?` — <b>${esc(d.other_tag)}</b> 기간 결과는 있습니다`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""}${whyEmpty(d.stage_kind,"[후보 발굴 실행]")} — [분석 실행](AI 분석 포함)을 돌리면 자동으로 만들어집니다.</div></div>`;}
 else{
  const lastErr=a.last_error&&a.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(a.last_error.error)}${a.last_error.hint?` — ${esc(a.last_error.hint)}`:""}</div>`:"";
  h+=`<div class="note">기간 ${esc(a.tag)} · 업무 ${num(a.rows_analyzed)}행 분석${a.chunks?` · 묶음 ${a.chunks}회`:""}${a.failed_chunks?` <span style="color:#c0122f">· ${a.failed_chunks}/${a.chunks||"?"} 묶음 실패</span>`:""}${pend?` <span style="color:#c0122f">· ${pend}행 미판정 — 위 단추로 남은 행만 이어서 발굴</span>`:""}${!news.length&&!pend?` · <b>근거가 충분한 후보가 없습니다(실패 아님)</b>`:""}</div>`
   +(a.rule_rows?`<div class="note">AI 판정 대기 ${num(a.rule_rows)}행 — 근거 대부분이 규칙 판정이라 아직 보내지 않았습니다</div>`:"")
   +(a.gate_skipped_rows?`<div class="note">개인정보 관문 ${num(a.gate_skipped_rows)}행 — 보내지 않았습니다(조치 불필요)</div>`:"")
   +agCarry(a,pend)+lastErr
   +(d.reextracted?`<div class="note" style="color:#8a5a00"><b>${esc(d.reextracted_title||"재추출 이후 결과")}</b> — ${esc(d.reextracted_note||"")}</div>`:"")+`</div>`;
  h+=`<div class="card"><h2>전환 후보 ${news.length}건 <span class="state">근거가 많은 후보부터 · 근거 N건 = 이 후보의 근거가 된 내 업무의 근거 수</span></h2>`;
  if(news.length){news.forEach(n=>{
   const ws=n.work||[];
   h+=`<div style="border-left:3px solid #6c4fb8;padding:4px 0 4px 12px;margin:10px 0">
    <b>${esc(n.name)}</b>${n.task_type?` <span class="tag" style="border-left:3px solid ${WTCOL[n.task_type]||"#98a0a8"}">${esc(n.task_type)}</span>`:""}${n.evidence_rows!=null?` <span class="state">근거 ${num(n.evidence_rows)}건</span>`:""}
    ${n.logic?`<div style="font-size:12px;margin-top:3px"><b>동작 로직:</b> ${esc(n.logic)}</div>`:""}
    ${n.reason?`<div style="font-size:11.5px;color:#5a626b;margin-top:2px"><b>발굴 사유:</b> ${esc(n.reason)}</div>`:""}
    ${ws.length?`<div style="margin-top:4px">${ws.slice(0,12).map(w=>`<span class="tag">${esc(w)}</span>`).join("")}${ws.length>12?` <span class="state">외 ${ws.length-12}건</span>`:""}</div>`:""}</div>`;});}
  else h+=`<div class="note">근거가 충분한 후보가 없습니다 — 근거가 쌓일수록 발굴이 정확해집니다.</div>`;
  h+=`</div>`;
 }
 el.innerHTML=h;
 const btn=$("agrun");
 if(btn)btn.onclick=async()=>{
  btn.disabled=true;btn.textContent="시작 중…";
  const r=await startTool("/api/agentic");
  if(!r.ok||!r.started){btn.disabled=false;btn.textContent="후보 발굴 실행";
   const m=$("agmsg");if(m)m.innerHTML='<span style="color:#c0122f">실패: '+esc(String(r.error||""))+(r.hint?" — "+esc(String(r.hint)):"")+'</span>';return;}
  btn.textContent="발굴 중…";
  const m=$("agmsg");if(m)m.textContent="후보 발굴 중… (묶음마다 수십 초~수 분 · 진행률은 상단 진행 바)";
  if(!timer)timer=setInterval(poll,1000);poll();
  await waitIdle();loaded.agentic=0;loadAgentic();
 };
 if(d.running&&btn){btn.disabled=true;btn.textContent="발굴 중…";waitIdle().then(()=>{loaded.agentic=0;loadAgentic();});}
}
// ── 워크플로우 탭 ──
const fold2=s=>String(s||"").normalize("NFKC").replace(/[·・ㆍ‧/_\\-()\\[\\]（）]/g," ").split(/\\s+/).filter(Boolean).join(" ").toLowerCase();
function mixedLine(mx){
 if(!mx||!mx.length)return "";
 const rows=mx.map(m=>{const v=(m.votes||[]).map(([k,w])=>`${esc(k)} ${num(w).toFixed(2)}`).join(" · ");
  return `<tr><td><b>${esc(m.model)}</b>${m.detail?` <span class="dim">/ ${esc(m.detail)}</span>`:""}</td><td class="dim">${v}</td></tr>`;}).join("");
 return '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:#8a5a00">'
  +`상위(업무 성격)가 갈린 과제 ${mx.length}건 — 다시 나눌 필요</summary>`
  +'<table style="width:100%;font-size:12px;margin-top:6px">'+rows+'</table>'
  +'<div class="note">1위 표가 60%에 못 미쳐 상위를 정하지 않았습니다. 서로 다른 성격의 일이 한 과제로 묶였다면 [분리]로 나누고, '
  +'과제는 맞는데 상위만 갈린 것이라면 config 폴더 projects.json 의 그 과제에 "level1" 을 적어 정하세요.</div></details>';
}
function mergeLine(m){
 if(!m)return "";
 const np=(m.pairs||[]).length, nd=(m.flow_dupes||[]).length, nr=(m.rejects||[]).length, na=(m.ask||[]).length;
 if(!np&&!nd&&!nr&&!na)return "";
 const rows=(m.pairs||[]).map(p=>`<tr><td>${esc(p.from)}</td><td style="color:#8b929b">→</td><td><b>${esc(p.to)}</b></td>`
  +`<td class="dim">${esc(p.why||"")}</td><td style="text-align:right" class="dim">근거 ${num(p.signals)}</td>`
  +`<td style="text-align:right"><button class="ghost" style="padding:1px 8px;font-size:11px" data-a="${esc(p.from)}" data-b="${esc(p.to)}" `
  +`onclick="projSplit(this)" title="두 과제를 다시 합치지 않게 적습니다 — 다음 [워크플로우 재분석]부터 따로 보입니다">분리</button></td></tr>`).join("");
 const dups=(m.flow_dupes||[]).map(x=>`<tr><td colspan="3">${esc(x.kept)}</td><td class="dim">${esc(x.why||"")}</td><td colspan="2" style="text-align:right" class="dim">`
  +`단계 ${(x.steps||[0,0])[0]}개 유지 · ${(x.steps||[0,0])[1]}개 버림</td></tr>`).join("");
 const rej=(m.rejects||[]).map(r=>`<tr><td colspan="3">${esc(r.a)} ↔ ${esc(r.b)}</td><td colspan="3" class="dim">${esc(r.why||"")}</td></tr>`).join("");
 const ask=(m.ask||[]).map(r=>`<tr><td colspan="3">${esc(r.a)} ↔ ${esc(r.b)}</td><td colspan="3" class="dim">${esc(r.why||"")}</td></tr>`).join("");
 return '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:#4a5159">'
  +`이름 병합 ${np}건 · 흐름 중복 제거 ${nd}건${nr?` <span class="dim">(합치지 않은 것 ${nr}건)</span>`:""}${na?` <span class="dim">· 확인이 필요한 것 ${na}건</span>`:""}`
  +'</summary><table style="width:100%;font-size:12px;margin-top:6px">'
  +(rows?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal">합친 과제 이름</th></tr>'+rows:"")
  +(dups?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal">중복으로 지운 흐름</th></tr>'+dups:"")
  +(ask?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal">확인이 필요한 것 — 이름이 달라 합치지 않았습니다</th></tr>'+ask:"")
  +(rej?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal">합치지 않은 것</th></tr>'+rej:"")
  +'</table><div class="note">잘못 합쳐졌으면 그 줄의 <b>[분리]</b>를 누르세요 — 다음 [워크플로우 재분석]부터 따로 보입니다.</div></details>';
}
async function projSplit(b){
 const a=b.getAttribute("data-a")||"", c=b.getAttribute("data-b")||"";
 if(!a||!c)return;
 if(!confirm(`'${a}' 와(과) '${c}' 를 나눕니다 — 다시 합치지 않게 적고, 다음 [워크플로우 재분석]부터 따로 보입니다. 나눌까요?`))return;
 b.disabled=true;
 const d=await api("/api/project_split",{body:{a:a,b:c}});
 if(d._http===409){alert(busyText(d,"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요"));b.disabled=false;return;}
 if(!d.ok){alert(d.error||"나누지 못했습니다");b.disabled=false;return;}
 b.textContent="나눔";b.title=d.msg||"";
}
async function loadFlow(){
 const el=$("rv-flow");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await api("/api/workflow");
 drawFlow(d);
 if(d.running&&$("flowre"))waitIdle().then(()=>{loaded.flow=0;loadFlow();});
}
function drawFlow(d){
 const el=$("rv-flow");if(!el)return;
 const flows=d.flows||[], nflows=flows.length;
 const partial=d.partial&&d.missing_count?`<span style="color:#c0122f"> · ${d.missing_count}개 업무 미판정 — ${d.resumable?"[이어서 분석]을 누르면 남은 업무만 이어서 판정합니다":"다시 눌러도 같을 수 있습니다(근거가 얕은 업무)"}</span>`:"";
 const lastErr=d.last_error&&d.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(d.last_error.error)}${d.last_error.hint?` — ${esc(d.last_error.hint)}`:""}</div>`:"";
 const ruleN=d.rule_units_count!=null?num(d.rule_units_count):(d.rule_units||[]).length;
 const gateN=d.gate_units_count!=null?num(d.gate_units_count):(d.gate_units||[]).length;
 const extra=(d.carried_from?`<div class="note" style="color:#8a5a00"><b>${esc(d.carried_from)}</b> 결과 ${num(d.carried)}개 이어받음 · 새로 판정 ${num(d.asked_new)}개</div>`:"")
  +(ruleN?`<div class="note">AI 판정 대기 <b>${ruleN}개</b> — 근거 대부분이 규칙 판정이라 묻지 않은 업무입니다</div>`:"")
  +(gateN?`<div class="note">개인정보 관문 <b>${gateN}개</b> — 보내지 않았습니다(조치 불필요)</div>`:"");
 const top='<div class="card"><div class="row" style="align-items:center;gap:10px">'
  +'<button class="ghost" id="flowre">'+(d.partial&&d.missing_count&&d.resumable?"이어서 분석(남은 "+d.missing_count+"개)":"워크플로우 재분석")+'</button>'
  +'<span class="state" id="flowmsg">'+(d.running?"워크플로우 분석 진행 중… (진행률은 상단 진행 바)":(d.generated?esc(`생성 ${d.generated} · ${d.model_name||""}`):""))+'</span></div>'
  +'<div class="note">업무마다 <b>일의 순서 → 단계별 Agent 적용 가능성(상·중·하)</b>을 판정합니다.'+(nflows?` 업무 ${nflows}개`+partial:"")+'</div>'
  +lastErr+extra
  +(d.reextracted?'<div class="note" style="color:#8a5a00"><b>재추출 이후 결과</b> — '+esc(d.reextracted_note||"")+' · [워크플로우 재분석]으로 갱신하세요</div>':"")
  +mergeLine(d.merge2)+mixedLine(d.level1_mixed)+manualLine(d.manual)+'</div>';
 if(!d.ok||!nflows){
  const per=d.tag?`지금 보는 기간(${esc(d.tag)})에는 `:"";
  const oth=d.other_tag?`<br><b>${esc(d.other_tag)}</b> 기간 결과는 있습니다.`:"";
  if(d.ok&&d.empty_reason){
   el.innerHTML=top+`<div class="card"><div class="note">${per}워크플로우로 만들 업무가 없습니다 — ${esc(d.empty_reason)}.</div></div>`;
  }else{
   const stBits=[d.stage_reason,d.stage_error].filter((x,i,a)=>x&&a.indexOf(x)===i);
   const stWhy=stBits.length?`<div class="note" style="color:#c0122f">최근 실행이 남긴 사유: ${stBits.map(x=>esc(x)).join(" · ")}</div>`:"";
   el.innerHTML=top+`<div class="card">${stWhy}<div class="note">${per}워크플로우 분석이 없습니다${d.file_error?` <span style="color:#c0122f">· ${esc(d.file_error)}</span>`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""}${whyEmpty(d.stage_kind,"[워크플로우 재분석]")} — AI 분석을 켜고 [분석 실행]을 돌리면 자동으로 만들어집니다.${oth}</div></div>`;
  }
 }else{
  const L1M=(DASH&&DASH.l1meta)||{};
  const l1c=k=>(L1M[k]&&L1M[k].color)||"#8b929b";
  const FOPEN=window.__flowOpen||(window.__flowOpen=new Set());
  let prevL1=null,prevPj=null,open=0,first={l1:null,pj:null};
  const pkOf=x=>x.pjkey||fold2(x.project||x.model);
  const cards=flows.map((f,fi)=>{
   let head="";
   const cur=f.level1||"", pj=f.project||f.model, pk=pkOf(f), hasDet=!!f.detail;
   if(cur!==prevL1){
    while(open>0){head+="</div></details>";open--;}
    if(first.l1===null)first.l1="l1:"+cur;
    const k="l1:"+cur, nP=new Set(flows.filter(x=>(x.level1||"")===cur).map(pkOf)).size, nF=flows.filter(x=>(x.level1||"")===cur).length;
    const op=(FOPEN.size?FOPEN.has(k):k===first.l1)?" open":"";
    const lab=cur?esc(cur):((f.level1_mix||[]).length?"상위 혼재":"상위 미분류");
    head+=`<details data-k="${esc(k)}"${op} style="margin:14px 0 4px"><summary style="font-size:12.5px;color:#4a5159;padding:6px 10px;background:#f3f5f8;border-radius:6px">`
     +`<b>${lab}</b> <span class="dim">— 과제 ${nP}개 · 업무 ${nF}개</span></summary><div class="body">`;
    open++;prevPj=null;}
   if(hasDet&&pk!==prevPj){
    if(open>1){head+="</div></details>";open--;}
    if(first.pj===null)first.pj="pj:"+pk;
    const k="pj:"+pk, sibs=flows.filter(x=>pkOf(x)===pk&&(x.level1||"")===cur).length;
    const op=(FOPEN.size?FOPEN.has(k):k===first.pj)?" open":"";
    head+=`<details data-k="${esc(k)}"${op} style="margin:8px 0 4px 6px"><summary style="font-size:13px;padding:4px 8px"><b>${esc(pj)}</b> <span class="dim">— 업무 ${sibs}개</span></summary><div class="body">`;
    open++;}
   prevL1=cur;prevPj=pk;
   const steps=(f.steps||[]).map((s,i)=>`<tr><td style="width:26px;text-align:center;color:#8b929b"><b>${esc(s.order||i+1)}</b></td>
     <td style="width:170px"><b>${esc(s.name)}</b>${s.evidence?`<div class="dim" style="font-size:11px">근거 ${esc(s.evidence)}</div>`:""}</td>
     <td>${(s.input||s.output)?`${esc(s.input||"")} <span class="dim">→</span> ${esc(s.output||"")}`:esc(s.desc||"")}</td>
     <td style="width:230px"><span style="display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px;background:${AGENT_C[s.agent]||"#8b929b"}">Agent ${esc(s.agent||"-")}</span>
      ${s.agent_how?`<div style="font-size:11px;color:#4a5159;margin-top:2px">${esc(s.agent_how)}</div>`:""}</td></tr>`).join("");
   const l1b=(!hasDet&&f.level1)?`<span style="display:inline-block;padding:0 7px;border-radius:9px;color:#fff;font-size:11px;background:${l1c(f.level1)};margin-right:6px">${esc(f.level1)}</span>`:"";
   const ttl=hasDet?`<span title="${esc(pj)}">${esc(f.detail)}</span>`:esc(f.model);
   const kc="wf:"+String(f.model||"")+"|"+String(f.branch||"");
   const opc=(FOPEN.size?FOPEN.has(kc):fi===0)?" open":"";
   const nAgent=(f.steps||[]).filter(s=>s.agent==="상").length;
   return head+`<details${opc}${hasDet?' style="margin-left:6px"':''} data-k="${esc(kc)}"><summary>${l1b}${ttl}${f.branch?`<span class="dim"> · ${esc(f.branch)}</span>`:""}
     <span class="state">${f.signals!=null?`근거 ${num(f.signals)}건 · `:""}단계 ${(f.steps||[]).length}개${nAgent?` · Agent 상 ${nAgent}개`:""}</span></summary>
    <div class="body">
    ${(f.upstream||f.downstream)?`<div class="note" style="margin:2px 0 6px">${f.upstream?`← 앞 업무: <b>${esc(String(f.upstream).split(" / ").pop())}</b>`:""}${(f.upstream&&f.downstream)?" · ":""}${f.downstream?`→ 다음 업무: <b>${esc(String(f.downstream).split(" / ").pop())}</b>`:""}</div>`:""}
    ${f.summary?`<div class="note" style="margin-bottom:6px;font-size:12px;color:#4a5159">${esc(f.summary)}</div>`:""}
    <table style="margin-top:6px"><tr><th></th><th>단계</th><th>입력 → 출력</th><th>Agent 적용 가능성</th></tr>${steps}</table>
    </div></details>`;}).join("")+(function(){let s="";while(open>0){s+="</div></details>";open--;}return s;})();
  el.innerHTML=top+cards;
  el.querySelectorAll("details[data-k]").forEach(dt=>dt.addEventListener("toggle",()=>{const k=dt.getAttribute("data-k");
   if(dt.open)FOPEN.add(k);else FOPEN.delete(k);if(!FOPEN.size)FOPEN.add("-");}));
 }
 const rb=$("flowre");
 if(rb)rb.onclick=async()=>{
  rb.disabled=true;$("flowmsg").textContent="워크플로우 판정 시작 중…";
  const r=await startTool("/api/workflow");
  if(!r.ok||!r.started){rb.disabled=false;$("flowmsg").textContent="실패: "+String(r.error||"")+(r.hint?" — "+String(r.hint):"");return;}
  $("flowmsg").textContent="워크플로우 판정 중… (묶음마다 수십 초~수 분 · 진행률은 상단 진행 바)";
  if(!timer)timer=setInterval(poll,1000);poll();
  await waitIdle();loaded.flow=0;loadFlow();
 };
 if(d.running&&rb)rb.disabled=true;
}
// ── 업무 분류 탭 ──
async function loadTax(){
 const el=$("rv-tax");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await api("/api/review?g=all");
 if(!d.levels||!d.levels.length){el.innerHTML='<div class="card"><div class="note">업무 분류가 없습니다 — [분석 실행]을 먼저 돌리세요.</div></div>';return;}
 let h="";
 const en=d.entities;
 if(en&&(en.models||[]).length){
  const disc=new Set(en.discovered||[]);
  h+=`<div class="card"><h2>과제 체계${en.fallback?' <span class="tag" style="background:#fdf3e6;color:#8a5a00">규칙 폴백 체계(임시)</span>':""}${en.reused_from?' <span class="tag">지난 체계 재사용</span>':""} <span class="state">AI 가 목록에서 찾은 과제 — 이 PC 에서만 보입니다</span></h2>
   <table><tr><th>과제</th><th>상위</th><th>식별 키워드</th><th>채택 근거</th></tr>${en.models.map(m=>`<tr><td><b>${esc(m.name)}</b>${disc.has(m.name)?' <span class="tag" style="background:#e6f4ea;color:#0f7a3d">판정 중 발견</span>':""}</td><td>${esc(m.l1||"-")}</td><td class="dim">${(m.match||[]).map(esc).join(", ")||"-"}</td><td class="dim">${esc(m.obs||"")||"-"}</td></tr>`).join("")}</table></div>`;
 }
 const bw=d.by_worktype||{}, bwk=Object.keys(bw).sort((a,b)=>bw[b]-bw[a]);
 const cm=d.common||[];
 if(bwk.length||cm.length){
  h+=`<div class="grid2"><div class="card"><h2>업무 유형별 근거</h2>${bwk.map(k=>`<span class="tag" style="border-left:3px solid ${WTCOL[k]||"#98a0a8"}">${esc(k)} ${num(bw[k])}건</span>`).join("")||'<div class="note">없음</div>'}</div>
   <div class="card"><h2>공통 업무 — 표준화·자동화 후보</h2>${cm.length?`<table><tr><th>업무</th><th>유형</th><th style="width:60px">근거</th></tr>${cm.map(c=>`<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.worktype)}</td><td>${num(c.count)}</td></tr>`).join("")}</table>`:'<div class="note">여러 과제에 걸친 업무가 아직 없습니다</div>'}</div></div>`;
 }
 h+=`<div class="card"><h2>업무 분류 <span class="state">상위 → 과제 → 세부업무 · 근거 = 그 업무로 분류된 메일·회의 근거 수 ${d.file?`· ${esc(d.file)}`:""}</span></h2>`;
 d.levels.forEach(l=>{
  h+=`<div style="margin:12px 0 4px;font-size:13px"><span class="dot" style="background:${esc(l.color)}"></span><b>${esc(l.name)}</b> <span class="state">근거 ${num(l.count)}건 · 과제 ${l.tasks.length}개</span></div>`
   +'<table><tr><th style="width:150px">과제</th><th style="width:170px">세부업무</th><th>상세설명</th><th style="width:70px">유형</th><th style="width:110px">근거</th><th style="width:44px">확신</th><th style="width:52px"></th></tr>';
  l.tasks.forEach(t=>t.details.forEach((x,i)=>{
   h+=`<tr><td>${i===0?`<b>${esc(t.name)}</b><div class="dim" style="font-size:11px">근거 ${num(t.count)}건</div>`:""}</td><td>${esc(x.name)}${x.ax?' <span class="tag" style="background:#efe9fb;color:#5a3ea8">AX</span>':""}</td>`
    +`<td class="dim">${esc(x.desc)}</td><td>${esc(x.worktype)}</td><td>${num(x.count)}건${x.basis?`<div class="dim" style="font-size:11px">${esc(x.basis)}</div>`:""}</td><td>${esc(x.conf)}</td>`
    +`<td><button class="ghost" style="padding:1px 7px;font-size:11px" data-row="${esc(t.name+"/"+x.name)}" title="이 업무의 근거를 분석에서 뺍니다(다음 분석에도 적용)">빼기</button></td></tr>`;}));
  h+="</table>";
 });
 h+='<div class="note">[빼기]는 내 업무가 아닌 것을 분석에서 뺍니다 — 기록은 이 PC 의 data 폴더에만 두고 다음 분석에도 적용합니다.</div></div>';
 el.innerHTML=h;
 el.querySelectorAll("[data-row]").forEach(b=>b.onclick=async()=>{
  const key=b.getAttribute("data-row");
  if(!confirm(`'${key}' 를 분석에서 뺍니다. 계속할까요?`))return;
  b.disabled=true;
  const r=await api("/api/exclude",{body:{row:key}});
  if(r._http===409){alert(busyText(r,"다른 작업이 도는 중입니다"));b.disabled=false;return;}
  if(!r.ok){alert(r.error||"빼지 못했습니다");b.disabled=false;return;}
  loaded.tax=0;loadTax();refreshDash();
 });
}
let PJ=[];
function pjRender(){
 const inp=(i,k,v)=>`<input data-i="${i}" data-k="${k}" value="${esc(v)}" style="width:100%">`;
 $("pjtbl").innerHTML="<tr><th style='width:160px'>과제 이름</th><th style='width:220px'>식별 키워드 (쉼표 구분)</th><th>관련 내용</th><th style='width:40px'></th></tr>"+
  (PJ.length?PJ.map((p,i)=>`<tr><td>${inp(i,"name",p.name)}</td><td>${inp(i,"match",(p.match||[]).join(", "))}</td><td>${inp(i,"desc",p.desc||"")}</td>
   <td><button class="ghost" data-del="${i}" style="padding:3px 8px">✕</button></td></tr>`).join("")
  :"<tr><td colspan=4 class='dim'>지정한 과제가 없습니다 — AI 자동 발견만 씁니다.</td></tr>");
 $("pjtbl").querySelectorAll("input").forEach(el=>el.onchange=()=>{const p=PJ[+el.dataset.i];
  if(el.dataset.k==="match")p.match=el.value.split(",").map(x=>x.trim()).filter(Boolean);else p[el.dataset.k]=el.value.trim();});
 $("pjtbl").querySelectorAll("[data-del]").forEach(b=>b.onclick=()=>{PJ.splice(+b.dataset.del,1);pjRender();});
}
async function pjLoad(){const d=await api("/api/projects");PJ=d.projects||[];pjRender();}
async function pjSave(){const d=await api("/api/projects",{body:{projects:PJ}});PJ=d.projects||PJ;pjRender();return d;}
$("pjadd").onclick=()=>{PJ.push({name:"",match:[],desc:""});pjRender();};
$("pjsave").onclick=async()=>{await pjSave();$("pjmsg").textContent="저장했습니다 — 다음 분석부터 반영합니다";};
$("pjretag").onclick=async()=>{
 await pjSave();$("pjmsg").textContent="재분류 중…";
 const d=await api("/api/retag",{body:{}});
 if(!d.ok){$("pjmsg").textContent=d.error==="no signals"?"분석 결과가 아직 없습니다 — 먼저 [분석 실행]":(d.error==="no projects"?"지정한 과제가 없습니다":(d.error==="not judged"?"AI 판정 전입니다":(d._http===409?busyText(d,"다른 작업이 실행 중입니다"):"재분류 실패")));return;}
 const det=Object.entries(d.by||{}).map(([k,v])=>`${k} ${v}건`).join(" · ");
 $("pjmsg").textContent=d.retagged?`재분류 ${d.retagged}건 (${det})`:"옮길 근거가 없습니다 — 바뀐 것 0건";
 loaded={};refreshDash();loadTab(curTab);};
// ── 수집·제외 현황 탭 ──
const EXCL_KO={private:"비공개·개인 항목",admin:"근태·행방·종일·취소 일정",sensitive:"민감한 내용",identifier:"주민번호·카드·계좌 같은 번호",
 external:"사외 참여자가 있는 메일·회의",external_unknown:"사내인지 확인할 수 없는 메일·회의",restricted:"제한 고객 관련",
 nonwork:"업무 외 항목",bulk:"단체 발송",private_text:"개인 문구",credential:"비밀번호류",duplicate:"중복"};
const CH_KO={com:"Outlook 앱",owa:"Outlook 웹",copilot:"M365 Copilot"};
async function loadCollect(){
 const el=$("rv-collect");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await api("/api/collect_summary");
 const s=d.summary, m=d.run_meta, rs=d.restricted;
 let h='<div class="card"><h2>수집·제외 현황 <span class="state">이 PC 에서만 보입니다 · 공유하지 않습니다</span></h2>';
 // 제한 고객 목록 — 운영 담당이 배포한 목록인지 맞춰 보는 확인 날짜와 지문(파일 sha256 앞 8자). 이름은 보이지 않는다
 if(rs)h+=rs.ok?`<div class="note" style="margin:0 0 8px">제한 고객 목록: 확인한 날 <b>${esc(rs.confirmed)}</b>${rs.age_days!=null?` (${num(rs.age_days)}일 전)`:""} · 지문 <b>${esc(rs.sha8)}</b> — 운영 담당이 알려 준 값과 같은지 확인하세요</div>`
  :`<div class="note" style="margin:0 0 8px;color:#c0122f">${esc(rs.msg||"제한 고객 목록을 읽지 못했습니다 — 분석·공유를 하지 않습니다")}</div>`;
 if(!s&&!m){el.innerHTML=h+'<div class="note">아직 수집 기록이 없습니다 — [분석 실행] 뒤에 생깁니다.</div></div>';cvLoad();return;}
 const per=(s&&s.period)||(m&&m.period)||{};
 h+=`<div style="font-size:12.5px">분석 기간 <b>${esc(per.from||"")} ~ ${esc(per.to||"")}</b>${((s&&s.clamped)||(m&&m.clamped))?' <span class="tag" style="background:#fdf3e6;color:#8a5a00">요청한 기간을 규칙에 맞게 줄였습니다</span>':""}${m&&m.generated?` <span class="state">· 분석 ${esc(m.generated)}</span>`:""}</div>`;
 if(s&&s.channels){
  h+='<table style="margin-top:8px"><tr><th>읽은 곳</th><th style="width:90px">결과</th><th style="width:90px">읽은 항목</th></tr>'
   +Object.keys(s.channels).map(k=>{const c=s.channels[k]||{};const rc=c.rc;
    return `<tr><td>${esc(CH_KO[k]||k)}</td><td>${rc==null?'<span class="dim">쓰지 않음</span>':(rc===0?"정상":`<span style="color:#b54708">코드 ${esc(rc)}</span>`)}</td><td>${num(c.rows)}</td></tr>`;}).join("")+"</table>";
 }
 const kept=(s&&s.kept)||(m&&m.counted)||{};
 h+=`<div class="row" style="margin-top:10px"><span class="tag">받은 메일 ${num(kept.mail_in)}건</span><span class="tag">보낸 메일 ${num(kept.mail_out)}건</span><span class="tag">회의 ${num(kept.meetings)}건</span><span class="state">분석에 쓴 항목</span></div>`;
 const ex=Object.assign({},(m&&m.excluded)||{},(s&&s.excluded)||{});
 const ek=Object.keys(EXCL_KO).filter(k=>k in ex);
 if(ek.length)h+='<table style="margin-top:10px"><tr><th>뺀 까닭</th><th style="width:90px">건수</th></tr>'+ek.map(k=>`<tr><td>${esc(EXCL_KO[k])}</td><td>${num(ex[k])}</td></tr>`).join("")+"</table>";
 if(s&&(s.internal_domains||[]).length)h+=`<div class="note">사내로 본 메일 도메인: ${s.internal_domains.map(esc).join(", ")}</div>`;
 const cw=(m&&m.config_warnings||[]).concat(d.config_warnings||[]).filter((x,i,a)=>x&&a.indexOf(x)===i);
 if(cw.length)h+=`<div class="note" style="color:#8a5a00">설정 경고: ${cw.map(esc).join(" · ")}</div>`;
 h+='<div class="note">뺀 항목은 내용 없이 건수만 남깁니다. 사외 사람이 있거나 사내인지 확인할 수 없는 메일·회의, 비공개·근태·민감한 항목은 읽은 즉시 빼고 저장하지 않습니다.</div></div>';
 el.innerHTML=h;
 cvLoad();
}
async function cvLoad(){
 const el=$("cvbody");if(!el)return;
 const d=await api("/api/collect_status?from="+encodeURIComponent($("from").value)+"&to="+encodeURIComponent($("to").value),{quiet:true});
 if(d._http!==200){el.innerHTML='<div class="note">수집 기록을 읽지 못했습니다</div>';return;}
 const L=d.ledger;let h="";
 if(L){
  const ax=L.axes||{};
  h+='<table><tr><th>항목</th><th>읽음</th><th>0건 확인</th><th>일부</th><th>미관측</th><th>출처</th></tr>';
  Object.keys(ax).forEach(k=>{const a=ax[k];
   h+=`<tr><td><b>${esc(a.label)}</b></td><td>${num(a.ok)}</td><td>${num(a.zero_ok)}</td><td>${num(a.partial)}</td>`
    +`<td${a.unobserved?' style="color:#b54708;font-weight:700"':""}>${num(a.unobserved)}</td><td class="state">${esc((a.srcs||[]).join(" · "))||"–"}</td></tr>`;});
  h+=`</table><div class="note">기간 ${esc(L.period[0])} ~ ${esc(L.period[1])}${L.pc?" · "+esc(L.pc):""}</div>`;
 }else h+='<div class="note">수집 기록이 아직 없습니다 — [분석 실행] 뒤에 생깁니다.</div>';
 const stg=d.stages||[];
 if(stg.length){
  h+='<details style="margin-top:6px"><summary style="padding:6px 10px;font-size:12px">마지막 실행의 수집 단계 결과 ('+stg.length+'단계)</summary><div class="body"><table><tr><th>단계</th><th>rc</th><th>사유</th><th>세부</th></tr>';
  stg.forEach(x=>{h+=`<tr><td>${esc(x.name)}</td><td>${esc(x.rc)}</td><td>${esc(x.reason||"")}</td><td class="state">${esc(Object.entries(x.counts||{}).map(([k,v])=>k+"="+v).join(" · "))}</td></tr>`;});
  h+='</table></div></details>';
 }
 if(d.owa&&d.owa.mail_rows)h+=`<div class="note">Outlook 웹: 메일 ${num(d.owa.mail_rows)}통 중 날짜만 읽힌 것 ${num(d.owa.date_only)}통</div>`;
 el.innerHTML=h;$("cvstate").textContent="확인 "+(d.as_of||"");
}
$("cvrefresh").onclick=()=>{$("cvmsg").textContent="";cvLoad();poll();};
$("cvreset").onclick=async()=>{
 if(!confirm("수집 커서와 날짜별 기록을 초기화합니다."+NL+"다음 [분석 실행]이 기간 전체를 처음부터 다시 읽습니다(모은 자료는 지우지 않습니다). 계속할까요?"))return;
 const r=await api("/api/reset_cursors",{body:{}});
 $("cvmsg").textContent=r.ok?("초기화했습니다 — "+((r.removed||[]).length?r.removed.join(", "):"커서 파일 없음")+(r.ledger?" · 날짜별 기록":"")):("실패: "+busyText(r,r.error||""));
 cvLoad();
};
// ── 공유 탭(D14) ──
const SH={nonce:"",sendNonce:"",checkNonce:"",ready:false,items:[],html:"",addr:{},check:null,tag:"",flags:"",lines:{}};
const partKo=p=>p==="personal"?"개인 리포트":(p==="team"?"익명 팀 집계":String(p||""));
function shLabel(){
 const s=SH.check&&SH.check.server;
 const org=(s&&s.org_label)||"조직장";
 $("sh_personal_l").textContent=`내 개인 리포트를 〈${org}〉에게 공유합니다 (조직장만 열람)`;
 return org;
}
// 상태 줄 — 저장한 주소(이 PC)와 마지막 [연결 확인] 결과만. 탭을 연다고 조직장 서버에 붙지 않는다
function shRender(){
 const a=SH.addr||{}, ck=SH.check, s=ck&&ck.server, t=(ck&&ck.teamup)||{};
 const org=shLabel();
 const tr=String((s&&s.transport)||"").toUpperCase();
 let h="";
 if(!a.host)h+='<div class="note" style="color:#8a5a00">조직장 서버 주소가 없습니다 — AgentFinder32-팀서버주소.bat 으로 조직장이 알려 준 주소와 참여 코드를 저장하세요.</div>';
 else h+=`<div style="font-size:12.5px">서버 <b>${esc(a.url||a.host)}</b>`
  +(!ck?' · <span class="dim">연결 확인 전 — [연결 확인]을 누르면 조직 이름·전송 방식·서버 보관기한을 받아 옵니다</span>'
   :(s?` · 조직 <b>${esc(org)}</b> · 전송 <b>${esc(tr)}</b> · <span style="color:#0f7a3d">연결됨</span>`:' · <span style="color:#c0122f">확인하지 못함</span>'))
  +(a.has_join?"":' · <span style="color:#8a5a00">참여 코드 없음</span>')+"</div>";
 if(ck&&!s)h+=`<div class="note">${esc(ck.check_msg||t.msg||t.code||"조직장 서버를 확인하지 못했습니다")}</div>`;
 (a.warnings||[]).forEach(w=>{h+=`<div class="note" style="color:#8a5a00">${esc(w)}</div>`;});
 if(tr==="HTTP")h+='<div class="note" style="color:#8a5a00">이 서버는 사내망 안에서 암호화하지 않고(HTTP) 받습니다. 개인 리포트는 조직장이 허용한 경우에만 받습니다.</div>';
 if(!SH.tag)h+='<div class="note">분석 결과가 없습니다 — 먼저 [분석 실행]을 돌려야 미리보기를 만들 수 있습니다.</div>';
 $("sh_status").innerHTML=h;
}
async function loadShare(){
 $("sh_status").innerHTML='<div class="note">불러오는 중…</div>';
 const d=await api("/api/share/status");
 SH.nonce=d.nonce||"";SH.addr=d.addr||{};SH.tag=d.tag||"";SH.lines=d.lines||{};
 // 공유 가리기가 지키는 것과 남을 수 있는 것 — 안내문과 같은 문장(서버가 준다)
 $("sh_mask").textContent=[SH.lines.mask,SH.lines.check,SH.lines.flag].filter(Boolean).join(" ");
 const a=SH.addr;
 $("sh_addr").innerHTML=a.host?`서버 <b>${esc(a.url||a.host)}</b> · 참여 코드 `+(a.has_join?`저장됨(${esc(a.join_hint||"")}…)`:'<span style="color:#8a5a00">없음</span>')
  +(a.saved_at?` · 저장한 날 ${esc(String(a.saved_at).slice(0,10))}`:"")
  :'<span style="color:#8a5a00">저장한 주소가 없습니다</span>';
 if(!$("sh_owner").value)$("sh_owner").value=d.owner||"";
 if(!$("sh_func").value)$("sh_func").value=d.function||"";
 shRender();
 const rc=(d.receipts||[]);
 const pend=pendingLine(d.pending);
 $("sh_receipts").innerHTML=(rc.length?'<table><tr><th>보낸 날</th><th>무엇</th><th>서버·조직</th><th>서버 보관기한</th></tr>'
  +rc.map(r=>`<tr><td>${esc(r.sent||r.date||"")}</td><td>${esc((r.parts||[r.part]).map(partKo).join(" · "))}${r.unsure?' <span style="color:#8a5a00">(서버가 받았는지 확인하지 못함 — 거두면 지워집니다)</span>':""}</td><td>${esc(r.server||"")} ${esc(r.org_label||"")}</td><td>${esc(r.expires||r.expiry||"")}</td></tr>`).join("")+"</table>"
  :'<div class="note">보낸 공유가 없습니다.</div>')+(pend?`<div class="note" style="color:#8a5a00">${esc(pend)}</div>`:"");
}
// [연결 확인]·[보내기…] — 조직장 서버에 hello 한 번(teamup --ping). 확인 창은 이 답만 보인다(이 PC 의 설정 값으로 채우지 않는다)
async function shCheck(){
 const d=await api("/api/share/status?check=1");
 if(d.nonce)SH.nonce=d.nonce;
 if(d.addr)SH.addr=d.addr;
 if(d.lines)SH.lines=d.lines;
 SH.check=d.checked?d:{server:null,teamup:{},check_msg:d.msg||d.error||"조직장 서버를 확인하지 못했습니다"};
 shRender();
 return SH.check;
}
$("sh_check").onclick=async()=>{
 $("sh_check").disabled=true;$("sh_cmsg").textContent="조직장 서버에 연결해 보는 중…";
 const ck=await shCheck();
 $("sh_check").disabled=false;
 $("sh_cmsg").textContent=ck.server?"연결했습니다 — 아무것도 보내지 않았습니다":"연결하지 못했습니다 — 아무것도 보내지 않았습니다";
};
function shInvalidate(){SH.ready=false;SH.sendNonce="";SH.checkNonce="";$("sh_send").disabled=true;$("sh_items").innerHTML="";$("sh_frame").style.display="none";$("sh_fnote").style.display="none";$("sh_pmsg").textContent="";}
$("sh_personal").onchange=shInvalidate;$("sh_team").onchange=shInvalidate;$("sh_owner").onchange=shInvalidate;$("sh_func").onchange=shInvalidate;
function shIncluded(){return Array.from($("sh_items").querySelectorAll("input[data-id]")).filter(x=>x.checked).map(x=>x.getAttribute("data-id"));}
// 미리보기 iframe 은 sandbox(스크립트 없음) — 체크를 끈 항목은 data-item-id 가 같은 요소를 빼고 다시 넣는다
function shFrame(){
 const fr=$("sh_frame");
 if(!SH.html){fr.style.display="none";return;}
 const keep=new Set(shIncluded());
 let src=SH.html, mirrored=false;
 try{const doc=new DOMParser().parseFromString(SH.html,"text/html");
  const marks=doc.querySelectorAll("[data-item-id]");
  if(marks.length){mirrored=true;marks.forEach(e=>{if(!keep.has(e.getAttribute("data-item-id")))e.remove();});src="<!doctype html>"+doc.documentElement.outerHTML;}}catch(e){}
 fr.srcdoc=src;fr.style.display="";
 const fn=$("sh_fnote");fn.style.display=mirrored?"none":"";fn.textContent=mirrored?"":"체크를 끈 항목은 보내지 않습니다(이 미리보기에는 모두 보입니다).";
}
$("sh_prev").onclick=async()=>{
 const personal=$("sh_personal").checked, team=$("sh_team").checked;
 shInvalidate();
 if(!personal&&!team){$("sh_pmsg").textContent="보낼 것을 하나 이상 고르세요";return;}
 if(!SH.nonce)await loadShare();
 $("sh_prev").disabled=true;$("sh_pmsg").textContent="미리보기 만드는 중…";
 const d=await api("/api/share/preview",{body:{nonce:SH.nonce,personal:personal,team:team,owner:$("sh_owner").value,function:$("sh_func").value}});
 $("sh_prev").disabled=false;SH.nonce=d.status_nonce||"";
 if(!d.ok){$("sh_pmsg").textContent=d.msg||d.error||"미리보기를 만들지 못했습니다";return;}
 SH.items=d.items||[];SH.html=d.html||"";SH.sendNonce=d.nonce||"";SH.flags=(personal?"p":"")+(team?"t":"");
 const nFlag=SH.items.filter(x=>x.flagged).length;
 $("sh_pmsg").textContent=`보낼 항목 ${SH.items.length}개 — 보내고 싶지 않은 항목은 체크를 끄세요`
  +(nFlag?` · 이름이 남았을 수 있는 항목 ${nFlag}개는 체크를 꺼 두었습니다`:"");
 const kindKo=k=>k==="step"?"워크플로우 단계":(k==="candidate"?"전환 후보":String(k||""));
 // 가린 뒤에도 이름 같은 낱말이 남은 항목(flagged · flag_terms)은 눈에 띄게 표시하고 처음에 체크를 꺼 둔다 — 이 PC 에서만 보인다
 $("sh_items").innerHTML=SH.items.map(x=>{const nm=x.name||x.label||x.title||x.text||x.id;
  const sub=x.kind==="step"?((x.agent?"Agent "+x.agent+(x.agent_how?" — ":""):"")+(x.agent_how||"")):(x.logic||x.reason||"");
  const pl=Array.isArray(x.parts)?x.parts:(x.part?[x.part]:[]);
  const parts=pl.map(partKo).join(" · ");
  const fl=!!x.flagged, ft=(Array.isArray(x.flag_terms)?x.flag_terms:[]).slice(0,8).map(t=>esc(t)).join(", ");
  const can=!Array.isArray(x.parts)||pl.length>0;   // 표시한 후보는 익명 팀 집계에 넣지 않는다 — 갈 갈래가 없으면 고를 수 없다
  return `<label class="item${fl?" flagged":""}"><input type="checkbox" data-id="${esc(x.id)}"${fl?"":" checked"}${can?"":" disabled"}><span>`
   +(fl?'<span class="tag" style="background:#fdf3e6;color:#8a5a00">확인 필요</span>':"")+`<span class="tag">${esc(kindKo(x.kind))}</span>`
   +`${x.task_type?`<span class="tag">${esc(x.task_type)}</span>`:""} <b>${esc(nm)}</b>${parts?` <span class="dim" style="font-size:11px">→ ${esc(parts)}</span>`:""}`
   +`${sub?`<div class="dim" style="font-size:11px">${esc(sub)}</div>`:""}`
   +(fl?`<div style="font-size:11px;color:#8a5a00">가린 뒤에도 이름일 수 있는 낱말이 남았습니다${ft?": "+ft:""} — `
    +(can?"확인하고 보낼 때만 직접 체크하세요 · 익명 팀 집계에는 넣지 않습니다":"익명 팀 집계에는 넣지 않습니다(개인 리포트를 함께 고르면 확인하고 넣을 수 있습니다)")+`</div>`:"")
   +`</span></label>`;}).join("");
 if(d.blocked)$("sh_pmsg").textContent+=` · 민감한 내용이 남아 뺀 항목 ${num(d.blocked)}개`;
 $("sh_items").querySelectorAll("input[data-id]").forEach(c=>c.onchange=()=>{shFrame();$("sh_send").disabled=!shIncluded().length&&SH.items.length>0;});
 shFrame();
 SH.ready=true;$("sh_send").disabled=false;
};
$("sh_send").onclick=async()=>{
 const personal=$("sh_personal").checked, team=$("sh_team").checked;
 if((personal?"p":"")+(team?"t":"")!==SH.flags){$("sh_smsg").textContent="고른 것이 바뀌었습니다 — 미리보기를 다시 만드세요";shInvalidate();return;}
 const inc=shIncluded();
 if(SH.items.length&&!inc.length){$("sh_smsg").textContent="보낼 항목을 하나 이상 고르세요";return;}
 const a=SH.addr||{};
 if(!a.host||!a.has_join){$("sh_smsg").textContent="먼저 위 [조직장 서버 주소]에 조직장이 알려 준 주소와 참여 코드를 저장하세요";return;}
 // 확인 창은 지금 조직장 서버가 답한 값(새 hello)만 보인다 — 받는 서버·조직·전송 방식·서버 보관기한을 모르면 열지 않는다
 $("sh_send").disabled=true;$("sh_smsg").textContent="조직장 서버를 확인하는 중…";
 const ck=await shCheck();
 $("sh_send").disabled=!SH.ready;
 const s=ck.server;
 if(!s||(personal&&!(num(s.serverPersonalDays)>0))||(team&&!(num(s.serverTeamDays)>0))){
  $("sh_smsg").textContent="조직장 서버를 확인하지 못해 확인 창을 열지 않았습니다 — "+(ck.check_msg||"조직·전송 방식·서버 보관기한을 알 수 없습니다")+" (보내지 않았습니다)";
  return;}
 if(team&&!SH.lines.team_file){$("sh_smsg").textContent="확인 창에 보일 안내를 받지 못해 열지 않았습니다 — 다시 누르세요 (보내지 않았습니다)";return;}
 SH.checkNonce=ck.check_nonce||"";$("sh_smsg").textContent="";
 const tr=String(s.transport||"").toUpperCase();
 const nf=SH.items.filter(x=>x.flagged&&inc.indexOf(String(x.id))>=0).length;
 $("cf_body").innerHTML=`<div>받는 서버: <b>${esc(s.server)}</b></div>`
  +`<div>조직: <b>${esc(s.org_label)}</b></div>`
  +`<div>전송 방식: <b>${esc(tr)}</b>${tr==="HTTP"?' <span style="color:#8a5a00">— 사내망 안에서 암호화하지 않고 보냅니다</span>':""}</div>`
  +`<div>보내는 것: <b>${[personal?"개인 리포트(조직장만 열람)":"",team?"익명 팀 집계 기여분(이름 없음)":""].filter(Boolean).join(" · ")}</b> — 고른 항목 ${inc.length}개</div>`
  +(nf?`<div style="color:#8a5a00">이름이 남았을 수 있다고 표시한 항목 ${nf}개를 골랐습니다 — 개인 리포트에만 넣고 익명 팀 집계에는 넣지 않습니다 · 미리보기에서 이름이 없는지 다시 확인하세요</div>`:"")
  +`<div>서버 보관기한: ${personal?`개인 리포트 ${num(s.serverPersonalDays)}일`:""}${personal&&team?" · ":""}${team?`팀 집계 ${num(s.serverTeamDays)}일`:""} 뒤 자동 삭제</div>`
  // 익명 팀 집계 — 인원 기준(조직장 서버가 말한 값)과, 기여분이 조직장 PC 에 남는 꼴(안내문과 같은 문장 · 서버가 준다)
  +(team&&num(s.minGroupSize)>0&&num(s.minCellSize)>0?`<div class="note" style="font-size:12px">익명 팀 집계는 참여 인원이 ${num(s.minGroupSize)}명 이상일 때만 보이고, ${num(s.minCellSize)}명 이상이 낸 후보만 이름이 나옵니다.</div>`:"")
  +(team&&SH.lines.team_file?`<div class="note" style="font-size:12px">${esc(SH.lines.team_file)}</div>`:"")
  +(SH.lines.check?`<div class="note" style="font-size:12px">${esc(SH.lines.check)}</div>`:"")
  +'<div class="note" style="font-size:12px">보낸 뒤에도 [보낸 공유 모두 거두기] 또는 [내 데이터] 탭의 [모두 지우기(서버 사본 포함)]로 서버 사본을 지울 수 있습니다. 보내지 못해도 자동으로 다시 보내지 않습니다.</div>';
 $("confirm").style.display="";
};
$("cf_no").onclick=()=>{$("confirm").style.display="none";};
$("cf_yes").onclick=async()=>{
 $("confirm").style.display="none";
 const personal=$("sh_personal").checked, team=$("sh_team").checked;
 $("sh_send").disabled=true;$("sh_smsg").textContent="보내는 중…";
 const d=await api("/api/share",{body:{nonce:SH.sendNonce,check:SH.checkNonce,include:shIncluded(),personal:personal,team:team,confirm:true}});
 SH.ready=false;SH.sendNonce="";SH.checkNonce="";
 $("sh_smsg").textContent=d.say||(d.ok?("보냈습니다"+(d.msg?" — "+d.msg:"")):("보내지 못했습니다 — "+(d.msg||d.error||d.code||"")+" (자동으로 다시 보내지 않습니다)"));
 loadShare();
};
$("sh_wd").onclick=async()=>{
 if(!confirm("조직장 서버에 보낸 내 개인 리포트와 익명 팀 집계 기여분을 모두 거둡니다(서버에서 지웁니다). 계속할까요?"))return;
 if(!SH.nonce)await loadShare();
 $("sh_wmsg").textContent="거두는 중…";
 const d=await api("/api/share/withdraw",{body:{nonce:SH.nonce,all:true}});
 SH.nonce=d.status_nonce||"";
 $("sh_wmsg").textContent=d.ok?"거뒀습니다":("다 거두지 못했습니다 — "+(d.msg||d.error||"")+" (서버 보관기한이 지나면 자동으로 지워집니다)");
 loadShare();
};
// ── 내 데이터 탭 ──
async function mineState(){
 const d=CONSENT;if(!d)return;
 const st=d.state||{};
 // 내 자료일 때만 이 탭이 보인다 — 마지막으로 모두 지운 날과 그때 지우지 못한 Copilot 채팅이 있으면 함께 말한다
 $("mi_state").textContent="이 폴더의 자료는 지금 Windows 계정의 것입니다."
  +(st.withdrawn_at?` 마지막으로 모두 지운 날 ${st.withdrawn_at}.`:"")+(d.chats_line?` ${d.chats_line}`:"");
 $("mi_paper").textContent=[d.withdraw_line||"",(d.contact&&d.contact.line)||""].filter(Boolean).join(" ");
 $("mi_notice").innerHTML=noticeHTML(d.notice,d.order);
}
async function loadMine(){
 const r=await api("/api/retention");
 const rows=r.table||[];
 $("mi_ret").innerHTML='<tr><th>무엇</th><th>어디</th><th style="width:70px">보관</th><th style="width:60px">파일</th><th style="width:110px">다음 삭제</th></tr>'
  +rows.map(x=>`<tr><td>${esc(x.label)}</td><td class="dim">${esc(x.where)}</td><td>${num(x.days)}일</td><td>${x.files==null?"–":num(x.files)}</td><td>${esc(x.next_delete||"–")}</td></tr>`).join("")
  // 보관기한 없이 모두 지울 때까지 남는 것(전용 Edge 로그인 프로필·공유 영수증)
  +(r.kept||[]).map(x=>`<tr><td>${esc(x.label)}</td><td class="dim">${esc(x.where)}</td><td colspan="3">${esc(x.until||"")} · 파일 ${x.files==null?"–":num(x.files)}개</td></tr>`).join("");
 const ps=r.purge_status;
 // 매일 정리 — 설정·작업 등록 상태와 마지막 자동 정리 결과(못 지운 것·서버에서 아직 못 지운 공유)
 $("mi_task").textContent=(r.scheduled?(r.task===true?"매일 한 번 Windows 작업 스케줄러의 내 사용자 작업이 기한 지난 자료를 지웁니다.":"매일 정리 작업이 등록돼 있지 않습니다 — 화면을 열 때와 분석 시작·끝에 기한 지난 자료를 지웁니다.")
  :(r.task===true?"매일 정리 작업은 설정으로 꺼져 있지만 예전에 만든 작업이 남아 있습니다 — Windows 작업 스케줄러에서 지울 수 있습니다."
   :"매일 정리 작업은 꺼져 있습니다 — 화면을 열 때와 분석 시작·끝에 기한 지난 자료를 지웁니다."))
  +(ps&&ps.date?` 마지막 자동 정리 ${ps.date} — 지운 것 ${num(ps.deleted)}개${num(ps.errors)?` · 못 지운 것 ${num(ps.errors)}개(다음 정리 때 다시 지웁니다)`:""}${num(ps.withdrawal_left)?` · 조직장 서버에서 아직 지우지 못한 공유 ${num(ps.withdrawal_left)}건`:""}.`:"");
 const rc=r.receipts||[], pend=pendingLine(r.pending);
 $("mi_rcpt").innerHTML=(rc.length?`<div class="note">조직장 서버에 보낸 공유 ${rc.length}건 — 서버 보관기한 ${rc.map(x=>esc(x.expires||"?")).join(", ")}</div>`:"")
  +(pend?`<div class="note" style="color:#8a5a00">${esc(pend)}</div>`:"");
 mineState();
}
async function minePurge(scope,msg){
 if(!confirm(msg))return;
 $("mi_msg").textContent="지우는 중…";
 const d=await api("/api/purge",{body:{scope:scope}});
 if(d._http===409){$("mi_msg").textContent=busyText(d,"작업이 도는 중에는 지우지 않습니다");return;}
 $("mi_msg").textContent=d.ok?`지웠습니다 — ${num(d.deleted)}개${d.n_errors?` · 못 지운 것 ${d.n_errors}개(다른 프로그램이 열고 있음 — 닫고 다시)`:""}`:(d.hint||d.error||"지우지 못했습니다");
 loaded={};loadMine();refreshDash();
}
$("mi_expired").onclick=()=>minePurge("expired","보관기한이 지난 자료를 지웁니다. 계속할까요?");
$("mi_all").onclick=()=>minePurge("all_keep_consent","이 PC 의 모은 자료와 분석 결과·리포트를 모두 지웁니다(설치 정보·전용 Edge 로그인·조직장 서버에 보낸 공유는 그대로 둡니다). 계속할까요?");
$("mi_withdraw").onclick=()=>wipeAll($("mi_msg"));
// ── 창을 닫으면 작업도 멈춘다— 10초마다 살아 있다고 알리고, 떠날 때 작별을 보낸다(keepalive fetch) ──
let AF32_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);
function af32Post(path,vis){try{fetch(path,{method:"POST",keepalive:true,cache:"no-store",
 headers:{"Content-Type":"application/json","X-AF32-UI":TOKEN},body:JSON.stringify({id:AF32_TAB,vis:vis||document.visibilityState})}).catch(()=>{});}catch(e){}}
// 떠나거나(pagehide) 멈추기(freeze·알림 창) 직전의 신호는 sendBeacon 으로 — 이때 fetch 는 도착하지 않을 때가 있다(실측).
// sendBeacon 은 머리글을 붙일 수 없어 화면 열쇠를 JSON 본문 "ui" 에 싣는다(서버가 /api/alive·/api/bye 에서만 받는다)
function af32Beacon(path,vis){
 const body=JSON.stringify({id:AF32_TAB,vis:vis||document.visibilityState,ui:TOKEN});
 try{if(navigator.sendBeacon&&navigator.sendBeacon(path,new Blob([body],{type:"application/json"})))return;}catch(e){}
 af32Post(path,vis);
}
// 알림·확인 창이 열려 있는 동안 브라우저는 화면의 타이머를 멈춘다 — 열기 직전에 'dialog' 를 알리고, 닫히면 곧바로 평소 신호를 보낸다
(function(){if(window.__af32Dlg)return;window.__af32Dlg=1;
 ["alert","confirm","prompt"].forEach(function(k){const f0=window[k];if(typeof f0!=="function")return;
  window[k]=function(){try{af32Beacon("/api/alive","dialog");}catch(e){}
   try{return f0.apply(window,arguments);}finally{try{af32Post("/api/alive");}catch(e){}}};});})();
function leaveWarn(e){e.preventDefault();e.returnValue="";return "";}
function leaveGuard(on){if(on===!!window.__af32Guard)return;window.__af32Guard=on;
 if(on)window.addEventListener("beforeunload",leaveWarn);else window.removeEventListener("beforeunload",leaveWarn);}
af32Post("/api/alive");setInterval(()=>af32Post("/api/alive"),10000);
document.addEventListener("visibilitychange",()=>af32Post("/api/alive"));
document.addEventListener("freeze",()=>af32Beacon("/api/alive","frozen"));
document.addEventListener("resume",()=>af32Post("/api/alive"));
window.addEventListener("pageshow",e=>{if(e.persisted){AF32_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);af32Post("/api/alive");}});
window.addEventListener("pagehide",()=>af32Beacon("/api/bye",""));
function appStart(){
 setMonths(3);pjLoad();refreshDash().then(()=>loadTab(curTab));
}
setInterval(()=>{if(!timer)poll();},3000);
consentLoad();poll();
</script>
</body></html>"""



PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; "
            "frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
PAGE_HEADERS = {"Cache-Control": "no-store", "Content-Security-Policy": PAGE_CSP, "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
DOC_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "Content-Security-Policy": "sandbox allow-popups; frame-ancestors 'none'"}
# 닫힌 폴더(다른 사용자의 자료 · 주인을 모르는 자료 · 모두 지우기가 끝나지 않음)에서도 답하는 /api 경로(spec §8 — 상수 이름은
# 예전 그대로). 그 밖의 /api/* 는 그때 403 {"error":"consent_required","reason","msg"}(gate_refusal). 내 자료이고 지우는 중이
# 아니면 처음부터 모든 경로가 열려 있다 — 사람에게 묻는 단계도, 그 답을 받는 경로도 없다.
CONSENT_FREE = frozenset(("/api/consent", "/api/consent/withdraw", "/api/status", "/api/alive",
                          "/api/bye", "/api/quit", "/api/retention", "/api/purge"))
BEACON_PATHS = frozenset(("/api/alive", "/api/bye"))   # 화면 열쇠를 본문 "ui" 로도 받는 경로(sendBeacon — _post_problem)
GET_ROUTES = {
    "/": "_g_index", "/index.html": "_g_index", "/guide": "_g_guide", "/docs": "_g_guide",
    "/api/status": "_g_status", "/api/consent": "_g_consent", "/api/retention": "_g_retention", "/api/period": "_g_period",
    "/api/collect_summary": "_g_collect_summary", "/api/collect_status": "_g_collect_status", "/api/dash": "_g_dash",
    "/api/review": "_g_review", "/api/agentic": "_g_agentic", "/api/workflow": "_g_workflow", "/api/projects": "_g_projects",
    "/api/share/status": "_g_share_status",
}
POST_ROUTES = {
    "/api/alive": "_p_alive", "/api/bye": "_p_bye", "/api/quit": "_p_quit", "/api/stop": "_p_stop",
    "/api/openfolder": "_p_openfolder", "/api/run": "_p_run", "/api/owa": "_p_owa", "/api/chat_sweep": "_p_chat_sweep",
    "/api/diag": "_p_diag", "/api/collectdiag": "_p_collectdiag", "/api/reset_cursors": "_p_reset_cursors",
    "/api/report": "_p_report", "/api/exclude": "_p_exclude", "/api/projects": "_p_projects",
    "/api/project_split": "_p_project_split", "/api/retag": "_p_retag", "/api/agentic": "_p_tool", "/api/workflow": "_p_tool",
    "/api/consent/withdraw": "_p_consent_withdraw",
    "/api/purge": "_p_purge", "/api/share/preview": "_p_share_preview", "/api/share": "_p_share",
    "/api/share/withdraw": "_p_share_withdraw",
}
NONCE_BAD = {"ok": False, "error": "bad_nonce",
             "msg": "화면이 오래되었거나 이미 처리한 요청입니다 — 화면을 새로 고친(F5) 뒤 다시 누르세요"}
PURGE_SCOPES = ("expired", "all_keep_consent", "all")


def blocked_page(msg):
    """시작 검사(install.startup_check)에 걸렸을 때 보이는 화면 — 까닭 한 줄만."""
    t = html.escape(lmname.DISPLAY_TITLE)
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>" + t + "</title></head>"
            "<body style=\"font-family:'Malgun Gothic',sans-serif;background:#f2f4f7;padding:40px\">"
            "<div style='max-width:760px;margin:0 auto;background:#fff;border:1px solid #f0b8c2;border-radius:8px;padding:22px'>"
            "<h2 style='font-size:17px;color:#8a1020'>" + t + " — 시작하지 않았습니다</h2>"
            "<p style='font-size:13.5px;line-height:1.8;margin-top:10px'>" + html.escape(msg) + "</p>"
            "<p style='font-size:12px;color:#8b929b;margin-top:14px'>아무것도 읽거나 지우지 않았습니다. 창을 닫고 안내대로 옮긴 뒤 다시 실행하세요.</p>"
            "</div></body></html>").encode("utf-8")


class H(BaseHTTPRequestHandler):
    server_version = "AF32"
    sys_version = ""

    def log_message(self, *a):
        pass

    # ── 응답·본문 ──────────────────────────────────────────────────────────────────────
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self._sent = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if not (headers and "Cache-Control" in headers):
            self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _drain(self):
        """본문을 읽어 버린다(거절 응답 전에 — 읽지 않은 채 닫으면 브라우저가 응답 대신 끊김을 본다)."""
        if getattr(self, "_drained", False):
            return
        self._drained = True
        try:
            left = min(max(int(self.headers.get("Content-Length", 0) or 0), 0), DRAIN_MAX)
        except ValueError:
            left = 0
        while left > 0:
            chunk = self.rfile.read(min(65536, left))
            if not chunk:
                break
            left -= len(chunk)

    def _body(self):
        """JSON 본문 → dict({} 이면 빈 본문) | None(깨졌거나 dict 가 아니거나 너무 큼 — 응답은 부르는 쪽)."""
        if hasattr(self, "_b"):
            return self._b
        self._b = None
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            n = -1
        if n < 0 or n > BODY_MAX:
            self._drain()
            return None
        self._drained = True
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            b = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except (ValueError, UnicodeDecodeError):
            return None
        self._b = b if isinstance(b, dict) else None
        return self._b

    def _body_or_400(self):
        b = self._body()
        if b is None:
            self._send(400, {"ok": False, "error": "bad json"})
        return b

    # ── 요청 보안(spec §8) ───────────────────────────────────────────────────────────────
    def _port(self):
        try:
            return int(self.server.server_address[1])
        except (AttributeError, TypeError, ValueError, IndexError):
            return PORT[0]

    def _host_ok(self):
        h = (self.headers.get("Host") or "").strip().lower()
        p = self._port()
        return h in (f"127.0.0.1:{p}", f"localhost:{p}")

    def _origin_ok(self):
        o = self.headers.get("Origin")
        if o is None:
            return True
        p = self._port()
        return o.strip().lower() in (f"http://127.0.0.1:{p}", f"http://localhost:{p}")

    def _post_problem(self, path=""):
        """POST·DELETE 검사 → 거절 까닭('' = 통과): JSON 형식 · Origin(있으면 이 화면) · 화면 열쇠(X-AF32-UI).
        /api/alive·/api/bye 만은 열쇠를 JSON 본문의 "ui" 로도 받는다 — 창을 닫거나 떠날 때(pagehide)는 sendBeacon 만 확실히
        도착하는데 sendBeacon 은 머리글을 붙일 수 없다(형식 application/json · Origin 검사는 그대로)."""
        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            return "content_type"
        if not self._origin_ok():
            return "origin"
        tok = (self.headers.get("X-AF32-UI") or "").strip()
        if not tok and path in BEACON_PATHS:
            tok = str((self._body() or {}).get("ui") or "").strip()
        if not tok or not hmac.compare_digest(tok.encode("utf-8"), UI_TOKEN.encode("utf-8")):
            return "token"
        return ""

    def _consent_state(self):
        try:
            return consent.status(ROOT, cfg())
        except Exception:  # noqa: BLE001 - 상태를 읽지 못하면 열지 않는다
            return {"accepted": False}

    def _fetch_site_ok(self):
        """Sec-Fetch-Site(브라우저가 붙인다 — 이 요청을 시킨 쪽)가 있으면 이 화면 자신(same-origin)이거나 사람이 직접 연 것(none)
        이어야 한다. 다른 사이트(cross-site)와 이 PC 의 다른 포트에서 뜬 화면(same-site — 쿠키는 포트를 가리지 않아 세션 쿠키가
        실린다)이 시킨 요청은 GET 도 받지 않는다 — 그런 화면이 [연결 확인](조직장 서버 hello) 같은 GET 을 대신 부르지 못한다.
        머리글이 없으면(브라우저가 아닌 프로그램·옛 브라우저) 세션 쿠키·Origin·화면 열쇠 검사에 맡긴다."""
        v = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        return v in ("", "same-origin", "none")

    def _cookie_sessions(self):
        """Cookie 머리글의 af32s 값들 → 세션 값 목록(점으로 이은 것을 풀어 · 꼴이 맞는 것만 · 받은 차례대로 · 16개까지).
        Cookie 머리글 여럿·같은 이름 여럿도 본다."""
        out = []
        for h in self.headers.get_all("Cookie") or []:
            for part in str(h).split(";"):
                k, sep, v = part.strip().partition("=")
                if not sep or k.strip() != SESSION_COOKIE:
                    continue
                for s in v.strip().split("."):
                    if KEY_RX.fullmatch(s) and s not in out and len(out) < 16:
                        out.append(s)
        return out

    def _session_ok(self):
        """세션 쿠키(af32s)에 이 프로세스의 세션 값이 있나."""
        want = SESSION_ID.encode("utf-8")
        ok = False
        for s in self._cookie_sessions():
            ok = hmac.compare_digest(s.encode("utf-8"), want) or ok
        return ok

    def _launch(self, method, path, query):
        """GET /?k=<시작 열쇠> — 맞으면 세션 쿠키와 함께 / 로 옮겨 가는 작은 화면(launch_page)을 보낸다 → 처리했나.
        쿠키 값 = 이미 있던 다른 화면의 세션 값(다른 설치 폴더의 화면 — 쿠키는 포트를 가리지 않는다) + 내 세션 값.
        틀린 열쇠는 무시한다(쿠키가 없으면 다음 검사가 403)."""
        if method != "GET" or path not in ("/", "/index.html") or not query:
            return False
        k = str((parse_qs(query).get("k") or [""])[0])
        if not k or not hmac.compare_digest(k.encode("utf-8", "replace"), LAUNCH_KEY.encode("utf-8")):
            return False
        self._drain()
        others = [s for s in self._cookie_sessions() if s != SESSION_ID]
        value = ".".join((others + [SESSION_ID])[-max(1, SESSION_KEEP):])
        self._send(200, launch_page(), "text/html; charset=utf-8",
                   headers=dict(PAGE_HEADERS, **{"Set-Cookie": f"{SESSION_COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/"}))
        return True

    def _pre(self, method, path, known=True, query=""):
        """모든 요청의 앞 검사 → 계속해도 되나. Host → 시작 열쇠(/?k=) → 요청을 시킨 쪽(Sec-Fetch-Site) → 세션 쿠키(없으면 GET 도
        403) → (시작 검사에 걸렸으면 그 화면만) → POST 검사 → 없는 경로(404) → 시작 확인(내 자료인가 · 모두 지우는 중이 아닌가 —
        아니면 CONSENT_FREE 밖의 /api/* 는 403)."""
        if not self._host_ok():
            self._drain()
            self._send(403, {"ok": False, "error": "bad_host"})
            return False
        if self._launch(method, path, query):       # 시작 열쇠가 맞으면 누가 연 것이든(bat·주소창) 쿠키를 주고 / 로 보낸다
            return False
        if not self._fetch_site_ok():
            self._drain()
            if method == "GET" and path in PAGE_PATHS:
                self._send(403, no_session_page(), "text/html; charset=utf-8", headers=PAGE_HEADERS)
            else:
                self._send(403, {"ok": False, "error": "forbidden", "why": "fetch_site"})
            return False
        if not self._session_ok():
            self._drain()
            if method == "GET" and path in PAGE_PATHS:
                self._send(403, no_session_page(), "text/html; charset=utf-8", headers=PAGE_HEADERS)
            else:
                self._send(403, {"ok": False, "error": "no_session", "msg": NO_SESSION_MSG})
            return False
        if STARTUP["blocked"]:
            self._drain()
            if method == "GET" and path in ("/", "/index.html"):
                self._send(200, blocked_page(STARTUP["blocked"]), "text/html; charset=utf-8", headers=PAGE_HEADERS)
            else:
                self._send(403, {"ok": False, "error": "setup_refused", "msg": STARTUP["blocked"]})
            return False
        if method != "GET":
            why = self._post_problem(path)
            if why:
                self._drain()
                self._send(403, {"ok": False, "error": "forbidden", "why": why})
                return False
        if not known:
            self._drain()
            self._send(404, {"ok": False, "error": "not found"})
            return False
        if path.startswith("/api/") and path not in CONSENT_FREE:
            st = self._consent_state()
            if not st.get("accepted"):
                self._drain()
                self._send(403, gate_refusal(st))
                return False
        return True

    def _dispatch(self, method, routes):
        u = urlparse(self.path)
        path = u.path or "/"
        self._sent = False
        if not self._pre(method, path, routes.get(path), u.query):
            return
        self.q = parse_qs(u.query)
        try:
            getattr(self, routes[path])()
        except Exception as e:  # noqa: BLE001 - 처리 중 예외도 응답은 한다(연결만 끊기면 화면이 까닭을 모른다)
            log(f"[ui] {method} {path} 처리 중 오류: {type(e).__name__}")
            if not self._sent:
                try:
                    self._drain()
                    self._send(500, {"ok": False, "error": f"서버 오류({type(e).__name__})"})
                except OSError:
                    pass

    def do_GET(self):
        self._dispatch("GET", GET_ROUTES)

    def do_POST(self):
        self._dispatch("POST", POST_ROUTES)

    def do_DELETE(self):
        self._dispatch("DELETE", {})

    # ── JOB 잡기 ───────────────────────────────────────────────────────────────────────
    def _claim(self, step, *, reset_log=False):
        """JOB 을 잡는다 → 잡았나. 이미 돌면 409(무엇이 도는지) · 리포트를 만드는 중이면 409."""
        with LOCK:
            if JOB["running"]:
                st = str(JOB.get("step") or "")
                self._send(409, {"ok": False, "error": "busy", "step": st, "hint": busy_hint(st)})
                return False
            if REPORT_LOCK.locked():
                self._send(409, {"ok": False, "error": "busy", "hint": "리포트를 만드는 중입니다 — 끝난 뒤 다시 누르세요"})
                return False
            JOB.update(running=True, step=step, started=time.time(), phase="", done=0, total=0, pid=0)
            if reset_log:
                JOB["log"] = []
        return True

    @staticmethod
    def _release():
        with LOCK:
            JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)

    def _busy409(self, hint=None):
        """작업이 도는 중이면 409 를 보내고 True(잡지는 않는다)."""
        with LOCK:
            busy, st = bool(JOB["running"]), str(JOB.get("step") or "")
        if busy or REPORT_LOCK.locked():
            self._send(409, {"ok": False, "error": "busy", "step": st, "hint": hint or busy_hint(st or "리포트 만들기")})
            return True
        return False

    # ── GET ──────────────────────────────────────────────────────────────────────────
    def _g_index(self):
        page = (PAGE.replace("__AF32_UI__", UI_TOKEN).replace("__AF32_TITLE__", html.escape(lmname.DISPLAY_TITLE))
                .replace("__AF32_PAPER__", html.escape(paper_line())))
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", headers=PAGE_HEADERS)

    def _g_guide(self):
        gp = os.path.join(ROOT, "docs", "사용안내.html")
        try:
            with open(gp, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8", headers=DOC_HEADERS)
        except OSError:
            self._send(200, ("<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic'\">"
                             r"<h3>사용 안내 파일이 없습니다</h3><p>docs\사용안내.html 이 함께 복사됐는지 FILES.txt 로 확인하세요.</p></body>"
                             ).encode(), "text/html; charset=utf-8", headers=DOC_HEADERS)

    def _g_status(self):
        with LOCK:
            el = time.time() - JOB["started"] if JOB["started"] else 0
            pel = time.time() - JOB["phase_started"] if JOB["phase_started"] else 0
            eta = None
            if JOB["total"] and JOB["done"] > 0 and pel > 0:
                eta = int(pel / JOB["done"] * (JOB["total"] - JOB["done"]))
            payload = {"running": JOB["running"], "log": JOB["log"][-200:], "step": JOB["step"], "phase": JOB["phase"],
                       "done": JOB["done"], "total": JOB["total"], "elapsed": int(el), "eta": eta,
                       "idle": (int(time.time() - JOB["last_out"]) if JOB["last_out"] else None)}
        accepted = bool(self._consent_state().get("accepted"))
        payload.update(version=VERSION, consented=accepted, notices=take_notices())
        if accepted:                          # 마지막 분석 기간·때는 내 자료일 때만(다른 사용자의 자료는 열지 않는다)
            tags = af32_tags()
            tag = max(tags, key=lambda t: (tags[t], t)) if tags else ""
            payload.update(last_run=_age(tags[tag]) if tag else "", last_tag=tag)
        self._send(200, payload)

    def _g_consent(self):
        """화면의 시작 상태와 안내(읽기만 한다) — 닫힌 폴더에서도 답한다(경로 이름은 예전 그대로). state = consent.status
        (accepted · other_user · unknown_owner · withdrawal_state · withdrawn_at · chats_left). notice·order = [안내]에 보일 글.
        nonce 는 [모두 지우기(서버 사본 포함)](POST /api/consent/withdraw)용이다 — 이 화면에는 고르고 저장하는 요청이 없다."""
        c, warns = cfg_and_warnings()
        st = consent.status(ROOT, c)
        other = bool(st.get("other_user") or st.get("unknown_owner"))
        n_chats = 0 if other else (_int(st.get("chats_left"), 0) or 0)
        # 다른 사용자의 자료면 공유 기록·남은 채팅 수를 싣지 않는다(열지 않는다 — D17)
        self._send(200, {"ok": True, "state": st, "notice": consent.notice(c), "order": list(consent.NOTICE_ORDER),
                         "nonce": issue_nonce("consent"), "purpose": consent.PURPOSE_LINE,
                         "paper_line": paper_line(), "withdraw_line": str(consent.WITHDRAW_PAPER_LINE),
                         "other_user_msg": owner_msg(st), "wiping_msg": consent.WIPING_MSG, "wiping_now": wiping_now(),
                         "config_warnings": warns,
                         "title": lmname.DISPLAY_TITLE, "contact": contact_info(c),
                         "receipts_n": 0 if other else len(_receipts()), "pending": [] if other else pending_view(),
                         "chats_line": chats_msg(n_chats)})

    def _g_retention(self):
        c = cfg()
        try:
            table = retention.expiry_table(ROOT, c)
        except Exception:  # noqa: BLE001 - 표 하나가 탭을 막지 않게
            table = []
        sched = bool(afcfg.get(c, "retention.scheduledPurge"))
        if self._consent_state().get("other_user"):
            # 다른 사용자의 자료 — 열지 않는다: 파일 수·날짜·공유 기록 없이 보관 규칙(일수)만
            rows = [dict(x, files=None, oldest=None, next_delete=None) for x in table if isinstance(x, dict)]
            self._send(200, {"ok": True, "other_user": True, "table": rows, "kept": [], "scheduled": sched, "task": None,
                             "receipts": [], "pending": [], "purge_status": None})
            return
        try:                                  # 꺼 둔 설정이어도 본다 — 예전에 만든 작업이 남아 있으면 그렇다고 알린다(L2-14)
            task = retention.task_registered(ROOT)
        except Exception:  # noqa: BLE001
            task = None
        try:                                  # 보관기한 없이 모두 지울 때까지 남는 것(전용 Edge 로그인 프로필·공유 영수증)
            kept = list(retention.kept_table(ROOT))
        except Exception:  # noqa: BLE001 - 표 하나가 탭을 막지 않게
            kept = []
        self._send(200, {"ok": True, "table": table, "kept": kept, "scheduled": sched, "task": task,
                         "receipts": receipts_view(), "pending": pending_view(), "purge_status": purge_status_view()})

    def _g_period(self):
        try:
            self._send(200, period_payload(self.q))
        except ValueError as e:
            self._send(400, {"ok": False, "error": str(e)[:200]})

    def _g_collect_summary(self):
        restricted_guard()
        self._send(200, collect_summary_payload())

    def _g_collect_status(self):
        self._send(200, collect_status_payload((self.q.get("from") or [""])[0], (self.q.get("to") or [""])[0]))

    def _g_dash(self):
        restricted_guard()                    # 제한 고객 목록이 바뀌었으면 그 전 목록으로 만든 결과를 보이지 않는다
        tag = latest_tag()
        fn, rows = result_rows(tag)
        snap1, meta_fn = _l1_tools()
        for r in rows:
            s1 = snap1(r.get("Level 1"))
            if s1:
                r["Level 1"] = s1
        judged, judged_n, judged_total, judged_issues = _judged_info(tag)
        lr = _read_json(os.path.join(REPORT, "last_run.json")) or {}
        lastrun = {"started": lr.get("started"), "finished": lr.get("finished"), "period": lr.get("period"),
                   "chats_line": str(lr.get("chats_line") or "")[:300],
                   "stages": [{"name": str(x.get("name") or ""), "ok": bool(x.get("ok")), "note": str(x.get("note") or "")[:200]}
                              for x in (lr.get("stages") or []) if isinstance(x, dict)][:40]}
        stub_note = _stub_note(lr)
        rm = run_meta(tag)
        with LOCK:
            stale = bool(JOB["running"])
        self._send(200, {"version": VERSION, "tag": tag, "file": fn, "rows": rows, "l1meta": meta_fn() or {},
                         "period": rm.get("period"), "clamped": rm.get("clamped"), "generated": rm.get("generated"),
                         "judged": judged, "judged_n": judged_n, "judged_total": judged_total, "judged_issues": judged_issues,
                         "last_run": lastrun, "stub": bool(stub_note), "stub_note": stub_note,
                         "stub_env": bool(os.environ.get(STUB_MARK)),
                         "collected_only": (not rows) and _has_collected(), "stale": stale})

    def _g_review(self):
        if (self.q.get("g") or [""])[0] != "all":
            self._send(404, {"ok": False, "error": "not found"})
            return
        restricted_guard()
        self._send(200, taxonomy())

    def _tool_result(self, kind, prefix, stage):
        """GET /api/agentic·/api/workflow 의 공통 뼈대 — 지금 기간의 결과 파일 + 단계 상태 + 화면 실행 결과."""
        restricted_guard()
        out = {"stage_note": _stage_note(stage), "stage_kind": _stage_kind(stage)}
        tag = latest_tag()
        data = None
        if tag:
            out["tag"] = tag
            p = os.path.join(REPORT, f"{prefix}{tag}.json")
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8-sig") as f:
                        data = json.load(f)
                    if not isinstance(data, dict):
                        data = None
                        out["file_error"] = f"{prefix}{tag}.json 의 최상위가 객체가 아닙니다 — 다시 만드세요"
                except (OSError, ValueError) as e:
                    out["file_error"] = f"{prefix}{tag}.json 을 읽지 못함({type(e).__name__}) — 다시 만드세요"
            else:
                ot = _other_tag(prefix, tag)
                if ot:
                    out["other_tag"] = ot
            out["stage_kind"] = _stage_kind(stage, tag)
        with LOCK:
            out["manual"] = MANUAL.get(kind)
            out["running"] = bool(JOB["running"] and JOB["step"] == TOOL_JOBS[kind][1])
            out["busy"] = JOB["step"] if JOB["running"] else ""
        return tag, data, out

    def _g_agentic(self):
        tag, a, out = self._tool_result("agentic", "agentic_", "Agentic 니즈 발굴")
        out["analysis"] = agentic_view(a) if a is not None else None
        if a is None and tag:
            out.update(_stage_why(tag, "agentic"))
        elif a is not None and _reextracted(tag):
            out["reextracted"] = True
            out["reextracted_title"] = "재추출 이후 결과"
            out["reextracted_note"] = "이 후보는 마지막 재추출 이전의 업무로 찾은 것입니다 — [후보 발굴 실행]으로 갱신하세요"
        self._send(200, out)

    def _g_workflow(self):
        tag, w, out = self._tool_result("flow", "workflow_", "워크플로우 분석")
        if w is not None:
            base = dict(w)
            snap1, _m = _l1_tools()
            for fl in (base.get("flows") or []):
                if isinstance(fl, dict):
                    fl.pop("role", None)
                    fl.pop("mm", None)
                    if fl.get("level1"):
                        fl["level1"] = snap1(fl["level1"]) or fl["level1"]
            for k in ("tag", "stage_note", "stage_kind", "manual", "running", "busy"):
                base[k] = out.get(k)
            out = base
            if _reextracted(tag):
                out["reextracted"] = True
                out["reextracted_note"] = "이 워크플로우는 마지막 재추출 이전의 업무로 판정한 것입니다 — 과제·업무 이름이 지금 화면과 어긋날 수 있습니다"
        else:
            out["ok"] = False
        if tag and not (isinstance(out.get("flows"), list) and out["flows"]):
            out.update(_stage_why(tag, "flow"))
        self._send(200, out)

    def _g_projects(self):
        import projmap
        self._send(200, {"projects": projmap.load_user_projects(ROOT)})

    def _g_share_status(self):
        r"""[공유] 탭 — 저장한 주소·영수증(이 PC 의 파일)만. 조직장 서버에 붙지 않는다(L5-06).
        ?check=1 이면 [연결 확인]·[보내기…]: teamup --ping 으로 hello 한 번(share_check — 확인 창 값 + share_check 표)."""
        c = cfg()
        out = {"ok": True, "checked": False, "addr": addr_info(), "receipts": receipts_view(), "pending": pending_view(),
               "owner": _clean_text(c.get("owner"), 40), "function": _clean_text(c.get("function"), 40),
               "tag": latest_tag(), "nonce": issue_nonce("share_status"), "lines": share_lines()}
        if (self.q.get("check") or [""])[0] in ("1", "true", "yes"):
            out.update(share_check(), checked=True)
        self._send(200, out)

    # ── POST ─────────────────────────────────────────────────────────────────────────
    def _p_alive(self):
        b = self._body() or {}
        self._send(200, {"ok": ui_tab_alive(b.get("id"), str(b.get("vis") or "visible"))})

    def _p_bye(self):
        b = self._body() or {}
        self._send(200, {"ok": ui_tab_bye(b.get("id"))})

    def _p_quit(self):
        self._drain()
        if _critical_busy():                  # 모두 지우기·자료 지우기를 반쯤에서 끊지 않는다
            with LOCK:
                st = str(JOB.get("step") or "")
            self._send(409, {"ok": False, "error": "busy", "step": st,
                             "hint": f"지금 '{st}' 중입니다 — 끝난 뒤 서버를 종료하세요"})
            return
        self._send(200, {"ok": True})
        cleanup_children()
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def _p_stop(self):
        self._drain()
        with LOCK:
            was = JOB["running"]
            had_pid = bool(JOB.get("pid"))
            was_run = str(JOB.get("step") or "") == RUN_STEP
        # 정리 중 예외가 나도 반드시 응답한다 — 응답이 안 나가면 [중지] 단추가 눌린 채로 남는다
        for fn2 in (kill_job, lambda: close_edge("ui_stop", budget=UI_SWEEP_SEC)):
            try:
                fn2()
            except Exception as e:  # noqa: BLE001
                log(f"[중지] {getattr(fn2, '__name__', '정리')} 실패({type(e).__name__}) — 계속 진행")
        if was and had_pid and was_run:
            drop_raw_now(check=False)        # 멈춘 수집이 남긴 원자료(COM — 바깥 사람 이름·주소)는 바로 지운다
        if had_pid:
            log("[중지] 사용자 요청으로 작업을 멈췄습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
        elif was:
            log("[중지] 지금 도는 작업은 중간에 멈출 수 없습니다 — 곧 끝나면 멈춥니다")
        self._send(200, {"ok": True, "stopped": was and had_pid})

    def _p_openfolder(self):
        self._drain()
        try:
            os.makedirs(REPORT, exist_ok=True)
            subprocess.Popen(["explorer", REPORT], creationflags=NO_WIN)
        except OSError:
            pass
        self._send(200, {"ok": True})

    def _p_run(self):
        b = self._body_or_400()
        if b is None:
            return
        try:
            d0, d1, info, note = clamp_period(b.get("from"), b.get("to"))
        except ValueError as e:
            self._send(400, {"ok": False, "error": str(e)[:200]})
            return
        if not self._claim("분석 실행", reset_log=True):
            return
        threading.Thread(target=run_job, args=(d0, d1, bool(b.get("ai")), bool(b.get("skip")), note),
                         kwargs={"req": (b.get("from"), b.get("to"))}, daemon=True).start()
        self._send(200, {"ok": True, "from": d0, "to": d1, "clamped": bool(info.get("clamped")), "notice": note})

    def _p_owa(self):
        b = self._body_or_400()
        if b is None:
            return
        try:
            d0, d1, _info, note = clamp_period(b.get("from"), b.get("to"))
        except ValueError as e:
            self._send(400, {"ok": False, "error": str(e)[:200]})
            return
        if not self._claim("Outlook 웹 읽기"):
            return
        try:
            if note:
                log(note)
            self._send(200, dict(web_read(d0, d1), notice=note))
        finally:
            self._release()

    def _p_chat_sweep(self):
        self._drain()
        if not self._claim("Copilot 채팅 지우기"):
            return
        res = {"ok": False, "line": "", "note": CHAT_SWEEP_NOTE}
        try:
            log("[Copilot 채팅] 이 도구의 기록에 있는 채팅을 다시 지웁니다(최대 5분 — 사람이 쓰던 채팅은 건드리지 않습니다)")
            res = chat_sweep_now()
            log("[Copilot 채팅] " + str(res.get("line") or "")[:400])
        except Exception as e:  # noqa: BLE001 - 어떤 예외도 JOB 을 '실행 중'으로 남기면 안 된다
            res = {"ok": False, "line": f"Copilot 채팅 지우기 실패({type(e).__name__})", "note": CHAT_SWEEP_NOTE}
            log("[Copilot 채팅] " + res["line"])
        finally:
            self._release()
        self._send(200, res)

    def _p_diag(self):
        # 몇 분 안에 'AI 판정이 가능한 상태인가'만 확인한다 — 진단 채팅은 한 번 묻고 바로 지운다(--retire)
        self._drain()
        if not self._claim("AI 연결 진단"):
            return
        import tempfile
        pf = os.path.join(tempfile.gettempdir(), lmname.TMP_PREFIX + "diag_prompt.txt")
        try:
            with open(pf, "w", encoding="utf-8") as f:
                f.write("아래 목록만 사용하세요. 메일·채팅·파일·웹을 검색하지 마세요.\n"
                        "연결 확인용 질문입니다. 아래 JSON 한 줄만 그대로 출력하세요.\n"
                        '{"ok":"연결됨"}\n')
            r2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"),
                                 "--send", pf, "--fresh", "--retire"], capture_output=True, timeout=300,
                                cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
            txt = (r2.stdout or b"").decode("utf-8", "replace").strip()
            try:
                res = json.loads(txt.splitlines()[-1])
                res = res if isinstance(res, dict) else {"ok": False, "error": "드라이버 출력 해석 실패"}
            except (ValueError, IndexError):
                res = {"ok": False, "phase": "driver", "error": "드라이버 출력 해석 실패", "hint": txt[-200:] or "출력 없음"}
        except subprocess.TimeoutExpired:
            res = {"ok": False, "phase": "timeout", "error": "5분 내 응답 없음", "hint": "전용 Edge 창이 응답을 만드는 중인지 확인하세요"}
        except OSError as e:
            res = {"ok": False, "phase": "spawn", "error": f"드라이버 실행 실패({type(e).__name__})", "hint": str(e)[:150]}
        finally:
            try:
                os.remove(pf)
            except OSError:
                pass
            self._release()
        res.pop("reply", None)               # 응답 원문은 화면에 싣지 않는다(연결 여부만)
        log("[진단] Copilot 왕복 " + ("성공" if res.get("ok") else "실패 — " + str(res.get("error", ""))))
        if res.get("chats"):
            log("[진단] Copilot 채팅 정리: " + str(res["chats"])[:300])
        self._send(200, res)

    def _p_collectdiag(self):
        # 수집 진단 — Outlook 메일·일정과 Copilot 에 닿는지만 본다(collect\Diagnose-Collectors.ps1 → report\collect_diag.txt)
        self._drain()
        if not self._claim("수집 진단"):
            return
        outp = os.path.join(REPORT, "collect_diag.txt")
        try:
            try:
                os.remove(outp)                  # 지난 보고서가 이번 실패를 가리지 않게 먼저 지운다
            except OSError:
                pass
            r2 = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 os.path.join(ROOT, "collect", "Diagnose-Collectors.ps1"), "-OutFile", outp],
                                capture_output=True, timeout=240, cwd=ROOT,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
            txt = (r2.stdout or b"").decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            self._send(200, {"ok": False, "error": "4분 내 끝나지 않음 (Outlook 응답 대기 의심)"})
            return
        except OSError as e:
            self._send(200, {"ok": False, "error": f"진단 스크립트 실행 실패({type(e).__name__})"})
            return
        finally:
            self._release()
        lines = [ln.rstrip() for ln in txt.splitlines()]
        verdict, on = [], False
        for ln in lines:
            if ln.startswith("[판정]"):
                on = True
            elif on and ln.startswith("→"):
                break
            elif on and ln.strip():
                verdict.append(ln.strip())
        log("[수집 진단] " + (verdict[0] if verdict else "판정 없음"))
        self._send(200, {"ok": r2.returncode == 0 and os.path.exists(outp), "verdict": verdict})

    def _p_reset_cursors(self):
        self._drain()
        if self._busy409("분석·웹 읽기가 끝난 뒤 누르세요"):
            return
        gone, led_ok = reset_cursors_local()
        log("[커서 초기화] " + ("커서 " + ", ".join(gone) if gone else "커서 파일 없음")
            + (" · 날짜별 기록 초기화" if led_ok else "") + " — 다음 [분석 실행]이 기간 전체를 다시 읽습니다")
        self._send(200, {"ok": True, "removed": gone, "ledger": led_ok})

    def _p_report(self):
        self._drain()
        restricted_guard()                    # 바뀐 제한 고객 목록 — 그 전 목록으로 만든 결과로 리포트를 만들지 않는다
        if not REPORT_LOCK.acquire(blocking=False):
            self._send(409, {"ok": False, "error": "busy", "hint": "리포트를 이미 만드는 중입니다 — 잠시 뒤 다시 누르세요"})
            return
        try:
            # 잠근 '뒤에' JOB 을 본다 — 먼저 보면 그 틈에 /api/run 이 끼어들어 만드는 도중 report\ 가 다시 써진다
            with LOCK:
                busy, st = bool(JOB["running"]), str(JOB.get("step") or "")
            if busy:
                self._send(409, {"ok": False, "error": "busy", "hint": busy_hint(st)})
                return
            self._send(200, make_report())
        finally:
            REPORT_LOCK.release()

    def _p_exclude(self):
        b = self._body_or_400()
        if b is None:
            return
        if not self._claim("업무 빼기"):
            return
        try:
            self._send(200, exclude_work(str(b.get("row") or "")))
        except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다
            self._send(200, {"ok": False, "error": f"빼지 못했습니다({type(e).__name__})"})
        finally:
            self._release()

    def _p_projects(self):
        b = self._body_or_400()
        if b is None:
            return
        import projmap
        saved = projmap.save_user_projects(ROOT, b.get("projects") or [])
        self._send(200, {"ok": True, "projects": saved})

    def _p_project_split(self):
        b = self._body_or_400()
        if b is None:
            return
        if not (isinstance(b.get("a"), str) and isinstance(b.get("b"), str)):
            self._send(400, {"ok": False, "error": "나눌 두 과제 이름을 읽지 못했습니다 — 화면을 새로 고친 뒤 다시 누르세요"})
            return
        with LOCK:
            if JOB["running"]:
                self._send(409, {"ok": False, "error": "busy",
                                 "hint": "분석·다른 작업이 도는 중에는 과제 이름 병합을 나누지 않습니다 — 끝난 뒤 누르세요"})
                return
            try:
                import details as _dsp
                ans = _dsp.split_project_pair(b["a"], b["b"], path=_cache_path("project_aliases.json"))
            except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다
                ans = {"ok": False, "error": "data 폴더의 project_aliases.json 을 쓰지 못했습니다"
                       f"({type(e).__name__}) — 다른 프로그램이 열고 있으면 닫고 다시 누르세요"}
        if ans.get("ok"):
            log("[워크플로우] 과제 이름 병합 1건을 나눴습니다 — 다음 [워크플로우 재분석]부터 따로 보입니다")
        self._send(400 if ans.pop("bad", False) else 200, ans)

    def _p_retag(self):
        self._drain()
        if not self._claim("지정 반영 재분류"):
            return
        try:
            p = subprocess.run([sys.executable, os.path.join(ROOT, "retag.py")], capture_output=True, timeout=180, cwd=ROOT,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
            txt = (p.stdout or b"").decode("utf-8", "replace").strip()
            for ln in txt.splitlines():
                if ln and not ln.startswith("{"):
                    log(ln)
            try:
                res = json.loads(txt.splitlines()[-1])
            except (ValueError, IndexError):
                res = None
            if not isinstance(res, dict):
                err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                self._send(200, {"ok": False, "error": "retag 출력 해석 실패",
                                 "hint": (err[-1][:200] if err else f"종료 코드 {p.returncode}")})
                return
            self._send(200, res)
        except subprocess.TimeoutExpired:
            self._send(200, {"ok": False, "error": "시간 초과", "hint": "재분류가 제한 시간 안에 끝나지 않았습니다 — 진행 로그를 확인하세요"})
        except OSError as e:
            self._send(200, {"ok": False, "error": f"실행 실패({type(e).__name__})"})
        finally:
            self._release()

    def _p_tool(self):
        # 화면에서 다시 돌리기 — [분석 실행]과 같은 백그라운드 방식(tool_job). {"wait": true} 면 끝까지 기다려 마지막 JSON 을
        # 돌려준다(시험·스크립트용), {"redo": true} 면 이어서 하지 않고 처음부터.
        kind = "flow" if urlparse(self.path).path == "/api/workflow" else "agentic"
        b = self._body() or {}
        if restricted_guard():                # 바뀐 제한 고객 목록 — 그 전 목록으로 만든 업무로 후보·흐름을 다시 만들지 않는다
            self._send(200, dict(RESTRICTED_GONE))
            return
        if not self._claim(TOOL_JOBS[kind][1]):
            return
        th = threading.Thread(target=tool_job, args=(kind, ["--redo"] if b.get("redo") else []), daemon=True)
        th.start()
        if b.get("wait"):
            th.join()
            with LOCK:
                res = dict(MANUAL.get(kind) or {"ok": False, "error": "결과 없음"})
            self._send(200, res)
        else:
            self._send(200, {"ok": True, "started": True, "kind": kind, "step": TOOL_JOBS[kind][1]})

    # ── 모두 지우기·자료 지우기 ────────────────────────────────────────────────────────
    def _nonce_or_403(self, b, purposes):
        ok, extra = take_nonce((b or {}).get("nonce"), purposes)
        if not ok:
            self._send(403, NONCE_BAD)
            return False, None
        return True, extra

    def _run_busy(self, msg=""):
        """이 폴더에서 화면 밖의 분석·수집(AgentFinder32.bat 의 run.py 등)이 돌고 있어 지우기를 하지 않았다 → 409 busy.
        돌던 분석은 지운 뒤에도 다시 쓰고 보낸다 — 그 분석이 끝난 뒤에 한다(retention.run_active · consent.WithdrawBusy — C5)."""
        self._send(409, {"ok": False, "error": "busy", "step": RUN_STEP, "hint": RUN_BUSY_HINT,
                         "msg": str(msg or RUN_BUSY_HINT)})

    def _p_consent_withdraw(self):
        """[모두 지우기(서버 사본 포함)] — 조직장 서버의 사본 → 이 도구가 연 Copilot 채팅 → 이 PC 의 자료·설치 정보·매일 정리
        작업(withdraw_sequence). 표는 GET /api/consent 의 것. 다 지우면 이 화면은 처음 설치한 상태로 이어진다."""
        b = self._body_or_400()
        if b is None:
            return
        ok, _x = self._nonce_or_403(b, ("consent",))
        if not ok:
            return
        # 다른 사용자의 자료에는 하지 않는다 — 그 사람의 전용 Edge(로그인)를 띄워 채팅을 지우지 않는다. [열지 않고 지우기]로 지운다
        st = self._consent_state()
        if st.get("other_user") or st.get("unknown_owner"):
            self._send(409, {"ok": False, "error": "other_user", "msg": owner_msg(st)})
            return
        # ① 화면 작업이 돌면 거절(409). bat 의 분석·수집이 돌면 withdraw_sequence 의 첫 단계(consent.begin_withdrawal)가 거절한다
        #    (WithdrawBusy → 409 — 아무것도 지우지 않았다) — 그다음 ②~④.
        # 도는 동안 JOB 을 잡아 다른 작업을 막고, 창을 닫아도 끝까지 한다(CRITICAL_STEPS)
        if self._busy409():
            return
        if not self._claim(WIPE_STEP):
            return
        busy = None
        try:
            res = withdraw_sequence()
        except consent.WithdrawBusy as e:
            busy, res = e, {}
        except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다(지우기 기록이 'in_progress' 로 남아 다음 시작 때 마저 지운다)
            res = {"ok": False, "error": "failed",
                   "msg": f"지우는 중 오류가 났습니다({type(e).__name__}) — 다음에 시작할 때 마저 지웁니다"}
        finally:
            if busy is None:
                with LOCK:
                    MANUAL.clear()
                    JOB["log"] = []
            self._release()
        if busy is not None:
            self._run_busy(busy.message)
            return
        keep_session_file()
        if res.get("ok"):
            log("[지우기] " + res["msg"])
        self._send(200, res)

    def _p_purge(self):
        b = self._body_or_400()
        if b is None:
            return
        scope = str(b.get("scope") or "")
        if scope not in PURGE_SCOPES:
            self._send(400, {"ok": False, "error": "bad scope", "hint": "지울 범위는 expired · all_keep_consent · all 입니다"})
            return
        if scope != "expired" and self._busy409():
            return
        if not self._claim("자료 지우기"):
            return
        busy = None
        try:
            if scope == "expired":
                r = retention.purge(ROOT, cfg())
            elif scope == "all_keep_consent":
                if run_active():                        # bat 의 분석이 지운 뒤에 다시 쓰지 않게
                    raise RunBusy()
                r = retention.purge_all(ROOT, keep_consent=True, keep_edge=True)
            else:
                r = None
                body = purge_everything(other_user=bool(self._consent_state().get("other_user")))
            if r is not None:
                errs = list(r.get("errors") or [])
                body = {"ok": True, "scope": scope, "deleted": int(r.get("deleted") or 0), "n_errors": len(errs),
                        "errors": errs[:20]}
        except (RunBusy, consent.WithdrawBusy) as e:
            busy, body = e, {}
        except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다
            body = {"ok": False, "scope": scope, "error": "failed", "hint": f"지우는 중 오류 — {type(e).__name__}"}
        finally:
            if scope != "expired" and busy is None:
                with LOCK:
                    MANUAL.clear()
            self._release()
        if busy is not None:
            self._run_busy(getattr(busy, "message", ""))
            return
        if scope != "expired":
            keep_session_file()
        if body.get("ok"):
            log(f"[지우기] {({'expired': '기한 지난 자료', 'all_keep_consent': '모은 자료 모두', 'all': '이 PC 의 내 자료 모두'})[scope]}"
                f" — {body['deleted']:,}개 지움" + (f" · {body['n_errors']}개 못 지움" if body["n_errors"] else ""))
        self._send(200, body)

    # ── 공유(D14) ───────────────────────────────────────────────────────────────────
    def _p_share_preview(self):
        b = self._body_or_400()
        if b is None:
            return
        ok, _x = self._nonce_or_403(b, ("share_status",))
        if not ok:
            return
        if restricted_guard():                # 바뀐 제한 고객 목록 — 그 전 목록으로 만든 결과는 미리 보지도 않는다
            self._send(200, dict(RESTRICTED_GONE, status_nonce=issue_nonce("share_status")))
            return
        if not self._claim("공유 미리보기"):
            return
        try:
            code, res = share_preview(b)
        except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다
            code, res = 200, {"ok": False, "code": "error", "msg": f"미리보기를 만들지 못했습니다({type(e).__name__})"}
        finally:
            self._release()
        self._send(code, dict(res, status_nonce=issue_nonce("share_status")))

    def _p_share(self):
        b = self._body_or_400()
        if b is None:
            return
        ok, extra = self._nonce_or_403(b, ("share",))
        if not ok:
            return
        if not self._claim("조직장에게 공유"):
            return
        try:
            code, res = share_send(b, extra or {})
        except Exception as e:  # noqa: BLE001 - 까닭을 돌려준다(다시 보내지 않는다)
            code, res = 200, {"ok": False, "code": "error", "msg": f"보내는 중 오류 — {type(e).__name__}"}
        finally:
            self._release()
        self._send(code, res)

    def _p_share_withdraw(self):
        b = self._body_or_400()
        if b is None:
            return
        ok, _x = self._nonce_or_403(b, ("share_status",))
        if not ok:
            return
        if not self._claim("공유 거두기"):
            return
        try:
            res = teamup_call(["--withdraw"] + (["--all"] if b.get("all", True) else []), timeout=90)
        finally:
            self._release()
        log("[공유] " + ("보낸 공유를 거뒀습니다" if res.get("ok") else
                       f"보낸 공유를 다 거두지 못했습니다 — {str(res.get('msg') or res.get('code') or '')[:160]}"))
        self._send(200, dict(_scrub_secrets(res), status_nonce=issue_nonce("share_status")))


def _browser_ok():
    """브라우저를 열어도 되나(--no-browser · AF32_NO_BROWSER 면 주소만 찍는다)."""
    return "--no-browser" not in sys.argv and not os.environ.get("AF32_NO_BROWSER")


def bind_server(ports=None):
    r"""화면 포트 대역(lmname.UI_PORTS — 9370~9389 · 다른 판 대시보드 대역과 나눠 북마크·탭이 섞이지 않게)에서 처음으로 잡히는
    포트에 화면 서버를 연다 → (서버, 포트) | (None, None).
    배타 bind(윈도 SO_EXCLUSIVEADDRUSE · SO_REUSEADDR 를 쓰지 않는다) — 다른 프로세스가 듣고 있는 포트 위에 덧바인딩하지 않는다.
    윈도의 SO_REUSEADDR 는 이미 듣고 있는 포트에도 bind 를 허락한다: 같은 때 뜬 두 화면이 한 포트에 겹치면 브라우저가 다른 화면
    (다른 시작 열쇠)에 붙어 열리지 않는다. 포트를 먼저 떠 보고 나중에 bind 하지도 않는다(그 사이에 다른 화면이 잡는 틈이 없다)."""
    for p in (lmname.UI_PORTS if ports is None else ports):
        srv = ThreadingHTTPServer(("127.0.0.1", p), H, bind_and_activate=False)
        srv.allow_reuse_address = False
        ex = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if ex is not None:
            try:
                srv.socket.setsockopt(socket.SOL_SOCKET, ex, 1)
            except OSError:                  # 이 옵션을 못 거는 곳에서도 화면은 뜬다(SO_REUSEADDR 는 여전히 쓰지 않는다)
                pass
        try:
            srv.server_bind()
            srv.server_activate()
            return srv, int(p)
        except OSError:
            srv.server_close()
    return None, None


def _serve_blocked(srv, port, msg):
    r"""시작 검사에 걸렸다 — 까닭만 보이는 화면을 띄우고(BLOCKED_SEC 뒤 스스로 끝남) 종료 코드 4. srv = bind_server 가 연 서버.
    이 화면도 시작 열쇠로 연다. 설치 위치가 맞지 않을 수 있으므로(동기화 폴더) 열쇠 파일(data\ui_session.json)은 쓰지 않는다."""
    print("[ui] " + msg, flush=True)
    url = launch_url(port)
    if _browser_ok():
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    threading.Timer(BLOCKED_SEC, srv.shutdown).start()
    print(f"[ui] 안내 화면: {url}  ({int(BLOCKED_SEC // 60)}분 뒤 저절로 닫힙니다 · Ctrl+C 종료)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 4


def main():
    # 이 폴더의 화면이 이미 떠 있으면(두 번째 bat 실행) 새 서버를 띄우지 않고 그 화면을 연다 — data\ui_session.json 의 시작 열쇠로
    other = running_ui()
    if other:
        url = launch_url(other["port"], other["key"])
        print(f"[ui] {lmname.DISPLAY_TITLE} 화면이 이미 열려 있습니다 — 그 화면을 엽니다: {url}", flush=True)
        if _browser_ok():
            webbrowser.open(url)
        return 0
    # 포트를 먼저 잡는다(배타 bind — 9370~9389 중 처음 잡히는 것). 시작 순서가 도는 동안에도 이 포트는 이 프로세스의 것이다
    srv, port = bind_server()
    if srv is None:
        print(f"사용 가능한 포트가 없습니다 ({lmname.UI_PORTS[0]}-{lmname.UI_PORTS[-1]})")
        return 1
    PORT[0] = port
    # 시작 순서(spec §6.2) — 설치 위치·옛 LoadMonitor 파일 검사 → 옛 자료 정리 → 보관기한 정리
    msg = startup()
    if msg:
        return _serve_blocked(srv, port, msg)
    os.makedirs(REPORT, exist_ok=True)
    # 서버로 뜰 때만 종료 정리를 건다 — 임포트 부작용이 없어야 시험이 이 모듈을 안전하게 쓴다
    import atexit
    atexit.register(cleanup_children)
    # 콘솔 창(bat)을 X 로 닫으면 — 작업 트리를 끝내고 Job 밖의 전용 Edge 를 몇 초 안에 닫는다(채팅 정리는 건너뛴다)
    proc.on_console_close(console_close_cleanup)
    proc.quiet_errors()      # 자식(run.py·수집기)이 못 켜질 때 Windows 오류 창이 쌓이지 않게
    # 지난 실행이 남긴 전용 Edge 는 owner.json 표식이 있을 때만 CDP 로 닫는다(로그인 대기 중이면 둔다 · 사람이 띄운 Edge 는 건드리지 않는다)
    threading.Thread(target=lambda: close_edge("ui_start"), daemon=True).start()
    # 이 주소(시작 열쇠)로 들어온 브라우저만 화면을 연다 — 콘솔·bat 은 이 PC 의 이 사용자에게만 보인다
    url = launch_url(port)
    print(f"[ui] {lmname.DISPLAY_TITLE} {VERSION} — {url}  (Ctrl+C 종료)")
    prev = prev_ui_exit()
    if prev:
        print(prev)
        log(prev[len("[ui] "):])
    ccfg = _close_cfg()
    if ccfg["on"]:
        print("[ui] 화면 창을 모두 닫으면 실행 중인 작업도 멈추고 이 창이 닫힙니다(약 20초 뒤)")
    SESSION_FILE_ON[0] = bool(write_session_file(port))    # 두 번째 bat 실행이 이 화면을 연다(끝날 때 지운다)
    if _browser_ok():
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if ccfg["on"]:
        threading.Thread(target=close_watch, args=(srv, ccfg), daemon=True, name="lm-close-watch").start()
    # 화면에서 띄운 작업이 도는 동안 PC 가 절전에 들어가지 않게(awake_watch · keepAwakeDuringRun)
    threading.Thread(target=awake_watch, daemon=True, name="lm-awake").start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        SESSION_FILE_ON[0] = False     # 끝나는 중 — 지우기가 끝난 뒤 열쇠 파일을 다시 쓰지 않는다
        remove_session_file()
    try:
        wait_critical(say=lambda s: print(s, flush=True))   # 모두 지우기·자료 지우기는 끝까지(요청 스레드는 데몬이다)
    except KeyboardInterrupt:
        pass
    remove_session_file()              # 기다리는 사이 다시 쓰였으면 한 번 더
    print("[ui] 종료")
    return 0


if __name__ == "__main__":
    # bat 더블클릭(CP949 콘솔)에서도 —·한글이 안 깨지게 stdout 래핑 (import 시엔 건드리지 않음)
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", line_buffering=True, encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # "실행이 안 된다"는 보고의 대부분은 창이 즉시 닫혀 원인이 사라진 경우다 — 어떤 예외든 ui_error.log 에 남긴다
        import traceback
        p = os.path.join(ROOT, "ui_error.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n=== " + time.strftime("%Y-%m-%d") + " ===\n")      # 날짜만(D10 — 시각은 data\outlook 밖에 두지 않는다)
            f.write(traceback.format_exc())
        print("\n[!] 오류가 발생했습니다 — 원인을 ui_error.log 에 저장했습니다:")
        print("    " + p)
        traceback.print_exc()
        raise
