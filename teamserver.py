# -*- coding: utf-8 -*-
r"""
teamserver.py — 팀 취합 서버 (LoadMonitor22)

팀 공용 PC(예: 192.168.0.10)에서 이 파일 하나를 돌려 두면:
  · 팀원들의 LoadMonitor 가 분석을 마칠 때마다 결과를 자동 업로드한다 (POST /api/upload)
  · 업로드가 올 때마다 기존 팀 취합(aggregate.py)을 다시 돌려 HTML 을 갱신한다
    (aggregate 가 팀 통합 보고서 team_full_report.html / _v3 까지 만든다 — Copilot 없이 캐시만)
  · 브라우저로 접속하면(GET /) 취합 대시보드가 바로 보인다 — 인별 현황·팀 리포트·Agentic 열지도·통합 보고서
    정적 보고서(/report /agentic /full /full_v3)는 CSP sandbox 로 origin 을 떼어 서빙한다.

  python teamserver.py                # 기본 포트 9310, 모든 인터페이스에서 수신
  python teamserver.py --port 9310
  (또는 LoadMonitor22-팀서버.bat)

저장 구조: teamdata\<이름>\ — 팀 공유폴더(teamShareDir)와 같은 배치라 aggregate.py 를
그대로 재사용한다. 사내망 전용 설계이며 인증은 없다(팀 합의 전제) — 외부망에 열지 말 것.
받는 파일은 이름 화이트리스트·경로 문자 차단·크기 상한으로 제한한다.
"""
import io
import html
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8

def _cfg():
    try:
        with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _share_root():
    r"""받는 곳과 보는 곳을 같은 폴더로 못박는다.

    예전에는 teamdata\ 로 고정이라, 팀 공유폴더(teamShareDir)를 설정해 둔 PC 에서
    서버를 켜면 '받은 자리'와 '보는 자리'가 갈라져 업로드가 화면에 영영 안 떴다."""
    d = str(_cfg().get("teamShareDir") or "").strip()
    if d and os.path.isdir(d):
        return d
    return os.path.join(ROOT, "teamdata")


def _cfg_port():
    r"""config.teamServerUrl 의 포트 — bat 과 대시보드가 서로 다른 포트를 쓰지 않게."""
    u = str(_cfg().get("teamServerUrl") or "")
    m = re.search(r":(\d{2,5})(?:/|$)", u)
    return int(m.group(1)) if m else 9310


TEAMDATA = _share_root()
MAX_BODY = 30 * 1024 * 1024          # 업로드 1회 상한 30MB
LOCK = threading.Lock()
AGG_LOCK = threading.Lock()          # 취합은 한 번에 하나만 — 겹치면 산출물을 서로 밟는다
OWNER_LOCKS = {}                     # owner → Lock: 같은 사람의 동시 업로드는 저장 구간을 직렬화한다
                                     # (겹치면 지는 요청의 되돌리기가 이긴 요청의 파일을 지웠다 — 검증 확정)
SRV = [None]                         # 종료 요청이 도달할 수 있게 서버 객체를 잡아 둔다
PORT = [0]
PIDFILE = os.path.join(ROOT, "report", "teamserver.pid")
TOKFILE = os.path.join(ROOT, "report", "teamserver.token")
TOKEN = [""]
STATE = {"last_agg": 0.0, "agg_note": "", "uploads": 0}

# 받는 파일 이름 — export.py 가 내보내는 것과 동일한 화이트리스트
NAME_OK = re.compile(
    r"^(mm_rows_\d{8}-\d{8}(_refined)?\.csv|signals_\d{8}-\d{8}\.csv|"
    r"mm_meta_\d{8}-\d{8}\.json|pivots_\d{8}-\d{8}\.json|ai_narratives_\d{8}-\d{8}\.json|"
    r"entities_\d{8}-\d{8}\.json|agentic_\d{8}-\d{8}\.json|workflow_\d{8}-\d{8}\.json)$")
