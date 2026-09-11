# -*- coding: utf-8 -*-
"""
app.py — LoadMonitor24 로컬 HTML UI (표준 라이브러리만).

  python ui\\app.py          또는  LoadMonitor24-UI.bat 더블클릭

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

REPORT = os.path.join(ROOT, "report")
DATA = os.path.join(ROOT, "data")
NO_WIN = 0x08000000
VERSION = "v24.0"
LOCK = threading.Lock()
FREEZE_LOCK = threading.Lock()       # [보고서 만들기] 직렬화 — JOB 과 별개(사본에 '실행 중'이 굳지 않게)
JOB = {"running": False, "log": [], "step": "", "started": 0.0, "pid": 0,
       "phase": "", "done": 0, "total": 0, "phase_started": 0.0}


def kill_job():
    """실행 중인 분석 프로세스 트리(run→mine/judge→copilot_auto)를 통째로 종료"""
    with LOCK:
        pid = JOB.get("pid") or 0
    if pid:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=NO_WIN)
        with LOCK:
            JOB["pid"] = 0


def kill_copilot_edge():
    """Copilot 왕복용 전용 Edge(작업이 끝나도 재사용 대기로 남는다)를 종료 —
    일반 Edge는 건드리지 않고 copilot_profile 프로필로 뜬 것만"""
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                    "Where-Object {$_.CommandLine -like '*copilot_profile*'} | "
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
        prof = os.path.join(DATA, "copilot_profile")
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
        kill_copilot_edge()
    except Exception:
        pass


# atexit.register(cleanup_children) 는 main() 안에서만 — 모듈을 임포트하는 쪽(freeze.py 의
# 얼린 보고서 굽기)이 끝날 때 Copilot 전용 Edge 를 죽이지 않게(임포트 부작용 제거).
PORT = [0]


TS_PID = os.path.join(REPORT, "teamserver.pid")
TS_LOG = os.path.join(REPORT, "teamserver.log")
# 팀 정적 보고서 — 경로 → 취합 폴더의 파일. 자기완결 문서라 same-origin 요청이 필요 없다;
# 업로드로 들어온 값의 이스케이프가 한 곳 새더라도 대시보드의 /api/* 를 부를 수 없게
# sandbox CSP 로 origin 을 떼어 서빙한다(teamserver.py 와 같은 문자열).
TEAM_FILES = {"/team/report": "team_report.html", "/team/agentic": "team_agentic.html",
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
                "team_detail_groups.json", "team_cand_groups.json", "team_agentic_adjust.json")


def agentic_recalc(tag=""):
    """오할당 제외·재분류 뒤 agentic_<tag>.json 의 load_mm 을 실측으로 다시 센다(Copilot 왕복 없음).
    agentic.recalc_file 이 없는 판이면 조용히 건너뛴다."""
    try:
        if not tag:
            sp = latest_signals()
            if not sp:
                return False
            tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
        import agentic
        fn = getattr(agentic, "recalc_file", None)
        if fn is None:
            return False
        fn(tag)
        log(f"[agentic] {tag} MM 실측 재계산")
        return True
    except ImportError:
        return False
    except Exception as e:
        log(f"[agentic] MM 실측 재계산 건너뜀({type(e).__name__}: {str(e)[:120]})")
        return False


def _agentic_stale(a, tag, ap, out):
    """agentic_<tag>.json 이 재추출 이전 것인지 표시하고(V-01), MM 실측(mm_recalc)이 지금 행 파일과 다른 파일 기준이면
    같은 조건으로 왕복 없이 다시 센다(agentic_recalc) — 오할당 제외·재분류가 부르는 것과 같은 함수.
    · reextracted: signals 가 규칙 축으로 다시 써졌거나(재추출), 매칭이 만들어진 행 파일(rows_file)이 지금 화면·리포트가
      읽는 행 파일과 다르다(정제본 무효화) → 화면이 '재추출 이후 결과'/'정제본 무효화 이후 결과' 로 알리고 [재매칭] 을
      권한다(결과는 지우지 않는다).
    반환: (재계산했으면 다시 읽은) 분석 dict."""
    cur = _rows_basename(tag)
    mr = a.get("mm_recalc") if isinstance(a.get("mm_recalc"), dict) else {}
    with LOCK:
        idle = not JOB["running"]
    if mr and str(mr.get("rows_file") or "") != cur and idle and not FREEZE_LOCK.locked():
        if agentic_recalc(tag):
            try:
                a2 = json.load(open(ap, encoding="utf-8-sig"))
                if isinstance(a2, dict):
                    a = a2
            except (OSError, ValueError):
                pass
    rf = str(a.get("rows_file") or "")
    reex = _reextracted(tag)
    if reex or (rf and rf != cur):
        out["reextracted"] = True
        out["reextracted_title"] = "재추출 이후 결과" if reex else "정제본 무효화 이후 결과"
        out["reextracted_note"] = ((f"이 매칭은 {rf} 행 기준이고 지금 화면은 {cur} 입니다" if rf and rf != cur
                                    else "이 매칭은 마지막 업무 로드 재추출 이전의 행으로 판정한 것입니다")
                                   + " — 과제별 현업 이름이 어긋나 로드 MM 이 실제보다 작게 보일 수 있으니 [재매칭]으로 갱신하세요")
    return a


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


def _team_port():
    """config.teamServerUrl 의 포트 (없으면 팀 표준 9310)"""
    try:
        from urllib.parse import urlparse
        u = urlparse((cfg().get("teamServerUrl") or "").strip())
        if u.port:
            return int(u.port)
    except (ValueError, TypeError):
        pass
    return 9310


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
    """이 PC 의 주소 — 팀원에게 알려 줄 값. (UDP connect 는 패킷을 보내지 않는다)"""
    out = []
    try:
        s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s2.settimeout(0.2)
        s2.connect(("10.255.255.255", 1))
        out.append(s2.getsockname()[0])
        s2.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out


TS_TOKEN = os.path.join(REPORT, "teamserver.token")


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
    base = max(hi + 1, 19310) if (lo and lo <= cur <= hi) else cur
    for p in range(int(base), int(base) + 40):
        if p == PORT[0] or 9148 <= p <= 9167:      # 대시보드 자신의 대역은 피한다
            continue
        if _port_reserved(p):
            continue
        if _bind_free(p)[0]:
            return p
    return 0


def teamserver_status():
    port = _team_port()
    lis = _listeners(port)                      # None = 알아내지 못함
    open_ = _port_open(port) or bool(lis)       # 특정 NIC 에만 붙은 리스너도 놓치지 않는다
    ident = _ts_identity(port) if open_ else {}
    same_root = bool(ident.get("root")) and \
        os.path.normcase(os.path.abspath(ident["root"])) == os.path.normcase(os.path.abspath(ROOT))
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
    # 강제로 가져올 수 있는가 — OS 사실로만 정한다(네트워크 응답은 근거가 아니다)
    take = "no"
    if occ and not any(x["protected"] for x in occ):
        take = "one_click" if all(x["teamserver"] for x in occ) else "confirm_pid"
    tail = ""
    try:
        with open(TS_LOG, encoding="utf-8", errors="replace") as f:
            tail = " / ".join([x.strip() for x in f.readlines()[-3:] if x.strip()])[:300]
    except OSError:
        pass
    return {"ok": True, "running": running, "port": port, "pid": pid if running else 0,
            "urls": [f"http://{ip}:{port}" for ip in local_ips()], "log": tail,
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

    쓰다 만 config 는 화면 전체에 '설정이 없다'로 읽힌다 — 사용자가 말한 그 '초기화'다."""
    try:
        p = os.path.join(ROOT, "config", "config.json")
        with open(p, encoding="utf-8-sig") as f:
            c = json.load(f)
        c[key] = val
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except (OSError, ValueError):
        return False


def _save_team_url(url):
    r"""화면에서 고친 팀 서버 주소를 config\config.json 에 남긴다 (설명 키·다른 값은 보존)."""
    try:
        p = os.path.join(ROOT, "config", "config.json")
        with open(p, encoding="utf-8-sig") as f:
            c = json.load(f)
        c["teamServerUrl"] = url
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except (OSError, ValueError):
        return False


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
    for k in ("failed_rows", "partial_chunks", "repaired"):
        if k in j:
            try:
                issues[k] = int(j.get(k) or 0)
            except (TypeError, ValueError):
                pass
    if "aborted" in j:
        issues["aborted"] = bool(j.get("aborted"))
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


# ── 창 샘플러 감시·재기동 (A26) ─────────────────────────────────────────────
# schtasks 한 줄로 등록한 샘플러는 기본 3일 실행 제한(PT72H)으로 로그온 3일 뒤 조용히 죽는다 —
# 멈춘 날은 하한 모드로 떨어져 PC 유형 편차가 되살아난다. 상태바 표시에 더해 10분에 한 번만
# 재기동을 시도한다(config.autoRestartSampler, 기본 true).
SAMPLER_STALE_MIN = 10                      # 마지막 샘플이 이보다 오래됐으면 '멈춤'
SAMPLER_TASK = "LoadMonitor24-Sampler"      # docs\설정가이드 §4 · collect\Register-Samplers.ps1 의 작업 이름
SAMPLER_RESTART = {"at": 0.0, "busy": False, "when": "", "how": "", "note": ""}
SAMPLER_TASK_STATE = {"at": 0.0, "exists": None}   # 등록 작업 유무 — /api/status 는 1초 폴링이라 캐시한다


def _sampler_task_exists():
    """로그온 자동 시작 작업이 등록돼 있는가 — True/False, 확인 실패는 None. 5분 캐시.
    '꺼짐' 안내가 '등록이 안 된 것'인지 '등록은 됐는데 안 도는 것'인지 사용자가 알아야 조치할 수 있다."""
    now = time.time()
    with LOCK:
        if now - SAMPLER_TASK_STATE["at"] < 300:
            return SAMPLER_TASK_STATE["exists"]
        SAMPLER_TASK_STATE["at"] = now
    ok = None
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", SAMPLER_TASK],
                           capture_output=True, timeout=20, creationflags=NO_WIN)
        ok = (r.returncode == 0)
    except Exception:  # noqa: BLE001 - 조회 실패는 '모름' 이지 '없음' 이 아니다
        ok = None
    with LOCK:
        SAMPLER_TASK_STATE["exists"] = ok
    return ok


def _cfg_bool(v, dflt=True):
    if isinstance(v, bool):
        return v
    if v is None:
        return dflt
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _sampler_restart_worker(ps1):
    """(백그라운드 스레드) ① 등록 작업이 있으면 schtasks /Run — 작업의 IgnoreNew 정책이 중복 기동을 막는다
    ② 없으면 이미 도는 인스턴스가 없을 때만 스크립트를 콘솔 없이 분리 실행."""
    how, note = "", ""
    try:
        r = subprocess.run(["schtasks", "/Run", "/TN", SAMPLER_TASK], capture_output=True,
                           timeout=30, creationflags=NO_WIN)
        if r.returncode == 0:
            how = "schtasks"
            return
        q = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | "
             "Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match 'Start-ActivitySampler' }).Count"],
            capture_output=True, timeout=40, creationflags=NO_WIN)
        try:
            n = int((q.stdout or b"0").decode("utf-8", "replace").strip().splitlines()[-1] or 0)
        except (ValueError, IndexError):
            n = 0
        if n > 0:
            how, note = "skip", f"샘플러 프로세스 {n}개가 이미 떠 있는데 샘플이 안 쌓임 — 수동 확인"
            return
        # 콘솔 없이(CREATE_NO_WINDOW|CREATE_NEW_PROCESS_GROUP) — 대시보드를 닫아도 샘플러는 남는다.
        # ★ 예전에는 DETACHED_PROCESS(0x8) 를 썼는데, 그러면 powershell.exe 가 스크립트를 **한 줄도
        #   실행하지 않고 즉시 exit 0** 한다(실측 플래그 행렬: 0x8 이 든 조합은 전부 0줄, 빼면 정상).
        #   그래서 이 경로는 한 번도 작동한 적이 없고, 화면에는 '재시작 시도' 만 10분마다 새로 찍혔다.
        #   CREATE_NO_WINDOW 로 띄운 자식도 부모(대시보드)가 죽은 뒤 계속 도는 것을 실측 확인했다.
        p = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                              "-WindowStyle", "Hidden", "-File", ps1],
                             cwd=ROOT, creationflags=NO_WIN | 0x00000200, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # 띄웠다고 도는 것이 아니다 — 3초 뒤에도 살아 있는지 본다. 즉사했으면 그 사실을 화면에 적는다
        # (예전에는 how="direct" 로 기록만 하고 안 도는 상태를 구분할 방법이 없었다).
        time.sleep(3.0)
        if p.poll() is not None:
            how, note = "error", (f"기동 직후 종료(rc={p.returncode}) — 실행 정책·보안 정책이 막았을 수 있습니다. "
                                  "LoadMonitor24-샘플러등록.bat 으로 등록해 보세요")
            return
        how = "direct"
    except Exception as e:  # noqa: BLE001 - 감시 스레드가 죽어도 UI 는 계속
        how, note = "error", f"{type(e).__name__}: {str(e)[:80]}"
    finally:
        with LOCK:
            SAMPLER_RESTART.update(busy=False, how=how, note=note, when=time.strftime("%H:%M"))
        log("[샘플러] " + {"schtasks": f"멈춤 감지 — 등록 작업({SAMPLER_TASK}) 재실행",
                           "direct": "멈춤 감지 — collect\\Start-ActivitySampler.ps1 재기동(등록 작업 없음)",
                           "skip": "멈춤 감지 — " + note,
                           "error": "재기동 실패 — " + note}.get(how, note))


def _sampler_autorestart(age_min):
    """/api/status 마다 호출된다(1초 폴링) — 멈춤(>10분)이거나 **아직 한 번도 안 켜졌을 때**,
    10분에 한 번만, 스레드로 시도한다. returns 상태바에 실을 사유(자동 재기동이 꺼져 있으면 그 사실).

    ★ 예전에는 첫 줄이 'age_min is None 이면 return' 이라, 샘플이 하나도 없는 PC(=한 번도 켜진 적 없음)
      에서는 자동 기동을 아예 시도하지 않았다. 그래서 화면은 영원히 '샘플러 꺼짐' 만 띄우고 아무 일도
      일어나지 않았다(제보: "샘플러가 계속 꺼짐 상태 안내인데"). 그 경우야말로 켜 줘야 하는 상황이다."""
    if age_min is not None and age_min <= SAMPLER_STALE_MIN:
        return ""
    if not _cfg_bool(cfg().get("autoRestartSampler"), True):
        return "자동 재시작 꺼짐(config.autoRestartSampler)"
    ps1 = os.path.join(ROOT, "collect", "Start-ActivitySampler.ps1")
    if not os.path.exists(ps1):
        return "collect\\Start-ActivitySampler.ps1 없음"
    now = time.time()
    with LOCK:
        if SAMPLER_RESTART["busy"] or now - SAMPLER_RESTART["at"] < 600:
            return ""
        SAMPLER_RESTART.update(at=now, busy=True)
    threading.Thread(target=_sampler_restart_worker, args=(ps1,), daemon=True).start()
    return ""


def outlook_coverage(period=None):
    r"""Outlook COM 수집의 달별 완료 표(data\outlook\coverage.json) 와 화면 기간을 맞춰 본다.

    수집기는 달 단위로 최신 달부터 읽고 예산에 닿으면 멈춘다(다음 실행이 잇는다). 그 사이 화면은 '메일·회의가
    M월부터만 있는' 상태라 주간 활동 추이·로드율이 앞 달에서 비어 보인다 — 화면이 그것을 말해야 한다.
    반환 {"months": n, "covered": [...], "uncovered": [...]} — 표가 없거나 COM 이 아닌 경로(색인·웹·Copilot)가
    채운 자료면 None (그 경로들은 달 단위 표를 남기지 않는다)."""
    from datetime import date
    try:
        with open(os.path.join(DATA, "outlook", "mail_source.json"), encoding="utf-8-sig") as f:
            src = json.load(f)
        with open(os.path.join(DATA, "outlook", "coverage.json"), encoding="utf-8-sig") as f:
            cov = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(src, dict) or src.get("source") != "com" or not isinstance(cov, dict):
        return None
    per = period if isinstance(period, (list, tuple)) and len(period) >= 2 else (src.get("period") or [])
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
    mail = cov.get("mail") if isinstance(cov.get("mail"), dict) else {}
    cal = cov.get("calendar") if isinstance(cov.get("calendar"), dict) else {}
    unc = [k for k in months if k not in mail or k not in cal]
    return {"months": len(months), "covered": [k for k in months if k not in unc], "uncovered": unc}


def dash_period(meta, lastrun=None):
    r"""화면이 다루는 기간 [d0, d1] — 추이·덩어리 판정·수집 범위 대조가 모두 이 기간을 쓴다.
      ① 분석 결과(mm_meta.period) ② 없으면 마지막 실행의 기간(report\last_run.json 의 period = 수집 기간 — 수집만 한
      추가 PC·분석 전) ③ 그것도 없으면 수집된 데이터의 실제 범위(pc_on·메일·파일 시각의 최소~최대) ④ ["", ""].
    예전엔 ①이 없으면 추이가 '오늘 기준 13주'로 떨어져, '올해'로 수집한 추가 PC 화면의 주간 활동 추이가 6월부터만
    그려졌다(제보: "팀 분석처럼 기간 전체를 포함했으면")."""
    from datetime import date, timedelta

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
    # ③ 데이터 범위 — /api/dash 는 자주 불리므로 파일 mtime 이 그대로면 지난 답을 쓴다(files.csv 는 수만 행일 수 있다)
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
    for name, pats, hint in (
        ("PC 가동", ["pc/pc_on.csv"], "run 실행 시 자동"),
        ("메일·일정", ["outlook/mail.csv", "outlook/calendar.csv"], "클래식 Outlook을 켠 상태로 실행"),
        ("파일·Recent", ["files/files.csv", "files/recent.csv"], "config.watchFolders 를 실제 작업 폴더로"),
        ("git 커밋", ["files/git_commits.csv"], "config.gitRepos 설정 (선택)"),
        ("팀즈 채팅", ["m365/teams_*.csv"], r"[팀즈 웹 읽기] 버튼 — 앱이 꺼져 있어도 됩니다 (전용 Edge 창에서 회사 계정 1회 로그인)"),
        ("창 샘플러", ["activity/activity_*.csv"],
         "LoadMonitor24-샘플러등록.bat 으로 1회 등록하면 로그온 때마다 자동 시작 (선택 · 없으면 PC 가동 하한으로 계산)"),
        ("추가 PC", ["추가PC/*/outlook/mail.csv", "추가PC/*/files/files.csv",
                     "추가PC/*/pc/pc_on.csv", "추가PC/*/m365/teams_*.csv"],
         "폴더째 옮겨 [추가 PC 수집] → 본 PC 에서 [분석 실행] — 자동 합산 · 중복 자동 제외 (선택)"),
    ):
        n, mt = 0, 0.0
        for p in pats:
            for f in glob.glob(os.path.join(DATA, p)):
                n += max(0, len(_rows(f)))
                mt = max(mt, _mtime(f))
        opt = name in ("git 커밋", "팀즈 채팅", "창 샘플러", "추가 PC")
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
            # '재수집'이 아니라 상시 샘플러가 정답이다 — 안내를 상황에 맞게 바꾼다.
            no_cp = os.path.exists(os.path.join(DATA, "m365", "teams_copilot_unavailable.json"))
            if no_cp and n < 5:
                st = "warn" if n else "off"
                hint = ("이 계정 Copilot은 팀즈 조회 불가 — [팀즈 웹 읽기] 를 쓰세요"
                        "(앱이 꺼져 있어도 됩니다). 상시 누적은 collect\\Start-TeamsSampler.ps1")
            elif 0 < n < 5:
                st, hint = "warn", "회수 부족 — [팀즈 웹 읽기] 로 보강 (창 읽기는 화면에 보인 부분만 긁습니다)"
        out.append({"name": name, "rows": n, "age": _age(mt),
                    "status": st, "hint": "" if st == "ok" else hint})
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
        for r in _rows(os.path.join(DATA, "files", name)):
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

