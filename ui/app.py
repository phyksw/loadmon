# -*- coding: utf-8 -*-
"""
app.py — LoadMonitor30 로컬 HTML UI (표준 라이브러리만).

  python ui\\app.py          또는  LoadMonitor30-UI.bat 더블클릭

탭: 대시보드(요약 시각화) · 주간/월간 리뷰(raw 근거가 들어간 기간 리뷰) · 상세 리뷰(업무별 딥다이브+연결성)
로컬 전용(127.0.0.1). 외부 전송 없음. Copilot 왕복만 사용자의 기존 세션으로 나간다.
"""
import csv
import glob
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
if ROOT not in sys.path:          # judge·aggregate 등 루트 모듈 임포트용
    sys.path.insert(0, ROOT)      # (ui\app.py 로 실행하면 sys.path[0]이 ui\ 라 루트가 안 잡힌다)
from progress import parse as parse_progress  # noqa: E402  (core 경로 등록 뒤에 임포트)
import lmname  # noqa: E402  — LM30 이름 단일원(작업·포트·Edge 프로필·%TEMP% 접두)

REPORT = os.path.join(ROOT, "report")
DATA = os.path.join(ROOT, "data")
NO_WIN = 0x08000000
VERSION = "v5.0"          # lm24-v5 — 팀 서버 IP·포트를 별도 설정(config\team_server.json)으로 분리 · 바꾸기는 LoadMonitor30-팀서버주소.bat 하나
LOCK = threading.Lock()
FREEZE_LOCK = threading.Lock()       # [보고서 만들기] 직렬화 — JOB 과 별개(사본에 '실행 중'이 굳지 않게)
JOB = {"running": False, "log": [], "step": "", "started": 0.0, "pid": 0,
       "phase": "", "done": 0, "total": 0, "phase_started": 0.0, "last_out": 0.0}


def kill_job():
    """실행 중인 분석 프로세스 트리(run→mine/judge→copilot_auto)를 통째로 종료.
    LM28: taskkill 대신 Job 째(core\\proc.kill_tree — 띄울 때 proc.attach 로 넣어 둔다). Job 에서 이탈한 전용 Edge 는
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
    프로세스를 띄우지 않는다(예전 시작·종료 정리는 매번 powershell 을 띄웠다 — W3-15). 로그인 대기 중이거나
    keepEdgeOpen 이면 닫지 않고, 사람이 띄운 Edge·LM24 의 Edge 는 표식이 없어 건드리지 않는다(P6).
    tidy=False — 닫기 전 Copilot 채팅 정리를 건너뛴다(콘솔 창 닫기 — 윈도가 몇 초만 준다).
    budget(LM30) — 닫기 전 정리(LM 이 연 채팅 다시 지우기 — sweep_owned)의 상한(초). 없으면 copilot_auto.SWEEP_SEC."""
    try:
        copilot_auto = _ca_mod()
        if not tidy:
            return copilot_auto.close_own_edge(None, reason, tidy=False)
        if budget is not None:
            return copilot_auto.close_own_edge(None, reason, budget=budget)
        return copilot_auto.close_own_edge(None, reason)
    except Exception as e:  # noqa: BLE001 - 정리 실패가 화면·종료를 막지 않는다
        return {"closed": False, "why": f"error:{type(e).__name__}"}


UI_SWEEP_SEC = 60          # LM30 — [중지]·대시보드 종료가 기다려 주는 채팅 정리 상한(초 · copilot_auto.SWEEP_UI_SEC 와 같다)
CHAT_SWEEP_SEC = 300       # LM30 — [LM이 연 Copilot 채팅 지우기] 의 상한(초 · copilot_auto.SWEEP_BUTTON_SEC 와 같다)
CHAT_SWEEP_NOTE = ("기록에 없는 채팅(예전 판이 연 것·직접 붙여 넣은 것)은 LM 것인지 확인할 수 없어 그대로 두었습니다")


def chat_job_run():
    r"""LM30(2026-10-21) — 화면 작업([니즈 후보 발굴]·[워크플로우 재분석]·[리뷰 코멘트 재생성]·[유사 항목 정리])의 실행 열쇠. 자식 프로세스에
    LM_CHAT_RUN 으로 넘기면 그 작업이 연 Copilot 채팅이 한 실행으로 묶인다(끝 한 줄 — job_chat_end)."""
    return f"job-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{int(time.time() * 1000) % 1000:03d}"


def job_chat_end(run, label=""):
    r"""LM30(2026-10-21) — 화면 작업이 끝난 뒤: LM 이 연 Copilot 채팅을 다시 지우고(copilot_auto.sweep_owned — 같은 프로세스 · 상한
    UI_SWEEP_SEC·3) 그 작업의 한 줄('Copilot 채팅: 이번 실행에서 연 N개 · 지운 M개 · 남긴 K개 (까닭: …)')을 진행 로그에 남긴다 → 그 줄 | "".
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
    r"""LM30(2026-10-21) — [LM이 연 Copilot 채팅 지우기]: LM 기록(owned[])에 있는 채팅만 다시 지운다(copilot_auto.sweep_owned — 같은 프로세스).
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
        out["line"] = "Copilot 채팅: LM 기록에 지울 채팅이 없습니다"
    elif out["login"] and not tried:
        out["ok"] = False
        out["line"] = "전용 Edge 창에서 로그인한 뒤 다시 누르세요(LM 은 로그인하지 않습니다 — 아무것도 지우지 않았습니다)"
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


def kill_copilot_edge():
    r"""(수동 진단용 — LM28 은 자동으로 부르지 않는다. 시작·종료·[중지] 는 close_edge 가 CDP 로 닫는다.)
    Copilot 왕복용 전용 Edge 를 명령줄 패턴으로 종료 —
    일반 Edge·LM24·LM28·LM29 의 전용 Edge 는 건드리지 않고 **이 설치본의** 프로필(<ROOT>\data\lm30_edge)로 뜬 것만.
    예전 패턴(프로필 폴더 이름만 비교)은 같은 PC 의 다른 판·다른 폴더 Edge 까지 죽였다(W3-03)."""
    prof = lmname.edge_profile(ROOT).lower().replace("'", "''")     # PS 작은따옴표 문자열 이스케이프
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                    "Where-Object {$_.CommandLine -and $_.CommandLine.ToLower().Contains('" + prof + "')} | "
                    "ForEach-Object {Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"],
                   capture_output=True, creationflags=NO_WIN, timeout=20)


def drop_foreign_profile():
    r"""다른 PC 에서 옮겨 온 폴더면 전용 Edge 프로필을 통째로 버린다(시작 시 1회).

    로그인 세션은 Local State 의 키가 DPAPI 로 '이 PC·이 계정' 에 묶여 있어 따라와도 살아나지
    않는다. 그런데 **죽은 세션이 남아 있는 쪽이 없는 쪽보다 나쁘다** — 사이트가 로그인 화면 대신
    오류 페이지를 주면 웹 수집기가 '로그인 필요(rc=2)' 가 아니라 '시간 초과(rc=1)' 로 끝나고
    화면에는 '화면이 뜨지 않았습니다(네트워크·차단?)' 라고 뜬다. 사용자는 네트워크 문제로 읽고
    넘어가고, 그 PC 의 메일·팀즈가 조용히 빈 채 폴더가 다음 PC 로 떠난다(그 PC 에서만 보이는
    신호라 다른 PC 가 메워 주지 못한다). 지우면 [AI 연결 진단] 이 새 프로필로 정상 로그인을 받는다.

    판정 신호는 archive_other_pc(run.py)가 쓰는 것과 같은 data\pc_name.txt 다. UI 는 그 파일을
    고치지 않으므로(고치는 쪽은 run.py) '폴더 복사 → UI 실행' 순서에서 정확히 한 번 발동한다.
    덤으로 도착 즉시 수백 MB 가 사라진다(실측 프로필 100~529MB).
    """
    try:
        prof = lmname.edge_profile(ROOT)       # <ROOT>\data\lm30_edge — 이 설치본의 전용 프로필만
        if not os.path.isdir(prof):
            return
        # 판정 기준은 run.py.archive_other_pc 와 **같아야 한다** — 한쪽만 '다른 PC' 라고 보면
        # 이름이 바뀌는 VDI 에서 접속할 때마다 프로필을 버려 매번 다시 로그인하게 된다.
        here = (os.environ.get("COMPUTERNAME") or "").strip()
        here_id = ""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                here_id = str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip()
        except (OSError, ImportError, IndexError, ValueError):
            here_id = ""

        def _read(fn):
            p = os.path.join(DATA, fn)
            if not os.path.exists(p):
                return ""
            with open(p, encoding="utf-8-sig") as f:
                return f.read().strip()

        prev, prev_id = _read("pc_name.txt"), _read("pc_id.txt")
        if prev_id and here_id:
            foreign = prev_id != here_id
        else:
            foreign = bool(prev and here and prev != here)
        if not foreign:
            return
        prev = prev or "이전 PC"
        n = b = 0
        for r, _d, fs in os.walk(prof):
            for fn in fs:
                try:
                    b += os.path.getsize(os.path.join(r, fn))
                    n += 1
                except OSError:
                    pass
        import shutil as _sh       # 모듈 수준에 없다 — 이 파일의 다른 삭제 경로와 같은 방식
        _sh.rmtree(prof, ignore_errors=True)
        if os.path.isdir(prof):     # 260자(MAX_PATH) 초과 경로는 \\?\ 가 있어야 지워진다
            _sh.rmtree("\\\\?\\" + os.path.abspath(prof), ignore_errors=True)
        log(f"[정리] 다른 PC({prev})에서 온 Copilot 로그인 세션은 이 PC 에서 쓸 수 없어 정리했습니다"
            f" — {n:,}개 {b / 1048576:.1f} MB 회수. [AI 연결 진단] 에서 한 번 로그인하시면 됩니다.")
    except OSError:
        pass


def cleanup_children():
    try:
        kill_job()
    except Exception:
        pass
    try:
        close_edge("ui_exit", budget=UI_SWEEP_SEC)
    except Exception:
        pass


# atexit.register(cleanup_children) 는 main() 안에서만 — 모듈을 임포트하는 쪽(freeze.py 의
# 얼린 보고서 굽기)이 끝날 때 Copilot 전용 Edge 를 죽이지 않게(임포트 부작용 제거).
PORT = [0]


# ── 창을 닫으면 작업도 멈춘다(LM28) ─────────────────────────────────────────────────────────
# 제보: "창을 꺼 버리면 끝났다고 생각하는데 뒤에서 계속 돌 수 있다". 대시보드(PAGE·TEAM_PAGE)는 10초마다 /api/alive 로
# '이 탭이 살아 있다'(탭 id·visibilityState)를 알리고, 닫히거나 다른 곳으로 떠날 때(pagehide) /api/bye 를 sendBeacon 으로 보낸다.
# 감시 스레드(main 에서만 — freeze.py 가 이 모듈을 임포트한다)가 ui_close_decision 으로 판정해 'exit' 면 [중지]+종료 정리와
# 같은 길(kill_job · 전용 Edge 닫기 — 채팅 정리 포함)로 작업을 멈추고 서버를 끝낸다. 팀 서버(teamserver.py)는 Job 밖이라 산다.
#   · 첫 /api/alive 전에는 판정하지 않는다(armed) — --no-browser·LM_NO_BROWSER·시험은 저절로 끝나지 않는다.
#   · 작별 뒤 CLOSE_GRACE 초는 기다린다 — 새로고침(F5)·이동은 작별 직후 새 탭이 다시 알린다.
#   · 모든 탭이 CLOSE_SILENCE 초 넘게 조용하면 닫힌 것으로 본다(브라우저째 강제 종료 — 작별이 못 온다). 숨긴·최소화한 탭은
#     Edge·Chrome 이 타이머를 1분에 1번까지 늦추므로 3분 — 더 짧으면 최소화한 대시보드를 죽인다.
#   · 잠든 탭(Edge '절전 탭'·Chrome 탭 동결 — 타이머가 아예 멈춘다)은 잠들 때 freeze 이벤트로 'frozen' 을 알린다 — CLOSE_ASLEEP 초까지
#     살아 있다고 본다(몇 시간짜리 분석을 탭이 잠들었다는 이유로 죽이지 않는다). 숨긴 탭은 1분에 1번은 알리므로 따로 봐 주지 않는다 —
#     브라우저째 꺼졌는데 '숨김' 이었다는 이유로 작업이 계속 돌면 이 기능의 뜻(닫으면 멈춘다)에 어긋난다.
#   · 작별한 탭 id 는 기억해 둔다(gone) — 탭을 닫을 때 visibilitychange 의 '숨김' 신호가 작별보다 늦게 도착해 닫힌 탭을 되살리지 않게.
#     bfcache 로 돌아온 탭(pageshow persisted)은 새 id 로 다시 알린다.
#   · PC 가 잠들었다 깨면(감시 루프가 CLOSE_RESUME_GAP 넘게 늦게 깸) 그동안 탭도 멈춰 있었다 — 시각을 그만큼 민다.
#   · LM28(2026-10-18) 사람이 화면을 볼 수 없는 동안(화면 보호기 · 잠금 · AWAY_IDLE_SEC 넘게 키보드·마우스 입력 없음 — _screen_away)의
#     조용함은 세지 않는다(탭 시각을 민다 — 작별 시각은 그대로라 창을 닫았으면 그대로 끝난다). 제보: "화면보호기로 꺼지는 경우가 있다" —
#     잠긴 화면에서 브라우저가 대시보드 탭을 얼리거나 버리면(신호 없음) 3분 뒤 작업째 끝냈다. 끝낼 때는 까닭을 last_run 과
#     report\ui_exit.json 에 남긴다(콘솔은 곧 닫혀 줄이 사라진다).
#   · LM28(2026-10-19) 알림·확인·입력 창(alert·confirm·prompt)이 열려 있는 동안 브라우저는 화면의 타이머를 멈춘다 — 10초 신호가 끊겨
#     3분 뒤 대시보드가 통째로 꺼졌고, 그 뒤 [데이터 리셋]은 닿을 곳이 없어 '리셋 실패'가 됐다(제보: 팀 서버 업로드 실패 알림을 띄워 둔 채
#     다른 프로그램에서 일하다 리셋). 화면이 창을 열기 직전에 'dialog'(알림 창이 열려 있음)를 알리므로 잠든 탭처럼 CLOSE_ASLEEP 까지 둔다.
#     작별(창 닫기)은 예전처럼 CLOSE_GRACE 뒤 끝난다.
#   · LM28(2026-10-19) 안전판 — 도는 작업도 굽는 보고서도 없으면 조용함만으로는 CLOSE_SILENCE_IDLE(30분) 뒤에야 끝낸다(멈출 작업이 없으니
#     서둘러 끝낼 까닭이 없다 · 작업이 돌면 예전처럼 3분 — 창을 닫았는데 뒤에서 도는 일을 막는 이 기능의 뜻은 그대로).
# 끄기: config.json 의 uiAutoExit=false(예전처럼 창을 닫아도 서버·작업이 계속 돈다).
CLOSE_GRACE = 20.0
CLOSE_SILENCE = 180.0
CLOSE_SILENCE_IDLE = 1800.0         # LM28(2026-10-19) 도는 작업·보고서 굽기가 없을 때의 조용함 상한(초) — ui_close_decision(busy=False)
CLOSE_ASLEEP = 4 * 3600.0
CLOSE_EVERY = 5.0
CLOSE_RESUME_GAP = 30.0
CLOSE_LOCK = threading.Lock()
UI_CLOSE = {"tabs": {}, "vis": {}, "gone": {}, "bye": 0.0, "armed": False}
CLOSE_LINE_BUSY = "[ui] 대시보드 창이 닫혀 실행 중인 작업을 멈추고 서버를 끝냅니다"
CLOSE_LINE_IDLE = "[ui] 대시보드 창이 닫혀 서버를 끝냅니다"
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
    """LM28(2026-10-19) — 지금 멈출 것이 있나(화면에서 띄운 작업이 돌거나 [보고서 만들기]가 굽는 중) → 창 닫힘 판정의 busy."""
    with LOCK:
        busy = bool(JOB["running"])
    return busy or FREEZE_LOCK.locked()


def _screen_away():
    """LM28(2026-10-18) — 지금 사람이 화면을 볼 수 없나 → 참/거짓. ① 화면 보호기가 도는 중(SPI_GETSCREENSAVERRUNNING) ② 잠금·암호 걸린
    화면 보호기·끊긴 원격(입력 데스크톱을 열 수 없음 — OpenInputDesktop) ③ AWAY_IDLE_SEC 넘게 키보드·마우스 입력 없음(GetLastInputInfo —
    화면 꺼짐 포함). ctypes 로만(프로세스를 띄우지 않는다 · 관리자 권한 없음). 윈도가 아니거나 읽기 오류면 거짓(예전 그대로)."""
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


def ui_close_decision(now, tabs, last_bye, armed, cfg=None, busy=True):
    """창 닫힘 판정(순수 함수) → ("keep"|"exit", 사유).
    tabs = {탭 id: 마지막 신호 시각} 또는 {탭 id: (시각, 상태)} — 상태 visible·hidden·frozen·dialog(작별한 탭은 이미 빠져 있다).
    last_bye = 마지막 작별 시각(없으면 0) · armed = 첫 신호를 받았나 · cfg = {on, grace, silence, silence_idle, asleep}(_close_cfg).
    busy = 멈출 작업이 있나(_ui_busy — 기본 참 = 예전 판정). LM28(2026-10-19): 거짓이면 조용함 상한이 silence_idle(30분)이고,
    알림 창이 열린 탭(dialog)은 잠든 탭(frozen)처럼 asleep 까지 둔다.
    사유: off · not_armed · alive · asleep · dialog(알림 창이 열려 있음) · grace(작별 뒤 새 탭 대기) · bye(작별 뒤 새 탭 없음) ·
    silence(모든 탭 조용 — 작업 중) · silence_idle(모든 탭 조용 — 도는 작업 없음)."""
    c = {"on": True, "grace": CLOSE_GRACE, "silence": CLOSE_SILENCE, "silence_idle": CLOSE_SILENCE_IDLE,
         "asleep": CLOSE_ASLEEP}
    c.update(cfg or {})
    if not c["on"]:
        return "keep", "off"
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
    """끝낸 까닭(한국어) — CLOSE_WHY_KO. 조용함으로 끝냈는데 알림 창이 열린 탭(dialog)이 있었으면 그것도 붙인다(LM28 2026-10-19)."""
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
    vis = vis if vis in CLOSE_VIS else "visible"           # LM28(2026-10-19) dialog = 알림 창이 열려 있음(화면이 열기 직전에 알린다)
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
    bye=False(LM28 2026-10-18 — 화면을 볼 수 없는 동안): 탭 시각만 민다 — 그동안 창을 닫았으면(작별) 그대로 CLOSE_GRACE 뒤 끝난다."""
    with CLOSE_LOCK:
        for k in list(UI_CLOSE["tabs"]):
            UI_CLOSE["tabs"][k] += gap
        if bye and UI_CLOSE["bye"]:
            UI_CLOSE["bye"] += gap


def _mark_last_run_stopped(job_started, note, report_dir=None):
    r"""작업을 멈췄으면 report\last_run.json 에 '중단(창 닫힘)' 단계를 붙인다 → 붙였나.
    이 작업(run.py)이 쓴 기록일 때만 — 작업 시작 뒤에 고쳐졌고 아직 끝나지 않은(finished 없음) 것. 워크플로우·리뷰 코멘트 같은
    다른 작업이 돌던 중이면 지난 실행 기록은 건드리지 않는다. 깨진 파일이면 두고, 바꿔 쓰기는 임시 파일 → os.replace."""
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
    r"""LM28(2026-10-18) — 대시보드 서버가 스스로 끝난 까닭을 report\ui_exit.json 에 남긴다(콘솔은 곧 닫혀 그 줄이 사라진다 — 다음에 켤 때
    화면·사진으로 본다). {t, why, why_ko, busy, away(지금 화면을 볼 수 없나), tabs[{age_s, vis}]} — 탭 id·글은 없다. 실패는 삼킨다."""
    now = time.time() if now is None else now
    rows = []
    for v in (tabs or {}).values():
        t, vis = (v[0], v[1]) if isinstance(v, (tuple, list)) else (v, "visible")
        try:
            rows.append({"age_s": int(max(0.0, now - float(t or 0.0))), "vis": str(vis)[:8]})
        except (TypeError, ValueError):
            continue
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "why": str(why), "why_ko": _close_why_ko(why, tabs),
           "busy": bool(busy), "away": bool(_screen_away()), "tabs": rows[:16]}
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
    r"""LM28(2026-10-19) — 지난번 대시보드가 스스로 끝났으면(report\ui_exit.json — _write_ui_exit) 그 까닭·시각 한 줄 → 문자열(없으면 "").
    대시보드를 다시 켤 때 진행 로그·콘솔에 한 번 남긴다(제보 사진 한 장으로 '왜 꺼졌나'를 본다). 한 번 알린 기록에는 seen 을 붙여
    다음 시작부터는 말하지 않는다(파일은 그대로 — 진단용). 깨졌거나 못 읽으면 ""(시작을 막지 않는다)."""
    p = os.path.join(report_dir or REPORT, "ui_exit.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(rec, dict) or rec.get("seen"):
        return ""
    why = str(rec.get("why_ko") or rec.get("why") or "까닭 모름")[:120]
    t = str(rec.get("t") or "")[:19]
    line = ("[ui] 지난번에는 대시보드가 스스로 끝났습니다 — 까닭: " + why + (f" ({t})" if t else "")
            + (" · 그때 돌던 작업도 멈췄습니다" if rec.get("busy") else ""))
    if mark:
        try:
            rec["seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
        except OSError:
            pass
    return line


def ui_close_exit(server, why, out=None, tabs=None, now=None):
    """판정이 'exit' — 콘솔에 한 줄을 남기고, 도는 작업을 [중지]와 같은 길로 멈추고(Job 째), 전용 Edge 를 닫고, 서버를 끝낸다.
    팀 서버(teamserver.py)는 Job 밖이라 그대로 산다(팀 전체가 쓴다). LM28(2026-10-18): 까닭(창 닫힘 · N분 넘게 화면 신호 없음)을 멈춘 작업의
    last_run 단계 글과 report\\ui_exit.json 에 남긴다."""
    say = out or (lambda s: print(s, flush=True))
    with LOCK:
        busy = bool(JOB["running"])
        had_pid = bool(JOB.get("pid"))
        started = float(JOB.get("started") or 0.0)
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
    if busy and had_pid:
        _mark_last_run_stopped(started, f"대시보드 창이 닫혀({why_ko}) 실행 중이던 작업을 멈췄습니다 — 지금까지의 결과는 "
                                        "report\\에 남아 있습니다")
    if server is not None:
        threading.Thread(target=server.shutdown, daemon=True).start()


def close_watch(server, c=None, every=CLOSE_EVERY, stop=None):
    """감시 루프(main 이 데몬 스레드로 띄운다) — every 초마다 판정, 'exit' 면 ui_close_exit 후 끝난다. stop: 시험용 Event."""
    c = _close_cfg() if c is None else c
    prev = time.time()
    while not (stop is not None and stop.is_set()):
        time.sleep(every)
        now = time.time()
        gap = now - prev
        if gap > every + CLOSE_RESUME_GAP:
            _close_shift(gap - every)
        elif c.get("away") and _screen_away():
            _close_shift(gap, bye=False)        # 화면을 볼 수 없는 동안의 조용함은 세지 않는다(LM28 2026-10-18)
        prev = now
        tabs, bye, armed = _close_snapshot()
        # LM28(2026-10-19): 도는 작업·굽는 보고서가 없으면 조용함 상한이 CLOSE_SILENCE_IDLE(30분) — 알림 창(dialog)은 잠든 탭처럼 둔다
        verdict, why = ui_close_decision(now, tabs, bye, armed, c, busy=_ui_busy())
        if verdict == "exit":
            ui_close_exit(server, why, tabs=tabs, now=now)
            return why
    return None


def awake_watch(stop=None, every=15.0, conf=None):
    """LM28(2026-10-18) — 대시보드에서 띄운 작업이 도는 동안 PC 가 절전(잠자기)에 들어가지 않게 한다(proc.keep_awake — 이 스레드 기준 ·
    화면 꺼짐·화면 보호기·잠금은 그대로). 작업이 끝나면 놓는다. 분석(run.py)은 스스로도 걸고, 이것은 [재분석]·Agentic·워크플로우·리뷰 코멘트처럼
    화면에서 따로 띄운 작업까지 덮는다. config.keepAwakeDuringRun=false 면 걸지 않는다. stop·conf: 시험용(Event · 설정 dict)."""
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
    """콘솔 창(LoadMonitor30-UI.bat)을 닫을 때(core\\proc.on_console_close) — 윈도가 주는 몇 초 안에 끝나는 것만 한다.
    Job 을 끝내고(작업 트리 — Job 안의 자식은 어차피 이 프로세스와 함께 끝난다), Job 밖에 남는 전용 Edge 를 채팅 정리 없이
    (tidy=False) 닫는다 — budget 초까지만 기다린다. 팀 서버는 건드리지 않는다. 예외를 내지 않는다."""
    try:
        with LOCK:
            busy = bool(JOB["running"])
            had_pid = bool(JOB.get("pid"))
            started = float(JOB.get("started") or 0.0)
        for fn in (kill_job, proc.kill_all):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        if busy and had_pid:
            _mark_last_run_stopped(started, "콘솔 창이 닫혀 실행 중이던 작업을 멈췄습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
        proc.run_within(lambda: close_edge("console_close", tidy=False), budget)
    except BaseException:  # noqa: BLE001 - 처리기는 예외를 내지 않는다(윈도 스레드 위에서 돈다)
        pass


TS_PID = os.path.join(REPORT, "teamserver.pid")
TS_LOG = os.path.join(REPORT, "teamserver.log")
# 팀 정적 보고서 — 경로 → 취합 폴더의 파일. 자기완결 문서라 same-origin 요청이 필요 없다;
# 업로드로 들어온 값의 이스케이프가 한 곳 새더라도 대시보드의 /api/* 를 부를 수 없게
# sandbox CSP 로 origin 을 떼어 서빙한다(teamserver.py 와 같은 문자열).
TEAM_FILES = {"/team/report": "team_report.html",
              "/team/full": "team_full_report.html", "/team/full_v3": "team_full_report_v3.html"}
REPORT_HEADERS = {"Content-Security-Policy":
                  "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox",
                  "X-Content-Type-Options": "nosniff"}


def team_cache_files():
    """취합 폴더 루트의 캐시 파일 이름(단일 진실 = team_report.CACHE_FILES)"""
    try:
        import team_report
        return tuple(team_report.CACHE_FILES)
    except Exception:
        return ("team_aliases.json", "team_series.json", "team_pjclass.json",
                "team_detail_groups.json")


def agentic_view(a):
    """agentic_<tag>.json → 화면(Agentic AI 탭)에 보낼 꼴 — LM29부터 니즈 후보만. agentic.needs_only 가 LM28 이 남긴 파일의
    과제 매칭(match)·오할당(misassigned)·MM 실측(mm_recalc) 키를 버린다. agentic 을 못 읽으면 그 키만 직접 지운다."""
    try:
        import agentic
        return agentic.needs_only(a)
    except Exception:  # noqa: BLE001 - 모듈 하나 때문에 탭이 죽지 않게
        return {k: v for k, v in (a or {}).items() if k not in ("match", "misassigned", "mm_recalc", "axes")}


def make_reports():
    """[보고서 만들기] — freeze.make_all 을 이 프로세스 안에서(자기 포트로 GET 해 화면을 굽는다).
    JOB 을 running 으로 만들지 않는다 — 사본의 /api/status running·/api/dash stale 가 참으로
    굳기 때문(FREEZE_LOCK 으로만 직렬화). freeze 모듈이 없는 판이면 옛 report_out 서브프로세스."""
    sp = latest_signals()
    mp = latest("mm_meta_*.json")
    tag = (os.path.basename(sp)[len("signals_"):-len(".csv")] if sp
           else (os.path.basename(mp)[len("mm_meta_"):-len(".json")] if mp else ""))
    if not tag:
        return {"ok": False, "error": "no result"}
    try:
        import freeze
    except ImportError:
        freeze = None
    if freeze is not None:
        try:
            r = freeze.make_all(tag, base_url=f"http://127.0.0.1:{PORT[0]}", full=True) or {}
            for f in (r.get("files") or []):
                log(f"[보고서] {os.path.basename(str(f))}")
            r.setdefault("ok", True)
            r.setdefault("tag", tag)
            return r
        except Exception as e:
            log(f"[보고서] 생성 실패: {type(e).__name__}: {e}")
            return {"ok": False, "error": "리포트 생성 실패",
                    "hint": f"{type(e).__name__}: {str(e)[:200]}"}
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "report_out.py")],
                           capture_output=True, timeout=120, cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                    PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
    except (subprocess.SubprocessError, OSError) as e:
        return {"ok": False, "error": "리포트 생성 실패", "hint": f"{type(e).__name__}"}
    txt = (p.stdout or b"").decode("utf-8", "replace").strip()
    for ln in txt.splitlines():
        if ln and not ln.startswith("{"):
            log(ln)
    try:
        r = json.loads(txt.splitlines()[-1])
        if r.get("ok") and not r.get("files"):
            r["files"] = [x for x in (r.get("html"), r.get("doc")) if x]
        return r
    except Exception:
        return {"ok": False, "error": "리포트 생성 실패", "hint": txt[-200:]}


def team_share():
    r"""팀 취합이 읽고 쓸 폴더 하나 — (경로, 출처).

    설정(teamShareDir)이 우선. 비어 있으면 이 PC 의 teamdata\ 를 본다(로컬에서 팀 서버를
    돌려 받은 경우). 보기·정리·되돌리기·리포트가 서로 다른 폴더를 보면 '정리했는데 화면은
    그대로'가 된다 — 그래서 이 한 곳에서만 정한다."""
    return team_share_ex()[:2]


def local_teamdata_n():
    r"""이 PC 의 teamdata\ 에 들어 있는 사람 수 — 갈아탈지 물어볼 근거"""
    td = os.path.join(ROOT, "teamdata")
    try:
        if os.path.isdir(td):
            return sum(1 for n in os.listdir(td)
                       if os.path.exists(os.path.join(td, n, "member.json")))
    except OSError:
        pass
    return 0


def team_share_ex():
    r"""(경로, 출처, 문제, 이 PC teamdata 인원수).

    설정한 폴더가 잠깐 안 잡힌다고 다른 폴더로 몰래 갈아타면, 화면의 명단이
    통째로 바뀐다 — 사용자가 본 '초기화'가 그것이었다. 그래서 자리는 고정하고
    문제만 알린다: unreachable(못 읽음) / empty(이 PC teamdata 도 비었음)."""
    d = (cfg().get("teamShareDir") or "").strip()
    n = local_teamdata_n()
    if d:
        return d, "설정", ("" if os.path.isdir(d) else "unreachable"), n
    return (os.path.join(ROOT, "teamdata"), "이 PC 의 teamdata (팀 서버로 받은 것)",
            ("" if n else "empty"), n)


def _ta():
    r"""팀 서버 주소 단일원(core\teamaddr.py — 설치 폴더의 config\team_server.json). 부를 때마다 파일을 다시
    읽어 LoadMonitor30-팀서버주소.bat 에서 바꾼 값이 곧바로 반영된다. 화면은 주소를 보여 주기만 하고 바꾸지
    않는다(사용자 지시: 바꾸는 곳은 별도 bat 하나). v5 이전처럼 config.teamServerUrl 을 직접 쪼개지 않는다."""
    import teamaddr
    return teamaddr


def _team_port():
    """설정된 팀 서버 포트(core\\teamaddr.py)"""
    return _ta().load(ROOT).port


def _alt_port_base():
    """임시 포트 범위를 피할 때 권하는 번호의 시작 — 기본 포트 + 10000."""
    return _ta().DEFAULT_PORT + 10000


def _port_open(port, host="127.0.0.1", timeout=0.25):
    r"""그 포트가 열려 있는가 — 루프백이라 열려 있으면 즉시 답한다.

    닫힌 포트에서는 이 시간을 그대로 다 쓴다(윈도우가 즉시 거부를 안 주는 경우가 있다).
    팀 서버를 안 켠 평상시가 바로 그 경우라, 짧게 잡아야 화면이 늦게 뜨지 않는다."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def local_ips():
    """이 PC 의 주소 — 팀원에게 알려 줄 값. 세는 규칙은 core\\teamaddr.local_ipv4s 한 곳(팀 서버의 '이 PC 인가' 판정과 같은 값)."""
    return _ta().local_ipv4s()


TS_TOKEN = os.path.join(REPORT, "teamserver.token")
# 팀 서버(teamserver.py)가 report\ 에 두는 제 파일 — 기록·pid·증명 토큰. [데이터 리셋]은 지우지 않는다(LM28 2026-10-19 — 켜진 서버의
# pid·토큰을 지우면 화면이 '내 서버' 임을 증명하지 못하고, 기록은 서버가 열고 있어 늘 '못 지운 파일' 로 남았다).
TS_FILES = tuple(os.path.basename(p) for p in (TS_LOG, TS_PID, TS_TOKEN))


def _my_token():
    r"""이 폴더의 팀 서버가 켜질 때 남긴 증명 문자열.

    신원 응답(JSON)은 아무나 흉내낼 수 있다. 이 토큰은 내 report\ 폴더를 읽을 수 있어야
    알 수 있으므로 '같은 계정·같은 폴더' 의 증명이 된다."""
    try:
        with open(TS_TOKEN, encoding="utf-8") as f:
            return (f.read() or "").strip()
    except OSError:
        return ""


def _http_json(port, path, timeout=2):
    """127.0.0.1:port 의 path 를 GET 해서 JSON 으로 (실패하면 빈 dict)"""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read(400000)
        c.close()
        if r.status != 200:
            return {}
        o = json.loads(body.decode("utf-8", "replace"))
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError, http.client.HTTPException):
        return {}


def _ts_identity(port):
    r"""포트를 잡고 있는 것이 무엇인지 물어본다 — 문구를 고르기 위한 것이지, 죽일 근거가 아니다.

    LM20 팀 서버는 /api/whoami 로 root/store/token 을 답한다. **LM18·LM19 에는 그 경로가 없어**
    404 가 오는데, 그것을 '남의 프로그램' 이라 부르면 사용자가 손쓸 수 없다(실측 제보).
    그래서 구버전이 답하는 /api/team 의 모양으로 'LoadMonitor 팀 서버(구버전)' 까지 알아본다.
    응답은 위조될 수 있으므로 여기서 얻은 것으로 프로세스를 종료하지 않는다 — 종료 판단은
    _proc_info() 가 읽은 OS 사실(명령줄·소유·이름)로만 한다."""
    o = _http_json(port, "/api/whoami")
    if o.get("root"):
        return {"kind": "lm20", "root": str(o.get("root") or ""),
                "store": str(o.get("store") or ""), "pid": int(o.get("pid") or 0),
                "token": str(o.get("token") or "")}
    t = _http_json(port, "/api/team")
    if isinstance(t.get("members"), list) and ("uploads" in t or "agg_note" in t):
        # 구버전 — 어느 폴더인지는 알 수 없다(그 빌드가 말해 주지 않는다)
        return {"kind": "legacy", "root": "", "store": "", "pid": 0, "token": ""}
    return {}


# 어떤 경우에도 종료하지 않는다 — 포트 하나 때문에 PC 를 망가뜨릴 수는 없다
PROTECTED = {
    "system", "system idle process", "registry", "memory compression", "idle",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe",
    "lsaiso.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "explorer.exe",
    "logonui.exe", "spoolsv.exe", "msmpeng.exe", "wudfhost.exe", "sihost.exe",
    "ctfmon.exe", "runtimebroker.exe", "taskhostw.exe", "searchindexer.exe",
    "searchhost.exe", "dllhost.exe", "conhost.exe", "audiodg.exe",
}


def _listeners(port):
    r"""그 포트를 LISTENING 으로 쥔 pid 전부. 알아내지 못했으면 None.

    · '-p TCP' 를 쓰지 않는다 — 그 옵션은 IPv6 표를 통째로 빼서, IPv6 로만 열린 포트를
      '아무도 안 쓴다' 로 보이게 만든다(실측: IPv6 행 0/166).
    · 한 포트에 리스너가 둘일 수 있다(IPv4·IPv6 가 서로 다른 프로세스). 전부 돌려준다.
    · **못 알아낸 것과 아무도 없는 것을 구분한다** — 둘을 0 으로 뭉치면 강제 종료가
      조용히 아무것도 하지 않고 '실패' 만 남긴다."""
    got = False
    out = []
    try:
        p = subprocess.run(["netstat", "-ano"], capture_output=True,
                           timeout=25, creationflags=NO_WIN)
        # 한국어 헤더만 cp949 이고 데이터 행은 순수 ASCII 다 — ascii 로 읽어 의도를 못박는다
        txt = (p.stdout or b"").decode("ascii", "replace")
        if p.returncode == 0 and txt.strip():
            got = True
            for ln in txt.splitlines():
                f = ln.split()
                if len(f) >= 5 and f[0].upper() == "TCP" and f[3].upper() == "LISTENING" \
                        and f[1].rsplit(":", 1)[-1] == str(port):
                    try:
                        if int(f[4]) not in out:
                            out.append(int(f[4]))
                    except ValueError:
                        pass
    except (OSError, subprocess.TimeoutExpired):
        pass
    if got:
        # netstat 이 정상으로 답했으면 '아무도 없다' 도 답이다 — 여기서 끝낸다.
        # 예전에는 빈 결과일 때마다 PowerShell 폴백까지 가서 평상시 조회가 1.4초씩 걸렸다.
        return out
    try:                    # netstat 이 막히거나(EDR) 표기가 달라도 여기서 건진다
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
                            "-ErrorAction SilentlyContinue).OwningProcess"],
                           capture_output=True, timeout=30, creationflags=NO_WIN)
        if p.returncode == 0:
            got = True
            for ln in (p.stdout or b"").decode("utf-8", "replace").split():
                try:
                    if int(ln) not in out:
                        out.append(int(ln))
                except ValueError:
                    pass
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out if got else None


def _pid_of_port(port):
    """LISTENING 중인 포트의 주인 pid 하나 (없거나 모르면 0)"""
    lis = _listeners(port)
    return lis[0] if lis else 0


def _proc_info(pids):
    r"""pid 들의 이름·경로·명령줄·소유 계정 — '무엇을 죽이는지' 를 사람이 보게 하기 위한 것.

    다른 계정 소유면 CommandLine·ExecutablePath 가 NULL 로 온다(실측). 그때 '팀 서버가 아니다'
    라고 단정하면 진짜 우리 서버조차 못 끄게 된다 — 그래서 '확인 불가' 를 그대로 전한다."""
    pids = [int(x) for x in (pids or []) if x]
    if not pids:
        return []
    filt = " or ".join(f"ProcessId={x}" for x in pids)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"@(Get-CimInstance Win32_Process -Filter '{filt}' "
                            "-ErrorAction SilentlyContinue | ForEach-Object { $o = $_ | "
                            "Invoke-CimMethod -MethodName GetOwner -ErrorAction SilentlyContinue; "
                            "[PSCustomObject]@{ ProcessId=$_.ProcessId; Name=$_.Name; "
                            "ExecutablePath=$_.ExecutablePath; CommandLine=$_.CommandLine; "
                            "Owner=$(if($o -and $o.ReturnValue -eq 0){$o.User}else{''}) } }) "
                            "| ConvertTo-Json -Compress"],
                           capture_output=True, timeout=40, creationflags=NO_WIN)
        raw = (p.stdout or b"").decode("utf-8", "replace").strip()
        o = json.loads(raw) if raw else []
        if isinstance(o, dict):
            o = [o]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        o = []
    seen = {}
    for x in o:
        if isinstance(x, dict):
            try:
                seen[int(x.get("ProcessId") or 0)] = x
            except (TypeError, ValueError):
                pass
    me = os.getpid()
    try:
        parent = os.getppid()
    except OSError:
        parent = 0
    out = []
    for pid in pids:
        x = seen.get(pid) or {}
        name = str(x.get("Name") or "")
        cmd = str(x.get("CommandLine") or "")
        exe = str(x.get("ExecutablePath") or "")
        owner = str(x.get("Owner") or "")
        readable = bool(cmd or exe)
        out.append({
            "pid": pid,
            "name": name or "(확인 불가)",
            "exe": exe,
            "cmd": cmd[:300],
            "owner": owner,
            "readable": readable,
            # 팀 서버 여부는 OS 사실로만 본다 — 네트워크 응답은 위조될 수 있다
            "teamserver": "teamserver.py" in cmd,
            "self": pid in (me, parent),
            # 이름을 못 읽었으면(다른 계정·보호) 종료 대상에서 뺀다 — 모르면 죽이지 않는다
            "protected": (not name) or name.lower() in PROTECTED or pid <= 4
                         or pid in (me, parent) or not readable,
        })
    return out


def _kill(pid):
    r"""그 pid 하나만 종료 — (성공, 종료코드, 메시지).

    /T(자식까지)를 쓰지 않는다. 대상은 언제나 '그 포트를 LISTENING 하는 프로세스' 하나이고,
    pid 를 잘못 집었을 때 /T 는 보험이 아니라 **피해 확대 장치**다(자식은 아무 검사도 안 거친다).
    taskkill 의 오류 문구는 한국어라 문자열로 판정하지 않는다 — 종료 코드만 본다."""
    try:
        p = subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                           capture_output=True, timeout=30, creationflags=NO_WIN)
        msg = ((p.stdout or b"") + (p.stderr or b"")).decode("cp949", "replace").strip()
        return p.returncode == 0, p.returncode, msg[:200]
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return False, -1, type(e).__name__


def _is_teamserver(pid):
    """정말 팀 서버인가 — True/False, 읽을 수 없으면 None(다른 계정일 수 있다)"""
    if not pid:
        return False
    inf = _proc_info([pid])
    if not inf:
        return None
    x = inf[0]
    return x["teamserver"] if x["readable"] else None


_NETSH = {}                     # 예약 범위·임시 범위는 재부팅 전에는 거의 안 바뀐다


def _reserved_ranges():
    """윈도우가 예약해 둔 TCP 포트 구간들 — 프로세스마다 한 번만 읽는다"""
    if "rsv" in _NETSH:
        return _NETSH["rsv"]
    out = []
    try:
        p = subprocess.run(["netsh", "interface", "ipv4", "show", "excludedportrange",
                            "protocol=tcp"], capture_output=True, timeout=25,
                           creationflags=NO_WIN)
        t = (p.stdout or b"").decode("cp949", "replace")
        out = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s+(\d+)", t)]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        out = []
    _NETSH["rsv"] = out
    return out


def _port_reserved(port):
    r"""윈도우가 그 포트를 예약(제외 범위)했는가 — 걸리면 아무도 안 잡아도 bind 가 실패한다."""
    for a, b in _reserved_ranges():
        if a <= int(port) <= b:
            return f"{a}~{b}"
    return ""


def _dyn_range():
    r"""나가는 연결에 임시로 배정되는 포트 범위 — (시작, 끝).

    이 PC 실측: 1024~15000 이었다(윈도우 기본 49152~65535 가 아니다). 팀 포트가 이 범위 안이면
    아무 프로그램의 '바깥으로 나가는 연결' 이 그 번호를 잠깐 차지해 서버가 못 뜬다.
    이때 주인은 LISTEN 이 아니라 나가는 연결이라 강제 종료 대상이 아니다 — 번호를 옮겨야 한다."""
    if "dyn" in _NETSH:
        return _NETSH["dyn"]
    out = (0, 0)
    try:
        p = subprocess.run(["netsh", "interface", "ipv4", "show", "dynamicport", "tcp"],
                           capture_output=True, timeout=25, creationflags=NO_WIN)
        t = (p.stdout or b"").decode("cp949", "replace")
        nums = [int(x) for x in re.findall(r":\s*(\d+)", t)]
        if len(nums) >= 2:
            out = (nums[0], nums[0] + nums[1] - 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        out = (0, 0)
    _NETSH["dyn"] = out
    return out


def _bind_free(port):
    r"""정말 빈 포트인가 — (가능, 사유).

    SO_REUSEADDR 을 절대 켜지 않는다. 윈도우에서는 그 옵션이 살아 있는 리스너 위에
    덧바인딩을 허용해서, 아무도 죽이지 않았는데 '가동 성공' 이라 말하고 업로드는 계속
    남의 서버로 가는 최악의 상태를 만든다(실측). 0.0.0.0 과 127.0.0.1 둘 다 본다."""
    for host in ("0.0.0.0", "127.0.0.1"):
        so = socket.socket()
        try:
            so.bind((host, int(port)))
        except OSError as e:
            return False, f"WinError {getattr(e, 'winerror', 0) or e.errno}"
        finally:
            so.close()
    return True, ""


def _ts_ask_shutdown(port):
    """정상 종료 요청 — 서버가 스스로 닫는다(누가 띄웠든 통한다)"""
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/api/shutdown", body=b"{}",
                  headers={"Content-Type": "application/json", "Content-Length": "2"})
        ok = c.getresponse().status == 200
        c.close()
        return ok
    except (OSError, http.client.HTTPException):
        return False


def _ts_wait_closed(port, tries=20):
    for _ in range(tries):
        if not _port_open(port):
            return True
        time.sleep(0.3)
    return not _port_open(port)


def _suggest_port(cur):
    r"""충돌을 안 겪을 만한 번호 하나 — 임시 포트 범위와 대시보드 대역을 피한다.

    이 PC 실측처럼 임시 포트 범위가 1024~15000 이면 9310 은 그 안이라 언제든 다시 뺏긴다."""
    lo, hi = _dyn_range()
    base = max(hi + 1, _alt_port_base()) if (lo and lo <= cur <= hi) else cur
    for p in range(int(base), int(base) + 40):
        if p == PORT[0] or p in lmname.UI_PORTS:   # 대시보드 자신의 대역(lmname.UI_PORTS)은 피한다
            continue
        if _port_reserved(p):
            continue
        if _bind_free(p)[0]:
            return p
    return 0


def _same_root(r, root=None):
    """신원 응답의 root 가 이 설치 폴더인가(대소문자·구분자 무시)"""
    if not r:
        return False
    return os.path.normcase(os.path.abspath(str(r))) == os.path.normcase(os.path.abspath(root or ROOT))


def _take_policy(ident, occ, root=None):
    r"""[포트 가져오기] 허용 — 'one_click' 또는 'no'(W3-08).

    LM28 은 LM24 와 기본 포트(9310)를 함께 쓴다(업로드 호환 — 바꾸지 않는다). 예전 규칙(리스너가 모두 teamserver.py 면
    한 번에 종료)은 같은 PC 의 **LM24 팀 서버**까지 내렸다. 이제 신원 응답(/api/whoami)의 root 가 이 설치 폴더일 때만
    (= 이 폴더의 옛 서버가 토큰·pid 증명 없이 남은 경우) 끈다. 그때도 종료 판단은 OS 사실로만 한다 — 리스너가 모두
    teamserver.py 이고 보호 대상이 아닐 것. 다른 폴더(LM24 포함)·구버전·남의 프로그램은 끄지 않고, 화면이
    LoadMonitor30-팀서버주소.bat 의 대체 포트를 제안만 한다(LM27 portdiag '제안만, 남의 프로세스는 안 죽임')."""
    if not occ or not _same_root((ident or {}).get("root"), root):
        return "no"
    if any(x.get("protected") for x in occ) or not all(x.get("teamserver") for x in occ):
        return "no"
    return "one_click"


def teamserver_status():
    port = _team_port()
    lis = _listeners(port)                      # None = 알아내지 못함
    open_ = _port_open(port) or bool(lis)       # 특정 NIC 에만 붙은 리스너도 놓치지 않는다
    ident = _ts_identity(port) if open_ else {}
    same_root = _same_root(ident.get("root"))
    tok = _my_token()
    # '내 서버' 의 증명은 두 가지 — 내 report\ 의 토큰을 알거나, 그 pid 가 실제 리스너 목록에 있거나.
    # 신원 응답만 믿으면 그 포트에 먼저 붙은 아무 프로그램이나 우리 행세를 할 수 있다(반박 검증).
    proven = bool(tok) and ident.get("token") == tok
    listed = bool(lis) and int(ident.get("pid") or 0) in lis
    running = same_root and (proven or listed)
    pid = int(ident.get("pid") or 0) if ident else 0
    if not pid:
        try:
            with open(TS_PID, encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
        except (OSError, ValueError):
            pid = 0
    occ, kind = [], "none"
    if running:
        kind = "mine"
    elif open_:
        # 무엇이 쥐고 있는지 지금 알아 둔다 — 화면이 '다른 프로그램' 대신 이름을 말하게
        occ = _proc_info(lis or [])
        if lis is None:
            kind = "unreadable"
        elif not lis:
            kind = "hidden"             # 포트는 막혔는데 LISTEN 하는 주인이 없다
        elif ident.get("kind") == "lm20":
            # 신원을 밝힌 현행 서버가 먼저다 — 명령줄에도 teamserver.py 가 있으므로
            # 순서를 뒤집으면 다른 폴더의 현행 서버가 '예전 버전' 으로 불린다
            kind = "other_lm"
        elif ident.get("kind") == "legacy" or any(x["teamserver"] for x in occ):
            kind = "legacy_lm"
        else:
            kind = "unknown"
    # 강제로 가져올 수 있는가 — whoami.root 가 이 폴더일 때만, 그리고 OS 사실(명령줄·보호 목록)로 확인될 때만(W3-08)
    take = _take_policy(ident, occ)
    tail = ""
    try:
        with open(TS_LOG, encoding="utf-8", errors="replace") as f:
            tail = " / ".join([x.strip() for x in f.readlines()[-3:] if x.strip()])[:300]
    except OSError:
        pass
    ta = _ta()
    a = ta.load(ROOT)
    ips = local_ips()
    akind, anote = ta.relation(a, ips)
    return {"ok": True, "running": running, "port": port, "pid": pid if running else 0,
            "urls": [f"http://{ip}:{port}" for ip in ips], "log": tail,
            # 설정된 서버 주소(설치 폴더의 config\team_server.json) — 팀원은 분석 후 이 주소로 올린다.
            # 화면은 보여 주기만 한다(바꾸는 곳은 LoadMonitor30-팀서버주소.bat).
            "host": a.host, "upload_url": a.url, "addr_kind": akind, "addr_note": anote,
            "addr_warnings": a.warnings, "edit_bat": ta.EDIT_BAT,
            # 포트는 열렸는데 내 서버가 아닐 때 — 화면이 사실대로 말할 수 있게
            "occupied": bool(open_ and not running),
            "kind": kind, "occupant": occ, "take": take,
            # 후보 포트를 실제로 bind 해 보는 계산이라, 막혔을 때만 한다
            "suggest_port": _suggest_port(port) if kind not in ("none", "mine") else 0,
            "foreign_root": "" if running else str(ident.get("root") or ""),
            "store": str(ident.get("store") or "") if running else "",
            "other_store": "" if running else str(ident.get("store") or "")}


def _save_cfg(key, val):
    r"""config\config.json 의 값 하나를 원자적으로 고친다(설명 키·다른 값은 보존).

    쓰다 만 config 는 화면 전체에 '설정이 없다'로 읽힌다 — 사용자가 말한 그 '초기화'다.
    LM30(2026-10-19) key 가 튜플이면 중첩 경로(('attendance', 'gerp', 'url')) — _save_cfg_many 와 같다."""
    return _save_cfg_many([(key, val)])


def _save_cfg_many(updates):
    r"""config\config.json 의 값 여러 개를 한 번에 원자적으로 고친다 → 썼나(LM30 2026-10-19 — GERP 켜기·끄기는 enabled·url 을 함께).
    updates = [(키 | (키, 키, …), 값)] — 중첩 경로의 중간 블록이 없거나 객체가 아니면 새 블록으로 만든다. 다른 키·설명 키는 그대로,
    파일 앞의 BOM 도 그대로 둔다(배포 config 는 UTF-8 BOM — 예전에는 쓰고 나면 BOM 이 사라졌다). 임시 파일에 쓴 뒤 바꿔 끼운다."""
    p = os.path.join(ROOT, "config", "config.json")
    tmp = p + ".tmp"
    try:
        with open(p, "rb") as f:
            raw = f.read()
        bom = raw.startswith(b"\xef\xbb\xbf")
        c = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(c, dict):
            return False
        for key, val in updates:
            path = [str(k) for k in key] if isinstance(key, (list, tuple)) else [str(key)]
            cur = c
            for k in path[:-1]:
                if not isinstance(cur.get(k), dict):
                    cur[k] = {}
                cur = cur[k]
            cur[path[-1]] = val
        with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except (OSError, ValueError):
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _addr_payload():
    r"""화면에 줄 팀 서버 주소(보여 주기만) — 값·출처·경고·이 PC 와의 관계. 바꾸는 곳은 LoadMonitor30-팀서버주소.bat."""
    ta = _ta()
    a = ta.load(ROOT)
    akind, anote = ta.relation(a, local_ips())
    return dict(a.as_dict(), addr_kind=akind, addr_note=anote)


def log(msg):
    with LOCK:
        JOB["log"].append(time.strftime("[%H:%M:%S] ") + msg)
        del JOB["log"][:-400]


def cfg():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def _rows(path):
    """수집 CSV는 엑셀로 열었다 CP949로 재저장되는 일이 흔하다 — 한 파일 때문에
    대시보드 전체가 죽지 않게 관대하게 읽는다(UnicodeDecodeError는 ValueError 계열)."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f))
    except (OSError, ValueError, csv.Error):      # csv.Error: 깨진 따옴표 뒤 13만 자 넘는 필드 — 한 파일이 /api/dash 를 죽이지 않게
        return []


def _data_roots():
    r"""본 수집 폴더 + data\추가PC\* 보관 폴더들. core.extract._data_roots 와 **같은 목록**이어야 한다.

    폴더째 다른 PC 로 옮기면 run.py 가 지난 PC 수집물을 data\추가PC\<지난 PC>\ 로
    옮긴다. 분석(core.extract)은 그것을 합쳐 세는데 **화면은 본 폴더만 봤다** — 그것이
    이동 직후 화면을 빈칸으로 만들었다(실측: 기간 인식이 ['2026-01-03','2026-09-10'] → ['','']
    로 무너지면서 추이가 '오늘 기준 13주' 로 떨어지고 막대 9개월치가 통째 사라졌다)."""
    roots = [DATA]
    base = os.path.join(DATA, "추가PC")
    try:
        if os.path.isdir(base):
            roots += sorted(os.path.join(base, n) for n in os.listdir(base)
                            if os.path.isdir(os.path.join(base, n)))
    except OSError:
        pass
    return roots


def _paths_multi(rel):
    r"""모든 뿌리에서 같은 상대경로인 파일 경로 목록(rel 은 '/' 또는 와일드카드 포함)."""
    parts = [x for x in str(rel).replace(chr(92), "/").split("/") if x]
    out = []
    for rt in _data_roots():
        p = os.path.join(rt, *parts)
        out += sorted(glob.glob(p)) if ("*" in p or "?" in p) else ([p] if os.path.exists(p) else [])
    return out


def _rows_multi(rel):
    r"""본 폴더 + 추가PC 를 이어붙인 CSV 행. 중복 제거는 하지 않는다 —
    여기 쓰는 곳은 '언제부터 언제까지 자료가 있는가'와 '하루 상한 8건' 뿐이다."""
    rows = []
    for p in _paths_multi(rel):
        rows += _rows(p)
    return rows


def _mtime(p):
    """리셋·재분석과 경합해도 죽지 않는 mtime — 파일이 사라졌으면 0"""
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _has_collected():
    r"""data\ 에 수집물이 있는가 — '수집은 했는데 분석을 안 했다' 를 가리기 위한 것."""
    try:
        d = os.path.join(ROOT, "data")
        for n in os.listdir(d):
            if n.endswith(".csv") and os.path.getsize(os.path.join(d, n)) > 200:
                return True
        sub = os.path.join(d, "추가PC")
        return os.path.isdir(sub) and bool(os.listdir(sub))
    except OSError:
        return False


class _Done(Exception):
    """이미 답을 얻었다는 신호 — 폴백 경로를 건너뛴다"""


def _stage_note(stage):
    """최근 실행(last_run.json)에서 해당 단계의 결과 한 줄 - 탭이 비어 있을 때 이유를 말한다.
    실측: 자동 실행이 '안 됐다'고 보였던 두 번 모두, 실제로는 실패/미실행 기록이 있었는데
    화면이 그것을 보여주지 않았다."""
    try:
        lr = json.load(open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    # 손으로 고쳤거나 쓰다 만 last_run.json 하나로 화면 전체가 죽지 않게 한다.
    # (형태가 어긋나면 예외가 라우트를 응답 없이 끊어 '탭이 비어 보이는' 증상이 된다 — 실측)
    if not isinstance(lr, dict):
        return ""
    st = {x.get("name"): x for x in (lr.get("stages") or []) if isinstance(x, dict)}
    s = st.get(stage)
    if not s:
        if st.get("AI 판정") is None and lr.get("started"):
            return "최근 실행은 AI 판정 단계에 도달하지 못했습니다"
        return "최근 실행에 이 단계 기록이 없습니다 (AI 정제를 끄고 실행했을 수 있음)"
    if s.get("ok"):
        return f"최근 실행에서 정상 완료 ({lr.get('finished') or lr.get('started') or ''})"
    return f"최근 실행에서 실패: {s.get('note') or '사유 미기록'}"


def _stage_kind(stage, tag=None):
    r"""그 단계가 왜 결과를 남기지 못했나 — 화면이 '다음에 무엇을 하라' 를 고를 수 있게 갈래를 준다.
    stalled(정체로 중단) · budget(시간 예산) · skipped(앞 단계 실패로 건너뜀) · failed(왕복 실패) ·
    none(기록 없음) · ok(정상 완료로 기록됨 — 결과 파일이 없으면 기간이 다른 것이다).
    제보: "에이전틱이 안 만들어졌습니다 — 정체되어 스킵된 걸까요?" 를 화면이 바로 답하게.
    v3: 상태 파일(stage_state)이 있으면 **데이터로** 답한다 — 한국어 note 부분 문자열 분류는
    구판 기록용 폴백으로만 남는다(문구를 다듬으면 분류가 깨지던 구조의 종식 · 구조 감사 4계층).
    LM28: stop.kind throttle(Copilot 사용량 제한 — 바로 다시 눌러도 같은 벽) → throttle · gate(개인정보 관문에 걸린 것만 남음 —
    조치 불필요) → gate · fail·gain·fatal·login·lock → failed."""
    _sid = {"AI 판정": "judge", "AI 정제": "refine", "Agentic 니즈 발굴": "agentic",
            "워크플로우 분석": "flow"}.get(stage)
    if _sid:
        try:
            from stage_state import read_latest
            from stage_state import read_state
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
    (값이 있는 키만). 결과 파일이 없거나 흐름이 비었을 때 화면이 '왜' 를 빨간 줄로 먼저 말하게 한다 — 예전에는 사유가 상태
    파일에만 남아 화면은 '분석이 없습니다' 한 줄과 갈래 문구뿐이었다(진단 D: 담당자 워크플로우 간헐 미생성)."""
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
    r"""signals_<tag>.csv 가 판정 축인가 — 머리글에 judge/model 열이 있으면 True(judge·오할당 제외·재분류가 쓴 것),
    없으면 False(mine 이 다시 쓴 규칙 축), 파일이 없으면 None.
    mtime 이 아니라 **내용**으로 본다: judge 는 ai_judgments 를 mm_rows 보다 먼저 쓰므로 'ai_judgments mtime < mm_rows
    mtime' 은 정상 판정까지 전부 재추출로 보이고, 폴더 복사(cp -r)·동기화는 mtime 을 복사 순서로 바꿔 '판정 뒤 재추출'
    을 지어낸다(검증 픽스처 vf_tie 에서 실측: evidence 가 ai_judgments 보다 52ms 새것)."""
    p = os.path.join(REPORT, f"signals_{tag}.csv")
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            head = f.readline()
    except OSError:
        return None
    cols = [c.strip().strip('"').strip() for c in head.strip().split(",")]
    return ("judge" in cols) or ("model" in cols)


def _reextracted(tag):
    """판정 뒤 업무 로드가 다시 추출됐는가(V-01) — signals 가 규칙 축(judge 열 없음)이면 True. 이때 화면의 표·KPI·리포트는
    모두 새 규칙 결과이고, 남아 있는 판정 산출물(agentic/workflow)은 옛 행 기준이다."""
    return _signals_judged(tag) is False


def _judged_info(tag):
    """(판정 반영 여부, 판정 건수, 대상 건수, 판정 기록 요약) — report\\ai_judgments_<tag>.json 기준.

    entities_<tag>.json 의 존재로 보지 않는다: 그 파일은 체계(taxonomy) 단계에서 먼저 생기고
    판정 왕복이 전부 실패해도 남는다(실측: 판정 0/954 인데 judged True → 배너 없음).
    judge.py 가 성공 경로 끝에서 쓰는 ai_judgments 의 judged(건수) > 0 이 기준이다.
    파일이 없거나 깨졌거나 0 건이면 False — 그 화면의 과제·세부업무는 규칙이 뽑은 임시 이름이다.
    네 번째 값(S1-12)은 failed_rows·partial_chunks·repaired·aborted 중 파일에 **있는 키만** 담은 dict —
    화면의 judged_warn 배너가 '실패로 규칙에 남은 행 N · 연속 실패로 중단' 한 줄을 붙인다(키 없으면 표시 안 함).
    LM28(진단 A) — 있으면 함께 싣는다: abort_kind(throttle·login·fatal·content·budget·'')·abort_reason·model_fallback(문자열),
    cache_reused·group_rows·reps·lowinfo_rows·unseen_rows·rule_rows·omitted_rows·cooldowns(정수), filled_rows(비슷한 판정으로
    채운 행 — 방법별 dict 면 합계, 방법별 수는 filled_by{same·conv·token·sim}). 배너는 중단 갈래별 문구와 'AI가 직접 못 본 행
    (채움·규칙)' 줄을 이 값으로 고른다.
    판정 뒤에 업무 로드가 다시 추출됐으면(run.py 가 기록을 .stale 로 개명했거나, signals 가 규칙 축으로 다시 써짐)
    judged=False 에 사유 reextracted/reason='판정 이후 재추출됨' 을 싣는다(V-01) — 화면은 규칙 결과다."""
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
              # 지난 실행 재사용·같은 내용 묶음·대표·짧은 대화·AI 가 직접 못 본 행·규칙으로 남은 행·쉬고 다시 보낸 횟수
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


STUB_MARK = "LM_COPILOT_STUB"


def _stub_note(lastrun):
    """최근 실행이 스텁(LM_COPILOT_STUB) 응답으로 판정했으면 그 단계의 note(아니면 "").
    run.py 가 단계 note 에 남긴다 — ok 여부와 무관하게 화면 상단 배너로 드러내야 실제 Copilot 판정과
    섞이지 않는다(스텁은 테스트 전용)."""
    if not isinstance(lastrun, dict):
        return ""
    for s in (lastrun.get("stages") or []):
        if isinstance(s, dict) and STUB_MARK in str(s.get("note") or ""):
            return str(s.get("note") or "")[:200]
    return ""


def latest_signals():
    """최신 signals CSV — judge 가 남기는 규칙 백업본(signals_*_rules.csv)은 제외한다.
    백업본이 걸리면 tag 파싱이 깨지고, 리뷰 탭이 판정 '이전' 귀속을 보여준다."""
    fs = [f for f in glob.glob(os.path.join(REPORT, "signals_*.csv"))
          if not f.endswith("_rules.csv")]
    return max(fs, key=_mtime) if fs else ""


def latest(pat):
    fs = sorted(glob.glob(os.path.join(REPORT, pat)), key=_mtime, reverse=True)
    return fs[0] if fs else ""


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
    except Exception:  # noqa: BLE001 - 화면 카드 하나가 /api/dash 를 죽이지 않게
        return None


def outlook_coverage(period=None):
    r"""메일·일정 수집 범위(달 단위)를 화면 기간과 맞춰 본다.

    LM28: 옛 data\outlook\coverage.json(LM24 COM 표 — 이제 갱신되지 않는다)을 읽지 않는다. 한 원천에서 센다(F-33):
      ① data\coverage_ledger.json(일자×축 원장) — 달 안의 지난 날(오늘 제외)이 mail_in·mail_out·cal 모두 ok·zero_ok 면 그 달은 확인됨.
      ② 원장이 없으면 COM 표(data\outlook\src\coverage_com.json — 검증된 달만 실린다).
    지난 PC(추가PC\*)가 확인한 달도 확인으로 친다(옮긴 직후 과잉 경고 방지). 반환 {"months", "covered", "uncovered",
    "basis": "ledger"|"com"} — 기간을 모르거나 둘 다 없으면 None."""
    from datetime import date, timedelta

    per = period if isinstance(period, (list, tuple)) and len(period) >= 2 else []
    if not per:
        try:
            with open(os.path.join(DATA, "outlook", "mail_source.json"), encoding="utf-8-sig") as f:
                per = (json.load(f) or {}).get("period") or []
        except (OSError, ValueError, AttributeError):
            per = []
    try:
        d0, d1 = date.fromisoformat(str(per[0])[:10]), date.fromisoformat(str(per[-1])[:10])
    except (TypeError, ValueError, IndexError):
        return None
    if d0 > d1:
        d0, d1 = d1, d0
    months, y, m = [], d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        months.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    last = min(d1, date.today() - timedelta(days=1))           # 오늘은 늘 진행 중(partial) — 판정에서 뺀다
    leds = [x for x in (_ledger(rt) for rt in _data_roots()) if x is not None]
    if leds:
        covered = []
        for mk in months:
            y, mo = int(mk[:4]), int(mk[5:7])
            a = max(d0, date(y, mo, 1))
            b = min(last, (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)))
            if a > b:                                           # 이번 달이 오늘 하루뿐 — 판정 보류(확인으로 둔다)
                covered.append(mk)
                continue
            ok = True
            dd = a
            while dd <= b and ok:
                k = dd.isoformat()
                ok = all(any(ld.is_verified(k, ax) for ld in leds) for ax in ("mail_in", "mail_out", "cal"))
                dd += timedelta(days=1)
            if ok:
                covered.append(mk)
        unc = [k for k in months if k not in covered]
        return {"months": len(months), "covered": covered, "uncovered": unc, "basis": "ledger"}

    def _load(rt):
        try:
            with open(os.path.join(rt, "outlook", "src", "coverage_com.json"), encoding="utf-8-sig") as f:
                c = json.load(f)
        except (OSError, ValueError):
            return None
        return c if isinstance(c, dict) else None

    cov = _load(DATA)
    if cov is None:
        return None
    mail = set(cov["mail"].keys()) if isinstance(cov.get("mail"), dict) else set()
    cal = set(cov["calendar"].keys()) if isinstance(cov.get("calendar"), dict) else set()
    for rt in _data_roots()[1:]:
        _c = _load(rt)
        if _c is None:
            continue
        mail |= set(_c["mail"].keys()) if isinstance(_c.get("mail"), dict) else set()
        cal |= set(_c["calendar"].keys()) if isinstance(_c.get("calendar"), dict) else set()
    unc = [k for k in months if k not in mail or k not in cal]
    return {"months": len(months), "covered": [k for k in months if k not in unc], "uncovered": unc, "basis": "com"}


# ── 수집 현황 카드(F-01·F-33·REQ-36) ──────────────────────────────────────────────────────
# 숫자는 한 원천(원장)에서만 센다 — 요약과 표가 따로 세면 어긋난다(F-33). '불가'는 실측 전이라 '의심'으로 적고(P13),
# 이 PC 인지 모르면 PC 이름을 지어내지 않고 출처만 적는다(F-01). 시각은 로컬(원장·last_run 이 로컬로 쓴다).
AXIS_KO = {"mail_in": "받은 메일", "mail_out": "보낸 메일", "cal": "일정", "teams": "팀즈", "pc": "PC 가동"}
SRC_KO = {"com": "Outlook 앱(COM)", "index": "검색 색인", "owa": "Outlook 웹", "copilot": "Copilot(증인)",
          "import": "반입 파일", "legacy": "예전 수집분", "teams_web": "팀즈 웹", "teams_window": "팀즈 앱 창",
          "teams_graph": "팀즈 Graph", "teams_copilot": "팀즈 Copilot(증인)", "pc_events": "이벤트 로그",
          "pc_hints": "브라우저 기록", "recent": "Recent", "git": "git"}


def _machine_guid():
    """이 PC 의 MachineGuid(원장 host 와 같은 값) — 못 읽으면 ''."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip()
    except (OSError, ImportError, IndexError, ValueError):
        return ""


def collect_status_payload(d0="", d1="", data_dir=None, report_dir=None, here_id=None):
    r"""수집 현황 카드 재료 — {"ledger": {...}|None, "stages": [...], "owa": {...}|None, "as_of": 로컬 시각}.

    ledger.axes[축] = {ok, zero_ok, partial, unobserved, na, days, srcs:[출처 이름]} — 기간 [d0, min(d1, 오늘)] 의 날 수.
      unobserved = 그 밖(unverified·blocked·asked·not_attempted). na 는 팀즈를 쓰지 않는 PC 의 해당 없음.
    ledger.pc = '이 PC' | '' — 원장 host 가 이 PC 의 MachineGuid 와 같을 때만 '이 PC'. 모르면 비워 출처만 보인다(F-01).
    stages = last_run.json 의 수집기 단계(rc 가 있는 것) — name·ok·rc·reason·counts(짧은 것만)·note.
    owa = data\outlook\src\mail_source_owa.json 의 date_only/mail_rows(시각 없이 날짜만 읽힌 메일 비율)."""
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
        except Exception:  # noqa: BLE001 - 날짜가 이상하면 카드만 비운다
            summ = {}
        axes = {}
        for ax in AXIS_KO:
            c = summ.get(ax) or {}
            n = sum(c.values())
            ok, zo, pa, na = c.get("ok", 0), c.get("zero_ok", 0), c.get("partial", 0), c.get("na", 0)
            srcs = sorted({s for day in led.days if a <= day <= b
                           for s in ((led.days.get(day) or {}).get(ax) or {})})
            axes[ax] = {"label": AXIS_KO[ax], "days": n, "ok": ok, "zero_ok": zo, "partial": pa, "na": na,
                        "unobserved": max(0, n - ok - zo - pa - na),
                        "srcs": [SRC_KO.get(s, s) for s in srcs]}
        host = ""
        try:
            with open(lp, encoding="utf-8-sig") as f:
                host = str((json.load(f) or {}).get("host") or "")
        except (OSError, ValueError, AttributeError):
            host = ""
        me = _machine_guid() if here_id is None else here_id
        last = {SRC_KO.get(k, k): {"rc": v.get("rc"), "reason": v.get("reason", ""), "at": v.get("at", "")}
                for k, v in (led.last or {}).items() if isinstance(v, dict)}
        out["ledger"] = {"period": [a, b], "axes": axes, "suspect": int(summ.get("_suspect") or 0),
                         "na": list(summ.get("_na") or []), "last": last,
                         "pc": "이 PC" if (host and me and host == me) else ""}
    try:
        with open(os.path.join(report_dir, "last_run.json"), encoding="utf-8-sig") as f:
            lr = json.load(f)
        for x in (lr.get("stages") or []) if isinstance(lr, dict) else []:
            if isinstance(x, dict) and x.get("rc") is not None:
                cnt = x.get("counts") if isinstance(x.get("counts"), dict) else {}
                keep = {k: v for k, v in cnt.items() if isinstance(v, (int, float, str, bool)) and len(str(v)) <= 24}
                out["stages"].append({"name": str(x.get("name") or ""), "ok": bool(x.get("ok")), "rc": x.get("rc"),
                                      "reason": str(x.get("reason") or ""), "note": str(x.get("note") or "")[:160],
                                      "counts": dict(list(keep.items())[:8])})
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(data_dir, "outlook", "src", "mail_source_owa.json"), encoding="utf-8-sig") as f:
            ms = json.load(f)
        mr, dn = int(ms.get("mail_rows") or 0), int(ms.get("date_only") or 0)
        out["owa"] = {"mail_rows": mr, "date_only": dn, "ratio": round(dn / mr, 3) if mr else 0.0}
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return out


def reset_cursors_local(data_dir=None):
    r"""[커서 초기화] — run.py --reset-cursors 와 같은 일을 이 프로세스에서(파이썬을 새로 띄우지 않는다):
    COM 달별 완료 표·옛 표·팀즈 웹 방 커서를 지우고 원장의 모든 축을 not_attempted 로. 수집한 행(CSV)은 그대로.
    원장의 판(ver)·PC(host)는 보존한다(다음 수집이 그대로 이어 쓴다). → (지운 파일 목록, 원장 초기화 여부)"""
    data_dir = data_dir or DATA
    gone = []
    for rel in (("outlook", "src", "coverage_com.json"), ("outlook", "coverage.json"), ("m365", "teams_web_rooms.json")):
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
            with open(lp, encoding="utf-8-sig") as f:
                raw = json.load(f) or {}
            led = _cv.Ledger.load(lp, ver=str(raw.get("ver") or ""), host=str(raw.get("host") or ""))
            led.reset()
            ok = led.save()
        except Exception:  # noqa: BLE001 - 초기화 실패는 결과로 알린다
            ok = False
    return gone, ok


def web_period(d0="", d1=""):
    r"""웹 읽기 기간 — 화면이 보낸 기간 → 없으면 마지막 실행(last_run.period) → 없으면 올해 1월 1일 ~ 오늘. 끝은 오늘로 자른다."""
    import datetime as _dt
    today = _dt.date.today().isoformat()

    def _ok(s):
        try:
            return _dt.date.fromisoformat(str(s)[:10]).isoformat()
        except (TypeError, ValueError):
            return ""
    a, b = _ok(d0), _ok(d1)
    if not (a and b):
        try:
            with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
                per = json.load(f).get("period") or []
            if len(per) == 2:
                a, b = _ok(per[0]), _ok(per[1])
        except (OSError, ValueError, AttributeError):
            pass
    if not (a and b):
        a, b = quarter_range(today, "ytd")
    if a > b:
        a, b = b, a
    return a, min(b, today)


def web_read(kind, d0, d1, timeout=1500):
    r"""run.py --web-only mail|teams|gerp --from d0 --to d1 → 화면 응답 dict. Job 으로 감싸 [중지]·시간 초과 때 트리째 끊는다.
    마지막 줄들의 'LMSTATUS {…}' 는 사람용 요약에서 뺀다(수집기 계약 줄 — 화면 문구가 아니다).
    LM30(2026-10-19) gerp = [GERP 근무 기록 읽기](시험 기능) — rc 2(회사 계정 로그인)는 없다(GERP 로그아웃은 상태 파일이 말한다)."""
    tag = {"mail": "Outlook 웹", "teams": "팀즈 웹", "gerp": "GERP 근무 기록"}.get(kind, str(kind))
    cmd = [sys.executable, os.path.join(ROOT, "run.py"), "--from", d0, "--to", d1, "--web-only", kind]
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
             if ln.strip() and not ln.lstrip().startswith("LMSTATUS ")]
    for ln in lines[-12:]:
        log(f"[{tag}] {ln[:200]}")
    tail = lines[-4:]
    why = {0: "", 2: "로그인 필요 — 전용 Edge 창에서 회사 계정으로 1회 로그인한 뒤 다시 누르세요"}.get(rc, "일부 실패 — 진행 로그를 보세요")
    if kind == "gerp" and rc != 0:
        why = "GERP 근무 기록을 읽지 못했습니다 — 진행 로그를 보세요"
    return {"ok": rc == 0, "rc": rc, "period": [d0, d1], "login": rc == 2 and kind != "gerp", "error": why,
            "summary": " / ".join(t.strip() for t in tail)[:600]}


# ── 수동 기록 폼(W1-19) — collect\Add-WorkLog.ps1 과 같은 열 ─────────────────────────────────
WORKLOG_COLS = ["date", "category", "hours", "entity", "note", "user", "start", "end"]


def _hhmm(s):
    s = str(s or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"시각은 HH:mm 입니다: {s}")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def add_worklog(rec, data_dir=None):
    r"""data\manual\worklog.csv 에 한 줄 — Add-WorkLog.ps1 과 같은 파일·8열(date,category,hours,entity,note,user,start,end).
    옛 6열 머리말이면 머리말 한 줄만 8열로 바꾼다(Add-WorkLog 와 같은 처리 — 읽는 쪽 core\extract 는 열 이름으로 읽는다).
    시작·끝(HH:mm)을 주면 시간은 그 차이(자정 넘김 허용) — 시간을 함께 주면 그 값을 쓴다(구간은 기록만). → 쓴 행 dict"""
    from datetime import date as _date
    data_dir = data_dir or DATA
    d = _date.fromisoformat(str(rec.get("date") or "")[:10]).isoformat()
    st, en = _hhmm(rec.get("start")), _hhmm(rec.get("end"))
    if bool(st) != bool(en):
        raise ValueError("시작·끝 시각은 둘 다 적거나 둘 다 비우세요")
    try:
        hours = float(rec.get("hours") or 0)
    except (TypeError, ValueError):
        raise ValueError("시간은 숫자입니다") from None
    if st and hours <= 0:
        m0 = int(st[:2]) * 60 + int(st[3:])
        m1 = int(en[:2]) * 60 + int(en[3:])
        hours = round(((m1 - m0) % 1440 or 1440) / 60.0, 2)
    if not (0 < hours <= 24):
        raise ValueError("시간은 0 보다 크고 24 이하여야 합니다")
    cat = str(rec.get("category") or "기타").strip()[:20] or "기타"
    row = {"date": d, "category": cat, "hours": f"{hours:g}",
           "entity": str(rec.get("entity") or "").strip()[:80], "note": str(rec.get("note") or "").strip()[:200],
           "user": os.environ.get("USERNAME", ""), "start": st, "end": en}
    p = os.path.join(data_dir, "manual", "worklog.csv")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        with open(p, encoding="utf-8-sig", newline="") as f:
            body = f.read()
        lines = body.splitlines()
        if lines and lines[0].strip() == ",".join(WORKLOG_COLS[:6]):
            lines[0] = ",".join(WORKLOG_COLS)          # 옛 6열 머리말 → 8열(Add-WorkLog.ps1 과 같은 처리)
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                f.write("\r\n".join(lines) + "\r\n")
    else:
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            f.write(",".join(WORKLOG_COLS) + "\r\n")
    with open(p, "a", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerow([row[k] for k in WORKLOG_COLS])
    return row


# ── 기간 빠른 선택(UD-18·W3-06) — 올해(기본)·1~4분기·상반기·하반기 ─────────────────────────────
# LM27 lm27\ui\period.py 의 규칙만 가져왔다: 모두 오늘이 속한 해, 진행 중인 기간은 끝을 오늘로 자르고, 아직 시작하지
# 않은 기간은 고를 수 없다(None). 같은 규칙의 JS 판 = PAGE 의 periodRange(), bat 판 = LoadMonitor30.bat 의 날짜 계산 1줄.
PERIOD_SPANS = {"ytd": ("01-01", "12-31"), "q1": ("01-01", "03-31"), "q2": ("04-01", "06-30"),
                "q3": ("07-01", "09-30"), "q4": ("10-01", "12-31"), "h1": ("01-01", "06-30"),
                "h2": ("07-01", "12-31")}


def quarter_range(today, key):
    """빠른 선택 key(ytd·q1~q4·h1·h2)의 (from, to) — 'YYYY-MM-DD' 글자. 끝이 오늘보다 뒤면 오늘로 자른다.
    아직 시작하지 않은 기간·모르는 키면 None. today 는 'YYYY-MM-DD'(date 도 받는다)."""
    t = today.isoformat() if hasattr(today, "isoformat") else str(today)[:10]
    span = PERIOD_SPANS.get(str(key or "").lower())
    if not span or len(t) != 10:
        return None
    a, b = t[:4] + "-" + span[0], t[:4] + "-" + span[1]
    if a > t:
        return None
    return a, min(b, t)


def dash_period(meta, lastrun=None):
    r"""화면이 다루는 기간 [d0, d1] — 추이·덩어리 판정·수집 범위 대조가 모두 이 기간을 쓴다.
      ① 분석 결과(mm_meta.period) ② 없으면 마지막 실행의 기간(report\last_run.json 의 period = 수집 기간 — 수집만 한
      추가 PC·분석 전) ③ 그것도 없으면 수집된 데이터의 실제 범위(data_extent) ④ ["", ""].
    주의: 추이 카드는 이 함수가 아니라 '이 값 ∪ data_extent()' 를 쓴다 — 분석 창이 집계 전체를 가리지 않게."""
    from datetime import date

    def _pair(v):
        """[d0, d1] 로 쓸 수 있는 값이면 ISO 날짜 문자열 쌍(앞이 이르게 정렬), 아니면 None — 손으로 고친 파일의 'abc' 같은 값은
        13주 폴백이 아니라 다음 후보(last_run·데이터 범위)로 넘어가야 한다(재검증 지적)"""
        if not (isinstance(v, (list, tuple)) and len(v) >= 2):
            return None
        try:
            a, b = date.fromisoformat(str(v[0])[:10]), date.fromisoformat(str(v[-1])[:10])
        except (TypeError, ValueError):
            return None
        if a > b:
            a, b = b, a
        return [a.isoformat(), b.isoformat()]

    for src in (meta, lastrun):
        per = _pair(src.get("period")) if isinstance(src, dict) else None
        if per:
            return per
    return data_extent()


def data_extent():
    r"""수집 데이터의 실측 범위 [d0, d1] — pc_on·메일·일정·파일 시각의 최소~최대(400일 창).
    dash_period ③ 이던 것을 분리했다: 추이 카드가 '분석 창'이 아니라 **집계 전체**를 그리려면
    분석 기간과 무관하게 이 범위가 필요하다(제보: "왜 집계기간 전체를 안 보여주나").
    /api/dash 는 자주 불리므로 파일 mtime 이 그대로면 지난 답을 쓴다(files.csv 는 수만 행일 수 있다)."""
    from datetime import date, timedelta
    srcs = (("pc/pc_on.csv", "date"), ("outlook/mail.csv", "time"), ("outlook/calendar.csv", "start"),
            ("files/files.csv", "mtime"))
    def _sz(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return -1
    # 키 = (mtime, 크기)×파일 + 오늘 날짜 — 같은 mtime 으로 덮어쓴 파일·자정을 넘긴 서버(400일 창)도 다시 잰다
    # 뿌리마다(본 폴더 + 추가PC\*) 잰다 — 옮겨 온 폴더는 자료가 전부 추가PC\ 쪽에 있어
    # 본 폴더만 보면 lo/hi 가 None 이 되고 기간이 ["",""] 로 떨어진다(실측 재현).
    _cand = [q for rel, _c in srcs for q in _paths_multi(rel)]
    sig = tuple((_mtime(q), _sz(q)) for q in _cand) + (date.today().isoformat(),)
    if _DASH_EXTENT.get("sig") == sig:
        return list(_DASH_EXTENT["per"])
    lo = hi = None
    for rel, col in srcs:
        for r in _rows_multi(rel):
            try:
                d = date.fromisoformat(str(r.get(col) or "")[:10])
            except ValueError:
                continue
            if d > date.today() + timedelta(days=1) or d < date.today() - timedelta(days=400):
                continue
            lo, hi = (d if lo is None or d < lo else lo), (d if hi is None or d > hi else hi)
    per = [lo.isoformat(), hi.isoformat()] if (lo and hi) else ["", ""]
    _DASH_EXTENT.update(sig=sig, per=list(per))
    return per


_DASH_EXTENT = {}      # dash_period ③ 의 캐시 — {"sig": (mtime, …), "per": [d0, d1]}


def sources(period=None):
    """수집 데이터 현황 — 무엇이 비어서 결과가 약한지 한눈에. period 는 화면이 보는 기간(메일 수집 범위 대조용)"""
    out = []
    # [로컬PC 자료수집]이 메일·일정·팀즈를 건너뛴 직후(run.skip_account_data) — 이 PC 의 0건은 수집 실패가 아니다
    try:
        with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
            _lr0 = json.load(f)
        acct_skip = isinstance(_lr0, dict) and _lr0.get("account_data") == "skipped"
    except (OSError, ValueError):
        acct_skip = False
    for name, pats, hint in (
        ("PC 가동", ["pc/pc_on.csv"], "run 실행 시 자동"),
        ("메일·일정", ["outlook/mail.csv", "outlook/calendar.csv"], "클래식 Outlook을 켠 상태로 실행"),
        ("파일·Recent", ["files/files.csv", "files/recent.csv"], "config.watchFolders 를 실제 작업 폴더로"),
        ("git 커밋", ["files/git_commits.csv"], "config.gitRepos 설정 (선택)"),
        ("팀즈 채팅", ["m365/teams_*.csv"], r"[팀즈 웹 읽기] 버튼 — 앱이 꺼져 있어도 됩니다 (전용 Edge 창에서 회사 계정 1회 로그인)"),
        ("추가 PC", ["추가PC/*/outlook/mail.csv", "추가PC/*/files/files.csv",
                     "추가PC/*/pc/pc_on.csv", "추가PC/*/m365/teams_*.csv"],
         "다른 PC 에서 [로컬PC 자료수집] → 폴더째 분석할 PC 로 옮겨 [분석 실행] — 자동 합산 · 중복 자동 제외 (선택)"),
    ):
        # '추가 PC'(추가PC 자체) 행은 본 폴더만, 나머지는 본 PC + 추가PC\* 를 합쳐 센다.
        # 폴더째 옮긴 직후에는 지난 PC 수집물이 전부 추가PC\ 에 있어, 본 폴더만 세면 '메일·일정 0건 · 없음' 같은 거짓
        # 경고가 KPI·현황표에 떴다(감사 재현 — 추가PC 에 716건이 있는데도). 분석·추이와 같은 뿌리를 본다.
        here_only = name in ("추가 PC",)
        always = ""                 # 상태가 ok 여도 화면에 남길 사실(수집 경로 등)
        n, mt, n_here = 0, 0.0, 0
        for p in pats:
            for f in glob.glob(os.path.join(DATA, p)):
                n_here += max(0, len(_rows(f)))
                mt = max(mt, _mtime(f))
            if not here_only:
                for f in _paths_multi(p):
                    if not f.startswith(os.path.join(DATA, "추가PC")):
                        continue                # 본 폴더 몫은 위에서 셌다
                    n += max(0, len(_rows(f)))
                    mt = max(mt, _mtime(f))
        n += n_here
        opt = name in ("git 커밋", "팀즈 채팅", "추가 PC")
        st = "ok" if n else ("off" if opt else "bad")
        # 건수가 있어도 기간 대비 몇 건뿐이면 '찾긴 했지만 못 찾은' 것이다(실측: 3개월에
        # PC 2건·팀즈 1건이 초록으로 표시됨) — 부족을 노랑으로 드러낸다.
        if name == "메일·일정" and not n:
            # 수집기가 남긴 실제 사유를 우선한다 — "Outlook 을 켜세요"는 마법사에 막힌
            # PC(이미 켜져 있다)에서 원인을 가린다.
            try:
                with open(os.path.join(DATA, "outlook", "outlook_skip.json"),
                          encoding="utf-8-sig") as f:
                    why = (json.load(f).get("reason") or "").strip()
                if why:
                    hint = why
            except (OSError, ValueError):
                pass
            # 대체 경로(색인·Outlook 웹·Copilot)가 각각 어떻게 끝났는지 한 줄씩 — 회사 PC 는 파일을
            # 밖으로 못 보내므로 원인은 이 화면에서 읽혀야 한다(실측: PC3 메일 공백).
            try:
                with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
                    _lr = json.load(f)
                _stages = (_lr.get("stages") or []) if isinstance(_lr, dict) else []
                _st = [x for x in _stages
                       if isinstance(x, dict) and str(x.get("name", "")).startswith("Outlook")]
                if _st:
                    parts = []
                    for x in _st:
                        nm = str(x.get("name", ""))
                        short = ("COM" if "대체" not in nm else
                                 "색인" if "대체①" in nm else
                                 "Outlook 웹" if "대체②" in nm else
                                 "Copilot" if "대체③" in nm else nm)
                        note = (x.get("note") or "").strip()
                        parts.append(f"{short}: {'OK' if x.get('ok') else '실패'}" + (f" — {note[:90]}" if note and not x.get("ok") else ""))
                    hint = (hint + " · " if hint else "") + " / ".join(parts)
                    if any("로그인 필요" in (x.get("note") or "") for x in _st):
                        hint += " → 전용 Edge 창의 Outlook 탭에서 회사 계정 1회 선택 후 [Outlook 웹 읽기]"
            except (OSError, ValueError):
                pass
        if name == "메일·일정" and n:
            # 자가검증(-SelfTest / LM_OUTLOOK_SELFTEST) 이 만든 가짜 메일이면 무엇보다 먼저 알린다 — 실제 수집과 섞이지 않게
            try:
                with open(os.path.join(DATA, "outlook", "mail_source.json"), encoding="utf-8-sig") as f:
                    _ms = json.load(f)
            except (OSError, ValueError):
                _ms = {}
            # 수집 경로는 **항상** 적는다 — 앱(COM)·색인은 시각이 정확하고, 웹·Copilot 은 어제 이전 항목이
            # 날짜만이라 그만큼 시간 계상에서 빠진다(extract A38). 예전에는 이 사실이 화면 어디에도 없었다(감사 지적).
            _path = {"com": "Outlook 앱(COM)", "index": "Windows 검색 색인", "owa": "Outlook 웹(Edge)",
                     "web": "Outlook 웹(Edge)", "copilot": "Copilot 왕복"}.get(str(_ms.get("source") or ""), "")
            _dn, _mr = int(_ms.get("date_only") or 0), int(_ms.get("mail_rows") or 0)
            if _path:
                # always 는 상태가 ok 여도 화면에 남는다 — 정상 줄의 hint 는 아래에서 비워지기 때문
                always = (f"수집 경로: {_path}"
                          + (f" · 시각 못 읽은 메일 {_dn:,}/{_mr:,}통(시간 계상 제외)" if _dn else ""))
            if _dn and _mr and _dn >= 0.20 * _mr:
                st = "warn"
                always = f"수집 경로: {_path}" if _path else ""      # 경고문이 통수를 말하므로 중복을 뺀다
                hint = (f"시각을 못 읽은 메일 {_dn:,}통({_dn * 100 // max(_mr, 1)}%)은 시간 계상에서 빠졌습니다 — "
                        "클래식 Outlook 을 켠 상태로 [분석 실행]을 하면 앱 경로가 정확한 시각으로 다시 씁니다"
                        + (" · " + hint if hint else ""))
            if isinstance(_ms, dict) and _ms.get("selftest"):
                st, hint = "warn", "자가검증(테스트 전용) 가짜 메일·일정입니다 — 실제 수집이 아닙니다. LM_OUTLOOK_SELFTEST 를 지우고 다시 수집하세요"
            # COM 이 예산에 닿아 못 읽은 달이 기간 안에 있으면 '있음'이 아니라 '부족'이다 — 앞 달의 메일·회의가
            # 통째로 빠진 채 로드율·주간 추이가 그려진다(실측 제보: 1~5월 공백). 다음 실행이 이어서 읽는다.
            oc = outlook_coverage(period)
            if oc and oc["uncovered"] and not (isinstance(_ms, dict) and _ms.get("selftest")):
                st = "warn"
                hint = (f"메일·일정이 {oc['months']}개월 중 {len(oc['covered'])}개월만 수집됨 — 미수집 "
                        f"{', '.join(oc['uncovered'][:8])}{' …' if len(oc['uncovered']) > 8 else ''}"
                        " (Outlook 시간 예산) → [분석 실행]을 다시 돌리면 남은 달을 이어서 읽습니다")
        if name == "PC 가동" and 0 < n < 10:
            st, hint = "warn", "기간 대비 부족 — 재분석 시 브라우저 힌트로 보강됩니다"
        elif name == "팀즈 채팅":
            # 이 계정의 Copilot 이 팀즈 조회 불가로 확인된 PC(실측: 커넥터 부재)에서는
            # '재수집'이 아니라 [팀즈 웹 읽기]가 정답이다 — 안내를 상황에 맞게 바꾼다.
            # LM28: 파일이 있다고 '불가' 가 아니다 — 1회 관측만 담길 수 있다(서로 다른 날 2회 + 14일 TTL · P13).
            # until 이 오늘 이후일 때만 불가로 본다(Get-TeamsViaCopilot unable_active 와 같은 규칙).
            no_cp = False
            try:
                with open(os.path.join(DATA, "m365", "teams_copilot_unavailable.json"), encoding="utf-8-sig") as f:
                    _un = json.load(f)
                no_cp = isinstance(_un, dict) and str(_un.get("until") or "")[:10] >= time.strftime("%Y-%m-%d")
            except (OSError, ValueError):
                no_cp = False
            if no_cp and n < 5:
                st = "warn" if n else "off"
                hint = ("이 계정 Copilot은 팀즈 조회 불가 의심(서로 다른 날 2회 확인 · 14일 뒤 다시 물음) — [팀즈 웹 읽기] 를 쓰세요"
                        "(앱이 꺼져 있어도 됩니다)")
            elif 0 < n < 5:
                st, hint = "warn", "회수 부족 — [팀즈 웹 읽기] 로 보강 (창 읽기는 화면에 보인 부분만 긁습니다)"
        if acct_skip and not n and name in ("메일·일정", "팀즈 채팅"):
            st, hint = "off", "로컬PC 자료수집은 읽지 않습니다 — 같은 계정이면 폴더를 받은 PC 의 [분석 실행]이 읽습니다"
        # 본 PC 와 추가 PC 의 몫을 갈라 적는다 — 합만 보이면 이 PC 의 수집 실패(0건)가 가려진다
        split = ""
        if n and n_here < n and not here_only:
            split = (f"본 PC {n_here:,}건 + 추가 PC {n - n_here:,}건" if n_here
                     else f"본 PC 0건 — 추가 PC 자료 {n:,}건(옮겨 온 폴더)으로 표시")
        # always(수집 경로 같은 '정상이어도 보여야 하는 사실')는 상태와 무관하게 남긴다
        out.append({"name": name, "rows": n, "here": n_here, "age": _age(mt), "status": st,
                    "hint": " · ".join(x for x in (split, always, ("" if st == "ok" else hint)) if x)})
    return out



def mtime_clumps(d0="", d1="", top=3):
    r"""같은 시각에 몰린 파일 덩어리를 찾는다 — '그날 일한 것' 이 아닐 수 있다.

    파일 흔적의 시각은 LastWriteTime(마지막 수정)이다. 파일 하나에 시각은 하나뿐이라,
    폴더가 통째로 다시 쓰이면 그 안 파일 전부의 시각이 그 순간으로 바뀐다 —
    공유 드라이브 재동기화, 폴더 복사·이관, git checkout, 백업 복원이 그렇다.
    같은 공유 폴더를 보는 사람들은 **모두** 같은 날 똑같은 봉우리가 생긴다(실측 제보).

    돌려주는 것: [{"when": "2026-05-14 10:00", "n": 4210, "folder": "...", "share": 0.62}]
    """
    from collections import Counter
    from datetime import date

    def _d(s, dflt=None):
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return dflt

    lo, hi = _d(d0), _d(d1)
    by_min, by_min_folder, total = Counter(), {}, 0
    for name in ("files.csv", "recent.csv"):
        for r in _rows_multi("files/" + name):     # 본 PC + 추가PC — 덩어리는 어느 뿌리에 있든 같은 경고
            t = (r.get("mtime") or "").strip()
            dt = _d(t)
            if not dt or (lo and dt < lo) or (hi and dt > hi):
                continue
            total += 1
            k = t[:16]                       # 분 단위
            by_min[k] += 1
            by_min_folder.setdefault(k, Counter())[(r.get("folder") or "")[:70]] += 1
    if total < 200:                          # 표본이 적으면 판단하지 않는다
        return []
    out = []
    for k, n in by_min.most_common(top):
        share = n / total
        if n < 50 or share < 0.10:           # 한 분에 50건 이상이고 10% 넘게 몰릴 때만
            continue
        fold = by_min_folder.get(k) or Counter()
        out.append({"when": k, "n": n, "share": round(share, 3),
                    "folder": (fold.most_common(1)[0][0] if fold else "")})
    return out

MONTHLY_OVER_WEEKS = 16     # 이보다 긴 기간(주)은 달 단위로 묶는다 — 화면 칩 기준 1·3개월=주간, 6개월·1년·올해=월간


def _trend_work_hours(_X, start, end):
    r"""근무시간(투입 실측) — report\day_hours_*.json **읽기만**. 계산은 수집·분석이 로드바 안에서
    한다(mine·run --collect-only 가 저장). v3 초기엔 여기서 load_signals+day_work_hours 를 요청
    스레드로 재계산해, 로드바가 끝난 뒤 수 분 동안 '탐색하듯 도는' CPU 가 됐다(제보 — 폐기)."""
    wh = _X.load_day_hours_range(REPORT, start.isoformat(), end.isoformat())
    from datetime import date as _date
    out = {}
    for k, v in wh.items():
        try:
            out[_date.fromisoformat(k)] = float(v)
        except (ValueError, TypeError):
            continue
    return out


def trend(d0="", d1="", tag="", info=None):
    r"""활동 추이 — 분석 기간을 덮고, **판정에 실제로 쓰인 신호**(report\signals_<기간>.csv)를 센다. LM24 의 기준.
    대시보드 MM 과 같은 축이고, 파일류는 하루 8건 상한으로 눌러 재동기화 몰림이 그래프를 지배하지 않는다.

    판정 신호가 없는 기간(수집만 한 PC·분석 전)은 수집 raw 로 모양만 보인다 — LM20+보완2(0901 보완2.py TREND_NEW)와
    **같은 규칙**: files.csv·recent.csv 의 mtime 을 하루 8건 상한, 메일·일정·커밋·팀즈는 그대로. 다른 점은 둘뿐이다 —
    본 PC + 추가PC\* 를 함께 읽고(폴더 이동 뒤 빈 추이), 두 PC 가 같은 사서함을 읽어 생긴 같은 메일·일정은 1회.
    (v24.2~v24.5 는 폴백에서 files_history 를 세고 하루 상한을 없애 한 달이 13,203건이 됐다 — 되돌림.)

    info(dict): src "signals"(판정 신호) / "raw"(수집 폴백) / "none"(기간 없음), signals_n, capped(상한에 눌린 건수),
    gran, pc_*(pc_days_total = 기록 있는 날 수), period, roots.
    기간이 길면(MONTHLY_OVER_WEEKS 초과) 주 대신 달로 묶고 제목도 '월간 활동 추이' 가 된다."""
    from datetime import date, timedelta

    def _d(s, dflt=None):
        try:
            return date.fromisoformat(str(s)[:10])
        except (TypeError, ValueError):
            return dflt

    end = _d(d1) or date.today()
    start = _d(d0) or (end - timedelta(weeks=13))
    if start > end:
        start, end = end, start
    span_w = max(1, ((end - start).days // 7) + 1)
    # 화면 기간 칩 기준으로 1개월·3개월(≤13주)은 주 단위, 6개월·1년·올해는 달 단위 — 제목도 '주간/월간 활동 추이' 로 바뀐다.
    # 예전 경계(26주)는 '6개월' 이 주 26개로 그려져 읽기 어려웠고, 기간이 길면 월별 추이를 기대한다(제보).
    monthly = span_w > MONTHLY_OVER_WEEKS

    buckets, idx = [], {}
    if monthly:
        y, m = start.year, start.month
        one_year = (start.year == end.year)     # 한 해 안이면 '3월', 해가 바뀌면 '25/12' 처럼 — 제목에 기간이 적힌다
        while (y, m) <= (end.year, end.month):
            idx[(y, m)] = len(buckets)
            buckets.append(f"{m}월" if one_year else f"{y % 100:02d}/{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

        def key(dt):
            return idx.get((dt.year, dt.month))
    else:
        w0 = start - timedelta(days=start.weekday())
        w = w0
        while w <= end:
            idx[w.isocalendar()[:2]] = len(buckets)
            buckets.append(f"{w:%m/%d}")
            w += timedelta(weeks=1)

        def key(dt):
            return idx.get(dt.isocalendar()[:2])

    # pc_days/pc_wd = 그 버킷에서 'PC 기록이 있는 날' / '평일 수'. 기록이 없는 주를 0h 로 그리면
    # 'PC 를 안 켠 주'와 구분되지 않는다(이벤트 로그 롤오버로 과거 주는 구조적으로 기록이 없다).
    # raw_n = 상한·중복제거로 누르기 전의 원건수 — 막대와 실제 신호 수의 차이를 화면이 말할 수 있게.
    out = [{"label": lb, "pc_h": 0.0, "파일": 0, "메일": 0, "회의": 0, "커밋": 0, "팀즈": 0,
            "작업창": 0, "pc_days": 0, "pc_wd": 0, "pc_rd": 0, "wk_h": 0.0, "raw_n": 0}
           for lb in buckets]
    if info is not None:
        info["src"] = "none"
    if not out:
        return out

    def slot(s):
        dt = _d(s)
        return key(dt) if (dt and start <= dt <= end) else None

    # ── 막대 = **판정에 실제로 쓰인 신호**(report\signals_<기간>.csv) — 대시보드 MM 과 같은 축. LM24 의 기준이다.
    # 파일 신호의 시각은 mtime 하나뿐이다 — 공유폴더 재동기화·폴더 이관·백업 복원이 수백 파일의 시각을 한 날로
    # 몰면 그 달만 산처럼 솟는다(실측 제보). 파일류는 하루 상한 8건으로 눌러 센다(mine 의 '사람 손 하루 한 폴더 8건').
    # 메일·회의·커밋·팀즈는 사건 시각이라 그대로 센다. '작업창'(창 샘플러)은 별도 계열 — 파일로 뭉치면 아침 창
    # 세션이 상한 8칸을 다 먹어 오후에 만든 문서가 사라졌다(실측 결함).
    _SRC = (("메일", "메일"), ("mail", "메일"), ("회의", "회의"), ("일정", "회의"),
            ("cal", "회의"), ("커밋", "커밋"), ("git", "커밋"),
            ("팀즈", "팀즈"), ("teams", "팀즈"),
            ("작업창", "작업창"), ("window", "작업창"))
    sp = os.path.join(REPORT, f"signals_{tag}.csv") if tag else latest_signals()
    n_sig = 0
    _fcap, _seen = {}, set()
    _sig_lo, _sig_hi = "", ""            # 판정 신호가 실제로 덮는 날짜 범위 — 그 밖 버킷은 수집 흔적으로 보완
    for r in _rows(sp):
        d = str(r.get("time") or r.get("date") or "")[:10]
        if len(d) == 10:
            _sig_lo = d if (not _sig_lo or d < _sig_lo) else _sig_lo
            _sig_hi = d if (not _sig_hi or d > _sig_hi) else _sig_hi
        i = slot(d)
        if i is None:
            continue
        src_l = str(r.get("source") or "").lower()
        # 변수명이 key 면 위쪽 버킷 함수 key() 를 가려 slot() 이 죽는다(실측)
        kind = next((v for k2, v in _SRC if k2.lower() in src_l), "파일")
        n_sig += 1                              # 상한 초과분도 '신호는 있었다'로 계상
        out[i]["raw_n"] += 1                    # 이 버킷의 누르기 전 원건수(막대와의 차이를 화면이 말한다)
        if kind == "파일":
            _t = str(r.get("text") or "")[:120]
            if _t:                              # 빈 text 는 서로 다른 신호일 수 있다 — 안 묶는다
                _k = (d, _t)
                if _k in _seen:                 # 같은 날 같은 파일 신호는 1회만
                    continue
                _seen.add(_k)
            _fcap[d] = _fcap.get(d, 0) + 1
            if _fcap[d] > 8:                    # 재동기화 몰림이 그래프를 지배하지 않게
                continue
        out[i][kind] += 1
    # 판정 신호가 덮지 않는 버킷(판정 기간 밖 달)은 수집 raw 로 보완한다 — 예전엔 신호가 하나라도
    # 있으면 raw 폴백 전체가 꺼져, 집계기간을 넓혀도 앞 달 막대가 통째로 비었다(all-or-nothing 구조).
    def _slot_raw(s10):
        i = slot(s10)
        if i is None:
            return None
        if not n_sig:
            return i                      # 판정 자체가 없다 — 전 버킷 raw(기존 규칙)
        if _sig_lo and _sig_hi and _sig_lo <= s10 <= _sig_hi:
            return None                   # 판정이 덮는 날 — 신호 막대가 진실
        return i

    _n_raw_out = 0
    if (not n_sig) or (_sig_lo and _sig_lo > (start.isoformat())) or (_sig_hi and _sig_hi < (end.isoformat())):
        _fcap.clear()
        for pat in ("files/files.csv", "files/recent.csv"):
            for r in _rows_multi(pat):                  # 본 PC + 추가PC
                d = str(r.get("mtime") or "")[:10]
                i = _slot_raw(d)
                if i is None:
                    continue
                _fcap[d] = _fcap.get(d, 0) + 1
                if _fcap[d] > 8:                        # 재동기화 몰림이 그래프를 지배하지 않게(보완2 와 같다)
                    continue
                out[i]["파일"] += 1
                _n_raw_out += 1
        for pat, k2, col, kcols in (("outlook/mail.csv", "메일", "time", ("subject", "sender")),
                                    ("outlook/calendar.csv", "회의", "start", ("subject",)),
                                    ("files/git_commits.csv", "커밋", "time", ("repo", "subject")),
                                    ("m365/teams_*.csv", "팀즈", "time", ("from", "summary"))):
            seen = set()
            for r in _rows_multi(pat):
                t = str(r.get(col) or "")
                i = _slot_raw(t[:10])
                if i is None:
                    continue
                if len(_data_roots()) > 1:
                    # 두 PC 가 같은 사서함·저장소를 읽으면 같은 사건이 두 번 들어온다 — 분 단위 시각 + 제목류로 1회만
                    k = (t[:16],) + tuple(str(r.get(c) or "")[:60] for c in kcols)
                    if k in seen:
                        continue
                    seen.add(k)
                out[i][k2] += 1
                _n_raw_out += 1

    # ── 근무시간(투입 실측) — 선의 **주 재료**. PC 이벤트 로그는 롤오버로 파괴되면 그 달이 영영
    # 한 자릿수라(수번째 제보 "수십 시간인데 8h"), 선을 로그에 묶어 두는 한 같은 문제가 반복된다.
    # 이 도구가 MM 을 계산할 때 이미 쓰는 실측(회의·산출물·메일·샘플러 세션 합집합 + PC 하한 —
    # extract.day_work_hours, mine 과 동일 호출)을 그대로 쓴다. 파일·메일 흔적은 롤오버되지 않는다.
    try:
        import extract as _XW
        _wh = _trend_work_hours(_XW, start, end)
        for _dd, _h in _wh.items():
            _i = key(_dd) if start <= _dd <= end else None
            if _i is not None:
                out[_i]["wk_h"] += float(_h or 0)
        if info is not None and not _wh:
            info["wk_note"] = ("근무시간 실측이 아직 없습니다 — [분석 실행]/[로컬PC 자료수집]이 계산해 "
                               "저장합니다(그때까지 선은 PC 가동 기준)")
    except Exception as _exw:  # noqa: BLE001 — 실측 판독 실패는 선을 비울 뿐, 추이를 막지 않는다
        if info is not None:
            info["wk_note"] = f"근무시간 실측 판독 실패({type(_exw).__name__}) — PC 가동 선만 표시"
    # LM30(2026-10-18) — 점 툴팁의 연장·휴일 시간: 출퇴근 추정(report\attendance_*.json 의 날짜별 시간)을 이 버킷(주·달)으로 합친 값 —
    # 시각은 싣지 않는다. 막대·선은 그대로(선은 day_hours). 출퇴근 추정이 없는 버킷은 키가 없다(화면이 툴팁에 넣지 않는다).
    try:
        import extract as _XA
        for _iso, _ar in _XA.load_attendance_range(REPORT, start.isoformat(), end.isoformat()).items():
            _i = slot(_iso)
            if _i is not None:
                out[_i]["ext_h"] = round(float(out[_i].get("ext_h") or 0) + float(_ar.get("ext_h") or 0), 2)
                out[_i]["hol_h"] = round(float(out[_i].get("hol_h") or 0) + float(_ar.get("holiday_h") or 0), 2)
    except Exception:  # noqa: BLE001 — 툴팁 재료 하나가 추이를 막지 않게
        pass

    # PC 가동 시간 — 기간 안만. 본 PC + 추가PC 를 extract.pc_daily 로 합친다(구간 합집합 — 분석의 PC 하한과 같은 값).
    # 예전엔 본 PC 의 pc_on.csv 만 세어 추가 PC 의 가동이 이 선에서 통째로 빠졌다(제보: 'PC 가동시간 합산 안 됨').
    pc_note = ""
    pcd = {}
    try:
        import extract as _X
        pcd = _X.pc_daily(DATA, start, end)[0]
        for dd, (on_h, _ni, _fo, _lo) in pcd.items():
            i = key(dd) if start <= dd <= end else None
            if i is not None:
                out[i]["pc_h"] += float(on_h or 0)
                out[i]["pc_rd"] += 1        # 기록 있는 날(주말 포함) — 선은 '기록일 평균 h/일' 로 그린다
    except Exception as ex:  # noqa: BLE001 — 병합 실패 시 **루트 단위 부분 성공**
        # v2 폴백은 루트 간 행-max 라 하루 두 세션(데스크톱 오전 + 노트북 오후)이 큰 쪽 하나로
        # 붕괴했고, 198h 달이 하루치로 꺼졌다(구조 감사 실측). v3: 깨진 루트만 빼고 남은 루트를
        # 같은 함수(pc_daily)로 계산한다 — 폴백에서도 읽기 규칙은 한 벌이다.
        pcd = {}
        _ok_roots, _bad_roots = [], []
        for _r1 in _data_roots():
            try:
                # pc_daily(DATA) 는 추가PC 를 스스로 또 합친다 — 루트별 부분 성공이 목적이므로
                # 그 루트 '하나만' 보는 임시 뷰를 만든다(최종 검증: 이중 합산 실측 13h→18h)
                _pcd1 = _X.pc_daily(_r1, start, end, single_root=True)[0]
            except TypeError:
                _pcd1 = _X.pc_daily(_r1, start, end)[0]
            except Exception:  # noqa: BLE001
                _bad_roots.append(os.path.basename(os.path.normpath(_r1)) or "본 PC")
                continue
            _ok_roots.append(_r1)
            for dd2, (on2, _n2, _f2, _l2) in _pcd1.items():
                i = key(dd2) if start <= dd2 <= end else None
                if i is not None:
                    out[i]["pc_h"] += float(on2 or 0)
                    out[i]["pc_rd"] += 1
                    pcd[dd2] = True
        pc_note = (f"PC 기록 일부를 읽지 못했습니다({type(ex).__name__}"
                   + (" · 제외: " + ", ".join(_bad_roots[:3]) if _bad_roots else "")
                   + ") — 읽힌 폴더만 합산했습니다")
    # 버킷마다 '평일 수'와 'PC 기록이 있는 평일 수' — 기록 없음과 0h 를 화면이 구분하게.
    # LM30(2026-10-21) 하루 휴가인 평일(pc_lv)과 그중 PC 기록이 있는 날(pc_lv_rec) — 이 PC 의 attendance 파일(core\attendance 머리말 22)에서.
    # 화면이 'PC 기록 없음' 주를 유급휴가로 말한다(얼린 사본은 이 두 칸을 뺀다 — freeze). 그런 날이 있는 버킷에만 키가 생긴다
    try:
        import extract as _XL
        lvd = _XL.load_leave_range(REPORT, start.isoformat(), end.isoformat())
    except Exception:  # noqa: BLE001 — 휴가 재료 하나가 추이를 막지 않게
        lvd = {}
    dd = start
    while dd <= end:
        i = key(dd)
        if i is not None and dd.weekday() < 5:
            out[i]["pc_wd"] += 1
            if dd in pcd:
                out[i]["pc_days"] += 1
            if float(lvd.get(dd.isoformat(), 0.0) or 0.0) >= 1.0:
                out[i]["pc_lv"] = out[i].get("pc_lv", 0) + 1
                out[i]["pc_lv_rec"] = out[i].get("pc_lv_rec", 0) + (1 if dd in pcd else 0)
        dd += timedelta(days=1)
    for w in out:
        w["pc_h"] = round(w["pc_h"], 1)
    if info is not None:
        info["src"] = "signals" if n_sig else "raw"   # 무엇을 셌는지 — 화면 안내·부제가 이 값을 본다
        info["signals_n"] = n_sig               # 판정에 쓰인 신호 수
        info["gran"] = "month" if monthly else "week"
        info["pc_note"] = pc_note
        # PC 기록이 있는 버킷 / 평일이 있는 버킷 — 화면이 "27주 중 16주만 기록" 처럼 말할 수 있게
        info["raw_outside_n"] = int(_n_raw_out) if n_sig else 0
        info["sig_span"] = [_sig_lo, _sig_hi] if (_sig_lo and n_sig) else []
        info["pc_buckets"] = sum(1 for w in out if w["pc_days"] > 0)
        info["pc_buckets_all"] = sum(1 for w in out if w["pc_wd"] > 0)
        info["pc_days_total"] = len(pcd)       # 기록이 있는 날 수 — 선 높이가 낮은 이유(기록 이틀치)를 화면이 말하게
        first_pc = next((d for d in sorted(pcd)), None)
        info["pc_from"] = first_pc.isoformat() if first_pc else ""
        info["capped"] = (sum(max(0, w["raw_n"] - (w["파일"] + w["메일"] + w["회의"] + w["커밋"] + w["팀즈"] + w["작업창"]))
                              for w in out) if n_sig else sum(max(0, n - 8) for n in _fcap.values()))   # 하루 8건 상한에 눌린 파일 수
        info["period"] = [start.isoformat(), end.isoformat()]     # 실제로 그린 기간 — 제목이 이것을 적는다
        info["roots"] = len(_data_roots())                          # 본 PC + 추가PC 폴더 수 — raw 안내에 적는다
        try:                    # PC 가동 진단 — 숫자가 낮은 이유(기록 자체가 적음)를 화면이 말하게
            import extract as _X2
            info["pc_diag"] = _X2.pc_coverage(DATA, start, end)
        except Exception:       # noqa: BLE001 — 진단이 추이를 막지 않는다
            info["pc_diag"] = {}
    return out

def _review_meta(sig_path):
    r"""리뷰가 쓰는 mm_meta — 신호 파일과 같은 기간(tag)의 report\mm_meta_<tag>.json. 없으면 {}."""
    m = re.search(r"signals_(\d{8}-\d{8})\.csv$", str(sig_path or ""))
    if not m:
        return {}
    try:
        with open(os.path.join(REPORT, f"mm_meta_{m.group(1)}.json"), encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def review_mm(meta, gran, key, days=None):
    r"""리뷰 묶음 하나의 투입 MM — mm_meta 기준(W2-09: 대시보드·리포트와 같은 값).
      month: mm_months[YYYY-MM].mm(그 달 투입 MM) · week: 그 주 날마다 day_hours ÷ 그 달 1 MM 시간(capacity_h)의 합
      · all: total_mm. mm_meta 에 값이 없으면 None(호출측이 예전 달력 개략치로 내려간다)."""
    from datetime import date, timedelta
    if not isinstance(meta, dict) or not meta:
        return None
    mmm = meta.get("mm_months") if isinstance(meta.get("mm_months"), dict) else {}
    try:
        if gran == "month":
            v = (mmm.get(key) or {}).get("mm")
            return float(v) if v is not None else None
        if gran == "week":
            dh = meta.get("day_hours") if isinstance(meta.get("day_hours"), dict) else {}
            if not dh or not mmm:
                return None
            d0 = date.fromisoformat(key)
            tot = 0.0
            for i in range(7):
                d = (d0 + timedelta(days=i)).isoformat()
                h = float(dh.get(d) or 0)
                if not h:
                    continue
                cap = float((mmm.get(d[:7]) or {}).get("capacity_h") or 0)
                if cap <= 0:
                    wd = int((mmm.get(d[:7]) or {}).get("workdays") or 0)
                    cap = 8.0 * max(1, wd or 21)
                tot += h / cap
            return tot
        v = meta.get("total_mm")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _via_note(tv):
    """리뷰 과제 한 줄(LM30 2026-10-27) — 그 과제의 팀즈 근거 행들({source, via})의 수로 core\\details.via_note(합니다체). 없으면 ""."""
    if not tv:
        return ""
    try:
        import details as _dv
        return _dv.via_note(_dv.teams_via_counts(tv))
    except Exception:  # noqa: BLE001 - 근거 한 줄이 리뷰를 막지 않는다
        return ""


def review(gran="week", rows=None, meta=None):
    """주간/월간/전체 업무 리뷰 — 신호별 귀속 내역(signals_*.csv)을 기간으로 묶어
    프로젝트별 raw 근거·타임라인·사람/산출물 연결까지 만든다. '요약'이 아니라 원문이 들어간 리뷰.
    LM28(W2-09): 과제 MM = 그 묶음의 투입 MM(mm_meta — 달 mm·주 day_hours·전체 total_mm) × 과제 몫(신호 가중치 비중).
    예전에는 달력일/30.44 × 비중이라 대시보드·리포트의 투입 MM 과 어긋났다. mm_meta 가 없을 때만 예전 개략치(mm_basis='calendar')."""
    from datetime import datetime, timedelta
    if rows is None:
        sp = latest_signals()
        rows = _rows(sp)
        if meta is None:
            meta = _review_meta(sp)
    meta = meta if isinstance(meta, dict) else {}
    if not rows:
        return []
    groups = {}
    for r in rows:
        try:
            t = datetime.strptime((r.get("time") or "")[:16], "%Y-%m-%d %H:%M")
            w = float(r.get("weight") or 0)
        except ValueError:
            continue
        if gran == "week":
            mon = t.date() - timedelta(days=t.weekday())
            key, label, span = mon.isoformat(), f"{mon:%m/%d} 주", 7.0
        elif gran == "month":
            key, label, span = t.strftime("%Y-%m"), f"{t:%Y년 %m월}", 30.44
        else:
            key, label, span = "all", "전체 기간", 0.0
        g = groups.setdefault(key, {"label": label, "span": span, "w": 0.0, "n": 0,
                                    "days": set(), "proj": {}, "tl": defaultdict(list)})
        g["w"] += w
        g["n"] += 1
        g["days"].add(t.date())
        pj = r.get("project") or "미지정"
        who = (r.get("who") or "").strip()
        src = r.get("source") or ""
        txt = (r.get("text") or "").strip()
        pp = g["proj"].setdefault(pj, {"w": 0.0, "n": 0, "acts": Counter(), "people": Counter(),
                                       "files": Counter(), "meets": Counter(), "comms": Counter(),
                                       "wt": Counter(), "tv": []})
        pp["w"] += w
        pp["n"] += 1
        if src.startswith("팀즈"):                   # 팀즈 근거가 과제를 받은 길(via — LM30 2026-10-27 · 과제별 한 줄)
            pp["tv"].append({"source": src, "via": r.get("via") or ""})
        pp["acts"][r.get("detail") or r.get("activity") or "기타"] += w
        pp["wt"][r.get("worktype") or "사무"] += w
        g.setdefault("wt", Counter())[r.get("worktype") or "사무"] += w
        if who and who != "나":
            pp["people"][who] += 1
        if src.startswith(("파일", "커밋")):
            pp["files"][txt[:60]] += 1
        elif src == "회의":
            pp["meets"][txt[:60]] += 1
        elif src.startswith(("메일", "팀즈")):
            pp["comms"][txt[:70]] += 1
        g["tl"][t.date().isoformat()].append(
            {"t": f"{t:%H:%M}", "src": src, "who": who, "text": txt[:90], "proj": pj, "w": w})
    out = []
    for key in sorted(groups, reverse=True):
        g = groups[key]
        tot = g["w"] or 1e-9
        span = g["span"] or (max(g["days"]) - min(g["days"])).days + 1
        months = span / 30.44
        gmm = review_mm(meta, gran, key)
        basis = "mm_meta" if gmm is not None else "calendar"
        if gmm is None:
            gmm = months                     # mm_meta 가 없을 때만 — 예전 개략치(달력일 ÷ 30.44)
        projs = []
        for pj, pp in sorted(g["proj"].items(), key=lambda kv: -kv[1]["w"]):
            projs.append({
                "name": pj, "share": round(pp["w"] / tot, 4),
                "mm": round(pp["w"] / tot * gmm, 3), "n": pp["n"],
                # pw 가드: 가중치 합 0(잘린 행 등)이면 ZeroDivision 으로 리뷰 탭 전체가 죽는다
                "acts": [{"name": a, "pct": round(v / (pp["w"] or 1e-9) * 100)} for a, v in pp["acts"].most_common(4)],
                "wt": [[k, round(v / (pp["w"] or 1e-9) * 100)] for k, v in pp["wt"].most_common()],
                "people": [[k, v] for k, v in pp["people"].most_common(6)],
                "files": [k for k, _v in pp["files"].most_common(6)],
                "meets": [k for k, _v in pp["meets"].most_common(4)],
                "comms": [k for k, _v in pp["comms"].most_common(5)],
                # LM30(2026-10-27) — '이 과제의 팀즈 근거 N건 중 M건은 같은 문장이라 함께 들어왔고, K건은 지난 판정을 다시 썼습니다'
                "note": _via_note(pp["tv"])})
        timeline = [{"date": d, "lines": sorted(g["tl"][d], key=lambda x: x["t"])[:60]}
                    for d in sorted(g["tl"], reverse=True)][:45]
        # 연결성: 사람↔프로젝트, 프로젝트↔산출물 간선
        p_edges, a_edges = [], []
        for p in projs[:6]:
            for who, n in p["people"][:5]:
                p_edges.append([who, p["name"], n])
            for fname in p["files"][:5]:
                a_edges.append([p["name"], fname[:24], 1])
        out.append({"key": key, "label": g["label"], "signals": g["n"], "days": len(g["days"]),
                    "months": round(months, 2), "mm": round(gmm, 3), "mm_basis": basis, "projects": projs,
                    "wt": [[k, round(v / tot * 100)] for k, v in (g.get("wt") or Counter()).most_common()],
                    "timeline": timeline, "p_edges": p_edges[:24], "a_edges": a_edges[:24]})
    return out


def _fresh_refined(plain, ref):
    """정제본을 써도 되는가 — core/details._fresh_refined 와 같은 규칙(정제본 mtime ≥ 원본 mtime)."""
    if not os.path.exists(ref):
        return False
    try:
        return (not os.path.exists(plain)) or os.path.getmtime(ref) >= os.path.getmtime(plain)
    except OSError:
        return True


def result_file():
    r"""화면에 띄울 결과 행 파일(report\mm_rows_<기간>[_refined].csv)의 경로 — 없으면 "". 고르는 규칙은 result_rows 머리말.
    LM30(2026-10-18): /api/attendance 가 행을 읽지 않고 기간만 같은 규칙으로 고르게 따로 뺐다."""
    bases = [f for f in glob.glob(os.path.join(REPORT, "mm_rows_*.csv"))
             if not f.endswith("_refined.csv")]
    base = max(bases, key=_mtime) if bases else ""
    if base:
        ref = base[:-4] + "_refined.csv"
        return ref if _fresh_refined(base, ref) else base
    # 정제본만 남은 폴더(옮겨 온 report\ 등) — 원본이 없다고 화면을 백지로 두지 않는다
    # (리포트·flow 는 정제본만으로도 돌아간다 — 대시보드도 같은 규칙)
    refs = glob.glob(os.path.join(REPORT, "mm_rows_*_refined.csv"))
    return max(refs, key=_mtime) if refs else ""


def pc_usage_view(meta):
    r"""LM30(2026-10-20) 'MM 산정 근거' 카드의 PC 사용 시간 줄(GET /api/dash 의 pc_usage_text) → [줄, …] — mm_meta 의 출퇴근 합계
    (mm_basis.attendance.total — 근태 기록 없이 잰 값)의 pc_usage_h·pc_usage_off_h·always_on_days(attendance.pc_usage_lines). 합계뿐이라
    얼린 사본에도 남는다. PC 사용 시간으로 재지 않은 결과(그 칸이 없다)는 []."""
    import attendance as _att
    meta = meta if isinstance(meta, dict) else {}
    b = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
    att = b.get("attendance") if isinstance(b.get("attendance"), dict) else (
        meta.get("attendance") if isinstance(meta.get("attendance"), dict) else {})
    cu = b.get("cfg_used") if isinstance(b.get("cfg_used"), dict) else (
        meta.get("cfg_used") if isinstance(meta.get("cfg_used"), dict) else {})
    return _att.pc_usage_lines(att.get("total"), cu.get("pcFloorWindow"))


def pc_months_view(meta):
    r"""LM30(2026-10-21) 'MM 산정 근거'·'출퇴근·시간외 근무' 카드의 달마다 근거(GET /api/dash·/api/attendance 의 pc_months) →
    {"cells": {달: 'PC 기록' 칸 글}, "lines": [경고·안내 줄], "fill8": 하루 8시간으로 채운 평일 수, "capped": 그런 달이 있나} —
    mm_meta 의 mm_basis.pc_months(일수·건수만 — 시각 없음)·pc_log(Windows 보관 주 수)·send_gap(이미 말한 달은 발신 0건 줄에서 뺀다)
    (core\attendance.month_cell·month_lines — 리포트와 같은 글자). 그 칸이 없는 예전 결과면 빈 값. 합계뿐이라 얼린 사본에도 남는다."""
    import attendance as _att
    meta = meta if isinstance(meta, dict) else {}
    b = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
    pm = b.get("pc_months") if isinstance(b.get("pc_months"), dict) else {}
    pm = {str(k): v for k, v in pm.items() if isinstance(v, dict)}
    if not pm:
        return {"cells": {}, "lines": [], "fill8": 0, "capped": False}
    sg = b.get("send_gap") if isinstance(b.get("send_gap"), dict) else {}
    lines = _att.month_lines(pm, (sg.get("months") or []) if sg.get("warn") else (), b.get("pc_log"))
    return {"cells": {k: _att.month_cell(v) for k, v in sorted(pm.items())}, "lines": lines,
            "fill8": int(sum(_att._num0(v.get("fill8")) for v in pm.values())),
            "capped": any(bool(v.get("capped")) for v in pm.values())}


def leave_view_lines(meta, tag):
    r"""LM30(2026-10-21) 'MM 산정 근거' 카드의 유급휴가 줄(GET /api/dash 의 leave_text — core\attendance 머리말 22) — 같은 기간의
    report\attendance_<기간>.json(이 PC 전용)의 agg.leave 로 휴가로 본 날·휴가로 보지 않은 평일(날짜). 그 칸이 없는 예전 결과는 mm_meta 의
    일수만. 얼린 사본은 freeze 가 일수만으로 바꾼다."""
    import attendance as _att
    import extract as _X
    doc = _X.load_attendance(REPORT, tag) if tag else None
    return _att.leave_lines_for(meta, None, doc, local=True)


# ── LM30(2026-10-21) 유급휴가 '휴가 날짜' 칸(core\attendance 머리말 22) — data\근태\휴가_직접입력.csv 를 이 프로세스 안에서 읽고 쓴다(새
#    프로세스 없음). 날짜는 이 PC 에만(얼린 사본은 /api/leave_days 를 굽지 않는다 — freeze.FREEZE_EPS 밖). 다음 [분석 실행]·[재분석만]이 읽는다.
LEAVE_BODY_MAX = 32768        # 칸 글 상한(attendance.LEAVE_TEXT_MAX 8000자 — 한글은 3바이트) + JSON 여유
LEAVE_DRAIN_MAX = 1 << 20     # 너무 큰 본문은 이만큼까지만 읽어 버리고 400(메모리에 담지 않는다)
LEAVE_BUSY_HINT = "분석·다른 작업이 도는 중에는 휴가 날짜를 저장하지 않습니다 — 끝난 뒤 누르세요"
# LM30(2026-10-27) 워크플로우 탭 '이름 병합' 표의 [분리](POST /api/project_split — 과제 이름 두 개)
SPLIT_BODY_MAX = 4096
SPLIT_BUSY_HINT = "분석·다른 작업이 도는 중에는 과제 이름 병합을 나누지 않습니다 — 끝난 뒤 누르세요"


def _leave_is_off():
    """휴가 날짜 칸의 주말·공휴일(설정의 holidays 포함 — 분석과 같은 달력)"""
    import extract as _X
    hol = _X._holiday_set(cfg())
    return lambda d: _X._is_off_day(d, hol)


def leave_days_view():
    r"""GET /api/leave_days → {"ok", "text": 칸에 보일 글(이어진 평일은 '~' 로 묶음), "n": 날 수, "days": 휴가 일수(반차 0.5), "file":
    data\근태\휴가_직접입력.csv}. 파일이 없으면 빈 글."""
    import attendance as _att
    d = _att.read_manual_leave(DATA)
    return {"ok": True, "text": _att.leave_text_of(d, _leave_is_off()), "n": len(d),
            "days": round(sum(d.values()), 1), "file": "data\\" + _att.RECORDS_DIR + "\\" + _att.MANUAL_LEAVE_CSV}


def leave_days_save(body):
    r"""POST /api/leave_days 본문 {"text"} → (상태, 답). 읽지 못한 항목이 있으면 400(아무것도 쓰지 않는다) · 날짜가 너무 많으면 400 ·
    쓰기 실패는 200 + ok False(엑셀 등에서 열려 있으면 닫고 다시) · 성공이면 ok True + msg + 다시 읽은 칸 글 + log(진행 로그 한 줄 —
    일수만 · 호출측이 LOCK 밖에서 남긴다). 바쁜지는 호출측이 LOCK 안에서 본다(이 함수는 LOCK 을 잡지 않는다)."""
    import attendance as _att
    b = body if isinstance(body, dict) else {}
    text = str(b.get("text") or "")
    if len(text) > _att.LEAVE_TEXT_MAX:
        return 400, {"ok": False, "error": f"글이 너무 깁니다({_att.LEAVE_TEXT_MAX}자까지)"}
    r = _att.parse_leave_text(text, None, _leave_is_off())
    if r["bad"]:
        return 400, {"ok": False, "bad": r["bad"],
                     "error": "읽지 못한 날짜가 있어 저장하지 않았습니다 — " + ", ".join(r["bad"])
                              + " (예: 2026-10-05, 10-06~10-08, 10/15 반차)"}
    if r["over"]:
        return 400, {"ok": False, "error": f"날짜가 너무 많습니다({_att.LEAVE_DATES_MAX}일까지)"}
    try:
        _att.write_manual_leave(DATA, r["dates"])
    except OSError:
        return 200, {"ok": False, "error": "휴가 날짜 파일을 쓰지 못했습니다 — 엑셀 등에서 열려 있으면 닫고 다시 누르세요"}
    n, days = len(r["dates"]), round(sum(r["dates"].values()), 1)
    line = f"[휴가 날짜] {n}일(휴가 {days:g}일) 저장 — 날짜는 이 PC 의 data\\근태 에만 둡니다"
    if n:
        msg = (f"휴가 날짜 {n}일(휴가 {days:g}일)을 저장했습니다"
               + (f" · 주말·휴일 {r['off']}일은 뺐습니다" if r["off"] else "")
               + " — [재분석만] 또는 [분석 실행]을 누르면 그 날을 휴가로 봅니다(일하지 않은 날로 세지 않고 가용에서 뺍니다).")
    else:
        msg = "휴가 날짜를 모두 지웠습니다 — [재분석만] 또는 [분석 실행]을 누르면 반영됩니다."
    v = leave_days_view()
    return 200, dict(v, ok=True, msg=msg, off=r["off"], log=line)


# ── LM30(2026-10-21) 예전 판 PC 가동 기록 가져오기(core\pc_import) — 'MM 산정 근거' 카드의 줄. 이 프로세스 안에서 찾고 가져온다(새 프로세스
#    없음). 찾기는 폴더 300개·2초까지라 10분 동안 같은 답을 쓴다. 폴더 경로는 이 PC 화면에만(얼린 사본은 /api/pc_import 를 굽지 않는다).
PCIMP = {"t": 0.0, "v": None}
PCIMP_TTL_S = 600.0


def pc_import_view(refresh=False):
    r"""GET /api/pc_import — 예전 판 설치 폴더(이 PC 의 형제·사용자 폴더)와 지난 가져오기 기록 → {"ok", "found": [{folder, name, same,
    who, events, hints, new, done, when}], "record": [{name, when, added, total, same, events, hints}], "scanned", "secs"}.
    읽기만 한다(core\pc_import.scan)."""
    now = time.time()
    with LOCK:
        if not refresh and PCIMP["v"] is not None and now - PCIMP["t"] < PCIMP_TTL_S:
            return PCIMP["v"]
    try:
        import pc_import as _pi
        s = _pi.scan(ROOT, DATA)
    except Exception as e:  # noqa: BLE001 - 찾기가 깨져도 대시보드는 그대로(이 줄만 빈다)
        return {"ok": False, "error": f"{type(e).__name__}"}
    found = [{"folder": x.get("folder"), "name": x.get("name"), "same": x.get("same_pc"), "who": _pi.same_pc_text(x.get("same_pc")),
              "events": x.get("events") or [], "hints": x.get("hints") or [], "new": int(x.get("new") or 0),
              "done": bool(x.get("done")), "when": x.get("when") or ""} for x in s.get("found") or []]
    rec = [{"name": r.get("name"), "when": r.get("when"), "added": r.get("added"), "total": r.get("total"),
            "same": r.get("same_pc"), "events": r.get("events") or [], "hints": r.get("hints") or []}
           for r in s.get("record") or [] if isinstance(r, dict)]
    v = {"ok": True, "found": found, "record": rec, "scanned": s.get("scanned"), "secs": s.get("secs")}
    with LOCK:
        PCIMP.update(t=now, v=v)
    return v


def pc_import_run(body):
    r"""POST /api/pc_import — {"folders": [찾은 폴더 경로…]} 또는 {"folder": 사람이 적은 폴더(다른 PC 에서 복사해 온 data\pc 등)} →
    {"ok", "results": [{name, ok, added, who, error}], "added", "msg"}. 찾은 폴더는 지난 찾기 결과에 있는 것만 받는다. 그 폴더에는 아무것도
    쓰지 않고, 이 설치의 원장(data\pc · data\추가PC\<이름>\pc)에만 더한다(원장 잠금 · 같은 행은 건너뜀)."""
    import pc_import as _pi
    b = body if isinstance(body, dict) else {}
    paths = []
    if isinstance(b.get("folders"), list):
        known = {os.path.normcase(os.path.abspath(str(x.get("folder") or ""))): str(x.get("folder") or "")
                 for x in (pc_import_view().get("found") or [])}
        for f in b["folders"][:20]:
            k = os.path.normcase(os.path.abspath(str(f or "")))
            if k in known:
                paths.append(known[k])
    elif str(b.get("folder") or "").strip():
        f = str(b.get("folder")).strip().strip('"')
        if not os.path.isdir(f):
            return {"ok": False, "error": "그 폴더가 없습니다 — 탐색기 주소 창의 경로를 그대로 붙여 넣으세요"}
        paths.append(f)
    if not paths:
        return {"ok": False, "error": "가져올 폴더가 없습니다"}
    hid, hnm = _pi.here_identity()
    res, total = [], 0
    for f in paths:
        r = _pi.import_folder(f, DATA, hid, hnm, root=ROOT)
        total += int(r.get("added") or 0) if r.get("ok") else 0
        res.append({"name": r.get("name"), "ok": bool(r.get("ok")), "added": int(r.get("added") or 0),
                    "who": _pi.same_pc_text(r.get("same_pc")), "error": r.get("error") or ""})
        log(f"[PC 기록 가져오기] {r.get('name')}: " + (f"{int(r.get('added') or 0):,}줄 더함({_pi.same_pc_text(r.get('same_pc'))})"
                                                  if r.get("ok") else str(r.get("error") or "실패")))
    with LOCK:
        PCIMP.update(t=0.0, v=None)                # 다음 GET 이 다시 찾는다(새로 가져올 행 수가 바뀌었다)
    ok = any(x["ok"] for x in res)
    if total > 0:
        msg = (f"PC 가동 기록 {total:,}줄을 가져왔습니다. [재분석만]을 누르면 PC 기록이 없던 달을 다시 잽니다"
               "(가져온 기록으로 잰 값이 예전 추정보다 작은 날은 예전 값을 그대로 둡니다).")
    elif ok:
        msg = "새로 가져올 기록이 없습니다 — 이미 가져왔거나 이 설치에 같은 기록이 있습니다."
    else:
        msg = "가져오지 못했습니다 — " + "; ".join(x["error"] for x in res if x["error"])[:200]
    return {"ok": ok, "results": res, "added": total, "msg": msg}


def meta_path_for(fn):
    r"""화면에 띄운 결과 행 파일(mm_rows_<기간>…)과 **같은 기간**의 report\mm_meta_<기간>.json — 없으면 가장 최근 mm_meta.
    /api/dash 와 /api/attendance 가 같은 규칙으로 기간을 고른다(LM30 — 한 곳). → 경로 또는 "" """
    m2 = re.search(r"mm_rows_(\d{8}-\d{8})", fn or "")
    if m2:
        cand = os.path.join(REPORT, f"mm_meta_{m2.group(1)}.json")
        if os.path.exists(cand):
            return cand
    return latest("mm_meta_*.json")


def result_rows():
    # '가장 최근 분석'을 기준으로 고른다. 예전의 기간(tag) 무관 '정제본 우선'은,
    # 분석 기간 기본값이 날마다 바뀌어 tag 가 매일 달라지는 상황에서 과거 실패한 날의
    # 정제본이 이후 모든 성공 결과를 영원히 가리는 함정이었다(실측: 재실행해도 같은
    # 토큰 화면 반복). 정제본은 '같은 기간'의 것이 있을 때만 우선한다.
    #
    # 정제본 선택은 core/details.rows_path(flow·freeze 공용)와 **같은 mtime 규칙**이다(V-01):
    # 정제본 mtime ≥ 원본 mtime 일 때만 정제본, 원본이 더 새로 써졌으면 '낡았다'고 보고 원본으로 내려간다.
    # 예전에는 '같은 tag 정제본이 있으면 무조건' 이라 무AI 재실행·판정 실패 뒤 옛 정제본이 표에 남아 KPI(새 meta)·
    # 분석리포트(새 원본)와 셋이 다른 값을 보였다. 1차 무효화는 run.py 가 추출 직후 정제본을 .stale 로 개명하는
    # 것이고, 여기 mtime 규칙은 mine 을 직접 돌린 경우의 안전망이다. 재분류 0건은 retag.py 가 파일을 다시 쓰지
    # 않으므로 화면이 튀지 않고, n>0·오할당 제외는 정제본을 지우므로 두 규칙이 같은 행을 본다.
    p = result_file()
    rows = _rows(p) if p else []

    def _f(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    for r in rows:
        # 항상 float 로 확정 — 비숫자 값이 남으면 아래 정렬·합산이 TypeError 로 죽어
        # /api/dash 전체(대시보드)가 백지가 된다
        r["mm"] = round(_f(r.get("mm")), 2)
        r["share"] = round(_f(r.get("share")) * 100, 1)
    rows.sort(key=lambda r: -(r.get("mm") or 0))
    return (os.path.basename(p) if p else ""), rows


# ── LM30(2026-10-25) 화면 표시 설정 — '0.04 MM 이하 숨기기'(config ui.hideSmallMM · 기본 켜짐 · 이 PC 의 개인 설정) ─────────────────────
# 사용자: "UI 대시보드 디스플레이에 0.04이하는 안보이게 하는 on/off 옵션 넣고, 디폴트는 on 되게해줘". 대시보드(PAGE)·팀 취합 화면(TEAM_PAGE)의
# 과제·업무 목록(표·범례·칩·막대·원)에서 화면에 보이는 MM(소수 둘째 자리)이 0.04 이하인 항목을 숨긴다 — 화면 스크립트가 그릴 때만 거른다.
# 결과 파일·합계·투입·가용·로드율·리포트·얼린 사본·팀으로 보내는 자료는 그대로다(지우거나 다시 계산하지 않는다). 숨긴 개수와 합은 표 아래 한 줄.
# 문턱은 고정: SMALL_MM 0.04 — 둘째 자리로 반올림해 0.04 이하 = SMALL_MM_LT(0.045) 미만, 0·음수 포함(화면 JS 의 SMALL_LT·smallV 와 같은 규칙).
# 옵션 줄 칸(팀 취합 화면에도 같은 칸)이 GET·POST /api/ui_prefs 로 읽고 쓴다. 얼린 사본에는 굽지 않는다(freeze.FREEZE_EPS 밖 — 사본은 모두 보인다).
SMALL_MM = 0.04
SMALL_MM_LT = 0.045
UI_PREFS_BODY_MAX = 1024     # {"hideSmallMM": true} 한 줄이면 된다 — 넘으면 읽어 담지 않고 버린 뒤 400
_UI_OFF_WORDS = ("false", "0", "off", "no", "n", "끔", "끄기")


def hide_small_on(c):
    r"""config → '0.04 MM 이하 숨기기'가 켜졌나(bool). ui.hideSmallMM 이 없거나(ui 블록째 없어도) 읽을 수 없는 값이면 켜짐(기본) —
    끄는 값은 false·0·"false"·"off"·"끔" 같은 것만이다."""
    u = c.get("ui") if isinstance(c, dict) else None
    v = u.get("hideSmallMM", True) if isinstance(u, dict) else True
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() not in _UI_OFF_WORDS
    return True


def is_small_mm(v):
    r"""숨길 MM 인가 — 화면 JS smallV 와 같은 규칙: 숫자이고 SMALL_MM_LT(0.045) 미만(둘째 자리로 0.04 이하 · 0·음수 포함).
    숫자가 아니면(MM 을 모르는 항목) 숨기지 않는다."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and float("-inf") < v < SMALL_MM_LT


def ui_prefs_view():
    r"""GET /api/ui_prefs — 화면 표시 설정('0.04 MM 이하 숨기기' — 켜짐·문턱). 파일만 읽는다."""
    return {"ok": True, "hideSmallMM": hide_small_on(cfg()), "threshold": SMALL_MM}


ATT_RECENT_DAYS = 31      # 출퇴근 카드·리포트의 날짜별 표 — 최근 31일
ATT_DAY_KEYS = ("arrive", "leave", "arrive_day", "leave_day", "work_h", "regular_h", "ext_h", "night_h", "holiday_h",
                "offpc_h", "lm29_h", "kind", "leave_frac", "conf", "late", "rec")


def attendance_view():
    r"""LM30(2026-10-18) '출퇴근·시간외 근무' 카드(GET /api/attendance) — 화면 기간(/api/dash 와 같은 규칙: meta_path_for)의
    report\attendance_<기간>.json(이 PC 전용 — 날짜별 출근·퇴근) + mm_meta 의 출퇴근 합계(시각 없음)·LM29 방식 MM.
      · 기간: 화면 결과 행 파일과 같은 기간의 mm_meta → 없으면 가장 최근 mm_meta → 그것도 없으면(수집만 한 PC) 가장 최근 attendance 파일
      · 합계(agg): mm_meta.mm_basis.attendance(투입 MM 과 같은 계산 — 판정 재산정 뒤 값) → 없으면 attendance 파일의 agg
      · 날짜별 행(days): 기간 끝(오늘을 넘지 않게)부터 최근 31일만, 근거 한 줄(why — core\attendance.day_why)을 붙여서
    없으면 ok False + 안내 한 줄. 파일만 읽는다(외부 전송 없음). 얼린 사본(freeze._att_summary_only)은 날짜별 행·평소 시각을 빼고 굽는다
    — 그 사본이 공유폴더로 복사되기 때문이다.
    LM30(2026-10-19) +@ — 근태 기록 = 확실히 일한 부분, +@ = 그 밖에서 LM 이 찾은 근무:
      · agg 는 늘 근태 기록 없이 잰 합계(mm_meta — 파일의 agg 를 쓸 때도 근태 칸을 뺀 사본 · attendance.strip_hr)
      · hr = attendance 파일 합계의 근태 칸(attendance.hr_view — 근태 기록이 없었으면 None) · plus_text(결론 첫 줄) · plus_note(설명)
      · 날짜별 행마다 plus = attendance.day_plus(+@ 시간·추정인가·까닭) — rec(근태 출근·퇴근·입실·퇴실)와 함께 이 PC 화면에서만
      얼린 사본은 hr·날짜별 행을 빼고 결론 줄을 근태 없이(추정만) 다시 쓴다(freeze._att_summary_only).
    LM30(2026-10-19) with_lm29(LM29 보다 적게 세지 않음 — 그 결과를 잰 설정) · offhours_text(분석 기간의 주말·휴일·저녁·야간 한 줄 —
    attendance.offhours_line) · send_gap·send_gap_text(발신 흔적 빈 곳 — mm_basis.send_gap · 건수·날짜만).
    LM30(2026-10-20) pc_usage(그 결과를 PC 사용 시간으로 쟀나) · pc_usage_text(분석 기간 PC 를 쓴 시간·켜 둔 날 — attendance.pc_usage_lines
    · 합계뿐이라 얼린 사본에도 남는다) · rule 은 PC 사용 시간 문장(낮 창 = cfg_used.pcFloorWindow)."""
    import copy as _copy
    from datetime import date as _date, timedelta as _td

    import attendance as _att
    import extract as _X
    out = {"ok": False, "tag": "", "period": ["", ""], "hint": "분석을 한 번 실행하면 보입니다.",
           "recent_days": ATT_RECENT_DAYS}
    mp = meta_path_for(os.path.basename(result_file()))
    meta = {}
    if mp:
        try:
            with open(mp, encoding="utf-8-sig") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
    meta = meta if isinstance(meta, dict) else {}
    tag = os.path.basename(mp)[len("mm_meta_"):-len(".json")] if mp else ""
    doc = _X.load_attendance(REPORT, tag) if tag else None
    if doc is None and not tag:
        ap = latest("attendance_*.json")
        if ap:
            tag = os.path.basename(ap)[len("attendance_"):-len(".json")]
            doc = _X.load_attendance(REPORT, tag)
    out["tag"] = tag
    b = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
    agg = b.get("attendance") if isinstance(b.get("attendance"), dict) else None
    src = "mm_meta"
    if agg is None and isinstance((doc or {}).get("agg"), dict):
        agg, src = doc["agg"], "file"
    hr = _att.hr_view((doc or {}).get("agg"))          # LM30(2026-10-19) 근태 기록과 견준 칸(+@) — 이 PC 의 attendance 파일에서만
    if isinstance(agg, dict):
        agg = _copy.deepcopy(agg)
        _att.strip_hr(agg)                              # agg 는 늘 근태 없이 잰 합계 — 근태 칸은 hr 로만(옛 mm_meta·파일 agg 도)
    if not agg or not (isinstance(agg.get("months"), dict) and agg.get("months")):
        if meta and doc is None:
            out["hint"] = "이 분석 결과에는 출퇴근 추정이 없습니다 — [분석 실행]을 한 번 더 하면 보입니다."
        return out
    per = meta.get("period") if isinstance(meta.get("period"), list) and len(meta.get("period")) == 2 else []
    if not per and re.match(r"^\d{8}-\d{8}$", tag):
        per = [f"{tag[:4]}-{tag[4:6]}-{tag[6:8]}", f"{tag[9:13]}-{tag[13:15]}-{tag[15:]}"]
    cu = b.get("cfg_used") if isinstance(b.get("cfg_used"), dict) else (
        meta.get("cfg_used") if isinstance(meta.get("cfg_used"), dict) else {})
    p = cu.get("attendance") if isinstance(cu.get("attendance"), dict) else _att.norm(cfg())[0]
    days = (doc or {}).get("days") if isinstance((doc or {}).get("days"), dict) else {}
    recent = {}
    try:
        end = min(_date.fromisoformat(str(per[1])[:10]), _date.today()) if per else _date.today()
    except ValueError:
        end = _date.today()
    lo, hi = (end - _td(days=ATT_RECENT_DAYS - 1)).isoformat(), end.isoformat()
    std = cu.get("standardDayHours")
    for iso in sorted(days, reverse=True):
        r = days[iso]
        if not (isinstance(r, dict) and lo <= str(iso)[:10] <= hi):
            continue
        row = {k: r.get(k) for k in ATT_DAY_KEYS if k in r}
        row["why"] = _att.day_why(r, p)
        row["plus"] = _att.day_plus(r, std)            # LM30(2026-10-19) +@ 시간·추정인가·까닭(근태 시각을 담는다 — 이 PC 화면만)
        recent[str(iso)[:10]] = row
    mo = meta.get("mm_months") if isinstance(meta.get("mm_months"), dict) else {}
    ms = b.get("measure") if isinstance(b.get("measure"), dict) else {}
    # LM30(2026-10-19) 시간외 나눠 보기(주말·휴일·저녁·야간 — 합계뿐)·발신 흔적 빈 곳(건수·날짜뿐) — 얼린 사본에 남아도 된다
    sg = b.get("send_gap") if isinstance(b.get("send_gap"), dict) else None
    tot = agg.get("total") if isinstance(agg.get("total"), dict) else {}
    out.update(
        ok=True, period=[str(x)[:10] for x in per] or ["", ""], hint="", agg_src=src,
        used_for_mm=bool(agg.get("used_for_mm")), method=ms.get("method") or "", lm29_method=ms.get("lm29_method") or "",
        agg={k: agg.get(k) for k in ("weeks", "months", "total") if k in agg},
        with_lm29=bool(p.get("withLM29")),
        offhours_text=_att.offhours_line(tot, cu.get("nightWindow"), bool(agg.get("used_for_mm"))) if tot else "",
        pc_usage=bool(p.get("pcUsage")), pc_usage_text=_att.pc_usage_lines(tot, cu.get("pcFloorWindow")),
        # LM30(2026-10-21) 달마다 근거 — 하루 8시간으로 채운 달·발신 0건인 달·Windows 보관 주 수(일수·건수만 — 얼린 사본에도 남는다)
        pc_months_text=pc_months_view(meta)["lines"],
        send_gap=sg, send_gap_text=_att.send_gap_text(sg),
        hr=hr,
        plus_text=_att.plus_line(agg, hr, per[1] if per else None, _date.today(), std),
        plus_note=_att.plus_note(std),
        headline=_att.headline(agg, per[1] if per else None),
        rule=_att.rule_text(p, cu.get("standardDayHours"), cu.get("nightWindow"), cu.get("pcFloorWindow")),
        records_text=_att.records_text((hr or {}).get("records")),
        usual=(doc or {}).get("usual") if isinstance((doc or {}).get("usual"), dict) else {},
        usual_text=_att.usual_text((doc or {}).get("usual")) if doc else "",
        days=recent, days_n=len(days),
        cfg={"weekHours": p.get("weekHours"), "weekMaxHours": p.get("weekMaxHours"),
             "breakPer4hMin": p.get("breakPer4hMin"), "standardDayHours": cu.get("standardDayHours")},
        mm={"months": {k: {x: v.get(x) for x in ("mm", "mm_lm29", "worked", "worked_lm29")}
                       for k, v in sorted(mo.items()) if isinstance(v, dict)},
            "total_mm": meta.get("total_mm"), "mm_lm29": meta.get("mm_lm29")})
    # LM30(2026-10-21) 유급휴가 보기(core\attendance 머리말 22) — 휴가로 본 날·휴가로 보지 않은 평일(날짜를 담는다 — 이 PC 화면에만 ·
    # 얼린 사본은 leave_n 으로 일수만 — freeze._att_summary_only)
    out["leave_lines"] = _att.leave_lines_for(meta, b, doc, local=True)
    out["leave_n"] = _att.leave_n_of(meta, b)
    return out


# ── LM30(2026-10-19) GERP 근무 기록 읽기 — 시험 기능(config attendance.gerp · 기본 꺼짐) ─────────────────────────────────
# '출퇴근·시간외 근무' 카드에 켜졌을 때만 [GERP 열기(직접 로그인)]·[GERP 근무 기록 읽기]와 상태 한 줄, 꺼져 있으면 짧은 안내 한 줄.
# 읽기는 run.py --web-only gerp(다른 웹 읽기 단추와 같은 작업 — Edge 정리·last_run 기록), 열기는 이 프로세스에서(프로세스를 띄우지 않는다).
# 주소는 화면으로 내보내지 않는다(켜짐·주소 있음만). 얼린 사본에는 /api/gerp 를 굽지 않는다(freeze.FREEZE_EPS 밖 — 카드에 아무것도 없다).
_GERP_MOD = {}


def _gerp_work():
    r"""collect\Get-GerpWork.py(이름에 '-' 가 있어 경로로 읽는다 · 한 번만) — [GERP 열기(직접 로그인)]가 같은 프로세스에서 open_login 을 부른다."""
    m = _GERP_MOD.get("m")
    if m is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("lm30_gerp_work", os.path.join(ROOT, "collect", "Get-GerpWork.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _GERP_MOD["m"] = m
    return m


def gerp_view():
    r"""GET /api/gerp — 카드의 GERP 줄 재료: 설정(attendance.gerp — 켜짐·주소 있음)·data\근태\gerp_status.json(지난 시도)·
    gerp.csv(모아 둔 날 수·기간). 파일만 읽는다(외부 전송·Edge 없음).
    LM30(2026-10-19) 카드에서 켜고 끈다 — url(저장한 주소: 주소 칸을 채우는 데만 · 이 PC 의 화면 서버(127.0.0.1)에서만 나간다)·host(켜졌을 때
    보이는 짧은 주소 — 호스트만). 상태 글(text)·로그·얼린 사본에는 주소를 싣지 않는다(얼린 사본은 /api/gerp 를 굽지 않는다)."""
    import attendance as _att
    import gerp as _gp
    g, _w = _att.norm_gerp(cfg())
    st = _gp.read_status(DATA)
    info = _gp.csv_info(DATA)
    keep = ("at", "ok", "kind", "rows", "gate_days", "period", "why", "last_ok_at")
    return {"ok": True, "enabled": bool(g["enabled"]), "url_ok": bool(g["url"]), "on": bool(g["on"]),
            "url": g["url"], "host": _gp.host_of(g["url"]),
            "off_text": _gp.OFF_TEXT, "text": _gp.status_text(st, g, info) if g["enabled"] else "",
            "status": {k: st[k] for k in keep if k in st}, "stored": info}


GERP_URL_MAX = 1000          # LM30(2026-10-19) 카드에서 받는 GERP 주소 길이 상한(config 를 손으로 고치면 2000 — attendance._gerp_url)


def gerp_config_check(body, cur):
    r"""POST /api/gerp_config 본문 검사(LM30 2026-10-19 — 카드의 [켜기]·[끄기]·[주소 바꾸기]) → (updates, 오류 글 | "").
    body = {"enabled": true|false, "url"?: 글} · cur = 지금 config(dict). url 이 없으면 저장한 주소를 그대로 둔다 · "" 이면 지운다(끌 때만).
    주소는 http·https 로 시작하는 한 줄(띄어쓰기·제어 문자·아이디@ 없이, 1000자 이하 — attendance._gerp_url 이 같은 규칙으로 본다).
    오류 글에는 주소를 싣지 않는다. updates = _save_cfg_many 에 넘길 [(경로, 값)] — gerp 블록이 없으면 기본값 블록을 통째로 만든다."""
    import attendance as _att
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return None, "켜기·끄기 값을 읽지 못했습니다 — 화면을 새로 고친 뒤 다시 누르세요"
    en = body["enabled"]
    a = cur.get("attendance") if isinstance(cur, dict) else None
    blk = a.get("gerp") if isinstance(a, dict) else None
    url = None
    if "url" in body:
        v = body.get("url")
        if not isinstance(v, str):
            return None, "GERP 주소는 글자여야 합니다"
        v = v.strip()
        if v:
            ok, bad = _att._gerp_url(v)
            if bad or not ok or len(ok) > GERP_URL_MAX:
                return None, ("GERP 주소는 http:// 또는 https:// 로 시작하는 한 줄 주소여야 합니다(띄어쓰기 없이 "
                              f"{GERP_URL_MAX}자 이하) — 로그인한 브라우저의 주소 창에서 그대로 복사해 넣으세요")
            v = ok
        url = v
    saved = _att.norm_gerp(cur)[0]["url"] if isinstance(cur, dict) else ""
    eff = saved if url is None else url
    if en and not eff:
        return None, "켜려면 GERP 근무시간 현황 화면 주소를 넣으세요(로그인한 브라우저의 주소 창에서 복사)"
    if not isinstance(blk, dict):
        return [(("attendance", "gerp"), dict(_att.GERP_DEFAULTS, enabled=en, url=eff))], ""
    ups = [(("attendance", "gerp", "enabled"), en)]
    if url is not None:
        ups.append((("attendance", "gerp", "url"), url))
    return ups, ""


def gerp_open():
    r"""POST /api/gerp_open — [GERP 열기(직접 로그인)]: 전용 Edge 에 GERP 근무 현황 화면을 연다(사람이 그 창에서 직접 로그인 — 아이디·
    비밀번호를 넣거나 저장하지 않는다). 꺼져 있거나 주소가 없으면 열지 않는다. → {"ok", "msg", "error"}"""
    import attendance as _att
    g, _w = _att.norm_gerp(cfg())
    if not g["on"]:
        return {"ok": False, "msg": "", "error": "GERP 근무 기록 읽기가 꺼져 있거나 주소가 비어 있습니다(config attendance.gerp)"}
    try:
        r = _gerp_work().open_login(g)
    except Exception as e:  # noqa: BLE001 - 열지 못한 까닭은 화면에 한 줄로
        r = {"ok": False, "why": f"전용 Edge 를 열지 못했습니다({type(e).__name__})"}
    msg = str(r.get("why") or "")
    log("[GERP] " + msg)
    return {"ok": bool(r.get("ok")), "msg": msg, "error": "" if r.get("ok") else msg}


def run_job(d0, d1, ai, skip, collect_only=False):
    try:
        # A34 — 종료일이 미래면 오늘로 당긴다: 미래 평일이 통째로 가용에 남아 로드율이 20% 대로 떨어지던 것.
        # (오늘 잔여 시간은 extract.mm_from_hours 가 now 로 비례 처리한다 — 산정 근거 노트 '가용 기준')
        today = time.strftime("%Y-%m-%d")
        if str(d1 or "") > today and len(str(d1 or "")) == 10:
            log(f"종료일 {d1} 이 미래라 오늘({today})로 조정 — 미래 날짜는 가용에서 제외됩니다")
            d1 = today
        cmd = [sys.executable, os.path.join(ROOT, "run.py"), "--from", d0, "--to", d1]
        if collect_only:
            # [로컬PC 자료수집](구 '추가 PC 수집'): 이 PC 자료만 모으고 분석·팀 서버 보고는 폴더를 옮긴 PC 의 [분석 실행]에서
            cmd.append("--collect-only")
        else:
            if ai:
                cmd.append("--ai")
            if skip:
                cmd.append("--skip-collect")
        log(f"실행: {d0} ~ {d1}" + (" · 로컬PC 자료수집(분석·팀 서버 보고 없음)" if collect_only else
            (" · AI 정제" if ai else "") + (" · 재분석만" if skip else "")))
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        job = proc.attach(p)                 # LM28: Job(KILL_ON_JOB_CLOSE+BREAKAWAY_OK) — 전용 Edge 는 이탈해 산다
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

        # 정체 감시 — 예전에는 자식이 멈추면 여기서 영원히 기다려 상태바가 '실행 중' 에서 벗어나지
        # 못했다(제보 '무한 정지'). 이제 무출력이 한도를 넘으면 트리를 끊고 이유를 로그에 남긴다.
        stopped = watch_child(p, _on, "분석 실행")
        p.wait()
        proc.release(job, p.pid)             # 남은 손자(고아)까지 정리 — 이미 닫혔으면 아무것도 안 한다
        if stopped:
            log(stopped)
            log("=== 중단(정체 감지) — [AI 연결 진단]으로 Copilot 창 상태를 확인한 뒤 다시 실행하세요 ===")
        else:
            log("=== 완료 ===" if p.returncode == 0 else f"=== 종료(코드 {p.returncode}) — 로그 확인 ===")
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
    정제본이 없으면(제외·재분류·재추출로 무효화) 빈 dict — 매핑은 그 정제본에만 유효하다(V-02)."""
    p = os.path.join(REPORT, f"refine_map_{tag}.json")
    if not os.path.exists(p) or not os.path.exists(os.path.join(REPORT, f"mm_rows_{tag}_refined.csv")):
        return {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            o = json.load(f)
    except (OSError, ValueError):
        return {}
    mp = o.get("map") if isinstance(o, dict) else None
    out = {}
    for k, v in (mp.items() if isinstance(mp, dict) else []):
        pairs = [(str(it[0] or "").strip(), str(it[1] or "").strip())
                 for it in (v if isinstance(v, list) else []) if isinstance(it, (list, tuple)) and len(it) >= 2]
        if pairs:
            out[str(k).strip()] = pairs
    return out


def _name_axes():
    """느슨한 이름 비교 축(core/details.fold·ukey3)과 세부업무 병합 캐시 — core 가 없으면 공백·대소문자 정규화만."""
    try:
        from details import fold, load_detail_aliases, ukey3
        try:
            amap = load_detail_aliases()
        except Exception:  # noqa: BLE001 - 깨진 캐시가 제외를 막지 않게
            amap = {}
        return fold, ukey3, amap
    except ImportError:
        def _plain(s):
            return " ".join(str(s or "").split()).casefold()
        return _plain, _plain, {}


def exclude_work(row_key):
    """오할당 확정 — '과제/세부업무' 행의 신호를 결과에서 제거하고 MM을 재집계한다.
    제외 이력은 config\\excluded_work.json 에 남아 다음 분석에도 적용된다(mine 이후 자동 제외는
    다음 판정에서 Copilot이 다시 넣을 수 있으므로, 여기 이력이 최종 방어선).
    화면 행은 정제본 이름이라 signals 의 (model, detail) 와 다를 수 있다(V-02) — refine 이 남긴 refine_map 으로
    정제 행 → 원본 쌍 전부(병합 행은 구성원 전부)를 풀고, 없으면 fold/ukey3·세부업무 병합 캐시로 느슨하게 맞추며,
    그래도 없으면 같은 과제의 후보 이름을 error 에 실어 안내한다."""
    sp = latest_signals()
    key = str(row_key or "").strip()
    if not sp or not key:
        return {"ok": False, "error": "no signals" if not sp else "bad row"}
    tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
    rows = _rows(sp)

    def _pair(r):
        return ((r.get("model") or r.get("project") or "").strip(),
                (r.get("detail") or r.get("activity") or "").strip())
    # 화면 행 이름 그대로 먼저(과제명에 '/' 가 있어도 refine_map 키는 그대로 맞는다), 그다음 '과제/세부업무' 로 나눈 쌍
    targets = set(_refine_map(tag).get(key) or [])
    if "/" in key:
        md, dt = (x.strip() for x in key.split("/", 1))
        targets.add((md, dt))
    if not targets:
        return {"ok": False, "error": "bad row"}
    hit = [r for r in rows if _pair(r) in targets]
    how = "exact"
    if not hit:
        # 느슨 일치 — 표기 변형(구분자·공백·괄호)과 세부업무 병합 캐시(detail_aliases)까지 같은 축으로 본다
        fold, ukey3, amap = _name_axes()

        def _axes(a, b, use_map):
            ks = {(fold(a), fold(b)), (fold(a), ukey3(b))}
            rep = amap.get((a, b)) if use_map else None
            if rep:
                ks |= {(fold(a), fold(rep)), (fold(a), ukey3(rep))}
            return ks
        # 1단계: 표기 변형만(구분자·공백·괄호). 2단계: 그래도 없을 때만 세부업무 병합 캐시까지 — 대시보드 행은 판정 이름
        # 그대로라 캐시의 다른 구성원('레이아웃 리뷰 회의')이 별도 행이다. 1단계에서 캐시를 함께 쓰면 이름 하나를 뺐는데
        # 같은 묶음의 다른 행 신호까지 지워졌다(재검증 실측).
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
        log(f"[제외] '{key}' — signals 에 일치하는 행 없음" + (f" · 같은 과제 후보 {len(cands)}개" if cands else ""))
        return {"ok": False, "candidates": cands,
                "error": "행을 찾지 못함 — " + (f"같은 과제의 후보: {' · '.join(cands)}" if cands else
                                          "signals 에 같은 과제가 없습니다(이미 제외됐거나 재추출·재분류로 이름이 바뀜) — [분석 실행] 뒤 다시")}
    hit_ids = {id(r) for r in hit}
    keep = [r for r in rows if id(r) not in hit_ids]
    dropped = hit
    removed = len(dropped)
    cols = ["time", "source", "who", "project", "activity", "weight", "text",
            "model", "worktype", "detail", "judge"]
    with open(sp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in keep:
            w.writerow({c: r.get(c, "") for c in cols})
    # 재집계 (judge.write_outputs 공용) + 낡은 정제본 무효화
    # 재집계가 실패하면 MM 이 옛 값 그대로다 — 성공으로 응답하면 사용자가 반영된 줄 안다.
    rh = None
    try:
        from judge import rehours_meta, write_outputs
        # A30 — 제외한 신호의 '시간' 도 총량에서 뺀다(mm_meta 갱신). 예전에는 신호만 줄고 total_mm 은
        # 그대로라 '내 업무 아님'을 빼도 로드율이 1pt 도 안 내려갔다. 실패해도 재집계는 계속(mine 값 유지).
        try:
            rh = rehours_meta(keep, dropped, tag, cfg(), REPORT, DATA, say=log)
        except Exception as e:  # noqa: BLE001 - 재산정 실패가 제외 자체를 막지 않게
            log(f"[제외] 시간 재산정 실패({type(e).__name__}: {str(e)[:80]}) — 투입 MM 은 이전 값 유지")
        write_outputs(keep, tag, cfg(), REPORT)
    except Exception as e:
        log(f"[제외] 재집계 실패: {type(e).__name__}: {e} — MM 이 갱신되지 않았습니다")
        return {"ok": False, "error": f"재집계 실패({type(e).__name__}) — 신호는 제거됐으니 [분석 실행]으로 재집계하세요"}
    for n in (f"mm_rows_{tag}_refined.csv", f"refine_map_{tag}.json"):   # 정제본과 그 매핑은 함께 무효화
        rf = os.path.join(REPORT, n)
        if os.path.exists(rf):
            os.remove(rf)
    # 이력 기록
    ep = os.path.join(ROOT, "config", "excluded_work.json")
    try:
        hist = json.load(open(ep, encoding="utf-8-sig")) if os.path.exists(ep) else []
    except (OSError, ValueError):
        hist = []
    hist.append({"row": key, "when": time.strftime("%Y-%m-%d %H:%M"), "signals": removed,
                 "dropped_h": (rh or {}).get("dropped_h"), "matched": how,
                 "pairs": sorted(f"{a}/{b}" for a, b in {_pair(r) for r in dropped})})
    with open(ep, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    log(f"[제외] '{key}' 확정 — 비업무 제외 {removed}건"
        + (f" (원본 {len(targets)}쌍 · {'정확' if how == 'exact' else '느슨'} 일치)" if len(targets) > 1 or how != "exact" else "")
        + (f"(누적 {rh['dropped_n']}건) · −{rh['dropped_h']:.1f}h → 투입 {rh['total_mm']:.2f} MM "
           f"(로드율 {rh['load_pct']:.0f}%)" if rh else " (시간 재산정 없음 — 투입 MM 유지)")
        + " · 재집계 (excluded_work.json 기록)")
    return {"ok": True, "removed": removed, "rehours": bool(rh), "matched": how, "pairs": len(targets),
            "dropped_n": (rh or {}).get("dropped_n"), "dropped_h": (rh or {}).get("dropped_h"),
            "total_mm": (rh or {}).get("total_mm"), "load_pct": (rh or {}).get("load_pct")}


# ── 수동 Agentic 니즈 발굴·워크플로우 재분석 (S2) ─────────────────────────────────
# 옛 판은 POST 핸들러가 subprocess.run(timeout=420/960) 으로 끝까지 기다렸다 — 업무가 많은 사람은
# 묶음 13~49회(회당 수십 초~수 분)라 반드시 시간 초과로 죽고(자식은 kill), 진행률도 안 보이고, 새로고침하면
# 결과·사유가 사라졌다. 이제 [분석 실행]과 같은 방식으로 스레드에서 돌리며 [progress] 를 진행 바에 흘리고,
# 마지막 줄 JSON(ok/error/hint)을 MANUAL 에 남겨 GET /api/agentic·/api/workflow 가 화면에 전한다.
TOOL_JOBS = {"agentic": ("agentic.py", "Agentic AI 니즈 발굴"), "flow": ("flow.py", "워크플로우 분석")}
MANUAL = {}                       # kind → 마지막 수동 실행 결과 {ok,error,hint,at,sec,tag,...}


def _tag_args():
    """화면이 보고 있는 기간(latest_signals 의 tag) → ['--from', d0, '--to', d1] (없으면 [])."""
    sp = latest_signals()
    if not sp:
        return "", []
    t = os.path.basename(sp)[len("signals_"):-len(".csv")]
    if len(t) == 17 and t[8] == "-":
        return t, ["--from", f"{t[:4]}-{t[4:6]}-{t[6:8]}", "--to", f"{t[9:13]}-{t[13:15]}-{t[15:]}"]
    return t, []


# v3: 감시기 한 벌 — core/watch 임포트(복제 3함수 삭제 · 구조 감사 4계층)
import proc  # noqa: E402  — LM28: 자식은 Job 에 넣고 끊을 때 Job 째(taskkill 을 띄우지 않는다 · P6)
import watch as _watch_mod  # noqa: E402
from watch import stage_limits as _core_stage_limits  # noqa: E402
from watch import watch_child as _core_watch_child  # noqa: E402

# 이 프로세스 안에서만 감시기의 종료를 Job 으로 바꾼다(run.py 와 같은 방식) — 전용 Edge 는 Job 에서 이탈해 산다
_watch_mod.kill_tree = proc.kill_tree
kill_tree = proc.kill_tree  # 기존 호출부 이름 유지


def _stage_limits():
    return _core_stage_limits(cfg() if callable(globals().get("cfg")) else {})


_WATCH_STATE_PATH = {"p": None}      # 다음 watch_child 가 볼 상태 파일 — tool_job 이 세팅


def watch_child(p, on_line, label, beat_sec=120):
    def _on(ln):                    # 화면의 "마지막 소식 N초 전" — 자식 출력 시각을 JOB 에 남긴다
        try:
            with LOCK:
                JOB["last_out"] = time.time()
        except Exception:  # noqa: BLE001
            pass
        on_line(ln)
    return _core_watch_child(p, _on, label, beat_sec=beat_sec,
                             cfg_dict=(cfg() if callable(globals().get("cfg")) else {}),
                             state_path=_WATCH_STATE_PATH.get("p"))


def tool_job(kind, extra=()):
    """agentic.py / flow.py 를 스레드에서 끝까지 돌리고 결과를 MANUAL[kind] 에 남긴다(run_job 과 같은 프로토콜).
    인자가 없으면 두 스크립트는 mm_meta 최신 기간을 잡아 화면과 어긋난 파일에 쓸 수 있으므로 기간을 명시한다."""
    script, step = TOOL_JOBS[kind]
    t0 = time.time()
    tag, targs = _tag_args()
    _WATCH_STATE_PATH["p"] = (os.path.join(REPORT, f"stage_state_{tag}_{kind}.json") if tag else None)
    res = {"ok": False, "error": "실행 실패", "hint": ""}
    run = chat_job_run()                 # LM30 — 이 작업이 연 Copilot 채팅을 한 실행으로 묶는다(끝 한 줄 — job_chat_end)
    try:
        cmd = [sys.executable, os.path.join(ROOT, script)] + targs + list(extra)
        log(f"[{step}] 시작 — 기간 {tag or '(최신)'}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", LM_CHAT_RUN=run),
                             creationflags=NO_WIN)
        job = proc.attach(p)                 # LM28: 끊을 때 Job 째(taskkill 없음)
        with LOCK:
            JOB["pid"] = p.pid
        last, tail = None, ""
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

        # 정체 감시 — 자식이 멈추면 트리를 끊고 이유를 남긴다(제보 '무한 정지': 화면이 실행 중에서 못 벗어났다)
        stopped = watch_child(p, _on, step)
        p.wait()
        proc.release(job, p.pid)
        last, tail = box["last"], box["tail"]
        if stopped:
            res = {"ok": False, "error": "중단(정체 감지)", "hint": stopped}
            log(stopped)
        elif last is None:
            # 자식이 죽으면 사유는 마지막 로그 줄(스택 끝)에 있다 — 버리면 빈 힌트만 남는다
            res = {"ok": False, "error": "출력 해석 실패",
                   "hint": (tail[:200] if tail else f"종료 코드 {p.returncode}") + " — 진행 로그를 확인하세요"}
        else:
            res = last
            if p.returncode == 2:
                res["partial"] = True           # v3 rc 규약: 2 = 부분(성공) — 다음 실행이 이어서
            elif p.returncode != 0 and res.get("ok"):
                res["ok"] = False
        log(f"=== {step} " + ("완료" if res.get("ok") else f"실패: {str(res.get('error') or '')[:80]}"
                                + (f" — {str(res.get('hint') or '')[:120]}" if res.get("hint") else "")) + " ===")
        cl = job_chat_end(run, step)         # LM30 — 이 작업이 연 Copilot 채팅을 지우고 한 줄(연·지운·남긴 수와 까닭)
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


def narrate_cmd(tag, all_months=False):
    """[리뷰 코멘트 재생성] 의 judge.py 명령 — 기간(tag 'YYYYMMDD-YYYYMMDD') + --narrate-only (+ all_months 면 --all)."""
    d0, d1 = tag.split("-")
    return ([sys.executable, os.path.join(ROOT, "judge.py"),
             "--from", f"{d0[:4]}-{d0[4:6]}-{d0[6:]}", "--to", f"{d1[:4]}-{d1[4:6]}-{d1[6:]}", "--narrate-only"]
            + (["--all"] if all_months else []))


def narrate_job(all_months=False):
    """9a — 리뷰 코멘트(월별 내러티브)만 다시 생성한다.
    다른 PC로 옮기면 report\\ 를 복사하지 않으므로 코멘트가 비어 보인다. 판정 결과
    (signals)만 있으면 왕복 몇 번으로 되살릴 수 있다.
    기본은 빠진 달·최근 달·데이터가 바뀐 달만 다시 만든다(바뀌지 않은 달은 보내지 않는다 — judge.narrate).
    all_months=True 면 모든 달을 새로 만든다(--all). judge rc: 0 = 한 달 이상 만들었거나 다시 만들 달이 없음 ·
    1 = AI 판정된 신호가 없거나 하나도 만들지 못함(이전 코멘트는 그대로)."""
    try:
        sp = latest_signals()
        if not sp:
            log("[리뷰] 판정 결과가 없습니다 — [분석 실행]에 'AI 판정'을 켜고 먼저 돌리세요")
            return
        tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
        cmd = narrate_cmd(tag, all_months)
        log(f"[리뷰] {tag} 코멘트 재생성 시작 — "
            + ("모든 달 다시 만들기" if all_months else "빠진 달·최근 달·데이터가 바뀐 달만"))
        run = chat_job_run()             # LM30 — 이 작업이 연 Copilot 채팅을 한 실행으로 묶는다(끝 한 줄 — job_chat_end)
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                      PYTHONUNBUFFERED="1", LM_CHAT_RUN=run), creationflags=NO_WIN)
        with LOCK:
            JOB["pid"] = p.pid
        job = proc.attach(p)

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
            log(line)

        stopped = watch_child(p, _on, "리뷰 코멘트")      # 멈추면 끊는다 — 화면이 '실행 중' 에 갇히지 않게
        p.wait()
        proc.release(job, p.pid)
        if stopped:
            log(stopped)
            log("=== 리뷰 생성 중단(정체 감지) ===")
        else:
            log("=== 리뷰 코멘트 완료 ===" if p.returncode == 0
                else "=== 리뷰 코멘트를 새로 만들지 못했습니다 — 위 사유를 확인하세요(이전 코멘트는 그대로 둡니다) ===")
        job_chat_end(run, "리뷰")            # LM30 — 이 작업이 연 Copilot 채팅을 지우고 한 줄
    except Exception as e:
        log(f"오류: {e}")
    finally:
        with LOCK:
            JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)


RESET_RETRY_SEC = 1.5     # LM28(2026-10-19) 첫 번에 못 지운 파일을 한 번 더 지우기 전 쉼(초) — 백신 검사·미리보기·동기화처럼 잠깐 잡은 것
HOLDER_MAX = 20           # 잡고 있는 프로그램 이름을 물어볼 파일 수 상한(Restart Manager 세션을 파일마다 1개 — 짧다)
_REPARSE_POINT = 0x400    # FILE_ATTRIBUTE_REPARSE_POINT
_NAME_SURROGATE = 0x20000000    # 다른 경로를 가리키는 재분석 태그(정션·심볼릭 링크 — IsReparseTagNameSurrogate)


def _xlong(p):
    r"""확장 경로(\\?\ — 260자 넘는 경로도 읽고 지운다). 리셋이 걷는 뿌리(report\·data\)에는 늘 붙인다 — 뿌리가 짧아도 그 아래가 길 수
    있고, 뿌리에 붙여 두면 os.walk 가 내놓는 모든 경로가 확장 경로가 된다(teamup.longp 는 240자 넘을 때만 붙인다 — 파일 하나는 _longp).
    윈도가 아니거나 이미 붙었으면 그대로."""
    p = str(p)
    if os.name != "nt" or p.startswith("\\\\?\\"):
        return p
    p = os.path.abspath(p)
    return ("\\\\?\\UNC" + p[1:]) if p.startswith("\\\\") else ("\\\\?\\" + p)


def _plain(p):
    r"""확장 경로 → 보통 경로(화면·기록·상대 경로 계산용)."""
    p = str(p)
    if p.startswith("\\\\?\\UNC\\"):
        return "\\" + p[7:]
    return p[4:] if p.startswith("\\\\?\\") else p


def _longp(p):
    r"""파일 하나의 경로 — 260자 넘으면 확장 경로로(teamup.longp — 짧으면 그대로). 이미 붙었으면 그대로. teamup 을 못 읽는 판이면 같은
    규칙(240자 넘으면)을 여기서."""
    p = str(p)
    if p.startswith("\\\\?\\"):
        return p
    try:
        from teamup import longp
        return longp(p)
    except Exception:  # noqa: BLE001 - 경로 늘이기는 덤 — 실패해도 지우기는 한다
        q = os.path.abspath(p)
        return _xlong(q) if len(q) >= 240 else q


def _rel(p, base_dir):
    r"""설치 폴더 기준 상대 경로(화면·기록용) — 확장 경로는 풀고, 드라이브가 다르면(relpath 가 ValueError) 절대 경로 그대로."""
    q = _plain(p)
    try:
        return os.path.relpath(q, base_dir)
    except ValueError:
        return q


def _link_dir(p):
    r"""정션·심볼릭 링크처럼 **다른 곳을 가리키는** 폴더인가 — lstat 의 FILE_ATTRIBUTE_REPARSE_POINT 와 이름 대리 태그(shutil.rmtree 의
    정션 판정과 같은 갈래). OneDrive 자리표시자 같은 다른 재분석 지점은 그 자리의 진짜 폴더라 들어간다(lstat 이 태그 없이 돌려준다).
    lstat 을 못 하면 참(들어가지 않는다 — 모르면 지우지 않는 쪽)."""
    import stat
    try:
        st = os.lstat(p)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0) or 0
    tag = getattr(st, "st_reparse_tag", 0) or 0
    return bool(attrs & _REPARSE_POINT and tag & _NAME_SURROGATE)


def _rm_file(path, tries=3, pause=0.3):
    r"""파일 하나 지우기 → 지웠나(이미 없으면 참). LM28(2026-10-18 — 제보 "데이터 리셋이 실패하는 경우가 있음"): 읽기 전용 파일(다른 PC·
    USB·공유 폴더에서 옮겨 온 자료)은 읽기 전용을 풀고, 잠깐 잠긴 파일(화면이 그 파일을 읽는 중 · 백신 검사 · OneDrive 동기화)은 잠깐
    쉬었다 다시 지운다. 예전에는 한 번 실패하면 말없이 건너뛰어 '리셋 완료'인데 결과가 그대로 남았다.
    LM28(2026-10-19): 260자 넘는 경로는 확장 경로(\\?\ — _longp)로 풀고 지우고, '지웠다' 는 지운 뒤 파일이 정말 없을 때만 센다 — 예전에는
    FileNotFoundError 를 지운 것으로 셌는데, 너무 긴 경로는 WinError 3(경로 없음)으로 나와 파일이 남았는데도 '지움' 이었다."""
    import stat
    lp = _longp(path)
    for i in range(max(1, int(tries))):
        try:
            os.remove(lp)
        except FileNotFoundError:
            pass                                    # '없다' 는 말만 믿지 않는다 — 아래에서 정말 없는지 본다
        except PermissionError:
            try:
                os.chmod(lp, stat.S_IWRITE)         # 읽기 전용이면 풀고 곧바로 한 번 더(아니면 그대로)
                os.remove(lp)
            except OSError:
                pass
        except OSError:
            pass
        if not os.path.lexists(lp):
            return True
        if i + 1 < tries:
            time.sleep(pause)
    return False


def _rm_holders(path):
    r"""LM28(2026-10-19) — 그 파일을 열고 있는 프로세스 → [(pid, 앱 이름, 서비스 이름)]. Windows Restart Manager(rstrtmgr.dll —
    RmStartSession · RmRegisterResources · RmGetList · RmEndSession)를 ctypes 로 한 세션 부른다(관리자 권한 없음 · 새 프로세스 없음).
    윈도가 아니거나 어떤 오류든 [](이름은 덤 — 모르면 화면이 예전 일반 문구를 쓴다)."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _UniqueProcess(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

        class _ProcessInfo(ctypes.Structure):
            _fields_ = [("Process", _UniqueProcess), ("strAppName", wintypes.WCHAR * 256),      # CCH_RM_MAX_APP_NAME + 1
                        ("strServiceShortName", wintypes.WCHAR * 64),                          # CCH_RM_MAX_SVC_NAME + 1
                        ("ApplicationType", ctypes.c_int), ("AppStatus", wintypes.ULONG),
                        ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]

        rm = ctypes.WinDLL("rstrtmgr")
        rm.RmStartSession.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR)
        rm.RmRegisterResources.argtypes = (wintypes.DWORD, wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR),
                                           wintypes.UINT, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p)
        rm.RmGetList.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
                                 ctypes.POINTER(_ProcessInfo), ctypes.POINTER(wintypes.DWORD))
        rm.RmEndSession.argtypes = (wintypes.DWORD,)
        for fn in (rm.RmStartSession, rm.RmRegisterResources, rm.RmGetList, rm.RmEndSession):
            fn.restype = wintypes.DWORD
        sess = wintypes.DWORD(0)
        key = ctypes.create_unicode_buffer(33)                         # CCH_RM_SESSION_KEY + 1
        if rm.RmStartSession(ctypes.byref(sess), 0, key) != 0:
            return []
        try:
            q = _plain(path)
            q = q if len(q) < 260 else str(path)
            if rm.RmRegisterResources(sess, 1, (wintypes.LPCWSTR * 1)(q), 0, None, 0, None) != 0:
                return []
            reasons, n = wintypes.DWORD(0), 0
            for _ in range(3):                                         # 사이에 늘었으면(ERROR_MORE_DATA) 다시
                need, have = wintypes.UINT(0), wintypes.UINT(n)
                buf = (_ProcessInfo * n)() if n else None
                rc = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(have), buf, ctypes.byref(reasons))
                if rc == 0:
                    return ([(int(buf[i].Process.dwProcessId), str(buf[i].strAppName or "").strip(),
                              str(buf[i].strServiceShortName or "").strip()) for i in range(min(have.value, n))]
                            if buf is not None else [])
                if rc != 234:                                          # ERROR_MORE_DATA 가 아니면 모른다
                    return []
                n = int(need.value) + 2
            return []
        finally:
            rm.RmEndSession(sess)
    except Exception:  # noqa: BLE001 - 이름은 덤이다
        return []


def file_holders(paths, report=None):
    r"""LM28(2026-10-19) — 못 지운 파일을 누가 열고 있나 → {경로(받은 그대로): '이름 · 이름'}. 파일마다 _rm_holders(Restart Manager)를
    부른다(HOLDER_MAX 개까지). 이 프로세스 → '이 대시보드', report\teamserver.pid 의 pid → '팀 서버', 그 밖은 윈도가 아는 이름
    (Microsoft Excel · Microsoft OneDrive · Windows 탐색기 등). 모르는 파일은 빠진다 — 화면이 예전 일반 문구를 쓴다."""
    out = {}
    if os.name != "nt" or not paths:
        return out
    try:
        with open(os.path.join(report or REPORT, os.path.basename(TS_PID)), encoding="utf-8") as f:
            ts_pid = int((f.read() or "0").strip() or 0)
    except (OSError, ValueError):
        ts_pid = 0
    me = os.getpid()
    for p in list(paths)[:HOLDER_MAX]:
        names = []
        for pid, app_name, svc in _rm_holders(p):
            nm = ("이 대시보드" if pid == me else "팀 서버" if ts_pid and pid == ts_pid
                  else (app_name or svc or f"프로그램(pid {pid})"))
            if nm not in names:
                names.append(nm)
        if names:
            out[p] = " · ".join(names[:4])
    return out


def reset_busy_hint(step):
    r"""LM28(2026-10-19) — [데이터 리셋]을 지금 할 수 없는 까닭(409 hint). 무엇이 돌고 있는지 이름을 넣는다 — 예전에는 '작업 실행 중'
    한 마디라 무엇을 기다려야 하는지 몰랐다(분석 끝의 팀 서버 보고·공유폴더 내보내기·Edge 닫기가 몇십 초 더 돈다)."""
    s = re.sub(r"\s+", " ", str(step or "")).strip()
    s = re.split(r" \(| — | - ", s)[0].strip()[:40] or "분석 실행"
    return f"지금 '{s}' 작업이 돌고 있어 리셋할 수 없습니다 — 위 상태가 '대기'로 바뀐 뒤 다시 누르세요"


def reset_files(what="report", keep_queue=True, report=None, data=None, failed=None, detail=None):
    r"""[데이터 리셋] — report\(what='all' 이면 data\ 도) 아래 파일을 지운다 → (지운 파일 수, 보존한 월별 코멘트 파일 수).
    · Copilot 로그인 세션(data\<lmname.EDGE_PROFILE_NAME>)은 늘 보존, 아직 못 보낸 팀 업로드 묶음(upload_pending)은 keep_queue 면 보존.
    · '분석 결과만 삭제'(what != 'all')는 월별 리뷰 코멘트(report\ai_narratives_*.json)를 남긴다 — Copilot 왕복 수십 번으로
      만든 것이고 같은 달 코멘트는 다음 분석이 이월해 쓴다(진단 C). 지우려면 수집 데이터+결과 리셋(what='all').
    · 같은 이유로 AI 판정 기록(report\judge_cache.json — 내용 해시 → 판정, 원문 없음)도 남긴다. 지우면 다음 분석이 수천 건을
      처음부터 다시 물어 Copilot 사용량 제한에 다시 걸린다. 다시 쓰는 판정의 과제명은 judge 가 매번 다시 거른다.
    · LM28(2026-10-18): 지우기는 _rm_file(읽기 전용 풀기 · 잠깐 잠긴 파일은 다시)로 하고, 끝내 못 지운 파일은 failed(목록을 주면)에
      설치 폴더 기준 상대 경로로 담는다 — 화면이 '몇 개는 다른 프로그램이 쓰고 있어 못 지웠다'고 말한다.
    · LM28(2026-10-19):
      - 팀 서버의 제 파일(report\teamserver.log·.pid·.token — TS_FILES)은 지우지 않는다(켜진 서버가 쓰고 있다).
      - Copilot 기록(data\<프로필>.chats.json·.pace.json·.wait.json·.busy.lock 등 — 프로필 이름 + '.' 로 시작하는 data\ 바로 아래 파일)은
        Copilot 세션과 함께 남긴다. chats.json 은 어느 Copilot 채팅이 LM 것인지의 기록이라 잃으면 LM 이 제 채팅을 지우지 못한다.
      - 프로필 폴더는 걷기에서 아예 빼고, 정션·심볼릭 링크 폴더(_link_dir)는 들어가지 않는다 — 그 너머(설치 폴더 밖일 수 있다)를 지우지 않는다.
      - 뿌리를 확장 경로(_xlong)로 걸어 260자 넘는 경로도 지우고 '정말 없을 때만' 지운 것으로 센다(_rm_file).
      - 못 읽은 폴더(os.walk onerror)는 까닭과 함께 failed 에 넣는다. 못 지운 파일은 RESET_RETRY_SEC 뒤 한 번 더 지우고, 그래도 남으면
        잡고 있는 프로그램 이름(file_holders)을 detail 에 담는다.
      detail(dict 를 주면): holders{상대 경로: 이름} · reasons{상대 경로: 까닭} · kept[보존한 파일 이름] · links[들어가지 않은 연결]."""
    report = report or REPORT
    data = data or DATA
    base_dir = os.path.dirname(os.path.abspath(report))
    prof = lmname.EDGE_PROFILE_NAME.lower()
    ts_keep = {x.lower() for x in TS_FILES}
    try:                                             # LM30(2026-10-21) 사람이 적은 휴가 날짜(data\근태\휴가_직접입력.csv)는 수집 자료가 아니다 — 남긴다
        import attendance as _att
        lv_keep = (_att.RECORDS_DIR.lower(), _att.MANUAL_LEAVE_CSV.lower())
    except ImportError:
        lv_keep = None
    removed = kept_nar = 0
    left, kept, links, stuck = [], [], [], []      # 다시 지울 것 · 보존한 이름 · 들어가지 않은 연결 · 못 읽은 폴더(경로, 까닭)

    def _onerr(e):
        if isinstance(e, (FileNotFoundError, NotADirectoryError)):
            return                                   # 없는 폴더(data\ 가 아직 없음 · 걷는 사이 사라짐) — 지울 것이 없다
        stuck.append((getattr(e, "filename", "") or "",
                       "폴더를 읽지 못함(" + ("권한 없음" if isinstance(e, PermissionError) else type(e).__name__) + ")"))

    for base, kind in [(report, "report")] + ([(data, "data")] if what == "all" else []):
        xbase = _xlong(base)
        top_key = os.path.normcase(xbase)
        for root, dirs, files in os.walk(xbase, onerror=_onerr):
            top = os.path.normcase(root) == top_key
            walk = []
            for dn in dirs:
                dl = dn.lower()
                if dl == prof:                       # Copilot 로그인 세션 — 통째로 보존(들어가지 않는다)
                    continue
                if keep_queue and dl == "upload_pending":
                    continue                         # 보내야 할 것을 리셋으로 잃지 않게(검증 지적)
                if _link_dir(os.path.join(root, dn)):
                    links.append(os.path.join(root, dn))
                    continue                         # 정션·링크 너머는 설치 폴더 밖일 수 있다 — 들어가지도 지우지도 않는다
                walk.append(dn)
            dirs[:] = walk
            for fn in files:
                fl = fn.lower()
                if top and kind == "report" and fl in ts_keep:
                    kept.append(fn)                  # 팀 서버의 제 파일
                    continue
                if top and kind == "data" and fl.startswith(prof + "."):
                    kept.append(fn)                  # Copilot 기록(채팅 소유·보내기 간격·쉬는 시간·잠금)
                    continue
                if (lv_keep and kind == "data" and fl == lv_keep[1]
                        and os.path.basename(os.path.normpath(root)).lower() == lv_keep[0]):
                    kept.append(fn)                  # LM30(2026-10-21) '휴가 날짜' 칸에 사람이 적은 유급휴가 날짜
                    continue
                if what != "all" and top and kind == "report" and fn.startswith("ai_narratives_") and fn.endswith(".json"):
                    kept_nar += 1
                    continue
                if what != "all" and top and kind == "report" and fn == "judge_cache.json":
                    continue
                p = os.path.join(root, fn)
                if _rm_file(p):
                    removed += 1
                else:
                    left.append(p)
    if left:
        time.sleep(RESET_RETRY_SEC)                  # 잠깐 잡았던 프로그램(백신 검사·미리보기·동기화)이 놓을 틈 — 한 번만 더
        again = [p for p in left if not _rm_file(p, tries=1)]
        removed += len(left) - len(again)
        left = again
    names = file_holders(left, report=report) if left else {}
    holders, reasons = {}, {}
    for p in left:
        rp = _rel(p, base_dir)
        if isinstance(failed, list):
            failed.append(rp)
        if p in names:
            holders[rp] = names[p]
    for fp, why in stuck:
        rp = _rel(fp, base_dir)
        if isinstance(failed, list):
            failed.append(rp)
        reasons[rp] = why
    if isinstance(detail, dict):
        detail.update(holders=holders, reasons=reasons, kept=sorted(set(kept)), links=[_rel(x, base_dir) for x in links])
    return removed, kept_nar


TEAM_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>LoadMonitor30 — 팀 취합</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic',system-ui,sans-serif;background:#f2f4f7;color:#12151a;padding:22px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:20px}h1 small{font-size:11px;color:#8b929b;font-weight:400;margin-left:8px}
.sub{font-size:11.5px;color:#5a626b;margin:3px 0 14px}
.card{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}
.card h2{font-size:13px;margin-bottom:10px;color:#2c333b}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px}
.kpi{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px}
.kpi .lb{font-size:10.5px;color:#8b929b}.kpi .vl{font-size:21px;font-weight:800;margin:2px 0}
.kpi .nt{font-size:10.5px;color:#5a626b}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;border-bottom:2px solid #e4e7eb;font-size:11px}
td{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px}
button.run{background:#2a78d6;color:#fff;border:0;border-radius:5px;padding:8px 20px;font-size:12.5px;font-weight:700;cursor:pointer;font-family:inherit}
button.run:disabled{background:#c9cfd8}
button.ghost{background:#fff;color:#4a5159;border:1px solid #c9cfd8;border-radius:5px;padding:6px 12px;font-size:12px;cursor:pointer;font-family:inherit}
.note{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}
.tag{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}}
.state{font-size:11px;color:#8b929b;font-weight:400}
body.snap .nosnap{display:none}
body.snap .snaponly{display:block}
.snaponly{display:none;font-size:11px;color:#8b929b;margin-bottom:10px}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;font-size:11.5px}
.steps a,.steps span{display:inline-block;padding:5px 10px;border-radius:14px;border:1px solid #d7dbe0;background:#fff;color:#4a5159;text-decoration:none}
.steps .on{background:#2a78d6;border-color:#2a78d6;color:#fff;font-weight:700}
</style></head><body><div class="wrap">
<h1>팀 취합<small id="ver">LoadMonitor30</small></h1>
<div class="sub">공유폴더의 인별 결과를 실시간으로 읽어 시각화합니다. 원본 파일은 수정하지 않습니다.</div>
<div class="steps nosnap">
 <a href="/" target="_blank">① 내 PC 분석</a>
 <a href="/" target="_blank">② 결과 확인</a>
 <a href="/" target="_blank">③ 팀 서버 보고(자동) / 공유폴더 저장</a>
 <span class="on">④ 팀 취합 (지금 화면)</span>
 <a href="/team/report" target="_blank">리포트</a>
 <a href="/team/full" target="_blank">통합 보고서</a>
 <a href="/guide" target="_blank">사용 안내</a>
</div>

<div class="card nosnap"><h2>팀 서버 (이 PC 에서 켜기) <span class="state">팀 결과를 모아 취합하는 쪽 — 팀 공용 PC 에서만 켜면 됩니다</span></h2>
 <div class="row" style="align-items:center;gap:10px">
  <span id="tsstate" class="state">확인 중…</span>
  <button class="ghost" id="tsstart">팀 서버 시작</button>
  <button class="ghost" id="tsstop">중지</button>
  <button class="ghost" id="tsopen">팀 대시보드 열기</button>
  <button class="ghost" id="tstake" style="display:none">포트 가져오기</button>
  </div>
 <div class="note" id="tsaddr"></div>
 <div class="note" id="tsurl"></div>
 <div class="note">여기서 켜면 이 PC 가 팀 취합 서버가 됩니다. 서버 IP·포트는 설치 폴더의 <b>LoadMonitor30-팀서버주소.bat</b>
 에서만 바꿉니다 — config\\team_server.json 에 저장되어, 이 폴더를 통째로 옮기거나 팀원에게 나눠 주면 같은 주소가
 그대로 따라갑니다. 팀원은 분석 후 그 주소로 [팀 서버 업로드]를 누르면 됩니다. 포트를 바꾼 뒤에는 켜져 있던 서버를
 [중지] 후 [팀 서버 시작]해야 새 포트로 열립니다. 대시보드를 닫아도 서버는 계속 돕니다(중지는 이 버튼으로).
 처음 켤 때 방화벽 허용 창이 뜨면 <b>허용</b>해야 다른 PC 에서 접속됩니다.</div></div>
<div class="snaponly" id="snapinfo"></div>
<div class="card nosnap"><h2>데이터 읽어오는 곳 — 팀 공유폴더</h2>
 <div class="row">
  <input id="sharedir" placeholder="예: \\\\서버\\팀공유\\LoadMonitor  또는  D:\\팀취합" style="flex:1;min-width:280px;border:1px solid #c9cfd8;border-radius:5px;padding:7px 10px;font:inherit;font-size:12px">
  <button class="run" id="savedir" style="padding:7px 16px;font-size:12px">경로 저장</button>
  <span id="dirstate" style="font-size:11.5px"></span>
 </div>
 <div class="note">각 팀원의 결과가 <b>&lt;이 폴더&gt;\\&lt;이름&gt;\\</b> 으로 내보내진 곳입니다. 저장하면 즉시 이 폴더를 읽어 아래를 갱신합니다
 (config.teamShareDir 에 저장 — 팀원 PC의 내보내기 대상도 같은 키를 씁니다).</div></div>

<div class="card nosnap"><div class="row">
 <button class="ghost" id="reload">새로고침</button>
 <button class="run" id="refine">Copilot으로 유사 항목 정리</button>
 <button class="ghost" id="undoalias" style="display:none">정리 되돌리기</button>
 <button class="ghost" id="savehtml">정적 리포트 다시 만들기 (team_report·통합 보고서)</button>
 <label title="켜면(기본) 아래 '과제 × 인원'·'공통업무'·'세부업무 상위'에서 팀 합산 MM이 0.04 이하인 줄과 이름표를 숨기고, 표 아래에 숨긴 개수와 합을 적습니다 — 화면 표시만 바꾸고 인원·로드율·저장하는 리포트는 그대로입니다 · 대시보드 옵션 줄과 같은 설정(이 PC)"><input type="checkbox" id="hidesm" checked> 0.04 MM 이하 숨기기</label>
 <span class="state" id="msg" style="font-size:11.5px;color:#5a626b"></span>
</div>
<div class="row" style="margin-top:8px">
 <button class="run" id="fullopen" disabled>팀 통합 보고서 열기</button>
 <button class="ghost" id="fullv3" disabled>v3 (로드율 제외)</button>
 <button class="ghost" id="fullmake">다시 만들기</button>
 <button class="ghost" id="fullsnap">스냅샷 저장</button>
 <span class="state" id="fullat" style="font-size:11.5px;color:#5a626b"></span>
</div>
<div class="note">팀 통합 보고서(team_full_report.html): 로드율·과제×인원·업무유형·워크플로우를 한 장에 담은
정적 파일 — 팀원 업로드마다 자동 갱신되고 [다시 만들기]로 즉시 새로 만듭니다(Copilot 없이 저장된 통합만 적용).
v3 는 인별 로드율을 뺀 공유용, [스냅샷 저장]은 팀통합보고서_&lt;시각&gt;.html 사본을 취합 폴더에 남깁니다.</div>
<div class="note">유사 항목 정리: 인별 분석에서 갈라진 표기('설계 검토'/'설계안 검토' 등)를 Copilot이
같은 실체끼리 묶어 대표 이름으로 통합합니다. 매핑만 얹으므로(team_aliases.json) 원본은 그대로이며
[정리 되돌리기]로 즉시 원상복구됩니다.</div></div>

<div class="kpis">
 <div class="kpi"><div class="lb">인원</div><div class="vl" id="k_n">–</div><div class="nt" id="k_nn"></div></div>
 <div class="kpi"><div class="lb">팀 로드율 (투입÷가용)</div><div class="vl" id="k_load">–</div><div class="nt" id="k_mm"></div></div>
 <div class="kpi"><div class="lb">과제 수</div><div class="vl" id="k_pj">–</div><div class="nt" id="k_alias"></div></div>
</div>

<div class="card"><h2>취합 현황 <span class="state">누가·언제·어디서 올렸는지 — 빠진 사람이 있는지 여기서 확인합니다</span></h2>
 <div id="whotbl"></div>
 <div class="note">‘올린 시각’은 그 사람이 업로드(또는 공유폴더 저장)한 때이고, ‘분석’은 그 PC 에서 분석을 돌린 때입니다.
 옛 버전으로 올린 자료는 이 값이 비어 있어 파일이 놓인 시각만 보입니다.</div></div>

<div class="card"><h2>인별 로드율 <span class="state" style="font-weight:400;font-size:11px;color:#8b929b">회색 눈금 = 100% (가용을 꽉 채움) · 초과분은 주황</span></h2>
 <div id="loadbars"></div></div>

<div class="grid2">
 <div class="card"><h2>과제 × 인원 (투입 MM)</h2><div id="pjstack"></div><div class="row" id="pjleg" style="margin-top:6px"></div></div>
 <div class="card"><h2>업무유형 분포 (인별)</h2><div id="wtstack"></div></div>
</div>

<div class="grid2">
 <div class="card"><h2>팀 Agentic AI 니즈 후보 <span class="state" id="needst"></span></h2>
  <div class="note" style="margin:0 0 4px">팀원 각자의 반복 업무에서 찾은 자동화 니즈 후보를 이름으로 합쳤습니다 — 팀 과제와 매칭하지 않습니다 · 근거 업무 N행 = 제안한 사람들의 근거 업무 행 수 합(MM 아님)</div>
  <div id="needlist"></div></div>
 <div class="card"><h2>공통업무 (여러 사람·여러 과제 반복)</h2><table id="commtbl"></table><div class="note" id="commsm" style="display:none"></div></div>
</div>

<div class="card"><h2>세부업무 상위 (팀 합산) <span class="state" style="font-weight:400;font-size:11px;color:#8b929b">유사 항목 정리 후 같은 일이 한 줄로 합쳐졌는지 확인</span></h2>
 <table id="dtltbl"></table>
 <div class="note" id="dtlsm" style="display:none"></div></div>

</div><script>
const $=id=>document.getElementById(id);
const PAL=["#2a78d6","#0e8c7a","#a61b4a","#e08a00","#6c4fb8","#3d8f3d","#c05a78","#4a7f9e","#8a6d3b","#556270"];
const WTC={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
let D=null;
// ── LM30(2026-10-25) '0.04 MM 이하 숨기기'(대시보드 옵션 줄과 같은 설정 — config ui.hideSmallMM · 기본 켜짐 · GET·POST /api/ui_prefs) ──
// 대시보드 화면 스크립트(PAGE)의 같은 이름 함수와 같은 규칙: 화면에 보이는 MM 이 0.04 이하(0.045 미만 · 0·음수 포함)인 과제·세부업무 줄과
// 이름표를 숨기고 표 아래 한 줄로 말한다. 인원·합계·로드율은 그대로. 저장본(정적 팀 리포트 — window.__TEAM_DATA__)·파일로 연 화면은 숨기지
// 않는다(칸은 저장본에서 nosnap 카드와 함께 숨는다).
const SMALL_LT=0.045;
const SMALL_LIVE=location.protocol.indexOf("http")===0&&!window.__TEAM_DATA__;
let HIDE_SMALL=SMALL_LIVE, SMALL_TOUCHED=false;
const smallV=v=>typeof v==="number"&&Number.isFinite(v)&&v<SMALL_LT;
function smallSplit(xs,mm,t){const vis=[],hid=[];let sum=0;
 (xs||[]).forEach(x=>{const v=mm(x);if(HIDE_SMALL&&smallV(v)){hid.push(x);sum+=v;}else vis.push(x);});
 if(t){t.n+=hid.length;t.sum+=sum;}
 return {vis,hid,n:hid.length,sum};}
const smallTally=()=>({n:0,sum:0});
const smallText=t=>`0.04 MM 이하 ${t.n}개(합 ${(Math.round(t.sum*100)/100||0).toFixed(2)} MM)는 숨겼습니다 — 옵션을 끄면 모두 보입니다`;
const smallLine=t=>(t&&t.n)?`<div class="note">${smallText(t)}</div>`:"";
const smallNote=(el,t)=>{if(!el)return;el.innerHTML=(t&&t.n)?smallText(t):"";el.style.display=(t&&t.n)?"":"none";};
async function uiPrefsLoad(){
 if(!SMALL_LIVE)return;
 let g=null;try{g=await fetch("/api/ui_prefs").then(r=>r.json());}catch(e){g=null;}
 if(SMALL_TOUCHED||!(g&&g.ok===true&&typeof g.hideSmallMM==="boolean"))return;
 const c=$("hidesm");if(c)c.checked=g.hideSmallMM;
 if(g.hideSmallMM!==HIDE_SMALL){HIDE_SMALL=g.hideSmallMM;if(D&&!D.error)render();}
}
async function uiPrefsToggle(){
 const c=$("hidesm");if(!c)return;
 SMALL_TOUCHED=true;HIDE_SMALL=!!c.checked;if(D&&!D.error)render();     // 이미 읽은 팀 자료로 바로 다시 그린다
 let r=null;
 try{r=await fetch("/api/ui_prefs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({hideSmallMM:HIDE_SMALL})}).then(x=>x.json());}catch(e){r=null;}
 if(!(r&&r.ok))alert("표시 설정을 저장하지 못했습니다 — 이 화면에는 반영했지만 다음에 열 때는 예전 설정으로 보입니다."+((r&&r.error)?" ("+r.error+")":""));
}
{const c=$("hidesm");if(c)c.onchange=uiPrefsToggle;}
async function loadDir(){
 try{const d=await fetch("/api/sharedir").then(r=>r.json());
  $("sharedir").value=d.dir||"";
  $("dirstate").innerHTML=(d.dir?(d.exists?'<span style="color:#0f7a3d">접근 가능</span>'
   :'<span style="color:#c0122f">경로에 접근할 수 없음</span>'):'<span style="color:#8b929b">미설정</span>')
   +(d.effective&&d.effective!==d.dir?` · 지금 읽는 곳: <b>${esc(d.effective)}</b> (${esc(d.used||"")})`:"")
   +(d.problem==="unreachable"?` · <span style="color:#c0122f">읽을 수 없음</span>`
     +(d.local_members>0?` (이 PC teamdata 에는 ${d.local_members}명)`:""):"")
   +(d.split?`<div style="margin-top:6px;color:#c0122f">[!] 받는 곳과 보는 곳이 다릅니다 — `
     +`업로드는 <b>${esc(d.store)}</b> 로 들어가는데 화면은 <b>${esc(d.effective)}</b> 를 읽고 있습니다.`
     +`<br>위 칸을 받는 곳으로 맞추거나, 팀 서버를 그 폴더에서 켜세요.</div>`:"");
 }catch(e){}
}
$("savedir").onclick=async()=>{
 const dir=$("sharedir").value.trim();
 $("savedir").disabled=true;
 const r=await fetch("/api/sharedir",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({dir})}).then(x=>x.json()).catch(()=>({ok:false}));
 $("savedir").disabled=false;
 if(!r.ok){alert("저장 실패: "+(r.error||""));return;}
 $("dirstate").innerHTML=r.dir?(r.exists?'<span style="color:#0f7a3d">저장됨 · 접근 가능</span>'
  :'<span style="color:#c0122f">저장됨 · 경로에 접근할 수 없음 — 오타/권한/네트워크 확인</span>')
  :'<span style="color:#8b929b">비움</span>';
 if(r.exists)load();
};
async function load(){
 // 정적 리포트(팀 취합 저장본)는 서버 없이 열린다 — 데이터가 파일 안에 박혀 있다
 if(window.__TEAM_DATA__){D=window.__TEAM_DATA__;document.body.classList.add("snap");
  const si=$("snapinfo");
  if(si)si.textContent=`저장된 팀 취합 리포트 — ${window.__SNAP_AT__||""} 기준 · 인원 ${(D.members||[]).length}명`
   +(D.share?` · ${D.share}`:"");
  render();return;}
 $("msg").textContent="읽는 중…";
 try{D=await fetch("/api/team").then(r=>r.json());}catch(e){$("msg").textContent="서버 오류";return;}
 if(D.error){
  const base=D.error==="no share"?"위 카드에서 팀 공유폴더 경로를 먼저 설정하세요"
   :(D.error==="share_unreachable"?"설정된 팀 공유폴더를 지금 읽을 수 없습니다"
   :(D.error==="no members"?"공유폴더에 인원이 없습니다 — 각 팀원이 [분석 실행]을 마치면 자동으로 나타납니다":D.error));
  $("msg").innerHTML=esc(base)+(D.dir?` · <b>${esc(D.dir)}</b>`:"")
   +(D.hint&&D.error!=="no share"?`<div class="note" style="margin-top:6px">${esc(D.hint)}</div>`:"")
   +(D.local_members>0?`<div style="margin-top:8px"><button class="ghost" id="uselocal">`
     +`이 PC 의 teamdata 로 전환 (${D.local_members}명)</button>`
     +`<span class="note" style="margin-left:8px">${esc(D.local||"")}</span></div>`:"");
  // 프로그램이 몰래 폴더를 갈아타면 명단이 통째로 바뀐다 — 그래서 누를 사람에게 맡긴다
  const ul=$("uselocal");
  if(ul)ul.onclick=async()=>{
   ul.disabled=true;
   const r=await fetch("/api/sharedir",{method:"POST",headers:{"Content-Type":"application/json"},
     body:JSON.stringify({dir:D.local})}).then(x=>x.json()).catch(()=>({ok:false}));
   if(!r.ok){ul.disabled=false;alert("전환 실패: "+(r.error||""));return;}
   await loadDir();load();
  };
  // 인원이 없어도 통합 보고서 파일은 있을 수 있다(예전 취합) — 서버가 준 full 로만 버튼을 켠다.
  // render() 를 안 거치는 분기라 여기서 정하지 않으면 HTML 기본값(disabled)에 머문다
  // (예전에는 기본이 enabled 라 결과 없는 상태에서도 눌려 안내 페이지만 떴다).
  const fu=D.full||{};
  $("fullat").textContent=fu.exists?`통합 보고서 ${fu.at||""} 생성${fu.v3?" · v3 있음":""}`:"통합 보고서 아직 없음 — [다시 만들기]";
  $("fullopen").disabled=!fu.exists;$("fullv3").disabled=!(fu.exists&&fu.v3);
  return;}
 $("msg").textContent=D.aliases?`유사 항목 정리 적용됨 (매핑 ${D.alias_n}건)`:"";
 $("undoalias").style.display=D.aliases?"":"none";
 render();
}
// D5 — 측정 신뢰도·산식 설정 배지. 수집 환경 차이(샘플러 유무·PC 기록·설정)를 사람 차이로 읽지 않게.
const GC9={reliable:["#0f7a3d","신뢰"],caution:["#c98a00","주의"],unreliable:["#c0122f","측정 불충분"]};
const covB=m=>{const c=(m.coverage&&typeof m.coverage==="object")?m.coverage:{};const g=GC9[c.grade];return g?` <span class="tag" style="border:1px solid ${g[0]};color:${g[0]};background:#fff" title="${esc((Array.isArray(c.reasons)?c.reasons:[]).join(" · ")||"측정 신뢰도 등급")}">${g[1]}</span>`:"";};
const cfgB=m=>m.cfg_diff?` <span class="tag" style="border:1px solid #b06ef7;color:#6c4fb8;background:#fff" title="표준 근무시간·점심·주간 창·PC 하한·공휴일 수 등 산식 설정이 팀 다수와 다릅니다 — 분모가 달라 로드율 비교가 어긋납니다">산식 설정 상이</span>`:"";
// LM30(2026-10-21) 무흔적 평일 = 흔적 없는 평일 중 휴가로 본 날(가용에서 뺀 날)을 뺀 수 — 휴가를 일하지 않은 날처럼 보이지 않게
const noEv=m=>Math.max(0,(Number(m.no_evidence_days)||0)-(Number(m.inferred_absence_days)||0));
// LM30(2026-10-18) — 출퇴근 추정 합계(member.attendance.total — 시각 없음): 연장·야간·휴일·52시간 넘은 주. 없는 사람(LM28·LM29)은 '—'
const attC=m=>{const a=(m.attendance&&typeof m.attendance==="object")?m.attendance:null;
 const t=(a&&a.total&&typeof a.total==="object")?a.total:null;
 if(!t)return '<td class="state">—</td><td class="state">—</td><td class="state">—</td><td class="state">—</td>';
 const h=v=>{const x=Number(v);return Number.isFinite(x)?x.toFixed(1)+"h":"–";};const w=Number(t.over52_weeks);
 return `<td>${h(t.ext_h)}</td><td>${h(t.night_h)}</td><td>${h(t.holiday_h)}</td><td>${Number.isFinite(w)?(w>0?`<b style="color:#c0122f">${w}주</b>`:"0주"):"–"}</td>`;};
function render(){
 const ms=D.members||[];
 // 측정 불충분(unreliable)은 팀 평균·순위·과제 매트릭스에서 빼고 표에는 남긴다(별도 표시)
 const okm=ms.filter(m=>!m.unreliable),exm=ms.filter(m=>m.unreliable);
 $("k_n").textContent=ms.length;
 $("k_nn").textContent=ms.map(m=>m.owner).join(" · ").slice(0,40);
 const tin=okm.reduce((a,m)=>a+(m.total_mm||0),0),tav=okm.reduce((a,m)=>a+(m.avail_mm||0),0);
 $("k_load").textContent=tav?Math.round(tin/tav*100)+"%":"–";
 $("k_mm").textContent=`투입 ${tin.toFixed(2)} / 가용 ${tav.toFixed(2)} MM`+(exm.length?` · 측정 불충분 ${exm.length}명 제외`:"");
 $("k_pj").textContent=Object.keys(D.matrix||{}).length;
 $("k_alias").textContent=D.aliases?`정리 매핑 ${D.alias_n}건 적용`:"정리 전";
 // 팀 통합 보고서 상태 — 정적 스냅샷(team_report.html)에서는 D.full 이 없어 '없음' 으로 남는다(nosnap 카드)
 const fu=D.full||{};
 $("fullat").textContent=fu.exists?`통합 보고서 ${fu.at||""} 생성${fu.v3?" · v3 있음":""}`:"통합 보고서 아직 없음 — [다시 만들기]";
 $("fullopen").disabled=!fu.exists;$("fullv3").disabled=!(fu.exists&&fu.v3);
 // 취합 현황 — 누가·언제·어디서 (빠진 사람을 눈으로 찾을 수 있게)
 $("whotbl").innerHTML=ms.length?
  '<table><tr><th>이름</th><th style="width:74px">파트</th><th style="width:150px">기간</th>'
  +'<th style="width:62px">투입 MM</th><th style="width:56px">로드율</th>'
  +'<th style="width:46px" title="출퇴근 추정(LM30) — 기간 합계. LM29 이전 판은 —">연장</th><th style="width:46px">야간</th><th style="width:46px">휴일</th><th style="width:58px">52시간 넘은 주</th>'
  +'<th style="width:210px">측정 방식</th>'
  +'<th style="width:118px">올린 시각</th><th style="width:104px">올린 PC</th>'
  +'<th style="width:118px">분석 시각</th><th style="width:104px">분석 PC</th></tr>'
  +ms.map(m=>{
    const up=m.uploaded_at||"",upf=m.uploaded_from||"",an=m.analyzed_at||"",hs=m.host||"";
    const fa=m.file_at||"";
    const pct=m.load_pct==null?(m.avail_mm?Math.round(m.total_mm/m.avail_mm*100):null):Math.round(m.load_pct);
    return `<tr${m.unreliable?' style="color:#8b929b"':""}><td><b>${esc(m.owner)}</b>${m.via?` <span class="tag">${esc(m.via)}</span>`:""}${covB(m)}${cfgB(m)}</td>
     <td>${esc(m.function||"")}</td><td>${esc((m.period||[]).join(" ~ "))}</td>
     <td>${(m.total_mm||0).toFixed(2)}</td><td>${pct==null?"–":pct+"%"}${m.unreliable?' <span class="state">비교 제외</span>':""}</td>
     ${attC(m)}
     <td style="font-size:11px">${esc(m.measure_text||"–")}</td>
     <td>${up?esc(up):`<span class="state">${esc(fa)||"–"}</span>`}</td>
     <td>${esc(upf)||"–"}</td><td>${esc(an)||"–"}</td><td>${esc(hs)||"–"}</td></tr>`;
   }).join("")+"</table>"
  +(exm.length?`<div class="note">측정 불충분(수집기 결측)으로 <b>팀 평균·순위·과제 매트릭스에서 제외</b>한 인원: ${esc(exm.map(m=>m.owner).join(", "))} — 그 PC 에서 PC 가동·Outlook 수집을 살린 뒤 다시 올리면 비교에 들어갑니다.</div>`:"")
  :'<div class="note">아직 취합된 사람이 없습니다.</div>';
 // 인별 로드율 막대 — 비교 가능 인원 먼저, 측정 불충분은 아래 회색으로
 $("loadbars").innerHTML=okm.concat(exm).map(m=>{
  const pct=m.load_pct==null?(m.avail_mm?Math.round(m.total_mm/m.avail_mm*100):0):Math.round(m.load_pct);
  const w=Math.min(100,pct/1.5), over=pct>100;
  return `<div style="display:flex;align-items:center;gap:10px;margin:5px 0${m.unreliable?";opacity:.55":""}">
   <span style="width:80px;font-size:12px;text-align:right">${esc(m.owner)}</span>
   <svg width="460" height="16" style="max-width:60%"><rect width="307" height="16" rx="3" fill="#eef0f3"/>
    <rect width="${w*4.6}" height="16" rx="3" fill="${m.unreliable?"#c9cfd8":(over?"#e08a00":(pct>=70?"#2a78d6":"#98a0a8"))}"/>
    <line x1="307" x2="307" y1="0" y2="16" stroke="#8b929b" stroke-dasharray="2"/></svg>
   <b style="font-size:12px;width:52px">${pct}%</b>
   <span style="font-size:10.5px;color:#8b929b">투입 ${m.total_mm.toFixed(2)} / 가용 ${m.avail_mm.toFixed(2)}${noEv(m)?` · 무흔적 ${noEv(m)}일`:""}${m.measure_text?` · ${esc(m.measure_text)}`:""}${covB(m)}${cfgB(m)}</span></div>`;
 }).join("")||'<div class="note">데이터 없음</div>';
 // 과제 × 인원 스택바 — 서버(aggregate.collect_team_data)가 측정 불충분 인원을 매트릭스에서 이미 뺐다
 const owners=okm.map(m=>m.owner);const oc=o=>PAL[owners.indexOf(o)%PAL.length];
 const pjs=Object.entries(D.matrix||{});
 const pmax=Math.max(...pjs.map(([_,v])=>Object.values(v).reduce((a,b)=>a+b,0)),0.001);
 // LM30(2026-10-25) 팀 합산이 0.04 MM 이하인 과제 줄은 숨긴다(막대 길이의 기준 pmax 는 모든 과제로 — 보이는 줄의 길이가 그대로) · 아래 한 줄
 const tJ=smallTally();
 $("pjstack").innerHTML=(smallSplit(pjs,([_,v])=>Object.values(v).reduce((a,b)=>a+b,0),tJ).vis.map(([pj,v])=>{
  const tot=Object.values(v).reduce((a,b)=>a+b,0);
  const segs=owners.map(o=>v[o]?`<i style="display:inline-block;height:14px;width:${v[o]/pmax*300}px;background:${oc(o)}" title="${esc(o)} ${v[o].toFixed(2)}MM"></i>`:"").join("");
  return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
   <span style="width:150px;font-size:11.5px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><b>${esc(pj)}</b></span>
   <span>${segs}</span><span style="font-size:11px;color:#5a626b">${tot.toFixed(2)} MM</span></div>`;
 }).join("")+smallLine(tJ))||'<div class="note">데이터 없음</div>';
 $("pjleg").innerHTML=owners.map(o=>`<span style="font-size:11px"><span class="dot" style="background:${oc(o)}"></span>${esc(o)}</span>`).join("");
 // 업무유형 스택 (비교 가능 인원만 — 측정 불충분은 유형 분포도 뺀다)
 $("wtstack").innerHTML=okm.map(m=>{
  const v=(D.wt||{})[m.owner]||{};const tot=Object.values(v).reduce((a,b)=>a+b,0)||1;
  const segs=Object.entries(v).map(([k,x])=>`<i style="display:inline-block;height:14px;width:${x/tot*260}px;background:${WTC[k]||"#98a0a8"}" title="${esc(k)} ${x.toFixed(2)}MM"></i>`).join("");
  return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
   <span style="width:80px;font-size:11.5px;text-align:right">${esc(m.owner)}</span><span>${segs}</span></div>`;
 }).join("")+`<div class="row" style="margin-top:6px">${Object.entries(WTC).map(([k,c])=>`<span style="font-size:11px"><span class="dot" style="background:${c}"></span>${k}</span>`).join("")}</div>`;
 // 팀 Agentic AI 니즈 후보 — 서버(aggregate.merge_needs)가 인원별 후보를 이름으로 합쳤다(팀 과제 매칭 없음)
 const nd=Array.isArray(D.needs)?D.needs:[];
 $("needst").textContent=`니즈 후보 결과 ${Number(D.agentic_n)||0}/${ms.length}명`
  +((D.needs_other||[]).length?` · 다른 기간 결과: ${(D.needs_other||[]).join(", ")}`:"");
 $("needlist").innerHTML=nd.slice(0,30).map(g=>`<div style="border-left:3px solid #6c4fb8;padding:3px 0 3px 10px;margin:8px 0">
  <b>${esc(g.name)}</b> <span style="font-size:10.5px;color:#8b929b">제안 ${Number(g.n)||0}명(${(g.who||[]).map(esc).join(", ")}) · 근거 업무 ${Number(g.ev)||0}행</span>
  ${g.logic?`<div style="font-size:11px;color:#5a626b">로직: ${esc(g.logic)}</div>`:""}${g.reason?`<div style="font-size:11px;color:#5a626b">사유: ${esc(g.reason)}</div>`:""}</div>`).join("")
  ||'<div class="note">발굴된 니즈 후보가 없습니다 — 팀원이 [분석 실행](AI 판정)을 마치고 결과를 올리면 여기에 모입니다.</div>';
 // 공통업무 — LM30(2026-10-25) 0.04 MM 이하 줄은 숨기고 표 아래 한 줄
 const tC=smallTally(), cm=D.common||[];
 $("commtbl").innerHTML="<tr><th>세부업무</th><th>관련 과제</th><th>수행 인원</th><th style='width:56px'>MM</th></tr>"+
  (smallSplit(cm,c=>c.mm||0,tC).vis.map(c=>`<tr><td><b>${esc(c.detail)}</b></td><td>${(c.models||[]).map(esc).join(", ")}</td>
   <td>${(c.who||[]).map(esc).join(", ")}</td><td>${(c.mm||0).toFixed(2)}</td></tr>`).join("")||(cm.length?"":"<tr><td colspan=4 class='note'>없음</td></tr>"));
 smallNote($("commsm"),tC);
 // 세부업무 상위 — LM30(2026-10-25) 팀 합산 0.04 MM 이하 줄은 담당 이름표와 함께 숨기고, 보이는 줄의 0.04 MM 이하 이름표는 그 이름표만 뺀다
 const tT=smallTally();
 $("dtltbl").innerHTML="<tr><th>과제 / 세부업무</th><th>담당</th><th style='width:70px'>팀 합산 MM</th></tr>"+
  smallSplit(Object.entries(D.details||{}).slice(0,25),([_,v])=>Object.values(v).reduce((a,b)=>a+b,0),tT).vis.map(([k,v])=>{
   const tot=Object.values(v).reduce((a,b)=>a+b,0);
   return`<tr><td><b>${esc(k)}</b></td><td>${smallSplit(Object.entries(v),([_,x])=>x,tT).vis.map(([o,x])=>`<span class="tag">${esc(o)} ${x.toFixed(2)}</span>`).join("")}</td><td>${tot.toFixed(2)}</td></tr>`;
  }).join("");
 smallNote($("dtlsm"),tT);
}
// ── 팀 서버 켜기/끄기 (팀 공용 PC 용) ──
let TS={running:false,port:0,urls:[]};
function tsRender(d){
 TS=d||TS;
 $("tsstate").innerHTML=TS.running
  ?`<span style="color:#0f7a3d">● 켜져 있음</span> · 포트 ${TS.port}`
  :`<span style="color:#98a0a8">● 꺼져 있음</span> · 포트 ${TS.port}`;
 $("tsstart").disabled=!!TS.running;$("tsstop").disabled=!TS.running;
 $("tsopen").disabled=!TS.running;
 const occ=TS.occupant||[], busy=!!TS.occupied;
 const KND={mine:"이 폴더의 팀 서버",other_lm:"다른 폴더의 팀 서버",
  legacy_lm:"예전 버전(LM18·LM19)의 팀 서버",unknown:"LoadMonitor 가 아닌 프로그램",
  unreadable:"확인하지 못한 프로그램",hidden:"잠깐 쓰이는 중(붙잡은 서버 없음)"};
 // 포트를 쥔 것이 '무엇인지' 이름으로 말한다 — '다른 프로그램' 으로는 손쓸 수 없다
 $("tstake").style.display=(busy&&TS.take&&TS.take!=="no")?"":"none";
 // 설정된 서버 주소(설치 폴더의 팀 서버 주소 파일) — 보여 주기만 한다. 바꾸는 곳은 LoadMonitor30-팀서버주소.bat.
 const AK={server:"#0f7a3d",member:"#b26a00",loopback:"#c0122f",unknown:"#98a0a8"};
 const bat=esc(TS.edit_bat||"LoadMonitor30-팀서버주소.bat");
 $("tsaddr").innerHTML=(TS.upload_url?`팀원 업로드 주소(설정): <b>${esc(TS.upload_url)}</b> — `
   +`<span style="color:${AK[TS.addr_kind]||"#98a0a8"}">${esc(TS.addr_note||"")}</span>`:"")
  +(busy&&TS.suggest_port?`<br><span style="color:#c0122f">포트 ${TS.port} 을 다른 프로그램이 쓰고 있습니다 — `
   +`${bat} 에서 포트를 ${TS.suggest_port} 처럼 빈 번호로 바꾼 뒤 [팀 서버 시작] 하세요 `
   +`(팀원도 같은 포트로 맞춰야 합니다 — 바뀐 설치 폴더나 팀 서버 주소 파일을 나눠 주면 됩니다).</span>`:"")
  +((TS.addr_warnings||[]).length?`<br><span style="color:#c0122f">${TS.addr_warnings.map(esc).join(" / ")}</span>`:"");
 if(busy)$("tsstate").innerHTML=`<span style="color:#c0122f">● 포트 ${TS.port} 사용 중</span> · `
  +esc(KND[TS.kind]||"확인 중");
 $("tsurl").innerHTML=TS.running
  ?("이 PC 에서 열린 주소: "+(TS.urls||[]).map(u=>`<b>${esc(u)}</b>`).join(" 또는 ")
    +'<br><span class="state">이 PC 안에서 확인된 주소입니다 — 팀원이 실제로 닿는지는 '
    +'각자 [연결 확인] 으로 봐야 합니다(방화벽 허용 필요).</span>'
    +(TS.log?`<br><span class="state">${esc(TS.log)}</span>`:""))
  :(busy?(occ.length
     ?"포트를 쥔 프로그램: "+occ.map(x=>`<b>${esc(x.name)}</b> (pid ${x.pid})`
        +(x.owner?` · 실행 계정 ${esc(x.owner)}`:"")+(x.protected?' <span style="color:#c0122f">끝낼 수 없음</span>':"")).join(", ")
      // 명령줄이 실행 파일 경로로 시작하면 같은 줄을 두 번 보여 줄 필요가 없다
      +((occ[0].exe&&!(occ[0].cmd||"").startsWith(occ[0].exe))?`<br><span class="state">${esc(occ[0].exe)}</span>`:"")
      +(occ[0].cmd?`<br><span class="state">${esc(occ[0].cmd)}</span>`:"")
      +(TS.foreign_root?`<br><span class="state">설치 폴더: ${esc(TS.foreign_root)}</span>`:"")
     :"붙잡고 있는 서버를 찾지 못했습니다 — LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸는 편이 확실합니다")
    :(TS.log?`<span class="state">${esc(TS.log)}</span>`:""));
}
async function tsLoad(){
 const d=await fetch("/api/teamserver").then(r=>r.json()).catch(()=>null);
 if(d)tsRender(d);
}
async function tsAct(action,force,confirmPid){
 ["tsstart","tsstop","tstake"].forEach(id=>$(id).disabled=true);
 $("tsstate").textContent=action==="start"?(force?"포트 가져오는 중…":"시작하는 중… (최대 20초)"):"중지하는 중…";
 const d=await fetch("/api/teamserver",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({action,force:!!force,confirm_pid:confirmPid||0})})
   .then(r=>r.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tsRender(d);
 const NL=String.fromCharCode(10);
 if(d.error)alert("팀 서버 "+(action==="start"?(force?"포트 가져오기":"시작"):"중지")+" 실패"+NL+NL+d.error);
 else if(action==="start"&&!d.running)alert("팀 서버가 뜨지 않았습니다 — [결과 폴더]의 teamserver.log 를 확인하세요.");
 else if(force&&d.running)alert("포트를 가져와 팀 서버를 켰습니다.");
}
$("tsstart").onclick=()=>tsAct("start");
$("tsstop").onclick=()=>{if(confirm("팀 서버를 중지할까요?\\n팀원의 업로드가 그동안 실패합니다(묶음은 각자 대기로 남습니다)."))tsAct("stop");};
$("tsopen").onclick=()=>{if(TS.urls&&TS.urls.length)window.open(TS.urls[0],"_blank");};
$("tstake").onclick=()=>{
 const occ=TS.occupant||[], NL=String.fromCharCode(10);
 if(!occ.length){alert("포트를 쥔 프로그램을 확인하지 못해 가져올 수 없습니다."+NL
  +"LoadMonitor30-팀서버주소.bat 에서 포트를 다른 번호로 바꾸세요.");return;}
 // 무엇을 죽이는지 그대로 보여 준다 — 이름만 보고 누르면 사고가 난다
 const list=occ.map(x=>" · "+x.name+" (pid "+x.pid+")"+(x.owner?"  ["+x.owner+"]":"")
  +(x.exe?NL+"   "+x.exe:"")+(x.cmd?NL+"   "+x.cmd.slice(0,140):"")).join(NL);
 let head="포트 "+TS.port+" 을 가져옵니다."+NL+NL+"다음을 강제 종료합니다:"+NL+list+NL+NL;
 if(TS.kind==="other_lm"||TS.kind==="legacy_lm")
  head+="그 서버로 올리는 중인 팀원이 있으면 전송이 끊깁니다(묶음은 각자 대기로 남습니다)."+NL
   +"그 폴더에 이미 받아 둔 자료는 지우지 않습니다."+NL+NL;
 else head+="저장하지 않은 작업이 있으면 잃을 수 있습니다."+NL+NL;
 if(!confirm(head+"계속할까요?"))return;
 if(TS.take==="confirm_pid"){
  // LoadMonitor 가 아닌 프로그램은 클릭 한 번으로 죽일 수 없다
  const v=prompt("이 프로그램은 LoadMonitor 가 아닙니다."+NL
   +"정말 종료하려면 아래 PID 를 그대로 입력하세요: "+occ[0].pid,"");
  if(String(v||"").trim()!==String(occ[0].pid))
   {alert("PID 가 일치하지 않아 취소했습니다.");return;}
  tsAct("start",true,occ[0].pid);return;
 }
 tsAct("start",true,0);
};
$("reload").onclick=()=>{loadDir();load();tsLoad();};
loadDir();
$("refine").onclick=async()=>{
 if(!confirm("팀 전체의 과제명·세부업무 목록을 Copilot에게 보내 유사 표기를 통합할까요?"+String.fromCharCode(10)
  +"(규칙 정리 → Copilot 최대 3회 → 계열·과제분류·세부·후보 통합 → 통합 보고서 갱신 — 수 분, 사람 이름·MM 은 보내지 않습니다)"))return;
 $("refine").disabled=true;$("msg").textContent="Copilot 정리 중…";
 const r=await fetch("/api/team_refine",{method:"POST"}).then(x=>x.json()).catch(()=>({ok:false}));
 $("refine").disabled=false;
 if(!r.ok){
  // 사유를 통째로 버리면 사용자가 손쓸 수 없다(실측 제보: '정리 실패'만 보임)
  const why=r.hint||r.error||"알 수 없는 오류";
  $("msg").innerHTML=`<span style="color:#c0122f">정리 실패</span> — ${esc(why)}`;
  alert("유사 항목 정리를 하지 못했습니다.\\n\\n"+why);return;}
 $("msg").textContent=(r.groups?`${r.groups}개 그룹 통합됨`:(r.hint||"통합할 유사 항목이 없었습니다"))
  +(r.members?` · 인원 ${r.members}명`:"")+(r.used&&r.used!=="설정"?` · ${r.used} 사용`:"");
 if(r.detail&&r.detail.length)alert("통합 내역:"+String.fromCharCode(10)+r.detail.join(String.fromCharCode(10)));
 // 정리 결과가 정적 파일(team_report.html·통합 보고서)에도 반영되게 — team_refine 이 이미 만들었으면
 // 화면 상태(생성 시각)만 새로 읽고, 못 만들었으면 여기서 만든다
 if(r.full_report)load();else await makeFull(false);
};
$("undoalias").onclick=async()=>{
 const NL=String.fromCharCode(10);
 if(!confirm("유사 항목 정리를 되돌릴까요? (team_aliases.json 삭제 — 원본은 원래 그대로입니다)"))return;
 const all=confirm("Copilot 이 채운 다른 캐시(team_series·team_pjclass·team_detail_groups.json)도 함께 지울까요?"
  +NL+"[취소] = team_aliases.json 만 삭제");
 await fetch("/api/team_refine",{method:"DELETE",headers:{"Content-Type":"application/json"},
   body:JSON.stringify(all?{files:["team_series.json","team_pjclass.json","team_detail_groups.json"]}:{})});
 load();
};
async function makeFull(snap){
 $("msg").textContent=snap?"팀 취합·통합 보고서 스냅샷 만드는 중…":"팀 취합·통합 보고서 만드는 중…";
 ["fullmake","fullsnap","savehtml"].forEach(id=>$(id).disabled=true);
 const r=await fetch("/api/aggregate",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({snapshot:!!snap})}).then(x=>x.json()).catch(()=>({ok:false}));
 ["fullmake","fullsnap","savehtml"].forEach(id=>$(id).disabled=false);
 const base=p=>String(p).split("/").pop().split(String.fromCharCode(92)).pop();
 $("msg").textContent=r.ok?(r.full_report?(snap&&r.snapshots&&r.snapshots.length
    ?`스냅샷 저장됨 — ${r.snapshots.map(base).join(" · ")}`:"만들었습니다 — [팀 통합 보고서 열기]")
   :"취합은 됐지만 통합 보고서는 실패 — 진행 로그 확인"):"실패: "+(r.hint||r.error||"");
 load();
}
$("fullopen").onclick=()=>window.open("/team/full","_blank");
$("fullv3").onclick=()=>window.open("/team/full_v3","_blank");
$("fullmake").onclick=()=>makeFull(false);
$("fullsnap").onclick=()=>makeFull(true);
$("savehtml").onclick=()=>makeFull(false);
// 창을 닫으면 서버도 끝난다(LM28 — 대시보드와 같은 신호: 10초마다 /api/alive, 닫힐 때 /api/bye). 팀 서버는 따로 돌아 계속 산다.
function lmLive(){return location.protocol.indexOf("http")===0&&!document.getElementById("lm-frozen-data");}
let LM_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);
function lmAlive(vis){if(!lmLive())return;
 fetch("/api/alive",{method:"POST",headers:{"Content-Type":"application/json"},keepalive:true,
  body:JSON.stringify({id:LM_TAB,vis:vis||document.visibilityState})}).catch(()=>{});}
function lmBeacon(path,vis){try{navigator.sendBeacon(path,JSON.stringify({id:LM_TAB,vis:vis||""}));}catch(e){}}
// LM28(2026-10-19): 알림·확인·입력 창이 열려 있으면 브라우저가 타이머를 멈춘다 — 열기 직전 'dialog' 를 알리고 닫히면 곧바로 다시 알린다(대시보드와 같다)
(function(){if(window.__lmDlg)return;window.__lmDlg=1;
 ["alert","confirm","prompt"].forEach(function(k){const f0=window[k];if(typeof f0!=="function")return;
  window[k]=function(){try{if(lmLive())lmBeacon("/api/alive","dialog");}catch(e){}
   try{return f0.apply(window,arguments);}finally{try{if(lmLive())lmAlive();}catch(e){}}};});})();
if(lmLive()){
 lmAlive();setInterval(()=>lmAlive(),10000);
 document.addEventListener("visibilitychange",()=>lmAlive());
 document.addEventListener("freeze",()=>lmBeacon("/api/alive","frozen"));
 document.addEventListener("resume",()=>lmAlive());
 window.addEventListener("pageshow",e=>{if(e.persisted){LM_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);lmAlive();}});
 window.addEventListener("pagehide",()=>lmBeacon("/api/bye"));
}
uiPrefsLoad();load();tsLoad();
</script></body></html>"""

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>LoadMonitor30</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic',system-ui,sans-serif;background:#f2f4f7;color:#12151a;padding:22px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:20px;letter-spacing:-0.3px}h1 small{font-size:11px;color:#8b929b;font-weight:400;margin-left:8px}
.sub{font-size:11.5px;color:#5a626b;margin:3px 0 14px}
.card{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}
.card h2{font-size:13px;margin-bottom:10px;color:#2c333b}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
@media(max-width:860px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px}
.kpi .lb{font-size:10.5px;color:#8b929b}
.kpi .vl{font-size:21px;font-weight:800;margin:2px 0;letter-spacing:-0.5px}
.kpi .nt{font-size:10.5px;color:#5a626b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:12px}
input[type=date]{padding:5px 8px;border:1px solid #c9cfd8;border-radius:5px;font:inherit;font-size:12px}
.chip{border:1px solid #c9cfd8;background:#fff;border-radius:14px;padding:4px 12px;font-size:11.5px;cursor:pointer;color:#4a5159}
.chip:hover,.chip.on{border-color:#2a78d6;color:#2a78d6;background:#f0f6fd}
button.run{background:#2a78d6;color:#fff;border:0;border-radius:5px;padding:9px 24px;font-size:13.5px;font-weight:700;cursor:pointer;font-family:inherit}
button.run:disabled{background:#c9cfd8;cursor:default}
button.run.local{background:#0e8c7a}button.run.local:disabled{background:#c9cfd8}
button.ghost{background:#fff;color:#4a5159;border:1px solid #c9cfd8;border-radius:5px;padding:6px 12px;font-size:12px;cursor:pointer;font-family:inherit}
#reset:disabled{opacity:.45;cursor:default}
#log{background:#12151a;color:#d6dbe1;border-radius:5px;padding:10px 12px;height:170px;overflow-y:auto;
 font-family:Consolas,monospace;font-size:11px;line-height:1.55;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:12px}
th{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;border-bottom:2px solid #e4e7eb;font-size:11px}
td{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}
.note{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:0}
.state{font-size:12px;color:#5a626b;font-weight:400}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 12px;font-size:11.5px}
.steps a,.steps span{display:inline-block;padding:5px 10px;border-radius:14px;border:1px solid #d7dbe0;background:#fff;color:#4a5159;text-decoration:none}
.steps .on{background:#eef4fd;border-color:#b9d3f2;color:#1c4e8a;font-weight:700}
.src{display:inline-flex;align-items:center;gap:6px;border:1px solid #e4e7eb;border-radius:14px;
 padding:4px 11px;font-size:11px;color:#4a5159;background:#fff}
.src b{font-weight:700}
.leg{font-size:11px;color:#4a5159;line-height:1.9}
.leg .v{float:right;font-weight:700}
details{margin-bottom:12px}
details summary{cursor:pointer;font-size:13px;font-weight:700;color:#2c333b;padding:12px 16px;
 background:#fff;border:1px solid #e4e7eb;border-radius:8px;list-style:none}
details summary::before{content:"▸ ";color:#8b929b}
details[open] summary{border-radius:8px 8px 0 0}details[open] summary::before{content:"▾ "}
details .body{background:#fff;border:1px solid #e4e7eb;border-top:0;border-radius:0 0 8px 8px;padding:14px 16px}
.bigbar{height:26px;border-radius:5px;overflow:hidden;display:flex;margin:6px 0 10px}
.bigbar i{display:block;height:100%}
.tl{font-family:Consolas,monospace;font-size:11px;line-height:1.75;color:#3d444c}
.tl .d{font-weight:700;color:#12151a;font-family:inherit;margin-top:6px}
.tl .s{color:#8b929b}.tl .p{font-weight:700}
.tag{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}
</style></head><body><div class="wrap">
<h1>LoadMonitor30<small id="ver">로컬 전용 · 외부 전송 없음</small></h1>
<div id="stub_banner" style="display:none;background:#fff1c2;border:2px solid #e08a00;color:#6b3a00;border-radius:6px;padding:10px 14px;margin:8px 0 12px;font-size:13px;line-height:1.6"></div>
<div class="steps">
 <span class="on">① 내 PC 분석 (지금 화면)</span>
 <span class="on">② 결과 확인</span>
 <span class="on">③ 팀 서버 보고(자동) / 공유폴더 저장</span>
 <a href="/team" target="_blank">④ 팀 취합 화면 →</a>
 <a href="/guide" target="_blank">사용 안내</a>
</div>
<div class="sub">PC 흔적에서 업무 로드를 추출합니다. <b>투입 MM</b>(실제 일한 양)과 <b>가용 MM</b>(일할 수 있었던 양 — 연차·반차는 법정 휴가라 일하지 않은 날로 세지 않고 가용에서 뺍니다)을
 나란히 내고 <b>로드율 = 투입 ÷ 가용</b>으로 비교합니다. 1 MM = 8h × 그 달 평일수(주40시간). 야근은 상한 없이 그대로 반영됩니다.</div>

<div class="card"><div class="row">
 <span class="chip on" data-d="ytd">올해</span>
 <span class="chip" data-d="q1">1분기</span><span class="chip" data-d="q2">2분기</span><span class="chip" data-d="q3">3분기</span><span class="chip" data-d="q4">4분기</span>
 <span class="chip" data-d="h1">상반기</span><span class="chip" data-d="h2">하반기</span>
 <span class="chip" data-d="30">1개월</span><span class="chip" data-d="90">3개월</span>
 <span class="chip" data-d="180">6개월</span><span class="chip" data-d="365">1년</span>
 <label>시작 <input type="date" id="from"></label><label>끝 <input type="date" id="to"></label>
 <label><input type="checkbox" id="ai" checked> AI 정제</label>
 <label><input type="checkbox" id="skip"> 재분석만</label>
 <label id="hronl" style="display:none" title="켜면 [분석 실행]이 GERP(인사 시스템) 근무 기록을 읽어 +@(근태 기록 밖 근무)를 근태와 견줍니다 — 시험 기능 · 전용 Edge 에 본인이 로그인해 둔 경우만 읽고, 로그아웃돼 있으면 건너뜁니다 · 기록은 이 PC에만 둡니다"><input type="checkbox" id="hron"> HR 근무 기록(GERP)</label>
 <label id="hidesml" title="켜면(기본) 과제·업무 목록(표·범례·막대)에서 MM이 0.04 이하인 항목을 숨기고, 표 아래에 숨긴 개수와 합을 적습니다 — 화면 표시만 바꾸고 합계·로드율·보고서·팀으로 보내는 자료는 그대로입니다 · 이 PC의 설정에 저장합니다"><input type="checkbox" id="hidesm" checked> 0.04 MM 이하 숨기기</label>
 <button class="run" id="go" title="로컬PC 자료수집 + AI 분석 + 팀 서버 보고까지 한 번에 합니다">분석 실행</button>
 <button class="run local" id="collect2" title="이 PC 의 자료만 모읍니다(분석·보고 없음). 폴더째 분석할 PC 로 옮겨 [분석 실행]을 누르면 합쳐집니다">로컬PC 자료수집</button>
 <button class="run" id="stop" style="background:#c0122f;display:none">중지</button>
 <span class="state" id="state">대기 중</span>
 <span style="flex:1"></span>
 <button class="ghost" id="report">보고서 만들기(리포트·분석리포트·얼린 보고서)</button>
 <button class="ghost" id="teamagg">팀 취합</button>
 <button class="ghost" id="teamup">팀 서버 업로드</button>
 <button class="ghost" id="diag">AI 연결 진단</button>
 <button class="ghost" id="chatsweep" title="LM이 열고 기록해 둔 Copilot 채팅만 다시 지웁니다 — 사람이 쓰던 채팅·기록에 없는 채팅은 건드리지 않습니다(분석·다른 작업 중에는 꺼집니다)">LM이 연 Copilot 채팅 지우기</button>
 <button class="ghost" id="cdiag">수집 진단</button>
 <button class="ghost" id="prepmove">PC 이동 준비</button>
 <button class="ghost" id="owa">Outlook 웹 읽기</button>
 <button class="ghost" id="teamsweb">팀즈 웹 읽기</button>
 <button class="ghost" id="narrate">리뷰 코멘트 재생성</button>
 <button class="ghost" id="reset" style="color:#c0122f;border-color:#f0cdd5">데이터 리셋</button>
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
<div id="tr_banner" style="display:none;background:#fdecee;border:1px solid #f0b8c2;color:#8a1020;border-radius:6px;padding:9px 14px;margin:0 0 12px;font-size:12.5px;line-height:1.6"></div>

<div class="row" id="tabs" style="margin-bottom:12px">
 <span class="chip on" data-t="dash">대시보드</span>
 <span class="chip" data-t="week">주간 리뷰</span>
 <span class="chip" data-t="month">월간 리뷰</span>
 <span class="chip" data-t="deep">상세 리뷰</span>
 <span class="chip" data-t="agentic">Agentic AI</span>
 <span class="chip" data-t="flow">담당자 워크플로우</span>
</div>

<div class="tab" id="tab-dash">
<div class="kpis">
 <div class="kpi"><div class="lb">로드율 <span style="font-weight:400">(투입 ÷ 가용)</span></div>
  <div class="vl" id="k_load">–</div><div class="nt" id="k_mm">–</div></div>
 <div class="kpi"><div class="lb">주력 업무</div><div class="vl" id="k_top" style="font-size:15px;line-height:1.3">–</div><div class="nt" id="k_topn"></div></div>
 <div class="kpi"><div class="lb">업무 항목</div><div class="vl" id="k_items">–</div><div class="nt" id="k_acts"></div></div>
 <div class="kpi"><div class="lb">데이터 소스</div><div class="vl" id="k_src">–</div><div class="nt" id="k_srcn"></div></div>
</div>

<div class="grid2">
 <div class="card"><h2>프로젝트별 로드 (MM)</h2>
  <div id="notice_bar" style="display:none;background:#eaf2fd;border:1px solid #b9d3f2;border-radius:6px;padding:8px 12px;margin:4px 0 8px;font-size:12px;color:#1c4e8a"></div>
  <div id="judged_warn" style="display:none;background:#fdf3e6;border:1px solid #f0d9b0;border-radius:6px;padding:8px 12px;margin:4px 0 8px;font-size:12px;color:#8a5a00">
   ⚠ <b>AI 판정 전(또는 실패)</b> — 아래는 규칙이 임시로 뽑은 토큰이라 과제로 정리되지 않은 상태입니다.
   [분석 실행]에서 <b>AI 판정 포함</b>으로 다시 돌리면 과제 단위로 정리됩니다.
   이미 돌렸는데 이 표시가 남아 있으면 진행 로그에서 "AI 판정" 단계의 실패 원인을 확인하세요.</div>
  <div style="display:flex;gap:16px;align-items:center">
   <div id="donut" style="width:170px;flex:none"></div>
   <div id="dleg" class="leg" style="flex:1;min-width:0"></div>
  </div></div>
 <div class="card"><h2>프로젝트 내 업무 로드 (MM) <span class="state">과제 → 담당 업무 — 그 과제 안에서 어떤 업무에 얼마나 들어갔나</span></h2>
  <div id="pjwork"></div>
  <div class="note">비중(%)은 <b>그 과제 안에서의</b> 배분입니다. 세부업무명은 AI 판정·정제 결과 — 상세 리뷰의 '과제 → 업무유형 · 세부업무' 표와 같은 축입니다.</div></div>
 <div class="card"><h2>세부업무 분포 <span class="state">Level 3 기준 — 개발/사무 유형 배분은 상세 리뷰의 '업무유형 → 과제' 표</span></h2>
  <div class="bigbar" id="actbar"></div>
  <div id="actleg" class="leg"></div></div>
</div>

<div class="card"><h2><span id="wtitle">활동 추이</span> <span class="state" id="wsub">막대 = 신호 건수 · 선 = PC 가동시간</span></h2>
 <div id="weekly"></div>
 <div class="row" id="wleg" style="margin-top:6px;font-size:11px;color:#4a5159"></div>
 <div class="note" id="wnote" style="display:none;color:#a86400"></div>
 <div id="wclump"></div></div>

<div class="card"><h2>업무별 상세 <span class="state" id="rsrc"></span></h2>
 <table id="res"></table>
 <div class="note" id="ressm" style="display:none"></div>
 <div class="note">상세설명은 Copilot이 원문 근거를 읽고 작성합니다. 원문은 주간/월간/상세 리뷰 탭에서 확인.</div></div>

<div class="card"><h2>수집 데이터 현황</h2><div class="row" id="src"></div>
 <div class="note">빨간 항목이 결과 품질을 떨어뜨립니다. 노란 항목은 수집은 됐지만 기간 대비 부족한 것, 회색은 선택 항목입니다.</div></div>

<div class="card"><h2>수집 현황 — 날짜별 원장 <span class="state" id="cvstate"></span></h2>
 <div id="cvbody"><div class="note">불러오는 중…</div></div>
 <div class="row" style="margin-top:8px">
  <button class="ghost" id="cvrefresh">새로고침</button>
  <button class="ghost" id="cvreset" title="다음 [분석 실행]이 기간 전체를 처음부터 다시 읽게 합니다(수집한 자료는 지우지 않음)">커서 초기화</button>
  <span class="state" id="cvmsg"></span></div>
 <div class="note">날 수는 한 원천(data\\coverage_ledger.json)에서 셉니다. <b>읽음</b>=확인된 날(0건 확인 포함) · <b>일부</b>=읽었지만 끝까지 확인하지 못한 날 ·
 <b>미관측</b>=못 읽은 날(0시간이 아니라 '근거 없음' — 휴가로 보지 않습니다) · <b>해당 없음</b>=이 PC 에서 팀즈를 쓰지 않음.
 '불가' 사유는 실측 전이라 <b>의심</b>으로 적습니다. 이 PC 의 원장인지 모르면 PC 이름 대신 출처만 보입니다.</div></div>

<div class="card"><h2>수동 기록 <span class="state">PC 밖 업무(출장·현장·장비 점검) — data\\manual\\worklog.csv (collect\\Add-WorkLog.ps1 과 같은 열)</span></h2>
 <div class="row">
  <label>날짜 <input type="date" id="wl_date"></label>
  <label>시작 <input type="time" id="wl_start"></label><label>끝 <input type="time" id="wl_end"></label>
  <label>또는 시간 <input type="number" id="wl_hours" min="0" max="24" step="0.5" style="width:64px"></label>
  <label>분류 <input type="text" id="wl_cat" value="현장" style="width:80px"></label>
  <label>과제 <input type="text" id="wl_entity" style="width:120px"></label>
  <label>메모 <input type="text" id="wl_note" style="width:160px"></label>
  <button class="ghost" id="wl_save">기록</button><span class="state" id="wl_msg"></span></div>
 <div class="note">시작·끝을 적으면 그 구간 길이가 시간이 됩니다(자정을 넘겨도 됩니다). 기록은 그날의 하한이 되어 다음 [분석 실행]부터 반영됩니다.</div></div>

<div class="card"><h2>팀 취합 업로드 <span class="state" id="tuhead">[분석 실행]이 끝나면 팀 서버로 자동 보고합니다 — 닿지 않으면 대기로 남고, 사내망에서 버튼으로 보냅니다</span></h2>
 <div class="row" style="align-items:center;gap:6px;margin-bottom:8px">
  <span class="state" style="flex:none">올릴 주소</span>
  <b id="tuurl" style="flex:1;min-width:200px;font-size:12.5px">확인 중…</b>
  <button class="ghost" id="tuping">연결 확인</button>
  <span class="state" id="tustat"></span></div>
 <div class="note" id="tuaddr"></div>
 <div id="tuavail"></div>
 <div id="tupend"></div>
 <div class="row" style="margin-top:8px;align-items:center">
  <button class="ghost" id="tusend" style="border-color:#2a78d6;color:#2a78d6">팀 서버 업로드</button>
  <button class="ghost" id="tufolder">공유폴더로 저장</button>
  <button class="ghost" id="tubuild" style="display:none">지금 묶음 만들기</button>
  <button class="ghost" id="tuopen">묶음 폴더 열기</button>
  <span class="state" id="tumsg"></span></div>
 <div class="note" id="tusent"></div>
 <div class="note" id="tureport"></div>
 <div class="note">팀 서버를 켜고 끄는 것과 취합 결과 보기는 <b><a href="/team" target="_blank">팀 취합 화면</a></b>에 있습니다
 (LoadMonitor30-팀취합.bat 과 같은 화면).</div>
 <div class="note">[분석 실행]이 끝나면 묶음을 먼저 <b>대기</b>로 만든 뒤 팀 서버로 <b>자동 보고</b>합니다(설정 teamUpload.autoReport).
 닿지 않는 망이면 묶음은 그대로 대기로 남고 화면에 실패 알림이 뜹니다 — 사내망에서 [팀 서버 업로드]를 한 번 누르면
 <b>밀린 기간까지 함께</b> 올라가고, 보낸 묶음은 <code>report\\upload_sent\\</code> 로 옮겨집니다.
 닿지 않는 망에서 눌러도 아무것도 잃지 않고 그대로 대기합니다. 서버 대신 공유폴더로 낼 수도 있습니다.</div>
 <div class="note">보내는 것: 그 기간의 판정 결과(과제·업무·MM)와 근거 신호 목록입니다 —
 메일 제목·회의 제목·동료 이름이 포함될 수 있습니다(개인 폴더 신호는 이미 제외됨). 사내망 전용으로만 쓰세요.</div></div>


<div class="card"><h2>MM 산정 근거 <span class="state">투입 ÷ 가용 = 로드율 · 1 MM = 8h × 그 달 평일수</span></h2>
 <div id="mmbasis"></div>
 <div id="pcimp"></div></div>

<div class="card"><h2>출퇴근·시간외 근무 <span class="state" id="atstate">PC를 켜고 끈 시각과 내 흔적으로 추정 · 날짜별 시각은 이 PC에만</span></h2>
 <div id="atbody"><div class="note">불러오는 중…</div></div>
 <div id="atleave"></div>
 <div id="atgerp"></div></div>

<div class="card"><h2>신호 출처 — 무엇이 계상되고 무엇이 빠졌나 <span class="state" id="metaper"></span></h2>
 <div class="row" id="mcount" style="margin-bottom:6px"></div>
 <div class="row" id="mexcl"></div>
 <div class="note">CC·단체발송·비업무(연차 등)·개인정보는 <b>계상하지 않고</b> '제외'로만 집계됩니다.
 팀즈가 채택 목록에 없으면 이번 분석에 팀즈 채팅이 포함되지 않은 것입니다.</div></div>

<div class="card"><h2>과제 지정 <span class="state">비워두면 AI가 raw에서 자동 발견합니다</span></h2>
 <table id="pjtbl"></table>
 <div class="row" style="margin-top:8px">
  <button class="ghost" id="pjadd">+ 프로젝트 추가</button>
  <button class="ghost" id="pjsave">저장</button>
  <button class="ghost" id="pjretag" style="border-color:#2a78d6;color:#2a78d6">저장 + 지정 반영 재분류</button>
  <span class="state" id="pjmsg"></span></div>
 <div class="note">지정한 프로젝트는 AI 분류 체계에 <b>항상 포함</b>되고, 지정하지 않은 영역은 기존 자동 발견이 분류합니다.
 <b>재분류</b>는 이미 '공통'·자동발견으로 분류된 신호 중 이름·키워드가 원문에 등장하거나 관련 내용 단어가
 2개 이상 일치하는 것을 지정 프로젝트로 재귀속합니다(몇 초, Copilot 불필요). 다른 지정 프로젝트로 이미
 판정된 신호는 건드리지 않습니다.</div></div>

<details id="dlog"><summary>진행 로그 <span class="state" id="step"></span></summary>
 <div class="body"><div id="log">대기 중…</div></div></details>

<details><summary>수집 데이터 열람</summary><div class="body">
 <div class="row" style="margin-bottom:8px">
  <span class="chip" data-s="files">파일</span><span class="chip" data-s="recent">Recent</span>
  <span class="chip" data-s="mail">메일</span><span class="chip" data-s="cal">일정</span>
  <span class="chip" data-s="git">git</span><span class="chip" data-s="teams">팀즈</span>
  <span class="chip" data-s="act">창 샘플러</span><span class="chip" data-s="pc">PC 가동</span>
  <span class="state" id="dsrc"></span></div>
 <div style="max-height:320px;overflow:auto"><table id="dtbl"></table></div></div></details>
</div><!-- /tab-dash -->

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
 <span id="sb_load" style="color:#8b929b"></span>
 <span style="flex:1"></span>
 <span id="sb_ver" style="color:#5a626b"></span>
</div>

<div class="tab" id="tab-week" style="display:none"><div id="rv-week"></div></div>
<div class="tab" id="tab-month" style="display:none"><div id="rv-month"></div></div>
<div class="tab" id="tab-deep" style="display:none"><div id="rv-deep"></div></div>
<div class="tab" id="tab-agentic" style="display:none"><div id="rv-agentic"></div></div>
<div class="tab" id="tab-flow" style="display:none"><div id="rv-flow"></div></div>
<div style="height:44px"></div><!-- 하단 고정 상태바에 내용이 가리지 않도록 여백 -->

</div><script>
const $=id=>document.getElementById(id);
const WTCOL={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
const PAL=["#2a78d6","#0e8c7a","#a61b4a","#e08a00","#6c4fb8","#3d8f3d","#c05a78","#4a7f9e","#8a6d3b","#556270"];
const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
// 기간 빠른 선택 — 서버 quarter_range(ui\\app.py)·LoadMonitor30.bat 과 같은 규칙: 오늘이 속한 해, 끝이 미래면 오늘로,
// 아직 시작하지 않은 분기·반기는 고를 수 없다(칩이 흐려진다). 'ytd' = 올해 1월 1일부터(팀 전체가 같은 기간이어야 취합이 맞다).
const PSPAN={ytd:["01-01","12-31"],q1:["01-01","03-31"],q2:["04-01","06-30"],q3:["07-01","09-30"],q4:["10-01","12-31"],h1:["01-01","06-30"],h2:["07-01","12-31"]};
function periodRange(k,today){const t=today||iso(new Date());const s=PSPAN[k];if(!s)return null;
 const a=t.slice(0,4)+"-"+s[0],b=t.slice(0,4)+"-"+s[1];if(a>t)return null;return [a,b>t?t:b];}
function setRange(a,b,el){const t=iso(new Date());
 // 끝이 미래면 오늘로 자른다 — 미래 평일이 가용에 남아 로드율이 떨어지던 것(A34)과 같은 이유
 $("from").value=a;$("to").value=(b>t?t:b);
 document.querySelectorAll("[data-d]").forEach(c=>c.classList.toggle("on",c===el));}
function setDays(n,el){const t=new Date();
 if(PSPAN[n]){const r=periodRange(n);if(r)setRange(r[0],r[1],el);return;}
 setRange(iso(new Date(t.getTime()-n*86400000)),iso(t),el);}
document.querySelectorAll("[data-d]").forEach(c=>{
 const v=c.dataset.d;
 if(PSPAN[v]&&!periodRange(v)){c.style.opacity="0.45";c.style.cursor="default";c.title="아직 오지 않은 기간이라 고를 수 없습니다";}
 else if(PSPAN[v]){const r=periodRange(v);c.title=r[0]+" ~ "+r[1];}
 c.onclick=()=>{if(PSPAN[v]&&!periodRange(v))return;setDays(PSPAN[v]?v:+v,c);};});
setDays("ytd",document.querySelector('[data-d="ytd"]'));
// ── LM30(2026-10-25) '0.04 MM 이하 숨기기'(옵션 줄 칸 — 기본 켜짐 · 이 PC의 설정 config ui.hideSmallMM · GET·POST /api/ui_prefs) ──
// 사용자: "UI 대시보드 디스플레이에 0.04이하는 안보이게 하는 on/off 옵션 넣고, 디폴트는 on". 화면에 보이는 MM(소수 둘째 자리)이 0.04 이하인
// 항목(0·음수 포함 = 0.045 미만 — 서버 SMALL_MM_LT 와 같은 문턱)을 과제·업무 목록(표·범례·칩·막대·원)에서 숨긴다. 그릴 때만 거른다 — 합계·비중·
// 개수·로드율은 그대로(지우거나 다시 계산하지 않는다)이고 숨긴 개수와 합은 표 아래 한 줄로 말한다. 부모(과제·흐름 카드)가 0.04 이하면 자식과
// 함께 숨기고, 보이는 부모 밑의 작은 자식은 그 자리에서만 빠진다. 막대·원은 숨긴 몫을 연회색 한 칸으로 모아 길이와 다른 항목의 비율을 그대로
// 둔다. MM 을 모르는 항목(숫자가 아님)은 숨기지 않는다. 얼린 사본·파일로 연 화면은 설정을 읽지 않고 모두 보인다(칸도 숨긴다).
const SMALL_LT=0.045;
const SMALL_LIVE=location.protocol.indexOf("http")===0&&!document.getElementById("lm-frozen-data");
let HIDE_SMALL=SMALL_LIVE;            // 설정을 읽기 전에도 기본(켜짐)으로 그린다 — 끈 PC 는 읽은 뒤 한 번 다시 그린다(uiPrefsLoad)
let SMALL_TOUCHED=false;              // 읽기 전에 사람이 칸을 바꿨으면 읽은 값으로 되돌리지 않는다
const smallV=v=>typeof v==="number"&&Number.isFinite(v)&&v<SMALL_LT;
// xs 를 보이는 것(vis)과 숨긴 것(hid)으로 가른다 — mm(x) = 그 항목의 MM · 꺼져 있으면 모두 보인다 · 숨긴 개수·합은 t(표 하나의 셈)에도 더한다
function smallSplit(xs,mm,t){const vis=[],hid=[];let sum=0;
 (xs||[]).forEach(x=>{const v=mm(x);if(HIDE_SMALL&&smallV(v)){hid.push(x);sum+=v;}else vis.push(x);});
 if(t){t.n+=hid.length;t.sum+=sum;}
 return {vis,hid,n:hid.length,sum};}
// 거르지 않는 목록(smallSplit 과 같은 모양 — 주간 리뷰: 한 주의 MM 은 작아 0.04 문턱이면 대부분 숨는다 · 2026-10-25)
const smallAll=xs=>({vis:xs||[],hid:[],n:0,sum:0});
const smallTally=()=>({n:0,sum:0});
const smallText=t=>`0.04 MM 이하 ${t.n}개(합 ${(Math.round(t.sum*100)/100||0).toFixed(2)} MM)는 숨겼습니다 — 옵션을 끄면 모두 보입니다`;
const smallLine=t=>(t&&t.n)?`<div class="note">${smallText(t)}</div>`:"";
const smallNote=(el,t)=>{if(!el)return;el.innerHTML=(t&&t.n)?smallText(t):"";el.style.display=(t&&t.n)?"":"none";};
// 막대의 숨긴 몫 — 연회색 한 칸(w = 너비 %) · 툴팁에 개수와 합
const smallSeg=(s,w)=>(s.n&&w>0)?`<i style="width:${w.toFixed(1)}%;background:#e4e7eb" title="${smallText(s)}"></i>`:"";
// 설정 읽기 — 읽지 못하면 기본(켜짐) 그대로. 얼린 사본·파일로 연 화면은 칸을 숨기고 읽지 않는다
async function uiPrefsLoad(){
 const l=$("hidesml"),c=$("hidesm");
 if(!SMALL_LIVE){if(l)l.style.display="none";return;}
 let g=null;try{g=await fetch("/api/ui_prefs").then(r=>r.json());}catch(e){g=null;}
 if(SMALL_TOUCHED||!(g&&g.ok===true&&typeof g.hideSmallMM==="boolean"))return;
 if(c)c.checked=g.hideSmallMM;
 if(g.hideSmallMM!==HIDE_SMALL){HIDE_SMALL=g.hideSmallMM;smallRedraw();}
}
// 칸을 바꾸면 화면은 바로(이미 읽은 자료로 — 다시 분석하거나 새로 고치지 않는다) 다시 그리고, 설정은 이 PC의 config 에 저장한다
async function uiPrefsToggle(){
 const c=$("hidesm");if(!c)return;
 SMALL_TOUCHED=true;HIDE_SMALL=!!c.checked;smallRedraw();
 let r=null;
 try{r=await fetch("/api/ui_prefs",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({hideSmallMM:HIDE_SMALL})}).then(x=>x.json());}catch(e){r=null;}
 if(!(r&&r.ok))alert("표시 설정을 저장하지 못했습니다 — 이 화면에는 반영했지만 다음에 열 때는 예전 설정으로 보입니다."+((r&&r.error)?" ("+r.error+")":""));
}
// 이미 읽은 자료로 다시 그린다 — 대시보드 표(window.__dash)·읽어 둔 리뷰 탭(RVC)·워크플로우 탭(FLC)
function smallRedraw(){
 try{if(window.__dash)drawMM(window.__dash);}catch(e){console.error(e);}
 Object.keys(RVC).forEach(k=>{try{drawReview(k);}catch(e){console.error(e);}});
 try{if(FLC)drawFlow(FLC);}catch(e){console.error(e);}
}
{const c=$("hidesm");if(c)c.onchange=uiPrefsToggle;}

function donut(el,data,center,unit){
 const tot=data.reduce((a,b)=>a+b.v,0);
 if(!tot){el.innerHTML='<div class="note">데이터 없음</div>';return;}
 const R=56,C=2*Math.PI*R;let acc=0,s='<svg viewBox="0 0 150 150">';
 data.forEach(d=>{const f=d.v/tot;
  s+=`<circle r="${R}" cx="75" cy="75" fill="none" stroke="${d.c}" stroke-width="24"
   stroke-dasharray="${(f*C).toFixed(2)} ${C.toFixed(2)}" stroke-dashoffset="${(-acc*C).toFixed(2)}"
   transform="rotate(-90 75 75)"><title>${esc(d.l)} ${d.v.toFixed(2)}</title></circle>`;acc+=f;});
 s+=`<text x="75" y="72" text-anchor="middle" style="font-size:19px;font-weight:800">${center}</text>
 <text x="75" y="90" text-anchor="middle" style="font-size:10px;fill:#8b929b">${unit}</text></svg>`;
 el.innerHTML=s;
}
function weekly(el,tr){
 // 막대 = 판정에 쓰인 신호(파일·작업창·메일·회의·커밋·팀즈) — LM24 의 기준. 신호가 없으면 서버가 수집 raw 로 채운다.
 // '작업창' 은 예전에 '파일' 로 뭉쳐 들어가 하루 8건 상한을 다 먹고 실제 문서를 밀어냈다 — 별도 계열.
 const keys=[["파일","#2a78d6"],["작업창","#7a8a99"],["메일","#0e8c7a"],["회의","#e08a00"],["커밋","#6c4fb8"],["팀즈","#4a7f9e"]];
 const W=740,H=180,L=34,Rm=38,B=26,T=12,iw=(W-L-Rm)/Math.max(tr.length,1);
 const cmax=Math.max(...tr.map(w=>keys.reduce((a,[k])=>a+(Number(w[k])||0),0)),1);
 // 주선(실선) = **근무시간(투입 실측)** 월 합계 — MM·로드율과 같은 산식(회의·산출물·메일·샘플러
 // 세션 합집합 + PC 하한). PC 이벤트 로그가 롤오버로 파괴된 달도 파일·메일 흔적으로 수십 시간이
 // 그대로 나온다(수번째 제보 "수십 시간인데 8h" 의 뿌리 교정). PC 가동 월 합계는 점선 보조선.
 // 근무 실측이 전혀 없으면(수집만 한 PC·분석 전) 기존 PC 선이 주선이다(폴백).
 const hasWk=tr.some(w=>Number(w.wk_h)>0);
 // 축은 **근무 기준** — 항상 켠 PC(월 320h)가 축을 늘리면 괜찮은 근무 실선(70~140h)이 플롯의
 // 19~44% 로 눌린다(실측). PC 가동은 점 툴팁·아래 진단 줄에만 — '기록 가용성 하키스틱' 을
 // 증거 차트에 다시 그려 넣지 않는다(이 도구 스스로 PC 가동을 '시간의 근거가 아니라 교차확인'
 // 으로 규정). 근무 실측이 없으면(수집만·분석 전) 기존 PC 선 폴백.
 const hmax=Math.max(...tr.map(w=>hasWk?(Number(w.wk_h)||0):(Number(w.pc_h)||0)),1);
 const lineVal=w=>hasWk?(Number(w.wk_h)||0):(Number(w.pc_h)||0);
 let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%">`;
 for(let g=0;g<=3;g++){const y=T+(H-T-B)*g/3;
  s+=`<line x1="${L}" x2="${W-Rm}" y1="${y}" y2="${y}" stroke="#eef0f3"/>
  <text x="${L-5}" y="${y+3}" text-anchor="end" style="font-size:9px;fill:#98a0a8">${Math.round(cmax*(1-g/3))}</text>
  <text x="${W-Rm+5}" y="${y+3}" style="font-size:9px;fill:#c8a06a">${(hmax*(1-g/3)).toFixed(0)}h</text>`;}
 // ① PC 기록이 없는 버킷의 회색 띠 — 0h 가 아니라 '모름' 이다(이벤트 로그가 롤오버되면 과거 주는 구조적으로 기록이 없다).
 //   ★ 막대 **뒤**에 깐다. 예전엔 막대 다음에 그려(불투명) 그 달의 막대를 통째로 덮었다 — 옮긴 PC 는 PC 기록이 없어
 //   모든 달이 회색이라 "집계가 안 뜬다" 로 보였다(실측 스크린샷: 1~5월 막대 없음 · 축만 13,203). LM24 에서는 PC 기록이
 //   있는 달만 그려져 발현하지 않았고, LM20 에는 이 띠가 없었다.
 const has=w=>(w.pc_rd!==undefined)?(w.pc_rd>0):((w.pc_wd===undefined)?(w.pc_h>0):(w.pc_days>0));
 // LM30(2026-10-21) 하루 휴가인 평일(pc_lv — 이 PC 화면에만)은 'PC 기록 없음'으로 말하지 않는다(유급휴가 — 일하지 않은 날로 세지 않는다)
 const lvW=w=>Number(w.pc_lv)||0;
 const wdW=w=>Math.max(0,(Number(w.pc_wd)||0)-lvW(w)), pdW=w=>Math.max(0,(Number(w.pc_days)||0)-(Number(w.pc_lv_rec)||0));
 tr.forEach((w,i)=>{if(w.pc_wd!==undefined&&!has(w))
  s+=`<rect x="${(L+i*iw).toFixed(1)}" y="${T}" width="${iw.toFixed(1)}" height="${(H-T-B).toFixed(1)}" fill="#f2f3f5"><title>${(lvW(w)>0&&wdW(w)===0)?`${w.label} 유급휴가 — 일하지 않은 날로 세지 않습니다`:`${w.label} PC 기록 없음 (평일 ${wdW(w)}일 중 0일${lvW(w)>0?` · 유급휴가 ${lvW(w)}일은 뺐습니다`:""}) — 0시간이 아니라 기록이 없는 구간입니다. 막대(신호)는 그대로 셉니다`}</title></rect>`;});
 // ② 막대
 tr.forEach((w,i)=>{
  const x=L+i*iw+iw*0.18,bw=iw*0.64;let y=H-B;
  keys.forEach(([k,c])=>{const h=(H-T-B)*(Number(w[k])||0)/cmax;if(h>0.5){y-=h;
   s+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${c}" rx="1"><title>${w.label} ${k} ${w[k]}건</title></rect>`;}});
  if(tr.length<=16||i%2===0)s+=`<text x="${(x+bw/2).toFixed(1)}" y="${H-B+13}" text-anchor="middle" style="font-size:9px;fill:#8b929b">${w.label}</text>`;
 });
 // ③ PC 가동 선 — 기록 없는 버킷에서 끊는다(0 으로 그리면 선이 바닥에 붙어 'PC 가동이 적용 안 된다' 로 읽혔다)
 let seg=[];
 const flush=()=>{if(seg.length>1)s+=`<polyline points="${seg.join(" ")}" fill="none" stroke="#c8a06a" stroke-width="2"/>`;seg=[];};
 tr.forEach((w,i)=>{if(has(w)||(hasWk&&Number(w.wk_h)>0))seg.push(`${(L+i*iw+iw/2).toFixed(1)},${(H-B-(H-T-B)*lineVal(w)/hmax).toFixed(1)}`);else flush();});
 flush();

 tr.forEach((w,i)=>{const _wk=Number(w.wk_h)||0;if(has(w)||(hasWk&&_wk>0)){
  const part=(w.pc_wd!==undefined&&pdW(w)<wdW(w));
  const _tot=Number(w.pc_h)||0, _rd=Number(w.pc_rd)||0, _avg=_rd>0?_tot/_rd:0;
  const _v=lineVal(w);
  s+=`<circle cx="${(L+i*iw+iw/2).toFixed(1)}" cy="${(H-B-(H-T-B)*_v/hmax).toFixed(1)}" r="2.6" fill="${part?"#fff":"#c8a06a"}" stroke="#c8a06a" stroke-width="${part?1.4:0}"><title>${w.label}${hasWk?` 근무 ${_wk.toFixed(1)}h ·`:""}${w.ext_h!=null?` 연장 ${Number(w.ext_h).toFixed(1)}h ·`:""}${Number(w.hol_h)>0?` 휴일 ${Number(w.hol_h).toFixed(1)}h ·`:""} PC 가동 ${_tot.toFixed(1)}h${_rd?`(기록 ${_rd}일·평균 ${_avg.toFixed(1)}h/일)`:""}${w.pc_wd!==undefined?` (평일 ${pdW(w)}/${wdW(w)}${lvW(w)>0?` · 유급휴가 ${lvW(w)}일`:""})`:""}${_avg>=20?" · PC 종일 켜 둠(야간 포함)":""}</title></circle>`;}});
 el.innerHTML=s+"</svg>";
 $("wleg").innerHTML=keys.map(([k,c])=>`<span><span class="dot" style="background:${c}"></span>${k}</span>`).join("")+
  '<span><span class="dot" style="background:#c8a06a"></span>근무시간(h·오른쪽 축)</span>'+
  '<span><span class="dot" style="background:#f2f3f5;border:1px solid #d7dbe0"></span>PC 기록 없음·유급휴가</span>';
}
// 409 의 사유(hint)를 그대로 보여 준다 — '이미 실행 중' 한 마디로는 보고서 굽는 중인지 알 수 없다
async function busyMsg(r,dflt){let h="";try{h=(await r.json()).hint||"";}catch(e){}return h||dflt;}
let timer=null;
async function poll(){
 try{
  const s=await fetch("/api/status").then(r=>r.json());
  $("log").textContent=s.log.join("\\n")||"…";$("log").scrollTop=$("log").scrollHeight;
  $("step").textContent=s.step||"";
  const fmt=x=>x==null?"":(x<60?`${x}초`:(x<3600?`${Math.floor(x/60)}분 ${x%60}초`:`${Math.floor(x/3600)}시간 ${Math.floor(x%3600/60)}분`));
  if(s.running){
   $("prog").style.display="";
   const pct=s.total?Math.round(s.done/s.total*100):null;
   $("pg_bar").style.width=(pct==null?8:pct)+"%";
   $("pg_bar").style.background=pct==null?"#c9cfd8":"#2a78d6";
   // Copilot 이 잠시 응답을 제한하면 판정이 몇 분 쉬었다 같은 묶음을 다시 보낸다 — 그동안 진행 줄 단계는 'Copilot 대기'
   const coolPh=s.phase==="Copilot 대기";
   $("pg_label").textContent=coolPh?"Copilot 대기 중(사용량 제한 — 쉬었다 이어 보냄)"
    :(s.phase?`${s.phase} ${s.done}/${s.total}${pct!=null?` (${pct}%)`:""}`:(s.step||"준비 중…"));
   $("pg_time").textContent=`경과 ${fmt(s.elapsed)}`+(s.eta!=null?` · 남은 시간 약 ${fmt(s.eta)}`:"");
   // 느린 것과 멈춘 것을 구분할 정보 — 예전에는 "수십 초~수 분" 한 줄뿐이라, 한 왕복이 십 분을 넘기면
   // 사용자가 "멈췄다" 고 판단할 수밖에 없었다(제보: 2시간 정체).
   const aiPhase=s.phase&&/^(AI|워크플로우|Agentic|월별)/.test(s.phase);
   const idle=(s.idle==null?null:s.idle);
   $("pg_hint").textContent=coolPh?"Copilot 이 잠시 응답을 제한해 1~2분 쉬었다가 같은 묶음을 다시 보냅니다(한 번 분석에서 쉬는 시간은 모두 합쳐 5분까지). 창을 닫지 말고 두세요 — 이미 판정한 신호는 저장돼 있습니다."
    :!aiPhase?""
    :("Copilot 왕복 한 번에 1~15분 걸립니다(왕복 상한 roundtripMaxSec)."
      +(idle!=null?` 마지막 소식 ${fmt(idle)} 전 —`:"")
      +(idle!=null&&idle>=120?" 아직 끊지 않았습니다(무출력이 계속되면 자동 중단합니다).":" 진행 중입니다.")
      +" 창을 닫지 말고 두세요 · 멈추려면 [중지]. 단계가 시간 예산에 닿으면 그때까지의 결과를 저장하고 멈춥니다.");
   $("pg_hint").style.color=(idle!=null&&idle>=120)?"#c0122f":"";
  }else{
   $("prog").style.display="none";
   // 실행이 막 끝났으면 업로드 카드도 새로 읽는다 — 분석이 만든 묶음이 바로 보이게(v4)
   // LM28: 팀 서버 자동 보고 결과도 — 실패면 이 실행 몫의 알림 1번 + 배너, 성공이면 상태 글자만(trLoad)
   if(window.__wasRunning){window.__wasRunning=false;tuLoad();trLoad(true);}
  }
  if(s.running){window.__wasRunning=true;window.__trIdle="";}
  // ── 하단 상태바 ──
  $("sb_dot").style.background=s.running?"#e08a00":"#4fc47f";
  $("sb_state").textContent=s.running?(s.step||"실행 중"):"대기";
  if(s.running&&s.total){
   $("sb_prog").style.display="inline-flex";
   const pct=Math.round(s.done/s.total*100);
   $("sb_phase").textContent=s.phase==="Copilot 대기"?"Copilot 대기 중(사용량 제한)":`${s.phase||""} ${s.done}/${s.total}`;
   $("sb_bar").style.width=pct+"%";
   $("sb_eta").textContent=(s.eta!=null?`남은 약 ${fmt(s.eta)}`:`경과 ${fmt(s.elapsed)}`);
  }else if(s.running){
   $("sb_prog").style.display="inline-flex";
   $("sb_phase").textContent="준비 중";$("sb_bar").style.width="8%";
   $("sb_eta").textContent=`경과 ${fmt(s.elapsed)}`;
  }else{$("sb_prog").style.display="none";}
  $("sb_last").textContent=s.last_run?`마지막 분석 ${s.last_run} (${s.last_tag})`:"분석 결과 없음";
  $("go").disabled=s.running;
  $("collect2").disabled=s.running;           // [로컬PC 자료수집]도 [분석 실행]과 똑같이 — 같은 run.py·원장·전용 Edge
  // 분석·웹 읽기 중에는 웹 읽기·커서 초기화를 끈다 — 같은 전용 Edge·원장을 두 작업이 함께 쓰지 않게(F-16)
  // LM30(2026-10-19): GERP 열기·읽기(시험 기능)도 — 같은 전용 Edge 를 쓴다. 카드가 단추를 다시 그릴 때도 이 값으로 끈다(__lmBusy)
  window.__lmBusy=!!s.running;
  ["owa","teamsweb","cvreset","gerpopen","gerpread"].forEach(id=>{const b=$(id);if(b)b.disabled=!!s.running;});
  {const cs=$("chatsweep");if(cs)cs.disabled=!!s.running;}   // LM30 — [LM이 연 Copilot 채팅 지우기]도 같은 전용 Edge 를 쓴다
  ["gerpon","gerpoff","gerpchg","gerpsave","hron"].forEach(id=>{const b=$(id);if(b)b.disabled=!!s.running;});   // LM30(2026-10-19) GERP 켜기·끄기도(옵션 줄 칸 포함)
  if(s.running)["pcimpgo","pcimprf","pcimpone"].forEach(id=>{const b=$(id);if(b)b.disabled=true;});   // LM30(2026-10-21) 가져오기 — 수집이 같은 원장에 쓴다(끝나면 카드를 다시 그린다)
  {const lb=$("lvsave");if(lb)lb.disabled=!!s.running;}   // LM30(2026-10-21) '휴가 날짜' 저장 — 분석이 그 파일을 읽는다(서버도 409)
  // LM28(2026-10-19): 작업이 도는 동안에는 [데이터 리셋]도 끈다(누르면 '실행 중'만 들었다) — 무엇이 도는지는 버튼에 마우스를 올리면 보인다
  const rsb=$("reset");if(rsb){rsb.disabled=!!s.running;rsb.title=s.running?`지금 도는 작업: ${s.step||"분석 실행"} — 끝나면 누를 수 있습니다`:"";}
  $("stop").style.display=s.running?"":"none";
  leaveGuard(!!s.running);                    // 작업 중에는 창을 닫기 전에 브라우저가 한 번 묻는다(닫으면 작업도 멈춘다)
  // 대기 글자 뒤에 이번 세션에서 끝난 실행의 팀 서버 보고 성공을 조용히 붙인다(3초 폴링이 지우지 않게 — trRender 가 채움)
  $("state").textContent=s.running?"실행 중…":("대기 중"+(window.__trIdle?" · "+window.__trIdle:""));
  if(s.running)$("dlog").open=true;
  if(!s.running&&timer){clearInterval(timer);timer=null;}
  // 실행 중 새로고침하면 timer 가 없어 완료를 놓친다 — 상태 전이(running→멈춤)로 판정한다
  if(wasRunning&&!s.running){loaded={};refresh();cvLoad();
   // 보고 있던 리뷰 탭은 바로 다시 그린다 — 실행이 끝나면 새 월별 코멘트가 보이게(예전에는 탭을 다시 눌러야 했다)
   if(["week","month","deep"].includes(curTab)){loaded[curTab]=1;loadReview(curTab).catch(()=>{loaded[curTab]=0;});}}
  wasRunning=s.running;
 }catch(e){$("state").textContent="서버 연결 끊김 — 창을 닫고 다시 실행하세요";}
}
let wasRunning=false;
// LM30(2026-10-25) 과제·업무 MM 목록 — 프로젝트별 로드(원·범례) · 프로젝트 내 업무 로드 · 세부업무 분포 · 업무별 상세 표. refresh 가 읽은
// /api/dash(window.__dash)로 그린다 — '0.04 MM 이하 숨기기'를 바꾸면 다시 읽지 않고 이것만 다시 부른다(smallRedraw). 숨긴 것은 각 카드 아래 한 줄.
function drawMM(d){
 const rs=d.rows||[];
 const projs=[...new Set(rs.map(r=>r["Level 2"]))];
 const col=p=>PAL[projs.indexOf(p)%PAL.length];
 const byP={};rs.forEach(r=>byP[r["Level 2"]]=(byP[r["Level 2"]]||0)+(r.mm||0));
 // 표시 정리: 항목이 많으면 상위 10개 + '기타(묶음)' — 수십 개 나열은 읽을 수 없다(실측)
 // 0.04 MM 이하 과제는 범례에서 빼고 원에서만 연회색 한 조각으로 남긴다 — 다른 조각의 비율이 그대로이게
 const tD=smallTally(), sD=smallSplit(Object.entries(byP).sort((a,b)=>b[1]-a[1]),([,v])=>v,tD);
 let dd=sD.vis.map(([l,v])=>({l,v,c:col(l)}));
 if(dd.length>12){
  const rest=dd.slice(10), sum=rest.reduce((s,x)=>s+x.v,0);
  dd=dd.slice(0,10); dd.push({l:`기타 (${rest.length}개 묶음)`,v:sum,c:"#98a0a8"});
 }
 donut($("donut"),(sD.n&&sD.sum>0)?dd.concat([{l:`0.04 MM 이하 ${sD.n}개(숨김)`,v:sD.sum,c:"#e4e7eb"}]):dd,(d.total||0).toFixed(1),"MM 합계");
 $("dleg").innerHTML=(dd.map(x=>`<div><span class="dot" style="background:${x.c}"></span>${esc(x.l)}<span class="v">${x.v.toFixed(2)} MM</span></div>`).join("")+smallLine(tD))||'<div class="note">분석을 실행하세요</div>';
 // 프로젝트 내 업무 로드 — 과제(Level 2) 안에서 중위 업무(Level 3)별 MM 과 과제 내 비중.
 // 예: A 프로젝트 → A-1 시뮬레이션 0.4MM(50%), A-2 보고서 작성 0.2MM(25%)
 // 0.04 MM 이하 과제는 업무와 함께 숨기고, 보이는 과제 안의 0.04 MM 이하 업무는 범례에서 빼 막대 끝 연회색 한 칸으로(비중·업무 수는 과제 전체 기준 그대로)
 const byPj={};rs.forEach(r=>{
  const p2=r["Level 2"]||"미지정", w=r["Level 3"]||"기타";
  (byPj[p2]=byPj[p2]||{}); byPj[p2][w]=(byPj[p2][w]||0)+(r.mm||0);});
 const tP=smallTally();
 const pjs=smallSplit(Object.entries(byPj).map(([p2,ws])=>({p2,ws,tot:Object.values(ws).reduce((a,b)=>a+b,0)}))
  .sort((a,b)=>b.tot-a.tot).slice(0,8),pj=>pj.tot,tP).vis;
 $("pjwork").innerHTML=(pjs.map(pj=>{
  const all=Object.entries(pj.ws).sort((a,b)=>b[1]-a[1]), sw=smallSplit(all,([,v])=>v,tP), det=sw.vis;
  const bar=det.map(([w,v],i)=>`<i style="width:${(v/(pj.tot||1)*100).toFixed(1)}%;background:${PAL[i%PAL.length]}" title="${esc(w)} ${v.toFixed(2)} MM"></i>`).join("")
   +smallSeg(sw,sw.sum/(pj.tot||1)*100);
  const leg=det.map(([w,v],i)=>`<div><span class="dot" style="background:${PAL[i%PAL.length]}"></span>${esc(w)}<span class="v">${v.toFixed(2)} MM · ${(v/(pj.tot||1)*100).toFixed(0)}%</span></div>`).join("");
  return `<div style="margin:8px 0 12px">
   <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:3px">
    <span class="dot" style="background:${col(pj.p2)}"></span><b>${esc(pj.p2)}</b>
    <span class="state">${pj.tot.toFixed(2)} MM · 업무 ${all.length}개</span></div>
   <div class="bigbar">${bar}</div>
   <div class="leg" style="font-size:11px">${leg}</div></div>`;
 }).join("")+smallLine(tP))||'<div class="note">분석을 실행하세요</div>';
 // 분포 개요는 9종 활동 범주('활동' 열, 정제 후) — 없으면 Level 3 로 폴백(정제 전).
 const byA={};rs.forEach(r=>{const k=(r["활동"]||"").trim()||r["Level 3"]||"기타";byA[k]=(byA[k]||0)+(r.mm||0);});
 const aa=Object.entries(byA).sort((a,b)=>b[1]-a[1]);
 const atot=aa.reduce((s,[,v])=>s+v,0)||1;
 const tA=smallTally(), sA=smallSplit(aa,([,v])=>v,tA);
 $("actbar").innerHTML=sA.vis.map(([l,v],i)=>`<i style="width:${(v/atot*100).toFixed(1)}%;background:${PAL[(i+3)%PAL.length]}" title="${esc(l)} ${(v/atot*100).toFixed(0)}%"></i>`).join("")
  +smallSeg(sA,sA.sum/atot*100);
 $("actleg").innerHTML=(sA.vis.map(([l,v],i)=>`<div><span class="dot" style="background:${PAL[(i+3)%PAL.length]}"></span>${esc(l)}<span class="v">${(v/atot*100).toFixed(0)}% · ${v.toFixed(2)} MM</span></div>`).join("")+smallLine(tA))||'<div class="note">분석을 실행하세요</div>';
 // 업무별 상세 — 0.04 MM 이하 행은 빼고 표 아래 한 줄(항목 수·비중은 그대로)
 const tR=smallTally(), vr=smallSplit(rs,r=>r.mm,tR).vis;
 $("res").innerHTML="<tr><th style='width:80px'>Level 1</th><th style='width:60px'>유형</th><th style='width:150px'>Level 2 (과제)</th><th style='width:90px'>Level 3</th><th>상세설명</th><th style='width:120px'>근거(출처)</th><th style='width:58px'>비중</th><th style='width:48px'>MM</th><th style='width:36px'>확신</th></tr>"+
  (rs.length?vr.map(r=>`<tr><td>${esc(r["Level 1"])||"-"}</td><td>${esc(r["유형"]||"")}</td>
   <td><span class="dot" style="background:${col(r["Level 2"])}"></span><b>${esc(r["Level 2"])}</b></td>
   <td>${esc(r["Level 3"])}</td>
   <td style="color:#4a5159">${esc(r["상세설명"])||"<span style='color:#b9c0c8'>(AI 정제 전)</span>"}</td>
   <td style="color:#8b929b;font-size:11px">${esc(r["근거"])}</td>
   <td>${r.share}%</td><td><b>${r.mm}</b></td><td>${esc(r["확신도"])}</td></tr>`).join("")
   :"<tr><td colspan=9 style='color:#8b929b'>아직 결과가 없습니다 — 위에서 [분석 실행]을 누르세요.</td></tr>");
 smallNote($("ressm"),tR);
}
async function refresh(){
 let d;
 try{ d=keepDash(await fetch("/api/dash").then(r=>r.json())); }
 catch(e){ $("state").textContent="대시보드 데이터를 읽지 못했습니다 — 진행 로그를 확인하세요"; return; }
 $("ver").textContent=`${d.version} · 포트 ${d.port} · 로컬 전용`;
 // 스텁 판정 배너 — 무엇보다 먼저. LM_COPILOT_STUB 로 만든 결과는 실제 Copilot 판정이 아니다(테스트 전용).
 // 얼린 사본은 이 화면과 같은 스크립트가 baked /api/dash 를 읽으므로 같은 배너가 그대로 굳는다.
 const sbn=$("stub_banner");
 if(sbn){
  if(d.stub){
   sbn.style.display="";
   sbn.innerHTML='⚠ <b>스텁 판정 — 실제 Copilot 판정 아님(테스트 전용)</b>: 이 결과는 LM_COPILOT_STUB 스텁 응답으로 만든 것입니다. '
    +'과제·세부업무·MM 배분·리뷰 코멘트를 실제 판정으로 쓰거나 팀에 올리지 마세요.'
    +(d.stub_note?`<div style="font-weight:400;font-size:11.5px;margin-top:3px">기록: ${esc(d.stub_note)}</div>`:"");
  }else if(d.stub_env&&!document.getElementById("lm-frozen-data")){
   // 떠 있는 프로세스의 상태라 얼린 사본에는 굳히지 않는다(사본은 결과의 표식 d.stub 만 본다)
   sbn.style.display="";
   sbn.innerHTML='⚠ <b>테스트 모드(LM_COPILOT_STUB)</b> — 이 대시보드는 스텁 환경으로 떠 있어 다음 [분석 실행]의 AI 판정은 실제 Copilot 이 아니라 스텁 응답을 씁니다.';
  }else{ sbn.style.display="none"; }
 }
 const rs=d.rows||[];
 try{chatLine(d.last_run);}catch(e){}         // LM30 — 마지막 실행의 Copilot 채팅 한 줄(연·지운·남긴 수와 까닭)
 const mm=d.meta||{};
 const inMM=(mm.total_mm!=null?mm.total_mm:d.total)||0, avMM=mm.avail_mm||0;
 $("k_load").textContent=avMM?Math.round(inMM/avMM*100)+"%":"–";
 $("sb_load").textContent=avMM?`로드율 ${Math.round(inMM/avMM*100)}% (투입 ${inMM.toFixed(2)}/가용 ${avMM.toFixed(2)} MM)`:"";
 $("sb_ver").textContent=`${d.version} · 포트 ${d.port}`;
 $("k_mm").textContent=avMM?`투입 ${inMM.toFixed(2)} / 가용 ${avMM.toFixed(2)} MM`:(d.total?d.total.toFixed(2)+" MM":"분석 전");
 const byP={};rs.forEach(r=>byP[r["Level 2"]]=(byP[r["Level 2"]]||0)+(r.mm||0));
 // 주력 업무 = 프로젝트 '합계' 최대 — 단일 행 최대(rs[0])로 하면 행이 여러 개로 쪼개진
 // 프로젝트가 밀려나 아래 '프로젝트별 로드' 도넛과 다른 답이 나온다(실측 지적).
 const topP=Object.entries(byP).sort((a,b)=>b[1]-a[1])[0];
 $("k_top").textContent=topP?topP[0]:"–";
 $("k_topn").textContent=topP?`${d.total?(topP[1]/d.total*100).toFixed(0):0}% · ${topP[1].toFixed(2)} MM`:"";
 $("k_items").textContent=rs.length||"–";
 $("k_acts").textContent=[...new Set(rs.map(r=>r["Level 3"]).filter(Boolean))].join(" · ");
 const ok=d.sources.filter(s=>s.status==="ok").length;
 $("k_src").textContent=`${ok}/${d.sources.length}`;
 $("k_srcn").textContent=d.sources.filter(s=>s.status==="bad").map(s=>s.name+" 없음")
  .concat(d.sources.filter(s=>s.status==="warn").map(s=>s.name+" 부족")).join(", ")||"필수 소스 정상";
 // 지금 보는 표가 '이번 실행·이 PC' 의 결과가 아니면 무엇보다 먼저 말한다.
 // judged 여부와 무관하게 뜬다 — 사용자가 본 '예시 화면'은 판정까지 끝난 산출물이라
 // 아래 judged===false 게이트로는 절대 잡히지 않는다(실측).
 const noticeBar=$("notice_bar"), noticeRun=d.last_run||{};
 if(noticeBar){
  if(d.stale){
   noticeBar.style.display="";
   noticeBar.innerHTML='\u23f3 <b>분석 진행 중</b> — 아래 표는 <b>직전 실행 결과</b>입니다. 끝나면 자동으로 바뀝니다.';
  }else if(d.collected_only){
   // 수집만 하고 분석을 안 한 상태 — 이때는 묶음도 워크플로우도 생기지 않는다.
   // 눌러 봐야 아는 대신(업로드 '보낼 결과가 없습니다', 워크플로우 탭 빈 화면) 먼저 말한다.
   noticeBar.style.display="";
   noticeBar.innerHTML='\u2139\ufe0f <b>자료수집만 되어 있습니다([로컬PC 자료수집]) — 아직 분석하지 않았습니다.</b> '
     +'이 상태에서는 팀 서버 보고 묶음도, 담당자 워크플로우도 만들어지지 않습니다.<br>'
     +(noticeRun.account_data==="skipped"
       ?'메일·일정·팀즈는 회사 계정 자료라 이 버튼에서 읽지 않았습니다 — 같은 계정이면 폴더를 받은 PC 의 [분석 실행]이 읽습니다.<br>':'')
     +'<b>이 PC 가 분석할(마지막) PC 라면 위 [분석 실행]</b>을 누르세요 — 수집·AI 분석·팀 서버 보고까지 합니다. '
     +'다른 PC 라면 [PC 이동 준비] 후 폴더를 옮기면 됩니다.';
  }else if(d.foreign){
   noticeBar.style.display="";
   noticeBar.innerHTML='\u26a0\ufe0f 이 결과는 <b>이 PC 에서 만든 것이 아닙니다</b> ('
     +esc(noticeRun.host||"다른 PC")+' 에서 실행). 배포본에 딸려온 <b>샘플</b>일 수 있습니다 — '
     +'[분석 실행] 으로 이 PC 의 데이터를 분석하세요.';
  }else{ noticeBar.style.display="none"; }
 }
 // 판정이 반영되지 않은 화면이면 '왜'까지 말한다 — 원인별로 조치가 다르다
 const jw=$("judged_warn");
 // S1-12: 판정 기록(ai_judgments)의 실패·부분·중단·복구 — 파일에 있는 키만, 값이 있을 때만 한 줄
 // LM28(진단 A): 중단 갈래(abort_kind)별 문구 · 'AI가 직접 못 본 행(채움·규칙)' 은 unseen_rows 로(구판 기록은 failed_rows)
 const ji=d.judged_issues||{}, jiBits=[];
 const ABORT_KO={throttle:"Copilot 사용량 제한으로 중단",login:"Copilot 로그인 만료로 중단",
  fatal:"사람이 손대야 풀리는 상태로 중단",budget:"시간 예산 도달"};
 const jiAk=String(ji.abort_kind||""), jiFill=Number(ji.filled_rows)||0;
 if(ji.unseen_rows!=null){
  if(ji.unseen_rows>0) jiBits.push(`AI가 직접 못 본 행 ${ji.unseen_rows} (비슷한 판정으로 채움 ${jiFill} · 규칙 ${Math.max(0,ji.unseen_rows-jiFill)})`);
 }else if(ji.failed_rows>0) jiBits.push(`실패로 규칙에 남은 행 ${ji.failed_rows}`);
 if(ji.partial_chunks>0) jiBits.push(`부분 판정 청크 ${ji.partial_chunks}`);
 // 시간 예산 도달(budget)은 aborted=false 로 온다 — 따로 본다
 if(ji.aborted||jiAk==="budget") jiBits.push((ABORT_KO[jiAk]||"연속 실패로 중단")
  +(ji.abort_reason?` (${esc(String(ji.abort_reason).slice(0,80))})`:""));
 if(ji.repaired>0) jiBits.push(`잘린 응답 복구 ${ji.repaired}회`);
 if(ji.reextracted) jiBits.push(ji.reason||"판정 이후 재추출됨");
 // 판정 구조(참고) — 지난 실행 재사용·같은 내용 묶음·보내지 않은 짧은 대화·쉬고 다시 보낸 횟수·대체 모델
 const jiInfo=[];
 if(ji.cache_reused>0) jiInfo.push(`지난 실행 재사용 ${ji.cache_reused}`);
 if(ji.group_rows>0) jiInfo.push(`같은 내용 묶음 ${ji.group_rows}행`);
 if(ji.lowinfo_rows>0) jiInfo.push(`짧은 대화 ${ji.lowinfo_rows}행(보내지 않음)`);
 if(ji.cooldowns>0) jiInfo.push(`대기 ${ji.cooldowns}회`);
 if(ji.rotations>0) jiInfo.push(`채팅 회전 ${ji.rotations}회`);   // LM30 — chatTurns 마다 새 채팅으로 넘어간 횟수
 if(ji.model_fallback) jiInfo.push(`대체 모델 ${esc(ji.model_fallback)}`);
 const jiLine=(jiBits.length?('· 판정 기록: '+jiBits.join(' · ')):"")
  +(jiInfo.length?((jiBits.length?'<br>':'')+'· 판정 구조: '+jiInfo.join(' · ')):"");
 const jiBad=(ji.failed_rows>0)||(ji.partial_chunks>0)||!!ji.aborted||jiAk==="budget";
 // 중단 갈래별 조치 — 사용량 제한·로그인 만료는 '바로 다시' 가 같은 벽이다. 이미 판정한 신호는 캐시에 남아 다시 묻지 않는다
 const jiHow=jiAk==="throttle"?"1~2시간 뒤 [재분석만]+AI 정제 — 이미 판정한 신호는 날짜가 바뀌어도 다시 묻지 않고 남은 것만 이어서 합니다."
  :(jiAk==="login"?"전용 Edge 창에서 Copilot 에 다시 로그인한 뒤([AI 연결 진단]) [재분석만]+AI 정제 — 이미 판정한 신호는 다시 묻지 않고 남은 것만 이어서 합니다."
  :"[재분석만]+AI 정제로 재실행하면 남은 행만 이어서 판정합니다(이미 판정한 신호는 날짜가 바뀌어도 다시 묻지 않습니다).");
 if(rs.length&&d.judged===false){
  const lr=d.last_run||{}, st=(lr.stages||[]);
  const j=st.find(x=>x.name==="AI 판정");
  // 화면 파일의 기간과 최근 실행의 기간이 다르면 — 최근 실행이 결과를 못 만든 것.
  // 이걸 먼저 말하지 않으면 '다시 실행하세요' 안내가 영원히 반복된다(검증 지적).
  const mTag=(d.file||"").match(/mm_rows_(\\d{8}-\\d{8})/);
  const lrTag=(lr.period&&lr.period.length===2)?(lr.period[0]+"-"+lr.period[1]).replace(/-/g,"").replace(/^(\\d{8})(\\d{8})$/,"$1-$2"):"";
  const tagMismatch=mTag&&lrTag&&mTag[1]!==lrTag;
  const stopped=lr.started&&!lr.finished;
  let why="", how="";
  if(tagMismatch){
   why=`최근 실행(${esc(lrTag)})이 결과를 만들지 못해, 화면은 <b>이전 분석(${esc(mTag[1])})</b>입니다`
       +(st.length?` — 최근 실행의 마지막 단계: ${esc(st[st.length-1].name)}${st[st.length-1].ok?"":" 실패"}`:"")+".";
   how="진행 로그에서 최근 실행이 어디서 멈췄는지 확인하세요. config/config.json 문법 오류면 실행이 시작도 못 합니다.";
  }else if(ji.reextracted){
   // 판정 뒤에 업무 로드가 다시 추출됐다(무AI 재실행·판정 실패·중단) — 지난 정제본·판정 기록은 .stale 로 무효화됐고
   // 이 표·KPI·리포트는 모두 새 규칙 결과다(V-01: 셋이 서로 다른 값을 보이던 결함)
   why="AI 판정 뒤에 업무 로드가 <b>다시 추출</b>됐습니다(판정 이후 재추출됨)"+(lr.ai_requested===false?" — 최근 실행은 AI 판정 없이 돌았습니다":"")
       +". 지난 판정 산출물(정제본·판정 기록)은 .stale 로 무효화돼 표·KPI·리포트가 모두 규칙 결과입니다.";
   how="[분석 실행] 옆의 <b>AI 정제</b> 체크를 켜고 다시 실행하세요 (재수집 없이 하려면 '재분석만'도 함께). Agentic AI·워크플로우 탭의 지난 결과는 '재추출 이후 결과'로 표시됩니다.";
  }else if(!j&&lr.ai_requested===false){
   why="AI 판정을 켜지 않고 실행했습니다.";
   how="[분석 실행] 옆의 <b>AI 정제</b> 체크를 켜고 다시 실행하세요 (재수집 없이 하려면 '재분석만'도 함께).";
  }else if(!j&&stopped){
   const lastSt=st.length?st[st.length-1]:null;
   why="분석이 <b>AI 판정 단계에 도달하기 전에 중단</b>됐습니다"+(lastSt?` (마지막 단계: ${esc(lastSt.name)})`:"")+".";
   // 마지막 단계의 note 에 진짜 원인(오류 줄·신호 0건 등)이 실려 있다 — 이걸 숨기면
   // 사용자는 "수집이 오래 걸렸나" 같은 엉뚱한 안내만 보게 된다(실측: 회사 PC 오진단).
   if(lastSt&&lastSt.note){ why+=`<br>· 기록된 원인: <b>${esc(lastSt.note)}</b>`; }
   how=(lastSt&&lastSt.note&&lastSt.note.indexOf("오류")>=0)
     ?"위 원인의 오류 메시지를 확인하세요. 반복되면 이 문구를 캡처해 개발자에게 전달하면 원격 진단이 됩니다."
     :"수집이 오래 걸렸을 수 있습니다. [재분석만]+AI 정제로 다시 돌리면 수집을 건너뛰고 판정만 수행합니다.";
  }else if(j&&j.ok===false){
   why="AI 판정이 실패했습니다"+(j.note?`: ${esc(j.note)}`:"")+".";
   how=(jiAk==="throttle"||jiAk==="login")?jiHow:"전용 Edge 창에서 Copilot 로그인 상태를 확인한 뒤 [재분석만]+AI 정제로 재실행하세요.";
  }else if(j&&d.judged_n===0){
   // 단계는 '성공'인데 판정 0건 — 왕복이 전부 실패한 경우(스텁 응답 없음·로그인 만료). 규칙 결과가 남아 있다.
   why="AI 판정은 실행됐지만 <b>판정된 신호가 0건</b>입니다"+(d.judged_total?` (대상 ${d.judged_total}건)`:"")
       +" — 왕복이 전부 실패했을 때 이렇게 됩니다"+(j.note?` (기록: ${esc(j.note)})`:"")+".";
   how=(jiAk==="throttle"||jiAk==="login")?jiHow
     :"[AI 연결 진단]으로 Copilot 왕복이 되는지 확인한 뒤 [재분석만]+AI 정제로 재실행하세요. 스텁(LM_COPILOT_STUB) 환경이면 스텁 응답 파일이 있는지 보세요.";
  }else if(j&&d.judged_n==null){
   why="AI 판정 기록 파일(ai_judgments)이 없거나 읽을 수 없습니다.";
   how="[재분석만]+AI 정제로 다시 실행하면 판정 기록이 새로 만들어집니다.";
  }else if(!j){
   why="이 결과에는 AI 판정 기록이 없습니다.";
   how="[분석 실행]에서 <b>AI 정제</b>를 켜고 실행하세요.";
  }else{
   why="AI 판정은 성공했지만 이 화면은 판정 전 결과입니다.";
   how="기간이 다른 옛 결과일 수 있습니다 — 기간을 확인하고 다시 실행하세요.";
  }
  const el=st.filter(x=>x.sec>60).sort((a,b)=>b.sec-a.sec)[0];
  const slow=el?` <span style="color:#8a5a00">· 가장 오래 걸린 단계: ${esc(el.name)} ${Math.round(el.sec/60)}분</span>`:"";
  jw.innerHTML='⚠ <b>AI 판정이 반영되지 않은 화면</b> — 아래 과제는 규칙이 임시로 뽑은 토큰입니다.<br>'
   +'· 원인: '+why+'<br>· 조치: '+how+slow+(jiLine?'<br>'+jiLine:'');
  jw.style.display="";
 } else if(rs.length&&d.judged===true&&jiBad){
  // 판정은 반영됐지만 일부 행을 AI 가 직접 보지 못했다(중단·부분 청크) — 비슷한 AI 판정으로 채운 행(AI(유사)) 말고는
  // 규칙이 기존 과제(또는 공통)에 임시 배정했다. 규칙 경로는 이제 사람 이름·공지 토큰을 과제로 만들지 않는다(진단 B).
  jw.innerHTML='⚠ <b>AI 판정이 일부만 반영된 화면</b> — '
   +(jiFill>0?'못 본 행은 비슷한 AI 판정(AI(유사))으로 채웠고, 닮은 것이 없는 행은 규칙으로 기존 과제(또는 공통)에 임시 배정돼 있습니다.'
     :'실패한 행은 규칙으로 기존 과제(또는 공통)에 임시 배정돼 있습니다.')+'<br>'
   +jiLine+'<br>· 조치: '+jiHow;
  jw.style.display="";
 } else { jw.style.display="none"; }
 drawMM(d);              // 프로젝트별 로드·프로젝트 내 업무 로드·세부업무 분포·업무별 상세 표(LM30 2026-10-25 — '0.04 MM 이하 숨기기'를 바꾸면 이것만 다시)
 weekly($("weekly"),d.trend||[]);
 // 제목은 묶음 단위를 따른다 — 1·3개월은 '주간', 6개월·1년·올해는 '월간' 활동 추이. 그린 기간을 제목에 적어
 // '어느 기간의 결과를 보고 있는지' 가 화면에 남게 한다(기본 기간이 bat·run.py·화면에서 서로 달라 기간이
 // 바뀐 줄 모르고 "추이가 고장났다" 로 읽히던 것 — 이제 기본은 셋 다 '올해' 다).
 {const ti0=d.trend_info||{};const wt=$("wtitle"),ws=$("wsub");const per0=ti0.period||d.period||[];
  if(wt)wt.textContent=(ti0.gran==="month"?"월간":"주간")+" 활동 추이";
  if(ws)ws.textContent=(per0[0]?`${per0[0]} ~ ${per0[1]||""} · `:"")
   +(ti0.gran==="month"?"막대 하나 = 한 달":"막대 하나 = 한 주")
   +(d.trend_src==="signals"?" · 막대 = 판정에 쓰인 신호 건수(MM 과 같은 축)":" · 막대 = 수집된 흔적 건수")+" · 선 = 근무시간(투입 실측·월 합계 — PC 가동은 점 툴팁·진단 줄)";}
 // 메일·일정이 기간의 일부 달만 수집된 상태(Outlook 시간 예산) — 앞 달의 메일·회의 막대가 비어 보이는 이유를 적는다
 const wn=$("wnote");
 if(wn){const mc=d.mail_coverage||null;const notes=[];
  // 막대는 판정 표본이 아니라 수집량이다 — 무엇을 셌는지, 뿌리 몇 개를 합쳤는지, 덩어리를 얼마나 뺐는지 한 줄로.
  {const tq=d.trend_info||{};const rt=Number(tq.roots||1);
   if(d.trend_src==="raw"&&d.period&&d.period[0]) notes.push(`아직 판정 신호가 없어(분석 전·수집만 한 PC) 막대는 <b>수집된 흔적</b>으로 그렸습니다 — AI 정제를 켠 [분석 실행] 뒤에는 판정 신호 기준(MM 과 같은 축)으로 바뀝니다`
    +(rt>1?` · 본 PC + 추가 PC ${rt-1}개 폴더 합산(같은 사건은 1회만)`:"")
    +(tq.signals_n?` · 이 중 판정에 쓰인 표본 신호 ${Number(tq.signals_n).toLocaleString()}건`:"")
    +".");}
  if(mc&&(mc.uncovered||[]).length) notes.push(`⚠ 메일·회의 막대는 ${mc.months}개월 중 <b>${(mc.covered||[]).length}개월</b>만 수집돼 있습니다 — 미수집 ${esc(mc.uncovered.join(", "))} (Outlook 시간 예산). [분석 실행]을 다시 돌리면 남은 달을 이어서 읽습니다.`);
  // PC 가동 선은 Windows 이벤트 로그에서 온다. 로그는 롤오버되므로 기간 앞쪽은 '0시간' 이 아니라
  // '기록 없음' 이다 — 그것을 말해 주지 않으면 'PC 가동이 적용 안 된다'로 읽힌다(제보).
  const ti=d.trend_info||{};const unit=ti.gran==="month"?"개월":"주";
  if(ti.pc_buckets_all&&ti.pc_buckets<ti.pc_buckets_all)
   notes.push(`PC 가동 선은 ${ti.pc_buckets_all}${unit} 중 <b>${ti.pc_buckets}${unit}</b>만 기록이 있습니다`
    +(ti.pc_days_total!=null?` (기록 있는 날 ${Number(ti.pc_days_total).toLocaleString()}일 — 선의 높이는 그 날들의 합입니다)`:"")
    +(ti.pc_from?` — Windows 이벤트 로그가 <b>${esc(ti.pc_from)}</b> 까지만 남아 있어 그 앞은 <b>0시간이 아니라 기록 없음</b>입니다(회색 구간).`:` — 회색 구간은 0시간이 아니라 기록이 없는 구간입니다.`));
  // PC 가동 진단 — **항상** 한 줄. 제보 "8h 라니 합산한 숫자도 아니다" 처럼 숫자가 낮을 때
  // 그것이 합산 실패인지 기록 부족인지 이 줄에서 끝나게 한다(합계·기록일·폴더별·로그 커버리지).
  {const pd=ti.pc_diag||{};const sum=(d.trend||[]).reduce((a,w)=>a+(Number(w.pc_h)||0),0);
   if((pd.roots||[]).length||sum>0){
    const per=(pd.roots||[]).map(r=>`${esc(r.name)} ${r.hours}h(${r.days}일·구간 ${r.spans})`).join(" + ");
    const cov=(pd.coverage_days!=null&&pd.range_days)?` · 이벤트 로그는 이 기간 ${pd.range_days}일 중 <b>${pd.coverage_days}일</b>만 덮습니다${pd.reach_start?`(${esc(pd.reach_start)} 부터)`:""}`:"";
    notes.push(`PC 가동 합계 <b>${sum.toFixed(1)}h</b> · 기록 있는 날 ${Number(pd.days||ti.pc_days_total||0).toLocaleString()}일`
     +(per?` · 폴더별 ${per}`:"")+cov
     +(pd.generated?` · 마지막 수집 ${esc(pd.generated)}`:"")
     +(pd.dropped?` · <span style="color:#c0122f">읽지 못한 행 ${pd.dropped}개</span>`:"")
     +((pd.roots||[]).length>1?" — 합계는 구간 합집합이라 폴더별 단순 합과 다릅니다(같은 시간대 중복 제거)":""));
    if(pd.fallback_boot) notes.push(`⚠ 이 기간 <b>Windows 이벤트 로그가 0건</b>이라 '부팅 후 경과시간' 한 구간만으로 PC 선을 그렸습니다(수집만 한 PC·권한 차단·Modern Standby). 그 달의 '${(sum||0).toFixed(1)}h' 는 합산이 아니라 <b>하루치 부팅 시간</b>입니다 — 이 PC 에서 [분석 실행]을 하면 켜기·끄기 기록이 쌓여 앞으로 정확해집니다.`);
    if(pd.dropped) notes.push(`⚠ PC 기록 파일에서 <b>읽지 못한 행 ${pd.dropped}개</b>가 있었습니다(이동 중 잘렸을 수 있음) — 그 파일만 빼고 나머지로 그렸습니다. [분석 실행]으로 다시 수집하면 복구됩니다.`);
    if(pd.warn) notes.push(`⚠ ${esc(pd.warn)} — 롤오버된 과거는 되살릴 수 없지만, 브라우저 사용기록 힌트가 닿는 만큼 보강합니다. [분석 실행]을 자주 하면 <b>앞으로의 구간</b>은 로그가 지워지기 전에 PC 기록 원장(추가 전용)에 남습니다.`);
   }}
  if(ti.wk_note) notes.push(`⚠ ${esc(ti.wk_note)}`);
  if(ti.raw_outside_n>0&&(ti.sig_span||[]).length===2)
   notes.push(`판정 기간(${esc(ti.sig_span[0])} ~ ${esc(ti.sig_span[1])}) <b>밖</b>의 막대 ${Number(ti.raw_outside_n).toLocaleString()}건은 <b>수집 흔적</b> 기준입니다 — 집계기간 전체를 보이기 위해 판정 전 달도 함께 그립니다(그 달을 판정 축으로 보려면 그 기간으로 [분석 실행]).`);
  if(ti.pc_note) notes.push(`⚠ ${esc(ti.pc_note)}`);
  if(ti.capped>0) notes.push(`파일 막대는 하루 8건까지만 셉니다 — 이 기간에 <b>${Number(ti.capped).toLocaleString()}건</b>이 상한에 눌렸습니다(공유폴더 재동기화가 그래프를 지배하지 않게 하는 장치 · 실제 신호 수는 [업무 리뷰] 탭).`);
  if(notes.length){wn.style.display="";wn.innerHTML=notes.join("<br>");}
  else wn.style.display="none";}
 // 같은 시각에 몰린 덩어리가 있으면 알린다 — 그날 일한 것이 아닐 수 있다
 const cl=$("wclump");
 if(cl){const cs=d.clumps||[];
  cl.innerHTML=cs.length?cs.map(c=>
   `<div style="color:#a86400;background:#fdf3e2;border-left:4px solid #e08a00;`
   +`padding:8px 12px;border-radius:6px;margin:6px 0;font-size:12px">`
   +`<b>${esc(c.when)}</b> 한 시각에 파일 <b>${c.n.toLocaleString()}건</b>`
   +` (이 기간 파일 흔적의 ${Math.round(c.share*100)}%)`
   +(c.folder?` · <code>${esc(c.folder)}</code>`:"")
   +`<br>폴더가 통째로 다시 쓰이면(공유 드라이브 동기화·폴더 복사·git 체크아웃·백업 복원) `
   +`그 안 파일 전부의 수정 시각이 그 순간으로 바뀝니다. `
   +`<b>그날 그만큼 일한 것이 아닐 수 있습니다</b> — 같은 폴더를 보는 사람은 모두 같은 봉우리가 생깁니다.</div>`
  ).join(""):"";}
 const max=Math.max(...rs.map(r=>r.mm||0),0.0001);
 $("rsrc").textContent=d.file?`${d.file} · ${rs.length}항목`:"결과 없음";
 const m=d.meta||{};
 const nb=m.mm_basis||m.night||{};
 $("metaper").textContent=m.period?`${m.period[0]} ~ ${m.period[1]} · 신호 ${m.signals}건`+(m.worked_h?` · 인정 근무 ${m.worked_h}h`:""):"분석 전";
 // MM 근거 — 사용자가 제출 전에 수치를 검증할 수 있어야 한다
 const mmEl=$("mmbasis");
 if(mmEl){
  const mo=Object.entries(m.mm_months||{}).sort();
  const bar=(pct)=>{const w=Math.min(100,Math.round((pct||0)/1.5));
   const col=(pct>=95?"#0f7a3d":(pct>=70?"#2a78d6":"#e08a00"));
   return `<svg width="120" height="12"><rect width="67" height="12" rx="2" fill="#eef0f3"/>
   <rect width="${w}" height="12" rx="2" fill="${col}"/><line x1="67" x2="67" y1="0" y2="12" stroke="#98a0a8"/></svg>`;};
  // 형태 방어 — 손으로 고친 mm_meta 나 구판이 남긴 값(anomalies 가 객체·null 항목, 숫자가 문자열)에
  // 여기서 죽으면 아래 mcount·mexcl·수집 현황까지 통째로 비어 보인다(실측: node 재현).
  const num=v=>{const n=Number(v);return Number.isFinite(n)?n:0;};
  const anoms=(Array.isArray(nb.anomalies)?nb.anomalies:[]).filter(a=>a&&typeof a==="object"&&!Array.isArray(a));
  const longd=(Array.isArray(nb.long_days)?nb.long_days:[]).filter(x=>x!=null);
  const absd=Array.isArray(nb.inferred_absence_dates)?nb.inferred_absence_dates:[];
  const fmtAnom=v=>v==null?"":(typeof v==="object"?JSON.stringify(v):String(v));
  // LM22 2차 — 측정 방식·신뢰도 등급·추가 보정·월별 PC 기록·가용 기준·비업무 제외 재산정.
  // 값이 있는 키만 그린다(구판 meta 는 조용히 생략). 키는 mm_basis → meta 최상위 → meta.mm_info 순으로 찾는다.
  const pick=k=>(nb[k]!=null?nb[k]:(m[k]!=null?m[k]:((m.mm_info&&typeof m.mm_info==="object")?m.mm_info[k]:undefined)));
  const obj=k=>{const v=pick(k);return (v&&typeof v==="object"&&!Array.isArray(v))?v:null;};
  const cnt=v=>Array.isArray(v)?v.length:((v&&typeof v==="object")?Object.keys(v).length:num(v));
  const cv=obj("coverage"),ms9=obj("measure"),cu=obj("cfg_used"),tu=obj("tool_usage");
  // 프로그램 사용 이력 — 참고 지표다(투입 MM·로드율 계산에 들어가지 않는다 — 문구로 못 박는다, 안 그러면 '투입 시간'으로 읽힌다).
  // 원천(출처 칸): 창기록(옛 샘플러 — 맨 앞 창 시간) · 실행기록(Windows 가 계정에 남긴 실행 흔적 스냅샷) · 파일(산출물 확장자).
  // 옛 meta(창기록만 — src·runs 칸 없음)도 그대로 그린다: 없는 칸은 '–'. 증가분을 모르면(스냅샷 1장) '누적 N' 으로 적는다.
  const tuP=(tu&&Array.isArray(tu.programs))?tu.programs.filter(x=>x&&typeof x==="object"&&x.name):[];
  const tuKind=(tu&&Array.isArray(tu.by_kind))?tu.by_kind.filter(x=>Array.isArray(x)&&x.length>=2&&num(x[1])>0):[];
  const tuKindN=(tu&&Array.isArray(tu.by_kind_n))?tu.by_kind_n.filter(x=>Array.isArray(x)&&x.length>=2):[];
  const tuIn=(tu&&Array.isArray(tu.inhouse))?tu.inhouse.filter(x=>x&&typeof x==="object"&&x.name):[];
  const tuSrc=(tu&&tu.sources&&typeof tu.sources==="object")?tu.sources:{};
  const tuReg=(tuSrc["실행기록"]&&typeof tuSrc["실행기록"]==="object")?tuSrc["실행기록"]:{};
  const tuCnt=(v,c)=>v==null?(c==null?"–":`<span class="dim">누적 ${num(c).toLocaleString()}</span>`):`${num(v).toLocaleString()}회`;
  const tuH=(v,c)=>v==null?(num(c)?`<span class="dim">누적 ${num(c).toFixed(1)}h</span>`:"–"):`${num(v).toFixed(1)}h`;
  const tuRow=x=>`<tr><td><b>${esc(x.name)}</b></td><td class="dim">${esc(x.kind||"")}${x.cat?" · "+esc(x.cat):""}</td>`
    +`<td class="dim">${esc((Array.isArray(x.src)?x.src:["창기록"]).join("·"))}</td>`
    +`<td>${tuCnt(x.runs,x.runs_cum)}</td><td>${tuH(x.focus_h,x.focus_h_cum)}</td>`
    +`<td class="dim">${esc(String(x.last_run||"").slice(0,16))||"–"}</td>`
    +`<td>${num(x.file_days)?num(x.file_days)+"일":"–"}</td>`
    +`<td>${num(x.hours)>=0.05?num(x.hours).toFixed(1)+"h":(num(x.bg_hours)>=1?`<span class="dim">배경 ${num(x.bg_hours).toFixed(0)}h</span>`:"–")}</td></tr>`;
  const tuWin=(Array.isArray(tuReg.window)&&tuReg.window.length===2)?tuReg.window:null;
  const tuBasis=(tuReg.basis==="delta"&&tuWin)?`실행 횟수·포커스 시간 = 실행 기록 스냅샷 ${esc(tuWin[0])}~${esc(tuWin[1])} 사이 증가분`
    :(tuReg.basis==="cum"?"실행 기록 스냅샷이 1장뿐이라 횟수·시간은 이 계정의 누적값입니다(다음 수집부터 기간 안 증가분이 보입니다)":"");
  const tuWhy=["실행기록","파일"].map(k=>(tuSrc[k]&&tuSrc[k].why)?`${k}: ${esc(tuSrc[k].why)}`:"").filter(Boolean)
    .concat(tuReg.track_off?["<b>앱 실행 추적이 꺼져 있습니다</b>(설정 > 개인 정보 > 일반 또는 회사 정책) — 실행 횟수가 늘지 않아 안 쓴 것처럼 보일 수 있습니다"]:[]);
  const tuInNote=(tuIn.length||num(tu&&tu.inhouse_hidden))?`<div class="note"><b>자체·프로토타입(추정)</b> ${tuIn.slice(0,10).map(x=>esc(x.name)+` <span class="dim">(${x.runs!=null?num(x.runs)+"회":"누적 "+num(x.runs_cum)+"회"}${x.last_run?" · "+esc(String(x.last_run).slice(0,10)):""})</span>`).join(" · ")}`
    +(num(tu.inhouse_hidden)?` · 이름을 가린 도구 ${num(tu.inhouse_hidden)}개`:"")
    +` <span class="dim">— 카탈로그에 없는 실행 파일이 사용자 폴더·다른 드라이브·네트워크에서 돈 것입니다(무료 휴대용 도구일 수도 있습니다 · config.programsExtra 로 이름표를 붙입니다)</span></div>`:"";
  const tuUnk=num(tu&&tu.unknown_n);       // 카탈로그 밖 '설치된' 프로그램 — 개수만(이름은 이 PC 의 data\\programs 스냅샷에만)
  const tuAmb=(tu&&Array.isArray(tu.ambiguous_files))?tu.ambiguous_files.filter(x=>Array.isArray(x)&&x.length>=2):[];
  const tuMore=(tuUnk||tuAmb.length||tuWhy.length)?`<div class="note dim">${[tuUnk?`카탈로그 밖 설치 프로그램 ${tuUnk}개(이름은 싣지 않습니다)`:"",
    tuAmb.length?`도구 불명 파일: ${tuAmb.slice(0,6).map(x=>esc(x[0])+" "+num(x[1])+"개").join(" · ")}`:""].concat(tuWhy).filter(Boolean).join(" / ")}</div>`:"";
  const toolNote=(tuP.length||tuIn.length)
    ?`<div class="note"><b>프로그램 사용(참고)</b> — ${esc((tu&&tu.note)||"참고 지표 — 투입 MM·로드율과 무관 · 실행 기록은 Windows 가 사용자 계정에 남긴 실행 흔적(관리자 권한 불필요)")}`
      +(tuKindN.length?` · 구분 ${tuKindN.map(x=>esc(x[0])+" "+num(x[1])+"개").join(" · ")}`:(tuKind.length?` · 구분 ${tuKind.map(x=>esc(x[0])+" "+num(x[1]).toFixed(1)+"h").join(" · ")}`:""))
      +(num(tu.solver_bg_h)>=1?` · 배경 솔버 가동 ${num(tu.solver_bg_h).toFixed(0)}h`:"")
      +(num(tu.unknown_h)>=1?` · 창기록 미상 ${num(tu.unknown_h).toFixed(0)}h`:"")
      +(tuBasis?`<br><span class="dim">${tuBasis}</span>`:"")
      +(tuP.length?`<table style="margin-top:4px"><tr><th>프로그램</th><th>구분·분류</th><th>출처</th><th>실행 횟수</th><th>포커스 시간</th><th>마지막 실행</th><th>파일 일수</th><th>창기록</th></tr>${tuP.slice(0,15).map(tuRow).join("")}</table>`:"")
      +(tuP.length>15?`<div class="dim">… 외 ${tuP.length-15}개</div>`:"")
      +`</div>`+tuInNote+tuMore
    :((tu&&tu.why)?`<div class="note"><b>프로그램 사용(참고)</b> <span class="dim">${esc(tu.why)}</span></div>`:"");
  const GC={reliable:["#0f7a3d","신뢰"],caution:["#c98a00","주의"],unreliable:["#c0122f","측정 불충분"]};
  const cvReasons=cv?((Array.isArray(cv.reasons)&&cv.reasons.length)?cv.reasons:(Array.isArray(cv.missing)?cv.missing:[])):[];
  const covBadge=(cv&&GC[cv.grade])?`<span style="display:inline-block;border:1px solid ${GC[cv.grade][0]};color:${GC[cv.grade][0]};border-radius:3px;padding:0 6px;font-size:11px;margin-left:4px" title="${esc(cvReasons.join(" · "))}">${GC[cv.grade][1]}</span>`:"";
  // LM30(2026-10-21) '표준일 추정' → 'PC 기록 없어 8시간 채움'(Windows가 지운 달 — LM30도 그 값을 근무로 쓴다)
  const measTxt=ms9?`샘플러 ${cnt(ms9.sampler_days)}일 / PC 하한 ${cnt(ms9.pc_floor_days)}일 / 흔적폭 ${cnt(ms9.trace_window_days)}일 / 출장 ${cnt(ms9.offsite_days)}일 / 수동 ${cnt(ms9.manual_days)}일`
    +(cnt(ms9.std_nopc_days)?` / PC 기록 없어 8시간 채움 ${cnt(ms9.std_nopc_days)}일`:"")+(cnt(ms9.hint_only_days)?` / 브라우저 기록만 ${cnt(ms9.hint_only_days)}일`:"")
    +(ms9.method?` (${esc(ms9.method)})`:""):"";
  const measNote=(measTxt||covBadge)?`<div class="note"><b>측정 방식</b> ${measTxt}${covBadge}${cvReasons.length?` — ${esc(cvReasons.slice(0,4).join(" · "))}`:""}${cv&&cv.grade==="unreliable"?" · <b style='color:#c0122f'>팀 비교에서 제외되는 결과입니다</b>":""}</div>`:"";
  const H=k=>pick(k)!=null;
  const extra=[];
  if(H("offsite_days"))extra.push(`종일 행사(출장·현장·교육) ${cnt(pick("offsite_days"))}일 ${num(pick("offsite_h")).toFixed(1)}h 인정`);
  if(H("manual_days"))extra.push(`수동 기록 ${cnt(pick("manual_days"))}일 ${num(pick("manual_h")).toFixed(1)}h`);
  if(H("dinner_deducted_h"))extra.push(`저녁 식사 차감 ${num(pick("dinner_deducted_h")).toFixed(1)}h`);
  if(H("flex_edge_h"))extra.push(`시차 근무 창 밖 인정 ${num(pick("flex_edge_h")).toFixed(1)}h`);
  if(H("sampler_bridge_h"))extra.push(`샘플러 공백 다리 ${num(pick("sampler_bridge_h")).toFixed(1)}h`);
  if(H("pc_record_missing_days"))extra.push(`PC 기록 결측 평일 ${cnt(pick("pc_record_missing_days"))}일(흔적 창 폴백 ${num(pick("trace_window_h")).toFixed(1)}h/${cnt(pick("trace_window_days"))}일)`);
  if(H("passive_capped_days"))extra.push(`수동 세션 상한 적용 ${cnt(pick("passive_capped_days"))}일`);
  if(H("weekend_pc_days"))extra.push(`주말 PC 창 인정 ${cnt(pick("weekend_pc_days"))}일`);
  const extraNote=extra.length?`<div class="note">추가 보정 — ${extra.join(" · ")}</div>`:"";
  // 야간 해석(솔버) 인정(S4-N1) — 밤새 돌린 해석의 실행 구간. 값이 0 이면 아무것도 그리지 않는다(구판 meta 호환)
  const snH=num(pick("sim_night_h")),snD=cnt(pick("sim_night_days"));
  const simNote=(snH||snD)?` · <b>야간 해석 인정 ${snH.toFixed(1)}h</b> · ${snD}일(상한 ${cnt(pick("sim_night_capped_days"))}일 · 재실행으로 상한 해제 ${cnt(pick("sim_night_unlocked_days"))}일 · PC 밖 ${num(pick("sim_night_remote_h")).toFixed(1)}h)`:"";
  const pcc=obj("pc_coverage_by_month");
  // LM30(2026-10-21) 40% 미만인 달 = PC 기록이 없는 평일을 하루 8시간으로 채운 달(예전 글은 그런 달에 PC 하한과 휴가 추정이 꺼진다고 적었다)
  const pccNote=pcc?`<div class="note">월별 PC 기록 — ${Object.entries(pcc).sort().map(([k,v])=>`${esc(k)} ${Math.round(num(v)*100)}%${num(v)<0.4?" <b style='color:#b54708'>[8시간 채움]</b>":""}`).join(" · ")} (유급휴가인 날은 빼고 셉니다 · 40% 미만인 달은 PC 기록이 없는 평일 중 메일·파일 흔적이 있는 날을 하루 8시간으로 채우고, 흔적 없는 날을 휴가로 보지 않습니다)</div>`:"";
  const fut=pick("future_days"),tf=pick("today_fraction");
  const futNote=(fut!=null||tf!=null)?`<div class="note">가용 기준 — ${fut!=null?`미래 평일 ${cnt(fut)}일은 가용에서 제외`:""}${(fut!=null&&tf!=null)?" · ":""}${tf!=null?`오늘은 ${Math.round(num(tf)*100)}% 만 가용(분석 시각${d.as_of?" "+esc(d.as_of):""} 기준 — 다시 분석하면 갱신)`:""}</div>`:"";
  const rhNote=m.rehours?`<div class="note"><b>비업무 제외 ${num(m.dropped_n)}건 · −${num(m.dropped_h).toFixed(1)}h</b> — 판정 후 시간을 다시 재어 투입 ${m.total_mm_before_rehours!=null?num(m.total_mm_before_rehours).toFixed(2)+" → ":""}${num(m.total_mm).toFixed(2)} MM 으로 갱신했습니다(버린 신호의 시간이 남은 행에 옮겨 붙지 않습니다)</div>`:"";
  // LM28(E) 시간 근거 한 줄 — 퇴근 후 미인정·시각 미상 발신·표준일 추정(PC 기록 없는 달)·브라우저 기록만 있는 평일·
  // AI 비업무 발신 시간 유지. 값이 있는 것만(mine 요약 줄·리포트 '산출 방식' 표 위 합계와 같은 숫자 — mm_basis 키)
  const tbBits=[];
  let tbStd=-1;
  if(num(pick("evening_missed_days"))>0)tbBits.push(`퇴근 후 미인정 ${num(pick("evening_missed_days"))}일·PC ${num(pick("evening_missed_pc_h")).toFixed(1)}h <span class="dim">(퇴근 뒤 PC 는 켜져 있었는데 내 흔적 없음)</span>`);
  if(num(pick("untimed_sends"))>0)tbBits.push(`시각 미상 발신 ${num(pick("untimed_sends"))}통 <span class="dim">(${num(pick("untimed_credit_h")).toFixed(1)}h 인정)</span>`);
  // LM30(2026-10-21) 출퇴근 추정이 투입을 맡았으면 하루 8시간으로 채운 날은 'LM29 방식 — 비교용' 줄(tbNoteAtt)에서 빼고 f8Note 로(LM30도 쓰는 값)
  if(num(pick("std_nopc_days"))>0){tbStd=tbBits.length;tbBits.push(`표준일 추정 ${num(pick("std_nopc_days"))}일 <span class="dim">(+${num(pick("std_nopc_h")).toFixed(1)}h — PC 기록 없는 달)</span>`);}
  if(num(pick("hint_only_days"))>0)tbBits.push(`브라우저 기록만 있는 평일 ${num(pick("hint_only_days"))}일`);
  if(num(pick("ai_n_time_kept"))>0)tbBits.push(`AI 비업무 발신 시간 유지 ${num(pick("ai_n_time_kept"))}건 <span class="dim">(과제 배분에서만 빼고 시간 근거로 남김)</span>`);
  const tbOf=bits=>bits.length?`<div class="note"><b>시간 근거</b> — ${bits.join(" · ")} <span class="dim">— 날짜별 근거는 리포트의 '산출 방식' 표</span></div>`:"";
  const tbNote=tbOf(tbBits),tbNoteAtt=tbOf(tbBits.filter((x,i)=>i!==tbStd));
  // LM30(2026-10-21) 달마다 근거(d.pc_months — 일수·건수만): 'PC 기록' 칸 · 하루 8시간으로 채운 달·발신 0건인 달·Windows 보관 주 수 경고
  const pcm=(d.pc_months&&typeof d.pc_months==="object")?d.pc_months:{};
  const pcmC=(pcm.cells&&typeof pcm.cells==="object")?pcm.cells:{};
  const pcmOn=Object.keys(pcmC).length>0;
  window.__pcCapped=!!pcm.capped;
  const pcmNote=(Array.isArray(pcm.lines)?pcm.lines:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note" style="color:#b54708;margin:0 0 6px"><b>${esc(x)}</b></div>`).join("");
  const f8Note=num(pcm.fill8)>0?`<div class="note"><b>PC 기록이 없어 하루 8시간으로 채운 평일 ${num(pcm.fill8)}일</b> — Windows가 PC를 켜고 끈 기록을 지운 날은 메일·파일 흔적이 있으면 하루 8시간(+저녁 흔적)으로 채워 근무로 씁니다(표의 'PC 기록' 칸 · 예전 판 기록을 가져오면 그 날을 PC 기록으로 다시 잽니다).</div>`:"";
  const win=v=>Array.isArray(v)?v.join("~"):(v==null?"":String(v));
  const cfgNote=cu?`<div class="note">산식 설정 — 표준 ${esc(cu.standardDayHours)}h · PC 하한 ${cu.usePcFloor===false?"끔":"켬"}${cu.pcFloorNeeds?`(${esc(cu.pcFloorNeeds)})`:""} · 주간 창 ${esc(win(cu.dayWindow))} · 점심 ${esc(win(cu.lunch))}${cu.dinner?` · 저녁 ${esc(win(cu.dinner))}`:""} · 미정 회의 ${esc(cu.tentativeMeetings||"")} · 공휴일 ${num(cu.holidays_n)}일${cu.offsiteAsWork===false?" · 종일 행사 미인정":""}${cu.samplerGapBridgeMin!=null?` · 샘플러 공백 다리 ${num(cu.samplerGapBridgeMin)}분`:""}${cu.noPcMonthDay?` · PC 기록 없는 달 ${cu.noPcMonthDay==="trace"?"흔적 창(예전)":"표준일 추정(기본)"}`:""} — 팀과 다르면 팀 취합에 '산식 설정 상이' 배지가 붙습니다</div>`:"";
  // LM30(2026-10-18) — 투입 MM 을 무엇으로 쟀나(출퇴근 추정 / LM29 방식)와 달마다 'LM29 방식' MM(같은 분모 — mm_months.mm_lm29)·차이를
  // 나란히. 출퇴근 추정이 투입을 맡았으면 초과근무·야근일·주말 근무는 그 값이고, PC 하한·점심·저녁 인정은 LM29 방식(비교용) 근거다.
  const att9=(nb.attendance&&typeof nb.attendance==="object")?nb.attendance:null;
  const attOn=!!(att9&&att9.used_for_mm)||!!(ms9&&ms9.method==="출퇴근 추정");
  const l29On=mo.some(([,v])=>v&&typeof v==="object"&&v.mm_lm29!=null);
  const sgn=x=>(x>0?"+":"")+x.toFixed(2);
  const l29Note=attOn?`<div class="note" style="margin:0 0 6px"><b>투입 MM은 출퇴근 추정(LM30 방식)으로 쟀습니다</b>${m.mm_lm29!=null?` — LM29 방식이었다면 ${num(m.mm_lm29).toFixed(2)} MM(차이 ${sgn(num(m.total_mm)-num(m.mm_lm29))} MM · 같은 분모)`:""}. 날짜별 출근·퇴근은 아래 '출퇴근·시간외 근무' 카드에 있습니다.</div>`
   :(att9?'<div class="note" style="margin:0 0 6px"><b>투입 MM은 LM29 방식으로 쟀습니다</b>(설정 attendance.useForMM 꺼짐) — 출퇴근 추정은 아래 카드에 참고로만 보입니다.</div>':"");
  // LM30(2026-10-21) 유급휴가 — 일하지 않은 날로 세지 않고 가용에서 뺀다(일수 = 달마다 가용에서 뺀 휴가 합 · 오늘까지 · 그중 휴가로 본
  // 평일 absent_inferred — 예전 결과에는 없다 · core\\attendance 머리말 22)
  const lvN=Math.round(mo.reduce((s,[,v])=>s+num(v&&v.absent),0)*10)/10;
  const lvInf=Math.round(mo.reduce((s,[,v])=>s+num(v&&v.absent_inferred),0)*10)/10;
  const lvTxt=`유급휴가 ${lvN}일${lvInf>0?`(휴가로 본 평일 ${lvInf}일 포함)`:""} — 법정 휴가라 일하지 않은 날로 세지 않습니다(투입 MM에 넣지 않고 가용에서 뺍니다)`;
  // 휴가로 본 날·휴가로 보지 않은 평일(d.leave_text — 날짜는 이 PC 화면에만 · 얼린 사본은 일수만 — freeze)
  const lvNote=(Array.isArray(d.leave_text)?d.leave_text:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note">${esc(x)}</div>`).join("");
  const otNote=attOn
   ?`<div class="note">${lvTxt} · 초과근무 ${num(nb.overtime_h).toFixed(0)}h(연장 + 휴일 — 출퇴근 추정)는
   상한 없이 그대로 반영(하루 24h 물리 한계만 · 이상치 ${anoms.length}일은 아래 표) · 20시 넘어 퇴근한 날 ${nb.night_days||0}일 · 주말·휴일 근무 ${nb.weekend_days||0}일 · 공휴일 ${nb.holidays||0}일 제외</div>`
   :`<div class="note">${lvTxt} · 초과근무 ${num(nb.overtime_h).toFixed(0)}h는
   상한 없이 그대로 반영(하루 24h 물리 한계만 · 이상치 ${anoms.length}일은 아래 표) · 야근일 ${nb.night_days||0}일(산출물이 찍힌 시각의 폭으로 산정 — 취침 중 켜둔 PC는 제외) ·
   주말 근무 ${nb.weekend_days||0}일 · PC가동 하한 보정 ${num(nb.pc_floor_h).toFixed(0)}h/${nb.pc_floor_days||0}일(흔적 있는 날의 주간 투입을 PC 가동시간까지 인정 — 저장 1번=1시간 과소 방지) · 공휴일 ${nb.holidays||0}일 제외</div>`;
  const fixLead=attOn?`<b>LM29 방식(비교용) 근거</b> — PC가동 하한 보정 ${num(nb.pc_floor_h).toFixed(0)}h/${nb.pc_floor_days||0}일 · 점심 차감`:"측정 보정 — 점심 차감";
  // LM30(2026-10-19) 시간외 나눠 보기 — 출퇴근 추정 합계(mm_basis.attendance)의 주말·휴일·저녁(19~22시)·야간을 달마다 칸으로, 분석 기간
  // 전체를 한 줄로(모두 투입에 든 시간) · 발신 흔적 빈 곳 경고(mm_basis.send_gap — 건수만 본 고정 문구)
  const ohNw=(cu&&Array.isArray(cu.nightWindow)&&cu.nightWindow.length===2)?cu.nightWindow.map(x=>String(x).slice(0,2)).join("~"):"22~06";
  const ohTxt=t=>(t&&typeof t==="object")?`주말·휴일 ${num(t.offday_h!=null?t.offday_h:t.holiday_h).toFixed(1)}h`
   +(t.evening_h!=null?` · 저녁(19~22시) ${num(t.evening_h).toFixed(1)}h`:"")+` · 야간(${ohNw}시) ${num(t.night_h).toFixed(1)}h`:"";
  const ohMo=(att9&&att9.months&&typeof att9.months==="object")?att9.months:{};
  const ohOn=Object.keys(ohMo).length>0;
  const ohC=k=>ohOn?`<td style="font-size:11px;color:#4a5159">${esc(ohTxt(ohMo[k]))||"–"}</td>`:"";
  const ohNote=(att9&&att9.total&&typeof att9.total==="object")?`<div class="note"><b>시간외(분석 기간)</b> — ${esc(ohTxt(att9.total))} — ${attOn?"모두 투입에 들어 있습니다":"참고(투입 MM은 LM29 방식으로 쟀습니다)"}</div>`:"";
  // LM30(2026-10-20) PC 사용 시간 줄(d.pc_usage_text — 분석 기간 PC를 쓴 시간·켜 둔 날 · attendance.pc_usage_lines 와 같은 글자)
  const puNote=(Array.isArray(d.pc_usage_text)?d.pc_usage_text:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note">${esc(x)}</div>`).join("");
  const sgw=(nb.send_gap&&typeof nb.send_gap==="object"&&nb.send_gap.warn&&nb.send_gap.text)?nb.send_gap:null;
  const sgNote=sgw?`<div class="note" style="color:#b54708;margin:0 0 6px"><b>${esc(sgw.text)}</b></div>`:"";
  mmEl.innerHTML=mo.length?sgNote+pcmNote+`<div class="note" style="margin:0 0 6px">${esc(nb.basis||"")} — 로드율 100% = 가용 시간을 꽉 채워 일함(회색 눈금). 야근하면 100%를 넘습니다.</div>`+l29Note+
   "<table><tr><th>월</th><th style='width:58px'>투입 MM</th>"+(l29On?"<th style='width:62px'>LM29 방식</th><th style='width:52px'>차이</th>":"")+"<th style='width:58px'>가용 MM</th><th style='width:62px'>로드율</th><th style='width:130px'></th><th>투입 시간</th>"+(ohOn?"<th>그중 주말·휴일·저녁·야간</th>":"")+(pcmOn?"<th title='PC를 켜고 끈 기록이 있는 평일 / 그 달 평일(오늘까지 · 유급휴가 뺌) · 가져온 기록 · 브라우저 기록만 · 하루 8시간으로 채운 날 · 휴가(하루 휴가·휴가로 본 날)'>PC 기록</th>":"")+"<th title='법정 휴가라 일하지 않은 날로 세지 않고 가용에서 뺀 날(반차는 0.5일)'>유급휴가</th><th>그 달 평일</th></tr>"+
   mo.map(([k,v0])=>{const v=(v0&&typeof v0==="object")?v0:{};const dl=num(v.mm)-num(v.mm_lm29);
    const l29c=l29On?(v.mm_lm29!=null?`<td>${num(v.mm_lm29).toFixed(2)}</td><td style="color:${dl>=0?"#0f7a3d":"#b54708"}">${sgn(dl)}</td>`:"<td>–</td><td>–</td>"):"";
    const pcmc=pcmOn?`<td style="font-size:11px;color:#4a5159">${esc(pcmC[k]||"–")}</td>`:"";
    return `<tr><td>${esc(k)}</td><td><b>${num(v.mm).toFixed(2)}</b></td>${l29c}<td>${num(v.avail_mm).toFixed(2)}</td>
    <td><b>${v.load_pct==null?"–":num(v.load_pct)+"%"}</b></td><td>${bar(num(v.load_pct))}</td>
    <td>${esc(v.worked)}h</td>${ohC(k)}${pcmc}<td>${esc(v.absent||0)}일</td><td>${esc(v.workdays)}일 = ${esc(v.capacity_h)}h</td></tr>`;}).join("")+
   `</table>${ohNote}${puNote}${otNote}${lvNote}${attOn?f8Note:""}
   <div class="note">${fixLead} ${num(nb.lunch_deducted_h).toFixed(0)}h · 저녁·새벽 가동 인정 ${num(nb.evening_credit_h).toFixed(1)}h · 주말 산출물 창 ${num(nb.weekend_window_h).toFixed(1)}h ·
   수동 흔적(수신·CC)만 있는 날 ${nb.floor_blocked_passive_days||0}일(하한 미적용 — 많으면 config.watchFolders 점검) · 미래 시각 신호 폐기 ${nb.future_signals_dropped||0}건 ·
   휴가로 본 평일 ${nb.inferred_absence_days||0}일(PC 기록도 흔적도 없는 평일 — 휴가로 보고 가용에서 뺐습니다${absd.length?": "+esc(absd.slice(0,12).join(", "))+(absd.length>12?" …":""):""})${simNote}</div>
   <div class="note">흔적 없는 평일 ${Math.max(0,num(nb.no_evidence_days)-num(nb.inferred_absence_days))}일(휴가로 본 날 빼고) — 이 수가 크면 수집이 덜 된 것입니다: Outlook을 켠 상태로 재실행하거나 config.watchFolders 를 확인하세요.</div>`
   +measNote+toolNote+rhNote+(attOn?tbNoteAtt.replace("<b>시간 근거</b>","<b>시간 근거(LM29 방식 — 비교용)</b>"):tbNote)+extraNote+pccNote+futNote+cfgNote
   +((Array.isArray(nb.config_warnings)&&nb.config_warnings.length)?`<div class="note" style="color:#b54708"><b>설정 경고 ${nb.config_warnings.length}건</b> — 잘못된 값은 기본값으로 대체했습니다: ${esc(nb.config_warnings.slice(0,6).join(" · "))}${nb.config_warnings.length>6?" …":""}</div>`:"")
   +(nb.utc_suspect?`<div class="note" style="color:#b54708"><b>메일 시각이 UTC 로 기록된 것 같습니다</b> — 낮 발신이 새벽 야근으로 잡힐 수 있으니 config.mm.mailTimeOffsetH(예: 9)를 확인하세요.</div>`:"")
   +(anoms.length?`<div class="note"><b>이상치 ${anoms.length}일</b> — PC 기록이 물리적으로 맞지 않아 보정한 날(투입을 자르지 않고 표시만 합니다)
    <table style="margin-top:4px"><tr><th style="width:90px">날짜</th><th>종류</th><th>원값 → 사용값</th></tr>${anoms.slice(0,30).map(a=>`<tr><td>${esc(a.date||"")}</td><td>${esc(a.kind||"")}</td><td style="color:#8b929b">${esc(fmtAnom(a.raw))} → ${esc(fmtAnom(a.used))}</td></tr>`).join("")}</table>${anoms.length>30?`<div class="note">… 외 ${anoms.length-30}일</div>`:""}</div>`:"")
   +(longd.length?`<div class="note"><b>16h 초과 ${longd.length}일</b>(자르지 않음 — 진짜 야근인지 확인하세요): ${longd.slice(0,20).map(x=>Array.isArray(x)?`${esc(x[0])}(${num(x[1]).toFixed(1)}h)`:esc(typeof x==="object"?JSON.stringify(x):String(x))).join(" · ")}${longd.length>20?" …":""}</div>`:"")
   :'<div class="note">분석을 실행하면 월별 투입·가용 MM과 로드율이 표시됩니다.</div>';
 }
 $("mcount").innerHTML=Object.entries(m.counted||{}).sort((a,b)=>b[1]-a[1])
  .map(([k,v])=>`<span class="src"><b>${esc(k)}</b> ${v}건</span>`).join("")||'<span class="note">분석을 실행하면 채워집니다</span>';
 // 제외 사유 풀이(마우스를 올리면) — 웹 경로 공지 메일은 '왜 뺐나' 가 이름만으로 안 읽힌다(진단 B)
 const exTip={"공지·근태 메일(제목 — 웹 경로는 단체발송 구분 불가)":"웹 경로(Outlook 웹 등)는 단체발송을 구분하지 못해, 회신하지 않은 근태·인사·부고·뉴스레터 등 강한 공지 제목은 업무 신호에서 뺐습니다"};
 $("mexcl").innerHTML=Object.entries(m.excluded||{})
  .map(([k,v])=>`<span class="src" style="border-color:#f0cdd5;color:#c0122f"${exTip[k]?` title="${esc(exTip[k])}"`:""}>제외: ${esc(k)} ${v}건</span>`).join("");
 const C={ok:"#0f7a3d",warn:"#c98a00",bad:"#c0122f",off:"#98a0a8"};
 $("src").innerHTML=d.sources.map(s=>`<span class="src"><span class="dot" style="background:${C[s.status]||C.off}"></span>
  <b>${s.name}</b> ${s.rows.toLocaleString()}건 · ${s.age}${s.hint?` <span style="color:${s.status==="warn"?"#c98a00":(s.status==="ok"?"#4a5159":"#c0122f")}">→ ${esc(s.hint)}</span>`:""}</span>`).join("");
 pcImpLoad(false);
 attLoad();
}
// ── 예전 판 PC 가동 기록 가져오기(LM30 2026-10-21) — /api/pc_import: 이 PC의 형제·사용자 폴더에서 찾은 예전 판 설치 폴더와 지난 가져오기.
//    [예전 판 PC 가동 기록 가져오기]·[이 폴더에서 가져오기](POST — 그 폴더는 읽기만 · 이 설치의 원장에만 더함). 분석이 도는 동안에는 단추를 끈다.
//    얼린 사본은 /api/pc_import 를 굽지 않아(막힘) 아무것도 그리지 않는다.
async function pcImpLoad(refresh){
 let g=null;
 try{g=await fetch("/api/pc_import"+(refresh?"?refresh=1":"")).then(r=>r.json());}catch(e){g=null;}
 pcImpRender(g);
}
function pcImpRender(g){
 const el=$("pcimp");if(!el)return;
 if(!g||g.ok!==true){el.innerHTML="";return;}
 const found=(Array.isArray(g.found)?g.found:[]).filter(x=>x&&typeof x==="object");
 const rec=(Array.isArray(g.record)?g.record:[]).filter(x=>x&&typeof x==="object");
 if(!found.length&&!rec.length&&!window.__pcCapped){el.innerHTML="";return;}
 const busy=!!window.__lmBusy;
 const rng=r=>(Array.isArray(r)&&r.length===2)?`${esc(r[0])}~${esc(String(r[1]).slice(5))}`:"없음";
 const todo=found.filter(x=>Number(x.new)>0);
 const line=x=>`<div class="note" style="margin:2px 0" title="${esc(x.folder||"")}"><b>${esc(x.name||"")}</b> — ${esc(x.who||"")} · PC 켜고 끈 기록 ${rng(x.events)} · 브라우저 기록 ${rng(x.hints)} · `
  +(Number(x.new)>0?`<b>새로 가져올 기록 ${Number(x.new).toLocaleString()}줄</b>`:"새로 가져올 기록 없음")+(x.done?` <span class="dim">(가져옴 ${esc(x.when||"")})</span>`:"")+`</div>`;
 el.innerHTML=`<div class="row" style="margin-top:10px;gap:6px;align-items:center;flex-wrap:wrap"><b style="font-size:12.5px">예전 판 PC 가동 기록 가져오기</b>`
  +`<button class="ghost" id="pcimpgo" title="찾은 예전 판 폴더의 PC 켜고 끈 기록을 이 설치로 가져옵니다 — 그 폴더는 읽기만 합니다">예전 판 PC 가동 기록 가져오기</button>`
  +`<button class="ghost" id="pcimprf" title="예전 판 폴더를 다시 찾습니다(형제 폴더·다운로드·바탕 화면·문서)">다시 찾기</button></div>`
  +(found.length?found.map(line).join(""):'<div class="note" style="margin:2px 0">이 PC의 형제 폴더·다운로드·바탕 화면·문서에서 예전 판(LM28·LM29 등) 설치 폴더를 찾지 못했습니다.</div>')
  +(rec.length?`<div class="note dim" style="margin:2px 0">지난 가져오기 — ${rec.slice(-4).map(r=>`${esc(r.name||"")} ${esc(r.when||"")} ${Number(r.added||0).toLocaleString()}줄`).join(" · ")}</div>`:"")
  +`<div class="row" style="margin-top:4px;gap:6px;align-items:center;flex-wrap:wrap"><input id="pcimpdir" type="text" spellcheck="false" autocomplete="off" maxlength="400" placeholder="다른 폴더(예: 다른 PC에서 복사해 온 data\\\\pc 폴더 · 예전 판 설치 폴더)" style="flex:1;min-width:260px;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px">`
  +`<button class="ghost" id="pcimpone" title="적은 폴더의 PC 켜고 끈 기록을 가져옵니다 — 이 PC 것이 아니면 data\\\\추가PC\\\\(그 PC 이름) 으로 들어가 함께 셉니다">이 폴더에서 가져오기</button></div>`
  +'<div class="note">가져온 뒤 [재분석만]을 누르면 PC 기록이 없던 달을 PC 기록으로 다시 잽니다. 가져온 기록으로 잰 값이 예전 추정(하루 8시간)보다 작은 날은 예전 값을 그대로 둡니다 — 가져오기는 시간을 줄이지 않습니다. 예전 폴더는 읽기만 하고, 가져온 기록은 이 PC에만 둡니다(팀 서버로 가지 않습니다).</div>';
 const go=$("pcimpgo"),rf=$("pcimprf"),one=$("pcimpone");
 if(go){go.disabled=busy||!todo.length;go.onclick=()=>pcImpRun({folders:todo.map(x=>x.folder)},todo.length+"곳");}
 if(rf){rf.disabled=busy;rf.onclick=()=>pcImpLoad(true);}
 if(one){one.disabled=busy;one.onclick=()=>{const v=String(($("pcimpdir")||{}).value||"").trim();
  if(!v){alert("가져올 폴더 경로를 적으세요 — 탐색기 주소 창의 경로를 그대로 붙여 넣으면 됩니다.");return;}
  pcImpRun({folder:v},"이 폴더");};}
}
async function pcImpRun(body,what){
 if(!confirm(`${what}의 PC 켜고 끈 기록을 이 설치로 가져옵니다.\\n· 그 폴더는 읽기만 합니다(지우거나 바꾸지 않습니다).\\n· 같은 기록은 한 번만 들어갑니다(여러 번 눌러도 됩니다).\\n· 가져온 뒤 [재분석만]을 누르면 그 달들을 다시 잽니다.\\n\\n계속할까요?`))return;
 ["pcimpgo","pcimprf","pcimpone"].forEach(id=>{const b=$(id);if(b)b.disabled=true;});
 let r=null,d={};
 try{r=await fetch("/api/pc_import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  d=await r.json().catch(e=>({ok:false,error:String(e)}));}catch(e){d={ok:false,error:String(e)};}
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");pcImpLoad(false);return;}
 const lines=(Array.isArray(d.results)?d.results:[]).map(x=>`· ${x.name}: `+(x.ok?`${Number(x.added||0).toLocaleString()}줄(${x.who})`:x.error)).join("\\n");
 alert((d.msg||d.error||"가져오지 못했습니다")+(lines?"\\n\\n"+lines:""));
 pcImpLoad(true);
}
// ── 출퇴근·시간외 근무 카드(LM30) — /api/attendance: 이 기간 report\\attendance_<기간>.json(날짜별 출근·퇴근 — 이 PC 전용) + mm_meta
//    합계(시각 없음). 결론 한 줄 · 재는 법 · 최근 8주 표 · 평소 시각 · 근태 기록 비교 · 최근 31일 날짜별 표(접힘).
//    얼린 사본에는 주·달 합계만 굳는다(freeze 가 날짜별 행·평소 시각을 뺀다 — a.frozen).
//    LM30(2026-10-19) +@ — 맨 위 +@ 줄(a.plus_text) · 설명 줄(a.plus_note) · 주 표 +@ 칸 · 날짜별 표의 근태 출근·퇴근·입실·퇴실·+@·까닭.
//    근태 기록과 견준 값(a.hr·rec)은 이 PC 화면에만 — 얼린 사본은 근태 없이 추정한 +@ 만(freeze._att_summary_only).
const AT_CONF={high:"높음",mid:"보통",low:"낮음"},AT_DOW=["일","월","화","수","목","금","토"];
async function attLoad(){
 gerpLoad();                                  // LM30(2026-10-19) GERP 근무 기록 줄(시험 기능) — 카드와 함께 그린다
 leaveLoad();                                 // LM30(2026-10-21) '휴가 날짜' 칸(유급휴가) — 카드와 함께 그린다
 let a=null;
 try{a=await fetch("/api/attendance").then(r=>r.json());}catch(e){a=null;}
 attRender(a);
}
function attRender(a){
 const el=$("atbody");if(!el)return;
 if(!a||!a.ok){el.innerHTML=`<div class="note">${esc((a&&a.hint)||"분석을 한 번 실행하면 보입니다.")}</div>`;return;}
 const n=v=>{const x=Number(v);return Number.isFinite(x)?x:0;};
 const h=v=>n(v).toFixed(1)+"h";
 const g=(a.agg&&typeof a.agg==="object")?a.agg:{};
 const cf=(a.cfg&&typeof a.cfg==="object")?a.cfg:{};
 const wH=n(cf.weekHours)||40,wM=n(cf.weekMaxHours)||52;
 const md=s=>String(s||"").slice(5).replace("-","/");
 // LM30(2026-10-19) +@ — 근태 기록 = 확실히 일한 부분, +@ = 그 밖에서 LM이 찾은 근무. a.hr(이 PC의 근태 기록과 견준 칸)이 있으면
 // 주 +@ = 근태와 견준 것 + 기록 없는 날의 추정(plus_all_h), 없으면(근태를 못 읽음·얼린 사본) 추정(plus_est_h — 없으면 연장 + 휴일)
 const hr=(a.hr&&typeof a.hr==="object")?a.hr:null;
 const hw=(hr&&hr.weeks&&typeof hr.weeks==="object")?hr.weeks:{};
 const est=w=>(w.plus_est_h!=null?n(w.plus_est_h):n(w.ext_h)+n(w.holiday_h));
 const wPlus=(k,w)=>{const x=(hw[k]&&typeof hw[k]==="object")?hw[k]:null;
  if(x&&x.plus_all_h!=null)return `<td title="근태 기록과 견준 것 ${h(x.plus_h)} · 기록 없이 추정한 것 ${h(x.plus_est_h)}"><b>${h(x.plus_all_h)}</b></td>`;
  return `<td title="근태 기록 없이 추정(하루 ${n(cf.standardDayHours)||8}시간 넘은 시간·휴일 근무)">${h(est(w))}</td>`;};
 const wks=Object.entries((g.weeks&&typeof g.weeks==="object")?g.weeks:{}).sort().slice(-8).reverse();
 const wTbl=wks.length?`<table style="margin-top:6px"><tr><th>주(월~일)</th><th>근무</th><th>연장</th><th>야간</th><th>휴일</th><th>PC 밖</th><th>${wH}시간 초과</th><th>${wM}시간</th><th>+@</th></tr>`
  +wks.map(([k,w0])=>{const w=(w0&&typeof w0==="object")?w0:{};
   return `<tr><td>${esc(md(w.from))}~${esc(md(w.to))}${w.partial?' <span class="state">일부</span>':""}</td><td><b>${h(w.work_h)}</b></td><td>${h(w.ext_h)}</td><td>${h(w.night_h)}</td><td>${h(w.holiday_h)}</td><td>${h(w.offpc_h)}</td><td>${n(w.over40_h)>0?h(w.over40_h):"–"}</td><td>${w.over52?'<b style="color:#c0122f">넘음</b>':"–"}</td>${wPlus(k,w)}</tr>`;}).join("")+"</table>"
  :'<div class="note">주별 합계가 아직 없습니다.</div>';
 const ds=Object.entries((a.days&&typeof a.days==="object")?a.days:{}).sort().reverse();
 const span=(t0,t1,d1)=>(t0||"?")+"~"+(n(d1)>0?"다음 날 ":"")+(t1||"?");
 const recCell=rc=>{if(!rc)return "–";if(rc.in&&rc.out)return span(rc.in,rc.out,rc.out_day);
  if(n(rc.leave)>=1)return "휴가";if(rc.missing)return "기록 없음";return "시각 없음";};
 const dRow=([iso,r0])=>{const r=(r0&&typeof r0==="object")?r0:{};const dt=new Date(iso+"T00:00:00");
  const lv=r.leave?((n(r.leave_day)>0?"다음 날 ":"")+r.leave):"–";
  const rc=(r.rec&&typeof r.rec==="object")?r.rec:null;
  const gt=rc&&(rc.gate_in||rc.gate_out)?span(rc.gate_in,rc.gate_out,rc.gate_out_day):"–";
  const pl=(r.plus&&typeof r.plus==="object")?r.plus:{};
  const pv=n(pl.h)>0?`<b>${h(pl.h)}</b>${pl.est?' <span class="state">추정</span>':""}`:"–";
  return `<tr><td>${esc(iso.slice(5))}(${AT_DOW[dt.getDay()]||""})</td><td>${esc(r.arrive||"–")}</td><td>${esc(lv)}</td><td><b>${h(r.work_h)}</b></td><td>${h(r.ext_h)}</td><td>${h(r.night_h)}</td><td>${h(r.holiday_h)}</td><td>${h(r.offpc_h)}</td><td>${h(r.lm29_h)}</td><td style="font-size:11px;color:#4a5159">${esc(r.why||"")}</td><td>${esc(AT_CONF[r.conf]||"–")}</td><td>${esc(recCell(rc))}</td><td>${esc(gt)}</td><td>${pv}</td><td style="font-size:11px;color:#4a5159">${esc(pl.why||"")}</td></tr>`;};
 const dTbl=a.frozen?'<div class="note">날짜별 출근·퇴근 시각과 근태 기록은 본인 PC의 화면에서만 보입니다 — 이 사본에는 주·달 합계만 담았습니다.</div>'
  :(ds.length?`<details style="margin:10px 0 0"><summary>최근 ${n(a.recent_days)||31}일 날짜별 출근·퇴근 <span class="state">${ds.length}일 · 최신순 · 근거 = 출근 쪽 → 퇴근 쪽 · +@ = 근태 기록 밖 근무</span></summary><div class="body"><div style="overflow-x:auto"><table><tr><th>날짜(요일)</th><th>출근</th><th>퇴근</th><th>근무</th><th>연장</th><th>야간</th><th>휴일</th><th>PC 밖</th><th>LM29 방식</th><th>근거</th><th>확실성</th><th>근태 출근·퇴근</th><th>입실·퇴실</th><th>+@</th><th>+@ 까닭</th></tr>${ds.map(dRow).join("")}</table></div></div></details>`
   :'<div class="note">최근 31일에 근무로 센 날이 없습니다.</div>');
 // LM30(2026-10-19) 발신 흔적 빈 곳 경고(a.send_gap_text — 건수만 본다) · 시간외 나눠 보기 한 줄(a.offhours_text — 분석 기간 합계)
 el.innerHTML=(a.send_gap_text?`<div class="note" style="color:#b54708;margin:0 0 4px"><b>${esc(a.send_gap_text)}</b></div>`:"")
  // LM30(2026-10-21) 달마다 근거 — 하루 8시간으로 채운 달·발신 0건인 달·Windows 보관 주 수(a.pc_months_text — 'MM 산정 근거' 카드와 같은 글자)
  +(Array.isArray(a.pc_months_text)?a.pc_months_text:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note" style="color:#b54708;margin:0 0 4px"><b>${esc(x)}</b></div>`).join("")
  +(a.plus_text?`<div style="font-size:13.5px;margin-bottom:2px"><b>${esc(a.plus_text)}</b></div>`:"")
  +`<div style="font-size:13px;margin-bottom:2px"><b>${esc(a.headline||"")}</b></div>`
  // LM30(2026-10-21) 유급휴가 — 휴가로 본 날·휴가로 보지 않은 평일(a.leave_lines — 날짜는 이 PC 화면에만 · 얼린 사본은 일수만)
  +(Array.isArray(a.leave_lines)?a.leave_lines:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note" style="margin-top:2px">${esc(x)}</div>`).join("")
  +(a.offhours_text?`<div class="note" style="margin-top:2px"><b>시간외(분석 기간)</b> — ${esc(a.offhours_text)}</div>`:"")
  +(Array.isArray(a.pc_usage_text)?a.pc_usage_text:[]).filter(x=>typeof x==="string"&&x).map(x=>`<div class="note" style="margin-top:2px">${esc(x)}</div>`).join("")
  +(a.plus_note?`<div class="note" style="margin-top:2px">${esc(a.plus_note)}</div>`:"")
  +`<div class="note" style="margin-top:2px">${a.used_for_mm?"<b>이 근무시간으로 투입 MM을 쟀습니다.</b>":"<b>투입 MM은 LM29 방식으로 쟀습니다</b> — 이 카드는 참고용입니다(설정 attendance.useForMM)."} ${esc(a.rule||"")}</div>`
  +wTbl
  +(a.frozen||!a.usual_text?"":`<div class="note">${esc(a.usual_text)}</div>`)
  +`<div class="note">${esc(a.records_text||"")}</div>`
  +dTbl
  +'<div class="note">날짜별 출근·퇴근 시각과 근태 기록(GERP 포함)에서 나온 값은 이 PC에만 있습니다. 팀 서버에는 주·달 합계 시간만 올라갑니다(근태 기록 없이 잰 값).</div>';
 const st=$("atstate");
 if(st&&Array.isArray(a.period)&&a.period[0])st.textContent=`${a.period[0]} ~ ${a.period[1]||""} · 날짜별 시각은 이 PC에만`;
}
// ── 휴가 날짜(LM30 2026-10-21 — 유급휴가 · core\\attendance 머리말 22) — /api/leave_days: 직접 넣은 휴가 날짜(data\\근태\\휴가_직접입력.csv
//    — 이 PC 에만). 저장하면 다음 [분석 실행]·[재분석만]이 그 날을 휴가로 본다(일하지 않은 날로 세지 않고 가용에서 뺀다). 얼린 사본은
//    /api/leave_days 를 굽지 않아(막힘) 칸을 그리지 않는다. 작업이 도는 동안에는 [저장]을 끈다(poll — window.__lmBusy · 서버도 409).
async function leaveLoad(){
 let v=null;
 try{v=await fetch("/api/leave_days").then(r=>r.json());}catch(e){v=null;}
 leaveRender(v);
}
function leaveRender(v){
 const el=$("atleave");if(!el)return;
 if(!v||v.ok!==true||typeof v.text!=="string"){el.innerHTML="";return;}
 el.innerHTML=`<div class="row" style="margin-top:10px;gap:6px;align-items:flex-start;flex-wrap:wrap"><b style="font-size:12.5px">휴가 날짜</b>`
  +`<textarea id="lvtext" rows="2" spellcheck="false" maxlength="8000" placeholder="예: 2026-10-05, 10-06~10-08, 10/15 반차" style="flex:1;min-width:260px;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px">${esc(v.text)}</textarea>`
  +`<button class="ghost" id="lvsave" title="적은 날짜를 이 PC에 저장합니다 — 다음 [분석 실행]·[재분석만]부터 그 날을 휴가로 봅니다">저장</button>`
  +`<span class="state" id="lvmsg">${v.n?`저장한 날 ${v.n}일(휴가 ${v.days}일)`:""}</span></div>`
  +`<div class="note">유급휴가(연차·반차·병가 등)를 쓴 날을 적으면 그 날을 휴가로 봅니다 — 법정 휴가라 일하지 않은 날로 세지 않고, 투입 MM에 넣지 않고 가용에서 뺍니다. 달력·근태 기록에 없는 휴가만 적으면 됩니다. 반나절이면 날짜 뒤에 '반차'를 붙이고, 이어진 날은 '~'로 적습니다. 저장한 뒤 [재분석만]이나 [분석 실행]을 누르면 반영됩니다. 날짜는 이 PC의 ${esc(v.file||"")}에만 두고 팀 서버·공유폴더로 보내지 않습니다(팀에는 가용 MM 안의 일수만 갑니다).</div>`;
 const b=$("lvsave");if(b){b.disabled=!!window.__lmBusy;b.onclick=leaveSave;}
}
async function leaveSave(){
 const t=$("lvtext");if(!t)return;
 const b=$("lvsave");if(b)b.disabled=true;
 let r=null,d={};
 try{r=await fetch("/api/leave_days",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:t.value})});
  d=await r.json().catch(e=>({ok:false,error:String(e)}));}catch(e){d={ok:false,error:String(e)};}
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");if(b)b.disabled=!!window.__lmBusy;return;}
 if(!d.ok){alert("휴가 날짜를 저장하지 않았습니다 — "+(d.error||""));if(b)b.disabled=!!window.__lmBusy;return;}
 leaveRender(d);
 const m=$("lvmsg");if(m)m.textContent=d.msg||"저장했습니다";
}
// ── GERP 근무 기록(LM30 2026-10-19 시험 기능 — config attendance.gerp, 기본 꺼짐) — /api/gerp: 켜졌을 때만 [GERP 열기(직접 로그인)]·
//    [GERP 근무 기록 읽기]와 상태 한 줄. 얼린 사본은 /api/gerp 를 굽지 않아(막힘) 아무것도 그리지 않는다.
//    작업이 도는 동안에는 단추를 끈다(poll — window.__lmBusy). 로그인은 사람이 그 Edge 창에서 — 이 화면은 아이디·비밀번호를 받지 않는다.
//    LM30(2026-10-19) 카드에서 켜고 끈다 — 꺼져 있으면 주소 칸(저장한 주소로 채움) + [켜기], 켜져 있으면 저장한 주소(호스트만)·[주소 바꾸기]·
//    [끄기](POST /api/gerp_config — config\\config.json 의 attendance.gerp.enabled·url 만 · 이 PC 의 개인 설정).
async function gerpLoad(){
 let g=null;
 try{g=await fetch("/api/gerp").then(r=>r.json());}catch(e){g=null;}
 gerpRender(g);
}
function hrSync(g){
 // LM30(2026-10-19) 옵션 줄의 'HR 근무 기록(GERP)' 칸 — 카드와 같은 설정(attendance.gerp.enabled)을 보인다. /api/gerp 를 못 읽는 화면
 // (얼린 사본·파일로 연 화면)에서는 숨긴다. 작업이 도는 동안에는 끈다(poll 도 같은 값으로 끈다).
 const l=$("hronl"),c=$("hron");if(!l||!c)return;
 const ok=!!(g&&g.ok===true&&typeof g.enabled==="boolean");
 l.style.display=ok?"":"none";
 if(ok){c.checked=!!g.enabled;c.disabled=!!window.__lmBusy;}
}
async function hrToggle(){
 // 켜기: 저장한 주소가 없거나 틀렸으면 한 번 묻는다(주소는 이 PC의 설정에만) · 끄기: 카드의 [끄기]와 같다(확인 창). 끝나면 서버 값으로 다시 맞춘다.
 const c=$("hron");if(!c)return;
 if(c.checked){
  let g=null;try{g=await fetch("/api/gerp").then(r=>r.json());}catch(e){g=null;}
  let url=(g&&g.url)||"";
  if(!(g&&g.url_ok)){
   url=prompt("GERP 근무시간 현황 화면 주소를 붙여 넣으세요 — 로그인한 브라우저의 주소 창에서 복사합니다.\\n(주소는 이 PC의 설정에만 둡니다)",url)||"";
   if(!url.trim()){gerpLoad();return;}
  }
  await gerpCfg(true,url);
 }else{
  await gerpCfg(false);
 }
 gerpLoad();
}
{const c=$("hron");if(c)c.onchange=hrToggle;}
function gerpRender(g){
 hrSync(g);
 const el=$("atgerp");if(!el)return;
 if(!g||g.ok!==true||typeof g.enabled!=="boolean"){el.innerHTML="";return;}
 const busy=!!window.__lmBusy;
 const urlBox=`<input id="gerpurl" type="text" spellcheck="false" autocomplete="off" maxlength="1000" placeholder="GERP 근무시간 현황 화면 주소(https:&#47;&#47;…)" value="${esc(g.url||"")}" style="flex:1;min-width:260px;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px">`;
 if(!g.enabled){
  el.innerHTML=`<div class="row" style="margin-top:10px;gap:6px;align-items:center;flex-wrap:wrap"><b style="font-size:12.5px">GERP 근무 기록 읽기(시험 기능)</b>`+urlBox
   +`<button class="ghost" id="gerpon" title="이 주소로 GERP 근무 기록 읽기를 켭니다 — 주소는 이 PC의 config\\\\config.json 에만 둡니다">켜기</button></div>`
   +`<div class="note">${esc(g.off_text||"")}</div>`;
  $("gerpon").disabled=busy;
  $("gerpon").onclick=()=>gerpCfg(true,$("gerpurl").value);
  return;
 }
 el.innerHTML=`<div class="row" style="margin-top:10px;gap:6px;align-items:center;flex-wrap:wrap"><b style="font-size:12.5px">GERP 근무 기록(시험)</b>`
  +(g.host?`<span class="state" title="저장한 GERP 주소의 호스트만 보입니다(주소는 이 PC에만 둡니다)">주소 ${esc(g.host)}</span>`:"")
  +`<button class="ghost" id="gerpopen" title="전용 Edge 창에 GERP 근무 현황 화면을 엽니다 — 그 창에서 직접 로그인하세요(이 프로그램은 아이디·비밀번호를 넣거나 저장하지 않습니다)">GERP 열기(직접 로그인)</button>`
  +`<button class="ghost" id="gerpread" title="로그인해 둔 GERP 화면에서 지난 날의 근무 기록을 읽어 이 PC에 모읍니다 — 로그아웃돼 있으면 읽지 않습니다">GERP 근무 기록 읽기</button>`
  +`<button class="ghost" id="gerpchg" title="GERP 근무시간 현황 화면 주소를 바꿉니다">주소 바꾸기</button>`
  +`<button class="ghost" id="gerpoff" title="GERP 근무 기록 읽기를 끕니다 — 모아 둔 기록과 주소는 그대로 둡니다">끄기</button>`
  +`<span class="note" id="gerpst" style="margin:0">${esc(g.text||"")}</span></div>`
  +`<div class="row" id="gerpedit" style="display:${g.url_ok?"none":"flex"};margin-top:4px;gap:6px;align-items:center;flex-wrap:wrap">`+urlBox
  +`<button class="ghost" id="gerpsave">주소 저장</button></div>`
  +'<div class="note">GERP 기록은 확실히 일한 부분으로 봅니다. 그 밖에서 LM이 찾은 근무(+@)는 위 +@ 줄과 표에 보입니다 — 읽은 뒤 [재분석만]으로 다시 분석하면 반영됩니다. GERP를 읽지 못하거나 로그아웃돼 있어도 +@는 하루 8시간 넘은 시간·휴일 근무로 추정해 보입니다. GERP에서 읽은 기록과 그것으로 센 값은 이 PC에만 두고 팀 서버·공유폴더로 보내지 않습니다(GERP의 휴가는 유급휴가 일수로만 가용 MM에 들어갑니다 — 날짜는 이 PC에만).</div>';
 ["gerpopen","gerpread","gerpchg","gerpoff","gerpsave"].forEach(id=>{const b=$(id);if(b)b.disabled=busy;});
 $("gerpopen").onclick=gerpOpen;$("gerpread").onclick=gerpRead;
 $("gerpchg").onclick=()=>{const e=$("gerpedit");if(e)e.style.display=(e.style.display==="none")?"flex":"none";};
 $("gerpoff").onclick=()=>gerpCfg(false);
 $("gerpsave").onclick=()=>gerpCfg(true,$("gerpurl").value);
}
async function gerpCfg(on,url){
 // LM30(2026-10-19) [켜기]·[끄기]·[주소 저장] — POST /api/gerp_config {enabled, url?}. 주소를 비워 켜려 하면 묻기만 한다(서버도 같은 검사).
 const body={enabled:!!on};
 if(url!==undefined)body.url=String(url||"").trim();
 if(on&&url!==undefined&&!body.url){alert("GERP 근무시간 현황 화면 주소를 넣으세요 — 로그인한 브라우저의 주소 창에서 복사합니다.");return;}
 if(!on&&!confirm("GERP 근무 기록 읽기를 끌까요?\\n· 모아 둔 기록(data\\\\근태\\\\gerp.csv)과 주소는 그대로 둡니다 — 다시 켜면 이어서 읽습니다."))return;
 ["gerpon","gerpoff","gerpsave","gerpchg"].forEach(id=>{const b=$(id);if(b)b.disabled=true;});
 let r=null,d={};
 try{r=await fetch("/api/gerp_config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  d=await r.json().catch(e=>({ok:false,error:String(e)}));}catch(e){d={ok:false,error:String(e)};}
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");gerpLoad();return;}
 if(d.gerp)gerpRender(d.gerp);else gerpLoad();
 if(!d.ok){alert("GERP 설정을 바꾸지 못했습니다 — "+(d.error||""));return;}
 if(on)alert((d.msg||"GERP 근무 기록 읽기를 켰습니다")+".\\n\\n[GERP 열기(직접 로그인)]로 그 창에서 로그인한 뒤 [GERP 근무 기록 읽기]를 누르세요.");
}
async function gerpOpen(){
 const b=$("gerpopen");if(b)b.disabled=true;
 let r=null,d={};
 try{r=await fetch("/api/gerp_open",{method:"POST"});d=await r.json().catch(e=>({ok:false,error:String(e)}));}catch(e){d={ok:false,error:String(e)};}
 if(b)b.disabled=!!window.__lmBusy;
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");return;}
 alert(d.ok?(d.msg||"전용 Edge 창에 GERP 화면을 열었습니다."):("GERP 화면을 열지 못했습니다 — "+(d.error||"")));
}
async function gerpRead(){
 if(!confirm("전용 Edge 창에서 GERP 근무시간 현황 화면을 읽습니다.\\n· 로그인은 하지 않습니다 — 먼저 [GERP 열기(직접 로그인)]로 그 창에서 로그인해 두세요.\\n· 로그아웃돼 있으면 읽지 않고 끝납니다.\\n· 읽은 기록과 그것으로 센 값(+@)은 이 PC에만 둡니다 — 팀 서버·공유폴더로 보내지 않습니다.\\n\\n계속할까요?"))return;
 const b=$("gerpread");if(b)b.disabled=true;
 $("state").textContent="GERP 근무 기록 읽는 중… (1~5분)";
 if(!timer){timer=setInterval(poll,1000);}
 let r=null,d={};
 try{r=await fetch("/api/gerp_read",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({from:$("from").value,to:$("to").value})});
  d=await r.json().catch(e=>({ok:false,error:String(e)}));}catch(e){d={ok:false,error:String(e)};}
 $("state").textContent="대기 중";
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");gerpLoad();return;}
 if(d.gerp)gerpRender(d.gerp);else gerpLoad();
 const st=(d.gerp&&d.gerp.status)||{};
 const head=st.kind==="ok"?"GERP 근무 기록을 읽었습니다.":(st.kind==="logged_out"?"GERP에 로그인되어 있지 않아 읽지 않았습니다.":"GERP 근무 기록을 읽지 못했습니다.");
 const tail=st.kind==="ok"?"\\n\\n[재분석만]으로 다시 분석하면 +@(근태 기록 밖 근무)에 반영됩니다.":(st.kind==="logged_out"?"\\n\\n[GERP 열기(직접 로그인)]로 그 창에서 로그인한 뒤 다시 누르세요.":"");
 alert(head+"\\n"+((d.gerp&&d.gerp.text)||d.error||"")+tail);
}
// ── 과제 지정 카드 ──
let PJ=[];
function pjRender(){
 $("pjtbl").innerHTML="<tr><th style='width:160px'>프로젝트명</th><th style='width:220px'>식별 키워드 (쉼표 구분)</th><th>관련 내용 (설명 — 유사성 재분류에 사용)</th><th style='width:40px'></th></tr>"+
  (PJ.length?PJ.map((p,i)=>`<tr>
   <td><input data-i="${i}" data-k="name" value="${esc(p.name)}" style="width:100%;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px"></td>
   <td><input data-i="${i}" data-k="match" value="${esc((p.match||[]).join(", "))}" style="width:100%;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px"></td>
   <td><input data-i="${i}" data-k="desc" value="${esc(p.desc||"")}" style="width:100%;border:1px solid #c9cfd8;border-radius:4px;padding:4px 6px;font:inherit;font-size:12px"></td>
   <td><button class="ghost" data-del="${i}" style="padding:3px 8px">✕</button></td></tr>`).join("")
  :"<tr><td colspan=4 style='color:#8b929b'>지정된 프로젝트가 없습니다 — AI 자동 발견만 사용 중. [+ 프로젝트 추가]로 지정할 수 있습니다.</td></tr>");
 $("pjtbl").querySelectorAll("input").forEach(el=>el.onchange=()=>{
  const p=PJ[+el.dataset.i];
  if(el.dataset.k==="match")p.match=el.value.split(",").map(x=>x.trim()).filter(Boolean);
  else p[el.dataset.k]=el.value.trim();});
 $("pjtbl").querySelectorAll("[data-del]").forEach(b=>b.onclick=()=>{PJ.splice(+b.dataset.del,1);pjRender();});
}
async function pjLoad(){try{PJ=(await fetch("/api/projects").then(r=>r.json())).projects||[];}catch(e){PJ=[];}pjRender();}
async function pjSave(){
 const r=await fetch("/api/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({projects:PJ})});
 const d=await r.json();PJ=d.projects||PJ;pjRender();return d;}
$("pjadd").onclick=()=>{PJ.push({name:"",match:[],desc:""});pjRender();
 const inp=$("pjtbl").querySelector(`input[data-i="${PJ.length-1}"][data-k="name"]`);if(inp)inp.focus();};
$("pjsave").onclick=async()=>{await pjSave();$("pjmsg").textContent="저장됨 — 다음 분석부터 체계에 반영";};
$("pjretag").onclick=async()=>{
 await pjSave();$("pjmsg").textContent="재분류 중…";
 const d=await fetch("/api/retag",{method:"POST"}).then(r=>r.json());
 if(!d.ok){$("pjmsg").textContent=d.error==="no signals"?"분석 결과가 아직 없습니다 — 먼저 [분석 실행]":(d.error==="no projects"?"지정된 프로젝트가 없습니다":(d.error==="not judged"?"AI 판정 전입니다 — 'AI 판정' 체크로 분석 후 재분류 가능":(d.error==="busy"?"다른 작업이 실행 중입니다":"재분류 실패")));return;}
 const det=Object.entries(d.by||{}).map(([k,v])=>`${k} ${v}건`).join(" · ");
 $("pjmsg").textContent=d.retagged?`재분류 ${d.retagged}건 (${det}) — 화면 갱신됨`:"유사한 신호 없음 — 변경 0건";
 loaded={};refresh();};
pjLoad();

$("go").onclick=async()=>{
 const b={from:$("from").value,to:$("to").value,ai:$("ai").checked,skip:$("skip").checked};
 if(!b.from||!b.to){alert("기간을 선택하세요");return;}
 const r=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
 if(r.status===409){alert(await busyMsg(r,"이미 실행 중입니다"));return;}
 $("go").disabled=true;$("collect2").disabled=true;timer=setInterval(poll,1000);poll();
};
$("stop").onclick=async()=>{
 if(!confirm("실행 중인 분석을 중단할까요? 지금까지 수집·판정된 결과는 보존됩니다."))return;
 $("stop").disabled=true;
 await fetch("/api/stop",{method:"POST"});
 $("stop").disabled=false;$("stop").style.display="none";
 if(timer){clearInterval(timer);timer=null;}
 loaded={};refresh();poll();tuLoad();
};
// ── 팀 취합 업로드 카드 — LM28: [분석 실행] 끝에 자동 보고(run.py) · 못 보낸 것은 대기 → 닿는 망에서 버튼으로 ──
let TU={pending:[],sent:[],url:"",share:""};
function tuBusy(on,msg){
 ["tusend","tufolder","tuping","teamup","tr_send"].forEach(id=>{const b=$(id);if(b)b.disabled=on;});
 $("tumsg").textContent=msg||"";
}
async function tuLoad(){
 const d=await fetch("/api/teamupload").then(r=>r.json()).catch(()=>null);
 if(!d||!d.ok||!d.pending){
  // 모를 때 '없음'이라고 하면 보낼 것이 있는데도 못 보내게 된다 — 확인 실패라고 말한다
  const el=$("tupend");
  if(el)el.innerHTML='<div class="note" style="color:#c0122f">대기 목록을 확인하지 못했습니다'
   +((d&&d.error)?` — ${esc(d.error)}`:"")+'. [묶음 폴더 열기]로 report\\\\upload_pending 을 직접 확인하세요.</div>';
  if(d)tuFill(d);
  TU={pending:[],sent:[],url:(d&&d.url)||"",share:(d&&d.share)||"",
      unknown:true,error:(d&&d.error)||"통신 실패"};
  return;
 }
 TU=d;
 tuFill(d);
 const p=d.pending||[];
 const av=d.available||[];
 $("tuavail").innerHTML=(!p.length&&av.length)
  ?`<div class="note" style="color:#8a5a00">분석 결과는 있는데 보낼 묶음이 아직 없습니다 (${av.length}개 기간)
    — <b>[지금 묶음 만들기]</b>를 누르면 그 결과로 묶음을 만듭니다. 예전 버전으로 분석했으면 이 경우입니다.</div>`
  :(av.length?`<div class="note">아직 묶지 않은 기간 ${av.length}개 — [지금 묶음 만들기]로 추가할 수 있습니다.</div>`:"");
 $("tubuild").style.display=av.length?"":"none";
 $("tupend").innerHTML=p.length?
  '<table><tr><th>기간</th><th style="width:112px">준비된 시각</th><th style="width:52px">파일</th><th style="width:64px">크기</th><th style="width:64px">투입 MM</th><th style="width:52px"></th></tr>'
  +p.map(x=>`<tr><td>${esc((x.period&&x.period.length===2)?x.period.join(" ~ "):(x.tag||x.file))}
   ${(x.blocked&&x.blocked.length)?`<div class="note" style="color:#c0122f;margin:2px 0 0">보낼 수 없음: ${esc(x.blocked[0])}</div>`:""}</td>
   <td>${esc(x.built||"")}</td><td>${x.files||0}개</td>
   <td>${Math.round((x.bytes||0)/1024).toLocaleString()}KB</td>
   <td>${x.total_mm==null?"–":esc(x.total_mm)}</td>
   <td><button class="ghost" data-drop="${esc(x.tag||x.file)}" style="padding:1px 6px;font-size:11px">버리기</button></td></tr>`).join("")+"</table>"
  :'<div class="note">대기 중인 묶음이 없습니다 — '+((d.auto===false||d.guard)?"[분석 실행]을 하면 여기에 쌓입니다."
    :"[분석 실행]이 끝나면 팀 서버로 자동 보고되고, 보내지 못한 것만 여기에 남습니다.")+'</div>';
 const sb=$("tusend");
 if(sb)sb.textContent="팀 서버 업로드"+(p.length?` (${p.length}건)`:"");
 const st=d.sent||[];
 $("tusent").textContent=st.length?`최근 보냄: ${st.slice(0,3).map(x=>x.when).join(" · ")}`:"";
 // 머리말 = 지금 설정(config.teamUpload.autoReport — teamup.auto_report_on 한 곳에서 읽은 값). 없으면(옛 서버) 기본 켬.
 // LM30 시험판 보호(d.guard — teamup.upload_guard)에 걸리면 그 규칙이 머리말이다
 const th=$("tuhead");
 if(th)th.textContent=d.guard?"LM30 시험판 — 시험용 팀 서버 주소를 정하기 전에는 보내지 않습니다(결과 묶음은 대기로 남습니다)"
  :(d.auto===false?"자동 보고 꺼짐(config.teamUpload.autoReport=false) — 서버에 닿는 망에서 버튼으로 보냅니다"
  :"[분석 실행]이 끝나면 팀 서버로 자동 보고합니다 — 닿지 않으면 대기로 남고, 사내망에서 버튼으로 보냅니다");
 $("tupend").querySelectorAll("[data-drop]").forEach(btn=>btn.onclick=async()=>{
  if(!confirm(`${btn.dataset.drop} 묶음을 대기 목록에서 버릴까요?\\n(사본은 report\\\\upload_sent 에 남습니다)`))return;
  const r=await fetch("/api/teamdrop",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({tag:btn.dataset.drop})}).then(x=>x.json()).catch(()=>({ok:false}));
  if(!r.ok)alert("버리지 못했습니다: "+(r.error||""));
  tuLoad();
 });
}
// v5: 올릴 주소는 보여 주기만 한다 — 바꾸는 곳은 LoadMonitor30-팀서버주소.bat 하나.
// 설치 폴더의 config\\team_server.json 에 저장되어 폴더를 옮기거나 나눠 줘도 그대로 따라간다.
function tuFill(d){
 if($("tuurl"))$("tuurl").textContent=d.url||"(주소 없음)";
 const SRC={file:"설치 폴더에 저장된 주소",legacy:"이전 판 설정에서 이어받은 주소",default:"기본 주소"};
 const src=(d.source||{}).host, el=$("tuaddr");
 if(!el)return;
 el.innerHTML=(src&&SRC[src]?esc(SRC[src])+" · ":"")
  +"바꾸려면 설치 폴더의 <b>"+esc(d.edit_bat||"LoadMonitor30-팀서버주소.bat")+"</b> 을 실행하세요(이 화면에서는 바꾸지 않습니다)."
  +(d.guard?'<div style="color:#8a5a00"><b>시험용 팀 서버 주소를 정하기 전에는 보내지 않습니다.</b> '+esc(d.guard)+'</div>':"")
  +(d.addr_kind==="loopback"?`<div style="color:#c0122f">${esc(d.addr_note||"")}</div>`:"")
  +((d.warnings||[]).length?`<div style="color:#c0122f">${(d.warnings||[]).map(esc).join("<br>")}</div>`:"");
}
$("tuping").onclick=async()=>{
 tuBusy(true,"");$("tustat").textContent="확인 중…";
 const r=await fetch("/api/teamping",{method:"POST",headers:{"Content-Type":"application/json"},
   body:"{}"}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 $("tustat").innerHTML=r.ok?`<span style="color:#0f7a3d">● 이 망에서 연결됨 (${r.ms||0}ms)</span>`
   :`<span style="color:#c0122f">● 이 망에서는 닿지 않음</span>`;
 if(!r.ok&&r.error)$("tumsg").textContent=String(r.error).slice(0,80);
};
// LM30 시험판 보호(teamup.upload_guard) — 시험용 팀 서버 주소를 정하기 전에는 보내지 않는다. 기본 주소는 기존 팀 서버라
// 거기로 보내면 팀원의 LM28·LM29 결과가 덮인다. 버튼은 실패라고 하지 않고 까닭과 할 일을 말한다(대기 묶음은 그대로)
function tuGuard(msg){
 const NL=String.fromCharCode(10);
 alert("시험용 팀 서버 주소를 정하기 전에는 보내지 않습니다."+NL+NL+(msg||"")+NL+NL
  +"설치 폴더의 "+((TU&&TU.edit_bat)||"LoadMonitor30-팀서버주소.bat")+" 으로 시험용 팀 서버 IP·포트를 저장한 뒤 "
  +"이 버튼을 다시 누르면 밀린 묶음까지 보냅니다.");
 $("tustat").innerHTML='<span class="state">● 보내지 않음 — 시험용 팀 서버 주소 없음</span>';
}
async function tuSend(){
 // v4: 판정 전에 **항상** 새로 읽는다 — 예전에는 TU(마지막 tuLoad 스냅샷)로 판정해서, 화면을
 // 분석 전에 열어 두면 분석이 끝나도 "보낼 결과가 없습니다" 가 떴다(UI 재시작으로만 풀리던 제보).
 // 교차 프로세스 사실(파일)은 메모리 스냅샷이 아니라 누르는 순간의 파일이 진실이다.
 tuBusy(true,"대기 목록 확인 중…");
 await tuLoad();
 tuBusy(false,"");
 if(TU.guard){tuGuard(TU.guard);return;}
 let p=(TU.pending||[]).length;
 if(!p){
  if(TU.unknown){
   // '모른다' 를 '없다' 로 말하면, 보낼 것이 있는데도 못 보내게 막는 셈이다(실측 제보)
   alert("대기 목록을 확인하지 못했습니다 — 보낼 것이 없다는 뜻이 아닙니다."
    +String.fromCharCode(10)+String.fromCharCode(10)+(TU.error||"")
    +String.fromCharCode(10)+String.fromCharCode(10)
    +"[묶음 폴더 열기] 로 report 폴더의 upload_pending 을 직접 확인하거나, "
    +"[새로고침] 후 다시 눌러 보세요.");
   return;}
  const av=(TU.available||[]).length;
  if(!av){alert("보낼 결과가 없습니다 — 먼저 [분석 실행]을 하세요.");return;}
  if(!confirm(`아직 묶음이 없습니다. 분석 결과 ${av}개 기간으로 지금 묶음을 만들고 보낼까요?`))return;
  if(!await tuBuild(false))return;
  p=(TU.pending||[]).length;
  if(!p){alert("묶음이 만들어지지 않았습니다 — 결과 파일을 확인하세요.");return;}
 }
 return tuSendConfirmed(p);
}
async function tuSendConfirmed(p){
 if(!confirm(`대기 ${p}건을 팀 서버로 보냅니다.\\n\\n${(TU&&TU.url)||"(주소 없음)"}\\n\\n판정 결과와 근거 신호(메일·회의 제목 포함)가 전송됩니다. 계속할까요?`))return;
 tuBusy(true,"업로드 중… (서버가 늦으면 1분 남짓에서 멈추고 묶음은 대기로 남깁니다)");
 const r=await fetch("/api/teamup",{method:"POST",headers:{"Content-Type":"application/json"},
   body:"{}"}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 await tuLoad();
 trLoad(false);                  // 다 보냈으면 teamup 이 '성공' 을 남긴다 — 자동 보고 실패 배너가 여기서 내려간다
 if(r.error==="busy"){alert("다른 작업이 실행 중입니다 — 끝난 뒤 다시 누르세요.");return;}
 if(r.kind==="no_test_server"){tuGuard(r.note);return;}
 if(r.unreachable){
  alert("이 망에서는 팀 서버에 닿지 않습니다.\\n\\n"+(r.error||"")+"\\n\\n묶음은 그대로 대기합니다 — 사내망에서 이 버튼을 다시 누르면 밀린 것까지 한 번에 올라갑니다.");
  $("tustat").innerHTML='<span style="color:#c0122f">● 이 망에서는 닿지 않음</span>';return;}
 const lines=(r.results||[]).map(x=>`· ${x.tag||x.file}: ${x.ok?"보냄":"실패"} ${x.msg||""}`).join("\\n");
 alert((r.ok?`업로드 완료 — ${r.sent}건`:`${(r.failed||!r.left)?"일부 실패":"일부만 보냄"} — 성공 ${r.sent||0} / 실패 ${r.failed||0}`+(r.left?` / 남김 ${r.left}`:""))
  +(lines?"\\n\\n"+lines:"")+(r.stopped?"\\n\\n"+r.stopped:""));
 if(r.sent&&TU.url&&confirm("팀 취합 대시보드를 열까요?"))window.open(TU.url,"_blank");
}
$("tusend").onclick=tuSend;
$("teamup").onclick=tuSend;
$("tufolder").onclick=async()=>{
 const cur=TU.share||"";
 const path=prompt("공유폴더 경로를 입력하세요 (예: \\\\\\\\서버\\\\공유\\\\LoadMonitor)\\n서버 대신 이 폴더에 묶음을 풀어 놓습니다.",cur);
 if(path===null)return;
 tuBusy(true,"공유폴더에 저장 중…");
 const r=await fetch("/api/teamfolder",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({share:path})}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 await tuLoad();
 trLoad(false);
 const lines=(r.results||[]).map(x=>`· ${x.tag||x.file}: ${x.ok?"저장":"실패"} ${x.msg||""}`).join("\\n");
 alert((r.ok?`공유폴더 저장 완료 — ${r.sent||0}건`:`실패 — ${r.error||""}`)+(lines?"\\n\\n"+lines:""));
};
async function tuBuild(latest){
 tuBusy(true,"분석 결과로 묶음을 만드는 중…");
 const r=await fetch("/api/teambuild",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({latest:!!latest})}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 await tuLoad();
 if(!r.ok){alert("묶음을 만들지 못했습니다 — "+(r.hint||r.error||""));return false;}
 return true;
}
$("tubuild").onclick=()=>tuBuild(false);
$("tuopen").onclick=()=>fetch("/api/teamopen",{method:"POST"});
// [로컬PC 자료수집](id collect2 · 구 '추가 PC 수집' — 이름이 헷갈린다는 제보로 LM28 에서 바꿈) = run.py --collect-only.
// 이 PC 에만 있는 자료만 모은다 — 메일·일정·팀즈(계정 자료)는 폴더를 받은 PC 의 [분석 실행]이 읽는다(run.collect_account_data).
// 분석·팀 서버 보고는 하지 않는다.
$("collect2").onclick=async()=>{
 const b={from:$("from").value,to:$("to").value,collect_only:true};
 if(!b.from||!b.to){alert("기간을 선택하세요");return;}
 if(!confirm("[로컬PC 자료수집] 이 PC 의 자료만 모읍니다 — AI 분석·팀 서버 보고는 하지 않습니다.\\n\\n"
   +"· 이 PC 에만 있는 자료(PC 가동 기록·파일·최근 문서·git·프로그램 기록)만 모아 빨리 끝납니다\\n"
   +"· 메일·일정·팀즈는 회사 계정 자료라 읽지 않습니다 — 같은 계정이면 폴더를 받은 PC 의 [분석 실행]이 읽습니다\\n"
   +"· 다른 PC 에서 가져온 폴더라면, 지난 PC 자료는 data\\\\추가PC\\\\ 로 자동 보관됩니다\\n"
   +"· 모은 뒤 폴더째 분석할 PC 로 옮겨 [분석 실행]을 누르면 두 PC 자료가 합쳐집니다\\n"
   +"· 겹치는 자료는 분석 때 자동 제외됩니다\\n\\n진행할까요?"))return;
 const r=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
 if(r.status===409){alert(await busyMsg(r,"이미 실행 중입니다"));return;}
 $("go").disabled=true;$("collect2").disabled=true;timer=setInterval(poll,1000);poll();
};
// ── 팀 서버 자동 보고 결과(LM28 — report\\team_report_status.json 을 /api/teamreport 로) ──
// 실패: 끝난 실행 1번당 알림 1번(열쇠 = 상태의 at — 이 화면을 연 뒤 바뀐 것만 · localStorage 로 새로고침·두 창을 넘어 1번)
// + 다음 성공(자동 보고·버튼·공유폴더 저장)까지 남는 배너([닫기] = 그 실패만 숨김). 성공: 대기 글자 뒤에 조용히 붙인다.
// 얼린 보고서 사본에는 /api/teamreport 를 굽지 않는다(freeze.FREEZE_EPS 밖) — 사본에 배너·알림이 뜨지 않는다.
async function trLoad(fromRun){
 const d=await fetch("/api/teamreport").then(r=>r.json()).catch(()=>null);
 trRender((d&&d.ok===true&&d.report)?d.report:{},fromRun);
}
function trRender(r,fromRun){
 const T=window.__tr||(window.__tr={seen:null,alerted:""}), NL=String.fromCharCode(10);
 const k=String(r.at||""), failed=r.ok===false, el=$("tr_banner");
 let dis="";try{dis=localStorage.getItem("lm28_tr_dismiss")||"";}catch(e){}
 if(el){
  if(failed&&k&&k!==dis){
   el.style.display="";
   el.innerHTML='⚠️ <b>팀 서버 자동 보고 실패 — '+esc(r.reason||"사유 미상")+'</b> <span style="color:#a0606a">('+esc(k)+')</span>'
    +(r.detail?'<div style="font-size:11.5px">'+esc(String(r.detail).slice(0,200))+'</div>':"")
    +'<div>'+esc(r.hint||"")+'</div>'
    +'<div style="margin-top:6px"><button class="ghost" id="tr_send">팀 서버 업로드</button> <button class="ghost" id="tr_close">닫기</button></div>';
   $("tr_send").onclick=tuSend;
   $("tr_close").onclick=()=>{try{localStorage.setItem("lm28_tr_dismiss",k);}catch(e){}el.style.display="none";};
  }else el.style.display="none";
 }
 const tl=$("tureport");
 if(tl)tl.innerHTML=!k?"":(r.ok===true
   ?`<span style="color:#0f7a3d">● 마지막 팀 서버 보고 ${esc(k)} — ${r.sent||0}건 보냄(${r.via==="auto"?"분석 끝 자동":(r.via==="folder"?"공유폴더":"버튼·bat")})</span>`
   :(failed?`<span style="color:#c0122f">● 마지막 자동 보고 ${esc(k)} — 실패: ${esc(r.reason||"")} · 대기 ${r.pending||0}건</span>`
     :`<span class="state">● 자동 보고 건너뜀 ${esc(k)} — ${esc(r.reason||"")}</span>`));
 if(fromRun&&k&&k!==T.seen){
  window.__trIdle=r.ok===true?`팀 서버 보고 완료 (${r.sent||0}건)`:"";
  if(failed&&k!==T.alerted){
   let al="";try{al=localStorage.getItem("lm28_tr_alerted")||"";}catch(e){}
   T.alerted=k;
   if(k!==al){
    try{localStorage.setItem("lm28_tr_alerted",k);}catch(e){}
    alert("팀 서버 자동 보고 실패 — "+(r.reason||"사유 미상")+(r.detail?NL+"("+String(r.detail).slice(0,160)+")":"")
     +NL+NL+(r.hint||"결과 묶음은 대기로 남았습니다. 사내망에서 [팀 서버 업로드]를 누르면 밀린 것까지 보내집니다."));
   }
  }
 }
 if(fromRun||T.seen===null)T.seen=k;
}
trLoad(false);
$("report").onclick=async()=>{
 const NL=String.fromCharCode(10);
 $("report").disabled=true;$("state").textContent="보고서 만드는 중… (리포트·분석리포트·얼린 보고서)";
 const d=await fetch("/api/report",{method:"POST"}).then(r=>r.json()).catch(()=>({ok:false}));
 $("report").disabled=false;
 if(d.ok){
  const fs=(d.files||[]).map(p=>String(p).split("/").pop().split(String.fromCharCode(92)).pop());
  $("state").textContent="보고서 생성됨 — report 폴더"+(fs.length?` (${fs.length}개)`:"");
  if(confirm("보고서를 만들었습니다."+NL+NL+(fs.length?fs.join(NL):"HTML: 브라우저용 / .doc: 더블클릭하면 Word로 열림")
    +NL+NL+"얼린 보고서·분석리포트 사본은 report 폴더의 얼린보고서 하위에도 남습니다. 폴더를 열까요?"))
   fetch("/api/openfolder",{method:"POST"});
 }else{$("state").textContent=d.error==="no result"?"분석 결과가 없습니다 — 먼저 [분석 실행]"
   :(d.error==="busy"?"다른 작업이 실행 중입니다":"보고서 생성 실패"+(d.hint?" — "+d.hint:""));}
 // (아래 배너와 같은 사실을 여기서도 말한다)
};
$("teamagg").onclick=async()=>{
 $("teamagg").disabled=true;$("state").textContent="팀 취합 중…";
 const d=await fetch("/api/aggregate",{method:"POST"}).then(r=>r.json()).catch(()=>({ok:false}));
 $("teamagg").disabled=false;
 if(!d.ok){
  $("state").textContent="대기 중";
  if(d.error==="no share"){
   if(confirm("팀 공유폴더가 설정되지 않았습니다.\\n팀 뷰어를 열어 경로를 설정할까요?"))window.open("/team","_blank");
   return;
  }
  alert(d.error==="no members"?"공유폴더에 취합할 인원이 없습니다.\\n각 팀원이 [분석 실행] 후 자동 내보내기가 되어야 합니다.":"팀 취합 실패 — 진행 로그 확인");
  return;
 }
 $("state").textContent=`팀 취합 완료 — ${d.members}명`+(d.agentic!=null?` (니즈 후보 결과 ${d.agentic}명 · 팀 니즈 후보 ${d.needs||0}건)`:"");
 window.open("/team/report","_blank");
};
$("diag").onclick=async()=>{
 $("diag").disabled=true;$("state").textContent="AI 연결 진단 중… (최대 1분)";
 const d=await fetch("/api/diag",{method:"POST"}).then(r=>r.json()).catch(e=>({ok:false,error:String(e)}));
 $("diag").disabled=false;$("state").textContent="대기 중";
 const L=[];
 L.push(d.ok?"✅ Copilot 왕복 성공 — AI 판정을 쓸 수 있습니다":"❌ Copilot 왕복 실패");
 if(d.phase)L.push("단계: "+d.phase);
 if(d.error)L.push("오류: "+d.error);
 if(d.hint)L.push("조치: "+d.hint);
 if(d.model)L.push("모델: "+d.model);
 if(d.reply)L.push("응답 일부: "+String(d.reply).slice(0,80));
 if(d.chats)L.push("Copilot 채팅 정리: "+d.chats);
 if(!d.ok)L.push("\\n대개는 전용 Edge 창에서 회사 계정 재로그인으로 해결됩니다.");
 alert(L.join("\\n"));
};
// LM30(2026-10-21) [LM이 연 Copilot 채팅 지우기] — LM 기록에 있는 채팅만 다시 지운다(사람이 쓰던 채팅·기록에 없는 채팅은 그대로).
// 분석·다른 작업 중에는 꺼진다(poll) · 서버도 409. 끝나면 실행 끝과 같은 한 줄을 알림 창과 아래 줄(chatline)에 보여 준다.
$("chatsweep").onclick=async()=>{
 if(!confirm("LM이 열고 기록해 둔 Copilot 채팅만 대화 목록에서 지웁니다(최대 5분).\\n사람이 쓰던 채팅과 기록에 없는 채팅은 건드리지 않습니다.\\n전용 Edge 가 로그인돼 있지 않으면 아무것도 지우지 않고 알려 드립니다.\\n\\n계속할까요?"))return;
 const b=$("chatsweep");b.disabled=true;$("state").textContent="LM이 연 Copilot 채팅 지우는 중… (최대 5분)";
 if(!timer){timer=setInterval(poll,1000);}
 const r=await fetch("/api/chat_sweep",{method:"POST"}).catch(e=>null);
 const d=r?await r.json().catch(e=>({ok:false,line:String(e)})):{ok:false,line:"서버 연결 끊김"};
 b.disabled=false;$("state").textContent="대기 중";
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");return;}
 if(d.line)window.__chatBtn=d.line;
 const el=$("chatline");if(el&&d.line){el.textContent=d.line;el.style.display="";}
 alert((d.line||"Copilot 채팅 지우기를 마치지 못했습니다 — 진행 로그를 확인하세요")+(d.note?"\\n\\n"+d.note:""));
};
// 마지막 실행의 Copilot 채팅 한 줄(LM30 — last_run.json 의 chats_line · 없으면 'Copilot 채팅 정리' 단계 note). 이 세션에서 버튼을 눌렀으면 그 줄
function chatLine(lr){
 const el=$("chatline");if(!el)return;
 const r=lr||{};const st=(r.stages||[]).find(x=>x&&x.name==="Copilot 채팅 정리");
 const ln=window.__chatBtn||r.chats_line||(st&&st.note)||"";
 if(ln){el.textContent=(window.__chatBtn?"":"마지막 실행 — ")+ln;el.style.display="";}else{el.style.display="none";}
}
// [Outlook 웹 읽기]·[팀즈 웹 읽기] — LM28: 화면 기간(시작~끝)을 넘기고 run.py --web-only 가 정제·병합·원장·Edge 정리까지 한다.
// 분석·다른 작업 중에는 버튼이 꺼진다(poll) — 같은 전용 Edge 를 두 작업이 함께 쓰지 않게(F-16).
async function webRead(kind,btn){
 const nm=kind==="mail"?"Outlook 웹":"팀즈 웹";
 const msg=kind==="mail"
  ?"Outlook 웹(outlook.office.com)을 전용 Edge 창으로 열어 메일·일정을 읽습니다.\\n처음이면 그 창의 Outlook 탭에서 회사 계정을 한 번 선택/로그인해야 합니다."
  :"팀즈 웹(teams.microsoft.com)을 전용 Edge 창으로 열어 채팅을 읽습니다.\\n처음이면 그 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인해야 합니다.\\n팀즈 앱은 켜져 있지 않아도 됩니다.";
 const f=$("from").value,t=$("to").value;
 if(!confirm(msg+"\\n\\n기간: "+f+" ~ "+t+" (위 기간 카드)\\n계속할까요?"))return;
 btn.disabled=true;$("state").textContent=nm+" 읽는 중… ("+f+" ~ "+t+", 수 분)";
 if(!timer){timer=setInterval(poll,1000);}
 const r=await fetch(kind==="mail"?"/api/owa":"/api/teamsweb",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({from:f,to:t})});
 const d=await r.json().catch(e=>({ok:false,error:String(e)}));
 btn.disabled=false;$("state").textContent="대기 중";
 if(r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");return;}
 if(d.rc===2){alert("로그인이 필요합니다.\\n지금 열린 전용 Edge 창의 "+(kind==="mail"?"Outlook":"팀즈")+" 탭에서 회사 계정을 선택/로그인한 뒤 ["+nm+" 읽기]를 다시 누르세요.\\n(로그인을 기다리는 동안 그 창은 닫지 않습니다)");return;}
 alert((d.ok?"읽기 완료 — ":"읽기 일부 실패(의심 — 실측 전) — ")+(d.summary||d.error||"")+"\\n\\n[재분석만]으로 다시 분석하면 반영됩니다.");
 cvLoad();
}
$("owa").onclick=()=>webRead("mail",$("owa"));
$("teamsweb").onclick=()=>webRead("teams",$("teamsweb"));
$("prepmove").onclick=async()=>{
 // 폴더를 다른 PC 로 옮기려면 우리(대시보드·팀 서버·Copilot Edge)가 먼저 손을 놓아야 한다
 if(!confirm("이 폴더를 다른 PC 로 옮길 수 있도록 정리합니다.\\n\\n· 팀 서버·Copilot 창을 종료합니다\\n· 정리 창이 열리고, 이 대시보드도 함께 닫힙니다\\n· 수집 데이터와 분석 결과는 그대로 둡니다\\n· 정리 창이 '빠르게 옮기는 방법'(Edge 캐시 제외)도 함께 알려 줍니다\\n\\n계속할까요?"))return;
 $("prepmove").disabled=true;$("state").textContent="이동 준비 중…";
 const r=await fetch("/api/prepmove",{method:"POST"}).then(x=>x.json()).catch(()=>({ok:false}));
 if(!r.ok){$("prepmove").disabled=false;$("state").textContent="대기 중";
  alert("정리 창을 띄우지 못했습니다 — LoadMonitor30-이동준비.bat 을 직접 실행하세요."+(r.error?"\\n"+r.error:""));return;}
 alert("정리 창이 열렸습니다.\\n그 창의 안내를 따라 주세요 — 잠시 뒤 이 대시보드는 닫힙니다.");
 fetch("/api/quit",{method:"POST"}).catch(()=>{});
 document.body.innerHTML='<div class="wrap"><h1>PC 이동 준비</h1>'
  +'<div class="card"><div class="note">대시보드를 종료했습니다. 열린 정리 창의 결과를 확인한 뒤 폴더를 옮기세요.<br>'
  +'옮긴 PC 에서는 LoadMonitor30-UI.bat 을 실행하면 됩니다 — 지난 PC 데이터는 자동으로 합산됩니다.</div></div></div>';
};
$("cdiag").onclick=async()=>{
 // PC 마다 Outlook·Teams 버전이 달라 메일·팀즈가 비는 실측 — 무엇이 막혔는지 이 PC 에서 바로 본다
 $("cdiag").disabled=true;$("state").textContent="수집 진단 중… (Outlook·Teams 상태 확인, 최대 2분)";
 const d=await fetch("/api/collectdiag",{method:"POST"}).then(r=>r.json()).catch(e=>({ok:false,error:String(e)}));
 $("cdiag").disabled=false;$("state").textContent="대기 중";
 if(!d.ok){alert("수집 진단 실패 — "+(d.error||""));return;}
 const v=(d.verdict||[]).join("\\n");
 alert("수집 진단 결과 (report 폴더의 collect_diag.txt 에 저장 — 채팅·메일 내용은 마스킹됨)\\n\\n"+(v||"판정 없음")+"\\n\\n전체 내용은 [결과 폴더]의 collect_diag.txt — [판정]대로 이 PC 안에서 조치하면 됩니다(밖으로 보낼 필요 없음).");
};
$("narrate").onclick=async()=>{
 if(!confirm("월별 리뷰 코멘트를 다시 생성할까요?\\nCopilot 왕복이 월당 수십 초 걸립니다."))return;
 // 기본은 빠진 달·최근 달·데이터가 바뀐 달만 — 바뀌지 않은 달은 보내지 않아 왕복이 크게 준다
 const all=confirm("모든 달을 새로 만들까요?\\n[확인] 전체 다시 만들기\\n[취소] 빠진 달·최근 달·데이터가 바뀐 달만");
 const r=await fetch("/api/narrate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({all})});
 if(r.status===409){alert(await busyMsg(r,"다른 작업이 실행 중입니다"));return;}
 timer=setInterval(poll,1000);poll();
};
$("reset").onclick=async()=>{
 const all=confirm("데이터를 리셋합니다.\\n\\n[확인] 수집 데이터 + 분석 결과 모두 삭제\\n[취소] 다음 창에서 분석 결과만 삭제 선택(월별 리뷰 코멘트·AI 판정 기록은 보존)\\n\\n어느 쪽이든 Copilot 로그인 세션·채팅 기록, 아직 팀 서버로 보내지 못한 결과 묶음(report\\\\upload_pending), 팀 서버 기록 파일은 지우지 않습니다.");
 let what="all";
 if(!all){ if(!confirm("분석 결과(report 폴더)만 삭제할까요?\\n월별 리뷰 코멘트·AI 판정 기록은 보존합니다 — 다음 분석이 같은 달 코멘트를 이어서 쓰고, 이미 판정한 신호는 다시 묻지 않습니다."))return; what="report"; }
 const d=await fetch("/api/reset",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({what})}).then(r=>r.json()).catch(()=>({ok:false,hint:"서버와 연결이 끊겼습니다 — 대시보드를 다시 켠 뒤 다시 누르세요"}));
 // LM28(2026-10-18): 끝내 못 지운 파일(다른 프로그램이 쓰는 중)을 말한다 — 예전에는 말없이 건너뛰어 '리셋 완료'인데 결과가 남았다
 // LM28(2026-10-19): 그 파일을 열고 있는 프로그램 이름(holders — 윈도가 아는 이름·이 대시보드·팀 서버)과 못 읽은 폴더의 까닭(reasons)을 '경로 — 이름' 으로
 const nf=d.n_failed||0, hd=d.holders||{}, rs=d.reasons||{};
 const ex=(d.failed||[]).slice(0,5).map(p=>p+(hd[p]?" — "+hd[p]:(rs[p]?" — "+rs[p]:""))).join("\\n");
 const who=[...new Set((d.failed||[]).map(p=>hd[p]).filter(Boolean))];
 // 지운 것이 있으면 업로드 카드·자동 보고 배너·수집 현황도 다시 읽는다(예전에는 결과 카드만 — 지운 배너가 남아 보였다)
 if(d.error!=="busy"&&d.removed!=null){loaded={};refresh();tuLoad();trLoad(false);cvLoad();}
 if(d.ok){$("state").textContent=`리셋 완료 — ${d.removed}개 파일 삭제`+(d.kept_narratives?` · 월별 리뷰 코멘트 ${d.kept_narratives}개 파일 보존`:"")
   +(nf?` · ${nf}개는 못 지움`:"");
   if(nf)alert(`리셋은 했지만 ${nf}개 파일을 지우지 못했습니다 — `
    +(who.length?`그 파일을 열고 있는 프로그램: ${who.join(" · ")}.`:"다른 프로그램(엑셀·메모장·탐색기 미리보기 등)이 그 파일을 열고 있습니다.")
    +`\\n\\n${ex}${nf>5?"\\n…":""}\\n\\n그 프로그램을 닫고 [데이터 리셋]을 한 번 더 누르세요.`);}
 else{alert(d.error==="busy"?(d.hint||"작업 실행 중에는 리셋할 수 없습니다"):("리셋 실패"+(d.hint?` — ${d.hint}`:"")));}
};
$("quit").onclick=async()=>{if(confirm("서버를 종료할까요?")){await fetch("/api/quit",{method:"POST"});
 document.body.innerHTML="<p style='font-family:sans-serif;padding:40px'>종료되었습니다. 창을 닫으세요.</p>";}};
document.querySelectorAll("details")[1].addEventListener("toggle",()=>{});
async function showData(src){
 const d=await fetch("/api/data?src="+src).then(r=>r.json());
 $("dsrc").textContent=d.file?`${d.file} · 총 ${d.total.toLocaleString()}건${d.shown<d.total?` (최근 ${d.shown}건 표시)`:""}`:"데이터 없음";
 $("dtbl").innerHTML=d.cols.length
  ?"<tr>"+d.cols.map(c=>`<th>${esc(c)}</th>`).join("")+"</tr>"+
   d.rows.map(r=>"<tr>"+d.cols.map(c=>`<td>${esc(r[c])}</td>`).join("")+"</tr>").join("")
  :"<tr><td style='color:#8b929b'>이 소스에는 수집된 데이터가 없습니다.</td></tr>";
}
document.querySelectorAll("[data-s]").forEach(c=>c.onclick=()=>showData(c.dataset.s));

// ── 탭 + 리뷰 (raw 근거·타임라인·연결성) ──
let loaded={};
let curTab="dash";          // 지금 보고 있는 탭 — 실행이 끝나면 열린 리뷰 탭을 다시 그린다(poll)
const AGENT_C={"상":"#1d8a4a","중":"#c98a00","하":"#8b929b"};
// 수동 재분석(Agentic 니즈 발굴·워크플로우)은 서버 스레드에서 돈다 — 끝날 때까지 /api/status 를 보며 기다린다.
// 새로고침해도 서버가 기억하므로(GET 의 running/manual) 탭을 다시 열면 이어서 기다리고 사유를 다시 보여 준다.
async function waitIdle(){
 for(;;){await new Promise(r=>setTimeout(r,2000));
  try{const s=await fetch("/api/status").then(r=>r.json());if(!s.running)return;}catch(e){return;}}
}
// 마지막 수동 실행 결과 한 줄 — 실패면 '무엇이 막혔고 무엇을 하면 되는지'(error — hint)
function manualLine(m){
 if(!m)return "";
 const when=m.at?` (${esc(m.at)}${m.sec!=null?` · ${m.sec}초`:""})`:"";
 if(m.ok){const extra=[];if(m.failed_chunks)extra.push(`${m.failed_chunks}/${m.chunks||"?"} 묶음 실패`);
  if(m.salvaged_chunks)extra.push(`잘린 답 복구 ${m.salvaged_chunks}묶음`);if(m.note)extra.push(esc(m.note));
  return `<div class="note" style="margin-top:6px">최근 수동 실행${when}: 완료${extra.length?" — "+extra.join(" · "):""}</div>`;}
 return `<div class="note" style="margin-top:6px;color:#c0122f"><b>최근 수동 실행${when}: 실패</b> — ${esc(String(m.error||""))}${m.hint?`<br>→ ${esc(String(m.hint))}`:""}</div>`;
}
// 실패 사유 표시 — 409(다른 작업 중)의 hint 도 그대로 보여 준다
async function startTool(path){
 let r;
 try{r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});}
 catch(e){return {ok:false,error:"서버 연결 실패",hint:"창을 닫고 UI 를 다시 실행하세요"};}
 let d={};try{d=await r.json();}catch(e){}
 if(r.status===409)return {ok:false,busy:true,error:"다른 작업 실행 중",hint:d.hint||""};
 return d;
}
// flow.py 의 details.fold 와 같은 축 — 과제 이름을 화면에서 묶을 때 쓴다.
// 구분자를 공백으로 바꾸고 공백을 접은 뒤 소문자로. 두 곳이 다른 축을 쓰면 머리말이 갈린다.
const fold2=s=>String(s||"").normalize("NFKC").replace(/[·・ㆍ‧/_\-()\[\]（）]/g," ").split(/\s+/).filter(Boolean).join(" ").toLowerCase();
// 상위(업무 성격) 표가 갈린 과제 — 억지로 하나를 찍지 않고 그 사실을 보여 준다.
// 이 목록이 곧 '재배치가 필요한 것' 이다: 과제가 과병합됐거나(서로 다른 성격의 일이 한 과제로 묶임)
// 상위 판정이 행마다 갈린 것이다. 어느 쪽인지는 사람이 보면 바로 안다.
function mixedLine(mx){
 if(!mx||!mx.length)return"";
 const rows=mx.map(m=>{
  const v=(m.votes||[]).map(([k,w])=>`${esc(k)} ${(+w).toFixed(2)}`).join(" · ");
  return `<tr><td><b>${esc(m.model)}</b>${m.detail?` <span class="dim">/ ${esc(m.detail)}</span>`:""}</td><td class="dim">${v}</td></tr>`;
 }).join("");
 return '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:#8a5a00">'
  +`상위(업무 성격)가 갈린 과제 ${mx.length}건 — 재배치 필요</summary>`
  +'<table style="width:100%;font-size:12px;margin-top:6px">'+rows+'</table>'
  +'<div class="note">1위 표가 60%에 못 미쳐 <b>일부러 상위를 찍지 않았습니다</b>. 억지로 하나를 고르면 '
  +'그 과제가 과병합됐다는 사실이 숨습니다. 서로 다른 성격의 일이 한 과제로 묶였다면 '
  +'<b>config\\project_aliases.json</b> 의 <b>never</b> 에 그 쌍을 적어 갈라 두고, 과제는 맞는데 상위만 '
  +'갈린 것이라면 <b>config\\projects.json</b> 의 그 과제에 <code>"level1": "개발"</code> 처럼 적어 '
  +'못 박으세요. 지정한 값은 투표를 이깁니다.</div></details>';
}
// 과제(중위) 표기 병합·흐름 중복 제거 내역 — 무엇을 왜 합쳤는지 보이지 않으면 잘못된 병합을
// 사람이 찾을 수 없다. 접어 두고, 펼치면 표와 되돌리는 방법을 보여준다.
function mergeLine(m){
 if(!m)return"";
 const np=(m.pairs||[]).length, nd=(m.flow_dupes||[]).length, nr=(m.rejects||[]).length, na=(m.ask||[]).length;
 if(!np&&!nd&&!nr&&!na)return"";
 // LM30(2026-10-27) 합친 줄마다 [분리] — 두 이름을 never 에 적어 다시 합치지 않는다(POST /api/project_split · 작업 중이면 409).
 // 얼린 사본·파일로 연 화면에는 단추를 두지 않는다(lmLive — 보낼 곳이 없다)
 const live=lmLive();
 const rows=(m.pairs||[]).map(p=>`<tr><td>${esc(p.from)}</td><td style="color:#8b929b">→</td><td><b>${esc(p.to)}</b></td>`
  +`<td class="dim">${esc(p.why||"")}</td><td style="text-align:right">${(p.mm||0).toFixed(2)} MM</td>`
  +`<td style="text-align:right" class="dim">신호 ${p.signals||0}</td>`
  +(live?`<td style="text-align:right"><button class="ghost" style="padding:1px 8px;font-size:11px" data-a="${esc(p.from)}" data-b="${esc(p.to)}" `
  +`onclick="projSplit(this)" title="두 과제를 다시 합치지 않게 적습니다 — 다음 [워크플로우 재분석]부터 따로 보입니다">분리</button></td>`:"<td></td>")
  +`</tr>`).join("");
 const dups=(m.flow_dupes||[]).map(x=>`<tr><td colspan="3">${esc(x.kept)}</td>`
  +`<td class="dim">${esc(x.why||"")}</td><td colspan="3" style="text-align:right" class="dim">`
  +`단계 ${(x.steps||[0,0])[0]}개 유지 · ${(x.steps||[0,0])[1]}개 버림</td></tr>`).join("");
 const rej=(m.rejects||[]).map(r=>`<tr><td colspan="3">${esc(r.a)} ↔ ${esc(r.b)}</td>`
  +`<td colspan="4" class="dim">${esc(r.why||"")}</td></tr>`).join("");
 const ask=(m.ask||[]).map(r=>`<tr><td colspan="3">${esc(r.a)} ↔ ${esc(r.b)}</td>`
  +`<td colspan="4" class="dim">${esc(r.why||"")}</td></tr>`).join("");
 return '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:#4a5159">'
  +`이름 병합 ${np}건 · 흐름 중복 제거 ${nd}건${nr?` <span class="dim">(합치지 않은 것 ${nr}건)</span>`:""}`
  +`${na?` <span class="dim">· 확인이 필요한 것 ${na}건(합치지 않음)</span>`:""}`
  +'</summary><table style="width:100%;font-size:12px;margin-top:6px">'
  +(rows?'<tr><th colspan="7" style="text-align:left;color:#8b929b;font-weight:normal">합친 과제 이름</th></tr>'+rows:"")
  +(dups?'<tr><th colspan="7" style="text-align:left;color:#8b929b;font-weight:normal;padding-top:6px">중복으로 지운 흐름</th></tr>'+dups:"")
  +(ask?'<tr><th colspan="7" style="text-align:left;color:#8b929b;font-weight:normal;padding-top:6px">확인이 필요한 것 — 이름이 달라 합치지 않았습니다</th></tr>'+ask:"")
  +(rej?'<tr><th colspan="7" style="text-align:left;color:#8b929b;font-weight:normal;padding-top:6px">합치지 않은 것</th></tr>'+rej:"")
  +'</table><div class="note">잘못 합쳐졌으면 그 줄의 <b>[분리]</b>를 누르세요 — 두 이름을 config 폴더 project_aliases.json 의 '
  +'<b>never</b> 에 적어 다시 합치지 않고, 다음 [워크플로우 재분석]부터 따로 보입니다. 이름이 다른 과제는 담당 업무·제품이 겹쳐도 '
  +'자동으로 합치지 않고 "확인이 필요한 것" 으로만 보입니다.</div></details>';
}
async function projSplit(b){
 const a=b.getAttribute("data-a")||"", c=b.getAttribute("data-b")||"";
 if(!a||!c)return;
 if(!confirm(`'${a}' 와(과) '${c}' 를 나눕니다 — 다시 합치지 않게 적고, 다음 [워크플로우 재분석]부터 따로 보입니다. 나눌까요?`))return;
 b.disabled=true;
 let r=null,d={};
 try{r=await fetch("/api/project_split",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({a:a,b:c})});d=await r.json();}catch(e){d={ok:false,error:"보내지 못했습니다 — 화면을 새로 고친 뒤 다시 누르세요"};}
 if(r&&r.status===409){alert(d.hint||"다른 작업이 도는 중입니다 — 끝난 뒤 누르세요");b.disabled=false;return;}
 if(!d.ok){alert(d.error||"나누지 못했습니다");b.disabled=false;return;}
 b.textContent="나눔";b.title=d.msg||"";
}
// LM30(2026-10-25) 마지막으로 읽은 워크플로우(/api/workflow) — '0.04 MM 이하 숨기기'를 바꾸면 다시 읽지 않고 이것으로 다시 그린다(smallRedraw)
let FLC=null;
async function loadFlow(){
 const el=$("rv-flow");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await fetch("/api/workflow").then(r=>r.json()).catch(()=>({}));
 FLC=d;
 drawFlow(d);
 if(d.running&&$("flowre"))waitIdle().then(()=>{loaded["flow"]=0;loadFlow();});
}
function drawFlow(d){
 const el=$("rv-flow");if(!el)return;
 const nflows=(d.flows||[]).length;
 // 워크플로우는 이제 한 번의 실행으로 끝까지 판정한다(진전이 있는 한 자동으로 마저 묻는다).
 // 그래도 남았다면 두 가지 중 하나다 — 시간 예산·상한에 걸려 끊긴 것(다시 누르면 이어진다)이거나,
 // 더 늘릴 수 없어 멈춘 것(다시 눌러도 같다). 후자에 [이어서 분석]을 권하면 헛수고를 시킨다.
 const partial=d.partial&&d.missing_count?`<span style="color:#c0122f"> · ${d.missing_count}개 업무 미판정${d.failed_chunks?` (${d.failed_chunks}/${d.chunks||"?"} 묶음 실패)`:""} — ${d.resumable?"[이어서 분석]을 누르면 남은 업무만 이어서 판정합니다":"자동 마무리가 더 늘리지 못했습니다 — 다시 눌러도 같을 수 있습니다(신호가 얕거나 응답이 그 이름을 돌려주지 않는 단위)"}</span>`:"";
 const salv=d.salvaged_chunks?` · 잘린 답 복구 ${d.salvaged_chunks}묶음(부분 결과)`:"";
 const lastErr=d.last_error&&d.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(d.last_error.error)}${d.last_error.hint?` — ${esc(d.last_error.hint)}`:""}</div>`:"";
 // LM28(진단 D) — 다른 날짜 결과 이어받기 · AI 판정 대기(신호 대부분이 규칙 판정이라 묻지 않은 업무) · 개인정보 관문 · 세부 병합 건너뜀
 const ruleU=Array.isArray(d.rule_units)?d.rule_units:[], gateU=Array.isArray(d.gate_units)?d.gate_units:[];
 const ruleN=d.rule_units_count!=null?(Number(d.rule_units_count)||0):ruleU.length;
 const gateN=d.gate_units_count!=null?(Number(d.gate_units_count)||0):gateU.length;
 const flowExtra=(d.carried_from?`<div class="note" style="color:#8a5a00">⚠ <b>${esc(d.carried_from)}</b> 결과 ${Number(d.carried)||0}개 이어받음 · 오늘 새로 판정 ${Number(d.asked_new)||0}개${d.expired?` · 오래돼 다시 물은 ${Number(d.expired)||0}개`:""}</div>`:"")
  +(ruleN?`<div class="note">AI 판정 대기 <b>${ruleN}개</b> — [재분석만] 후 생성 <span class="dim">(신호 대부분이 규칙 판정이라 묻지 않은 업무${ruleU.length?": "+ruleU.slice(0,6).map(u=>`${esc(u.project||"")} / ${esc(u.detail||"")}(${Number(u.signals)||0}건·규칙 ${Math.round((Number(u.rule_share)||0)*100)}%)`).join(", ")+(ruleU.length>6?" …":""):""})</span></div>`:"")
  +(gateN?`<div class="note">개인정보 관문 <b>${gateN}개</b> — 조치 불필요 <span class="dim" title="${esc(gateU.slice(0,30).join(", "))}">(관문에 걸려 보내지 않은 업무 — 미판정으로 세지 않습니다)</span></div>`:"")
  +(d.merge_skipped?`<div class="note">세부업무 병합 왕복 건너뜀 — ${esc(d.merge_skipped)} 규칙 병합과 캐시만 썼습니다</div>`:"");
 const btnTop='<div class="card"><div class="row" style="align-items:center;gap:10px">'
  +'<button class="ghost" id="flowre">'+(d.partial&&d.missing_count&&d.resumable?"이어서 분석(남은 "+d.missing_count+"개)":"워크플로우 재분석")+'</button>'
  +'<span class="state" id="flowmsg">'+(d.running?"워크플로우 분석 진행 중… (진행률은 상단 진행 바)":(d.generated?esc(`생성 ${d.generated} · ${d.model_name||""}`)+(d.basis==="규칙"?" · 규칙 축(AI 판정 없음)":""):""))+'</span></div>'
  +'<div class="note">과제별로 <b>역할 → 일의 순서 → 단계별 Agent 가능성</b>을 raw 근거에서 판정합니다. '
  +'MM 배분 숫자는 AI 가 아니라 판정 실측치입니다.'+(nflows?` 업무 ${nflows}/${d.rows_units||nflows}개 판정`+partial+salv:"")+'</div>'+lastErr+flowExtra
  +(d.reextracted?'<div class="note" style="color:#8a5a00">⚠ <b>재추출 이후 결과</b> — '+esc(d.reextracted_note||"이 결과는 마지막 업무 로드 재추출 이전의 것입니다")+' · [워크플로우 재분석]으로 갱신하세요</div>':"")
  +mergeLine(d.merge2)+mixedLine(d.level1_mixed)+manualLine(d.manual);
 const btn=btnTop+'</div>';
 if(!d.ok||!nflows){
  // 홑따옴표 문자열에서는 ${...} 가 치환되지 않는다 — 템플릿 리터럴로 써야 사유가 실제로 보인다
  // '결과가 없다' 와 '다른 기간 것만 있다' 는 다르다 — 구분해서 말한다
  const per=d.tag?`지금 보는 기간(${esc(d.tag)})에는 `:"";
  const oth=d.other_tag?`<br><b>${esc(d.other_tag)}</b> 기간 결과는 있습니다 — 그 기간을 분석하거나 아래 버튼으로 지금 기간을 만드세요.`:"";
  if(d.ok&&d.empty_reason){
   // 결과 없음 ≠ 오류 — 신호 3건 이상인 담당 업무가 없어 흐름을 만들 수 없었다(실패로 표시하지 않는다)
   el.innerHTML=btn+`<div class="card"><div class="note">${per}워크플로우로 만들 담당 업무가 없습니다 — ${esc(d.empty_reason)}.<br>`
    +'신호가 3건 이상 쌓인 (과제, 담당업무)가 있어야 흐름을 판정합니다. 더 긴 기간을 분석하거나 신호가 쌓인 뒤 다시 돌리세요.</div></div>';
  }else{
   // 상태 파일이 남긴 중단 사유 — 갈래 문구(whyEmpty)보다 먼저, 빨간 줄로(진단 D: 사유가 화면에 없어 '정체로 스킵?' 으로 읽혔다)
   const stBits=[d.stage_reason,d.stage_error].filter((x,i,a)=>x&&a.indexOf(x)===i);
   const stWhy=stBits.length?`<div class="note" style="color:#c0122f">최근 실행이 남긴 사유: ${stBits.map(x=>esc(x)).join(" · ")}</div>`:"";
   el.innerHTML=btn+`<div class="card">${stWhy}<div class="note">${per}워크플로우 분석이 없습니다${d.file_error?` <span style="color:#c0122f">· ${esc(d.file_error)}</span>`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""}${whyEmpty(d.stage_kind,"[워크플로우 재분석]")} — `
    +'AI 정제를 포함해 [분석 실행]을 돌리면 자동 생성됩니다. 위 [워크플로우 재분석]으로 지금 만들 수도 있습니다.'+oth+'</div></div>';
  }
 }else{
  // 상위(Level 1)가 바뀌는 자리마다 머리말을 넣어 '상위 → 과제' 계층이 눈에 보이게 한다.
  // flow.py 가 상위로 묶어 정렬해 내보내므로 여기서는 바뀌는 지점만 잡으면 된다.
  let _l1prev=null,_pjprev=null;
  // 상위(업무 성격)·과제(중위)도 접었다 펼 수 있게 <details> 로 감싼다(제보). 열고 닫은 상태는
  // 화면이 다시 그려져도 유지돼야 하므로 창 전역 Set 에 키로 기억한다.
  const FOPEN=window.__flowOpen||(window.__flowOpen=new Set());
  let _grpOpen=0;                       // 지금 열려 있는 그룹 <details> 수(상위·과제) — 끝에서 닫는다
  const _first={l1:null,pj:null};
  // LM30(2026-10-25) 0.04 MM 이하인 담당 업무(흐름 카드)는 숨긴다 — 머리말의 과제·업무 수도 보이는 카드로 센다(MM 을 모르는 카드는 그대로).
  // 보이는 카드 안의 작은 세부 몫은 범례에서 빼고 막대 끝 연회색 한 칸으로. 숨긴 개수·합은 위 카드 끝 한 줄(업무 N/M개 판정은 그대로)
  const tF=smallTally(), fl=smallSplit(d.flows,f=>(f.mm||{}).mm,tF).vis;
  const cards=fl.map(f=>{
   const mm=f.mm||{}, all=Object.entries(mm.details||{}), sd=smallSplit(all,([,v])=>v,tF), det=sd.vis;
   const mtot=all.reduce((s,[,v])=>s+v,0)||1;
   const mmBar=all.length?('<div class="bigbar" style="margin:4px 0">'
     +det.map(([k,v],i)=>`<i style="width:${(v/mtot*100).toFixed(1)}%;background:${PAL[i%PAL.length]}" title="${esc(k)} ${v} MM"></i>`).join("")
     +smallSeg(sd,sd.sum/mtot*100)
     +'</div><div class="leg" style="font-size:11px">'
     +det.map(([k,v],i)=>`<div><span class="dot" style="background:${PAL[i%PAL.length]}"></span>${esc(k)}<span class="v">${v} MM</span></div>`).join("")+'</div>'):"";
   const steps=(f.steps||[]).map(s=>`
    <tr><td style="width:26px;text-align:center;color:#8b929b"><b>${s.order}</b></td>
     <td style="width:150px"><b>${esc(s.name)}</b>${s.cycle?`<div style="color:#8b929b;font-size:11px">${esc(s.cycle)}</div>`:""}</td>
     <td>${esc(s.desc)}${s.evidence?`<div style="color:#98a0a8;font-size:11px">근거: ${esc(s.evidence)}</div>`:""}</td>
     <td style="width:220px"><span style="display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px;background:${AGENT_C[s.agent]||"#8b929b"}">Agent ${esc(s.agent)}</span>
      ${s.agent_how?`<div style="font-size:11px;color:#4a5159;margin-top:2px">${esc(s.agent_how)}</div>`:""}</td></tr>`).join("");
   const fi=fl.indexOf(f);
   const cur=f.level1||"";
   // 계층: 상위(업무 성격) → 과제(중위) → 담당업무(하위, 카드). 보완2 처럼 담당업무마다 흐름이 따로 서되,
   // 화면에서는 자기 과제 밑에 모여 있어야 '뒤죽박죽' 으로 읽히지 않는다.
   const pj=f.project||f.model, hasDet=!!f.detail;
   const pjOf=x=>x.project||x.model;
   // 과제를 묶는 키는 flow.py 가 실어 준 pjkey(정렬과 같은 축)를 쓴다. 예전에는 표시 이름을
   // 그대로 비교해, 정렬은 정규화 축인데 머리말은 원시 문자열이라 표기가 조금만 달라도
   // 같은 과제 머리말이 두 번 나왔다. 옛 결과 파일에는 pjkey 가 없으므로 이름으로 되돌린다.
   const pkOf=x=>x.pjkey||pjOf(x);
   const pk=pkOf(f);
   let head="";
   // 상위가 빈 카드는 두 종류다 — 표 자체가 없는 것(미분류)과, 표가 갈려 일부러 안 찍은 것(혼재).
   // 후자는 '재배치가 필요한 것' 이므로 그렇게 말해 줘야 한다. 예전에는 둘 다 '상위 미분류' 였다.
   const l1lab=cur?esc(cur):((f.level1_mix||[]).length?"상위 혼재 — 재배치 필요":"상위 미분류");
   if(cur!==_l1prev){
    // 앞 그룹들을 닫는다(과제 → 상위 순서)
    while(_grpOpen>0){head+="</div></details>";_grpOpen--;}
    if(_first.l1===null)_first.l1="l1:"+cur;
    const _k="l1:"+cur, _n=new Set(fl.filter(x=>(x.level1||"")===cur).map(pkOf)).size;
    const _nf=fl.filter(x=>(x.level1||"")===cur).length;
    const _op=(FOPEN.size?FOPEN.has(_k):_k===_first.l1)?" open":"";
    head+=`<details class="grp1" data-k="${esc(_k)}"${_op} style="margin:14px 0 4px">
      <summary style="font-size:12.5px;color:#4a5159;padding:6px 10px;background:#f3f5f8;border-radius:6px">
      <b>${l1lab}</b> <span class="dim">— 과제 ${_n}개 · 담당 업무 ${_nf}개</span></summary><div class="body">`;
    _grpOpen++;_pjprev=null;}
   if(hasDet&&pk!==_pjprev){
    const sibs=fl.filter(x=>pkOf(x)===pk&&(x.level1||"")===cur).length;
    // 신호가 얕아 흐름을 만들지 않은 업무 — 콘솔에만 있던 것을 과제 밑에 한 줄로 알린다.
    // 이것이 안 보이면 사용자에게는 '내 일이 통째로 사라졌다' 로 읽힌다.
    const th=(d.thin||[]).filter(t=>fold2(t.project)===pk);
    const thin=th.length?`<span class="dim"> · <span title="${esc(th.map(t=>t.detail+"("+t.signals+")").join(", "))}">신호가 얕아 흐름을 만들지 않은 업무 ${th.length}개</span></span>`:"";
    if(_grpOpen>1){head+="</div></details>";_grpOpen--;}          // 앞 과제를 닫는다
    if(_first.pj===null)_first.pj="pj:"+pk;
    const _kp="pj:"+pk;
    const _opp=(FOPEN.size?FOPEN.has(_kp):_kp===_first.pj)?" open":"";
    head+=`<details class="grp2" data-k="${esc(_kp)}"${_opp} style="margin:8px 0 4px 6px">
      <summary style="font-size:13px;padding:4px 8px"><b>${esc(pj)}</b> <span class="dim">— 담당 업무 ${sibs}개</span>${thin}</summary><div class="body">`;
    _grpOpen++;
   }
   _l1prev=cur;_pjprev=pk;
   // 과제 수만큼 길어지는 탭 — 접이식으로. 제목 줄에 역할 요약을 실어 접힌 채로도 훑는다.
   // 상위(업무 성격) 배지 — 계층은 상위(Level 1) > 과제(Level 2) > 담당업무(Level 3) 다.
   // LM20 처럼 상위로도 묶어 읽히게 제목에 배지를 달고, 아래에서 상위별로 구간을 나눈다.
   // 상위 색·순서는 서버(details.L1_META 단일원)가 /api/dash 로 준다 — JS 하드코딩 사전 폐기.
   // 얼린 사본(l1meta 없는 옛 데이터)은 회색 기본값으로 그린다(방어).
   const L1M=(window.__dash&&window.__dash.l1meta)||{};
   const L1C=new Proxy({},{get:(_,k)=>(L1M[k]&&L1M[k].color)||"#8b929b",has:(_,k)=>k in L1M});
   const l1b=f.level1?`<span style="display:inline-block;padding:0 7px;border-radius:9px;color:#fff;font-size:11px;background:${L1C[f.level1]||"#8b929b"};margin-right:6px">${esc(f.level1)}</span>`:"";
   // 한 과제가 여러 흐름을 가질 수 있다 — 이어지지 않는 일을 억지로 한 타임라인으로 엮지 않기 위해서다.
   // 흐름 이름을 제목에 붙여 같은 과제의 다른 줄기임을 알 수 있게 한다.
   const br=f.branch?`<span class="dim"> · ${esc(f.branch)}</span>`:"";
   // 담당업무 카드는 과제 머리말 밑에 있으니 제목에는 담당업무만(과제는 title 속성으로).
   const ttl=hasDet?`<span title="${esc(pj)}">${esc(f.detail)}</span>`:esc(f.model);
   // 카드도 같은 규칙으로 상태를 기억한다 — 처음 화면에서는 첫 카드만 펼친다
   const _kc="wf:"+String(f.model||"")+"|"+String(f.branch||"");
   const _opc=(FOPEN.size?FOPEN.has(_kc):fi===0)?" open":"";
   return head+`<details${_opc}${hasDet?' style="margin-left:6px"':''} data-k="${esc(_kc)}"><summary>${hasDet?"":l1b}${ttl}${br}
     <span class="state">${(mm.mm!=null)?mm.mm+" MM · ":""}단계 ${(f.steps||[]).length}개 · ${esc((f.role||"판단 유보").split("—")[0].trim())}${(d.carried_from&&f.asked_at)?` · ${esc(f.asked_at)} 판정`:""}</span></summary>
    <div class="body">
    ${(f.upstream||f.downstream)?`<div class="note" style="margin:2px 0 6px">${f.upstream?`← 앞 업무: <b>${esc(String(f.upstream).split(" / ").pop())}</b>`:""}${(f.upstream&&f.downstream)?" &nbsp;·&nbsp; ":""}${f.downstream?`→ 다음 업무: <b>${esc(String(f.downstream).split(" / ").pop())}</b>`:""}</div>`:""}
    <div style="margin:2px 0 6px"><b>역할:</b> ${esc(f.role)||"판단 유보"}</div>
    ${f.summary?`<div class="note" style="margin-bottom:6px">${esc(f.summary)}</div>`:""}
    ${mmBar}
    <table style="margin-top:6px"><tr><th></th><th>단계</th><th>무슨 일</th><th>Agent 가능성</th></tr>${steps}</table>
    </div></details>`;}).join("")+(function(){let s="";while(_grpOpen>0){s+="</div></details>";_grpOpen--;}return s;})();
  el.innerHTML=btnTop+smallLine(tF)+'</div>'+cards;
  // 접고 펴는 상태를 기억한다 — 1초 주기 갱신이나 탭 이동 뒤에도 보던 자리가 유지된다
  el.querySelectorAll("details[data-k]").forEach(dt=>{
   dt.addEventListener("toggle",()=>{const k=dt.getAttribute("data-k");
    if(dt.open)FOPEN.add(k);else FOPEN.delete(k);
    if(!FOPEN.size)FOPEN.add("\u0000");});           // 전부 접은 상태도 '사용자가 정한 것' 으로 남긴다
  });
 }
 const rb=$("flowre");
 if(rb)rb.onclick=async()=>{
  rb.disabled=true;$("flowmsg").textContent="워크플로우 판정 시작 중…";
  const r=await startTool("/api/workflow");
  // 사유(hint)를 버리면 '실패' 만 남아 사용자가 원인을 영영 못 본다 — 409 의 hint(무엇이 도는지)도 그대로
  if(!r.ok||!r.started){rb.disabled=false;$("flowmsg").textContent="실패: "+esc(String(r.error||""))+(r.hint?" — "+esc(String(r.hint)):"");return;}
  $("flowmsg").textContent="워크플로우 판정 중… (묶음마다 수십 초~수 분 · 진행률은 상단 진행 바 · 창을 닫아도 계속 돕니다)";
  if(!timer){timer=setInterval(poll,1000);}poll();
  await waitIdle();loaded["flow"]=0;loadFlow();
 };
 if(d.running&&rb)rb.disabled=true;      // 끝나기를 기다려 다시 읽는 것은 loadFlow 한 곳(다시 그릴 때마다 기다림을 늘리지 않게)
}
document.querySelectorAll("#tabs [data-t]").forEach(c=>c.onclick=()=>{
 document.querySelectorAll("#tabs [data-t]").forEach(x=>x.classList.toggle("on",x===c));
 document.querySelectorAll(".tab").forEach(t=>t.style.display="none");
 const id=c.dataset.t;curTab=id;$("tab-"+id).style.display="";
 // 실패하면 loaded 플래그를 되돌린다 — 안 그러면 '불러오는 중…'에서 영구 정지하고
 // 탭을 다시 눌러도 재시도되지 않는다.
 const fail=(k,e)=>{loaded[k]=0;const el=$("rv-"+k);
  if(el)el.innerHTML='<div class="card"><div class="note">표시 실패('+esc(String(e&&e.message||e))+') — 탭을 다시 누르면 재시도합니다.</div></div>';};
 if(id==="agentic"){if(!loaded[id]){loaded[id]=1;loadAgentic().catch(e=>fail(id,e));}}
 else if(id==="flow"){if(!loaded[id]){loaded[id]=1;loadFlow().catch(e=>fail(id,e));}}
 else if(id!=="dash"&&!loaded[id]){loaded[id]=1;loadReview(id).catch(e=>fail(id,e));}
});
function connSVG(g,col){
 if(!g.p_edges.length&&!g.a_edges.length)return"";
 const people=[...new Set(g.p_edges.map(e=>e[0]))].slice(0,7);
 const projs=[...new Set([...g.p_edges.map(e=>e[1]),...g.a_edges.map(e=>e[0])])].slice(0,6);
 const arts=[...new Set(g.a_edges.map(e=>e[1]))].slice(0,7);
 const H=Math.max(people.length,projs.length,arts.length)*30+30,W=740;
 const y=(arr,i)=>25+i*((H-30)/Math.max(arr.length-1,1));
 let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%">`;
 g.p_edges.forEach(([who,pj,n])=>{const i=people.indexOf(who),j=projs.indexOf(pj);
  if(i<0||j<0)return;
  s+=`<path d="M 150 ${y(people,i)} C 240 ${y(people,i)}, 280 ${y(projs,j)}, 360 ${y(projs,j)}" fill="none" stroke="${col(pj)}" stroke-opacity="0.35" stroke-width="${Math.min(1+n,5)}"/>`;});
 g.a_edges.forEach(([pj,art])=>{const j=projs.indexOf(pj),k=arts.indexOf(art);
  if(j<0||k<0)return;
  s+=`<path d="M 430 ${y(projs,j)} C 500 ${y(projs,j)}, 520 ${y(arts,k)}, 585 ${y(arts,k)}" fill="none" stroke="${col(pj)}" stroke-opacity="0.35" stroke-width="1.6"/>`;});
 people.forEach((p,i)=>s+=`<text x="145" y="${y(people,i)+4}" text-anchor="end" style="font-size:11px;fill:#3d444c">${esc(p)}</text>`);
 projs.forEach((p,j)=>s+=`<g><rect x="365" y="${y(projs,j)-11}" width="60" height="22" rx="4" fill="${col(p)}" opacity="0.12"/>
  <text x="395" y="${y(projs,j)+4}" text-anchor="middle" style="font-size:11px;font-weight:700;fill:#12151a">${esc(p.slice(0,8))}</text></g>`);
 arts.forEach((a,k)=>s+=`<text x="590" y="${y(arts,k)+4}" style="font-size:10.5px;fill:#3d444c">${esc(a)}</text>`);
 s+=`<text x="145" y="12" text-anchor="end" style="font-size:9.5px;fill:#98a0a8">함께 일한 사람</text>
 <text x="395" y="12" text-anchor="middle" style="font-size:9.5px;fill:#98a0a8">프로젝트</text>
 <text x="590" y="12" style="font-size:9.5px;fill:#98a0a8">산출물·커밋</text></svg>`;
 return `<div class="card" style="margin:8px 0"><h2 style="font-size:12px">업무 연결성</h2>${s}</div>`;
}
// 결과가 없을 때 '무엇을 하면 되는지' — 사유 갈래(stage_kind)별 한 문장. 제보: "안 만들어졌는데
// 정체되어 스킵된 걸까요?" 를 화면이 바로 답하게 한다.
function whyEmpty(kind, redo){
 const b=redo||"위 버튼";
 return {
  stalled:` — <b>정체로 중단</b>됐습니다(진행이 멈춰 자동으로 끊었습니다). [AI 연결 진단]으로 Copilot 창 상태를 확인한 뒤 ${b} 으로 남은 것만 이어서 하세요.`,
  budget:` — <b>시간 예산</b>에 닿아 남은 묶음을 보내지 않았습니다. ${b} 을 누르면 남은 것만 이어서 합니다(예산은 config.aiStageBudgetMin·flowBudgetMin).`,
  skipped:` — 앞 단계(AI 판정) 실패로 <b>건너뛰었습니다</b>. 판정을 먼저 성공시킨 뒤 ${b} 을 누르세요.`,
  failed:` — 왕복이 실패했습니다(위 사유). [AI 연결 진단] 확인 후 ${b}.`,
  // LM28 — Copilot 사용량 제한(쉬었다 다시 보내도 막힘)은 바로 다시 눌러도 같은 벽이다 · 관문은 실패가 아니다
  throttle:` — <b>Copilot 사용량 제한</b>으로 멈췄습니다(쉬었다 다시 보내도 막혀 남은 묶음을 보내지 않음). 1~2시간 뒤 [재분석만]·${b} — 이미 한 것은 이어서 씁니다.`,
  gate:` — 개인정보 관문에 걸린 업무는 보내지 않았습니다 — <b>조치 불필요</b>(미판정으로 세지 않습니다).`,
  ok:` — 최근 실행은 정상 완료로 기록돼 있습니다. 결과가 안 보이면 <b>화면이 보는 기간과 결과 기간이 다른</b> 경우입니다(기간을 맞춰 다시 실행).`,
  none:""
 }[kind||"none"]||"";
}
function keepDash(d){window.__dash=d;return d;}
// LM30(2026-10-25) 마지막으로 읽은 리뷰 자료(탭마다 {d, extra}) — '0.04 MM 이하 숨기기'를 바꾸면 다시 읽지 않고 이것으로 다시 그린다(smallRedraw)
const RVC={};
async function loadReview(kind){
 const el=$("rv-"+kind);
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const g={week:"week",month:"month",deep:"all"}[kind];
 const d=await fetch("/api/review?g="+g).then(r=>r.json());
 let extra={};try{extra=await fetch("/api/extra").then(r=>r.json());}catch(e){}
 RVC[kind]={d,extra};
 drawReview(kind);
}
function drawReview(kind){
 const el=$("rv-"+kind), rc=RVC[kind];
 if(!el||!rc)return;
 const d=rc.d, extra=rc.extra||{};
 const nar=extra.narratives||{};
 if(!d.groups.length){el.innerHTML='<div class="card"><div class="note">데이터 없음 — [분석 실행]을 먼저 돌리면 신호별 내역이 생성됩니다.</div></div>';return;}
 const allP=[...new Set(d.groups.flatMap(x=>x.projects.map(p=>p.name)))];
 const col=p=>PAL[allP.indexOf(p)%PAL.length];
 let pre="";
 if(kind==="deep"&&extra.entities&&(extra.entities.models||[]).length){
  const en=extra.entities;
  const disc=new Set(en.discovered||[]);
  // 상위(업무 성격, l1)는 체계가 과제마다 고른 값 — 있는 체계만 열을 보인다
  const hasL1=(en.models||[]).some(m=>m&&m.l1);
  const mrows2=(en.models||[]).map(m=>`<tr><td><b>${esc(m.name)}</b>${disc.has(m.name)?' <span class="tag" style="background:#e6f4ea;color:#0f7a3d">판정 중 발견</span>':''}</td>${hasL1?`<td style="font-size:11px">${esc(m.l1||"")||"-"}</td>`:""}<td style="color:#8b929b;font-size:11px">${(m.match||[]).map(esc).join(", ")||"-"}</td><td style="color:#5a626b;font-size:11px">${esc(m.obs||"")||"-"}</td></tr>`).join("");
  // 규칙 폴백 체계(체계 왕복 실패 — 임시) · 지난 체계 재사용(새로 물을 신호가 없어 체계 왕복을 건너뜀)
  const enBadge=(en.fallback?' <span class="tag" style="background:#fdf3e6;color:#8a5a00">규칙 폴백 체계(임시)</span>':"")
   +(en.reused_from?` <span class="tag" style="background:#eef4fb;color:#1c4e8a" title="${esc(en.reused_from)}">지난 체계 재사용</span>`:"");
  pre+=`<div class="card"><h2>과제 체계${enBadge} <span class="state">AI가 raw에서 발견한 상위 과제 — config.projects 는 힌트로만 참고${(en.hints_used||[]).length?` (힌트: ${en.hints_used.map(esc).join(", ")})`:" (힌트 없음)"}</span></h2>
  <table><tr><th>과제</th>${hasL1?"<th>상위</th>":""}<th>식별 키워드</th><th>채택 근거(raw)</th></tr>${mrows2}</table>
  <div class="note">힌트에 넣어도 raw에 흔적이 없으면 채택되지 않고, 판정 중 새 과제가 보이면 자동 추가됩니다.</div></div>`;
 }
 if(kind==="deep"&&extra.pivots&&extra.pivots.by_model){
  const pv=extra.pivots,WTC={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
  // LM30(2026-10-25) 0.04 MM 이하 — 과제·유형 줄은 그 칩과 함께 숨기고, 보이는 줄 안의 작은 칩은 그 칩만 뺀다 · 표마다 아래 한 줄
  const tM=smallTally(), tW=smallTally(), tC=smallTally(), cmn=pv.common||[];
  const chips=o=>smallSplit(Object.entries(o||{}),([,v])=>v,tM).vis.map(([k,v])=>`<span class="tag" style="border-left:3px solid ${WTC[k]||"#98a0a8"}">${esc(k)} ${v.toFixed(2)}</span>`).join("");
  const mrows=smallSplit(Object.entries(pv.by_model),([,v])=>v.mm,tM).vis.map(([m2,v])=>`<tr><td><b>${esc(m2)}</b></td><td><b>${v.mm.toFixed(2)}</b></td><td>${chips(v.worktypes)}</td><td>${smallSplit(Object.entries(v.details).slice(0,6),([,x2])=>x2,tM).vis.map(([k,x2])=>`<span class="tag">${esc(k)} ${x2.toFixed(2)}</span>`).join("")}</td></tr>`).join("");
  const wrows=smallSplit(Object.entries(pv.by_worktype),([,v])=>v.mm,tW).vis.map(([w2,v])=>`<tr><td><b style="color:${WTC[w2]||"#333"}">${esc(w2)}</b></td><td><b>${v.mm.toFixed(2)}</b></td><td>${smallSplit(Object.entries(v.models),([,x2])=>x2,tW).vis.map(([k,x2])=>`<span class="tag">${esc(k)} ${x2.toFixed(2)}</span>`).join("")}</td></tr>`).join("");
  const crows=smallSplit(cmn,c=>c.mm,tC).vis.map(c=>`<tr><td><b>${esc(c.detail)}</b></td><td>${c.models.map(esc).join(", ")}</td><td>${c.mm.toFixed(2)}</td></tr>`).join("");
  const ep=pv.episodes||{};
  const orows=(ep.orders||[]).slice(0,10).map(o=>`<tr><td>${esc(o.start.slice(5,16))}</td><td>${esc(o.model)}</td><td>${esc(o.req)}</td><td>→ ${esc(o.done)}</td><td><b>${o.lead_h}h</b></td></tr>`).join("");
  const srows=(ep.spans||[]).slice(0,10).map(o=>`<span class="tag">${esc(o.model)} ${esc(o.start.slice(5))}~${esc(o.end.slice(5))} (${o.signals}건)</span>`).join("");
  pre+=`<div class="card"><h2>과제 → 업무유형 · 세부업무 (MM)${pv.consistent_with?` <span class="state">기준: ${esc(pv.consistent_with)} — 대시보드와 동일</span>`:""}</h2><table><tr><th>과제</th><th style="width:52px">MM</th><th>유형 배분</th><th>세부업무 상위</th></tr>${mrows}</table>${smallLine(tM)}</div>
  <div class="grid2"><div class="card"><h2>업무유형 → 과제 (MM)</h2><table><tr><th>유형</th><th style="width:52px">MM</th><th>과제 배분</th></tr>${wrows}</table>${smallLine(tW)}</div>
  <div class="card"><h2>공통업무 — 표준화·자동화 후보</h2>${crows?`<table><tr><th>세부업무</th><th>관련 과제</th><th style="width:52px">MM</th></tr>${crows}</table>`:(cmn.length?"":'<div class="note">2개 이상 과제에 걸친 세부업무가 아직 없습니다 (AI 판정 후 생성)</div>')}${smallLine(tC)}<div class="note">여러 과제에 반복되는 업무일수록 표준화·AI 대체 우선순위가 높습니다.</div></div></div>
  <div class="card"><h2>업무 에피소드 <span class="state">외부요청 → 산출 리드타임${ep.avg_lead_h?` · 평균 ${ep.avg_lead_h}h`:""}</span></h2>
  ${orows?`<table><tr><th>요청 시각</th><th>과제</th><th>요청(시작)</th><th>산출(끝)</th><th style="width:56px">리드</th></tr>${orows}</table>`:'<div class="note">오더→산출 페어가 없습니다</div>'}
  ${srows?`<div style="margin-top:8px"><span class="state">자체진행 구간(연속 신호, 3일 공백 시 분리):</span><div style="margin-top:4px">${srows}</div></div>`:""}
  <div class="note">시작 = 외부요청(팀즈 오더·메일 수신) / 끝 = 요청과 <b>내용 연관(공통 단어·같은 세부업무)이 확인된</b> 첫 발신·산출물 — 연관 산출을 못 찾은 요청은 페어하지 않습니다. 자체진행 업무는 시작이 불명확해 연속 신호 구간으로 근사합니다.</div></div>`;
 }
 el.innerHTML=pre+d.groups.map((x,gi)=>{
  // LM30(2026-10-25) 이 묶음(달·전체)에서 0.04 MM 이하인 과제는 숨긴다 — 막대에서는 연회색 한 칸(비중 그대로), 과제 줄 아래 한 줄.
  // 주간 리뷰는 거르지 않는다 — 한 주의 과제 MM 은 대개 작아(1주 ≈ 0.25 MM) 0.04 문턱이면 과제 대부분이 숨는다
  const tG=smallTally(), sG=kind==="week"?smallAll(x.projects):smallSplit(x.projects,p=>p.mm,tG);
  const bar='<div class="bigbar" style="height:18px">'+sG.vis.map(p=>
   `<i style="width:${(p.share*100).toFixed(1)}%;background:${col(p.name)}" title="${esc(p.name)} ${(p.share*100).toFixed(0)}%"></i>`).join("")
   +smallSeg(sG,sG.hid.reduce((s,p)=>s+(Number(p.share)||0),0)*100)+"</div>";
  const psec=sG.vis.map(p=>{
   const acts=p.acts.map(a=>`${esc(a.name)} ${a.pct}%`).join(" · ");
   const ppl=p.people.map(([w,n])=>`<span class="tag">${esc(w)} ×${n}</span>`).join("");
   const fls=p.files.map(f=>`<span class="tag" style="background:#eef4fb">${esc(f)}</span>`).join("");
   const mts=p.meets.map(m2=>`<span class="tag" style="background:#fdf3e6">${esc(m2)}</span>`).join("");
   const cms=p.comms.map(c=>`<div style="font-size:11px;color:#5a626b;line-height:1.7">· ${esc(c)}</div>`).join("");
   return `<div style="border-left:3px solid ${col(p.name)};padding:4px 0 4px 12px;margin:12px 0">
    <div style="font-size:13px"><b>${esc(p.name)}</b>
     <span class="state">${(p.share*100).toFixed(0)}% · ${p.mm.toFixed(2)} MM · 신호 ${p.n}건</span></div>
    <div style="margin-top:3px;font-size:11.5px">${(p.wt||[]).map(([k,v])=>`<span class="tag" style="border-left:3px solid ${WTCOL[k]||"#98a0a8"}">${esc(k)} ${v}%</span>`).join("")}
     <span class="state">· ${acts}</span></div>
    ${ppl?`<div style="margin-top:5px"><span class="state">함께:</span> ${ppl}</div>`:""}
    ${p.note?`<div class="note" style="margin-top:3px">${esc(p.note)}</div>`:""}
    ${fls?`<div style="margin-top:3px"><span class="state">산출물:</span> ${fls}</div>`:""}
    ${mts?`<div style="margin-top:3px"><span class="state">회의:</span> ${mts}</div>`:""}
    ${cms?`<div style="margin-top:4px">${cms}</div>`:""}
   </div>`;}).join("");
  const tl=x.timeline.map(day=>`<div class="d">${day.date}</div>`+day.lines.map(l=>
   `<div>${l.t} <span class="s">[${esc(l.src)}]</span> <span class="p" style="color:${col(l.proj)}">${esc(l.proj)}</span> ${l.who&&l.who!=="나"?esc(l.who)+": ":""}${esc(l.text)}</div>`).join("")).join("");
  const nx=(kind==="month")?nar[x.key]:null;
  // 이월된 달은 출처를 적는다 — 같은 달 코멘트는 기간이 달라도 그 달의 것이지만, 어느 기간에서 온
  // 것인지 모르면 사용자가 숫자와 글이 어긋난 것으로 읽는다. 이번 실행에서 새로 만들지 못한 달(earlier — AI 판정이 적음·
  // 왕복 실패·관문)은 '이전 실행 코멘트' 라고 적는다. made = 그 코멘트를 만든 시각.
  const narMade=nx&&nx.made?` · ${esc(nx.made)} 작성`:"";
  const narFrom=!nx?"":(nx.from_tag?` <span class="state">(${esc(nx.from_tag)} 기간에서 이월${narMade})</span>`
   :(nx.earlier?` <span class="state">(이전 실행 코멘트${narMade} — 이번 실행에서 새로 만들지 못함)</span>`:""));
  const narH=nx?`<div style="background:#f0f6fd;border:1px solid #d6e5f7;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:12.5px;line-height:1.7">
   <b>AI 월간 리뷰</b>${narFrom} — ${esc(nx.summary||"")}${(nx.projects||[]).map(p=>`<div style="margin-top:4px">· <b>${esc(p.name)}</b> ${esc(p.story||"")} <span class="state">${esc(p.worktypes||"")}</span></div>`).join("")}</div>`
   :(kind==="month"?`<div class="note" style="border:1px dashed #c9cfd8;border-radius:6px;padding:8px 12px;margin:8px 0">
   이 달의 AI 리뷰 코멘트가 없습니다. 흔한 순서대로 — ① 이 기간을 <b>AI 판정 없이</b> 분석했다
   ② 그 달의 왕복이 실패했다(진행 로그의 "${esc(x.key)} 내러티브 실패") ③ 판정이 시간 예산·정체 감지로
   끊겨 남은 달을 만들지 못했다 ④ 다른 PC에서 결과만 복사했다(코멘트는 report 폴더에 있어 제외됨)
   ⑤ 그 달은 AI 판정된 신호가 적어(규칙 결과 위주) 코멘트를 만들지 않았다 — 판정이 회복된 뒤 [리뷰 코멘트 재생성].
   상단 <b>[리뷰 코멘트 재생성]</b> 이 이미 판정된 신호로 빠진 달·최근 달·데이터가 바뀐 달을 다시 만듭니다 — 재수집·재판정은 하지 않습니다.</div>`:"");
  const wtsum=(x.wt||[]).map(([k,v])=>`${k} ${v}%`).join(" · ");
  const head=`${esc(x.label)} <span class="state">신호 ${x.signals}건 · 활동 ${x.days}일${wtsum?" · "+esc(wtsum):""}</span>`;
  const body=`${narH}${bar}${psec}${smallLine(tG)}${connSVG(x,col)}
   <details style="margin-top:6px"><summary style="padding:8px 12px;font-size:12px">원문 근거 타임라인 (해석 검증용 — 판정된 업무 신호만)</summary>
   <div class="body tl" style="max-height:420px;overflow:auto">${tl}</div></details>
   <div class="note" style="margin-top:6px">${x.mm_basis==="mm_meta"?`과제 MM = 이 기간 투입 ${(x.mm||0).toFixed(2)} MM(대시보드·리포트와 같은 mm_meta) × 과제 몫(신호 비중)`:"과제 MM 은 기간×신호 비중 개략치 — 이 기간의 mm_meta 가 없어 대시보드 확정 MM 과 다를 수 있습니다"}</div>`;
  // 카드가 길어 접이식으로 — 첫 기간만 펼침. 상세 리뷰(deep)는 표 중심이라 기존 유지.
  if(kind==="deep")return `<div class="card"><h2>${head}</h2>${body}</div>`;
  return `<details${gi===0?" open":""}><summary>${head}</summary><div class="body">${body}</div></details>`;
 }).join("");
}
// ── Agentic AI 탭 — 니즈 후보 발굴만(LM29부터: 팀 과제 매칭·오할당 검증 없음) ──
// 이어받기·멈춘 이유 — 다른 기간 결과를 이어받았으면 그 기간과 발굴 시작일, 남은 행이 있으면 왜 멈췄는지(stop_kind)
function agCarry(a,pend){
 if(!a)return "";
 const STOP_KO={budget:"시간 예산에 닿음 — [이어서 발굴]",throttle:"Copilot 사용량 제한 — 1~2시간 뒤 [이어서 발굴]",
  login:"Copilot 로그인 만료 — [AI 연결 진단]에서 다시 로그인한 뒤 [이어서 발굴]",fatal:"사람이 손대야 풀리는 상태 — 아래 사유 확인",
  fail:"왕복 실패 — [AI 연결 진단] 확인 후 [이어서 발굴]",gate:"개인정보 관문 — 조치 불필요"};
 let h="";
 if(a.carried_from)h+=`<div class="note" style="color:#8a5a00">⚠ <b>${esc(a.carried_from)}</b> 기간 결과를 이어받음${a.matched_since?` (발굴 시작 ${esc(a.matched_since)})`:""}</div>`;
 if(pend&&STOP_KO[a.stop_kind])h+=`<div class="note">멈춘 이유: ${STOP_KO[a.stop_kind]}${a.cooldowns?` · Copilot 대기 ${Number(a.cooldowns)||0}회`:""}</div>`;
 return h;
}
async function loadAgentic(){
 const el=$("rv-agentic");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await fetch("/api/agentic").then(r=>r.json()).catch(()=>({}));
 const a=d.analysis||null;
 const pend=a&&a.rows_pending?a.rows_pending:0;
 const news=(a&&a.new)||[];
 let h=`<div class="card"><h2>Agentic AI 니즈 후보 발굴 <span class="state">[분석 실행](AI 판정) 뒤 자동으로 찾습니다</span></h2>
  <div class="note" style="margin:0 0 8px">팀 과제와 매칭하지 않고, 내 반복 업무에서 Agentic AI 로 자동화할 만한 니즈 후보만 찾습니다. 팀 전체의 니즈 후보는 팀 취합 화면에서 모아 봅니다.</div>
  <div class="row" style="margin-bottom:8px">
   <button class="${a?"ghost":"run"}" id="agrun" style="padding:7px 18px;font-size:12.5px">${pend?`이어서 발굴(남은 ${pend}행)`:"니즈 후보 발굴 실행"}</button>
   <span class="state" id="agmsg">${d.running?"니즈 후보 발굴 진행 중… (진행률은 상단 진행 바)":"묶음마다 Copilot 왕복 1회 — 수십 초~수 분"}</span>
  </div>${d.file_error?`<div class="note" style="color:#c0122f">${esc(d.file_error)}</div>`:""}${manualLine(d.manual)}`;
 if(!a){const stBits=[d.stage_reason,d.stage_error].filter((x,i,arr)=>x&&arr.indexOf(x)===i);
  if(stBits.length)h+=`<div class="note" style="color:#c0122f">최근 실행이 남긴 사유: ${stBits.map(x=>esc(x)).join(" · ")}</div>`;
  h+=`<div class="note">아직 니즈 후보 결과가 없습니다${d.tag?` (기간 ${esc(d.tag)})`:""}${d.other_tag?` — <b>${esc(d.other_tag)}</b> 기간 결과는 있습니다`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""}${whyEmpty(d.stage_kind,"[니즈 후보 발굴 실행]")} — [분석 실행](AI 판정 포함)을 돌리면 자동으로 만들어집니다. 이미 분석을 마쳤다면 위 버튼으로 발굴만 실행하세요.</div></div>`;}
 else{
  const lastErr=a.last_error&&a.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(a.last_error.error)}${a.last_error.hint?` — ${esc(a.last_error.hint)}`:""}</div>`:"";
  h+=`<div class="note">기간 ${esc(a.tag)} · 업무 ${a.rows_analyzed}행 분석${a.rows_total&&a.rows_total!==a.rows_analyzed?` / 전체 ${a.rows_total}행`:""}${a.chunks?` · 묶음 ${a.chunks}회`:""}${a.failed_chunks?` <span style="color:#c0122f">· ${a.failed_chunks}/${a.chunks||"?"} 묶음 실패</span>`:""}${pend?` <span style="color:#c0122f">· ${pend}행 미판정 — 후보가 실제보다 적을 수 있음. 위 버튼으로 남은 행만 이어서 발굴</span>`:""}${a.salvaged_chunks?` · 잘린 답 복구 ${a.salvaged_chunks}묶음(부분 결과)`:""}${!news.length&&!pend?` · <b>근거가 충분한 니즈 후보가 없습니다(실패 아님)</b>`:""}</div>`
   +(a.rule_rows?`<div class="note">AI 판정 대기 ${Number(a.rule_rows)||0}행 — 신호 대부분이 규칙 판정이라 아직 보내지 않았습니다([재분석만] 후 [니즈 후보 발굴 실행])</div>`:"")
   +(a.gate_skipped_rows?`<div class="note">개인정보 관문 ${Number(a.gate_skipped_rows)||0}행 — 보내지 않았습니다(조치 불필요)</div>`:"")
   +agCarry(a,pend)+lastErr
   +(d.reextracted?`<div class="note" style="color:#8a5a00">⚠ <b>${esc(d.reextracted_title||"재추출 이후 결과")}</b> — ${esc(d.reextracted_note||"")}</div>`:"")+`</div>`;
  h+=`<div class="card"><h2>니즈 후보 ${news.length}건 <span class="state">근거 업무가 많은 후보부터 · 근거 업무 N행 = 이 후보의 근거가 된 내 업무 행 수(MM 아님)</span></h2>`;
  if(news.length){news.forEach(n=>{
   const ws=n.work||[];
   h+=`<div style="border-left:3px solid #6c4fb8;padding:4px 0 4px 12px;margin:10px 0">
    <b>${esc(n.name)}</b>${n.evidence_rows!=null?` <span class="state">근거 업무 ${Number(n.evidence_rows)||0}행</span>`:""}
    ${n.logic?`<div style="font-size:12px;margin-top:3px"><b>동작 로직:</b> ${esc(n.logic)}</div>`:""}
    ${n.reason?`<div style="font-size:11.5px;color:#5a626b;margin-top:2px"><b>발굴 사유:</b> ${esc(n.reason)}</div>`:""}
    ${ws.length?`<div style="margin-top:4px">${ws.slice(0,12).map(w=>`<span class="tag">${esc(w)}</span>`).join("")}${ws.length>12?` <span class="state">외 ${ws.length-12}건</span>`:""}</div>`:""}</div>`;});}
  else h+=`<div class="note">근거가 충분한 니즈 후보가 없습니다 — 신호가 쌓일수록 발굴 정확도가 올라갑니다.</div>`;
  h+=`</div>`;
 }
 el.innerHTML=h;
 const btn=$("agrun");
 if(btn)btn.onclick=async()=>{
  btn.disabled=true;btn.textContent="시작 중…";
  const r=await startTool("/api/agentic");
  if(!r.ok||!r.started){
   // 사유(error — hint)를 그대로 — '실패' 한 마디로는 로그인 만료인지 자료 없음인지 알 수 없다
   btn.disabled=false;btn.textContent="니즈 후보 발굴 실행";
   const m=$("agmsg");if(m)m.innerHTML='<span style="color:#c0122f">실패: '+esc(String(r.error||""))+(r.hint?" — "+esc(String(r.hint)):"")+'</span>';
   return;}
  btn.textContent="발굴 중…";
  const m=$("agmsg");if(m)m.textContent="니즈 후보 발굴 중… (묶음마다 수십 초~수 분 · 진행률은 상단 진행 바 · 창을 닫아도 계속 돕니다)";
  if(!timer){timer=setInterval(poll,1000);}poll();
  await waitIdle();loaded={};loadAgentic();
 };
 if(d.running&&btn){btn.disabled=true;btn.textContent="발굴 중…";waitIdle().then(()=>{loaded={};loadAgentic();});}
}
// ── 수집 현황 카드(원장 한 원천 — F-33) · 커서 초기화 · 수동 기록(W1-19) ──
async function cvLoad(){
 const el=$("cvbody");if(!el)return;
 let d;
 try{d=await fetch("/api/collect_status?from="+encodeURIComponent($("from").value)+"&to="+encodeURIComponent($("to").value)).then(r=>r.json());}
 catch(e){el.innerHTML='<div class="note">수집 현황을 읽지 못했습니다</div>';return;}
 const L=d.ledger;let h="";
 if(L){
  const ax=L.axes||{};
  h+='<table><tr><th>축</th><th>읽음</th><th>0건 확인</th><th>일부</th><th>미관측</th><th>해당 없음</th><th>출처</th></tr>';
  Object.keys(ax).forEach(k=>{const a=ax[k];
   h+=`<tr><td><b>${esc(a.label)}</b></td><td>${a.ok}</td><td>${a.zero_ok}</td><td>${a.partial}</td>`
    +`<td${a.unobserved?' style="color:#b54708;font-weight:700"':""}>${a.unobserved}</td><td>${a.na}</td>`
    +`<td class="state">${esc((a.srcs||[]).join(" · "))||"–"}</td></tr>`;});
  h+=`</table><div class="note">기간 ${esc(L.period[0])} ~ ${esc(L.period[1])}${L.pc?" · "+esc(L.pc):""}`
   +`${L.suspect?` · COM 누락 의심 ${L.suspect}일(다른 경로가 확인할 때까지 미관측으로 둡니다)`:""}</div>`;
 }else h+='<div class="note">원장이 아직 없습니다 — [분석 실행](수집 포함) 뒤에 생깁니다.</div>';
 const stg=d.stages||[];
 if(stg.length){
  const bad=stg.filter(x=>[0,1,4].indexOf(x.rc)<0||x.reason);
  h+='<details style="margin-top:6px"><summary style="padding:6px 10px;font-size:12px">마지막 실행의 수집기 결과 '
   +`(${stg.length}단계${bad.length?` · 확인 필요 ${bad.length}`:""})</summary><div class="body"><table>`
   +'<tr><th>단계</th><th>rc</th><th>사유(의심 — 실측 전)</th><th>세부</th></tr>';
  stg.forEach(x=>{h+=`<tr><td>${esc(x.name)}</td><td>${esc(x.rc)}</td><td>${esc(x.reason||"")}</td>`
   +`<td class="state">${esc(Object.entries(x.counts||{}).map(([k,v])=>k+"="+v).join(" · "))}</td></tr>`;});
  h+='</table></div></details>';
 }
 if(d.owa&&d.owa.mail_rows){h+=`<div class="note">Outlook 웹: 메일 ${d.owa.mail_rows}통 중 시각 없이 날짜만 읽힌 것 ${d.owa.date_only}통`
  +`(${Math.round((d.owa.ratio||0)*100)}%) — 그만큼 시간 계상에서 빠집니다.</div>`;}
 el.innerHTML=h;$("cvstate").textContent="확인 "+(d.as_of||"");
}
$("cvrefresh").onclick=()=>{
 $("cvmsg").textContent="";
 cvLoad();poll();
};
$("cvreset").onclick=async()=>{
 if(!confirm("수집 커서와 날짜별 원장을 초기화합니다.\\n다음 [분석 실행]이 기간 전체를 처음부터 다시 읽습니다(수집한 자료는 지우지 않습니다).\\n계속할까요?"))return;
 const r=await fetch("/api/reset_cursors",{method:"POST"}).then(x=>x.json()).catch(e=>({ok:false,error:String(e)}));
 $("cvmsg").textContent=r.ok?("초기화했습니다 — "+((r.removed||[]).length?r.removed.join(", "):"커서 파일 없음")+(r.ledger?" · 원장":"")):("실패: "+(r.hint||r.error||""));
 cvLoad();
};
$("wl_date").value=iso(new Date());
$("wl_save").onclick=async()=>{
 const b={date:$("wl_date").value,start:$("wl_start").value,end:$("wl_end").value,hours:$("wl_hours").value,
  category:$("wl_cat").value,entity:$("wl_entity").value,note:$("wl_note").value};
 const r=await fetch("/api/worklog",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)})
  .then(x=>x.json()).catch(e=>({ok:false,error:String(e)}));
 $("wl_msg").textContent=r.ok?`기록됨 — ${r.row.date} ${r.row.category} ${r.row.hours}h${r.row.start?" ("+r.row.start+"~"+r.row.end+")":""}`:("실패: "+(r.error||""));
};
// 창을 닫으면 작업도 멈춘다(LM28): 10초마다 이 탭이 살아 있다고 알리고(/api/alive), 닫히거나 떠날 때(pagehide) 작별을 보낸다(/api/bye).
// 서버는 작별 뒤 20초 안에 새 탭(새로고침)이 오지 않거나 모든 탭이 3분 넘게 조용하면 작업을 멈추고 끝난다(ui_close_decision).
// 잠든 탭(freeze)은 그렇다고 알린다 — 몇 시간짜리 분석을 탭이 잠들었다는 이유로 죽이지 않게. 얼린 사본·파일로 연 화면은 하지 않는다.
function lmLive(){return location.protocol.indexOf("http")===0&&!document.getElementById("lm-frozen-data");}
let LM_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);
function lmAlive(vis){if(!lmLive())return;
 fetch("/api/alive",{method:"POST",headers:{"Content-Type":"application/json"},keepalive:true,
  body:JSON.stringify({id:LM_TAB,vis:vis||document.visibilityState})}).catch(()=>{});}
function lmBeacon(path,vis){try{navigator.sendBeacon(path,JSON.stringify({id:LM_TAB,vis:vis||""}));}catch(e){}}
// LM28(2026-10-19): 알림·확인·입력 창(alert·confirm·prompt)이 열려 있는 동안 브라우저는 이 화면의 타이머를 멈춘다 — 10초 신호가 끊겨
// 3분 뒤 대시보드가 통째로 꺼졌다(제보: 팀 서버 업로드 실패 알림을 띄워 둔 채 다른 일을 하다 [데이터 리셋] → 실패). 창을 열기 직전에
// 'dialog'(알림 창이 열려 있음)를 알리고, 닫히면 곧바로 평소 신호를 보낸다. 창의 결과는 그대로 돌려주고, 알리기가 실패해도 창은 연다.
(function(){if(window.__lmDlg)return;window.__lmDlg=1;
 ["alert","confirm","prompt"].forEach(function(k){const f0=window[k];if(typeof f0!=="function")return;
  window[k]=function(){try{if(lmLive())lmBeacon("/api/alive","dialog");}catch(e){}
   try{return f0.apply(window,arguments);}finally{try{if(lmLive())lmAlive();}catch(e){}}};});})();
function leaveWarn(e){e.preventDefault();e.returnValue="";return "";}
function leaveGuard(on){if(!lmLive()||on===!!window.__lmGuard)return;window.__lmGuard=on;
 if(on)window.addEventListener("beforeunload",leaveWarn);else window.removeEventListener("beforeunload",leaveWarn);}
if(lmLive()){
 lmAlive();setInterval(()=>lmAlive(),10000);
 document.addEventListener("visibilitychange",()=>lmAlive());
 document.addEventListener("freeze",()=>lmBeacon("/api/alive","frozen"));
 document.addEventListener("resume",()=>lmAlive());
 window.addEventListener("pageshow",e=>{if(e.persisted){LM_TAB=Math.random().toString(36).slice(2,10)+Date.now().toString(36);lmAlive();}});
 window.addEventListener("pagehide",()=>lmBeacon("/api/bye"));
}
setInterval(()=>{if(!timer)poll();},3000);
uiPrefsLoad();refresh();poll();tuLoad();cvLoad();
</script>
</body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _freezing(self):
        r"""[보고서 만들기]가 report\ 를 읽어 굽는 중이면 409 를 보내고 True.

        /api/report 는 JOB 을 보고 물러나지만 반대 방향이 없었다 — 굽는 도중 /api/run 이 들어와
        run.py 가 mm_meta·mm_rows 를 다시 쓰고, 사본에는 그 반쪽이 stale:false 로 굳었다(검증 확정).
        결과 파일을 다시 쓰는 작업(run·narrate·reset·exclude·retag)은 JOB 검사와 같은 LOCK 안에서
        이것을 본다 — /api/report 쪽은 FREEZE_LOCK 을 먼저 잡은 뒤 JOB 을 보므로 어느 순서로 겹쳐도
        한쪽만 진행한다."""
        if FREEZE_LOCK.locked():
            self._send(409, {"ok": False, "error": "busy",
                             "hint": "보고서를 만드는 중입니다 — 끝난 뒤 다시 누르세요"})
            return True
        return False

    def do_DELETE(self):
        if self.path == "/api/team_refine":
            share = team_share()[0]
            # 기본 = team_aliases.json 삭제(정리 되돌리기). 선택 본문 {"files":[...]} 로 계열·세부·후보·
            # 과제분류 캐시(team_report.CACHE_FILES 화이트리스트)도 함께 되돌릴 수 있다.
            files = ["team_aliases.json"]
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                b = json.loads(self.rfile.read(n)) if n else {}
                allowed = set(team_cache_files())
                files += [str(x) for x in ((b or {}).get("files") or [])
                          if str(x) in allowed and str(x) not in files]
            except (ValueError, OSError, AttributeError):
                pass
            removed = []
            for name in files:
                p = os.path.join(share, name) if share else ""
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                        removed.append(name)
                    except OSError:
                        pass
            if removed:
                log(f"[정리] {', '.join(removed)} 삭제 — 유사 항목 정리 되돌림")
            self._send(200, {"ok": True, "removed": removed})
        else:
            self._send(404, {"error": "not found"})

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/status":
            with LOCK:
                el = time.time() - JOB["started"] if JOB["started"] else 0
                pel = time.time() - JOB["phase_started"] if JOB["phase_started"] else 0
                eta = None
                if JOB["total"] and JOB["done"] > 0 and pel > 0:
                    eta = int(pel / JOB["done"] * (JOB["total"] - JOB["done"]))
                payload = {"running": JOB["running"], "log": JOB["log"][-200:],
                           "step": JOB["step"], "phase": JOB["phase"],
                           "done": JOB["done"], "total": JOB["total"],
                           "elapsed": int(el), "eta": eta,
                           # 마지막 출력 이후 흐른 초 — 화면이 '돌고 있다/조용하다' 를 구분한다
                           "idle": (int(time.time() - JOB["last_out"]) if JOB["last_out"] else None)}
            # 상태바 요약 — mtime 만 보므로 1초 폴링에도 부담 없다
            mp = latest("mm_meta_*.json")
            payload["last_run"] = _age(_mtime(mp)) if mp else ""
            payload["last_tag"] = (os.path.basename(mp)[len("mm_meta_"):-len(".json")]
                                   if mp else "")
            payload["busy_web"] = bool(JOB["running"])      # 분석·웹 읽기 중 — 화면이 웹 읽기 버튼을 끈다(F-16)
            self._send(200, payload)
        elif self.path == "/api/dash":
            fn, rows = result_rows()
            # 옛 정제본(v24.15 이전·다른 버전 PC 업로드분)의 스냅 전 상위 이름을 새 4범주로 접어 내려준다 —
            # 화면을 열기만 해도(재분석 없이) '신제품개발'·'기술내재화' 가 '개발' 로 보인다(제보: 재분석 요구 금지).
            try:
                import details as _dl1
                for _r in rows:
                    _sn = _dl1.snap1(_r.get("Level 1"))
                    if _sn:
                        _r["Level 1"] = _sn
            except Exception:  # noqa: BLE001
                pass
            meta = {}
            # meta 는 화면에 띄운 rows 와 **같은 태그**를 우선한다 — mtime 최신만 고르면
            # 다른 기간의 meta 로 로드율을 계산하거나, 그 meta 가 없어서 rows 는 멀쩡한데
            # 로드율만 '—' 가 되는 어긋남이 생긴다(실측: 회사 PC 화면). 규칙은 meta_path_for 한 곳(/api/attendance 도 같은 기간).
            mp = meta_path_for(fn)
            if mp:
                # 깨진/중단 저장된 JSON도 견뎌야 한다 — 여기서 예외가 나면 /api/dash 전체가
                # 실패해 대시보드가 통째로 백지가 된다. BOM 도 허용(utf-8-sig).
                try:
                    with open(mp, encoding="utf-8-sig") as f:
                        meta = json.load(f)
                except (OSError, ValueError):
                    meta = {}
            # AI 판정 여부 — entities_{tag}.json 의 존재로 보지 않는다(체계 단계에서 먼저 생겨 왕복이
            # 전부 실패해도 남는다). ai_judgments_{tag}.json 의 judged>0 이 기준 — _judged_info 참조.
            # False 면 지금 화면은 규칙 임시 결과(토큰 조각)라는 뜻이므로 배너로 알린다.
            m2 = re.match(r"mm_rows_(\d{8}-\d{8})", fn or "")
            judged, judged_n, judged_total, judged_issues = _judged_info(m2.group(1) if m2 else "")
            lastrun = {}
            try:                        # 왜 판정이 안 됐는지 화면이 직접 말하게 한다
                with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
                    lastrun = json.load(f)
                if not isinstance(lastrun, dict):    # 형태가 어긋난 파일 하나로 화면이 죽지 않게
                    lastrun = {}
            except (OSError, ValueError):
                lastrun = {}
            # 스텁 판정 표식(LM_COPILOT_STUB) — 성공 단계의 note 는 화면이 버리고 있었다(검증 확정).
            # 얼린 사본은 baked /api/dash 를 같은 스크립트로 그리므로 여기 실어야 사본에도 배너가 굳는다.
            stub_note = _stub_note(lastrun)
            # 화면 기간 — 분석 결과가 있으면 그 기간, 없으면 마지막 실행(수집)의 기간, 그것도 없으면 수집 데이터의 범위.
            # 추이·덩어리·수집 범위 대조가 전부 같은 기간을 본다(dash_period 참조).
            per = dash_period(meta, lastrun)
            # 추이 카드만은 **집계기간 전체** — 분석 창(per)이 6월~ 이어도 자료가 3월부터 있으면
            # 3월부터 그린다(제보). 나머지 카드(덩어리·수집 대조)는 분석 창 그대로.
            _ext = data_extent()
            per_tr = [min(x for x in (per[0], _ext[0]) if x) if (per[0] or _ext[0]) else "",
                      max(x for x in (per[1], _ext[1]) if x) if (per[1] or _ext[1]) else ""]
            tinfo = {}
            tr = trend(per_tr[0], per_tr[1], (m2.group(1) if m2 else ""), info=tinfo)
            # LM30(2026-10-20) PC 사용 시간 줄(분석 기간 합계 — 'MM 산정 근거' 카드 · 얼린 사본에도 남는다)
            try:
                pc_usage_text = pc_usage_view(meta)
            except Exception:  # noqa: BLE001 - 한 줄 때문에 대시보드 전체가 죽지 않게
                pc_usage_text = []
            # LM30(2026-10-21) 달마다 근거(일수·건수만 — 'PC 기록' 칸·8시간으로 채운 달 경고 · 얼린 사본에도 남는다)
            try:
                pc_months = pc_months_view(meta)
            except Exception:  # noqa: BLE001
                pc_months = {"cells": {}, "lines": [], "fill8": 0, "capped": False}
            # LM30(2026-10-21) 유급휴가 줄(core\attendance 머리말 22 — 날짜를 담는다: 이 PC 화면만 · 얼린 사본은 일수만 — freeze)
            try:
                leave_text = leave_view_lines(meta, os.path.basename(mp)[len("mm_meta_"):-len(".json")] if mp else "")
            except Exception:  # noqa: BLE001 - 한 줄 때문에 대시보드 전체가 죽지 않게
                leave_text = []
            try:
                import details as _dl1m
                _l1meta = _dl1m.l1_meta_payload()
            except Exception:  # noqa: BLE001
                _l1meta = {}
            self._send(200, {"version": VERSION, "port": PORT[0], "sources": sources(per),
                             "l1meta": _l1meta,
                             "file": fn, "rows": rows, "meta": meta,
                             "pc_usage_text": pc_usage_text, "pc_months": pc_months, "leave_text": leave_text,
                             # 메일·일정 수집 범위(달 단위) — 주간 활동 추이 밑에 '미수집 달'을 적는다(얼린 사본에도 굳는다)
                             "mail_coverage": outlook_coverage(per),
                             # 화면이 보고 있는 그 기간을 넘긴다 — 예전에는 오늘 기준
                             # 14주 고정이라 1월부터 본 사람도 최근 3개월만 보였다(제보)
                             "clumps": mtime_clumps(per[0], per[1]),
                             "trend": tr,
                             # 추이가 무엇을 셌는지 — signals(판정 신호) / raw(수집 raw 폴백) / none. 화면 안내가 이 값을 본다
                             "trend_src": tinfo.get("src", ""),
                             # 추이 밑 안내 재료 — PC 기록이 있는 버킷/전체, 기록 시작일, 상한에 눌린 건수,
                             # 주/월 단위, 추가PC 합산 실패 사유. 화면이 '0h' 와 '기록 없음' 을 구분해 말한다.
                             "trend_info": {k: tinfo.get(k) for k in
                                            ("gran", "pc_note", "pc_buckets", "pc_buckets_all", "pc_from", "capped",
                                             "period", "roots", "signals_n", "pc_days_total", "pc_diag",
                                             "raw_outside_n", "sig_span", "wk_note")},
                             "period": per,
                             "judged": judged, "last_run": lastrun,
                             # 판정 건수/대상 — 0 이면 '단계는 성공인데 왕복이 전부 실패' 를 화면이 구분한다
                             "judged_n": judged_n, "judged_total": judged_total,
                             # 판정 기록의 실패·부분·중단·복구(S1-12) — 있는 키만. 배너가 한 줄로 붙인다
                             "judged_issues": judged_issues,
                             # 스텁 판정 표식 — 화면·얼린 사본 모두 이 값으로 배너를 그린다(테스트 전용)
                             "stub": bool(stub_note), "stub_note": stub_note,
                             "stub_env": bool(os.environ.get(STUB_MARK)),
                             # 수집만 하고 분석을 안 한 상태 — 이때는 묶음도 워크플로우도
                             # 생기지 않는다. 눌러 봐야 아는 대신 화면이 먼저 말하게 한다.
                             "collected_only": (not rows) and _has_collected(),
                             # 기간 끝이 오늘·미래인 결과의 가용 해석용 — 오늘 날짜와 분석 시각(mm_meta mtime).
                             # 투입·가용은 mine 이 분석 시각의 now 로 확정한 값이라 화면에서 다시 재지 않는다
                             # (보는 시각으로 가용만 늘리면 투입과 어긋난다). 산정 근거 노트가 이 값을 읽는다.
                             "today": time.strftime("%Y-%m-%d"),
                             "as_of": (time.strftime("%Y-%m-%d %H:%M", time.localtime(_mtime(mp)))
                                       if mp and _mtime(mp) else ""),
                             # 화면에 보이는 것이 '지금 이 PC 의 이번 결과'인지 알린다
                             "stale": bool(JOB["running"]),
                             "foreign": bool(lastrun.get("host")
                                             and lastrun["host"] != os.environ.get("COMPUTERNAME", "")),
                             "total": round(sum(r.get("mm") or 0 for r in rows), 2)})
        elif self.path in ("/guide", "/docs"):
            # 팀 배포용 사용 안내 — 파일을 따로 챙기지 않아도 화면에서 바로 열리게
            gp = os.path.join(ROOT, "docs", "사용안내.html")
            try:
                with open(gp, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(200, ("<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic'\">"
                                 r"<h3>사용 안내 파일이 없습니다</h3><p>docs\사용안내.html 이 "
                                 "함께 복사됐는지 FILES.txt 로 확인하세요.</p></body>"
                                 ).encode(), "text/html; charset=utf-8")
        elif self.path == "/team":
            self._send(200, TEAM_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/sharedir":
            d = (cfg().get("teamShareDir") or "").strip()
            eff, used, prob, ln = team_share_ex()
            st = teamserver_status()
            store = st.get("store") or ""
            self._send(200, {"dir": d, "exists": bool(d and os.path.isdir(d)),
                             "effective": eff, "used": used, "problem": prob,
                             "local": os.path.join(ROOT, "teamdata"), "local_members": ln,
                             # 받는 자리와 보는 자리가 다르면 화면이 먼저 말해야 한다
                             "store": store,
                             "split": bool(store and os.path.normcase(os.path.abspath(store))
                                           != os.path.normcase(os.path.abspath(eff)))})
        elif self.path == "/api/team":
            share, used, prob, ln = team_share_ex()
            local = os.path.join(ROOT, "teamdata")
            if prob == "unreachable":
                # 예전에는 여기서 말없이 teamdata 로 갈아탔다 — 명단이 통째로 바뀌어 보였다
                self._send(200, {"error": "share_unreachable", "share": share, "used": used,
                                 "dir": share, "local": local, "local_members": ln,
                                 # 배너가 이미 폴더를 보여 준다 — 여기서는 다음 수만 말한다
                                 "hint": (f"이 PC 의 teamdata 에는 {ln}명이 있습니다 — "
                                          "그쪽을 보려면 아래 버튼을 누르세요." if ln else
                                          "경로·권한·네트워크 연결을 확인하세요.")})
                return
            if not share or not os.path.isdir(share):
                self._send(200, {"error": "no share", "local": local, "local_members": ln,
                                 "hint": "위 [팀 공유폴더] 칸에 취합 폴더를 넣고 저장하세요. "
                                         "이 PC 에서 팀 서버를 돌렸다면 teamdata 폴더를 넣으면 됩니다."})
                return
            try:
                sys.path.insert(0, ROOT)
                import aggregate as agg
                data = agg.collect_team_data(share)
                data["share"] = share
                data["used"] = used
                # 팀 통합 보고서(정적 파일) 유무·생성 시각 — 화면의 [열기] 버튼 활성 근거
                fp = os.path.join(share, TEAM_FILES["/team/full"])
                try:
                    data["full"] = {
                        "exists": os.path.exists(fp),
                        "at": (time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
                               if os.path.exists(fp) else ""),
                        "v3": os.path.exists(os.path.join(share, TEAM_FILES["/team/full_v3"]))}
                except OSError:
                    data["full"] = {"exists": False, "at": "", "v3": False}
                if not data["members"]:
                    same = os.path.normcase(os.path.abspath(share)) == \
                        os.path.normcase(os.path.abspath(local))
                    self._send(200, {"error": "no members", "share": share, "used": used,
                                     "dir": share, "local": local,
                                     # 통합 보고서 파일 유무는 인원과 무관하다 — 화면의 [열기] 버튼
                                     # 활성 근거를 이 분기에서도 준다(빠지면 버튼이 기본값으로 눌렸다)
                                     "full": data["full"],
                                     "local_members": 0 if same else ln,
                                     "hint": f"{share} 안에 <이름>\\member.json 이 있는 폴더가 없습니다. "
                                             "각자 화면의 [공유폴더로 저장]을 쓰면 member.json 까지 만들어집니다."
                                             + (f"  ·  이 PC 의 teamdata 에는 {ln}명이 있습니다."
                                                if ln and not same else "")})
                    return
                self._send(200, data)
            except Exception as e:
                self._send(200, {"error": f"{type(e).__name__}: {e}"})
        elif self.path in TEAM_FILES:
            # 정적 보고서 4종 — 바이트 그대로 + CSP sandbox(origin 분리) + nosniff
            name = TEAM_FILES[self.path]
            share = team_share()[0]
            p = os.path.join(share, name) if share else ""
            if p and os.path.exists(p):
                try:
                    with open(p, "rb") as f:
                        body = f.read()
                    self._send(200, body, "text/html; charset=utf-8", headers=REPORT_HEADERS)
                except OSError:
                    self._send(500, {"error": "read fail"})
            else:
                if self.path.startswith("/team/full"):
                    msg = ("<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic'\">"
                           "<h3>팀 통합 보고서가 아직 없습니다</h3>"
                           "<p>[팀 취합 화면]의 [다시 만들기]를 누르거나, 팀원이 [팀 서버 업로드]를 하면 "
                           "자동으로 만들어집니다(취합 폴더의 team_full_report.html).<br>"
                           "config.teamShareDir 설정과 팀원들의 내보내기가 선행돼야 합니다.</p></body>")
                else:
                    msg = ("<meta charset='utf-8'><body style=\"font-family:'Malgun Gothic'\">"
                           "<h3>팀 취합 결과가 아직 없습니다</h3>"
                           "<p>대시보드의 [팀 취합] 버튼을 누르거나 LoadMonitor30-팀취합.bat 을 실행하세요.<br>"
                           "config.teamShareDir 설정과 팀원들의 내보내기가 선행돼야 합니다.</p></body>")
                self._send(200, msg.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/teamserver":
            self._send(200, teamserver_status())
        elif self.path == "/api/teamupload":
            # 실패를 '대기 없음'으로 보여 주면, 쌓여 있는 묶음을 못 보내게 막는 셈이다(검증 확정).
            # 모를 때는 pending 을 null 로 주고 화면이 '확인 실패'라고 말하게 한다.
            st, err = None, ""
            try:
                # 먼저 이 프로세스 안에서 직접 읽는다 — 외부 프로세스는 제한 시간·인코딩·백신에
                # 걸려 '모름' 이 되고, 그 '모름' 이 화면에서 '없음' 으로 둔갑한다(실측 제보).
                if ROOT not in sys.path:        # 요청마다 쌓이지 않게
                    sys.path.insert(0, ROOT)
                import teamup as _tu
                st = {**_addr_payload(),
                      "share": (cfg().get("teamShareDir") or "").strip(),
                      # [분석 실행] 끝 자동 보고 켬 — run.py 와 같은 한 함수(config.teamUpload.autoReport · 기본 켬)
                      "auto": _tu.auto_report_on(cfg()),
                      # LM30 시험판 보호 — 시험용 팀 서버 주소를 정하기 전이면 그 사유(teamup.upload_guard 한 곳 · 아니면 "")
                      "guard": _tu.upload_guard(cfg()),
                      "pending": _tu.list_pending(), "sent": _tu.list_sent(),
                      "available": _tu.buildable()}
            except Exception as e:                # 임포트가 안 되면 예전 방식으로
                st, err = None, f"{type(e).__name__}: {str(e)[:80]}"
            try:
                if st is not None:
                    raise _Done()
                p = subprocess.run([sys.executable, os.path.join(ROOT, "teamup.py"),
                                    "--list", "--json"], capture_output=True, timeout=60, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                lines = [x for x in (p.stdout or b"").decode("utf-8", "replace").splitlines() if x.strip()]
                if lines:
                    try:
                        st = json.loads(lines[-1])
                    except ValueError:
                        st = None
                if not isinstance(st, dict) or "pending" not in st:
                    st = None
                    tail = ((p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                            or (lines[-1:] if lines else []))
                    err = (tail[-1][:150] if tail else f"teamup.py 응답 없음 (rc={p.returncode})")
            except _Done:
                err = ""
            except subprocess.TimeoutExpired:
                err = "teamup.py 가 60초 안에 응답하지 않았습니다"
            except OSError as e:
                err = f"teamup.py 실행 실패({type(e).__name__})"
            if st is None:
                self._send(200, {**_addr_payload(), "ok": False, "error": err, "pending": None, "sent": [],
                                 "share": (cfg().get("teamShareDir") or "").strip()})
            else:
                st["ok"] = True
                self._send(200, st)
        elif self.path == "/api/teamreport":
            # LM28 — 마지막 팀 서버 보고 결과(report\team_report_status.json: run.py 자동 보고 · teamup 버튼/공유폴더 '다 보냄').
            # 화면이 실패 알림(끝난 실행 1번당 1번)·배너(다음 성공까지)를 여기서 정한다. 얼린 보고서는 이 길을 굽지 않는다
            # (freeze.FREEZE_EPS 밖 — 사유 원문이 공유되는 사본에 굳지 않게).
            try:
                if ROOT not in sys.path:
                    sys.path.insert(0, ROOT)
                import teamup as _tu
                self._send(200, {"ok": True, "report": _tu.read_report_status(REPORT),
                                 "auto": _tu.auto_report_on(cfg())})
            except Exception as e:  # noqa: BLE001 - 모르면 '모름' — 화면은 배너를 띄우지 않는다
                self._send(200, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}"})
        elif self.path == "/api/attendance":
            # LM30(2026-10-18) 출퇴근·시간외 근무 카드 — 이 PC 의 report\ 파일만 읽는다(attendance_view). 얼린 사본에는 합계만 굳는다.
            try:
                self._send(200, attendance_view())
            except Exception as e:  # noqa: BLE001 - 카드 하나가 화면을 죽이지 않게(까닭은 카드에 한 줄)
                self._send(200, {"ok": False, "hint": f"출퇴근 자료를 읽지 못했습니다({type(e).__name__}) — [분석 실행]을 "
                                                      "한 번 더 하면 다시 만들어집니다."})
        elif self.path == "/api/gerp":
            # LM30(2026-10-19) GERP 근무 기록 읽기(시험 기능 · 기본 꺼짐) — 카드의 단추·상태 한 줄 재료(gerp_view). 얼린 사본에는 굽지 않는다.
            try:
                self._send(200, gerp_view())
            except Exception as e:  # noqa: BLE001 - 카드 한 줄이 화면을 죽이지 않게(화면은 아무것도 그리지 않는다)
                self._send(200, {"ok": False, "error": f"{type(e).__name__}"})
        elif self.path == "/api/leave_days":
            # LM30(2026-10-21) '휴가 날짜' 칸(유급휴가 — core\attendance 머리말 22) — 저장한 날짜를 읽기만. 얼린 사본에는 굽지 않는다.
            try:
                self._send(200, leave_days_view())
            except Exception as e:  # noqa: BLE001 - 칸 하나가 화면을 죽이지 않게(화면은 칸을 그리지 않는다)
                self._send(200, {"ok": False, "error": f"{type(e).__name__}"})
        elif self.path == "/api/ui_prefs":
            # LM30(2026-10-25) 화면 표시 설정('0.04 MM 이하 숨기기' — config ui.hideSmallMM · 없으면 켜짐). 얼린 사본에는 굽지 않는다.
            self._send(200, ui_prefs_view())
        elif self.path in ("/api/pc_import", "/api/pc_import?refresh=1"):
            # LM30(2026-10-21) 예전 판 PC 가동 기록 가져오기 — 찾은 폴더·지난 가져오기(pc_import_view — 읽기만). 얼린 사본에는 굽지 않는다.
            try:
                self._send(200, pc_import_view(refresh=self.path.endswith("refresh=1")))
            except Exception as e:  # noqa: BLE001 - 이 줄 하나가 화면을 죽이지 않게
                self._send(200, {"ok": False, "error": f"{type(e).__name__}"})
        elif self.path == "/api/projects":
            import projmap
            self._send(200, {"projects": projmap.load_user_projects(ROOT)})
        elif self.path == "/api/workflow":
            out = {"ok": False, "stage_note": _stage_note("워크플로우 분석"),
                   "stage_kind": _stage_kind("워크플로우 분석")}
            sp = latest_signals()
            if sp:
                tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
                out["tag"] = tag
                wp = os.path.join(REPORT, f"workflow_{tag}.json")
                if os.path.exists(wp):
                    try:
                        out = json.load(open(wp, encoding="utf-8-sig"))
                        if not isinstance(out, dict):
                            out = {"ok": False, "error": "파일 손상", "file_error": f"workflow_{tag}.json 의 최상위가 객체가 아닙니다"}
                    except (OSError, ValueError) as e:
                        out = {"ok": False, "error": "파일 손상",
                               "file_error": f"workflow_{tag}.json 을 읽지 못함({type(e).__name__}) — [워크플로우 재분석]으로 다시 만드세요"}
                    out["tag"] = tag
                    try:                     # 읽기 경계 스냅 — 옛 workflow_*.json 의 스냅 전 상위 이름
                        import details as _dsn
                        for _fl in (out.get("flows") or []):
                            if isinstance(_fl, dict) and _fl.get("level1"):
                                _fl["level1"] = _dsn.snap1(_fl["level1"]) or _fl["level1"]
                    except Exception:  # noqa: BLE001
                        pass
                    out["stage_note"] = _stage_note("워크플로우 분석")
                    out["stage_kind"] = _stage_kind("워크플로우 분석", tag)
                    # 판정 뒤 업무 로드가 다시 추출됐으면(무AI 재실행 등) 이 결과는 옛 행 기준이다(V-01) — 지우지 않고 표시
                    if _reextracted(tag):
                        out["reextracted"] = True
                        out["reextracted_note"] = ("이 워크플로우는 마지막 업무 로드 재추출 이전의 행으로 판정한 것입니다 — "
                                                   "과제·담당업무 이름이 지금 화면과 어긋날 수 있습니다")
                else:
                    # 결과가 '없는' 것과 '다른 기간 것만 있는' 것은 다르다 — 화면이 구분해 말하게 한다
                    other = sorted(glob.glob(os.path.join(REPORT, "workflow_*.json")))
                    if other:
                        ot = os.path.basename(other[-1])[len("workflow_"):-len(".json")]
                        if ot != tag:
                            out["other_tag"] = ot
                    out["stage_kind"] = _stage_kind("워크플로우 분석", tag)      # 이 기간의 상태 파일이 있으면 그것으로
                # 결과가 없거나 흐름이 비었으면 상태 파일의 중단 사유(stop.reason·error/hint·stop.kind)를 싣는다 — 화면이 빨간 줄로
                # 먼저 말한다(진단 D: 사유가 상태 파일에만 있고 화면은 '분석이 없습니다' 뿐이었다)
                _flows = out.get("flows")
                if not (isinstance(_flows, list) and _flows):
                    out.update(_stage_why(tag, "flow"))
            with LOCK:
                # 수동 실행의 마지막 결과(ok/error/hint)와 '지금 도는 중' — 새로고침해도 화면이 사유를 다시 말한다
                out["manual"] = MANUAL.get("flow")
                out["running"] = bool(JOB["running"] and JOB["step"] == TOOL_JOBS["flow"][1])
                out["busy"] = JOB["step"] if JOB["running"] else ""
            self._send(200, out)
        elif self.path == "/api/agentic":
            # LM29부터 — Agentic AI 니즈 후보만. LM28 이 남긴 파일의 과제 매칭(match)·오할당(misassigned)은 화면에 보내지 않는다.
            out = {"analysis": None, "stage_note": _stage_note("Agentic 니즈 발굴"),
                   "stage_kind": _stage_kind("Agentic 니즈 발굴")}
            sp = latest_signals()
            if sp:
                tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
                out["tag"] = tag
                ap = os.path.join(REPORT, f"agentic_{tag}.json")
                if os.path.exists(ap):
                    try:
                        a = json.load(open(ap, encoding="utf-8-sig"))
                        if isinstance(a, dict):
                            out["analysis"] = agentic_view(a)
                            out["stage_kind"] = _stage_kind("Agentic 니즈 발굴", tag)
                            # 판정 뒤 업무 로드가 다시 추출됐으면(무AI 재실행 등) 이 후보는 옛 행 기준이다(V-01) — 지우지 않고 표시
                            if _reextracted(tag):
                                out["reextracted"] = True
                                out["reextracted_title"] = "재추출 이후 결과"
                                out["reextracted_note"] = ("이 니즈 후보는 마지막 업무 로드 재추출 이전의 행으로 찾은 것입니다 — "
                                                           "[니즈 후보 발굴 실행]으로 갱신하세요")
                        else:
                            out["file_error"] = (f"agentic_{tag}.json 의 최상위가 객체가 아닙니다 — "
                                                 "[니즈 후보 발굴 실행]으로 다시 만드세요")
                    except (OSError, ValueError) as e:
                        out["file_error"] = (f"agentic_{tag}.json 을 읽지 못함({type(e).__name__}) — "
                                             "[니즈 후보 발굴 실행]으로 다시 만드세요")
                else:
                    other = sorted(glob.glob(os.path.join(REPORT, "agentic_*.json")))
                    if other:
                        ot = os.path.basename(other[-1])[len("agentic_"):-len(".json")]
                        if ot != tag:
                            out["other_tag"] = ot
                    out["stage_kind"] = _stage_kind("Agentic 니즈 발굴", tag)
                    out.update(_stage_why(tag, "agentic"))
            with LOCK:
                out["manual"] = MANUAL.get("agentic")
                out["running"] = bool(JOB["running"] and JOB["step"] == TOOL_JOBS["agentic"][1])
                out["busy"] = JOB["step"] if JOB["running"] else ""
            self._send(200, out)
        elif self.path == "/api/extra":
            # 리뷰 본문과 같은 signals 파일의 tag를 앵커로 — 서로 다른 분석 기간의
            # pivots/내러티브/체계가 한 화면에 섞이지 않게 한다
            out = {}
            sp = latest_signals()
            tag = os.path.basename(sp)[len("signals_"):-len(".csv")] if sp else ""
            if tag:
                out["tag"] = tag
                for key, name in (("pivots", f"pivots_{tag}.json"),
                                  ("entities", f"entities_{tag}.json")):
                    p = os.path.join(REPORT, name)
                    if os.path.exists(p):
                        try:
                            with open(p, encoding="utf-8") as f:
                                out[key] = json.load(f)
                        except (OSError, ValueError):
                            pass
                # 월별 코멘트 — 이 기간 파일의 달 + 빠진 달은 다른 기간 파일에서(core/narratives.load_merged — judge·리포트와
                # 같은 이월 규칙 · 이월한 달은 from_tag). 예전에는 이 기간 파일이 '없을 때만' 가장 최근 파일 하나로 대신해,
                # 오늘 파일에 몇 달만 있으면 나머지 달이 화면에서 빠졌다(제보: '월간 리뷰 코멘트가 사라짐'). 기간 밖의 달
                # (작년 12월 등)은 섞지 않는다.
                try:
                    import narratives as _nv
                    nv = _nv.load_merged(REPORT, tag, months=_nv.period_months(tag))
                except Exception:  # noqa: BLE001 - 모듈이 없는 판·판독 실패 — 이 기간 파일만(예전 방식) · 리뷰 탭을 막지 않게
                    nv = {}
                    try:
                        with open(os.path.join(REPORT, f"ai_narratives_{tag}.json"), encoding="utf-8-sig") as f:
                            _v = json.load(f)
                        nv = {k: x for k, x in _v.items() if isinstance(x, dict)} if isinstance(_v, dict) else {}
                    except (OSError, ValueError):
                        pass
                if nv:
                    out["narratives"] = nv
                    if all(v.get("from_tag") for v in nv.values()):
                        out["narratives_alt_tag"] = next(iter(nv.values()))["from_tag"]
            # ── 일관성: 피벗의 MM 숫자는 대시보드와 '같은 파일'에서 다시 계산한다 ──
            # judge 시점 pivots JSON은 refine(행 병합·비업무 제거·재정규화) 이전 값이라
            # 대시보드(refined 우선)와 어긋난다 — 실측: 상세리뷰 '개발' MM이 대시보드 초과.
            # 에피소드·엔티티는 신호 수준 산물이라 JSON을 유지하고, MM 표 3종만 재계산.
            _fn2, _rows2 = result_rows()
            # tag 가드 — result_rows 는 태그 무관 '최신 정제본 우선'이라, 이전 기간의
            # 정제본이 남아 있으면 다른 기간의 MM 표가 이 화면(tag 앵커)에 섞인다(검증 확정).
            # 같은 기간 파일일 때만 재계산하고, 아니면 judge 시점 pivots(그 tag)를 그대로 둔다.
            if _rows2 and tag and tag in _fn2 and isinstance(out.get("pivots"), dict):
                bm, bw, dm = {}, {}, {}
                for r in _rows2:
                    md = (r.get("Level 2") or "공통").strip() or "공통"
                    dt = (r.get("Level 3") or "기타").strip() or "기타"
                    wt = (r.get("유형") or "사무").strip() or "사무"
                    v = float(r.get("mm") or 0)
                    m = bm.setdefault(md, {"mm": 0.0, "worktypes": {}, "details": {}})
                    m["mm"] += v
                    m["worktypes"][wt] = m["worktypes"].get(wt, 0.0) + v
                    m["details"][dt] = m["details"].get(dt, 0.0) + v
                    w2 = bw.setdefault(wt, {"mm": 0.0, "models": {}})
                    w2["mm"] += v
                    w2["models"][md] = w2["models"].get(md, 0.0) + v
                    dm.setdefault(dt, {})[md] = dm.setdefault(dt, {}).get(md, 0.0) + v
                srt = lambda d2: dict(sorted(d2.items(), key=lambda kv: -kv[1]))  # noqa: E731
                out["pivots"]["by_model"] = {
                    k: {"mm": v["mm"], "worktypes": srt(v["worktypes"]),
                        "details": dict(list(srt(v["details"]).items())[:10])}
                    for k, v in sorted(bm.items(), key=lambda kv: -kv[1]["mm"])}
                out["pivots"]["by_worktype"] = {
                    k: {"mm": v["mm"], "models": srt(v["models"])}
                    for k, v in sorted(bw.items(), key=lambda kv: -kv[1]["mm"])}
                out["pivots"]["common"] = sorted(
                    [{"detail": dt, "models": sorted(ms, key=lambda m2: -ms[m2]),
                      "mm": round(sum(ms.values()), 3)}
                     for dt, ms in dm.items()
                     if len([m2 for m2 in ms if m2 != "공통"]) >= 2],
                    key=lambda x: -x["mm"])[:12]
                out["pivots"]["consistent_with"] = _fn2
            self._send(200, out)
        elif self.path.startswith("/api/review"):
            g = "week"
            if "g=month" in self.path:
                g = "month"
            elif "g=all" in self.path:
                g = "all"
            self._send(200, {"gran": g, "groups": review(g)})
        elif self.path.startswith("/api/collect_status"):
            # 수집 현황 카드 — 원장 축별 일수·last_run rc/reason/counts·OWA 날짜만 비율(파일만 읽는다)
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            self._send(200, collect_status_payload((q.get("from") or [""])[0], (q.get("to") or [""])[0]))
        elif self.path.startswith("/api/data"):
            src = (self.path.split("src=")[-1] if "src=" in self.path else "files")
            pats = {"mail": "outlook/mail.csv", "cal": "outlook/calendar.csv",
                    "files": "files/files.csv", "recent": "files/recent.csv",
                    "git": "files/git_commits.csv", "pc": "pc/pc_on.csv",
                    "teams": "m365/teams_*.csv", "act": "activity/activity_*.csv"}
            rows, cols, fns = [], [], []
            _pat = pats.get(src, "files/files.csv")
            # 창 샘플러(act)는 이 PC 의 상태 — 나머지 원본은 본 PC + 추가PC\* 를 함께 보인다(추이·분석과 같은 뿌리)
            for f in (sorted(glob.glob(os.path.join(DATA, _pat))) if src == "act" else _paths_multi(_pat)):
                rs = _rows(f)
                if rs:
                    fns.append(os.path.basename(f))
                    cols = cols or list(rs[0].keys())
                    rows += rs
            total = len(rows)                       # 자르기 '전' 실제 수집량 — 400 고정 오인 방지
            rows = rows[-400:][::-1]
            if src == "teams":
                # 팀즈 웹이 날짜만 짚은 행(time_precision=date)의 12:00 은 자리표다 — 시각으로 읽히지 않게 날짜만(LM28 E)
                for r in rows:
                    if str(r.get("time_precision") or "").strip() == "date":
                        r["time"] = str(r.get("time") or "")[:10]
            fn = fns[0] if len(fns) == 1 else (f"{len(fns)}개 파일" if fns else "")
            self._send(200, {"file": fn, "cols": cols[:8], "rows": [
                {c: str(r.get(c, ""))[:90] for c in cols[:8]} for r in rows],
                "total": total, "shown": len(rows)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/run":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"error": "bad json"})
                return
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"error": "busy"})
                    return
                if self._freezing():        # 보고서 굽는 중 — run.py 가 report\ 를 다시 쓰면 사본이 반쪽이 된다
                    return
                JOB.update(running=True, log=[], step="", started=time.time())
            threading.Thread(target=run_job, args=(b.get("from"), b.get("to"),
                                                   bool(b.get("ai")), bool(b.get("skip")),
                                                   bool(b.get("collect_only"))),
                             daemon=True).start()
            self._send(200, {"ok": True})
        elif self.path == "/api/projects":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"error": "bad json"})
                return
            import projmap
            saved = projmap.save_user_projects(ROOT, b.get("projects") or [])
            self._send(200, {"ok": True, "projects": saved})
        elif self.path in ("/api/teamup", "/api/teamfolder", "/api/teamping"):
            # 사람이 '지금 이 망에서' 누른 것 — 자동 보고는 [분석 실행] 끝에서 run.py 가 같은 teamup.py --upload 로 한다
            # (LM28). 팀 서버는 특정 망에서만 닿으므로 거기서 못 보낸 묶음을 여기서 보낸다. teamup.py 가 --json 으로
            # 마지막 줄에 결과를 주므로 건별 성공/실패를 그대로 화면에 돌려준다(다 보내면 teamup 이 보고 상태에 '성공' 을 남긴다).
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            # v5: 보낼 주소는 설치 폴더의 config\team_server.json(LoadMonitor30-팀서버주소.bat 에서만 바꾼다).
            # 화면이 보낸 주소는 받지도 저장하지도 않는다 — teamup.py 가 같은 설정을 읽는다.
            cmd = [sys.executable, os.path.join(ROOT, "teamup.py"), "--json"]
            # LM28 — 팀 서버 쪽 상한은 teamup 이 스스로 지킨다(연결 확인 3초×2 · 답 45초 · 늦거나 끊기면 남은 묶음 멈춤 ·
            # 새 묶음은 75초까지만 시작). 여기 상한은 설정을 가장 길게 잡았을 때(연결 확인 34초 · 업로드 2분 남짓)의 안전판이다
            # (예전 업로드 1800초 — 느린 서버 앞에서 버튼이 30분 동안 '업로드 중' 이었다)
            if self.path == "/api/teamping":
                cmd += ["--ping"]
                timeout, step = 45, ""
            elif self.path == "/api/teamfolder":
                cmd += ["--to-folder", str(b.get("share") or "")]
                timeout, step = 600, "공유폴더 저장"
            else:
                cmd += ["--upload"]
                timeout, step = 180, "팀 서버 업로드"
            if step:
                with LOCK:
                    if JOB["running"]:
                        self._send(409, {"ok": False, "error": "busy"})
                        return
                    JOB.update(running=True, step=step)
            try:
                p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                            PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
                txt = (p.stdout or b"").decode("utf-8", "replace").strip()
                lines = [x for x in txt.splitlines() if x.strip()]
                res = {}
                if lines:
                    try:
                        res = json.loads(lines[-1])
                    except ValueError:
                        res = {}
                    for ln in lines[:-1] if res else lines:
                        log(ln)
                if not isinstance(res, dict):
                    res = {}
                res.setdefault("ok", p.returncode == 0)
                self._send(200, res)
            except subprocess.TimeoutExpired:
                _lim = f"{timeout // 60}분" if timeout % 60 == 0 else f"{timeout}초"     # 연결 확인 45초가 '0분' 으로 찍히지 않게
                self._send(200, {"ok": False, "error": f"{_lim} 안에 끝나지 않았습니다 — 묶음은 그대로 대기합니다"})
            except OSError as e:
                self._send(200, {"ok": False, "error": f"실행 실패({type(e).__name__})"})
            finally:
                if step:
                    with LOCK:
                        JOB.update(running=False, step="")
        elif self.path == "/api/teamserver":
            # 팀 취합 서버를 이 PC 에서 켜고 끈다 — bat 을 찾아 실행하지 않아도 되게.
            # 대시보드를 닫아도 서버는 계속 돈다(팀이 쓰는 것이라 일부러 살려 둔다).
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            act = str(b.get("action") or "")
            force = bool(b.get("force"))        # [포트 가져오기] — 확인 창을 거친 요청
            try:
                confirm_pid = int(b.get("confirm_pid") or 0)
            except (TypeError, ValueError):
                confirm_pid = 0
            port = _team_port()
            if act == "start":
                st0 = teamserver_status()
                if st0["running"]:
                    self._send(200, dict(st0, note="이미 켜져 있습니다"))
                    return
                if st0.get("occupied"):
                    # 여기서 '켜져 있다' 고 답하면 업로드가 남의 폴더로 들어가 버린다(실측 증상)
                    occ = st0.get("occupant") or []
                    kind = st0.get("kind") or "unknown"
                    take = st0.get("take") or "no"
                    who = " / ".join(f"{x['name']} (pid {x['pid']})" for x in occ) or "(확인 불가)"
                    fr = st0.get("foreign_root") or ""
                    if kind == "other_lm":
                        msg = (f"포트 {port} 은 다른 폴더의 팀 서버가 쓰고 있습니다: {fr}\n"
                               f"저장 위치: {st0.get('other_store') or '(알 수 없음)'}\n"
                               f"프로세스: {who}\n"
                               "지금 업로드하면 그 폴더로 들어갑니다.")
                    elif kind == "legacy_lm":
                        # 사용자가 본 그 문구의 진짜 정체 — 남이 아니라 우리 구버전이다
                        msg = (f"포트 {port} 은 예전 버전(LM18·LM19 형식)의 LoadMonitor 팀 서버가 "
                               f"쓰고 있습니다 — {who}\n"
                               "예전 버전에는 원격 종료 기능이 없어 화면에서 곱게 닫을 수 없습니다. "
                               "그 검은 창을 닫거나, 아래 [포트 가져오기] 를 쓰세요.")
                    elif kind == "hidden":
                        lo, hi = _dyn_range()
                        rsv = _port_reserved(port)
                        msg = (f"포트 {port} 이 막혀 있는데 붙잡고 있는 서버가 없습니다.")
                        if rsv:
                            msg += (f"\n윈도우 예약 포트 범위({rsv})에 들어 있어 이 번호는 쓸 수 "
                                    "없습니다 — LoadMonitor30-팀서버주소.bat 에서 포트를 다른 번호로 바꾸세요.")
                        elif lo and lo <= port <= hi:
                            msg += (f"\n이 PC 의 임시 포트 범위가 {lo}~{hi} 이고 {port} 이 그 안에 "
                                    "듭니다 — 다른 프로그램이 '바깥으로 연결' 하며 잠깐 쓴 것입니다. "
                                    "잠시 뒤 다시 누르거나, LoadMonitor30-팀서버주소.bat 에서 번호를 " + str(max(hi + 1, _alt_port_base()))
                                    + " 처럼 그 범위 밖으로 바꾸면 다시 생기지 않습니다.")
                        else:
                            msg += "\n잠시 뒤 다시 시도하거나 LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요."
                    elif kind == "unreadable":
                        msg = (f"포트 {port} 이 쓰이고 있는데 무엇이 쥐고 있는지 확인하지 못했습니다"
                               " (권한 또는 보안 프로그램). LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요.")
                    else:
                        msg = (f"포트 {port} 을 LoadMonitor 가 아닌 프로그램이 쓰고 있습니다 — {who}")
                        if occ and occ[0].get("exe"):
                            msg += f"\n실행 파일: {occ[0]['exe']}"
                        if occ and occ[0].get("cmd"):
                            msg += f"\n명령줄: {occ[0]['cmd'][:160]}"
                        msg += ("\n무엇인지 모르겠으면 죽이지 마세요 — 사내 보안·백업 프로그램일 수 "
                                "있습니다. LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸는 편이 안전합니다.")
                    if not force:
                        if take == "no" and kind in ("legacy_lm", "other_lm", "unknown"):
                            # LM28: 다른 폴더(LM24 포함)·구버전·남의 프로그램은 끄지 않는다 — 대체 포트를 제안만(W3-08)
                            alt = int(st0.get("suggest_port") or 0)
                            msg += ("\n\n이 화면은 그 프로그램을 끄지 않습니다(같은 PC 의 LM24 팀 서버일 수 있습니다)."
                                    + (f" 따로 켜려면 LoadMonitor30-팀서버주소.bat 에서 포트를 {alt} 처럼 비어 있는 번호로"
                                       " 바꾸세요 — 팀원도 같은 주소로 맞춰야 합니다." if alt else
                                       " 따로 켜려면 LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요."))
                            bad = [x for x in occ if x["protected"]]
                            if bad and any(x["self"] for x in bad):
                                msg += ("\n\n[!] 그 프로세스는 이 대시보드 자신입니다 — "
                                        "팀 서버 포트와 대시보드 포트가 같습니다. "
                                        "LoadMonitor30-팀서버주소.bat 에서 포트를 다른 번호로 바꾸세요.")
                            elif bad:
                                msg += ("\n\n이 프로그램은 강제로 끝낼 수 없습니다 "
                                        "(시스템 프로세스이거나 다른 계정 소유) — "
                                        "그 계정에서 닫거나 LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요.")
                        log("[팀 서버] 시작 거절 — " + msg.splitlines()[0])
                        self._send(200, {"ok": False, "error": msg, "occupied": True,
                                         "port": port, "running": False, "kind": kind,
                                         "occupant": occ, "take": take})
                        return
                    # ── 여기부터 [포트 가져오기] — 확인 창을 거친 요청만 온다 ──
                    if take == "no":
                        self._send(200, {"ok": False, "occupied": True, "running": False,
                                         "kind": kind, "occupant": occ, "take": take,
                                         "error": f"강제로 끝낼 수 없는 프로세스입니다 — {who}. "
                                                  "LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요."})
                        return
                    if take == "confirm_pid" and confirm_pid not in [x["pid"] for x in occ]:
                        # LoadMonitor 가 아닌 것을 죽이려면 pid 를 직접 입력해야 한다
                        self._send(200, {"ok": False, "occupied": True, "running": False,
                                         "kind": kind, "occupant": occ, "take": take,
                                         "error": "PID 확인이 일치하지 않습니다 — 목록의 PID 를 "
                                                  "그대로 입력해야 진행합니다."})
                        return
                    steps, fails = [], []
                    # 정체가 확인된 LoadMonitor 에만 정상 종료를 청한다 — 남의 프로그램에
                    # /api/shutdown 을 쏘면 그쪽의 전혀 다른 기능을 건드릴 수 있다
                    if kind in ("legacy_lm", "other_lm") and _ts_ask_shutdown(port):
                        steps.append("정상 종료 요청")
                        _ts_wait_closed(port)
                    if _port_open(port):
                        now = _listeners(port) or []        # 죽이기 직전에 다시 확인한다
                        for x in occ:
                            if x["pid"] not in now:
                                steps.append(f"pid {x['pid']} 는 이미 없음")
                                continue
                            if x["protected"]:
                                continue
                            okk, rc, why = _kill(x["pid"])
                            steps.append(f"{x['name']}(pid {x['pid']}) 종료"
                                         + ("" if okk else f" 실패(코드 {rc})"))
                            if not okk:
                                fails.append(f"{x['name']}(pid {x['pid']}): {why}")
                        _ts_wait_closed(port)
                    log("[팀 서버] 포트 가져오기 — " + (", ".join(steps) or "대상 없음"))
                    if _port_open(port):
                        rsv = _port_reserved(port)
                        self._send(200, {"ok": False, "occupied": True, "running": False,
                                         "error": (f"포트 {port} 을 가져오지 못했습니다.\n"
                                                   + ("\n".join(fails) if fails else
                                                      "종료했는데도 포트가 열려 있습니다.")
                                                   + (f"\n윈도우 예약 포트 범위({rsv})입니다 — "
                                                      "번호를 바꾸세요." if rsv else
                                                      "\n다른 계정이 띄웠다면 그 계정에서 닫아야 "
                                                      "합니다."))})
                        return
                try:
                    os.makedirs(REPORT, exist_ok=True)
                    # 받는 곳과 보는 곳을 못박는다 — 서버는 teamShareDir 를 우선 쓴다
                    if not str(cfg().get("teamShareDir") or "").strip():
                        _save_cfg("teamShareDir", os.path.join(ROOT, "teamdata"))
                    flags = NO_WIN
                    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
                    # LM28(2026-10-19): 기록 파일은 팀 서버(자식)가 물려받은 제 핸들로 쓴다 — 대시보드 쪽 사본은 띄우자마자 닫는다.
                    # 예전에는 열어 둔 채 두어 [데이터 리셋]마다 teamserver.log 1개를 '다른 프로그램이 쓰는 중'으로 못 지웠다고 말했다.
                    with open(TS_LOG, "a", encoding="utf-8") as lf:
                        pr = subprocess.Popen([sys.executable, os.path.join(ROOT, "teamserver.py"),
                                               "--port", str(port)], cwd=ROOT, stdout=lf,
                                              stderr=subprocess.STDOUT, creationflags=flags,
                                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                    with open(TS_PID, "w", encoding="utf-8") as f:
                        f.write(str(pr.pid))
                except OSError as e:
                    self._send(200, {"ok": False, "error": f"실행 실패({type(e).__name__})"})
                    return
                for _ in range(40):                 # 최대 20초 — 포트가 열릴 때까지
                    if _port_open(port):
                        break
                    time.sleep(0.5)
                # 윈도우는 살아 있는 리스너 위에 덧바인딩을 허용한다(SO_REUSEADDR, 실측) —
                # '포트가 열렸다' 도 'bind 가 됐다' 도 소유의 증거가 아니다. 응답하는 쪽의
                # pid 가 방금 내가 띄운 그 pid 인지 확인해야 한다. 아니면 내가 띄운 것을
                # 내가 정리하고 실패로 말한다(유령 서버를 남기지 않는다).
                who = _ts_identity(port)
                if _port_open(port) and pr.pid and int(who.get("pid") or 0) != pr.pid:
                    _kill(pr.pid)
                    log("[팀 서버] 시작 취소 — 다른 서버가 계속 응답합니다")
                    self._send(200, {"ok": False, "running": False, "occupied": True,
                                     "port": port,
                                     "error": "포트를 넘겨받지 못했습니다 — 먼저 잡고 있던 서버가 "
                                              "계속 응답합니다. 방금 띄운 것은 정리했습니다.\n"
                                              "그 서버 창을 직접 닫거나 LoadMonitor30-팀서버주소.bat 에서 포트를 바꾸세요."})
                    return
                st = teamserver_status()
                log("[팀 서버] " + ("시작됨 · " + (st["urls"][0] if st["urls"] else f"포트 {port}")
                                  if st["running"] else "시작 실패 — report\\teamserver.log 확인"))
                self._send(200, st)
            elif act == "stop":
                # 예전에는 '우리가 띄운 pid 파일' 하나에만 기댔다 — bat 으로 띄웠거나
                # 데이터 리셋으로 파일이 지워졌으면 아무것도 죽이지 않고 실패만 알렸다.
                st0 = teamserver_status()
                if st0.get("occupied"):
                    fr = st0.get("foreign_root") or ""
                    occ = st0.get("occupant") or []
                    who = " / ".join(f"{x['name']} (pid {x['pid']})" for x in occ) or "(확인 불가)"
                    log("[팀 서버] 중지 거절 — 이 폴더의 서버가 아닙니다")
                    self._send(200, dict(st0, error=(
                        f"포트 {port} 의 서버는 이 폴더 것이 아닙니다 — {who}"
                        + (f"\n설치 폴더: {fr}" if fr else "")
                        + "\n그 창에서 직접 닫거나, [팀 서버 시작] 의 [포트 가져오기] 를 쓰세요.")))
                    return
                how = []
                if _port_open(port) and _ts_ask_shutdown(port):
                    how.append("정상 종료 요청")
                    _ts_wait_closed(port)
                if _port_open(port):
                    # pid 파일은 낡을 수 있다(창을 X 로 닫으면 정리 코드가 돌지 않는다) —
                    # 지금 이 순간 그 포트를 쥔 프로세스를 다시 읽어 그 안에 있을 때만 쓴다.
                    lis = _listeners(port) or []
                    saved = 0
                    try:
                        with open(TS_PID, encoding="utf-8") as f:
                            saved = int((f.read() or "0").strip() or 0)
                    except (OSError, ValueError):
                        saved = 0
                    for x in _proc_info(lis):
                        if x["protected"]:
                            how.append(f"{x['name']}(pid {x['pid']}) 는 끝낼 수 없음")
                            continue
                        if not (x["teamserver"] or x["pid"] == saved):
                            how.append(f"pid {x['pid']} 는 팀 서버가 아니어서 건드리지 않음")
                            continue
                        okk, rc, _why = _kill(x["pid"])   # /T 는 쓰지 않는다 — 대상은 이 하나다
                        how.append(f"강제 종료(pid {x['pid']})" + ("" if okk else f" 실패({rc})"))
                    _ts_wait_closed(port)
                st = teamserver_status()
                if not _port_open(port):
                    try:
                        os.remove(TS_PID)
                    except OSError:
                        pass
                done = not _port_open(port)
                log("[팀 서버] " + ("중지됨" + (f" ({', '.join(how)})" if how else "")
                                  if done else "중지 실패 — 다른 계정이 띄웠을 수 있습니다"))
                self._send(200, dict(st, running=not done, error="" if done else
                                     f"포트 {port} 이 아직 열려 있습니다 — 다른 계정이 띄웠다면 "
                                     "그 계정에서 닫아야 합니다"))
            else:
                self._send(400, {"ok": False, "error": "action 은 start/stop"})
        elif self.path == "/api/teambuild":
            # 결과는 있는데 묶음이 없을 때 — 지금 결과로 묶음을 만든다(실측 제보 대응)
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                b = {}
            flag = "--build-latest" if b.get("latest") else "--build-all"
            try:
                p = subprocess.run([sys.executable, os.path.join(ROOT, "teamup.py"), "--json", flag],
                                   capture_output=True, timeout=300, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                lines = [x for x in (p.stdout or b"").decode("utf-8", "replace").splitlines() if x.strip()]
                res = json.loads(lines[-1]) if lines else {"ok": False, "error": "응답 없음"}
                for ln in lines[:-1]:
                    log(ln)
                self._send(200, res)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                self._send(200, {"ok": False, "error": "묶음 생성 실패"})
        elif self.path == "/api/teamdrop":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            try:
                p = subprocess.run([sys.executable, os.path.join(ROOT, "teamup.py"), "--json",
                                    "--drop", str(b.get("tag") or "")],
                                   capture_output=True, timeout=60, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                lines = [x for x in (p.stdout or b"").decode("utf-8", "replace").splitlines() if x.strip()]
                res = json.loads(lines[-1]) if lines else {"ok": False, "error": "응답 없음"}
                log("[팀 업로드] 묶음 버림: " + str(b.get("tag") or ""))
                self._send(200, res)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                self._send(200, {"ok": False, "error": "버리기 실패"})
        elif self.path == "/api/teamopen":
            try:
                d = os.path.join(REPORT, "upload_pending")
                os.makedirs(d, exist_ok=True)
                subprocess.Popen(["explorer", d], creationflags=NO_WIN)
            except OSError:
                pass
            self._send(200, {"ok": True})
        elif self.path in ("/api/workflow", "/api/agentic"):
            # 수동 재분석 — [분석 실행]과 같은 백그라운드 방식(tool_job). 시간 제한 없이 자식의 왕복 타임아웃에
            # 맡기고, 화면은 /api/status 의 진행률을 보다가 끝나면 GET 으로 결과·사유(manual)를 읽는다.
            # body {"wait": true} 면 옛 방식처럼 끝까지 기다려 마지막 JSON 을 돌려준다(시험 하네스·스크립트용),
            # {"redo": true} 면 이어서 하지 않고 처음부터.
            kind = "flow" if self.path == "/api/workflow" else "agentic"
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except Exception:
                b = {}
            if not isinstance(b, dict):
                b = {}
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy",
                                     "hint": f"'{JOB['step'] or '분석'}' 이(가) 실행 중입니다 — 끝난 뒤(상단 상태바 '대기') 다시 누르세요"})
                    return
                if self._freezing():        # agentic_/workflow_ JSON 을 다시 쓴다 — 굽는 중에는 막는다
                    return
                JOB.update(running=True, step=TOOL_JOBS[kind][1], started=time.time(),
                           phase="", done=0, total=0)
            th = threading.Thread(target=tool_job, args=(kind, ["--redo"] if b.get("redo") else []), daemon=True)
            th.start()
            if b.get("wait"):
                th.join()
                with LOCK:
                    self._send(200, dict(MANUAL.get(kind) or {"ok": False, "error": "결과 없음"}))
            else:
                self._send(200, {"ok": True, "started": True, "kind": kind, "step": TOOL_JOBS[kind][1]})
        elif self.path == "/api/exclude":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                if self._freezing():        # signals·mm_rows 를 다시 쓴다 — 굽는 중에는 막는다
                    return
                JOB.update(running=True, step="오할당 제외 재집계")
            try:
                self._send(200, exclude_work(str(b.get("row") or "")))
            finally:
                with LOCK:
                    JOB.update(running=False, step="")
        elif self.path == "/api/sharedir":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            new_dir = str(b.get("dir") or "").strip().strip('"')
            cp = os.path.join(ROOT, "config", "config.json")
            with LOCK:                      # 분석·리셋과의 동시 쓰기 방지
                try:
                    c = json.load(open(cp, encoding="utf-8-sig"))
                except (OSError, ValueError) as e:
                    self._send(200, {"ok": False, "error": f"config 읽기 실패: {e}"})
                    return
                c["teamShareDir"] = new_dir
                tmp = cp + ".tmp"
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    json.dump(c, f, ensure_ascii=False, indent=2)
                os.replace(tmp, cp)
            exists = bool(new_dir and os.path.isdir(new_dir))
            log(f"[설정] 팀 공유폴더 = {new_dir or '(비움)'}"
                + ("" if exists or not new_dir else "  ← 경로가 아직 접근되지 않음(저장은 됨)"))
            self._send(200, {"ok": True, "dir": new_dir, "exists": exists})
        elif self.path == "/api/team_refine":
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                JOB.update(running=True, step="팀 유사 항목 정리")
            try:
                # 화면과 같은 폴더를 보게 인자로 넘긴다(설정이 비어도 teamdata 폴백을 공유)
                sh = team_share()[0]
                cmd = [sys.executable, os.path.join(ROOT, "team_refine.py")] + ([sh] if sh else [])
                # Copilot 왕복 예산(>=900s)에 형식 이탈 재질의까지 감안 — 예전 420초는
                # 정상 왕복을 끊고 응답 없이 연결을 닫아 '알 수 없는 오류'로 보였다(검증 확정).
                # LM22: 정리 ≤3회 + 통합 보고서 캐시(계열·과제분류·세부·후보) 왕복까지 이어지므로 60분.
                # 넘겨도 그때까지의 결과는 캐시에 남아 '다시 누르면 이어서' 가 성립한다.
                run = chat_job_run()         # LM30 — 이 작업이 연 Copilot 채팅을 한 실행으로 묶는다(끝 한 줄 — job_chat_end)
                p = subprocess.run(cmd, capture_output=True, timeout=3600, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                            PYTHONUNBUFFERED="1", LM_CHAT_RUN=run), creationflags=NO_WIN)
                txt = (p.stdout or b"").decode("utf-8", "replace").strip()
                err = (p.stderr or b"").decode("utf-8", "replace").strip()
                for ln in txt.splitlines():
                    if ln and not ln.startswith("{"):
                        log(ln)
                job_chat_end(run, "팀 유사 항목 정리")     # LM30 — 이 작업이 연 Copilot 채팅을 지우고 한 줄
                try:
                    self._send(200, json.loads(txt.splitlines()[-1]))
                except Exception:
                    # 자식이 죽으면 사유는 stderr 에 있다 — 빈 힌트를 주지 않는다
                    tail = (err or txt).strip().splitlines()
                    self._send(200, {"ok": False, "error": "정리 프로그램이 응답을 주지 못했습니다",
                                     "hint": (tail[-1][:200] if tail else f"종료 코드 {p.returncode}")})
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "error": "시간 초과",
                                 "hint": "60분 안에 끝나지 않았습니다 — 그때까지의 정리는 저장돼 있으니 "
                                         "Copilot 창이 응답하는지 확인한 뒤 다시 누르면 이어서 정리합니다."})
            except OSError as e:
                self._send(200, {"ok": False, "error": f"실행 실패({type(e).__name__})"})
            finally:
                with LOCK:
                    JOB.update(running=False, step="")
        elif self.path == "/api/aggregate":
            # 선택 본문 {"snapshot": true} → 통합 보고서 타임스탬프 사본도(옛 무본문 호출 호환).
            # 409 를 보내기 전에 본문을 소진한다 — 안 읽고 닫으면 브라우저가 응답 대신 리셋을 본다.
            snap = False
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(n) if n else b""
            except (ValueError, OSError):
                raw = b""
            if raw.strip():
                try:
                    b = json.loads(raw)
                except ValueError:
                    # 다른 핸들러(/api/run·exclude·teamport)와 같은 답 — 깨진 본문으로 취합을 돌리지
                    # 않는다(예전에는 조용히 '스냅샷 없음'으로 실행됐다). 본문은 이미 읽었으니 리셋 없음.
                    self._send(400, {"ok": False, "error": "bad json"})
                    return
                snap = bool(b.get("snapshot")) if isinstance(b, dict) else False
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                JOB.update(running=True, step="팀 취합")
            try:
                sh = team_share()[0]
                p = subprocess.run([sys.executable, os.path.join(ROOT, "aggregate.py")]
                                   + ([sh] if sh else []) + (["--snapshot"] if snap else []),
                                   capture_output=True, timeout=180, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                            PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
                txt = (p.stdout or b"").decode("utf-8", "replace").strip()
                for ln in txt.splitlines():
                    if ln and not ln.startswith("{"):
                        log(ln)
                try:
                    self._send(200, json.loads(txt.splitlines()[-1]))
                except Exception:
                    # 자식이 죽으면 사유는 stderr 에 있다 — 버리면 빈 힌트만 남는다
                    _err = (p.stderr or b"").decode("utf-8", "replace").strip()
                    _tail = (_err or txt).strip().splitlines()
                    self._send(200, {"ok": False, "error": "출력 해석 실패",
                                     "hint": (_tail[-1][:200] if _tail else f"종료 코드 {p.returncode}")})
            except subprocess.TimeoutExpired:
                # 응답 없이 끊으면 화면은 원인을 영영 모른다
                self._send(200, {"ok": False, "error": "시간 초과",
                                 "hint": "aggregate.py 이(가) 제한 시간 안에 끝나지 않았습니다 — 진행 로그를 확인하세요."})
            except OSError as _e:
                self._send(200, {"ok": False, "error": f"실행 실패({type(_e).__name__})"})
            finally:
                with LOCK:
                    JOB.update(running=False, step="")
        elif self.path == "/api/retag":
            # 재분류 동안 JOB을 점유해 [분석 실행]과의 동시 파일 쓰기를 차단한다
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                if self._freezing():        # signals·mm_rows 를 다시 쓴다 — 굽는 중에는 막는다
                    return
                JOB.update(running=True, step="지정 반영 재분류")
            try:
                p = subprocess.run([sys.executable, os.path.join(ROOT, "retag.py")],
                                   capture_output=True, timeout=180, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
                txt = (p.stdout or b"").decode("utf-8", "replace").strip()
                for ln in txt.splitlines():
                    if ln:
                        log(ln)
                try:
                    res = json.loads(txt.splitlines()[-1])
                except Exception:
                    res = None
                if not isinstance(res, dict):
                    # 자식이 죽으면 사유는 stderr 에 있다 — 버리면 빈 힌트만 남는다
                    _err = (p.stderr or b"").decode("utf-8", "replace").strip()
                    _tail = (_err or txt).strip().splitlines()
                    self._send(200, {"ok": False, "error": "retag 출력 해석 실패",
                                     "hint": (_tail[-1][:200] if _tail else f"종료 코드 {p.returncode}")})
                    return
                self._send(200, res)
            except subprocess.TimeoutExpired:
                # 응답 없이 끊으면 화면은 원인을 영영 모른다
                self._send(200, {"ok": False, "error": "시간 초과",
                                 "hint": "retag.py 이(가) 제한 시간 안에 끝나지 않았습니다 — 진행 로그를 확인하세요."})
            except OSError as _e:
                self._send(200, {"ok": False, "error": f"실행 실패({type(_e).__name__})"})
            finally:
                with LOCK:
                    JOB["running"] = False
                    JOB["step"] = ""
        elif self.path == "/api/stop":
            with LOCK:
                was = JOB["running"]
                had_pid = bool(JOB.get("pid"))
            # 정리 중 예외가 나도 반드시 응답해야 한다 — 응답이 안 나가면 [중지] 버튼이
            # disabled 인 채로 영구히 남아 사용자가 다시 누를 수 없다.
            # LM28: 전용 Edge 는 CDP 로 우리가 띄운 것만 닫는다(로그인 대기 중이면 두고 — P6). powershell 을 띄우지 않는다.
            for fn2 in (kill_job, lambda: close_edge("ui_stop", budget=UI_SWEEP_SEC)):
                try:
                    fn2()
                except Exception as e:
                    log(f"[중지] {getattr(fn2, '__name__', '정리')} 실패({type(e).__name__}) — 계속 진행")
            if had_pid:
                log("[중지] 사용자 요청으로 분석을 중단했습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
            elif was:
                # 팀 취합·리포트·재분류 등 짧은 동기 작업은 pid 를 추적하지 않아 못 죽인다 —
                # "중단했습니다"라고 거짓 기록하지 않는다
                log("[중지] 지금 도는 작업은 중간 중단을 지원하지 않습니다 — 곧 끝나면 멈춥니다")
            self._send(200, {"ok": True, "stopped": was and had_pid})
        elif self.path == "/api/reset":
            # LM28(2026-10-19): 본문은 try 안에서 읽는다 — 깨졌거나 dict 가 아니면 {}(예전에는 dict 가 아닌 본문이 try 밖의 b.get 에서 죽어
            # JOB 이 '데이터 리셋' 실행 중으로 굳었다). what 은 all|report 만 받는다(아니면 400 + 까닭). JOB 은 어느 길로 끝나도 비운다.
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                b = json.loads(self.rfile.read(n) or b"{}") if n > 0 else {}
            except (ValueError, OSError):
                b = {}
            if not isinstance(b, dict):
                b = {}
            what = str(b.get("what") or "report")          # report | all
            if what not in ("all", "report"):
                self._send(400, {"ok": False, "error": "bad what",
                                 "hint": "리셋 범위는 'all'(수집 데이터+결과) 또는 'report'(분석 결과만)만 받습니다 — "
                                         "화면을 새로고침(F5)한 뒤 다시 누르세요"})
                return
            with LOCK:
                if JOB["running"]:
                    # 무엇이 돌고 있는지 말한다(LM28 2026-10-19) — 예전에는 '작업 실행 중' 한 마디라 무엇을 기다려야 하는지 몰랐다
                    step = str(JOB.get("step") or "")
                    self._send(409, {"ok": False, "error": "busy", "step": step, "hint": reset_busy_hint(step)})
                    return
                if self._freezing():        # 굽는 중에 report\ 를 지우면 사본이 반쪽·실패가 된다
                    return
                JOB.update(running=True, step="데이터 리셋")
            removed = kept_nar = 0
            failed, det, err = [], {}, ""
            try:
                # 아직 못 보낸 팀 업로드 묶음은 기본 보존 · '분석 결과만' 이면 월별 리뷰 코멘트도 보존(reset_files)
                removed, kept_nar = reset_files(what, keep_queue=not b.get("drop_queue"), failed=failed, detail=det)
            except Exception as e:  # noqa: BLE001 - 리셋 중 오류는 화면에 까닭으로 돌려준다(예전에는 연결이 끊겨 '리셋 실패'만 떴다)
                err = f"{type(e).__name__}: {e}"[:200]
            finally:
                try:
                    hold, ts_kept = det.get("holders") or {}, [x for x in (det.get("kept") or []) if x in TS_FILES]
                    log(f"[리셋] {'수집 데이터+결과' if what == 'all' else '분석 결과'} {removed}개 파일 삭제"
                        " (Copilot 로그인 세션·채팅 기록은 유지)"
                        + (f" (월별 리뷰 코멘트 {kept_nar}개 파일은 보존 — 지우려면 수집 데이터+결과 리셋)" if kept_nar else "")
                        + (" (AI 판정 기록 judge_cache.json 은 보존 — 다음 분석이 이미 판정한 신호를 다시 묻지 않는다)"
                           if what != "all" and os.path.isfile(os.path.join(REPORT, "judge_cache.json")) else "")
                        + (f" (팀 서버 파일 {'·'.join(ts_kept)} 은 보존 — 팀 서버가 쓰는 파일)" if ts_kept else "")
                        + (f" · 바로 가기 연결(정션) {len(det.get('links') or [])}개는 따라 들어가지 않음(그 너머는 지우지 않는다)"
                           if det.get("links") else "")
                        + (f" · 못 지운 파일 {len(failed)}개 — " + ", ".join(
                            (f"{x}({hold[x]})" if x in hold else x) for x in failed[:3]) if failed else "")
                        + (f" · 오류: {err}" if err else ""))
                except Exception:  # noqa: BLE001 - 기록 한 줄 때문에 JOB 이 '실행 중' 으로 굳지 않게
                    pass
                with LOCK:
                    JOB.update(running=False, step="")
            hold, why = det.get("holders") or {}, det.get("reasons") or {}
            body = {"removed": removed, "what": what, "kept_narratives": kept_nar,
                    "failed": failed[:20], "n_failed": len(failed),
                    # LM28(2026-10-19) 못 지운 파일을 열고 있는 프로그램 · 못 읽은 폴더의 까닭(failed 의 상대 경로가 열쇠)
                    "holders": {k: hold[k] for k in failed[:20] if k in hold},
                    "reasons": {k: why[k] for k in failed[:20] if k in why},
                    "kept": det.get("kept") or [], "links": len(det.get("links") or [])}
            if err:
                self._send(200, dict(body, ok=False, error="failed", hint=f"리셋 중 오류 — {err}"))
                return
            self._send(200, dict(body, ok=True))
        elif self.path == "/api/report":
            # 보고서 3종(리포트·분석리포트·얼린 보고서) — in-process freeze.make_all. JOB 을 점유하지
            # 않고(얼린 사본에 '실행 중'이 굳는다) FREEZE_LOCK 으로만 직렬화; 분석 중이면 409.
            if not FREEZE_LOCK.acquire(blocking=False):
                self._send(409, {"ok": False, "error": "busy",
                                 "hint": "보고서를 이미 만드는 중입니다 — 잠시 뒤 다시 누르세요"})
                return
            try:
                # 잠근 '뒤에' JOB 을 본다 — 먼저 보면 그 틈에 /api/run 이 끼어들어 굽는 도중 report\ 가
                # 다시 써진다(run·narrate·reset·exclude·retag 는 LOCK 안에서 FREEZE_LOCK 을 본다 — _freezing)
                with LOCK:
                    busy = bool(JOB["running"])
                if busy:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                self._send(200, make_reports())
            finally:
                FREEZE_LOCK.release()
        elif self.path == "/api/reset_cursors":
            # [커서 초기화] — 다음 수집이 기간 전체를 처음부터 읽게(수집한 행은 그대로). 분석 중에는 하지 않는다.
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy", "hint": "분석·웹 읽기가 끝난 뒤 누르세요"})
                    return
            gone, led_ok = reset_cursors_local()
            log("[커서 초기화] " + ("커서 " + ", ".join(gone) if gone else "커서 파일 없음")
                + (" · 원장 초기화" if led_ok else " · 원장 없음") + " — 다음 [분석 실행]이 기간 전체를 다시 읽습니다")
            self._send(200, {"ok": True, "removed": gone, "ledger": led_ok})
        elif self.path == "/api/worklog":
            # 수동 기록 폼(W1-19) — PC 밖 업무(출장·현장)를 화면에서. data\manual\worklog.csv(Add-WorkLog.ps1 과 같은 열)
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
                row = add_worklog(b if isinstance(b, dict) else {})
            except (ValueError, OSError) as e:
                self._send(200, {"ok": False, "error": str(e)[:200]})
                return
            log(f"[수동 기록] {row['date']} {row['category']} {row['hours']}h"
                + (f" {row['start']}~{row['end']}" if row["start"] else "") + " — 다음 분석부터 반영됩니다")
            self._send(200, {"ok": True, "row": row})
        elif self.path in ("/api/owa", "/api/teamsweb"):
            # [Outlook 웹 읽기]·[팀즈 웹 읽기] — LM28: 수집기를 직접 부르지 않고 run.py --web-only 로(화면 기간 · G1 정제 ·
            # 출처 병합 · 원장 · Edge 정리 · login_pending 이 한 번에). 분석 중에는 하지 않는다(전용 Edge 를 함께 쓴다 — F-16).
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                b = {}
            kind = "mail" if self.path == "/api/owa" else "teams"
            d0, d1 = web_period((b or {}).get("from"), (b or {}).get("to"))
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy",
                                     "hint": "분석·다른 작업이 도는 중에는 웹 읽기를 하지 않습니다(전용 Edge 를 함께 씁니다) — 끝난 뒤 누르세요"})
                    return
                if self._freezing():
                    return
                JOB.update(running=True, step=("Outlook 웹 읽기" if kind == "mail" else "팀즈 웹 읽기"),
                           started=time.time())
            try:
                self._send(200, web_read(kind, d0, d1))
            finally:
                with LOCK:
                    JOB.update(running=False, step="", pid=0)
        elif self.path == "/api/gerp_open":
            # LM30(2026-10-19) [GERP 열기(직접 로그인)] — 전용 Edge 에 GERP 화면을 연다(로그인은 사람이). 작업 중에는 하지 않는다(같은 Edge).
            # 본문은 쓰지 않지만 먼저 읽는다 — 읽지 않은 채 409 로 닫으면 Windows 가 연결을 끊어(RST) 화면이 답을 못 받을 때가 있다
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > 0:
                self.rfile.read(n)
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy",
                                     "hint": "분석·다른 작업이 도는 중에는 열지 않습니다(전용 Edge 를 함께 씁니다) — 끝난 뒤 누르세요"})
                    return
            self._send(200, gerp_open())
        elif self.path == "/api/pc_import":
            # LM30(2026-10-21) [예전 판 PC 가동 기록 가져오기] — 이 프로세스 안에서 가져온다(pc_import_run — 원장 잠금 · 같은 행은 건너뜀 ·
            # 그 폴더에는 쓰지 않는다). 분석이 도는 동안에는 하지 않는다(409 — 수집이 같은 원장에 쓴다)
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                b = {}
            with LOCK:
                busy = bool(JOB["running"])
            if busy:
                self._send(409, {"ok": False, "error": "busy",
                                 "hint": "분석·다른 작업이 도는 중에는 가져오지 않습니다 — 끝난 뒤 누르세요"})
                return
            try:
                self._send(200, pc_import_run(b))
            except Exception as e:  # noqa: BLE001 - 실패 까닭은 한 줄로
                self._send(200, {"ok": False, "error": f"가져오지 못했습니다({type(e).__name__})"})
        elif self.path == "/api/leave_days":
            # LM30(2026-10-21) '휴가 날짜' 칸 [저장](유급휴가 — core\attendance 머리말 22) — data\근태\휴가_직접입력.csv 만 갈아 쓴다(이 PC 에만).
            # 작업이 도는 동안에는 쓰지 않는다(409 — 분석이 그 파일을 읽는다). 본문은 LEAVE_BODY_MAX 까지 — 넘으면 읽어 담지 않고 버린 뒤
            # 400(큰 본문을 메모리에 올리지 않는다 · 끝까지 비워야 브라우저가 응답 대신 리셋을 보지 않는다). 날짜는 로그에 싣지 않는다(일수만)
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                n = -1
            if n < 0 or n > LEAVE_BODY_MAX:
                left = min(max(n, 0), LEAVE_DRAIN_MAX)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                self._send(400, {"ok": False, "error": "글이 너무 깁니다"})
                return
            raw = self.rfile.read(n) if n > 0 else b""
            try:
                b = json.loads(raw or b"{}")
            except ValueError:
                b = None
            if not (isinstance(b, dict) and isinstance(b.get("text"), str)):
                # 칸 글(text)이 없는 본문으로 저장하지 않는다 — 빈 글('')이 '모두 지우기'라 깨진 본문이 파일을 지우면 안 된다
                self._send(400, {"ok": False, "error": "본문을 읽지 못했습니다"})
                return
            with LOCK:
                busy = bool(JOB["running"])
            if busy:
                self._send(409, {"ok": False, "error": "busy", "hint": LEAVE_BUSY_HINT})
                return
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy", "hint": LEAVE_BUSY_HINT})
                    return
                st, ans = leave_days_save(b)
            if ans.get("log"):
                log(ans.pop("log"))                      # LOCK 밖에서(log 가 LOCK 을 잡는다)
            self._send(st, ans)
        elif self.path == "/api/project_split":
            # LM30(2026-10-27) 워크플로우 탭 '이름 병합' 표의 [분리] — config\project_aliases.json 에 두 과제 이름을 never 로 적고 둘을 잇는
            # map 항목을 지운다(이 PC 의 파일 · 프로세스 없음). 작업이 도는 동안에는 쓰지 않는다(409 — 워크플로우가 그 파일을 읽고 쓴다).
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                n = -1
            if n < 0 or n > SPLIT_BODY_MAX:
                left = min(max(n, 0), LEAVE_DRAIN_MAX)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                self._send(400, {"ok": False, "error": "본문이 너무 깁니다"})
                return
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n > 0 else {}
            except ValueError:
                b = None
            if not (isinstance(b, dict) and isinstance(b.get("a"), str) and isinstance(b.get("b"), str)):
                self._send(400, {"ok": False, "error": "나눌 두 과제 이름을 읽지 못했습니다 — 화면을 새로 고친 뒤 다시 누르세요"})
                return
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy", "hint": SPLIT_BUSY_HINT})
                    return
                try:
                    import details as _dsp
                    ans = _dsp.split_project_pair(b["a"], b["b"], path=os.path.join(ROOT, "config", "project_aliases.json"))
                except OSError:
                    ans = {"ok": False, "error": "config 폴더의 project_aliases.json 을 쓰지 못했습니다 — 다른 프로그램이 열고 있으면 닫고 다시 누르세요"}
            if ans.get("ok"):
                log("[워크플로우] 과제 이름 병합 1건을 나눴습니다 — 다음 [워크플로우 재분석]부터 따로 보입니다")
            self._send(400 if ans.pop("bad", False) else 200, ans)
        elif self.path == "/api/ui_prefs":
            # LM30(2026-10-25) 옵션 줄 '0.04 MM 이하 숨기기' 칸(팀 취합 화면에도 같은 칸) — config\config.json 의 ui.hideSmallMM 만 고친다(이 PC 의
            # 개인 설정 · BOM·다른 키·설명 키 그대로 — _save_cfg_many). 화면 표시만 바꾸는 값이라 분석이 도는 중에도 받는다(분석·보고서는 이 값을
            # 읽지 않는다). 본문은 UI_PREFS_BODY_MAX 까지 — 넘으면 읽어 담지 않고 버린 뒤 400 · 값이 참·거짓이 아니면 400(파일은 그대로).
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n < 0 or n > UI_PREFS_BODY_MAX:
                left = min(max(n, 0), LEAVE_DRAIN_MAX)
                while left > 0:
                    chunk = self.rfile.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                self._send(400, {"ok": False, "error": "본문이 너무 깁니다"})
                return
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n > 0 else {}
            except ValueError:
                b = None
            if not (isinstance(b, dict) and isinstance(b.get("hideSmallMM"), bool)):
                self._send(400, {"ok": False, "error": "켜기·끄기 값을 읽지 못했습니다 — 화면을 새로 고친 뒤 다시 누르세요"})
                return
            on = b["hideSmallMM"]
            with LOCK:                          # 같은 파일을 쓰는 다른 단추(GERP 켜기·끄기)와 겹쳐 한쪽 값을 잃지 않게
                wrote = _save_cfg_many([(("ui", "hideSmallMM"), on)])
            if not wrote:
                self._send(200, {"ok": False, "hideSmallMM": hide_small_on(cfg()),
                                 "error": "config\\config.json 을 쓰지 못했습니다 — 메모장 같은 다른 프로그램이 열고 있으면 닫고 다시 누르세요"})
                return
            self._send(200, {"ok": True, "hideSmallMM": on,
                             "msg": "0.04 MM 이하 항목을 숨깁니다" if on else "모든 항목을 보입니다"})
        elif self.path == "/api/gerp_config":
            # LM30(2026-10-19) GERP 근무 기록 읽기 [켜기]·[끄기]·[주소 바꾸기](카드) — config\config.json 의 attendance.gerp.enabled·url 만
            # 고친다(이 PC 의 개인 설정 — 팀 서버 주소 같은 팀 공통 값이 아니다 · BOM·다른 키 그대로 · gerp_config_check 가 검사).
            # 작업이 도는 동안에는 바꾸지 않는다(409). 주소는 로그·오류 글에 싣지 않는다(답의 gerp.url 은 주소 칸을 채우는 데만).
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                b = None
            busy_hint = "분석·다른 작업이 도는 중에는 GERP 설정을 바꾸지 않습니다 — 끝난 뒤 누르세요"
            with LOCK:
                busy = bool(JOB["running"])
            if busy:
                self._send(409, {"ok": False, "error": "busy", "hint": busy_hint})
                return
            import attendance as _att
            cur = cfg()
            prev_on = bool(_att.norm_gerp(cur)[0]["enabled"])
            ups, err = gerp_config_check(b, cur)
            if err:
                self._send(400, {"ok": False, "error": err})
                return
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy", "hint": busy_hint})
                    return
                wrote = _save_cfg_many(ups)
            if not wrote:
                self._send(200, {"ok": False, "gerp": gerp_view(),
                                 "error": "config\\config.json 을 쓰지 못했습니다 — 메모장 같은 다른 프로그램이 열고 있으면 닫고 다시 누르세요"})
                return
            g = gerp_view()
            if not g["enabled"]:
                msg = "GERP 근무 기록 읽기를 껐습니다"
            elif prev_on and "url" in b:
                msg = "GERP 주소를 바꿨습니다"
            else:
                msg = "GERP 근무 기록 읽기를 켰습니다"
            log(f"[GERP] {msg} — 주소는 이 PC의 config\\config.json 에만 둡니다")
            self._send(200, {"ok": True, "msg": msg, "gerp": g})
        elif self.path == "/api/gerp_read":
            # LM30(2026-10-19) [GERP 근무 기록 읽기] — 다른 웹 읽기 단추와 같은 작업(run.py --web-only gerp · JOB · Edge 정리). 시험 기능 —
            # 꺼져 있으면 띄우지 않는다. 답에 카드 재료(gerp — 상태 한 줄)를 함께 싣는다.
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                b = {}
            b = b if isinstance(b, dict) else {}
            import attendance as _att
            import gerp as _gp
            g = _att.norm_gerp(cfg())[0]
            if not g["on"]:
                self._send(200, {"ok": False, "error": "GERP 근무 기록 읽기가 꺼져 있거나 주소가 비어 있습니다(config attendance.gerp)",
                                 "gerp": gerp_view()})
                return
            d0, d1 = web_period(b.get("from"), b.get("to"))
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy",
                                     "hint": "분석·다른 작업이 도는 중에는 읽지 않습니다(전용 Edge 를 함께 씁니다) — 끝난 뒤 누르세요"})
                    return
                if self._freezing():
                    return
                JOB.update(running=True, step="GERP 근무 기록 읽기", started=time.time())
            try:
                r = web_read("gerp", d0, d1, timeout=_gp.timeout_sec(g) + 120)
            finally:
                with LOCK:
                    JOB.update(running=False, step="", pid=0)
            try:
                r["gerp"] = gerp_view()
            except Exception:  # noqa: BLE001 - 상태 줄이 없어도 결과는 보낸다
                pass
            self._send(200, r)
        elif self.path == "/api/prepmove":
            # 정리 작업은 TEMP 로 복사된 스크립트가 한다 — 이 폴더 안에서 돌리면
            # 그 스크립트 자신이 폴더를 잡아 '옮길 수 있는가' 확인이 항상 실패한다.
            ps1 = os.path.join(ROOT, "tools", "Prepare-Move.ps1")
            if not os.path.exists(ps1):
                self._send(200, {"ok": False, "error": "tools\\Prepare-Move.ps1 이 없습니다"})
                return
            try:
                import shutil as _sh
                import tempfile as _tf
                tmp = os.path.join(_tf.gettempdir(), "LM30-Prepare-Move.ps1")   # LM24·LM28·LM29 의 사본과 겹치지 않게
                _sh.copy2(ps1, tmp)
                # 새 콘솔 창으로 띄운다 — 사용자가 결과를 봐야 하고, 우리가 죽어도 살아남아야 한다
                flags = 0x00000010                       # CREATE_NEW_CONSOLE (DETACHED 는 쓰지 않는다 —
                #                                          그것을 섞으면 자식이 아무것도 실행하지 않고 즉사한다)
                subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                  "-File", tmp, "-Root", ROOT],
                                 creationflags=0x00000010, close_fds=True)
                log("[이동 준비] 정리 창을 띄웠습니다 — 대시보드는 곧 종료됩니다")
                self._send(200, {"ok": True, "flags": flags})
            except OSError as e:
                self._send(200, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"})
        elif self.path == "/api/collectdiag":
            # 수집 진단 — 이 PC 의 Outlook·Teams 버전/상태에서 무엇이 막혔는지를 한 장으로.
            # PC 마다 Outlook(클래식/새 Outlook/2016 마법사)·Teams(클래식/새 Teams·지역 형식)가 달라
            # 메일·팀즈가 비는데 개발자는 그 PC 를 못 본다 — 사실만 모아 report\collect_diag.txt 에
            # 남긴다(채팅·메일 내용은 마스킹). COM 은 '붙기'만 시도하므로 마법사 무한 대기가 없다.
            outp = os.path.join(REPORT, "collect_diag.txt")
            try:                                # 지난 보고서가 이번 실패를 가리지 않게 먼저 지운다
                os.remove(outp)
            except OSError:
                pass
            try:
                r2 = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                     os.path.join(ROOT, "collect", "Diagnose-Collectors.ps1"),
                                     "-OutFile", outp],
                                    capture_output=True, timeout=240, cwd=ROOT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                txt = (r2.stdout or b"").decode("utf-8", "replace")
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "error": "4분 내 끝나지 않음 (Outlook 응답 대기 의심)"})
                return
            except OSError as e:
                self._send(200, {"ok": False, "error": f"진단 스크립트 실행 실패({type(e).__name__})"})
                return
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
            self._send(200, {"ok": r2.returncode == 0 and os.path.exists(outp), "verdict": verdict, "path": outp,
                             "text": "\n".join(lines)[-6000:]})
        elif self.path == "/api/diag":
            # 30초 안에 '판정이 가능한 상태인가'만 확인한다 — 분석 전체를 돌릴 필요 없이
            # 사용자가 스스로 원인(로그인 만료·모델 선택·차단)을 알 수 있게.
            import tempfile
            pf = os.path.join(tempfile.gettempdir(), lmname.TMP_PREFIX + "diag_prompt.txt")   # LM24 와 겹치지 않게
            try:
                with open(pf, "w", encoding="utf-8") as f:
                    f.write("연결 확인용 질문입니다. 아래 JSON 한 줄만 그대로 출력하세요.\n"
                            '{"ok":"연결됨"}\n')
                # --retire(LM28): 진단 채팅은 한 번 묻고 끝나므로 왕복 뒤 바로 Copilot 대화 목록에서 지운다(우리가 연 채팅만) —
                # 결과 한 줄(chats — 숫자·사유)이 알림 창에 나온다(현장 사진 한 장으로 삭제 흐름을 확인)
                r2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"),
                                     "--send", pf, "--fresh", "--retire"], capture_output=True, timeout=300,
                                    cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                    creationflags=NO_WIN)
                txt = (r2.stdout or b"").decode("utf-8", "replace").strip()
                try:
                    res = json.loads(txt.splitlines()[-1])
                except Exception:
                    res = {"ok": False, "phase": "driver", "error": "드라이버 출력 해석 실패",
                           "hint": txt[-200:] or "출력 없음"}
            except subprocess.TimeoutExpired:
                res = {"ok": False, "phase": "timeout", "error": "5분 내 응답 없음",
                       "hint": "전용 Edge 창이 응답을 생성 중인지 확인하세요"}
            except OSError as e:
                res = {"ok": False, "phase": "spawn", "error": f"드라이버 실행 실패({type(e).__name__})",
                       "hint": str(e)[:150]}
            log("[진단] Copilot 왕복 " + ("성공" if res.get("ok") else "실패 — "
                 + str(res.get("error", ""))))
            if res.get("chats"):
                log("[진단] Copilot 채팅 정리: " + str(res["chats"])[:300])
            self._send(200, res)
        elif self.path == "/api/chat_sweep":
            # LM30(2026-10-21) [LM이 연 Copilot 채팅 지우기] — LM 기록(owned[])에 있는 채팅만 다시 지운다(같은 프로세스 · 파이썬을 띄우지
            # 않는다 — 전용 Edge 가 꺼져 있을 때만 그 Edge 를 띄운다). 다른 작업이 도는 동안은 409(같은 전용 Edge 를 함께 쓰지 않게) · 도는 동안
            # JOB 을 잡아 다른 작업도 막는다. 로그인은 하지 않는다(로그인 화면이면 아무것도 지우지 않고 안내).
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                if 0 < n <= 4096:
                    self.rfile.read(n)                  # 본문은 쓰지 않지만 먼저 읽는다(409 로 닫을 때 연결이 끊기지 않게)
            except (ValueError, OSError):
                pass
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy",
                                     "hint": f"지금 도는 작업({JOB.get('step') or '분석 실행'})이 끝난 뒤 누르세요"})
                    return
                JOB.update(running=True, step="Copilot 채팅 지우기", started=time.time(), phase="", done=0, total=0)
            res = {"ok": False, "line": "", "note": CHAT_SWEEP_NOTE}
            try:
                log("[Copilot 채팅] LM 기록에 있는 채팅을 다시 지웁니다(최대 5분 — 사람이 쓰던 채팅은 건드리지 않습니다)")
                res = chat_sweep_now()
                log("[Copilot 채팅] " + str(res.get("line") or "")[:400])
            except Exception as e:  # noqa: BLE001 - 어떤 예외도 JOB 을 '실행 중'으로 남기면 안 된다
                res = {"ok": False, "line": f"Copilot 채팅 지우기 실패({type(e).__name__})", "note": CHAT_SWEEP_NOTE}
                log("[Copilot 채팅] " + res["line"])
            finally:
                with LOCK:
                    JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)
            self._send(200, res)
        elif self.path == "/api/narrate":
            # 본문 {"all": true} = 모든 달 다시 만들기(--all) · 없으면 빠진 달·최근 달·데이터가 바뀐 달만.
            # 본문은 LOCK 밖에서 먼저 읽는다(소켓 읽기 동안 LOCK 을 잡고 있지 않게) — 깨졌으면 {}.
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                b = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except Exception:  # noqa: BLE001
                b = {}
            if not isinstance(b, dict):
                b = {}
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                if self._freezing():        # judge.py --narrate-only 가 report\ 를 다시 쓴다
                    return
                JOB.update(running=True, log=[], step="리뷰 코멘트 재생성",
                           started=time.time(), phase="", done=0, total=0)
            threading.Thread(target=narrate_job, args=(bool(b.get("all")),), daemon=True).start()
            self._send(200, {"ok": True, "all": bool(b.get("all"))})
        elif self.path == "/api/openfolder":
            try:
                subprocess.Popen(["explorer", REPORT], creationflags=NO_WIN)
            except OSError:
                pass
            self._send(200, {"ok": True})
        elif self.path == "/api/quit":
            self._send(200, {"ok": True})
            cleanup_children()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif self.path in ("/api/alive", "/api/bye"):
            # 창 닫기 = 작업 종료(LM28 — ui_close_decision). sendBeacon 은 text/plain 으로 오므로 형식을 보지 않고 JSON 으로 읽는다.
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                b = json.loads(self.rfile.read(n) or b"{}") if 0 < n <= 4096 else {}
            except (ValueError, OSError):
                b = {}
            b = b if isinstance(b, dict) else {}
            if self.path == "/api/alive":
                ok = ui_tab_alive(b.get("id"), str(b.get("vis") or "visible"))
            else:
                ok = ui_tab_bye(b.get("id"))
            self._send(200, {"ok": ok})
        else:
            self._send(404, {"error": "not found"})


def main():
    port = None
    for p in lmname.UI_PORTS:          # 9288~9307 — LM24·LM28·LM29 대시보드 대역과 나눠 북마크·탭이 섞이지 않게
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            port = p
            break
        except OSError:
            continue
    if port is None:
        print(f"사용 가능한 포트가 없습니다 ({lmname.UI_PORTS[0]}-{lmname.UI_PORTS[-1]})")
        return 1
    PORT[0] = port
    os.makedirs(REPORT, exist_ok=True)
    # 서버로 뜰 때만 종료 정리를 건다 — 임포트 부작용이 없어야 freeze.py 가 이 모듈을 안전하게 쓴다
    import atexit
    atexit.register(cleanup_children)
    # 콘솔 창(bat)을 X 로 닫으면 — 작업 트리를 끝내고 Job 밖의 전용 Edge 를 몇 초 안에 닫는다(채팅 정리는 건너뛴다).
    # Ctrl+C 는 예전처럼 KeyboardInterrupt → atexit(cleanup_children) 이 맡는다.
    proc.on_console_close(console_close_cleanup)
    proc.quiet_errors()      # 자식(run.py·수집기)이 못 켜질 때 Windows 오류 창이 쌓이지 않게 — 오류 모드는 물려받는다
    # 이전 세션이 갑자기 꺼졌어도 남아 있는 Copilot 전용 Edge를 시작 시 자가 정리
    # (다음 AI 왕복 때 자동으로 다시 뜨므로 부작용 없음)
    # 이어서 '다른 PC 에서 온 프로필 버리기' 를 같은 스레드에서 한다 — Edge 가 확실히 죽은 뒤라야
    # 잠긴 파일 없이 지워진다(별도 스레드로 띄우면 종료와 삭제가 겹친다).
    def _startup_cleanup():
        # LM28: 지난 실행이 남긴 전용 Edge 는 owner.json 표식이 있을 때만 CDP 로 닫는다(powershell 을 띄우지 않는다 · W3-15).
        # 로그인 대기 중이면 두고(P6), 사람이 띄운 Edge·LM24 의 Edge 는 건드리지 않는다.
        close_edge("ui_start")
        drop_foreign_profile()
    threading.Thread(target=_startup_cleanup, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"[ui] LoadMonitor30 {VERSION} — {url}  (Ctrl+C 종료)")
    # LM28(2026-10-19) 지난번에 스스로 끝났으면(report\ui_exit.json) 그 까닭을 한 번 — 콘솔과 화면의 진행 로그에
    prev = prev_ui_exit()
    if prev:
        print(prev)
        log(prev[len("[ui] "):])
    ccfg = _close_cfg()
    if ccfg["on"]:
        print("[ui] 대시보드 창을 모두 닫으면 실행 중인 작업도 멈추고 이 창이 닫힙니다(약 20초 뒤 · 팀 서버는 계속)")
    # LM_NO_BROWSER(수집기·드라이버와 같은 환경변수)도 존중한다 — bat 은 인자 없이 띄우므로 회귀 실행이
    # 실제 브라우저를 열던 결함(PK-03)
    if "--no-browser" not in sys.argv and not os.environ.get("LM_NO_BROWSER"):
        target = url + "team" if "--team" in sys.argv else url
        threading.Timer(0.6, lambda: webbrowser.open(target)).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    # 대시보드 창을 닫으면 작업도 멈추고 서버가 끝난다(uiAutoExit · 첫 /api/alive 뒤에만 판정 — ui_close_decision)
    if ccfg["on"]:
        threading.Thread(target=close_watch, args=(srv, ccfg), daemon=True, name="lm-close-watch").start()
    # 화면에서 띄운 작업이 도는 동안 PC 가 절전에 들어가지 않게(LM28 2026-10-18 — awake_watch · keepAwakeDuringRun)
    threading.Thread(target=awake_watch, daemon=True, name="lm-awake").start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    print("[ui] 종료")
    return 0


if __name__ == "__main__":
    # bat 더블클릭(CP949 콘솔)에서도 —·한글이 안 깨지게 stdout 래핑 (import 시엔 건드리지 않음)
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", line_buffering=True, encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
    # line_buffering — 주소 안내 줄이 8KB 버퍼에 갇혀 창이 열릴 때까지 안 보이던 것(재검증 실측)
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # "실행이 안 된다"는 보고의 대부분은 창이 즉시 닫혀 원인이 사라진 경우다 —
        # 어떤 예외든 ui_error.log 에 남겨 다음에 원인을 볼 수 있게 한다.
        import traceback
        p = os.path.join(ROOT, "ui_error.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write("\n=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n")
            f.write(traceback.format_exc())
        print("\n[!] 오류가 발생했습니다 — 원인을 ui_error.log 에 저장했습니다:")
        print("    " + p)
        traceback.print_exc()
        raise