OWNER_BAD = re.compile(r'[\\/:*?"<>|.]|^\s*$')   # core/owner.py 와 글자까지 같은 규칙 — 다르면 같은 사람이 두 폴더로 갈라진다
# 폴더 이름으로 쓸 수 없는 owner — 윈도우 장치 예약어(CON 폴더가 실제로 생겼다), 복원 HTML 폴더(team_report.MEMBER_HTML_DIR),
# 취합 산출물 접두어. 인원 자료와 산출물이 한 폴더에 섞이면 취합이 그 사람을 잘못 읽는다.
_OWNER_DEVICE = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
_OWNER_RESERVED = ("개인리포트",)
_OWNER_PREFIX = ("team_", "팀통합보고서")


def norm_owner(v):
    r"""owner 정규화 — NFKC · 공백 접기 · 제어/서식 문자(zero-width·BOM) 제거 · 앞뒤 공백 제거.

    보내는 쪽(core/owner.safe_owner)이 공백을 접어 보내므로 받는 쪽도 같은 축으로 맞춘다. 예전에는
    '김철수'·'김철수​'·'김철수 ' 가 폴더 두 개(또는 member.json 의 원문 owner)로 갈라졌다(검증 확정).
    금지문자는 치환하지 않는다 — 서버는 계속 거부한다(경로 이탈 방어)."""
    s = unicodedata.normalize("NFKC", str(v or ""))
    s = " ".join(s.split())
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    return " ".join(s.split()).strip()


def owner_problem(owner):
    """400 으로 거절할 사유 — 없으면 빈 문자열"""
    if OWNER_BAD.search(owner) or len(owner) > 40:
        return "owner 이름 불량"
    low = owner.casefold()
    if low in _OWNER_DEVICE:
        return "owner 이름 불량(윈도우 예약어)"
    if owner in _OWNER_RESERVED or any(low.startswith(p) for p in _OWNER_PREFIX):
        return "owner 이름 불량(취합 폴더 예약어)"
    return ""