def trend(d0="", d1="", tag="", info=None):
    r"""활동 추이 — **분석 기간을 덮고, 실제로 계상된 신호**를 센다.
    info(dict)를 주면 info["src"] 에 무엇을 셌는지 남긴다: "signals"(판정 신호) / "raw"(수집 raw 폴백) / "none"(기간 없음).
    화면 안내는 이 값을 봐야 한다 — meta.period 유무로 판단하면 signals 로 그려 놓고 'raw' 라고 적는다(재검증 실측).

    예전에는 오늘 기준 14주 고정이라 1월부터 본 사람도 최근 3개월만 보였고(실측 제보),
    data\ 의 raw 수집물을 표본화 없이 세어 한 주의 배치 산출물이 나머지를 눌렀다.
    이제 report\signals_<기간>.csv(판정에 실제로 쓰인 신호)를 세므로 MM 산정과 축이 같다.
    기간이 길면 주 대신 달로 묶는다 — 34주를 한 화면에 그리면 읽을 수 없다."""
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
    monthly = span_w > 26                       # 반년이 넘으면 달 단위로

    buckets, idx = [], {}
    if monthly:
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            idx[(y, m)] = len(buckets)
            buckets.append(f"{y % 100:02d}/{m:02d}")
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
            "작업창": 0, "pc_days": 0, "pc_wd": 0, "raw_n": 0}
           for lb in buckets]
    if info is not None:
        info["src"] = "none"
    if not out:
        return out

    def slot(s):
        dt = _d(s)
        return key(dt) if (dt and start <= dt <= end) else None

    # 판정에 **실제로 쓰인 신호**(report\signals_<기간>.csv)를 센다 — 대시보드 MM 과 같은 축.
    # 파일 신호의 시각은 mtime 하나뿐이다 — 공유폴더 재동기화·폴더 이관·백업 복원이
    # 수백 파일의 시각을 한 날로 몰면 그 달만 산처럼 솟는다(실측 제보 — 특정 달 몰림).
    # 파일류는 하루 상한 8건으로 눌러 센다(mine 의 '사람 손 하루 한 폴더 8건' 과 같은 눈금).
    # 메일·회의·커밋·팀즈는 사건 시각(발신·개최 시각)이라 그대로 센다.
    # ★ '작업창' 이 이 표에 없어 기본값 '파일' 로 떨어지던 것이 실측 결함이었다. 신호는 시간순이라
    #   아침 창 세션이 그날 파일 상한 8칸을 전부 차지하고, 오후에 실제로 만든 문서가 통째로 사라졌다
    #   (창 샘플러를 켠 PC — 즉 분석을 돌리는 PC — 에서 항상 일어난다). 별도 계열로 뺀다.
    _SRC = (("메일", "메일"), ("mail", "메일"), ("회의", "회의"), ("일정", "회의"),
            ("cal", "회의"), ("커밋", "커밋"), ("git", "커밋"),
            ("팀즈", "팀즈"), ("teams", "팀즈"),
            ("작업창", "작업창"), ("window", "작업창"))
    sp = os.path.join(REPORT, f"signals_{tag}.csv") if tag else latest_signals()
    n_sig = 0
    _fcap, _seen = {}, set()
    for r in _rows(sp):
        d = str(r.get("time") or r.get("date") or "")[:10]
        i = slot(d)
        if i is None:
            continue
        s = str(r.get("source") or "").lower()
        # 변수명이 key 면 위쪽 버킷 함수 key() 를 가려 slot() 이 죽는다(실측)
        kind = next((v for k2, v in _SRC if k2.lower() in s), "파일")
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
    if not n_sig:
        # 판정 결과가 아직 없는 기간 — 그때만 수집 raw 로라도 모양을 보여준다 (같은 상한)
        _fcap.clear()
        for pat, k2, col in (("files/files.csv", "파일", "mtime"),
                             ("files/recent.csv", "파일", "mtime"),
                             ("outlook/mail.csv", "메일", "time"),
                             ("outlook/calendar.csv", "회의", "start"),
                             ("files/git_commits.csv", "커밋", "time")):
            for r in _rows_multi(pat):          # 본 PC + 추가PC — 옮겨 온 폴더도 모양이 보이게
                d = str(r.get(col) or "")[:10]
                i = slot(d)
                if i is None:
                    continue
                if k2 == "파일":
                    _fcap[d] = _fcap.get(d, 0) + 1
                    if _fcap[d] > 8:
                        continue
                out[i][k2] += 1
        for f in _paths_multi("m365/teams_*.csv"):
            for r in _rows(f):
                i = slot(r.get("time"))
                if i is not None:
                    out[i]["팀즈"] += 1

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
    except Exception as ex:  # noqa: BLE001 — 병합 실패 시 예전 방식(본 PC 만)
        # 조용히 '본 PC 만' 으로 떨어지면 화면에는 아무 표시가 없어 원인을 못 찾는다(실측:
        # csv.Error 가 extract 의 except OSError 를 통과해 여기까지 샌다). 이유를 남긴다.
        pc_note = f"추가 PC 합산 실패({type(ex).__name__}) — 본 PC 기록만 표시합니다"
        pcd = {}
        for r in _rows(os.path.join(DATA, "pc", "pc_on.csv")):
            d2 = _d(r.get("date"))
            i = slot(r.get("date"))
            if i is not None:
                try:
                    out[i]["pc_h"] += float(r.get("on_hours") or 0)
                    if d2:
                        pcd[d2] = True
                except (TypeError, ValueError):
                    pass
    # 버킷마다 '평일 수'와 'PC 기록이 있는 평일 수' — 기록 없음과 0h 를 화면이 구분하게.
    dd = start
    while dd <= end:
        i = key(dd)
        if i is not None and dd.weekday() < 5:
            out[i]["pc_wd"] += 1
            if dd in pcd:
                out[i]["pc_days"] += 1
        dd += timedelta(days=1)
    for w in out:
        w["pc_h"] = round(w["pc_h"], 1)
    if info is not None:
        info["src"] = "signals" if n_sig else "raw"
        info["gran"] = "month" if monthly else "week"
        info["pc_note"] = pc_note
        # PC 기록이 있는 버킷 / 평일이 있는 버킷 — 화면이 "27주 중 16주만 기록" 처럼 말할 수 있게
        info["pc_buckets"] = sum(1 for w in out if w["pc_days"] > 0)
        info["pc_buckets_all"] = sum(1 for w in out if w["pc_wd"] > 0)
        first_pc = next((d for d in sorted(pcd)), None)
        info["pc_from"] = first_pc.isoformat() if first_pc else ""
        info["capped"] = sum(max(0, w["raw_n"] - (w["파일"] + w["메일"] + w["회의"] + w["커밋"] + w["팀즈"] + w["작업창"]))
                             for w in out)
    return out

def review(gran="week"):
    """주간/월간/전체 업무 리뷰 — 신호별 귀속 내역(signals_*.csv)을 기간으로 묶어
    프로젝트별 raw 근거·타임라인·사람/산출물 연결까지 만든다. '요약'이 아니라 원문이 들어간 리뷰."""
    from datetime import datetime, timedelta
    rows = _rows(latest_signals())
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
                                       "wt": Counter()})
        pp["w"] += w
        pp["n"] += 1
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
        projs = []
        for pj, pp in sorted(g["proj"].items(), key=lambda kv: -kv[1]["w"]):
            projs.append({
                "name": pj, "share": round(pp["w"] / tot, 4),
                "mm": round(pp["w"] / tot * months, 3), "n": pp["n"],
                # pw 가드: 가중치 합 0(잘린 행 등)이면 ZeroDivision 으로 리뷰 탭 전체가 죽는다
                "acts": [{"name": a, "pct": round(v / (pp["w"] or 1e-9) * 100)} for a, v in pp["acts"].most_common(4)],
                "wt": [[k, round(v / (pp["w"] or 1e-9) * 100)] for k, v in pp["wt"].most_common()],
                "people": [[k, v] for k, v in pp["people"].most_common(6)],
                "files": [k for k, _v in pp["files"].most_common(6)],
                "meets": [k for k, _v in pp["meets"].most_common(4)],
                "comms": [k for k, _v in pp["comms"].most_common(5)]})
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
                    "months": round(months, 2), "projects": projs,
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


def _rows_basename(tag):
    """지금 화면·리포트·Agentic 실측이 읽는 행 파일 이름 — details.rows_path(tag) 와 같은 규칙."""
    plain = os.path.join(REPORT, f"mm_rows_{tag}.csv")
    ref = os.path.join(REPORT, f"mm_rows_{tag}_refined.csv")
    return os.path.basename(ref if _fresh_refined(plain, ref) else plain)


def result_rows():
    # '가장 최근 분석'을 기준으로 고른다. 예전의 기간(tag) 무관 '정제본 우선'은,
    # 분석 기간 기본값이 날마다 바뀌어 tag 가 매일 달라지는 상황에서 과거 실패한 날의
    # 정제본이 이후 모든 성공 결과를 영원히 가리는 함정이었다(실측: 재실행해도 같은
    # 토큰 화면 반복). 정제본은 '같은 기간'의 것이 있을 때만 우선한다.
    #
    # 정제본 선택은 core/details.rows_path(agentic·flow·freeze 공용)와 **같은 mtime 규칙**이다(V-01):
    # 정제본 mtime ≥ 원본 mtime 일 때만 정제본, 원본이 더 새로 써졌으면 '낡았다'고 보고 원본으로 내려간다.
    # 예전에는 '같은 tag 정제본이 있으면 무조건' 이라 무AI 재실행·판정 실패 뒤 옛 정제본이 표에 남아 KPI(새 meta)·
    # 분석리포트(새 원본)와 셋이 다른 값을 보였다. 1차 무효화는 run.py 가 추출 직후 정제본을 .stale 로 개명하는
    # 것이고, 여기 mtime 규칙은 mine 을 직접 돌린 경우의 안전망이다. 재분류 0건은 retag.py 가 파일을 다시 쓰지
    # 않으므로 화면이 튀지 않고, n>0·오할당 제외는 정제본을 지우므로 두 규칙이 같은 행을 본다.
    bases = [f for f in glob.glob(os.path.join(REPORT, "mm_rows_*.csv"))
             if not f.endswith("_refined.csv")]
    base = max(bases, key=_mtime) if bases else ""
    p = ""
    if base:
        ref = base[:-4] + "_refined.csv"
        p = ref if _fresh_refined(base, ref) else base
    else:
        # 정제본만 남은 폴더(옮겨 온 report\ 등) — 원본이 없다고 화면을 백지로 두지 않는다
        # (리포트·agentic·flow 는 정제본만으로도 돌아간다 — 대시보드도 같은 규칙)
        refs = glob.glob(os.path.join(REPORT, "mm_rows_*_refined.csv"))
        p = max(refs, key=_mtime) if refs else ""
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
            cmd.append("--collect-only")          # 추가 PC 에서: 수집만 하고 분석은 본 PC 에서
        else:
            if ai:
                cmd.append("--ai")
            if skip:
                cmd.append("--skip-collect")
        log(f"실행: {d0} ~ {d1}" + (" · 수집만(추가 PC)" if collect_only else
            (" · AI 정제" if ai else "") + (" · 재분석만" if skip else "")))
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        with LOCK:
            JOB["pid"] = p.pid
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                pg = parse_progress(line)
                if pg:
                    ph, done, total = pg
                    with LOCK:
                        if JOB["phase"] != ph:
                            JOB["phase_started"] = time.time()
                        JOB.update(phase=ph, done=done, total=total)
                    continue                     # 진행률 줄은 로그를 채우지 않는다
                log(line)
                if line.startswith("──"):
                    with LOCK:
                        JOB["step"] = line.strip("─ ")
                        JOB.update(phase="", done=0, total=0)
        p.wait()
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
    # Agentic 매칭의 load_mm 도 실측으로 다시 — 제외한 업무가 대체 로드에 남지 않게(왕복 없음)
    agentic_recalc(tag)
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


# ── 수동 Agentic 매칭·워크플로우 재분석 (S2) ─────────────────────────────────
# 옛 판은 POST 핸들러가 subprocess.run(timeout=420/960) 으로 끝까지 기다렸다 — 업무가 많은 사람은
# 묶음 13~49회(회당 수십 초~수 분)라 반드시 시간 초과로 죽고(자식은 kill), 진행률도 안 보이고, 새로고침하면
# 결과·사유가 사라졌다. 이제 [분석 실행]과 같은 방식으로 스레드에서 돌리며 [progress] 를 진행 바에 흘리고,
# 마지막 줄 JSON(ok/error/hint)을 MANUAL 에 남겨 GET /api/agentic·/api/workflow 가 화면에 전한다.
TOOL_JOBS = {"agentic": ("agentic.py", "Agentic AI 분석"), "flow": ("flow.py", "워크플로우 분석")}
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


def tool_job(kind, extra=()):
    """agentic.py / flow.py 를 스레드에서 끝까지 돌리고 결과를 MANUAL[kind] 에 남긴다(run_job 과 같은 프로토콜).
    인자가 없으면 두 스크립트는 mm_meta 최신 기간을 잡아 화면과 어긋난 파일에 쓸 수 있으므로 기간을 명시한다."""
    script, step = TOOL_JOBS[kind]
    t0 = time.time()
    tag, targs = _tag_args()
    res = {"ok": False, "error": "실행 실패", "hint": ""}
    try:
        cmd = [sys.executable, os.path.join(ROOT, script)] + targs + list(extra)
        log(f"[{step}] 시작 — 기간 {tag or '(최신)'}")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"),
                             creationflags=NO_WIN)
        with LOCK:
            JOB["pid"] = p.pid
        last, tail = None, ""
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            pg = parse_progress(line)
            if pg:
                ph, done, total = pg
                with LOCK:
                    if JOB["phase"] != ph:
                        JOB["phase_started"] = time.time()
                    JOB.update(phase=ph, done=done, total=total)
                continue
            if line.startswith("{") and line.rstrip().endswith("}"):
                try:
                    o = json.loads(line)
                    if isinstance(o, dict):
                        last = o
                        continue
                except ValueError:
                    pass
            tail = line
            log(line)
        p.wait()
        if last is None:
            # 자식이 죽으면 사유는 마지막 로그 줄(스택 끝)에 있다 — 버리면 빈 힌트만 남는다
            res = {"ok": False, "error": "출력 해석 실패",
                   "hint": (tail[:200] if tail else f"종료 코드 {p.returncode}") + " — 진행 로그를 확인하세요"}
        else:
            res = last
            if p.returncode != 0 and res.get("ok"):
                res["ok"] = False
        log(f"=== {step} " + ("완료" if res.get("ok") else f"실패: {str(res.get('error') or '')[:80]}"
                                + (f" — {str(res.get('hint') or '')[:120]}" if res.get("hint") else "")) + " ===")
    except Exception as e:  # noqa: BLE001 - 어떤 예외도 JOB 을 '실행 중'으로 남기면 안 된다
        res = {"ok": False, "error": f"실행 오류({type(e).__name__})", "hint": str(e)[:150]}
        log(f"오류: {e}")
    finally:
        res = dict(res, at=time.strftime("%Y-%m-%d %H:%M"), sec=round(time.time() - t0), kind=kind, tag=tag)
        with LOCK:
            MANUAL[kind] = res
            JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)


def narrate_job():
    """9a — 리뷰 코멘트(월별 내러티브)만 다시 생성한다.
    다른 PC로 옮기면 report\\ 를 복사하지 않으므로 코멘트가 비어 보인다. 판정 결과
    (signals)만 있으면 왕복 몇 번으로 되살릴 수 있다."""
    try:
        sp = latest_signals()
        if not sp:
            log("[리뷰] 판정 결과가 없습니다 — [분석 실행]에 'AI 판정'을 켜고 먼저 돌리세요")
            return
        tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
        d0, d1 = tag.split("-")
        d0 = f"{d0[:4]}-{d0[4:6]}-{d0[6:]}"
        d1 = f"{d1[:4]}-{d1[4:6]}-{d1[6:]}"
        cmd = [sys.executable, os.path.join(ROOT, "judge.py"),
               "--from", d0, "--to", d1, "--narrate-only"]
        log(f"[리뷰] {tag} 코멘트 재생성 시작")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                      PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        with LOCK:
            JOB["pid"] = p.pid
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            pg = parse_progress(line)
            if pg:
                ph, done, total = pg
                with LOCK:
                    if JOB["phase"] != ph:
                        JOB["phase_started"] = time.time()
                    JOB.update(phase=ph, done=done, total=total)
                continue
            log(line)
        p.wait()
        log("=== 리뷰 코멘트 완료 ===" if p.returncode == 0 else "=== 리뷰 생성 실패 ===")
    except Exception as e:
        log(f"오류: {e}")
    finally:
        with LOCK:
            JOB.update(running=False, step="", pid=0, phase="", done=0, total=0)



TEAM_PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>LoadMonitor24 — 팀 취합</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Malgun Gothic',system-ui,sans-serif;background:#f2f4f7;color:#12151a;padding:22px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:20px}h1 small{font-size:11px;color:#8b929b;font-weight:400;margin-left:8px}
.sub{font-size:11.5px;color:#5a626b;margin:3px 0 14px}
.card{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}
.card h2{font-size:13px;margin-bottom:10px;color:#2c333b}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}
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
.heat td{text-align:center;font-size:11px}
.state{font-size:11px;color:#8b929b;font-weight:400}
body.snap .nosnap{display:none}
body.snap .snaponly{display:block}
.snaponly{display:none;font-size:11px;color:#8b929b;margin-bottom:10px}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;font-size:11.5px}
.steps a,.steps span{display:inline-block;padding:5px 10px;border-radius:14px;border:1px solid #d7dbe0;background:#fff;color:#4a5159;text-decoration:none}
.steps .on{background:#2a78d6;border-color:#2a78d6;color:#fff;font-weight:700}
</style></head><body><div class="wrap">
<h1>팀 취합<small id="ver">LoadMonitor24</small></h1>
<div class="sub">공유폴더의 인별 결과를 실시간으로 읽어 시각화합니다. 원본 파일은 수정하지 않습니다.</div>
<div class="steps nosnap">
 <a href="/" target="_blank">① 내 PC 분석</a>
 <a href="/" target="_blank">② 결과 확인</a>
 <a href="/" target="_blank">③ 팀 업로드 / 공유폴더 저장</a>
 <span class="on">④ 팀 취합 (지금 화면)</span>
 <a href="/team/report" target="_blank">리포트</a>
 <a href="/team/agentic" target="_blank">Agentic</a>
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
  <button class="ghost" id="tsport" style="display:none">포트 바꾸기</button></div>
 <div class="note" id="tsurl"></div>
 <div class="note">여기서 켜면 이 PC 가 팀 취합 서버가 됩니다. 팀원은 각자 대시보드의 저장소 주소에
 <b>위 주소</b>를 적고 [팀 서버 업로드]를 누르면 됩니다. 대시보드를 닫아도 서버는 계속 돕니다(중지는 이 버튼으로).
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
 <button class="ghost" id="savehtml">정적 리포트 다시 만들기 (team_report·team_agentic·통합 보고서)</button>
 <span class="state" id="msg" style="font-size:11.5px;color:#5a626b"></span>
</div>
<div class="row" style="margin-top:8px">
 <button class="run" id="fullopen" disabled>팀 통합 보고서 열기</button>
 <button class="ghost" id="fullv3" disabled>v3 (로드율 제외)</button>
 <button class="ghost" id="fullmake">다시 만들기</button>
 <button class="ghost" id="fullsnap">스냅샷 저장</button>
 <span class="state" id="fullat" style="font-size:11.5px;color:#5a626b"></span>
</div>
<div class="note">팀 통합 보고서(team_full_report.html): 로드율·과제×인원·업무유형·Agentic·워크플로우를 한 장에 담은
정적 파일 — 팀원 업로드마다 자동 갱신되고 [다시 만들기]로 즉시 새로 만듭니다(Copilot 없이 저장된 통합만 적용).
v3 는 인별 로드율을 뺀 공유용, [스냅샷 저장]은 팀통합보고서_&lt;시각&gt;.html 사본을 취합 폴더에 남깁니다.</div>
<div class="note">유사 항목 정리: 인별 분석에서 갈라진 표기('광학 설계'/'광학계 설계' 등)를 Copilot이
같은 실체끼리 묶어 대표 이름으로 통합합니다. 매핑만 얹으므로(team_aliases.json) 원본은 그대로이며
[정리 되돌리기]로 즉시 원상복구됩니다.</div></div>

<div class="kpis">
 <div class="kpi"><div class="lb">인원</div><div class="vl" id="k_n">–</div><div class="nt" id="k_nn"></div></div>
 <div class="kpi"><div class="lb">팀 로드율 (투입÷가용)</div><div class="vl" id="k_load">–</div><div class="nt" id="k_mm"></div></div>
 <div class="kpi"><div class="lb">과제 수</div><div class="vl" id="k_pj">–</div><div class="nt" id="k_alias"></div></div>
 <div class="kpi"><div class="lb">Agentic 분석</div><div class="vl" id="k_ag">–</div><div class="nt">완료 인원</div></div>
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

<div class="card"><h2>Agentic AI 12과제 적합률 — 과제 × 인원 <span class="state" style="font-weight:400;font-size:11px;color:#8b929b">셀 색이 진할수록 적합 · 숫자 = 적합%(대체 가능 MM)</span></h2>
 <div style="overflow-x:auto"><table class="heat" id="heat"></table></div>
 <div class="note" id="heatrank"></div></div>

<div class="grid2">
 <div class="card"><h2>팀 발굴 신규 Agentic AI 후보</h2><div id="newlist"></div></div>
 <div class="card"><h2>공통업무 (여러 사람·여러 과제 반복)</h2><table id="commtbl"></table></div>
</div>

<div class="card"><h2>세부업무 상위 (팀 합산) <span class="state" style="font-weight:400;font-size:11px;color:#8b929b">유사 항목 정리 후 같은 일이 한 줄로 합쳐졌는지 확인</span></h2>
 <table id="dtltbl"></table></div>

</div><script>
const $=id=>document.getElementById(id);
const PAL=["#2a78d6","#0e8c7a","#a61b4a","#e08a00","#6c4fb8","#3d8f3d","#c05a78","#4a7f9e","#8a6d3b","#556270"];
const WTC={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;");
let D=null;
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
 $("k_ag").textContent=`${(D.agentic||[]).length}/${ms.length}`;
 // 팀 통합 보고서 상태 — 정적 스냅샷(team_report.html)에서는 D.full 이 없어 '없음' 으로 남는다(nosnap 카드)
 const fu=D.full||{};
 $("fullat").textContent=fu.exists?`통합 보고서 ${fu.at||""} 생성${fu.v3?" · v3 있음":""}`:"통합 보고서 아직 없음 — [다시 만들기]";
 $("fullopen").disabled=!fu.exists;$("fullv3").disabled=!(fu.exists&&fu.v3);
 // 취합 현황 — 누가·언제·어디서 (빠진 사람을 눈으로 찾을 수 있게)
 $("whotbl").innerHTML=ms.length?
  '<table><tr><th>이름</th><th style="width:74px">파트</th><th style="width:150px">기간</th>'
  +'<th style="width:62px">투입 MM</th><th style="width:56px">로드율</th>'
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
     <td style="font-size:11px">${esc(m.measure_text||"–")}</td>
     <td>${up?esc(up):`<span class="state">${esc(fa)||"–"}</span>`}</td>
     <td>${esc(upf)||"–"}</td><td>${esc(an)||"–"}</td><td>${esc(hs)||"–"}</td></tr>`;
   }).join("")+"</table>"
  +(exm.length?`<div class="note">측정 불충분(수집기 결측)으로 <b>팀 평균·순위·과제 매트릭스에서 제외</b>한 인원: ${esc(exm.map(m=>m.owner).join(", "))} — 그 PC 에서 PC 가동·Outlook·창 샘플러 수집을 살린 뒤 다시 올리면 비교에 들어갑니다.</div>`:"")
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
   <span style="font-size:10.5px;color:#8b929b">투입 ${m.total_mm.toFixed(2)} / 가용 ${m.avail_mm.toFixed(2)}${m.no_evidence_days?` · 무흔적 ${m.no_evidence_days}일`:""}${m.measure_text?` · ${esc(m.measure_text)}`:""}${covB(m)}${cfgB(m)}</span></div>`;
 }).join("")||'<div class="note">데이터 없음</div>';
 // 과제 × 인원 스택바 — 서버(aggregate.collect_team_data)가 측정 불충분 인원을 매트릭스에서 이미 뺐다
 const owners=okm.map(m=>m.owner);const oc=o=>PAL[owners.indexOf(o)%PAL.length];
 const pjs=Object.entries(D.matrix||{});
 const pmax=Math.max(...pjs.map(([_,v])=>Object.values(v).reduce((a,b)=>a+b,0)),0.001);
 $("pjstack").innerHTML=pjs.map(([pj,v])=>{
  const tot=Object.values(v).reduce((a,b)=>a+b,0);
  const segs=owners.map(o=>v[o]?`<i style="display:inline-block;height:14px;width:${v[o]/pmax*300}px;background:${oc(o)}" title="${esc(o)} ${v[o].toFixed(2)}MM"></i>`:"").join("");
  return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
   <span style="width:150px;font-size:11.5px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"><b>${esc(pj)}</b></span>
   <span>${segs}</span><span style="font-size:11px;color:#5a626b">${tot.toFixed(2)} MM</span></div>`;
 }).join("")||'<div class="note">데이터 없음</div>';
 $("pjleg").innerHTML=owners.map(o=>`<span style="font-size:11px"><span class="dot" style="background:${oc(o)}"></span>${esc(o)}</span>`).join("");
 // 업무유형 스택 (비교 가능 인원만 — 측정 불충분은 유형 분포도 뺀다)
 $("wtstack").innerHTML=okm.map(m=>{
  const v=(D.wt||{})[m.owner]||{};const tot=Object.values(v).reduce((a,b)=>a+b,0)||1;
  const segs=Object.entries(v).map(([k,x])=>`<i style="display:inline-block;height:14px;width:${x/tot*260}px;background:${WTC[k]||"#98a0a8"}" title="${esc(k)} ${x.toFixed(2)}MM"></i>`).join("");
  return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
   <span style="width:80px;font-size:11.5px;text-align:right">${esc(m.owner)}</span><span>${segs}</span></div>`;
 }).join("")+`<div class="row" style="margin-top:6px">${Object.entries(WTC).map(([k,c])=>`<span style="font-size:11px"><span class="dot" style="background:${c}"></span>${k}</span>`).join("")}</div>`;
 // 12과제 히트맵
 const ags=D.agentic||[];const tks=D.tasks||[];
 if(tks.length){
  let h=`<tr><th style="text-align:left">과제</th>${ags.map(a=>`<th>${esc(a.owner)}</th>`).join("")}<th>팀 합계</th></tr>`;
  const rank=[];
  tks.forEach(t=>{
   let tot=0;
   const cells=ags.map(a=>{
    const m=(a.match||[]).find(x=>x.task===t.id);
    if(!m||!m.fit)return`<td style="color:#c9cfd8">-</td>`;
    tot+=m.load_mm||0;
    const al=Math.min(0.85,m.fit/100*0.85+0.08);
    return`<td style="background:rgba(42,120,214,${al});color:${m.fit>=45?"#fff":"#12151a"}"><b>${m.fit}%</b><br><span style="font-size:9.5px">${(m.load_mm||0).toFixed(2)}</span></td>`;
   }).join("");
   rank.push([t,tot]);
   h+=`<tr><td style="text-align:left" title="${esc(t.desc)}"><b>${esc(t.id)}</b> ${esc(t.name)}</td>${cells}<td><b>${tot.toFixed(2)} MM</b></td></tr>`;
  });
  $("heat").innerHTML=h;
  rank.sort((a,b)=>b[1]-a[1]);
  const top=rank.filter(([_,v])=>v>0).slice(0,3).map(([t,v])=>`${t.id}(${v.toFixed(2)}MM)`);
  $("heatrank").textContent=top.length?`팀 우선순위 제안(현재 로드 기준): ${top.join(" → ")}`:"Agentic 분석을 실행한 인원이 없거나 매칭이 없습니다 — 각자 UI의 Agentic AI 탭에서 분석 후 재내보내기";
 }
 // 발굴 후보
 let nl="";
 ags.forEach(a=>(a.new||[]).forEach(n=>{nl+=`<div style="border-left:3px solid #6c4fb8;padding:3px 0 3px 10px;margin:8px 0">
  <b>${esc(n.name)}</b> <span style="font-size:10.5px;color:#8b929b">제안 ${esc(a.owner)} · ≈${(n.load_mm||0).toFixed(2)} MM</span>
  <div style="font-size:11px;color:#5a626b">로직: ${esc(n.logic)}<br>사유: ${esc(n.reason)}</div></div>`;}));
 $("newlist").innerHTML=nl||'<div class="note">발굴된 후보가 없습니다.</div>';
 // 공통업무
 $("commtbl").innerHTML="<tr><th>세부업무</th><th>관련 과제</th><th>수행 인원</th><th style='width:56px'>MM</th></tr>"+
  ((D.common||[]).map(c=>`<tr><td><b>${esc(c.detail)}</b></td><td>${(c.models||[]).map(esc).join(", ")}</td>
   <td>${(c.who||[]).map(esc).join(", ")}</td><td>${(c.mm||0).toFixed(2)}</td></tr>`).join("")||"<tr><td colspan=4 class='note'>없음</td></tr>");
 // 세부업무 상위
 $("dtltbl").innerHTML="<tr><th>과제 / 세부업무</th><th>담당</th><th style='width:70px'>팀 합산 MM</th></tr>"+
  Object.entries(D.details||{}).slice(0,25).map(([k,v])=>{
   const tot=Object.values(v).reduce((a,b)=>a+b,0);
   return`<tr><td><b>${esc(k)}</b></td><td>${Object.entries(v).map(([o,x])=>`<span class="tag">${esc(o)} ${x.toFixed(2)}</span>`).join("")}</td><td>${tot.toFixed(2)}</td></tr>`;
  }).join("");
}
// ── 팀 서버 켜기/끄기 (팀 공용 PC 용) ──
let TS={running:false,port:9310,urls:[]};
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
 $("tsport").style.display=busy?"":"none";
 if(busy)$("tsstate").innerHTML=`<span style="color:#c0122f">● 포트 ${TS.port} 사용 중</span> · `
  +esc(KND[TS.kind]||"확인 중");
 $("tsurl").innerHTML=TS.running
  ?("팀원에게 알려줄 주소: "+(TS.urls||[]).map(u=>`<b>${esc(u)}</b>`).join(" 또는 ")
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
     :"붙잡고 있는 서버를 찾지 못했습니다 — 포트를 바꾸는 편이 확실합니다")
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
  +"[포트 바꾸기] 로 다른 번호를 쓰세요.");return;}
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
$("tsport").onclick=async()=>{
 const NL=String.fromCharCode(10);
 const v=prompt("팀 서버가 쓸 새 포트 번호"+NL
  +"※ 팀원들이 쓰는 주소가 바뀝니다 — 각자 저장소 주소를 새 주소로 고쳐야 합니다."+NL
  +"  (밀린 묶음은 각자 PC 에 대기로 남으니 주소만 고치면 한 번에 올라갑니다)",
  String((TS.suggest_port||0)||TS.port||9310));
 if(!v)return;
 const r=await fetch("/api/teamport",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({port:parseInt(v,10)})}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 if(!r.ok){alert("포트 변경 실패"+NL+NL+(r.error||""));return;}
 alert("포트를 "+r.port+" 으로 바꿨습니다."+NL+"팀원에게 새 주소를 알려 주세요: "+(r.url||"")
  +NL+NL+"처음 켤 때 방화벽 허용 창이 다시 뜨면 [허용] 해야 다른 PC 에서 닿습니다.");
 tsLoad();
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
 const all=confirm("Copilot 이 채운 다른 캐시(team_series·team_pjclass·team_detail_groups·team_cand_groups.json)도 함께 지울까요?"
  +NL+"[취소] = team_aliases.json 만 삭제");
 await fetch("/api/team_refine",{method:"DELETE",headers:{"Content-Type":"application/json"},
   body:JSON.stringify(all?{files:["team_series.json","team_pjclass.json","team_detail_groups.json","team_cand_groups.json"]}:{})});
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
load();tsLoad();
</script></body></html>"""

PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>LoadMonitor24</title><style>
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
button.ghost{background:#fff;color:#4a5159;border:1px solid #c9cfd8;border-radius:5px;padding:6px 12px;font-size:12px;cursor:pointer;font-family:inherit}
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
<h1>LoadMonitor24<small id="ver">로컬 전용 · 외부 전송 없음</small></h1>
<div id="stub_banner" style="display:none;background:#fff1c2;border:2px solid #e08a00;color:#6b3a00;border-radius:6px;padding:10px 14px;margin:8px 0 12px;font-size:13px;line-height:1.6"></div>
<div class="steps">
 <span class="on">① 내 PC 분석 (지금 화면)</span>
 <span class="on">② 결과 확인</span>
 <span class="on">③ 팀 업로드 / 공유폴더 저장</span>
 <a href="/team" target="_blank">④ 팀 취합 화면 →</a>
 <a href="/guide" target="_blank">사용 안내</a>
</div>
<div class="sub">PC 흔적에서 업무 로드를 추출합니다. <b>투입 MM</b>(실제 일한 양)과 <b>가용 MM</b>(일할 수 있었던 양 — 연차는 일자에서 차감)을
 나란히 내고 <b>로드율 = 투입 ÷ 가용</b>으로 비교합니다. 1 MM = 8h × 그 달 평일수(주40시간). 야근은 상한 없이 그대로 반영됩니다.</div>

<div class="card"><div class="row">
 <span class="chip on" data-d="ytd">올해</span> <span class="chip" data-d="30">1개월</span><span class="chip" data-d="90">3개월</span>
 <span class="chip" data-d="180">6개월</span><span class="chip" data-d="365">1년</span>
 <label>시작 <input type="date" id="from"></label><label>끝 <input type="date" id="to"></label>
 <label><input type="checkbox" id="ai" checked> AI 정제</label>
 <label><input type="checkbox" id="skip"> 재분석만</label>
 <button class="run" id="go">분석 실행</button>
 <button class="run" id="stop" style="background:#c0122f;display:none">중지</button>
 <span class="state" id="state">대기 중</span>
 <span style="flex:1"></span>
 <button class="ghost" id="report">보고서 만들기(리포트·분석리포트·얼린 보고서)</button>
 <button class="ghost" id="teamagg">팀 취합</button>
 <button class="ghost" id="collect2">추가 PC 수집</button>
 <button class="ghost" id="teamup">팀 서버 업로드</button>
 <button class="ghost" id="diag">AI 연결 진단</button>
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
</div></div>

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

<div class="card"><h2>주간 활동 추이 <span class="state">막대 = 신호 건수 · 선 = PC 가동시간</span></h2>
 <div id="weekly"></div>
 <div class="row" id="wleg" style="margin-top:6px;font-size:11px;color:#4a5159"></div>
 <div class="note" id="wnote" style="display:none;color:#a86400"></div>
 <div id="wclump"></div></div>

<div class="card"><h2>업무별 상세 <span class="state" id="rsrc"></span></h2>
 <table id="res"></table>
 <div class="note">상세설명은 Copilot이 원문 근거를 읽고 작성합니다. 원문은 주간/월간/상세 리뷰 탭에서 확인.</div></div>

<div class="card"><h2>수집 데이터 현황</h2><div class="row" id="src"></div>
 <div class="note">빨간 항목이 결과 품질을 떨어뜨립니다. 노란 항목은 수집은 됐지만 기간 대비 부족한 것, 회색은 선택 항목입니다.</div></div>

<div class="card"><h2>팀 취합 업로드 <span class="state">자동 전송하지 않습니다 — 서버에 닿는 망에서 버튼으로 보냅니다</span></h2>
 <div class="row" style="align-items:center;gap:6px;margin-bottom:8px">
  <span class="state" style="flex:none">저장소</span>
  <input id="tuurl" placeholder="http://10.115.147.68:9310" style="flex:1;min-width:200px;padding:5px 8px;border:1px solid #d7dbe0;border-radius:5px;font-size:12px">
  <button class="ghost" id="tuping">연결 확인</button>
  <span class="state" id="tustat"></span></div>
 <div id="tuavail"></div>
 <div id="tupend"></div>
 <div class="row" style="margin-top:8px;align-items:center">
  <button class="ghost" id="tusend" style="border-color:#2a78d6;color:#2a78d6">팀 서버 업로드</button>
  <button class="ghost" id="tufolder">공유폴더로 저장</button>
  <button class="ghost" id="tubuild" style="display:none">지금 묶음 만들기</button>
  <button class="ghost" id="tuopen">묶음 폴더 열기</button>
  <span class="state" id="tumsg"></span></div>
 <div class="note" id="tusent"></div>
 <div class="note">팀 서버를 켜고 끄는 것과 취합 결과 보기는 <b><a href="/team" target="_blank">팀 취합 화면</a></b>에 있습니다
 (LoadMonitor24-팀취합.bat 과 같은 화면).</div>
 <div class="note">분석이 끝나면 보낼 묶음이 <b>대기</b>로 쌓입니다. 팀 서버에 닿는 망(사내망)에서 [팀 서버 업로드]를
 한 번 누르면 <b>밀린 기간까지 함께</b> 올라가고, 보낸 묶음은 <code>report\\upload_sent\\</code> 로 옮겨집니다.
 닿지 않는 망에서 눌러도 아무것도 잃지 않고 그대로 대기합니다. 서버 대신 공유폴더로 낼 수도 있습니다.</div>
 <div class="note">보내는 것: 그 기간의 판정 결과(과제·업무·MM)와 근거 신호 목록입니다 —
 메일 제목·회의 제목·동료 이름이 포함될 수 있습니다(개인 폴더 신호는 이미 제외됨). 사내망 전용으로만 쓰세요.</div></div>


<div class="card"><h2>MM 산정 근거 <span class="state">투입 ÷ 가용 = 로드율 · 1 MM = 8h × 그 달 평일수</span></h2>
 <div id="mmbasis"></div></div>

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
 <span id="sb_sampler"></span>
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
function setDays(n,el){const t=new Date();
 // 'ytd' = 올해 1월 1일부터. 팀 전체가 같은 기간이어야 취합이 맞아 이것을 기본으로 둔다
 const a=(n==="ytd")?new Date(t.getFullYear(),0,1):new Date(t.getTime()-n*86400000);
 $("from").value=iso(a);$("to").value=iso(t);
 document.querySelectorAll("[data-d]").forEach(c=>c.classList.toggle("on",c===el));}
document.querySelectorAll("[data-d]").forEach(c=>c.onclick=()=>{
 const v=c.dataset.d;setDays(v==="ytd"?"ytd":+v,c);});
setDays("ytd",document.querySelector('[data-d="ytd"]'));

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
 // '작업창' 은 예전에 '파일' 로 뭉쳐 들어가 하루 8건 상한을 다 먹고 실제 문서를 밀어냈다 — 별도 계열.
 const keys=[["파일","#2a78d6"],["작업창","#7a8a99"],["메일","#0e8c7a"],["회의","#e08a00"],["커밋","#6c4fb8"],["팀즈","#4a7f9e"]];
 const W=740,H=180,L=34,Rm=38,B=26,T=12,iw=(W-L-Rm)/tr.length;
 const cmax=Math.max(...tr.map(w=>keys.reduce((a,[k])=>a+w[k],0)),1);
 const hmax=Math.max(...tr.map(w=>w.pc_h),1);
 let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%">`;
 for(let g=0;g<=3;g++){const y=T+(H-T-B)*g/3;
  s+=`<line x1="${L}" x2="${W-Rm}" y1="${y}" y2="${y}" stroke="#eef0f3"/>
  <text x="${L-5}" y="${y+3}" text-anchor="end" style="font-size:9px;fill:#98a0a8">${Math.round(cmax*(1-g/3))}</text>
  <text x="${W-Rm+5}" y="${y+3}" style="font-size:9px;fill:#c8a06a">${(hmax*(1-g/3)).toFixed(0)}h</text>`;}
 tr.forEach((w,i)=>{
  const x=L+i*iw+iw*0.18,bw=iw*0.64;let y=H-B;
  keys.forEach(([k,c])=>{const h=(H-T-B)*w[k]/cmax;if(h>0.5){y-=h;
   s+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" fill="${c}" rx="1"><title>${w.label} ${k} ${w[k]}건</title></rect>`;}});
  if(i%2===0)s+=`<text x="${(x+bw/2).toFixed(1)}" y="${H-B+13}" text-anchor="middle" style="font-size:9px;fill:#8b929b">${w.label}</text>`;
 });
 // PC 기록이 없는 버킷은 0h 가 아니라 '모름' 이다(이벤트 로그가 롤오버되면 과거 주는 구조적으로 기록이 없다).
 // 예전에는 0 으로 그려 선이 바닥에 붙어 'PC 가동이 적용 안 된다'로 읽혔다 — 선을 끊고 회색 밴드로 칠한다.
 const has=w=>(w.pc_wd===undefined)?(w.pc_h>0):(w.pc_days>0);
 tr.forEach((w,i)=>{if(w.pc_wd!==undefined&&!has(w))
  s+=`<rect x="${(L+i*iw).toFixed(1)}" y="${T}" width="${iw.toFixed(1)}" height="${(H-T-B).toFixed(1)}" fill="#f2f3f5"><title>${w.label} PC 기록 없음 (평일 ${w.pc_wd}일 중 0일) — 0시간이 아니라 기록이 없는 구간입니다</title></rect>`;});
 let seg=[];
 const flush=()=>{if(seg.length>1)s+=`<polyline points="${seg.join(" ")}" fill="none" stroke="#c8a06a" stroke-width="2"/>`;seg=[];};
 tr.forEach((w,i)=>{if(has(w))seg.push(`${(L+i*iw+iw/2).toFixed(1)},${(H-B-(H-T-B)*w.pc_h/hmax).toFixed(1)}`);else flush();});
 flush();
 tr.forEach((w,i)=>{if(has(w)){
  const part=(w.pc_wd!==undefined&&w.pc_days<w.pc_wd);
  s+=`<circle cx="${(L+i*iw+iw/2).toFixed(1)}" cy="${(H-B-(H-T-B)*w.pc_h/hmax).toFixed(1)}" r="2.6" fill="${part?"#fff":"#c8a06a"}" stroke="#c8a06a" stroke-width="${part?1.4:0}"><title>${w.label} PC ${w.pc_h}h${w.pc_wd!==undefined?` · 기록 ${w.pc_days}/${w.pc_wd}평일`:""}</title></circle>`;}});
 el.innerHTML=s+"</svg>";
 $("wleg").innerHTML=keys.map(([k,c])=>`<span><span class="dot" style="background:${c}"></span>${k}</span>`).join("")+
  '<span><span class="dot" style="background:#c8a06a"></span>PC 가동(h·오른쪽 축)</span>'+
  '<span><span class="dot" style="background:#f2f3f5;border:1px solid #d7dbe0"></span>PC 기록 없음</span>';
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
   $("pg_label").textContent=s.phase?`${s.phase} ${s.done}/${s.total}${pct!=null?` (${pct}%)`:""}`:(s.step||"준비 중…");
   $("pg_time").textContent=`경과 ${fmt(s.elapsed)}`+(s.eta!=null?` · 남은 시간 약 ${fmt(s.eta)}`:"");
   $("pg_hint").textContent=s.phase&&s.phase.startsWith("AI")
    ?"Copilot 왕복은 한 번에 수십 초~수 분 걸립니다. 창을 닫지 말고 두세요 — 중간에 멈추려면 [중지]."
    :"";
  }else{$("prog").style.display="none";}
  // ── 하단 상태바 ──
  $("sb_dot").style.background=s.running?"#e08a00":"#4fc47f";
  $("sb_state").textContent=s.running?(s.step||"실행 중"):"대기";
  if(s.running&&s.total){
   $("sb_prog").style.display="inline-flex";
   const pct=Math.round(s.done/s.total*100);
   $("sb_phase").textContent=`${s.phase||""} ${s.done}/${s.total}`;
   $("sb_bar").style.width=pct+"%";
   $("sb_eta").textContent=(s.eta!=null?`남은 약 ${fmt(s.eta)}`:`경과 ${fmt(s.elapsed)}`);
  }else if(s.running){
   $("sb_prog").style.display="inline-flex";
   $("sb_phase").textContent="준비 중";$("sb_bar").style.width="8%";
   $("sb_eta").textContent=`경과 ${fmt(s.elapsed)}`;
  }else{$("sb_prog").style.display="none";}
  $("sb_last").textContent=s.last_run?`마지막 분석 ${s.last_run} (${s.last_tag})`:"분석 결과 없음";
  const sr=s.sampler_restart||{};
  const srTxt=(sr.when?` · ${sr.how==="skip"||sr.how==="error"?"재시작 보류":"재시작 시도"} ${esc(sr.when)}`:"")+(sr.note?` — ${esc(sr.note)}`:"");
  // '꺼짐'(기록이 하나도 없음)일 때 예전에는 원인도 조치도 없이 같은 문장만 반복했다 — 무엇을 하면
  // 되는지 적고, 자동 기동 시도 결과도 함께 보여 준다.
  const tk=s.sampler_task;
  const tkTxt=(tk===false)?' · 로그온 자동 시작 작업이 <b>등록돼 있지 않습니다</b>'
             :((tk===true)?' · 등록 작업은 있습니다(정책·권한으로 안 돌 수 있음)':'');
  $("sb_sampler").innerHTML=(s.sampler_age_min==null)
   ?`<span style="color:#e08a00" title="창 샘플러가 없으면 투입시간이 PC 가동 하한으로만 계산돼 과소 집계될 수 있습니다">샘플러 꺼짐 — 아직 기록이 하나도 없습니다${tkTxt}${srTxt}<br><span class="dim">켜기: <b>LoadMonitor24-샘플러등록.bat</b> 실행(1회 등록 · 로그온 시 자동 시작). 이 화면도 10분에 한 번 자동 기동을 시도합니다.</span></span>`
   :(s.sampler_age_min<=10?'<span style="color:#4fc47f">샘플러 가동 중</span>'
     :`<span style="color:#e08a00" title="마지막 샘플 ${esc(s.last_sample||"")} — 멈춘 날은 PC 하한 모드로 계산됩니다">샘플러 멈춤 (${s.sampler_age_min}분 전${s.last_sample?` · 마지막 샘플 ${esc(s.last_sample)}`:""})${tkTxt}${srTxt}</span>`);
  $("go").disabled=s.running;
  $("stop").style.display=s.running?"":"none";
  $("state").textContent=s.running?"실행 중…":"대기 중";
  if(s.running)$("dlog").open=true;
  if(!s.running&&timer){clearInterval(timer);timer=null;}
  // 실행 중 새로고침하면 timer 가 없어 완료를 놓친다 — 상태 전이(running→멈춤)로 판정한다
  if(wasRunning&&!s.running){loaded={};refresh();}
  wasRunning=s.running;
 }catch(e){$("state").textContent="서버 연결 끊김 — 창을 닫고 다시 실행하세요";}
}
let wasRunning=false;
async function refresh(){
 let d;
 try{ d=await fetch("/api/dash").then(r=>r.json()); }
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
 const mm=d.meta||{};
 const inMM=(mm.total_mm!=null?mm.total_mm:d.total)||0, avMM=mm.avail_mm||0;
 $("k_load").textContent=avMM?Math.round(inMM/avMM*100)+"%":"–";
 $("sb_load").textContent=avMM?`로드율 ${Math.round(inMM/avMM*100)}% (투입 ${inMM.toFixed(2)}/가용 ${avMM.toFixed(2)} MM)`:"";
 $("sb_ver").textContent=`${d.version} · 포트 ${d.port}`;
 $("k_mm").textContent=avMM?`투입 ${inMM.toFixed(2)} / 가용 ${avMM.toFixed(2)} MM`:(d.total?d.total.toFixed(2)+" MM":"분석 전");
 const projs=[...new Set(rs.map(r=>r["Level 2"]))];
 const col=p=>PAL[projs.indexOf(p)%PAL.length];
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
   noticeBar.innerHTML='\u2139\ufe0f <b>수집만 되어 있습니다 — 아직 분석하지 않았습니다.</b> '
     +'이 상태에서는 팀 업로드 묶음도, 담당자 워크플로우도 만들어지지 않습니다.<br>'
     +'<b>이 PC 가 마지막(클라우드) PC 라면 위 [분석 실행]</b>을 누르세요. '
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
 const ji=d.judged_issues||{}, jiBits=[];
 if(ji.failed_rows>0) jiBits.push(`실패로 규칙에 남은 행 ${ji.failed_rows}`);
 if(ji.partial_chunks>0) jiBits.push(`부분 판정 청크 ${ji.partial_chunks}`);
 if(ji.aborted) jiBits.push("연속 실패로 중단");
 if(ji.repaired>0) jiBits.push(`잘린 응답 복구 ${ji.repaired}회`);
 if(ji.reextracted) jiBits.push(ji.reason||"판정 이후 재추출됨");
 const jiLine=jiBits.length?('· 판정 기록: '+jiBits.join(' · ')):"";
 const jiBad=(ji.failed_rows>0)||(ji.partial_chunks>0)||!!ji.aborted;
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
   how="[분석 실행] 옆의 <b>AI 정제</b> 체크를 켜고 다시 실행하세요 (재수집 없이 하려면 '재분석만'도 함께). Agentic·워크플로우 탭의 지난 결과는 '재추출 이후 결과'로 표시됩니다.";
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
   how="전용 Edge 창에서 Copilot 로그인 상태를 확인한 뒤 [재분석만]+AI 정제로 재실행하세요.";
  }else if(j&&d.judged_n===0){
   // 단계는 '성공'인데 판정 0건 — 왕복이 전부 실패한 경우(스텁 응답 없음·로그인 만료). 규칙 결과가 남아 있다.
   why="AI 판정은 실행됐지만 <b>판정된 신호가 0건</b>입니다"+(d.judged_total?` (대상 ${d.judged_total}건)`:"")
       +" — 왕복이 전부 실패했을 때 이렇게 됩니다"+(j.note?` (기록: ${esc(j.note)})`:"")+".";
   how="[AI 연결 진단]으로 Copilot 왕복이 되는지 확인한 뒤 [재분석만]+AI 정제로 재실행하세요. 스텁(LM_COPILOT_STUB) 환경이면 스텁 응답 파일이 있는지 보세요.";
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
  // 판정은 반영됐지만 일부 행이 실패(연속 실패 중단·부분 청크)로 규칙에 남았다 — 그 행의 과제·세부업무는 임시 이름
  jw.innerHTML='⚠ <b>AI 판정이 일부만 반영된 화면</b> — 실패한 행은 규칙이 임시로 뽑은 토큰으로 남아 있습니다.<br>'
   +jiLine+'<br>· 조치: [재분석만]+AI 정제로 재실행하면 실패한 행을 다시 판정합니다.';
  jw.style.display="";
 } else { jw.style.display="none"; }
 // 표시 정리: 항목이 많으면 상위 10개 + '기타(묶음)' — 수십 개 나열은 읽을 수 없다(실측)
 let dd=Object.entries(byP).sort((a,b)=>b[1]-a[1]).map(([l,v])=>({l,v,c:col(l)}));
 if(dd.length>12){
  const rest=dd.slice(10), sum=rest.reduce((s,x)=>s+x.v,0);
  dd=dd.slice(0,10); dd.push({l:`기타 (${rest.length}개 묶음)`,v:sum,c:"#98a0a8"});
 }
 donut($("donut"),dd,(d.total||0).toFixed(1),"MM 합계");
 $("dleg").innerHTML=dd.map(x=>`<div><span class="dot" style="background:${x.c}"></span>${esc(x.l)}<span class="v">${x.v.toFixed(2)} MM</span></div>`).join("")||'<div class="note">분석을 실행하세요</div>';
 // 프로젝트 내 업무 로드 — 과제(Level 2) 안에서 중위 업무(Level 3)별 MM 과 과제 내 비중.
 // 예: A 프로젝트 → A-1 시뮬레이션 0.4MM(50%), A-2 보고서 작성 0.2MM(25%)
 const byPj={};rs.forEach(r=>{
  const p2=r["Level 2"]||"미지정", w=r["Level 3"]||"기타";
  (byPj[p2]=byPj[p2]||{}); byPj[p2][w]=(byPj[p2][w]||0)+(r.mm||0);});
 const pjs=Object.entries(byPj).map(([p2,ws])=>({p2,ws,tot:Object.values(ws).reduce((a,b)=>a+b,0)}))
  .sort((a,b)=>b.tot-a.tot).slice(0,8);
 $("pjwork").innerHTML=pjs.map(pj=>{
  const det=Object.entries(pj.ws).sort((a,b)=>b[1]-a[1]);
  const bar=det.map(([w,v],i)=>`<i style="width:${(v/(pj.tot||1)*100).toFixed(1)}%;background:${PAL[i%PAL.length]}" title="${esc(w)} ${v.toFixed(2)} MM"></i>`).join("");
  const leg=det.map(([w,v],i)=>`<div><span class="dot" style="background:${PAL[i%PAL.length]}"></span>${esc(w)}<span class="v">${v.toFixed(2)} MM · ${(v/(pj.tot||1)*100).toFixed(0)}%</span></div>`).join("");
  return `<div style="margin:8px 0 12px">
   <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:3px">
    <span class="dot" style="background:${col(pj.p2)}"></span><b>${esc(pj.p2)}</b>
    <span class="state">${pj.tot.toFixed(2)} MM · 업무 ${det.length}개</span></div>
   <div class="bigbar">${bar}</div>
   <div class="leg" style="font-size:11px">${leg}</div></div>`;
 }).join("")||'<div class="note">분석을 실행하세요</div>';
 // 분포 개요는 9종 활동 범주('활동' 열, 정제 후) — 없으면 Level 3 로 폴백(정제 전).
 const byA={};rs.forEach(r=>{const k=(r["활동"]||"").trim()||r["Level 3"]||"기타";byA[k]=(byA[k]||0)+(r.mm||0);});
 const aa=Object.entries(byA).sort((a,b)=>b[1]-a[1]);
 const atot=aa.reduce((s,[,v])=>s+v,0)||1;
 $("actbar").innerHTML=aa.map(([l,v],i)=>`<i style="width:${(v/atot*100).toFixed(1)}%;background:${PAL[(i+3)%PAL.length]}" title="${esc(l)} ${(v/atot*100).toFixed(0)}%"></i>`).join("");
 $("actleg").innerHTML=aa.map(([l,v],i)=>`<div><span class="dot" style="background:${PAL[(i+3)%PAL.length]}"></span>${esc(l)}<span class="v">${(v/atot*100).toFixed(0)}% · ${v.toFixed(2)} MM</span></div>`).join("")||'<div class="note">분석을 실행하세요</div>';
 weekly($("weekly"),d.trend||[]);
 // 메일·일정이 기간의 일부 달만 수집된 상태(Outlook 시간 예산) — 앞 달의 메일·회의 막대가 비어 보이는 이유를 적는다
 const wn=$("wnote");
 if(wn){const mc=d.mail_coverage||null;const notes=[];
  // 추이가 수집 raw 로 그려진 화면(판정 신호가 없음 — 수집만 한 추가 PC·분석 전) — 서버가 실제로 무엇을 셌는지(trend_src)로 판단한다
  if(d.trend_src==="raw"&&d.period&&d.period[0]) notes.push(`판정에 쓰인 신호가 없어 수집 raw 를 <b>${esc(d.period[0])} ~ ${esc(d.period[1]||"")}</b> 기간으로 그렸습니다 — AI 정제를 켠 [분석 실행] 뒤에는 판정 신호 기준으로 바뀝니다.`);
  if(mc&&(mc.uncovered||[]).length) notes.push(`⚠ 메일·회의 막대는 ${mc.months}개월 중 <b>${(mc.covered||[]).length}개월</b>만 수집돼 있습니다 — 미수집 ${esc(mc.uncovered.join(", "))} (Outlook 시간 예산). [분석 실행]을 다시 돌리면 남은 달을 이어서 읽습니다.`);
  // PC 가동 선은 Windows 이벤트 로그에서 온다. 로그는 롤오버되므로 기간 앞쪽은 '0시간' 이 아니라
  // '기록 없음' 이다 — 그것을 말해 주지 않으면 'PC 가동이 적용 안 된다'로 읽힌다(제보).
  const ti=d.trend_info||{};const unit=ti.gran==="month"?"개월":"주";
  if(ti.pc_buckets_all&&ti.pc_buckets<ti.pc_buckets_all)
   notes.push(`PC 가동 선은 ${ti.pc_buckets_all}${unit} 중 <b>${ti.pc_buckets}${unit}</b>만 기록이 있습니다`
    +(ti.pc_from?` — Windows 이벤트 로그가 <b>${esc(ti.pc_from)}</b> 까지만 남아 있어 그 앞은 <b>0시간이 아니라 기록 없음</b>입니다(회색 구간).`:` — 회색 구간은 0시간이 아니라 기록이 없는 구간입니다.`));
  if(ti.pc_note) notes.push(`⚠ ${esc(ti.pc_note)}`);
  if(ti.capped>0) notes.push(`파일 막대는 하루 8건까지만 셉니다 — 이 기간에 <b>${ti.capped.toLocaleString()}건</b>이 상한에 눌렸습니다(공유폴더 재동기화가 그래프를 지배하지 않게 하는 장치입니다. 실제 신호 수는 [업무 리뷰] 탭에서 봅니다).`);
  if(ti.gran==="month") notes.push(`기간이 길어 <b>월 단위</b>로 묶어 그렸습니다(막대 하나 = 한 달).`);
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
 $("res").innerHTML="<tr><th style='width:80px'>Level 1</th><th style='width:60px'>유형</th><th style='width:150px'>Level 2 (과제)</th><th style='width:90px'>Level 3</th><th>상세설명</th><th style='width:120px'>근거(출처)</th><th style='width:58px'>비중</th><th style='width:48px'>MM</th><th style='width:36px'>확신</th></tr>"+
  (rs.length?rs.map(r=>`<tr><td>${esc(r["Level 1"])||"-"}</td><td>${esc(r["유형"]||"")}</td>
   <td><span class="dot" style="background:${col(r["Level 2"])}"></span><b>${esc(r["Level 2"])}</b></td>
   <td>${esc(r["Level 3"])}</td>
   <td style="color:#4a5159">${esc(r["상세설명"])||"<span style='color:#b9c0c8'>(AI 정제 전)</span>"}</td>
   <td style="color:#8b929b;font-size:11px">${esc(r["근거"])}</td>
   <td>${r.share}%</td><td><b>${r.mm}</b></td><td>${esc(r["확신도"])}</td></tr>`).join("")
   :"<tr><td colspan=9 style='color:#8b929b'>아직 결과가 없습니다 — 위에서 [분석 실행]을 누르세요.</td></tr>");
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
  // 프로그램 사용 이력 — 참고 지표다. 창 샘플러가 본 '맨 앞 창' 시간이라 투입 MM 과 다른 값이고,
  // 로드율 계산에는 들어가지 않는다. 같은 카드에 두되 문구로 못 박는다(안 그러면 '투입 시간'으로 읽힌다).
  const tuP=(tu&&Array.isArray(tu.programs))?tu.programs.filter(x=>x&&x.name):[];
  const tuKind=(tu&&Array.isArray(tu.by_kind))?tu.by_kind.filter(x=>Array.isArray(x)&&x.length>=2):[];
  const toolNote=tuP.length
    ?`<div class="note"><b>프로그램 사용(참고)</b> ${tuP.slice(0,8).map(x=>esc(x.name)+" "+(num(x.hours)<0.05?`<span class="dim">배경 ${num(x.bg_hours).toFixed(0)}h</span>`:num(x.hours).toFixed(1)+"h"+(num(x.bg_hours)>=1?`<span class="dim">(배경 ${num(x.bg_hours).toFixed(0)}h)</span>`:""))).join(" · ")}`
      +(tuKind.length?` — 구분 ${tuKind.map(x=>esc(x[0])+" "+num(x[1]).toFixed(1)+"h").join(" · ")}`:"")
      +(num(tu.solver_bg_h)>=1?` · 배경 솔버 가동 ${num(tu.solver_bg_h).toFixed(0)}h`:"")
      +(num(tu.unknown_h)>=1?` · 미상 ${num(tu.unknown_h).toFixed(0)}h`:"")
      +` <span class="dim">— 맨 앞 창을 띄우고 있던 시간입니다. 투입 MM·로드율에는 들어가지 않습니다.</span></div>`
    :((tu&&tu.why)?`<div class="note"><b>프로그램 사용(참고)</b> <span class="dim">${esc(tu.why)}</span></div>`:"");
  const GC={reliable:["#0f7a3d","신뢰"],caution:["#c98a00","주의"],unreliable:["#c0122f","측정 불충분"]};
  const cvReasons=cv?((Array.isArray(cv.reasons)&&cv.reasons.length)?cv.reasons:(Array.isArray(cv.missing)?cv.missing:[])):[];
  const covBadge=(cv&&GC[cv.grade])?`<span style="display:inline-block;border:1px solid ${GC[cv.grade][0]};color:${GC[cv.grade][0]};border-radius:3px;padding:0 6px;font-size:11px;margin-left:4px" title="${esc(cvReasons.join(" · "))}">${GC[cv.grade][1]}</span>`:"";
  const measTxt=ms9?`샘플러 ${cnt(ms9.sampler_days)}일 / PC 하한 ${cnt(ms9.pc_floor_days)}일 / 흔적폭 ${cnt(ms9.trace_window_days)}일 / 출장 ${cnt(ms9.offsite_days)}일 / 수동 ${cnt(ms9.manual_days)}일${ms9.method?` (${esc(ms9.method)})`:""}`:"";
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
  const pccNote=pcc?`<div class="note">월별 PC 기록 — ${Object.entries(pcc).sort().map(([k,v])=>`${esc(k)} ${Math.round(num(v)*100)}%${num(v)<0.4?" <b style='color:#b54708'>[하한 미적용]</b>":""}`).join(" · ")} (40% 미만인 달은 PC 하한·부재 추정이 꺼집니다)</div>`:"";
  const fut=pick("future_days"),tf=pick("today_fraction");
  const futNote=(fut!=null||tf!=null)?`<div class="note">가용 기준 — ${fut!=null?`미래 평일 ${cnt(fut)}일은 가용에서 제외`:""}${(fut!=null&&tf!=null)?" · ":""}${tf!=null?`오늘은 ${Math.round(num(tf)*100)}% 만 가용(분석 시각${d.as_of?" "+esc(d.as_of):""} 기준 — 다시 분석하면 갱신)`:""}</div>`:"";
  const rhNote=m.rehours?`<div class="note"><b>비업무 제외 ${num(m.dropped_n)}건 · −${num(m.dropped_h).toFixed(1)}h</b> — 판정 후 시간을 다시 재어 투입 ${m.total_mm_before_rehours!=null?num(m.total_mm_before_rehours).toFixed(2)+" → ":""}${num(m.total_mm).toFixed(2)} MM 으로 갱신했습니다(버린 신호의 시간이 남은 행에 옮겨 붙지 않습니다)</div>`:"";
  const win=v=>Array.isArray(v)?v.join("~"):(v==null?"":String(v));
  const cfgNote=cu?`<div class="note">산식 설정 — 표준 ${esc(cu.standardDayHours)}h · PC 하한 ${cu.usePcFloor===false?"끔":"켬"}${cu.pcFloorNeeds?`(${esc(cu.pcFloorNeeds)})`:""} · 주간 창 ${esc(win(cu.dayWindow))} · 점심 ${esc(win(cu.lunch))}${cu.dinner?` · 저녁 ${esc(win(cu.dinner))}`:""} · 미정 회의 ${esc(cu.tentativeMeetings||"")} · 공휴일 ${num(cu.holidays_n)}일${cu.offsiteAsWork===false?" · 종일 행사 미인정":""}${cu.samplerGapBridgeMin!=null?` · 샘플러 공백 다리 ${num(cu.samplerGapBridgeMin)}분`:""} — 팀과 다르면 팀 취합에 '산식 설정 상이' 배지가 붙습니다</div>`:"";
  mmEl.innerHTML=mo.length?`<div class="note" style="margin:0 0 6px">${esc(nb.basis||"")} — 로드율 100% = 가용 시간을 꽉 채워 일함(회색 눈금). 야근하면 100%를 넘습니다.</div>`+
   "<table><tr><th>월</th><th style='width:58px'>투입 MM</th><th style='width:58px'>가용 MM</th><th style='width:62px'>로드율</th><th style='width:130px'></th><th>투입 시간</th><th>부재</th><th>그 달 평일</th></tr>"+
   mo.map(([k,v0])=>{const v=(v0&&typeof v0==="object")?v0:{};return `<tr><td>${esc(k)}</td><td><b>${num(v.mm).toFixed(2)}</b></td><td>${num(v.avail_mm).toFixed(2)}</td>
    <td><b>${v.load_pct==null?"–":num(v.load_pct)+"%"}</b></td><td>${bar(num(v.load_pct))}</td>
    <td>${esc(v.worked)}h</td><td>${esc(v.absent||0)}일</td><td>${esc(v.workdays)}일 = ${esc(v.capacity_h)}h</td></tr>`;}).join("")+
   `</table><div class="note">연차·휴가 ${nb.absence_days||0}일은 <b>가용에서 차감</b>(일자에서 뺌) · 초과근무 ${num(nb.overtime_h).toFixed(0)}h는
   상한 없이 그대로 반영(하루 24h 물리 한계만 · 이상치 ${anoms.length}일은 아래 표) · 야근일 ${nb.night_days||0}일(산출물이 찍힌 시각의 폭으로 산정 — 취침 중 켜둔 PC는 제외) ·
   주말 근무 ${nb.weekend_days||0}일 · PC가동 하한 보정 ${num(nb.pc_floor_h).toFixed(0)}h/${nb.pc_floor_days||0}일(흔적 있는 날의 주간 투입을 PC 가동시간까지 인정 — 저장 1번=1시간 과소 방지) · 공휴일 ${nb.holidays||0}일 제외</div>
   <div class="note">측정 보정 — 점심 차감 ${num(nb.lunch_deducted_h).toFixed(0)}h · 저녁·새벽 가동 인정 ${num(nb.evening_credit_h).toFixed(1)}h · 주말 산출물 창 ${num(nb.weekend_window_h).toFixed(1)}h ·
   수동 흔적(수신·CC)만 있는 날 ${nb.floor_blocked_passive_days||0}일(하한 미적용 — 많으면 config.watchFolders 점검) · 미래 시각 신호 폐기 ${nb.future_signals_dropped||0}건 ·
   부재 추정 ${nb.inferred_absence_days||0}일(PC 도 흔적도 없는 평일 — 가용에서 차감${absd.length?": "+esc(absd.slice(0,12).join(", "))+(absd.length>12?" …":""):""})${simNote}</div>
   <div class="note">흔적 없는 평일 ${nb.no_evidence_days||0}일 — 이 수가 크면 수집이 덜 된 것입니다: Outlook을 켠 상태로 재실행하거나 config.watchFolders 를 확인하세요.</div>`
   +measNote+toolNote+rhNote+extraNote+pccNote+futNote+cfgNote
   +((Array.isArray(nb.config_warnings)&&nb.config_warnings.length)?`<div class="note" style="color:#b54708"><b>설정 경고 ${nb.config_warnings.length}건</b> — 잘못된 값은 기본값으로 대체했습니다: ${esc(nb.config_warnings.slice(0,6).join(" · "))}${nb.config_warnings.length>6?" …":""}</div>`:"")
   +(nb.utc_suspect?`<div class="note" style="color:#b54708"><b>메일 시각이 UTC 로 기록된 것 같습니다</b> — 낮 발신이 새벽 야근으로 잡힐 수 있으니 config.mm.mailTimeOffsetH(예: 9)를 확인하세요.</div>`:"")
   +(anoms.length?`<div class="note"><b>이상치 ${anoms.length}일</b> — PC 기록이 물리적으로 맞지 않아 보정한 날(투입을 자르지 않고 표시만 합니다)
    <table style="margin-top:4px"><tr><th style="width:90px">날짜</th><th>종류</th><th>원값 → 사용값</th></tr>${anoms.slice(0,30).map(a=>`<tr><td>${esc(a.date||"")}</td><td>${esc(a.kind||"")}</td><td style="color:#8b929b">${esc(fmtAnom(a.raw))} → ${esc(fmtAnom(a.used))}</td></tr>`).join("")}</table>${anoms.length>30?`<div class="note">… 외 ${anoms.length-30}일</div>`:""}</div>`:"")
   +(longd.length?`<div class="note"><b>16h 초과 ${longd.length}일</b>(자르지 않음 — 진짜 야근인지 확인하세요): ${longd.slice(0,20).map(x=>Array.isArray(x)?`${esc(x[0])}(${num(x[1]).toFixed(1)}h)`:esc(typeof x==="object"?JSON.stringify(x):String(x))).join(" · ")}${longd.length>20?" …":""}</div>`:"")
   :'<div class="note">분석을 실행하면 월별 투입·가용 MM과 로드율이 표시됩니다.</div>';
 }
 $("mcount").innerHTML=Object.entries(m.counted||{}).sort((a,b)=>b[1]-a[1])
  .map(([k,v])=>`<span class="src"><b>${esc(k)}</b> ${v}건</span>`).join("")||'<span class="note">분석을 실행하면 채워집니다</span>';
 $("mexcl").innerHTML=Object.entries(m.excluded||{})
  .map(([k,v])=>`<span class="src" style="border-color:#f0cdd5;color:#c0122f">제외: ${esc(k)} ${v}건</span>`).join("");
 const C={ok:"#0f7a3d",warn:"#c98a00",bad:"#c0122f",off:"#98a0a8"};
 $("src").innerHTML=d.sources.map(s=>`<span class="src"><span class="dot" style="background:${C[s.status]||C.off}"></span>
  <b>${s.name}</b> ${s.rows.toLocaleString()}건 · ${s.age}${s.hint?` <span style="color:${s.status==="warn"?"#c98a00":"#c0122f"}">→ ${esc(s.hint)}</span>`:""}</span>`).join("");
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
 $("go").disabled=true;timer=setInterval(poll,1000);poll();
};
$("stop").onclick=async()=>{
 if(!confirm("실행 중인 분석을 중단할까요? 지금까지 수집·판정된 결과는 보존됩니다."))return;
 $("stop").disabled=true;
 await fetch("/api/stop",{method:"POST"});
 $("stop").disabled=false;$("stop").style.display="none";
 if(timer){clearInterval(timer);timer=null;}
 loaded={};refresh();poll();tuLoad();
};
// ── 팀 취합 업로드 카드 (자동 전송 없음 — 가능한 망에서 버튼으로) ──
let TU={pending:[],sent:[],url:"",share:""};
function tuBusy(on,msg){
 ["tusend","tufolder","tuping","teamup"].forEach(id=>{const b=$(id);if(b)b.disabled=on;});
 $("tumsg").textContent=msg||"";
}
async function tuLoad(){
 const d=await fetch("/api/teamupload").then(r=>r.json()).catch(()=>null);
 if(!d||!d.ok||!d.pending){
  // 모를 때 '없음'이라고 하면 보낼 것이 있는데도 못 보내게 된다 — 확인 실패라고 말한다
  const el=$("tupend");
  if(el)el.innerHTML='<div class="note" style="color:#c0122f">대기 목록을 확인하지 못했습니다'
   +((d&&d.error)?` — ${esc(d.error)}`:"")+'. [묶음 폴더 열기]로 report\\\\upload_pending 을 직접 확인하세요.</div>';
  if(d&&d.url&&$("tuurl")&&!$("tuurl").value)$("tuurl").value=d.url;
  TU={pending:[],sent:[],url:(d&&d.url)||"",share:(d&&d.share)||"",
      unknown:true,error:(d&&d.error)||"통신 실패"};
  return;
 }
 TU=d;
 const inp=$("tuurl");
 if(inp&&document.activeElement!==inp)inp.value=d.url||"";
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
  :'<div class="note">대기 중인 묶음이 없습니다 — [분석 실행]을 하면 여기에 쌓입니다.</div>';
 const sb=$("tusend");
 if(sb)sb.textContent="팀 서버 업로드"+(p.length?` (${p.length}건)`:"");
 const st=d.sent||[];
 $("tusent").textContent=st.length?`최근 보냄: ${st.slice(0,3).map(x=>x.when).join(" · ")}`:"";
 if(d.auto)$("tustat").textContent="(설정: 분석 후 자동 전송도 시도)";
 $("tupend").querySelectorAll("[data-drop]").forEach(btn=>btn.onclick=async()=>{
  if(!confirm(`${btn.dataset.drop} 묶음을 대기 목록에서 버릴까요?\\n(사본은 report\\\\upload_sent 에 남습니다)`))return;
  const r=await fetch("/api/teamdrop",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({tag:btn.dataset.drop})}).then(x=>x.json()).catch(()=>({ok:false}));
  if(!r.ok)alert("버리지 못했습니다: "+(r.error||""));
  tuLoad();
 });
}
$("tuping").onclick=async()=>{
 tuBusy(true,"");$("tustat").textContent="확인 중…";
 const r=await fetch("/api/teamping",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({url:$("tuurl").value})}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 $("tustat").innerHTML=r.ok?`<span style="color:#0f7a3d">● 이 망에서 연결됨 (${r.ms||0}ms)</span>`
   :`<span style="color:#c0122f">● 이 망에서는 닿지 않음</span>`;
 if(!r.ok&&r.error)$("tumsg").textContent=String(r.error).slice(0,80);
 if(r.saved)tuLoad();
};
async function tuSend(){
 let p=(TU.pending||[]).length;
 if(!p){
  // 결과가 있는데 묶음만 없는 경우가 흔하다(예전 버전으로 분석) — 여기서 바로 만들어 준다
  if(TU.unknown){
   // 한 번 실패한 상태로 굳어 '껐다 켜야 되는' 일이 없게, 누른 김에 다시 읽어 본다
   tuBusy(true,"대기 목록 다시 확인 중…");
   await tuLoad();
   tuBusy(false,"");
   p=(TU.pending||[]).length;
   if(p)return tuSendConfirmed(p);
  }
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
 if(!confirm(`대기 ${p}건을 팀 서버로 보냅니다.\\n\\n${$("tuurl").value||"(주소 없음)"}\\n\\n판정 결과와 근거 신호(메일·회의 제목 포함)가 전송됩니다. 계속할까요?`))return;
 tuBusy(true,"업로드 중… (서버가 팀 취합을 다시 계산합니다)");
 const r=await fetch("/api/teamup",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({url:$("tuurl").value})}).then(x=>x.json()).catch(()=>({ok:false,error:"통신 실패"}));
 tuBusy(false,"");
 await tuLoad();
 if(r.error==="busy"){alert("다른 작업이 실행 중입니다 — 끝난 뒤 다시 누르세요.");return;}
 if(r.unreachable){
  alert("이 망에서는 팀 서버에 닿지 않습니다.\\n\\n"+(r.error||"")+"\\n\\n묶음은 그대로 대기합니다 — 사내망에서 이 버튼을 다시 누르면 밀린 것까지 한 번에 올라갑니다.");
  $("tustat").innerHTML='<span style="color:#c0122f">● 이 망에서는 닿지 않음</span>';return;}
 const lines=(r.results||[]).map(x=>`· ${x.tag||x.file}: ${x.ok?"보냄":"실패"} ${x.msg||""}`).join("\\n");
 alert((r.ok?`업로드 완료 — ${r.sent}건`:`일부 실패 — 성공 ${r.sent||0} / 실패 ${r.failed||0}`)+(lines?"\\n\\n"+lines:""));
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
$("collect2").onclick=async()=>{
 const b={from:$("from").value,to:$("to").value,collect_only:true};
 if(!b.from||!b.to){alert("기간을 선택하세요");return;}
 if(!confirm("이 PC 의 데이터를 수집만 합니다 (분석 없음).\\n\\n"
   +"· 다른 PC 에서 가져온 폴더라면, 지난 PC 데이터는 data\\\\추가PC\\\\ 로 자동 보관됩니다\\n"
   +"· 수집 후 폴더째 본 PC 로 가져가 [분석 실행]을 누르면 두 PC 가 합산됩니다\\n"
   +"· 같은 메일·일정 등 중복 자료는 분석 때 자동 제외됩니다\\n\\n진행할까요?"))return;
 const r=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
 if(r.status===409){alert(await busyMsg(r,"이미 실행 중입니다"));return;}
 timer=setInterval(poll,1000);poll();
};
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
 $("state").textContent=`팀 취합 완료 — ${d.members}명 (Agentic ${d.agentic}명)`;
 window.open("/team/agentic","_blank");
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
 if(!d.ok)L.push("\\n대개는 전용 Edge 창에서 회사 계정 재로그인으로 해결됩니다.");
 alert(L.join("\\n"));
};
$("owa").onclick=async()=>{
 // Outlook 버전과 무관한 경로 — 전용 Edge 프로필(Copilot 과 같은 창)에 회사 계정 로그인 1회 후 읽는다
 if(!confirm("Outlook 웹(outlook.office.com)을 전용 Edge 창으로 열어 메일·일정을 읽습니다.\\n처음이면 그 창의 Outlook 탭에서 회사 계정을 한 번 선택/로그인해야 합니다.\\n계속할까요?"))return;
 $("owa").disabled=true;$("state").textContent="Outlook 웹 읽는 중… (기간은 최근 실행 기준, 수 분)";
 const d=await fetch("/api/owa",{method:"POST"}).then(r=>r.json()).catch(e=>({ok:false,error:String(e)}));
 $("owa").disabled=false;$("state").textContent="대기 중";
 if(d.rc===2){alert("로그인이 필요합니다.\\n지금 열린 전용 Edge 창의 Outlook 탭에서 회사 계정을 선택/로그인한 뒤 [Outlook 웹 읽기]를 다시 누르세요.");return;}
 alert((d.ok?"읽기 완료 — ":"읽기 실패 — ")+(d.summary||d.error||"")+"\\n\\n[재분석만]으로 다시 분석하면 반영됩니다.");
};
$("teamsweb").onclick=async()=>{
 // 팀즈 앱이 꺼져 있어도 되는 경로 — 창 읽기(UIA)와 달리 화면 렌더에 좌우되지 않는다
 if(!confirm("팀즈 웹(teams.microsoft.com)을 전용 Edge 창으로 열어 채팅을 읽습니다.\\n처음이면 그 창의 팀즈 탭에서 회사 계정을 한 번 선택/로그인해야 합니다.\\n\\n팀즈 앱은 켜져 있지 않아도 됩니다.\\n계속할까요?"))return;
 $("teamsweb").disabled=true;$("state").textContent="팀즈 웹 읽는 중… (대화방을 하나씩 열어 되감습니다, 수 분)";
 const d=await fetch("/api/teamsweb",{method:"POST"}).then(r=>r.json()).catch(e=>({ok:false,error:String(e)}));
 $("teamsweb").disabled=false;$("state").textContent="대기 중";
 if(d.rc===2){alert("로그인이 필요합니다.\\n지금 열린 전용 Edge 창의 팀즈 탭에서 회사 계정을 선택/로그인한 뒤 [팀즈 웹 읽기]를 다시 누르세요.");return;}
 alert((d.ok?"읽기 완료 — ":"읽기 실패 — ")+(d.summary||d.error||"")+"\\n\\n[재분석만]으로 다시 분석하면 반영됩니다.");
};
$("prepmove").onclick=async()=>{
 // 폴더를 다른 PC 로 옮기려면 우리(대시보드·팀 서버·Copilot Edge·샘플러)가 먼저 손을 놓아야 한다
 if(!confirm("이 폴더를 다른 PC 로 옮길 수 있도록 정리합니다.\\n\\n· 팀 서버·Copilot 창·샘플러를 종료합니다\\n· 정리 창이 열리고, 이 대시보드도 함께 닫힙니다\\n· 수집 데이터와 분석 결과는 그대로 둡니다\\n· 정리 창이 '빠르게 옮기는 방법'(Edge 캐시 제외)도 함께 알려 줍니다\\n\\n계속할까요?"))return;
 $("prepmove").disabled=true;$("state").textContent="이동 준비 중…";
 const r=await fetch("/api/prepmove",{method:"POST"}).then(x=>x.json()).catch(()=>({ok:false}));
 if(!r.ok){$("prepmove").disabled=false;$("state").textContent="대기 중";
  alert("정리 창을 띄우지 못했습니다 — LoadMonitor24-이동준비.bat 을 직접 실행하세요."+(r.error?"\\n"+r.error:""));return;}
 alert("정리 창이 열렸습니다.\\n그 창의 안내를 따라 주세요 — 잠시 뒤 이 대시보드는 닫힙니다.");
 fetch("/api/quit",{method:"POST"}).catch(()=>{});
 document.body.innerHTML='<div class="wrap"><h1>PC 이동 준비</h1>'
  +'<div class="card"><div class="note">대시보드를 종료했습니다. 열린 정리 창의 결과를 확인한 뒤 폴더를 옮기세요.<br>'
  +'옮긴 PC 에서는 LoadMonitor24-UI.bat 을 실행하면 됩니다 — 지난 PC 데이터는 자동으로 합산됩니다.</div></div></div>';
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
 const r=await fetch("/api/narrate",{method:"POST"});
 if(r.status===409){alert(await busyMsg(r,"다른 작업이 실행 중입니다"));return;}
 timer=setInterval(poll,1000);poll();
};
$("reset").onclick=async()=>{
 const all=confirm("데이터를 리셋합니다.\\n\\n[확인] 수집 데이터 + 분석 결과 모두 삭제\\n[취소] 다음 창에서 분석 결과만 삭제 선택\\n\\nCopilot 로그인 세션은 어느 쪽이든 유지됩니다.");
 let what="all";
 if(!all){ if(!confirm("분석 결과(report 폴더)만 삭제할까요?"))return; what="report"; }
 const d=await fetch("/api/reset",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({what})}).then(r=>r.json()).catch(()=>({ok:false}));
 if(d.ok){$("state").textContent=`리셋 완료 — ${d.removed}개 파일 삭제`;loaded={};refresh();}
 else{alert(d.error==="busy"?(d.hint||"작업 실행 중에는 리셋할 수 없습니다"):"리셋 실패");}
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
const AGENT_C={"상":"#1d8a4a","중":"#c98a00","하":"#8b929b"};
// 수동 재분석(Agentic·워크플로우)은 서버 스레드에서 돈다 — 끝날 때까지 /api/status 를 보며 기다린다.
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
  +'갈린 것이라면 <b>config\\projects.json</b> 의 그 과제에 <code>"level1": "신제품개발"</code> 처럼 적어 '
  +'못 박으세요. 지정한 값은 투표를 이깁니다.</div></details>';
}
// 과제(중위) 표기 병합·흐름 중복 제거 내역 — 무엇을 왜 합쳤는지 보이지 않으면 잘못된 병합을
// 사람이 찾을 수 없다. 접어 두고, 펼치면 표와 되돌리는 방법을 보여준다.
function mergeLine(m){
 if(!m)return"";
 const np=(m.pairs||[]).length, nd=(m.flow_dupes||[]).length, nr=(m.rejects||[]).length;
 if(!np&&!nd&&!nr)return"";
 const rows=(m.pairs||[]).map(p=>`<tr><td>${esc(p.from)}</td><td style="color:#8b929b">→</td><td><b>${esc(p.to)}</b></td>`
  +`<td class="dim">${esc(p.why||"")}</td><td style="text-align:right">${(p.mm||0).toFixed(2)} MM</td>`
  +`<td style="text-align:right" class="dim">신호 ${p.signals||0}</td></tr>`).join("");
 const dups=(m.flow_dupes||[]).map(x=>`<tr><td colspan="3">${esc(x.kept)}</td>`
  +`<td class="dim">${esc(x.why||"")}</td><td colspan="2" style="text-align:right" class="dim">`
  +`단계 ${(x.steps||[0,0])[0]}개 유지 · ${(x.steps||[0,0])[1]}개 버림</td></tr>`).join("");
 const rej=(m.rejects||[]).map(r=>`<tr><td colspan="3">${esc(r.a)} ↔ ${esc(r.b)}</td>`
  +`<td colspan="3" class="dim">${esc(r.why||"")}</td></tr>`).join("");
 return '<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:#4a5159">'
  +`이름 병합 ${np}건 · 흐름 중복 제거 ${nd}건${nr?` <span class="dim">(합치지 않은 것 ${nr}건)</span>`:""}`
  +'</summary><table style="width:100%;font-size:12px;margin-top:6px">'
  +(rows?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal">합친 과제 이름</th></tr>'+rows:"")
  +(dups?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal;padding-top:6px">중복으로 지운 흐름</th></tr>'+dups:"")
  +(rej?'<tr><th colspan="6" style="text-align:left;color:#8b929b;font-weight:normal;padding-top:6px">합치지 않은 것</th></tr>'+rej:"")
  +'</table><div class="note">잘못 합쳐졌으면 <b>config\\project_aliases.json</b> 의 그 줄을 지우세요. '
  +'띄어쓰기만 다른 이름은 규칙이 다시 합치므로, 영영 갈라 두려면 같은 파일 <b>never</b> 에 '
  +'<code>["이름A", "이름B"]</code> 를 적으면 됩니다. 다음 [워크플로우 재분석]부터 반영됩니다.</div></details>';
}
async function loadFlow(){
 const el=$("rv-flow");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await fetch("/api/workflow").then(r=>r.json()).catch(()=>({}));
 const nflows=(d.flows||[]).length;
 // 워크플로우는 이제 한 번의 실행으로 끝까지 판정한다(진전이 있는 한 자동으로 마저 묻는다).
 // 그래도 남았다면 두 가지 중 하나다 — 시간 예산·상한에 걸려 끊긴 것(다시 누르면 이어진다)이거나,
 // 더 늘릴 수 없어 멈춘 것(다시 눌러도 같다). 후자에 [이어서 분석]을 권하면 헛수고를 시킨다.
 const partial=d.partial&&d.missing_count?`<span style="color:#c0122f"> · ${d.missing_count}개 업무 미판정${d.failed_chunks?` (${d.failed_chunks}/${d.chunks||"?"} 묶음 실패)`:""} — ${d.resumable?"[이어서 분석]을 누르면 남은 업무만 이어서 판정합니다":"자동 마무리가 더 늘리지 못했습니다 — 다시 눌러도 같을 수 있습니다(신호가 얕거나 응답이 그 이름을 돌려주지 않는 단위)"}</span>`:"";
 const salv=d.salvaged_chunks?` · 잘린 답 복구 ${d.salvaged_chunks}묶음(부분 결과)`:"";
 const lastErr=d.last_error&&d.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(d.last_error.error)}${d.last_error.hint?` — ${esc(d.last_error.hint)}`:""}</div>`:"";
 const btn='<div class="card"><div class="row" style="align-items:center;gap:10px">'
  +'<button class="ghost" id="flowre">'+(d.partial&&d.missing_count&&d.resumable?"이어서 분석(남은 "+d.missing_count+"개)":"워크플로우 재분석")+'</button>'
  +'<span class="state" id="flowmsg">'+(d.running?"워크플로우 분석 진행 중… (진행률은 상단 진행 바)":(d.generated?esc(`생성 ${d.generated} · ${d.model_name||""}`)+(d.basis==="규칙"?" · 규칙 축(AI 판정 없음)":""):""))+'</span></div>'
  +'<div class="note">과제별로 <b>역할 → 일의 순서 → 단계별 Agent 가능성</b>을 raw 근거에서 판정합니다. '
  +'MM 배분 숫자는 AI 가 아니라 판정 실측치입니다.'+(nflows?` 업무 ${nflows}/${d.rows_units||nflows}개 판정`+partial+salv:"")+'</div>'+lastErr
  +(d.reextracted?'<div class="note" style="color:#8a5a00">⚠ <b>재추출 이후 결과</b> — '+esc(d.reextracted_note||"이 결과는 마지막 업무 로드 재추출 이전의 것입니다")+' · [워크플로우 재분석]으로 갱신하세요</div>':"")
  +mergeLine(d.merge2)+mixedLine(d.level1_mixed)+manualLine(d.manual)+'</div>';
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
   el.innerHTML=btn+`<div class="card"><div class="note">${per}워크플로우 분석이 없습니다${d.file_error?` <span style="color:#c0122f">· ${esc(d.file_error)}</span>`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""} — `
    +'AI 정제를 포함해 [분석 실행]을 돌리면 자동 생성됩니다. 위 [워크플로우 재분석]으로 지금 만들 수도 있습니다.'+oth+'</div></div>';
  }
 }else{
  // 상위(Level 1)가 바뀌는 자리마다 머리말을 넣어 '상위 → 과제' 계층이 눈에 보이게 한다.
  // flow.py 가 상위로 묶어 정렬해 내보내므로 여기서는 바뀌는 지점만 잡으면 된다.
  let _l1prev=null,_pjprev=null;
  el.innerHTML=btn+d.flows.map(f=>{
   const mm=f.mm||{}, det=Object.entries(mm.details||{});
   const mtot=det.reduce((s,[,v])=>s+v,0)||1;
   const mmBar=det.length?('<div class="bigbar" style="margin:4px 0">'
     +det.map(([k,v],i)=>`<i style="width:${(v/mtot*100).toFixed(1)}%;background:${PAL[i%PAL.length]}" title="${esc(k)} ${v} MM"></i>`).join("")
     +'</div><div class="leg" style="font-size:11px">'
     +det.map(([k,v],i)=>`<div><span class="dot" style="background:${PAL[i%PAL.length]}"></span>${esc(k)}<span class="v">${v} MM</span></div>`).join("")+'</div>'):"";
   const steps=(f.steps||[]).map(s=>`
    <tr><td style="width:26px;text-align:center;color:#8b929b"><b>${s.order}</b></td>
     <td style="width:150px"><b>${esc(s.name)}</b>${s.cycle?`<div style="color:#8b929b;font-size:11px">${esc(s.cycle)}</div>`:""}</td>
     <td>${esc(s.desc)}${s.evidence?`<div style="color:#98a0a8;font-size:11px">근거: ${esc(s.evidence)}</div>`:""}</td>
     <td style="width:220px"><span style="display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px;background:${AGENT_C[s.agent]||"#8b929b"}">Agent ${esc(s.agent)}</span>
      ${s.agent_how?`<div style="font-size:11px;color:#4a5159;margin-top:2px">${esc(s.agent_how)}</div>`:""}</td></tr>`).join("");
   const fi=d.flows.indexOf(f);
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
   if(cur!==_l1prev){head+=`<div style="margin:14px 0 6px;font-size:12px;color:#4a5159"><b>${l1lab}</b> <span class="dim">— ${new Set(d.flows.filter(x=>(x.level1||"")===cur).map(pkOf)).size}개 과제</span></div>`;_pjprev=null;}
   if(hasDet&&pk!==_pjprev){
    const sibs=d.flows.filter(x=>pkOf(x)===pk&&(x.level1||"")===cur).length;
    // 신호가 얕아 흐름을 만들지 않은 업무 — 콘솔에만 있던 것을 과제 밑에 한 줄로 알린다.
    // 이것이 안 보이면 사용자에게는 '내 일이 통째로 사라졌다' 로 읽힌다.
    const th=(d.thin||[]).filter(t=>fold2(t.project)===pk);
    const thin=th.length?`<span class="dim"> · <span title="${esc(th.map(t=>t.detail+"("+t.signals+")").join(", "))}">신호가 얕아 흐름을 만들지 않은 업무 ${th.length}개</span></span>`:"";
    head+=`<div style="margin:8px 0 4px 6px;font-size:13px"><b>${esc(pj)}</b> <span class="dim">— 담당 업무 ${sibs}개</span>${thin}</div>`;
   }
   _l1prev=cur;_pjprev=pk;
   // 과제 수만큼 길어지는 탭 — 접이식으로. 제목 줄에 역할 요약을 실어 접힌 채로도 훑는다.
   // 상위(업무 성격) 배지 — 계층은 상위(Level 1) > 과제(Level 2) > 담당업무(Level 3) 다.
   // LM20 처럼 상위로도 묶어 읽히게 제목에 배지를 달고, 아래에서 상위별로 구간을 나눈다.
   const L1C={"신제품개발":"#2a78d6","기술 내재화":"#0e8c7a","양산준비":"#e08a00","일반업무":"#8b929b"};
   const l1b=f.level1?`<span style="display:inline-block;padding:0 7px;border-radius:9px;color:#fff;font-size:11px;background:${L1C[f.level1]||"#8b929b"};margin-right:6px">${esc(f.level1)}</span>`:"";
   // 한 과제가 여러 흐름을 가질 수 있다 — 이어지지 않는 일을 억지로 한 타임라인으로 엮지 않기 위해서다.
   // 흐름 이름을 제목에 붙여 같은 과제의 다른 줄기임을 알 수 있게 한다.
   const br=f.branch?`<span class="dim"> · ${esc(f.branch)}</span>`:"";
   // 담당업무 카드는 과제 머리말 밑에 있으니 제목에는 담당업무만(과제는 title 속성으로).
   const ttl=hasDet?`<span title="${esc(pj)}">${esc(f.detail)}</span>`:esc(f.model);
   return head+`<details${fi===0?" open":""}${hasDet?' style="margin-left:6px"':''}><summary>${hasDet?"":l1b}${ttl}${br}
     <span class="state">${(mm.mm!=null)?mm.mm+" MM · ":""}단계 ${(f.steps||[]).length}개 · ${esc((f.role||"판단 유보").split("—")[0].trim())}</span></summary>
    <div class="body">
    ${(f.upstream||f.downstream)?`<div class="note" style="margin:2px 0 6px">${f.upstream?`← 앞 업무: <b>${esc(String(f.upstream).split(" / ").pop())}</b>`:""}${(f.upstream&&f.downstream)?" &nbsp;·&nbsp; ":""}${f.downstream?`→ 다음 업무: <b>${esc(String(f.downstream).split(" / ").pop())}</b>`:""}</div>`:""}
    <div style="margin:2px 0 6px"><b>역할:</b> ${esc(f.role)||"판단 유보"}</div>
    ${f.summary?`<div class="note" style="margin-bottom:6px">${esc(f.summary)}</div>`:""}
    ${mmBar}
    <table style="margin-top:6px"><tr><th></th><th>단계</th><th>무슨 일</th><th>Agent 가능성</th></tr>${steps}</table>
    </div></details>`;}).join("");
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
 if(d.running&&rb){rb.disabled=true;waitIdle().then(()=>{loaded["flow"]=0;loadFlow();});}
}
document.querySelectorAll("#tabs [data-t]").forEach(c=>c.onclick=()=>{
 document.querySelectorAll("#tabs [data-t]").forEach(x=>x.classList.toggle("on",x===c));
 document.querySelectorAll(".tab").forEach(t=>t.style.display="none");
 const id=c.dataset.t;$("tab-"+id).style.display="";
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
async function loadReview(kind){
 const el=$("rv-"+kind);
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const g={week:"week",month:"month",deep:"all"}[kind];
 const d=await fetch("/api/review?g="+g).then(r=>r.json());
 let extra={};try{extra=await fetch("/api/extra").then(r=>r.json());}catch(e){}
 const nar=extra.narratives||{};
 if(!d.groups.length){el.innerHTML='<div class="card"><div class="note">데이터 없음 — [분석 실행]을 먼저 돌리면 신호별 내역이 생성됩니다.</div></div>';return;}
 const allP=[...new Set(d.groups.flatMap(x=>x.projects.map(p=>p.name)))];
 const col=p=>PAL[allP.indexOf(p)%PAL.length];
 let pre="";
 if(kind==="deep"&&extra.entities&&(extra.entities.models||[]).length){
  const en=extra.entities;
  const disc=new Set(en.discovered||[]);
  const mrows2=(en.models||[]).map(m=>`<tr><td><b>${esc(m.name)}</b>${disc.has(m.name)?' <span class="tag" style="background:#e6f4ea;color:#0f7a3d">판정 중 발견</span>':''}</td><td style="color:#8b929b;font-size:11px">${(m.match||[]).map(esc).join(", ")||"-"}</td><td style="color:#5a626b;font-size:11px">${esc(m.obs||"")||"-"}</td></tr>`).join("");
  pre+=`<div class="card"><h2>과제 체계 <span class="state">AI가 raw에서 발견한 상위 과제 — config.projects 는 힌트로만 참고${(en.hints_used||[]).length?` (힌트: ${en.hints_used.map(esc).join(", ")})`:" (힌트 없음)"}</span></h2>
  <table><tr><th>과제</th><th>식별 키워드</th><th>채택 근거(raw)</th></tr>${mrows2}</table>
  <div class="note">힌트에 넣어도 raw에 흔적이 없으면 채택되지 않고, 판정 중 새 과제가 보이면 자동 추가됩니다.</div></div>`;
 }
 if(kind==="deep"&&extra.pivots&&extra.pivots.by_model){
  const pv=extra.pivots,WTC={"개발":"#2a78d6","사무":"#e08a00","현장":"#0e8c7a","협업":"#6c4fb8"};
  const chips=o=>Object.entries(o||{}).map(([k,v])=>`<span class="tag" style="border-left:3px solid ${WTC[k]||"#98a0a8"}">${esc(k)} ${v.toFixed(2)}</span>`).join("");
  const mrows=Object.entries(pv.by_model).map(([m2,v])=>`<tr><td><b>${esc(m2)}</b></td><td><b>${v.mm.toFixed(2)}</b></td><td>${chips(v.worktypes)}</td><td>${Object.entries(v.details).slice(0,6).map(([k,x2])=>`<span class="tag">${esc(k)} ${x2.toFixed(2)}</span>`).join("")}</td></tr>`).join("");
  const wrows=Object.entries(pv.by_worktype).map(([w2,v])=>`<tr><td><b style="color:${WTC[w2]||"#333"}">${esc(w2)}</b></td><td><b>${v.mm.toFixed(2)}</b></td><td>${Object.entries(v.models).map(([k,x2])=>`<span class="tag">${esc(k)} ${x2.toFixed(2)}</span>`).join("")}</td></tr>`).join("");
  const crows=(pv.common||[]).map(c=>`<tr><td><b>${esc(c.detail)}</b></td><td>${c.models.map(esc).join(", ")}</td><td>${c.mm.toFixed(2)}</td></tr>`).join("");
  const ep=pv.episodes||{};
  const orows=(ep.orders||[]).slice(0,10).map(o=>`<tr><td>${esc(o.start.slice(5,16))}</td><td>${esc(o.model)}</td><td>${esc(o.req)}</td><td>→ ${esc(o.done)}</td><td><b>${o.lead_h}h</b></td></tr>`).join("");
  const srows=(ep.spans||[]).slice(0,10).map(o=>`<span class="tag">${esc(o.model)} ${esc(o.start.slice(5))}~${esc(o.end.slice(5))} (${o.signals}건)</span>`).join("");
  pre+=`<div class="card"><h2>과제 → 업무유형 · 세부업무 (MM)${pv.consistent_with?` <span class="state">기준: ${esc(pv.consistent_with)} — 대시보드와 동일</span>`:""}</h2><table><tr><th>과제</th><th style="width:52px">MM</th><th>유형 배분</th><th>세부업무 상위</th></tr>${mrows}</table></div>
  <div class="grid2"><div class="card"><h2>업무유형 → 과제 (MM)</h2><table><tr><th>유형</th><th style="width:52px">MM</th><th>과제 배분</th></tr>${wrows}</table></div>
  <div class="card"><h2>공통업무 — Agentic AI 자동화 후보</h2>${crows?`<table><tr><th>세부업무</th><th>관련 과제</th><th style="width:52px">MM</th></tr>${crows}</table>`:'<div class="note">2개 이상 과제에 걸친 세부업무가 아직 없습니다 (AI 판정 후 생성)</div>'}<div class="note">여러 과제에 반복되는 업무일수록 표준화·AI 대체 우선순위가 높습니다.</div></div></div>
  <div class="card"><h2>업무 에피소드 <span class="state">외부요청 → 산출 리드타임${ep.avg_lead_h?` · 평균 ${ep.avg_lead_h}h`:""}</span></h2>
  ${orows?`<table><tr><th>요청 시각</th><th>과제</th><th>요청(시작)</th><th>산출(끝)</th><th style="width:56px">리드</th></tr>${orows}</table>`:'<div class="note">오더→산출 페어가 없습니다</div>'}
  ${srows?`<div style="margin-top:8px"><span class="state">자체진행 구간(연속 신호, 3일 공백 시 분리):</span><div style="margin-top:4px">${srows}</div></div>`:""}
  <div class="note">시작 = 외부요청(팀즈 오더·메일 수신) / 끝 = 요청과 <b>내용 연관(공통 단어·같은 세부업무)이 확인된</b> 첫 발신·산출물 — 연관 산출을 못 찾은 요청은 페어하지 않습니다. 자체진행 업무는 시작이 불명확해 연속 신호 구간으로 근사합니다.</div></div>`;
 }
 el.innerHTML=pre+d.groups.map((x,gi)=>{
  const bar='<div class="bigbar" style="height:18px">'+x.projects.map(p=>
   `<i style="width:${(p.share*100).toFixed(1)}%;background:${col(p.name)}" title="${esc(p.name)} ${(p.share*100).toFixed(0)}%"></i>`).join("")+"</div>";
  const psec=x.projects.map(p=>{
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
    ${fls?`<div style="margin-top:3px"><span class="state">산출물:</span> ${fls}</div>`:""}
    ${mts?`<div style="margin-top:3px"><span class="state">회의:</span> ${mts}</div>`:""}
    ${cms?`<div style="margin-top:4px">${cms}</div>`:""}
   </div>`;}).join("");
  const tl=x.timeline.map(day=>`<div class="d">${day.date}</div>`+day.lines.map(l=>
   `<div>${l.t} <span class="s">[${esc(l.src)}]</span> <span class="p" style="color:${col(l.proj)}">${esc(l.proj)}</span> ${l.who&&l.who!=="나"?esc(l.who)+": ":""}${esc(l.text)}</div>`).join("")).join("");
  const nx=(kind==="month")?nar[x.key]:null;
  const narH=nx?`<div style="background:#f0f6fd;border:1px solid #d6e5f7;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:12.5px;line-height:1.7">
   <b>AI 월간 리뷰</b> — ${esc(nx.summary||"")}${(nx.projects||[]).map(p=>`<div style="margin-top:4px">· <b>${esc(p.name)}</b> ${esc(p.story||"")} <span class="state">${esc(p.worktypes||"")}</span></div>`).join("")}</div>`
   :(kind==="month"?`<div class="note" style="border:1px dashed #c9cfd8;border-radius:6px;padding:8px 12px;margin:8px 0">
   이 달의 AI 리뷰 코멘트가 없습니다 — 다른 PC에서 복사했거나(코멘트는 report 폴더에 있어 복사 시 제외됨)
   AI 판정 없이 분석한 경우입니다. 상단 <b>[리뷰 코멘트 재생성]</b> 버튼으로 몇 분 만에 복구할 수 있습니다.</div>`:"");
  const wtsum=(x.wt||[]).map(([k,v])=>`${k} ${v}%`).join(" · ");
  const head=`${esc(x.label)} <span class="state">신호 ${x.signals}건 · 활동 ${x.days}일${wtsum?" · "+esc(wtsum):""}</span>`;
  const body=`${narH}${bar}${psec}${connSVG(x,col)}
   <details style="margin-top:6px"><summary style="padding:8px 12px;font-size:12px">원문 근거 타임라인 (해석 검증용 — 판정된 업무 신호만)</summary>
   <div class="body tl" style="max-height:420px;overflow:auto">${tl}</div></details>
   <div class="note" style="margin-top:6px">프로젝트 MM은 기간×신호 비중 개략치 — 확정 MM은 대시보드 기준</div>`;
  // 카드가 길어 접이식으로 — 첫 기간만 펼침. 상세 리뷰(deep)는 표 중심이라 기존 유지.
  if(kind==="deep")return `<div class="card"><h2>${head}</h2>${body}</div>`;
  return `<details${gi===0?" open":""}><summary>${head}</summary><div class="body">${body}</div></details>`;
 }).join("");
}
// ── Agentic AI 탭 ──
async function loadAgentic(){
 const el=$("rv-agentic");
 el.innerHTML='<div class="card"><div class="note">불러오는 중…</div></div>';
 const d=await fetch("/api/agentic").then(r=>r.json()).catch(()=>({}));
 const t=d.tasks||[];const a=d.analysis||null;
 const pend=a&&a.rows_pending?a.rows_pending:0;
 let h=`<div class="card"><h2>Agentic AI 과제 매칭 <span class="state">계획 12과제 ↔ 현재 업무 로드 — [분석 실행](AI 판정) 후 자동으로 매칭됩니다</span></h2>
  <div class="row" style="margin-bottom:8px">
   <button class="${a?"ghost":"run"}" id="agrun" style="padding:7px 18px;font-size:12.5px">${a?(pend?`이어서 매칭(남은 ${pend}행)`:"재매칭"):"Agentic AI 매칭 실행"}</button>
   <span class="state" id="agmsg">${d.running?"Agentic 매칭 진행 중… (진행률은 상단 진행 바)":(a?"과제 지정·제외를 바꿨거나 agentic_tasks.json 을 수정했을 때 다시 돌리세요 (묶음마다 왕복 1회, 수십 초~수 분)":"분석이 아직 없거나 자동 매칭이 실패한 경우 수동 실행 (묶음마다 왕복 1회, 수십 초~수 분)")}</span>
  </div>${d.tasks_error?`<div class="note" style="color:#c0122f">과제 목록을 읽지 못했습니다 — ${esc(d.tasks_error)}</div>`:""}${d.file_error?`<div class="note" style="color:#c0122f">${esc(d.file_error)}</div>`:""}${manualLine(d.manual)}`;
 if(!a){h+=`<div class="note">아직 매칭 결과가 없습니다${d.tag?` (기간 ${esc(d.tag)})`:""}${d.other_tag?` — <b>${esc(d.other_tag)}</b> 기간 결과는 있습니다`:""}${d.stage_note?` <span class="state">· 최근 실행 기록: ${esc(d.stage_note)}</span>`:""} — [분석 실행](AI 판정 포함)을 돌리면 자동으로 생성됩니다. 이미 분석을 마쳤다면 위 버튼으로 매칭만 실행하세요.</div></div>`;}
 else{
  const lastErr=a.last_error&&a.last_error.error?`<div class="note" style="color:#c0122f">마지막 실패 사유: ${esc(a.last_error.error)}${a.last_error.hint?` — ${esc(a.last_error.hint)}`:""}</div>`:"";
  h+=`<div class="note">기간 ${esc(a.tag)} · 업무 ${a.rows_analyzed}행 분석${a.rows_total&&a.rows_total!==a.rows_analyzed?` / 전체 ${a.rows_total}행`:""}${a.chunks?` · 묶음 ${a.chunks}회`:""}${a.failed_chunks?` <span style="color:#c0122f">· ${a.failed_chunks}/${a.chunks||"?"} 묶음 실패</span>`:""}${pend?` <span style="color:#c0122f">· ${pend}행 미판정 — 결과가 실제보다 적을 수 있음. 위 버튼으로 남은 행만 이어서 판정</span>`:""}${a.salvaged_chunks?` · 잘린 답 복구 ${a.salvaged_chunks}묶음(부분 결과)`:""}${a.mm_recalc?` · 로드 MM 은 업무 실측 합(겹침 과제는 안분)`:""}${!(a.match||[]).length&&!pend?` · <b>12과제에 걸치는 현업이 없습니다(매칭 0건 — 실패 아님)</b>`:""}</div>${lastErr}${d.reextracted?`<div class="note" style="color:#8a5a00">⚠ <b>${esc(d.reextracted_title||"재추출 이후 결과")}</b> — ${esc(d.reextracted_note||"이 매칭은 마지막 업무 로드 재추출 이전의 것입니다")}</div>`:""}</div>`;
  const axCol={"축1":"#2a78d6","축2":"#0e8c7a","축3":"#a61b4a"};
  const FITC=["#e1e0d9","#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95"];
  const fitBar=f=>{const v=Math.max(0,Math.min(100,Number(f)||0));
   const w=v>0?Math.max(3,Math.round(v*0.9)):0;
   const c=FITC[v<=0?0:Math.min(6,Math.floor(v/17)+1)];
   return `<svg width="90" height="12" style="vertical-align:middle"><rect width="90" height="12" rx="2" fill="#eef0f3"/><rect width="${w}" height="12" rx="2" fill="${c}"/><text x="${v>=45?4:(w+4)}" y="9.3" style="font-size:9px;font-weight:700;fill:${v>=45?"#fff":"#52514e"}">${v}%</text></svg>`;};
  h+=`<div class="card"><h2>① 12과제 × 현업 매칭</h2>
   <table><tr><th style="width:46px">축</th><th style="width:60px">과제</th><th style="width:190px">과제명</th>
   <th style="width:60px">적합률</th><th style="width:95px"></th><th style="width:66px">현재 로드</th><th>매칭 현업 · 사유</th></tr>`;
  const byId={};(a.match||[]).forEach(m=>byId[m.task]=m);
  t.forEach(tk=>{const m=byId[tk.id]||{fit:0,load_mm:0,work:[],reason:"관련 현업 없음"};
   h+=`<tr${m.fit>=60?' style="background:#f4faf5"':""}><td><b style="color:${axCol[tk.axis]||"#333"}">${esc(tk.axis)}</b></td>
    <td><b>${esc(tk.id)}</b></td><td title="${esc(tk.desc||"")}">${esc(tk.name)}<div class="note" style="margin:2px 0 0">${esc(String(tk.desc||"").slice(0,64))}…</div></td>
    <td><b>${m.fit}%</b></td><td>${fitBar(m.fit)}</td><td>${(m.load_mm||0).toFixed(2)} MM</td>
    <td>${(m.work||[]).map(w=>`<span class="tag">${esc(w)}</span>`).join("")}
     <div style="font-size:11px;color:#5a626b;margin-top:2px">${esc(m.reason||"")}</div></td></tr>`;});
  h+=`</table><div class="note">적합률 = 그 과제가 내 현재 업무를 자동화·대체할 수 있는 정도(Copilot 판정). 과제 설명은 과제명에 마우스를 올리면 전문이 보입니다.</div></div>`;
  h+=`<div class="card"><h2>② 신규 Agentic AI 후보 발굴</h2>`;
  if((a.new||[]).length){(a.new||[]).forEach(n=>{
   h+=`<div style="border-left:3px solid #6c4fb8;padding:4px 0 4px 12px;margin:10px 0">
    <b>${esc(n.name)}</b> <span class="state">대체 가능 로드 ≈ ${(n.load_mm||0).toFixed(2)} MM</span>
    <div style="font-size:12px;margin-top:3px"><b>동작 로직:</b> ${esc(n.logic)}</div>
    <div style="font-size:11.5px;color:#5a626b;margin-top:2px"><b>발굴 사유:</b> ${esc(n.reason)}</div></div>`;});}
  else h+=`<div class="note">근거가 충분한 신규 후보가 없습니다 — 신호가 쌓일수록 발굴 정확도가 올라갑니다.</div>`;
  h+=`</div>`;
  h+=`<div class="card"><h2>③ 분류기 검증 — 오할당 의심 <span class="state">내 업무가 아닌데 내 업무로 분류된 것</span></h2>`;
  if((a.misassigned||[]).length){
   h+=`<table><tr><th style="width:230px">업무 행</th><th>의심 사유</th><th style="width:120px"></th></tr>`;
   (a.misassigned||[]).forEach((m,i)=>{
    h+=`<tr><td><b>${esc(m.row)}</b></td><td style="font-size:11.5px;color:#5a626b">${esc(m.reason)}</td>
     <td><button class="ghost" data-ex="${esc(m.row)}" style="color:#c0122f;border-color:#f0cdd5;padding:3px 10px">내 업무 아님 — 제외</button></td></tr>`;});
   h+=`</table><div class="note">[제외]를 누르면 해당 업무의 신호가 결과에서 빠지고 MM이 재집계됩니다 (제외 이력은 config\\\\excluded_work.json 에 남습니다).</div>`;}
  else h+=`<div class="note">오할당 의심 항목이 없습니다.</div>`;
  h+=`</div>`;
 }
 el.innerHTML=h;
 const btn=$("agrun");
 if(btn)btn.onclick=async()=>{
  btn.disabled=true;btn.textContent="시작 중…";
  const r=await startTool("/api/agentic");
  if(!r.ok||!r.started){
   // 사유(error — hint)를 그대로 — '분석 실패' 한 마디로는 로그인 만료인지 자료 없음인지 알 수 없다
   btn.disabled=false;btn.textContent="Agentic AI 매칭 실행";
   const m=$("agmsg");if(m)m.innerHTML='<span style="color:#c0122f">실패: '+esc(String(r.error||""))+(r.hint?" — "+esc(String(r.hint)):"")+'</span>';
   return;}
  btn.textContent="분석 중…";
  const m=$("agmsg");if(m)m.textContent="Agentic 매칭 중… (묶음마다 수십 초~수 분 · 진행률은 상단 진행 바 · 창을 닫아도 계속 돕니다)";
  if(!timer){timer=setInterval(poll,1000);}poll();
  await waitIdle();loaded={};loadAgentic();
 };
 if(d.running&&btn){btn.disabled=true;btn.textContent="분석 중…";waitIdle().then(()=>{loaded={};loadAgentic();});}
 el.querySelectorAll("[data-ex]").forEach(b=>b.onclick=async()=>{
  if(!confirm(`"${b.dataset.ex}" 을 내 업무가 아닌 것으로 확정하고 결과에서 제외할까요?`))return;
  const r=await fetch("/api/exclude",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({row:b.dataset.ex})}).then(x=>x.json()).catch(()=>({ok:false}));
  if(r.ok){alert(`제외 완료 — 비업무 제외 ${r.removed}건`+(r.rehours&&r.dropped_h!=null?` · −${Number(r.dropped_h).toFixed(1)}h (투입 ${Number(r.total_mm||0).toFixed(2)} MM · 로드율 ${Math.round(r.load_pct||0)}%)`:" · 시간 재산정 없음(투입 MM 유지)")+", MM 재집계됨");loaded={};refresh();loadAgentic();}
  else alert("제외 실패: "+(r.error||""));
 });
}
setInterval(()=>{if(!timer)poll();},3000);
refresh();poll();tuLoad();
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
                           "elapsed": int(el), "eta": eta}
            # 상태바 요약 — mtime 만 보므로 1초 폴링에도 부담 없다
            mp = latest("mm_meta_*.json")
            payload["last_run"] = _age(_mtime(mp)) if mp else ""
            payload["last_tag"] = (os.path.basename(mp)[len("mm_meta_"):-len(".json")]
                                   if mp else "")
            act = sorted(glob.glob(os.path.join(DATA, "activity", "activity_*.csv")),
                         key=_mtime, reverse=True)
            last_ts = _mtime(act[0]) if act else 0.0
            age_min = round((time.time() - last_ts) / 60) if last_ts else None
            payload["sampler_age_min"] = age_min
            # A26 — 멈춤 판정·마지막 샘플 시각·자동 재기동 결과(10분에 1회 시도)
            payload["sampler_stale"] = bool(age_min is not None and age_min > SAMPLER_STALE_MIN)
            # '꺼짐'(기록이 하나도 없음)과 '멈춤'(있는데 오래됨)은 조치가 다르다 — 화면이 구분해 말한다.
            payload["sampler_never"] = age_min is None
            payload["sampler_task"] = (_sampler_task_exists()
                                       if (age_min is None or payload["sampler_stale"]) else None)
            payload["last_sample"] = (time.strftime("%Y-%m-%d %H:%M", time.localtime(last_ts))
                                      if last_ts else "")
            why = _sampler_autorestart(age_min)
            with LOCK:
                payload["sampler_restart"] = {"when": SAMPLER_RESTART["when"], "how": SAMPLER_RESTART["how"],
                                              "note": SAMPLER_RESTART["note"] or why}
            self._send(200, payload)
        elif self.path == "/api/dash":
            fn, rows = result_rows()
            meta = {}
            # meta 는 화면에 띄운 rows 와 **같은 태그**를 우선한다 — mtime 최신만 고르면
            # 다른 기간의 meta 로 로드율을 계산하거나, 그 meta 가 없어서 rows 는 멀쩡한데
            # 로드율만 '—' 가 되는 어긋남이 생긴다(실측: 회사 PC 화면).
            mp = None
            m2 = re.search(r"mm_rows_(\d{8}-\d{8})", fn or "")
            if m2:
                cand = os.path.join(REPORT, f"mm_meta_{m2.group(1)}.json")
                if os.path.exists(cand):
                    mp = cand
            if not mp:
                mp = latest("mm_meta_*.json")
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
            tinfo = {}
            tr = trend(per[0], per[1], (m2.group(1) if m2 else ""), info=tinfo)
            self._send(200, {"version": VERSION, "port": PORT[0], "sources": sources(per),
                             "file": fn, "rows": rows, "meta": meta,
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
                                            ("gran", "pc_note", "pc_buckets", "pc_buckets_all", "pc_from", "capped")},
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
                           "<p>대시보드의 [팀 취합] 버튼을 누르거나 LoadMonitor24-팀취합.bat 을 실행하세요.<br>"
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
                st = {"url": (cfg().get("teamServerUrl") or "").strip(),
                      "share": (cfg().get("teamShareDir") or "").strip(),
                      "auto": False,
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
                self._send(200, {"ok": False, "error": err, "pending": None, "sent": [],
                                 "url": (cfg().get("teamServerUrl") or "").strip(),
                                 "share": (cfg().get("teamShareDir") or "").strip()})
            else:
                st["ok"] = True
                self._send(200, st)
        elif self.path == "/api/projects":
            import projmap
            self._send(200, {"projects": projmap.load_user_projects(ROOT)})
        elif self.path == "/api/workflow":
            out = {"ok": False, "stage_note": _stage_note("워크플로우 분석")}
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
                    out["stage_note"] = _stage_note("워크플로우 분석")
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
            with LOCK:
                # 수동 실행의 마지막 결과(ok/error/hint)와 '지금 도는 중' — 새로고침해도 화면이 사유를 다시 말한다
                out["manual"] = MANUAL.get("flow")
                out["running"] = bool(JOB["running"] and JOB["step"] == TOOL_JOBS["flow"][1])
                out["busy"] = JOB["step"] if JOB["running"] else ""
            self._send(200, out)
        elif self.path == "/api/agentic":
            out = {"tasks": [], "analysis": None, "stage_note": _stage_note("Agentic 매칭")}
            tp = os.path.join(ROOT, "config", "agentic_tasks.json")
            try:
                tj = json.load(open(tp, encoding="utf-8-sig"))
                out["tasks"] = [t for t in ((tj.get("tasks") if isinstance(tj, dict) else None) or [])
                                if isinstance(t, dict) and t.get("id")]
                if not out["tasks"]:
                    out["tasks_error"] = "config\\agentic_tasks.json 에 과제(tasks, id 필수)가 없습니다"
            except OSError:
                out["tasks_error"] = "config\\agentic_tasks.json 이 없습니다 — 과제 목록 파일을 config\\ 에 두세요"
            except ValueError as e:
                out["tasks_error"] = f"config\\agentic_tasks.json 의 JSON 형식이 깨졌습니다({str(e)[:60]})"
            sp = latest_signals()
            if sp:
                tag = os.path.basename(sp)[len("signals_"):-len(".csv")]
                out["tag"] = tag
                ap = os.path.join(REPORT, f"agentic_{tag}.json")
                if os.path.exists(ap):
                    try:
                        a = json.load(open(ap, encoding="utf-8-sig"))
                        if isinstance(a, dict):
                            a = _agentic_stale(a, tag, ap, out)
                            out["analysis"] = a
                        else:
                            out["file_error"] = f"agentic_{tag}.json 의 최상위가 객체가 아닙니다 — [재매칭]으로 다시 만드세요"
                    except (OSError, ValueError) as e:
                        out["file_error"] = f"agentic_{tag}.json 을 읽지 못함({type(e).__name__}) — [재매칭]으로 다시 만드세요"
                else:
                    other = sorted(glob.glob(os.path.join(REPORT, "agentic_*.json")))
                    if other:
                        ot = os.path.basename(other[-1])[len("agentic_"):-len(".json")]
                        if ot != tag:
                            out["other_tag"] = ot
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
                                  ("narratives", f"ai_narratives_{tag}.json"),
                                  ("entities", f"entities_{tag}.json")):
                    p = os.path.join(REPORT, name)
                    if os.path.exists(p):
                        try:
                            with open(p, encoding="utf-8") as f:
                                out[key] = json.load(f)
                        except (OSError, ValueError):
                            pass
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
        elif self.path.startswith("/api/data"):
            src = (self.path.split("src=")[-1] if "src=" in self.path else "files")
            pats = {"mail": "outlook/mail.csv", "cal": "outlook/calendar.csv",
                    "files": "files/files.csv", "recent": "files/recent.csv",
                    "git": "files/git_commits.csv", "pc": "pc/pc_on.csv",
                    "teams": "m365/teams_*.csv", "act": "activity/activity_*.csv"}
            rows, cols, fns = [], [], []
            for f in sorted(glob.glob(os.path.join(DATA, pats.get(src, "files/files.csv")))):
                rs = _rows(f)
                if rs:
                    fns.append(os.path.basename(f))
                    cols = cols or list(rs[0].keys())
                    rows += rs
            total = len(rows)                       # 자르기 '전' 실제 수집량 — 400 고정 오인 방지
            rows = rows[-400:][::-1]
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
            # 팀 취합은 자동 전송하지 않는다 — 팀 서버는 특정 망에서만 닿기 때문(실측).
            # 여기서는 사용자가 '지금 이 망에서' 누른 것만 처리한다. teamup.py 가 --json 으로
            # 마지막 줄에 결과를 주므로 건별 성공/실패를 그대로 화면에 돌려준다.
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, {"ok": False, "error": "bad json"})
                return
            url = str(b.get("url") or "").strip().rstrip("/")
            if url:
                # 형식이 틀린 주소를 그대로 저장하면 멀쩡하던 주소가 사라진다(검증 확정).
                # 연결 여부와는 무관하게 '형식'만 본다 — 서버망 밖에서 미리 적어 두는 것이 정상 흐름이라서.
                from urllib.parse import urlparse
                u = urlparse(url)
                if u.scheme not in ("http", "https") or not u.netloc or any(c.isspace() for c in url):
                    self._send(200, {"ok": False,
                                     "error": "주소 형식이 올바르지 않습니다 — 예: http://10.115.147.68:9310"})
                    return
            saved = False
            if url and url != (cfg().get("teamServerUrl") or "").strip():
                saved = _save_team_url(url)      # 형식이 맞는 주소만 설정에 남긴다
            cmd = [sys.executable, os.path.join(ROOT, "teamup.py"), "--json"]
            if self.path == "/api/teamping":
                cmd += ["--ping"] + (["--url", url] if url else [])
                timeout, step = 30, ""
            elif self.path == "/api/teamfolder":
                cmd += ["--to-folder", str(b.get("share") or "")]
                timeout, step = 600, "공유폴더 저장"
            else:
                cmd += ["--upload"] + (["--url", url] if url else [])
                timeout, step = 1800, "팀 서버 업로드"
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
                if saved:
                    res["saved"] = True
                self._send(200, res)
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "error": f"{timeout // 60}분 내에 끝나지 않았습니다 — 묶음은 그대로 대기합니다"})
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
                                    "없습니다 — [포트 바꾸기] 로 다른 번호를 쓰세요.")
                        elif lo and lo <= port <= hi:
                            msg += (f"\n이 PC 의 임시 포트 범위가 {lo}~{hi} 이고 {port} 이 그 안에 "
                                    "듭니다 — 다른 프로그램이 '바깥으로 연결' 하며 잠깐 쓴 것입니다. "
                                    "잠시 뒤 다시 누르거나, 번호를 " + str(max(hi + 1, 19310))
                                    + " 처럼 그 범위 밖으로 바꾸면 다시 생기지 않습니다.")
                        else:
                            msg += "\n잠시 뒤 다시 시도하거나 [포트 바꾸기] 를 쓰세요."
                    elif kind == "unreadable":
                        msg = (f"포트 {port} 이 쓰이고 있는데 무엇이 쥐고 있는지 확인하지 못했습니다"
                               " (권한 또는 보안 프로그램). [포트 바꾸기] 를 쓰세요.")
                    else:
                        msg = (f"포트 {port} 을 LoadMonitor 가 아닌 프로그램이 쓰고 있습니다 — {who}")
                        if occ and occ[0].get("exe"):
                            msg += f"\n실행 파일: {occ[0]['exe']}"
                        if occ and occ[0].get("cmd"):
                            msg += f"\n명령줄: {occ[0]['cmd'][:160]}"
                        msg += ("\n무엇인지 모르겠으면 죽이지 마세요 — 사내 보안·백업 프로그램일 수 "
                                "있습니다. [포트 바꾸기] 가 안전합니다.")
                    if not force:
                        if take == "no" and kind in ("legacy_lm", "other_lm", "unknown"):
                            bad = [x for x in occ if x["protected"]]
                            if bad and any(x["self"] for x in bad):
                                msg += ("\n\n[!] 그 프로세스는 이 대시보드 자신입니다 — "
                                        "팀 서버 포트와 대시보드 포트가 같습니다. "
                                        "[포트 바꾸기] 로 다른 번호를 쓰세요.")
                            elif bad:
                                msg += ("\n\n이 프로그램은 강제로 끝낼 수 없습니다 "
                                        "(시스템 프로세스이거나 다른 계정 소유) — "
                                        "그 계정에서 닫거나 [포트 바꾸기] 를 쓰세요.")
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
                                                  "[포트 바꾸기] 를 쓰세요."})
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
                    lf = open(TS_LOG, "a", encoding="utf-8")
                    flags = NO_WIN
                    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
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
                                              "그 서버 창을 직접 닫거나 [포트 바꾸기] 를 쓰세요."})
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
        elif self.path == "/api/teamport":
            # 점유자를 죽이고 싶지 않을 때의 안전한 길. 팀원 주소가 바뀐다는 사실은 화면이 알린다.
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
                newp = int(b.get("port") or 0)
            except (ValueError, TypeError):
                self._send(400, {"ok": False, "error": "포트 번호가 아닙니다"})
                return
            if not (1024 <= newp <= 65535):
                self._send(200, {"ok": False, "error": "1024~65535 사이의 번호를 쓰세요"})
                return
            if newp == PORT[0]:
                self._send(200, {"ok": False, "error": f"{newp} 은 이 대시보드가 쓰는 번호입니다 "
                                                       "— 다른 번호를 쓰세요"})
                return
            rsv = _port_reserved(newp)
            if rsv:
                self._send(200, {"ok": False, "error": f"{newp} 은 윈도우 예약 포트 범위({rsv})입니다"
                                                       " — 다른 번호를 쓰세요"})
                return
            free, why = _bind_free(newp)
            if not free:
                self._send(200, {"ok": False, "error": f"{newp} 도 지금 쓸 수 없습니다({why})"
                                                       " — 다른 번호를 쓰세요"})
                return
            old = str(cfg().get("teamServerUrl") or "")
            m = re.match(r"^(https?://)([^:/]+)", old)
            ips = local_ips()
            host = m.group(2) if m else (ips[0] if ips else "127.0.0.1")
            url = f"http://{host}:{newp}"
            ok = _save_cfg("teamServerUrl", url)
            log(f"[팀 서버] 포트 변경 → {newp} ({url})" if ok else "[팀 서버] 포트 변경 실패")
            self._send(200, {"ok": ok, "port": newp, "url": url,
                             "here": [f"http://{ip}:{newp}" for ip in ips],
                             "error": "" if ok else "config 저장에 실패했습니다"})
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
                p = subprocess.run(cmd, capture_output=True, timeout=3600, cwd=ROOT,
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                            PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
                txt = (p.stdout or b"").decode("utf-8", "replace").strip()
                err = (p.stderr or b"").decode("utf-8", "replace").strip()
                for ln in txt.splitlines():
                    if ln and not ln.startswith("{"):
                        log(ln)
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
                try:
                    n_re = int(res.get("retagged") or 0)
                except (TypeError, ValueError):
                    n_re = 0
                if p.returncode == 0 and res.get("ok") and n_re > 0:
                    # 재분류로 과제(Level 2)가 바뀌었으니 Agentic 의 실측 load_mm 도 다시(왕복 없음).
                    # **0건이면 부르지 않는다** — 0건이면 retag.py 가 결과 파일을 다시 쓰지 않으므로(정제본 유지)
                    # 재계산할 것이 없고, 원본 행(규칙 이름)에는 Agentic work 이름이 거의 없어 원본으로 재계산하면
                    # load_mm 이 30배 줄었다(실측 5.80→0.18). n>0 이면 retag.py 가 정제본을 지워 대시보드
                    # (result_rows)와 recalc_file(details.rows_path)이 같은 mtime 규칙으로 원본을 읽으므로 그때만 맞다.
                    agentic_recalc(str(res.get("tag") or ""))
                elif p.returncode == 0 and res.get("ok"):
                    log("[agentic] 재분류 0건 — 정제본 유지, MM 실측 재계산 건너뜀")
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
            for fn2 in (kill_job, kill_copilot_edge):
                try:
                    fn2()
                except Exception as e:
                    log(f"[중지] {fn2.__name__} 실패({type(e).__name__}) — 계속 진행")
            if had_pid:
                log("[중지] 사용자 요청으로 분석을 중단했습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
            elif was:
                # 팀 취합·리포트·재분류 등 짧은 동기 작업은 pid 를 추적하지 않아 못 죽인다 —
                # "중단했습니다"라고 거짓 기록하지 않는다
                log("[중지] 지금 도는 작업은 중간 중단을 지원하지 않습니다 — 곧 끝나면 멈춥니다")
            self._send(200, {"ok": True, "stopped": was and had_pid})
        elif self.path == "/api/reset":
            n = int(self.headers.get("Content-Length", 0))
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                b = {}
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                if self._freezing():        # 굽는 중에 report\ 를 지우면 사본이 반쪽·실패가 된다
                    return
                JOB.update(running=True, step="데이터 리셋")
            what = b.get("what") or "report"          # report | all
            removed = 0
            targets = [REPORT]
            if what == "all":
                targets.append(DATA)
            keep_q = not b.get("drop_queue")      # 아직 못 보낸 팀 업로드 묶음은 기본 보존
            for base in targets:
                for root, _dirs, files in os.walk(base):
                    if "copilot_profile" in root:     # Copilot 로그인 세션은 보존
                        continue
                    if keep_q and "upload_pending" in root:
                        continue                      # 보내야 할 것을 리셋으로 잃지 않게(검증 지적)
                    for fn in files:
                        try:
                            os.remove(os.path.join(root, fn))
                            removed += 1
                        except OSError:
                            pass
            log(f"[리셋] {'수집 데이터+결과' if what == 'all' else '분석 결과'} {removed}개 파일 삭제"
                " (Copilot 로그인 세션은 유지)")
            with LOCK:
                JOB.update(running=False, step="")
            self._send(200, {"ok": True, "removed": removed, "what": what})
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
        elif self.path == "/api/owa":
            # Outlook 웹 읽기(대체②)를 손으로 — 로그인 직후 재수집용. 기간은 최근 실행(last_run.period) 또는 90일.
            d0 = d1 = ""
            try:
                with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
                    per = json.load(f).get("period") or []
                if len(per) == 2:
                    d0, d1 = per
            except (OSError, ValueError):
                pass
            if not (d0 and d1):
                import datetime as _dt
                d1 = _dt.date.today().isoformat()
                # 화면 기본값과 같게 — 올해 1월 1일부터
                d0 = _dt.date(_dt.date.today().year, 1, 1).isoformat()
            try:
                r2 = subprocess.run([sys.executable, os.path.join(ROOT, "collect", "Get-OutlookWeb.py"),
                                     "--from", d0, "--to", d1, "--force"],
                                    capture_output=True, timeout=1500, cwd=ROOT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                txt = (r2.stdout or b"").decode("utf-8", "replace")
                tail = [ln for ln in txt.strip().splitlines() if ln.strip()][-4:]
                log(f"[Outlook 웹] rc={r2.returncode} " + (tail[-1] if tail else "")[:120])
                self._send(200, {"ok": r2.returncode == 0, "rc": r2.returncode, "period": [d0, d1],
                                 "summary": " / ".join(t.replace("[outlook-web] ", "") for t in tail)[:600]})
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "rc": -1, "error": "25분 내 끝나지 않음"})
            except OSError as e:
                self._send(200, {"ok": False, "rc": -1, "error": f"실행 실패({type(e).__name__})"})
        elif self.path == "/api/teamsweb":
            # 팀즈 웹 읽기를 손으로 — 로그인 직후 재수집용. 기간은 Outlook 웹과 같은 규칙.
            # --force 는 주지 않는다: 이 파일은 '그때 화면에 보인 대화'만 담으므로 누적이 자산이다.
            d0 = d1 = ""
            try:
                with open(os.path.join(REPORT, "last_run.json"), encoding="utf-8-sig") as f:
                    per = json.load(f).get("period") or []
                if len(per) == 2:
                    d0, d1 = per
            except (OSError, ValueError):
                pass
            if not (d0 and d1):
                import datetime as _dt
                d1 = _dt.date.today().isoformat()
                d0 = _dt.date(_dt.date.today().year, 1, 1).isoformat()
            try:
                r2 = subprocess.run([sys.executable, os.path.join(ROOT, "collect", "Get-TeamsWeb.py"),
                                     "--from", d0, "--to", d1],
                                    capture_output=True, timeout=1500, cwd=ROOT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
                txt = (r2.stdout or b"").decode("utf-8", "replace")
                tail = [ln for ln in txt.strip().splitlines() if ln.strip()][-4:]
                log(f"[팀즈 웹] rc={r2.returncode} " + (tail[-1] if tail else "")[:120])
                self._send(200, {"ok": r2.returncode == 0, "rc": r2.returncode, "period": [d0, d1],
                                 "summary": " / ".join(t.replace("[teams-web] ", "") for t in tail)[:600]})
            except subprocess.TimeoutExpired:
                self._send(200, {"ok": False, "rc": -1, "error": "25분 내 끝나지 않음"})
            except OSError as e:
                self._send(200, {"ok": False, "rc": -1, "error": f"실행 실패({type(e).__name__})"})
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
                tmp = os.path.join(_tf.gettempdir(), "LM22-Prepare-Move.ps1")
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
            pf = os.path.join(tempfile.gettempdir(), "lm_diag_prompt.txt")
            try:
                with open(pf, "w", encoding="utf-8") as f:
                    f.write("연결 확인용 질문입니다. 아래 JSON 한 줄만 그대로 출력하세요.\n"
                            '{"ok":"연결됨"}\n')
                r2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "copilot_auto.py"),
                                     "--send", pf, "--fresh"], capture_output=True, timeout=300,
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
            self._send(200, res)
        elif self.path == "/api/narrate":
            with LOCK:
                if JOB["running"]:
                    self._send(409, {"ok": False, "error": "busy"})
                    return
                if self._freezing():        # judge.py --narrate-only 가 report\ 를 다시 쓴다
                    return
                JOB.update(running=True, log=[], step="리뷰 코멘트 재생성",
                           started=time.time(), phase="", done=0, total=0)
            threading.Thread(target=narrate_job, daemon=True).start()
            self._send(200, {"ok": True})
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
        else:
            self._send(404, {"error": "not found"})


def main():
    port = None
    for p in range(9148, 9168):
        try:
            s = socket.socket()
            s.bind(("127.0.0.1", p))
            s.close()
            port = p
            break
        except OSError:
            continue
    if port is None:
        print("사용 가능한 포트가 없습니다 (9148-9167)")
        return 1
    PORT[0] = port
    os.makedirs(REPORT, exist_ok=True)
    # 서버로 뜰 때만 종료 정리를 건다 — 임포트 부작용이 없어야 freeze.py 가 이 모듈을 안전하게 쓴다
    import atexit
    atexit.register(cleanup_children)
    # 이전 세션이 갑자기 꺼졌어도 남아 있는 Copilot 전용 Edge를 시작 시 자가 정리
    # (다음 AI 왕복 때 자동으로 다시 뜨므로 부작용 없음)
    # 이어서 '다른 PC 에서 온 프로필 버리기' 를 같은 스레드에서 한다 — Edge 가 확실히 죽은 뒤라야
    # 잠긴 파일 없이 지워진다(별도 스레드로 띄우면 종료와 삭제가 겹친다).
    def _startup_cleanup():
        kill_copilot_edge()
        drop_foreign_profile()
    threading.Thread(target=_startup_cleanup, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"[ui] LoadMonitor24 {VERSION} — {url}  (Ctrl+C 종료)")
    # LM_NO_BROWSER(수집기·드라이버와 같은 환경변수)도 존중한다 — bat 은 인자 없이 띄우므로 회귀 실행이
    # 실제 브라우저를 열던 결함(PK-03)
    if "--no-browser" not in sys.argv and not os.environ.get("LM_NO_BROWSER"):
        target = url + "team" if "--team" in sys.argv else url
        threading.Timer(0.6, lambda: webbrowser.open(target)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
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