def write_pid():
    r"""누가 띄웠든(bat·대시보드·손수) 자기 pid 를 남긴다 — 그래야 [중지] 가 상대를 안다."""
    try:
        os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
        with open(PIDFILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def write_token():
    r"""이 폴더에서 켰다는 증명 — 대시보드가 report\teamserver.token 과 맞춰 본다.

    신원 응답만으로는 부족하다. 그 포트에 먼저 붙은 아무 프로그램이나 '나는 LoadMonitor 다' 라고
    답할 수 있기 때문이다(반박 검증에서 실제로 재현됨). 이 파일을 읽을 수 있다는 것은
    같은 계정으로 같은 폴더에 접근할 수 있다는 뜻이라, 흉내내기 어려운 증거가 된다."""
    import secrets
    TOKEN[0] = secrets.token_hex(16)
    try:
        os.makedirs(os.path.dirname(TOKFILE), exist_ok=True)
        with open(TOKFILE, "w", encoding="utf-8") as f:
            f.write(TOKEN[0])
    except OSError:
        TOKEN[0] = ""       # 못 남겼으면 증명도 없다 — 없는 증거를 있는 척하지 않는다


def clear_token():
    try:
        with open(TOKFILE, encoding="utf-8") as f:
            if (f.read() or "").strip() != TOKEN[0]:
                return      # 내 것이 아니면 지우지 않는다(뒤에 뜬 인스턴스의 것일 수 있다)
        os.remove(TOKFILE)
    except OSError:
        pass


def clear_pid():
    """내 pid 일 때만 지운다 — 두 번째 인스턴스가 첫 번째의 기록을 지우면 안 된다"""
    try:
        with open(PIDFILE, encoding="utf-8") as f:
            if int((f.read() or "0").strip() or 0) != os.getpid():
                return
        os.remove(PIDFILE)
    except (OSError, ValueError):
        pass


def arg(flag, d=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def esc(v):
    """업로드로 들어온 남의 값을 화면에 낼 때 반드시 거친다 — 저장형 XSS 방지"""
    return html.escape(str("" if v is None else v), quote=True)


def run_aggregate():
    r"""업로드 반영 — 기존 팀 취합을 teamdata 대상으로 재실행 (실패해도 서버는 계속).

    여러 사람이 같은 순간에 올리면 이 함수가 동시에 불린다. 그대로 두면 aggregate.py 가
    여러 벌 동시에 돌며 같은 리포트 파일을 서로 밟는다(실측: 3명 동시 업로드에서 화면형
    리포트가 표 형식으로 강등되거나 산출물이 아예 안 생겼다). 한 번에 하나만 돌린다."""
    with AGG_LOCK:
        return _run_aggregate_once()


def _run_aggregate_once():
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, os.path.join(ROOT, "aggregate.py"), TEAMDATA],
                           capture_output=True, timeout=300, cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        if p.returncode == 0:
            # 메모는 마지막 줄 JSON 에서 만든다 — 예전 '끝에서 두 번째 줄' 방식은 aggregate 가
            # 안내 줄을 하나만 더 찍어도 메모가 엉뚱한 줄로 바뀌었다
            lines = [x for x in out.splitlines() if x.strip()]
            try:
                js = json.loads(lines[-1])
                note = (f"{js.get('members')}명 취합 · 통합 보고서 "
                        f"{'OK' if js.get('full_report') else '없음'}")
            except (ValueError, IndexError, AttributeError):
                note = lines[-2] if len(lines) >= 2 else out[-120:]
        else:
            # 실패 사유는 대개 stderr 에 있다 — 버리면 화면에 '실패 (0s)' 만 남아 손쓸 수 없다
            tail = (err or out).splitlines()
            note = (tail[-1] if tail else f"종료 코드 {p.returncode}")
        with LOCK:
            STATE["last_agg"] = time.time()
            STATE["agg_note"] = f"{'OK' if p.returncode == 0 else '실패'} ({time.time()-t0:.0f}s) {note[:120]}"
        return p.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        with LOCK:
            STATE["agg_note"] = f"실패: {type(e).__name__}"
        return False


def members():
    out = []
    if not os.path.isdir(TEAMDATA):
        return out
    for d in sorted(os.listdir(TEAMDATA)):
        mp = os.path.join(TEAMDATA, d, "member.json")
        if not os.path.exists(mp):
            continue
        try:
            m = json.load(open(mp, encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(m, dict):      # 손편집 '[]' 한 파일이 GET / · /api/team · /api/whoami 를 죽이지 않게
            continue
        if not str(m.get("owner") or "").strip():
            m["owner"] = d               # aggregate.load_members 와 같은 규칙 — 폴더명이 인원 키
        try:
            m["uploaded_at"] = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(mp)))
        except OSError:
            m["uploaded_at"] = ""
        out.append(m)
    return out


# 정적 보고서 라우트 표 — 경로 → 취합 폴더의 파일. 전부 자기완결 문서(데이터 섬·__TEAM_DATA__)라
# same-origin 요청이 필요 없다. 이스케이프가 한 곳 새더라도 /api/* 를 부를 수 없게 sandbox CSP
# 로 origin 을 떼어 서빙한다(새 탭 링크는 popups 로 허용).
REPORT_FILES = {"/report": "team_report.html", "/agentic": "team_agentic.html",
                "/full": "team_full_report.html", "/full_v3": "team_full_report_v3.html"}
REPORT_CSP = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"

PAGE_HEAD = """<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="120">
<title>LoadMonitor 팀 서버</title>
<style>
body{font:14px/1.6 'Segoe UI',sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#23282e}
h1{font-size:20px} h2{font-size:15px;margin:18px 0 8px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #e4e8ec;padding:6px 8px;text-align:left}
th{color:#5a6169;font-weight:600;background:#f7f8fa}
.note{color:#8b929b;font-size:12px} .ok{color:#1d8a4a} .old{color:#c98a00}
a.btn{display:inline-block;border:1px solid #c9cfd8;border-radius:6px;padding:5px 12px;
 text-decoration:none;color:#23282e;margin-right:8px;font-size:13px}
</style>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass                                             # 콘솔 소음 억제

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype="text/html; charset=utf-8"):
        """정적 보고서 — 바이트 그대로 + CSP sandbox(origin 분리) + nosniff"""
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Security-Policy", REPORT_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            ms = members()
            now = time.time()
            rows = []
            for m in ms:
                mp = os.path.join(TEAMDATA, str(m.get("owner")), "member.json")
                age_d = (now - os.path.getmtime(mp)) / 86400 if os.path.exists(mp) else 99
                cls = "ok" if age_d < 8 else "old"
                lp = m.get("load_pct")
                try:                        # 숫자가 아니면 화면이 통째로 죽는다(저장형 DoS)
                    lp_cell = "" if lp is None else f"{round(float(lp))}%"
                except (TypeError, ValueError):
                    lp_cell = esc(lp)
                per = m.get("period")
                per = "~".join(str(x) for x in per) if isinstance(per, list) else str(per or "")
                # 값은 업로드로 들어온 남의 입력이다 — 반드시 이스케이프(저장형 XSS 방지)
                rows.append(
                    f"<tr><td><b>{esc(m.get('owner'))}</b></td>"
                    f"<td>{esc(m.get('function'))}</td>"
                    f"<td>{esc(per)}</td>"
                    f"<td>{lp_cell}</td>"
                    f"<td>{esc(m.get('total_mm', ''))}</td>"
                    f"<td class='{cls}'>{esc(m.get('uploaded_at', ''))}</td></tr>")
            agg_html = os.path.join(TEAMDATA, "team_report.html")
            has_rep = os.path.exists(agg_html)
            ag_html = os.path.join(TEAMDATA, "team_agentic.html")
            full_html = os.path.join(TEAMDATA, REPORT_FILES["/full"])
            full_v3 = os.path.join(TEAMDATA, REPORT_FILES["/full_v3"])
            body = [PAGE_HEAD,
                    "<h1>LoadMonitor 팀 서버 <span class='note'>업로드 "
                    + str(STATE["uploads"]) + "건 · 취합 "
                    + (time.strftime("%m-%d %H:%M", time.localtime(STATE["last_agg"]))
                       if STATE["last_agg"] else "-") + "</span></h1>",
                    "<p>",
                    ("<a class='btn' href='/report'>팀 리포트 열기</a>" if has_rep else
                     "<span class='note'>팀 리포트는 첫 업로드 후 생성됩니다</span>"),
                    ("<a class='btn' href='/agentic'>Agentic 열지도</a>"
                     if os.path.exists(ag_html) else ""),
                    ("<a class='btn' href='/full'>팀 통합 보고서</a>"
                     if os.path.exists(full_html) else ""),
                    ("<a class='btn' href='/full_v3'>v3 (로드율 제외)</a>"
                     if os.path.exists(full_v3) else ""),
                    "<a class='btn' href='/refresh'>지금 다시 취합</a></p>",
                    "<h2>인별 업로드 현황 (" + str(len(ms)) + "명)</h2>",
                    "<table><tr><th>이름</th><th>Function</th><th>기간</th><th>로드율</th>"
                    "<th>투입 MM</th><th>업로드</th></tr>",
                    "".join(rows) or "<tr><td colspan=6 class='note'>아직 업로드가 없습니다 — "
                    "각자 UI 의 [팀 서버 업로드] 또는 분석 실행 시 자동 업로드</td></tr>",
                    "</table>",
                    "<p class='note'>이 페이지는 2분마다 자동 새로고침 · "
                    + esc(STATE["agg_note"]) + "</p>"]
            self._send(200, "\n".join(body), "text/html; charset=utf-8")
        elif self.path in REPORT_FILES:
            self._file(os.path.join(TEAMDATA, REPORT_FILES[self.path]))
        elif self.path == "/refresh":
            run_aggregate()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        elif self.path in ("/api/team", "/api/whoami"):
            # root/store 를 함께 알린다 — 대시보드가 '내 서버'와 '남의 서버'를 구분하는 근거
            fp = os.path.join(TEAMDATA, REPORT_FILES["/full"])
            try:
                full_at = (time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp)))
                           if os.path.exists(fp) else "")
            except OSError:
                full_at = ""
            self._send(200, {"ok": True, "members": members(),
                             "uploads": STATE["uploads"], "agg_note": STATE["agg_note"],
                             "root": ROOT, "store": TEAMDATA,
                             "pid": os.getpid(), "port": PORT[0], "token": TOKEN[0],
                             "full_report_at": full_at})
        else:
            self._send(404, {"error": "not found"})

    @staticmethod
    def _save(owner, member, files):
        r"""한 사람의 묶음을 원자적으로 바꿔 끼운다 — 반환 (bad, staged). 호출자는 owner 잠금을 쥔 채 부른다.

        부분 저장은 팀 취합을 조용히 망친다(파일은 옛것, member.json 만 새것) — 검증 확정.
        .part 로 먼저 쓰고 전부 성공했을 때만 한꺼번에 바꿔 끼운다. 임시 이름에는 pid·스레드·난수를
        붙여 다른 요청·다른 프로세스(teamup --to-folder)와 절대 겹치지 않게 한다.
        되돌리기 순서: 원본이 있던 파일은 .bak 를 제자리로(새 파일을 덮음), 원본이 없던 파일만 지운다 —
        예전 순서(먼저 지우고 나중에 복원)는 .bak 가 없으면 설치된 파일을 통째로 잃었다."""
        dst = os.path.join(TEAMDATA, owner)
        os.makedirs(dst, exist_ok=True)
        uniq = f"{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(3)}"
        staged, bad = [], []
        # member.json 도 같은 묶음으로 — 파일만 새것이고 member.json 만 옛것이면 취합이 섞인다
        items = list(files.items()) + [("member.json",
                                        json.dumps(member, ensure_ascii=False, indent=1))]
        for name, content in items:
            p2 = os.path.join(dst, name)
            tmp = f"{p2}.{uniq}.part"
            try:
                with open(tmp, "w", encoding="utf-8", newline="") as f:
                    f.write(content)
                staged.append((tmp, p2))
            except OSError as e:
                bad.append(f"{name}({type(e).__name__})")
        if not bad:
            done, baks, firstfail = [], [], ""
            for tmp, p2 in staged:
                try:
                    if os.path.isfile(p2):
                        # 파일일 때만 비켜 놓는다 — 같은 이름의 폴더가 있으면 그것은 비정상이므로
                        # 옮기지 말고 실패로 두어 사람이 보게 한다
                        bak = f"{p2}.{uniq}.bak"
                        os.replace(p2, bak)               # 예전 내용을 옆에 보관
                        baks.append((bak, p2))
                    os.replace(tmp, p2)
                    done.append(p2)
                except OSError as e:
                    firstfail = f"{os.path.basename(p2)}({type(e).__name__})"
                    break                             # 첫 실패에서 멈춘다 — 더 헤집지 않는다
            if firstfail:
                restored = set()
                for bak, p2 in baks:                  # 예전 파일을 제자리로(이번에 넣은 것을 덮는다)
                    try:
                        os.replace(bak, p2)
                        restored.add(p2)
                    except OSError:
                        pass
                for p2 in done:                       # 원본이 없던(새로 생긴) 파일만 걷어낸다
                    if p2 in restored:
                        continue
                    try:
                        os.remove(p2)
                    except OSError:
                        pass
                bad.append(firstfail)
            else:
                for bak, _p in baks:
                    try:
                        os.remove(bak)
                    except OSError:
                        pass
        if bad:
            for tmp, _ in staged:                # 내 임시 파일만 정리 — 반쪽 상태를 남기지 않는다
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        return bad, staged

    def do_POST(self):
        if self.path == "/api/shutdown":
            # 인증 없는 사내망 서버다 — 팀원 누구나 팀 수집기를 죽일 수 있으면 안 된다
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(403, {"ok": False, "error": "로컬에서만 가능합니다"})
                return
            self._send(200, {"ok": True, "stopping": True})
            self.close_connection = True
            if SRV[0] is not None:
                threading.Thread(target=SRV[0].shutdown, daemon=True).start()
            return
        if self.path != "/api/upload":
            self._send(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0 or n > MAX_BODY:
            # 본문을 소진하고 응답한다 — 읽지 않고 거절하면 클라이언트가 아직 보내는 중이라
            # 연결이 리셋돼(RST) 오류 응답조차 전달되지 않는다(시험 실측). 상한 64MB 까지만
            # 소진하고 그 밖은 연결을 닫는다(허위 Content-Length 방어).
            drain = min(max(n, 0), 64 * 1024 * 1024)
            try:
                while drain > 0:
                    chunk = self.rfile.read(min(1024 * 1024, drain))
                    if not chunk:
                        break
                    drain -= len(chunk)
            except OSError:
                pass
            self._send(413 if n > MAX_BODY else 400, {"ok": False, "error": "본문 크기 이상"})
            self.close_connection = True
            return
        try:
            b = json.loads(self.rfile.read(n))
        except (ValueError, OSError):
            self._send(400, {"ok": False, "error": "JSON 아님"})
            return
        # 본문이 객체가 아니면('[1,2,3]'·'"abc"'·'null') 예전엔 미처리 예외로 응답 없이 끊겼다 — 400 으로 답한다
        if not isinstance(b, dict):
            self._send(400, {"ok": False, "error": "JSON 객체 아님"})
            return
        member = b.get("member")
        if not isinstance(member, dict):
            self._send(400, {"ok": False, "error": "member 객체 아님"})
            return
        owner = norm_owner(member.get("owner"))
        why = owner_problem(owner)
        if why:
            self._send(400, {"ok": False, "error": why})
            return
        member = dict(member, owner=owner)   # 저장본의 owner 도 정규화 값 — 폴더명과 같은 이름
        files = b.get("files") or {}
        if not isinstance(files, dict) or not files:
            self._send(400, {"ok": False, "error": "files 없음"})
            return
        # fullmatch — '$' 는 끝 개행 앞에서도 맞아 'x.csv\n' 이 통과해 저장 단계에서 500 이 났다
        bad = [k for k in files if not NAME_OK.fullmatch(str(k))]
        if bad:
            self._send(400, {"ok": False, "error": f"허용되지 않는 파일명: {bad[:3]}"})
            return
        bad = [k for k, v in files.items() if not isinstance(v, str)]
        if bad:
            self._send(400, {"ok": False, "error": f"files 내용은 문자열이어야 합니다: {bad[:3]}"})
            return
        with LOCK:
            olock = OWNER_LOCKS.setdefault(owner, threading.Lock())
        with olock:
            bad, staged = self._save(owner, member, files)
        if bad:
            print(f"[team] 업로드 거부(저장 실패): {owner} — {bad[:3]}")
            self._send(500, {"ok": False, "error": f"저장 실패: {', '.join(bad[:3])} "
                                                   "(파일이 열려 있거나 권한이 없습니다)"})
            return
        saved = max(0, len(staged) - 1)          # member.json 은 파일 수에서 뺀다
        with LOCK:
            STATE["uploads"] += 1
        ok = run_aggregate()
        print(f"[team] 업로드: {owner} ({saved}개 파일) · 취합 {'OK' if ok else '실패'}")
        self._send(200, {"ok": True, "saved": saved, "aggregated": ok,
                         # 어디에 담겼는지 보내는 쪽이 알 수 있게 — '엉뚱한 폴더' 제보 대응
                         "store": TEAMDATA, "root": ROOT,
                         "host": os.environ.get("COMPUTERNAME", "")})


def main():
    port = int(arg("--port", "0") or 0) or _cfg_port()
    PORT[0] = port
    os.makedirs(TEAMDATA, exist_ok=True)
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    except OSError as e:
        # 예전에는 traceback 만 로그에 남아 화면이 '시작 실패' 라고만 말했다.
        # 10013(다른 프로그램이 잠깐 쓰는 중)·10048(이미 사용 중)은 조치가 서로 다르다.
        code = getattr(e, "winerror", 0) or e.errno or 0
        print(f"[team] 포트 {port} 을 열지 못했습니다 (WinError {code}) — {e}")
        if code == 10013:
            print("[team] 다른 프로그램이 그 번호를 잠깐 쓰고 있습니다. "
                  "잠시 뒤 다시 시도하거나 포트를 임시 포트 범위 밖(예: 19310)으로 바꾸세요.")
        elif code == 10048:
            print("[team] 이미 그 포트를 쓰는 서버가 있습니다. 대시보드의 [포트 가져오기] 를 쓰세요.")
        return 3
    SRV[0] = srv
    write_pid()
    write_token()
    print(f"[team] 팀 서버 가동 — http://<이 PC 의 IP>:{port}  (저장: {TEAMDATA})")
    print(f"[team] 이 서버의 설치 폴더: {ROOT}")
    print("[team] 팀원 설정: config.teamServerUrl 에 이 주소를 넣으면 대시보드 [팀 서버 업로드] 버튼으로 올립니다(자동 전송 없음)")
    print("[team] 종료: Ctrl+C (또는 대시보드의 [팀 서버 중지])")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("[team] 종료")
    finally:
        clear_pid()
        clear_token()
    return 0


if __name__ == "__main__":
    sys.exit(main())
