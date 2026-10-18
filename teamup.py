# -*- coding: utf-8 -*-
r"""
teamup.py — 분석 결과를 팀 저장소로 올린다 (LoadMonitor30: 묶음 '대기' → [분석 실행] 끝 자동 보고 → 실패면 버튼)

팀 서버는 특정 망에서만 닿는다. 분석은 아무 망에서나 하니 분석 끝에 보내면 실패가 잦고,
LM19 이전에는 그 실패가 조용히 묻혀 결과가 사라졌다(실측). 그래서 이렇게 나눈다:

  1) 분석이 끝나면  → 보낼 묶음을 report\upload_pending\ 에 **먼저** 만들어 둔다(어떤 실패에도 대기로 남는다)
  2) 이어서 run.py 가 --upload --json 으로 자동 보고한다(LM28 사용자 요청 · config.teamUpload.autoReport 기본 켬).
     결과는 report\team_report_status.json 에 남고, 실패하면 화면이 알림 1번 + 배너로 말한다(조용히 묻지 않는다)
  3) 서버에 닿는 망에서 → 대시보드 [팀 서버 업로드] 버튼(또는 이 스크립트)으로 밀린 것까지 한 번에 보낸다
     밀린 기간이 여러 개면 전부 함께 올라가고, 보낸 묶음은 report\upload_sent\ 로 옮긴다

  python teamup.py --build --from 2026-05-19 --to 2026-08-17   묶음 준비(전송 안 함)
  python teamup.py --list                                      대기 목록
  python teamup.py --ping [--host <IP>] [--port <번호>]         이 망에서 닿는지 확인(빠름)
  python teamup.py --upload [--host <IP>] [--port <번호>]       대기분 전부 전송
      (주소는 팀 서버 주소 설정 config\team_server.json — core\teamaddr.py 가 읽는다.
       --host·--port·--url 은 이번 한 번만 쓰는 값이고 설정은 바꾸지 않는다 —
       설정을 바꾸는 곳은 LoadMonitor30-팀서버주소.bat 하나)
  python teamup.py --to-folder "\\서버\공유\LoadMonitor"          공유폴더로 대신 저장
      (개인 HTML 보고서 분석리포트_<기간>.html·보고서_<기간>.html 이 있으면
       <폴더>\개인리포트\<이름>_<파일명> 으로 함께 복사 — 팀 서버 묶음에는 넣지 않는다)
  (--json 을 붙이면 마지막 줄에 결과 JSON 한 줄 — 대시보드·run.py 자동 보고가 이걸 읽는다.
   --upload 는 묶음마다 results[].kind = sent·blocked·rejected·unreachable·slow, 주소가 없으면 no_url, 남은 대기 수 pending,
   보내지 않고 남긴 묶음 수 left 와 그 사유 stopped. LM30 시험판 보호에 걸리면 kind·no_test_server — 보내지 않음이지 실패가
   아니다: ok null · 종료 코드 0 · 사유 note)

기다림 상한(LM28 — "시도 1-2번 해서 안 되면 아닌 값… 업로드에서 기다리는 건 너무 로스"):
  연결 확인 3초 × 최대 2번(사이 2초) · 업로드 연결 3초(끊기면 1번만 다시) · 본문을 다 보낸 뒤 답 45초.
  답이 늦으면 다시 보내지 않고(서버가 이미 저장했을 수 있다) 남은 묶음도 멈춘다 — 자동 보고 전체가 1분 남짓이면 끝난다.
  config.teamUpload 의 pingTries·pingTimeoutSec·timeoutSec 로 바꾼다(wait_limits 가 범위 안으로 접는다).

LM30 시험판 보호(사용자 결정 — "LM30 결과는 LoadMonitor30-팀서버주소.bat 으로 정한 시험용 팀 서버로"):
  기본 주소(core\teamaddr.py)는 기존 팀 서버다. 거기로 보내면 서버가 TEAMDATA\<이름>\* 를 갈아 끼워 그 사람의 LM28·LM29
  결과가 LM30 시험 결과로 덮인다. 그래서 config.teamUpload.requireSavedAddress(배포 설정 true · 키가 없어도 켬)가 켜져 있으면
  시험용 서버 주소를 config\team_server.json 에 저장하기 전에는 --upload(자동 보고·[팀 서버 업로드]·팀업로드.bat)가 보내지
  않는다(upload_guard — 묶음은 대기 그대로). 기본 주소는 바꾸지 않는다. 연결 확인·묶음 만들기·공유폴더 저장은 그대로 된다.

묶음 내용은 팀 공유폴더 내보내기(export.py)와 동일하다 — 이미 excludePathKeywords 로 걸러진
판정 결과다. 사내망 전용.
LM28: signals 는 G4 팀 반출 변환(core\privacy.team_export_rows — export.py 와 같은 함수)을 거친다 — who 는
사내|고객사|협력사|외부 로 접고, text 는 다시 정제하고, 고위험 잔여 행과 flag 열은 빼고, 이 PC·본인 식별자(카나리아)가
남은 파일은 보내지 않는다. 묶음을 만들 때(build)와 보내기 직전(upload_one) 두 번 건다(다시 걸어도 같은 결과).
member 에는 판 표식 lm_ver(LM_VER — 'LM30')을 추가 키로 싣는다(기존 키·파일명·measure·coverage·cfg_used 는 그대로).
"""
import http.client
import io
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(ROOT, "report")
PENDING = os.path.join(REPORT, "upload_pending")
SENT = os.path.join(REPORT, "upload_sent")
# 마지막 팀 서버 보고 결과(LM28) — run.py 자동 보고가 성공·실패를, 여기 --upload·--to-folder 가 '다 보냄' 을 쓴다.
# 대시보드는 이 파일로 실패 배너(다음 성공까지)와 실행 1회당 알림 1번을 정한다(at 이 그 열쇠)
REPORT_STATUS = "team_report_status.json"
MAX_BYTES = 30 * 1024 * 1024        # 서버 상한과 같다 — 넘으면 보내기 전에 알려 준다
LM_VER = "LM30"                     # member.lm_ver — 묶음을 만든 판(추가 키만, 기존 키·파일명 불변)
# 팀 서버 기다림 기본값(LM28) — 예전에는 연결 확인 4초 1번, 묶음마다 응답 360초, 실패해도 남은 묶음을 전부 시도해
# 서버가 느린 날 자동 보고가 몇 분씩 붙잡혔다(사용자 지적). config.teamUpload 로 바꾸되 범위(_WAIT_RANGE)를 넘지 못한다 —
# 가장 길게 잡아도 run.py 의 teamup 상한(TR_CAP_SEC 150초) 안에 끝나야 결과 JSON 이 남는다.
PING_TRIES = 2                      # 연결 확인 시도 수 — 순간 끊김 한 번으로 '닿지 않음' 이라 단정하지 않을 만큼만
PING_TIMEOUT = 3.0                  # 연결 확인 1번(초) — 업로드의 '연결' 단계도 이 값으로 끊는다
UP_TIMEOUT = 45.0                   # 본문을 다 보낸 뒤 서버 답을 기다리는 상한(초)
RETRY_PAUSE = 2.0                   # 다시 시도하기 전 쉼(초)
BUDGET_SEC = 75.0                   # 이 실행에서 다음 묶음을 시작해도 되는 시간 상한(초) — 넘기면 남은 묶음은 대기로 둔다
STOP_KINDS = ("unreachable", "slow")  # 이 갈래로 실패하면 남은 묶음은 보내지 않는다(같은 서버라 같은 결과를 또 기다린다)
_WAIT_RANGE = {"pingTries": (1, 3), "pingTimeoutSec": (1.0, 10.0), "timeoutSec": (5.0, 90.0)}
SLOW_MSG = ("서버 응답 지연 — 서버에 저장됐을 수 있습니다. 묶음은 대기로 남겨 다음 실행 때 다시 보냅니다"
            "(덮어쓰기라 결과는 같습니다)")
# LM30 시험판 보호(upload_guard) — 시험용 팀 서버 주소를 정하기 전에는 기본 주소(기존 팀 서버)로 보내지 않는다. 실패가 아니라
# '보내지 않음' 이다: --upload 는 kind no_test_server(ok null · 종료 코드 0)로 답하고 묶음은 대기 그대로 — run.py 자동 보고는
# 알림·배너 없이 '건너뜀' 으로 남기고, 화면 버튼은 실패 대신 까닭을 말한다
NO_TEST_KIND = "no_test_server"
NO_TEST_MSG = ("LM30 시험판은 시험용 팀 서버 주소를 LoadMonitor30-팀서버주소.bat 으로 정한 뒤에만 보냅니다 — "
               "기존 팀 서버의 LM28·LM29 결과를 덮지 않게. 결과 묶음은 대기로 남습니다")
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8


FLAGS = {"--build", "--build-all", "--build-latest", "--scan", "--list", "--ping",
         "--upload", "--to-folder", "--drop", "--json", "--url", "--host", "--port", "--from", "--to"}


def arg(flag, d=""):
    """플래그의 값. 값이 없거나(마지막) 다음 토큰이 또 다른 플래그면 기본값 —
    '--to-folder --json' 이 '--json' 이라는 폴더를 만들어 묶음을 흘리던 실측 결함 방어."""
    if flag in sys.argv:
        i = sys.argv.index(flag) + 1
        if i < len(sys.argv) and sys.argv[i] not in FLAGS and not sys.argv[i].startswith("--"):
            return sys.argv[i]
    return d


sys.path.insert(0, os.path.join(ROOT, "core"))
try:
    from owner import safe_owner  # noqa: E402
except ImportError:                 # teamup.py 만 떼어 온 최소 환경에서도 돌아야 한다
    def safe_owner(v):
        """core\\owner.py 와 같은 규칙(그 파일이 없을 때만 쓰인다 — 규칙이 갈리면 인원이 두 폴더로 나뉜다)"""
        s = re.sub(r'[\\/:*?"<>|.]', '_', str(v or '').strip())
        s = re.sub(r'\s+', ' ', s).strip()[:40].strip()
        return s or '이름미상'

# 서버(teamserver.py NAME_OK)와 같은 파일명 규칙 — 보내기 전에 이쪽에서 먼저 걸러 낸다
NAME_OK = re.compile(r"^(mm_rows_\d{8}-\d{8}(_refined)?\.csv|signals_\d{8}-\d{8}\.csv|"
                     r"(mm_meta|pivots|ai_narratives|entities|agentic|workflow)_\d{8}-\d{8}\.json)$")


def blockers(member, files):
    """이 묶음이 '보낼 수 없는' 이유 목록 — 준비할 때와 보낼 때 같은 규칙으로 본다.
    준비 단계에서 미리 알려 주지 않으면, 며칠 뒤 서버망에서야 실패를 알게 된다(검증 확정)."""
    out = []
    n = len(json.dumps({"member": member, "files": files}, ensure_ascii=False).encode("utf-8"))
    if n > MAX_BYTES:
        out.append(f"묶음이 서버 상한을 넘습니다 ({n / 1048576:.1f}MB > 30MB) — 기간을 나눠 분석하세요")
    ow = str((member or {}).get("owner") or "")
    if not ow or ow != safe_owner(ow) or len(ow) > 40:
        out.append(f"이름이 서버 규칙에 맞지 않습니다: '{ow}' — config.owner 를 고치세요(경로문자·점 불가)")
    bad = [k for k in (files or {}) if not NAME_OK.match(str(k))]
    if bad:
        out.append(f"서버가 받지 않는 파일명: {bad[:3]}")
    return out


def load_cfg():
    try:
        return json.load(open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def wait_limits(cfg=None):
    r"""팀 서버 기다림 값 → {ping_tries, ping_timeout, timeout} — config.teamUpload 의 pingTries·pingTimeoutSec·timeoutSec.
    없거나 형식이 틀리면 기본값, 범위(_WAIT_RANGE) 밖이면 가장자리로 접는다. 큰 값을 적어도 자동 보고가 몇 분씩 붙잡히지
    않게 — 가장 길게 잡아도 연결 확인 34초 + 묶음 하나(연결 22초 또는 답 90초)라 run.py 상한 150초 안에 끝난다."""
    tu = (cfg if isinstance(cfg, dict) else {}).get("teamUpload")
    tu = tu if isinstance(tu, dict) else {}

    def pick(key, dflt):
        lo, hi = _WAIT_RANGE[key]
        v = tu.get(key)
        try:
            v = dflt if v is None or isinstance(v, bool) or v == "" else float(v)
        except (TypeError, ValueError):
            v = dflt
        return min(hi, max(lo, v if math.isfinite(v) else dflt))
    return {"ping_tries": int(pick("pingTries", PING_TRIES)), "ping_timeout": pick("pingTimeoutSec", PING_TIMEOUT),
            "timeout": pick("timeoutSec", UP_TIMEOUT)}


def target_url(cfg, override=""):
    r"""보낼 주소 — 우선순위: 함수 인자 > --url > --host/--port > 팀 서버 주소 설정(teamaddr).
    v5: 설정은 core\teamaddr.py 한 곳에서만 읽는다(예전처럼 config.teamServerUrl 을 직접 읽지 않는다).
    형식이 틀린 일회성 값은 빈 문자열로 돌려 '주소 없음' 으로 멈추게 한다 — 엉뚱한 곳으로 보내지 않게."""
    import teamaddr
    one = (override or arg("--url") or "").strip().rstrip("/")
    if one:
        pu = teamaddr.parse_url(one)
        if pu is None:
            return ""
        return f"http://{pu[0]}:{pu[1] or teamaddr.load(ROOT).port}"
    h, p = arg("--host"), arg("--port")
    if h or p:
        a = teamaddr.load(ROOT)
        hh, pp, err = teamaddr.split_input(h or a.host, p or None)
        if err:
            return ""
        return f"http://{hh}:{pp or a.port}"
    return teamaddr.load(ROOT).url


# 윈도우 경로 길이(260자) — 공유폴더가 깊으면 <공유폴더>\<이름>\<파일> 이 이를 넘겨 저장이 실패한다
# (실측: FileNotFoundError 로 나와 원인이 안 보인다). 필요한 때만 확장 경로(\\?\)로 연다.
MAXP = 240


def longp(p):
    """길면 확장 경로로 — 짧으면 그대로(평소 동작을 바꾸지 않는다)"""
    p = os.path.abspath(p)
    if os.name != "nt" or len(p) < MAXP or p.startswith("\\\\?\\"):
        return p
    return ("\\\\?\\UNC" + p[1:]) if p.startswith("\\\\") else ("\\\\?\\" + p)


# ── 묶음 만들기 ──────────────────────────────────────────────────────────────
FILE_NAMES = ("mm_rows_{t}.csv", "mm_rows_{t}_refined.csv", "signals_{t}.csv",
              "mm_meta_{t}.json", "pivots_{t}.json", "ai_narratives_{t}.json",
              "entities_{t}.json", "agentic_{t}.json", "workflow_{t}.json")
# agentic_{t}.json — LM29부터 Agentic AI 니즈 후보만 싣는다(kind "needs" · 과제 매칭·오할당 없음). 팀 취합이 인원별 후보를 모은다.
# freeze.py 가 만드는 개인 HTML 보고서 — 묶음(files)·팀 서버에는 넣지 않는다(서버 NAME_OK 불변:
# 업로드 HTML = 서버 origin 의 임의 스크립트, 얼린 보고서는 메일·회의 제목 원문 포함).
# 공유폴더 저장(--to-folder) 때만 <공유폴더>\개인리포트\<이름>_<파일명> 으로 복사한다 —
# 팀 취합(팀보완툴·LM22 팀 취합)이 그 자리의 데이터 섬(lm-report-data / lm-frozen-data)을 읽는다.
# 고정명은 언제나 원문 포함(full) 본이다 — freeze --summary 의 요약본은 *_<기간>_요약.html 로 따로 쓰이고
# 여기 목록에 없으므로 공유폴더에 나가지 않는다(요약/원문이 구분 없이 섞여 나가던 결함 방어).
REPORT_HTML = ("분석리포트_{t}.html", "보고서_{t}.html")
REPORT_HTML_DIR = "개인리포트"


def _count(v):
    """mm_basis 의 목록(anomalies·long_days)은 길이, 숫자는 정수 — 없거나 형식이 다르면 0.
    팀 취합(aggregate/team_report)이 member.json 에서 정수로 읽는다(형식 오류 하나가 취합을 죽이지 않게)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (list, tuple, dict)):
        return len(v)
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0
    return int(n) if math.isfinite(n) else 0


def _hours(v):
    """시간(h) 실수 — 없거나 형식이 다르면 0.0"""
    if isinstance(v, bool):
        return 0.0
    try:
        n = float(v)
    except (TypeError, ValueError):
        return 0.0
    return round(n, 2) if math.isfinite(n) else 0.0


def _obj(v):
    """dict 만 통과 — mm_meta 의 measure/coverage/cfg_used 는 객체여야 한다(아니면 None)"""
    return v if isinstance(v, dict) and v else None


def measure_of(mj, b):
    """측정 방식 요약(D5) — mine 이 mm_meta 최상위/mm_basis 에 실은 measure 를 우선, 없으면(구판 core)
    mm_basis 의 일수 키로 조립한다. 팀 취합은 '샘플러 N일/PC 하한 N일/흔적폭 N일/출장 N일/수동 N일' 을 보여 준다."""
    ms = _obj(mj.get("measure")) or _obj(b.get("measure"))
    if ms is None:
        if not b:
            return None
        ms = {"method": b.get("method"),
              "sampler_days": b.get("sampler_days"), "pc_floor_days": b.get("pc_floor_days"),
              "floor_blocked_passive_days": b.get("floor_blocked_passive_days"),
              "trace_window_days": b.get("trace_window_days"),
              "pc_record_missing_days": b.get("pc_record_missing_days"),
              "offsite_days": b.get("offsite_days"), "manual_days": b.get("manual_days")}
    out = {"method": str(ms.get("method") or b.get("method") or "")[:20]}
    for k in ("sampler_days", "pc_floor_days", "floor_blocked_passive_days", "pc_record_days",
              "trace_window_days", "pc_record_missing_days", "offsite_days", "manual_days"):
        if k in ms and ms.get(k) is not None:
            out[k] = _count(ms.get(k))
    return out


def coverage_of(mj, b):
    """측정 신뢰도 등급 — {grade: reliable|caution|unreliable, reasons:[…]} / 없으면 None(구판 core)"""
    cv = _obj(mj.get("coverage")) or _obj(b.get("coverage"))
    if cv is None:
        return None
    g = str(cv.get("grade") or "").strip().lower()
    reasons = cv.get("reasons") if isinstance(cv.get("reasons"), list) else \
        (cv.get("missing") if isinstance(cv.get("missing"), list) else [])
    out = {"grade": g if g in ("reliable", "caution", "unreliable") else "",
           "reasons": [str(x)[:60] for x in reasons][:6]}
    r = cv.get("pc_weekday_ratio")
    if isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r):
        out["pc_weekday_ratio"] = round(float(r), 2)
    return out


def cfg_used_of(mj, b):
    """산식 설정 스냅샷 — 팀 취합이 '팀 다수와 다름' 배지를 붙이는 재료. 값은 스칼라/문자열 목록만."""
    cu = _obj(mj.get("cfg_used")) or _obj(b.get("cfg_used"))
    if cu is None:
        return None
    out = {}
    for k in ("standardDayHours", "usePcFloor", "pcFloorNeeds", "dayWindow", "lunch", "dinner",
              "tentativeMeetings", "holidays_n", "offsiteAsWork", "samplerGapBridgeMin"):
        if k not in cu:
            continue
        v = cu.get(k)
        if isinstance(v, (list, tuple)):
            out[k] = [str(x) for x in v][:4]
        elif isinstance(v, (bool, int, float, str)) or v is None:
            out[k] = v
    return out


def tool_usage_of(mj, b):
    """프로그램 사용 이력 요약 — 팀 취합에 올릴 만큼만 줄인다(상위 12개·합계).

    ★ 참고 지표다. 로드율·MM 과 무관하므로 팀 리포트에서도 '얼마나 일했나' 로 읽히지 않게
      '프로그램 사용' 절에만 쓴다. 창 제목은 애초에 집계에 들어가지 않아 과제명·사람 이름이 없다."""
    tu = _obj(mj.get("tool_usage")) or _obj(b.get("tool_usage"))
    if tu is None:
        return None
    out = {}
    for k in ("samples", "days"):
        if tu.get(k) is not None:
            out[k] = _count(tu.get(k))
    for k in ("total_h", "known_h", "unknown_h", "sim_h", "cad_h", "solver_bg_h"):
        if tu.get(k) is not None:
            out[k] = _hours(tu.get(k))
    progs = tu.get("programs") if isinstance(tu.get("programs"), list) else []

    def _opt(x, f):           # 증가분을 모르는 칸(None — 실행 기록 스냅샷 1장)은 None 그대로: 0 이면 '안 썼다' 로 읽힌다
        return None if x is None else f(x)
    out["programs"] = []
    for p in [p for p in progs if isinstance(p, dict)][:12]:
        row = {"name": str(p.get("name") or "")[:40], "kind": str(p.get("kind") or "")[:6],
               "cat": str(p.get("cat") or "")[:10], "hours": _hours(p.get("hours")),
               "bg_hours": _hours(p.get("bg_hours")), "days": _count(p.get("days"))}
        if isinstance(p.get("src"), list):
            # LM28 — 출처(창기록·실행기록·파일)·실행 횟수·포커스 시간·마지막 실행·파일 일수(숫자·날짜만 — 경로·파일 이름 없음)
            row.update(src=[str(s)[:6] for s in p["src"]][:3], runs=_opt(p.get("runs"), _count),
                       runs_cum=_opt(p.get("runs_cum"), _count), taskbar=_opt(p.get("taskbar"), _count),
                       focus_h=_opt(p.get("focus_h"), _hours), focus_h_cum=_opt(p.get("focus_h_cum"), _hours),
                       last_run=str(p.get("last_run") or "")[:16], file_days=_count(p.get("file_days")),
                       files=_count(p.get("files")))
        out["programs"].append(row)
    for k in ("by_cat", "by_kind"):
        v = tu.get(k)
        if isinstance(v, list):
            out[k] = [[str(x[0])[:12], _hours(x[1])] for x in v
                      if isinstance(x, (list, tuple)) and len(x) >= 2][:8]
    for k in ("by_kind_n", "by_cat_n"):          # 프로그램 수 — '자체·프로토타입(추정)' 이 잘리지 않게 14자
        v = tu.get(k)
        if isinstance(v, list):
            out[k] = [[str(x[0])[:14], _count(x[1])] for x in v if isinstance(x, (list, tuple)) and len(x) >= 2][:8]
    # 자체·프로토타입(추정) — 이름은 core 가 G3 관문(privacy.gate_items)을 거친 것만 mm_meta 에 실었다. 상위 12개·숫자만 더한다
    if isinstance(tu.get("inhouse"), list):
        out["inhouse"] = [{"name": str(x.get("name") or "")[:40], "cls": str(x.get("cls") or "")[:12],
                           "runs": _opt(x.get("runs"), _count), "runs_cum": _opt(x.get("runs_cum"), _count),
                           "focus_h": _opt(x.get("focus_h"), _hours), "last_run": str(x.get("last_run") or "")[:16]}
                          for x in tu["inhouse"] if isinstance(x, dict) and x.get("name")][:12]
        out["inhouse_n"] = _count(tu.get("inhouse_n"))
        out["inhouse_hidden"] = _count(tu.get("inhouse_hidden"))
    src = tu.get("sources")
    if isinstance(src, dict):                    # 원천 요약 — 스칼라만(이유 글·스냅샷 날짜·건수)
        out["sources"] = {str(sk)[:8]: {str(kk)[:16]: (vv[:200] if isinstance(vv, str) else
                                                       [str(y)[:10] for y in vv][:2] if isinstance(vv, list) else vv)
                                        for kk, vv in list(sv.items())[:16]
                                        if vv is None or isinstance(vv, (bool, int, float, str, list))}
                          for sk, sv in list(src.items())[:4] if isinstance(sv, dict)}
    if isinstance(tu.get("note"), str):
        out["note"] = tu["note"][:200]
    return out


def push_reports(share, owner, tag):
    r"""report\ 의 개인 HTML 보고서를 <share>\개인리포트\<owner>_<파일명> 으로 복사 → (복사한 이름들, 실패)
    없는 파일은 조용히 건너뛴다(보고서 생성 단계가 실패했어도 묶음 저장은 그대로 유효하다)."""
    copied, bad = [], []
    srcs = [(n, os.path.join(REPORT, n)) for n in (p.format(t=tag) for p in REPORT_HTML)
            if os.path.exists(os.path.join(REPORT, n))]
    if not srcs:
        return copied, bad
    who = safe_owner(owner)
    ddir = os.path.join(share, REPORT_HTML_DIR)
    try:
        if not os.path.isdir(longp(ddir)):
            os.mkdir(longp(ddir))            # 공유폴더 바로 아래 한 단계만(확장 경로 makedirs 함정)
    except FileExistsError:
        pass
    except OSError as e:
        return copied, [f"{REPORT_HTML_DIR}({type(e).__name__})"]
    for name, src in srcs:
        dst = os.path.join(ddir, f"{who}_{name}")
        tmp = dst + ".part"
        try:
            shutil.copyfile(longp(src), longp(tmp))
            os.replace(longp(tmp), longp(dst))   # 읽다 만 반쪽 HTML 을 취합이 보지 않게
            copied.append(os.path.basename(dst))
        except OSError as e:
            bad.append(f"{name}({type(e).__name__})")
            try:
                os.remove(longp(tmp))
            except OSError:
                pass
    return copied, bad


ATT_TEAM_KEYS = ("work_h", "ext_h", "night_h", "holiday_h", "offpc_h", "over52_weeks", "leave_work_days")


def attendance_of(mj, b):
    r"""LM30(2026-10-18) 출퇴근 추정 합계(mm_basis.attendance) → 팀에 올리는 달·전체 합계
    {"used_for_mm": 투입 MM 에 썼나, "months": {"YYYY-MM": {work_h, ext_h, night_h, holiday_h, offpc_h, over52_weeks,
    leave_work_days}}, "total": {같은 칸}}. 날짜별 출근·퇴근·평소 시각은 애초에 mm_meta 에 없다(이 PC 의 report\attendance_<기간>.json
    에만) — 여기서도 숫자 칸만 옮긴다. 출퇴근 추정이 없는 판(LM29 이전)이면 None."""
    a = _obj(b.get("attendance")) or _obj(mj.get("attendance"))
    if a is None:
        return None

    def row(x):
        x = x if isinstance(x, dict) else {}
        return {k: (_count(x.get(k)) if k in ("over52_weeks", "leave_work_days") else _hours(x.get(k)))
                for k in ATT_TEAM_KEYS}
    ms = a.get("months") if isinstance(a.get("months"), dict) else {}
    return {"used_for_mm": bool(a.get("used_for_mm")),
            "months": {str(k): row(v) for k, v in sorted(ms.items()) if re.match(r"^\d{4}-\d{2}$", str(k))},
            "total": row(a.get("total"))}


def _team_meta(text):
    r"""mm_meta 본문에서 이 PC 전용 칸을 뺀다(LM30 — 날짜별 출퇴근·평소 시각·LM29 근거의 저녁·새벽 창 시각:
    core\attendance.scrub_meta). 쓰는 쪽(mine·judge 재산정)이 이미 떼어 내므로 보통 그대로 돌려준다 — 옛 사본이나 다른 경로로 남은
    것을 팀 서버·공유폴더로 나가기 직전에 한 번 더 막는 자리다. 못 읽으면(형식 오류·core 없음) 그대로."""
    try:
        import attendance
        mj = json.loads(text)
        if isinstance(mj, dict) and attendance.scrub_meta(mj):
            return json.dumps(mj, ensure_ascii=False, indent=1)
    except (ImportError, ValueError, TypeError):
        pass
    return text


def team_signals(name, text, cfg):
    r"""G4 팀 반출 변환(core\privacy.team_export_rows — export.py 공유폴더와 같은 함수, WP7) → (본문 또는 None, 안내).
    who → 사내|고객사|협력사|외부, text 재정제, 고위험 잔여 행만 빼고 flag 열 제거. 이미 변환한 본문에 다시 걸어도 같다.
    None = 이 PC·본인 식별자(카나리아)가 남아 그 파일만 보내지 않는다. 신호 파일이 아니면 그대로 돌려준다.
    LM30(2026-10-18): mm_meta_<기간>.json 은 이 PC 전용 칸(날짜별 출퇴근 시각)을 한 번 더 뺀다(_team_meta) — 묶음 만들기·
    보내기 직전·공유폴더 저장이 모두 이 함수를 지난다."""
    if re.match(r"^mm_meta_\d{8}-\d{8}\.json$", str(name)):
        return _team_meta(text), ""
    if not re.match(r"^signals_\d{8}-\d{8}\.csv$", str(name)):
        return text, ""
    import privacy
    out, inf = privacy.team_export_csv(text, cfg=cfg, data_dir=os.path.join(ROOT, "data"))
    if out is None:
        return None, f"{name} 은 보내지 않습니다 — {inf.get('why') or '변환 실패'}"
    note = f"{name}: 개인정보가 남은 신호 {inf['high_dropped']}행은 빼고 보냅니다" if inf.get("high_dropped") else ""
    return out, note


def build(cfg, d0, d1):
    """report 의 산출물로 업로드 묶음(서버 전송 본문 그대로)을 만든다 → 경로 또는 None.
    같은 기간을 다시 분석하면 그 기간 대기 묶음을 갈아끼운다(같은 것이 쌓이지 않게).
    signals 는 팀 반출 변환(team_signals)을 거친 본문을 싣는다 — 서버·공유폴더 어느 쪽으로 가도 같은 행."""
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    files = {}
    for pat in FILE_NAMES:
        n = pat.format(t=tag)
        p = os.path.join(REPORT, n)
        if os.path.exists(p):
            try:
                files[n] = open(p, encoding="utf-8-sig", errors="replace").read()
            except OSError:
                pass
            if n in files:
                txt, note = team_signals(n, files[n], cfg)
                if note:
                    print(f"[teamup] {note}")
                if txt is None:
                    del files[n]
                else:
                    files[n] = txt
    if not files:
        return None
    meta_p = os.path.join(REPORT, f"mm_meta_{tag}.json")
    try:
        mj = json.load(open(meta_p, encoding="utf-8-sig")) if os.path.exists(meta_p) else {}
    except (OSError, ValueError):
        mj = {}
    b = mj.get("mm_basis") or {}
    member = {"owner": safe_owner(cfg.get("owner") or os.environ.get("USERNAME", "")),
              "function": cfg.get("function", ""), "period": [d0, d1], "tag": tag,
              "total_mm": mj.get("total_mm"), "avail_mm": mj.get("avail_mm"),
              "load_pct": mj.get("load_pct"), "worked_h": mj.get("worked_h"),
              "signals": mj.get("signals"),
              "absence_days": b.get("absence_days"), "overtime_h": b.get("overtime_h"),
              "no_evidence_days": b.get("no_evidence_days"), "gap_days": b.get("gap_days"),
              # 측정 품질 표시(LM22 mm_basis) — 팀 취합·팀 통합 보고서가 '상한 없는 야근' 의 이상치·장시간일·
              # 부재 추정·점심 차감을 인별로 보여 준다. 목록은 일수(len)로, 없으면 0.
              "anomaly_days": _count(b.get("anomalies")),
              "long_days": _count(b.get("long_days")),
              "inferred_absence_days": _count(b.get("inferred_absence_days")),
              "lunch_deducted_h": _hours(b.get("lunch_deducted_h")),
              # D5 — 측정 방식·신뢰도·산식 설정 스냅샷: 수집 환경 차이(샘플러 유무·PC 기록 결측·설정)를 팀 취합이
              # 사람 차이로 읽지 않게. 구판 core 가 만든 meta 면 None(취합은 배지 없이 예전처럼 비교).
              "measure": measure_of(mj, b), "coverage": coverage_of(mj, b), "cfg_used": cfg_used_of(mj, b),
              "tool_usage": tool_usage_of(mj, b),
              # LM30(2026-10-18) — 출퇴근 추정의 달·전체 합계(시각 없음). overtime_h 는 위 mm_basis 값 그대로 — 출퇴근 추정이
              # 투입을 맡으면(useForMM) 연장 + 휴일이다. 없는 판(LM29 이전)이면 None
              "attendance": attendance_of(mj, b),
              # A30 — 비업무 제외 후 시간 재산정 여부·뺀 시간(h)
              "rehours": bool(mj.get("rehours")), "dropped_h": _hours(mj.get("dropped_h")),
              "host": os.environ.get("COMPUTERNAME", ""),
              # 누가·언제·어디서 — 팀장이 "이 숫자는 누구 것이고 언제 것인가"를 묻는다(사용자 요청)
              "analyzed_at": time.strftime("%Y-%m-%d %H:%M"),
              # 판 표식(LM28 부터) — 추가 키라 LM24 서버·취합은 그대로 받는다(team_recalc 가 'LM30(v3)' 로 표시).
              # measure·coverage·cfg_used 키는 바꾸지 않는다(팀 호환 불변 — 없으면 'LM20(추정)' 으로 오분류된다)
              "lm_ver": LM_VER}
    os.makedirs(PENDING, exist_ok=True)
    dst = os.path.join(PENDING, f"{tag}.json")
    tmp = dst + ".tmp"
    payload = {"member": member, "files": files,
               "built": time.strftime("%Y-%m-%d %H:%M"),
               "blocked": blockers(member, files)}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, dst)                    # 쓰다 만 묶음이 남지 않게
    return dst


def _info(p):
    """대기 묶음 한 개의 요약 (본문 전체를 읽지 않고 필요한 것만)"""
    try:
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"file": os.path.basename(p), "bad": True,
                "bytes": os.path.getsize(p) if os.path.exists(p) else 0}
    m = d.get("member") or {}
    return {"file": os.path.basename(p), "tag": m.get("tag", ""),
            "owner": m.get("owner", ""), "period": m.get("period") or [],
            "built": d.get("built", ""), "files": len(d.get("files") or {}),
            "bytes": os.path.getsize(p), "total_mm": m.get("total_mm"),
            "load_pct": m.get("load_pct"), "blocked": d.get("blocked") or []}


def report_tags():
    r"""report\ 에 산출물이 있는 기간 목록(최신순) — 묶음이 없어도 '보낼 수 있는 것'을 찾는다.
    묶음은 분석하는 순간에만 만들어지므로, 예전 버전으로 분석한 PC 는 결과만 있고 묶음이 없다."""
    seen = {}
    try:
        for n in os.listdir(REPORT):
            m = re.match(r"^mm_rows_(\d{8})-(\d{8})(_refined)?\.csv$", n)
            if not m:
                continue
            tag = f"{m.group(1)}-{m.group(2)}"
            try:
                t = os.path.getmtime(os.path.join(REPORT, n))
            except OSError:
                t = 0
            seen[tag] = max(seen.get(tag, 0), t)
    except OSError:
        return []
    out = []
    for tag, t in sorted(seen.items(), key=lambda kv: -kv[1]):
        a, b = tag.split("-")
        out.append({"tag": tag,
                    "period": [f"{a[:4]}-{a[4:6]}-{a[6:8]}", f"{b[:4]}-{b[4:6]}-{b[6:8]}"],
                    "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""})
    return out


def buildable():
    """아직 대기 묶음이 없는 기간 (이미 보낸 것도 다시 묶을 수 있게 보여 준다)"""
    have = {x.get("tag") for x in list_pending()}
    return [t for t in report_tags() if t["tag"] not in have]


def list_pending():
    if not os.path.isdir(PENDING):
        return []
    out = [_info(os.path.join(PENDING, n)) for n in sorted(os.listdir(PENDING))
           if n.endswith(".json")]
    return out


def list_sent(limit=10):
    if not os.path.isdir(SENT):
        return []
    ns = sorted((n for n in os.listdir(SENT) if n.endswith(".json")), reverse=True)[:limit]
    out = []
    for n in ns:
        p = os.path.join(SENT, n)
        try:
            out.append({"file": n, "when": time.strftime("%Y-%m-%d %H:%M",
                                                         time.localtime(os.path.getmtime(p))),
                        "bytes": os.path.getsize(p)})
        except OSError:
            pass
    return out


# ── 서버 ────────────────────────────────────────────────────────────────────
def ping(url, timeout=None, tries=None):
    """이 망에서 서버에 닿는가 — 짧게 확인한다(응답이 오면 도달로 본다).
    LM28: 3초 × 최대 2번(사이 2초 — config.teamUpload.pingTimeoutSec·pingTries). 순간 끊김 한 번으로 '닿지 않음' 이라
    단정하지 않되, 닿지 않는 망에서는 8초 안에 끝낸다(예전 4초 1번). tries 는 결과에 몇 번 만에 닿았는지 남긴다."""
    if not url:
        return {"ok": False, "error": "팀 서버 주소가 비었거나 형식이 틀렸습니다 — "
                                      "LoadMonitor30-팀서버주소.bat 에서 서버 IP·포트를 저장하세요"}
    if timeout is None or tries is None:
        lim = wait_limits(load_cfg())
        timeout = lim["ping_timeout"] if timeout is None else timeout
        tries = lim["ping_tries"] if tries is None else tries
    tries = max(1, int(tries))
    t0 = time.time()
    err, n = None, 0
    while n < tries:
        if n:
            time.sleep(RETRY_PAUSE)
        n += 1
        try:
            req = urllib.request.Request(url + "/api/team", method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read(2048)
                code = r.status
        except urllib.error.HTTPError as e:      # 404 라도 서버는 살아 있다 = 이 망에서 닿는다
            code = e.code
        except ValueError as e:                  # 주소 형식 — 다시 해도 같다
            err = e
            break
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            err = e
            continue
        return {"ok": True, "url": url, "code": code, "ms": int((time.time() - t0) * 1000), "tries": n}
    reason = getattr(err, "reason", err)
    return {"ok": False, "url": url, "ms": int((time.time() - t0) * 1000), "tries": n,
            "error": f"{reason}",
            "hint": "이 망에서는 팀 서버에 닿지 않습니다 — 서버망(사내망)에서 다시 눌러 주세요. "
                    "묶음은 그대로 대기합니다."}


class _PhaseConn(http.client.HTTPConnection):
    r"""업로드 연결 — 연결은 짧게(connect_timeout), 답은 길게(read_timeout) 기다리고, 끊긴 단계를 phase[0] 에 남긴다.
    connect(연결 중) → send(본문 보내는 중) → wait(본문을 다 보내고 답을 기다리는 중).
    한 상한으로 묶으면 닿지 않는 서버를 45초씩 기다리고, 끊긴 단계를 모르면 서버가 이미 받았을 수 있는 묶음을 또 보낸다."""

    def __init__(self, host, timeout=None, *, connect_timeout, read_timeout, phase, **kw):
        super().__init__(host, timeout=connect_timeout, **kw)
        self._read_timeout = read_timeout
        self._phase = phase

    def connect(self):
        self._phase[0] = "connect"
        super().connect()
        self.sock.settimeout(self._read_timeout)
        self._phase[0] = "send"

    def getresponse(self):
        self._phase[0] = "wait"
        return super().getresponse()


class _PhaseHandler(urllib.request.HTTPHandler):
    """urllib 이 업로드 연결을 _PhaseConn 으로 만들게 한다(프록시·오류 처리는 urllib 그대로)"""

    def __init__(self, connect_timeout, read_timeout, phase):
        super().__init__()
        self._kw = {"connect_timeout": connect_timeout, "read_timeout": read_timeout, "phase": phase}

    def http_open(self, req):
        return self.do_open(lambda host, **kw: _PhaseConn(host, **kw, **self._kw), req)


def _proxy_handler():
    r"""프록시는 예전 urlopen 과 같은 길을 따른다 — 설치된 오프너(urllib.request.install_opener)가 있으면 그 설정,
    없으면 시스템 설정(환경 변수·인터넷 옵션). 업로드만 연결·답 시간을 따로 재려고 오프너를 새로 짓기 때문이다."""
    for h in getattr(getattr(urllib.request, "_opener", None), "handlers", None) or ():
        if isinstance(h, urllib.request.ProxyHandler):
            return urllib.request.ProxyHandler(dict(h.proxies))
    return urllib.request.ProxyHandler()


def _is_timeout(e):
    return isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)


def _post_json(url, body, connect_timeout, read_timeout, phase):
    """본문 POST → 서버 답(JSON). 실패는 예외 그대로 — 어느 단계였는지는 phase[0] 이 말한다."""
    op = urllib.request.build_opener(_proxy_handler(), _PhaseHandler(connect_timeout, read_timeout, phase))
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with op.open(req, timeout=read_timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def upload_one(url, path, timeout=None, connect_timeout=None):
    """대기 묶음 한 개 전송 → (ok, 메시지, 갈래). timeout = 본문을 다 보낸 뒤 답 상한, connect_timeout = 연결 상한
    (없으면 wait_limits — config.teamUpload.timeoutSec 45초 · pingTimeoutSec 3초).
    갈래(LM28) — 자동 보고(run.py)가 실패 사유를 한국어 문구의 부분 문자열이 아니라 이 값으로 가른다(문구를 다듬어도
    분류가 깨지지 않게): sent 보냄 · blocked 이 묶음은 이대로 보낼 수 없음(읽기 실패·크기·이름·파일명·개인정보 관문·형식) ·
    rejected 서버가 받지 않음(HTTP 오류·ok:false·응답 해석 불가) · unreachable 연결 실패(2번)·보내는 중이나 답 전에 끊김 ·
    slow 본문은 갔는데 답이 상한 안에 오지 않음(서버에 저장됐을 수 있다 — 다시 보내지 않는다)."""
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        return False, f"묶음을 읽지 못했습니다: {e}", "blocked"
    if len(raw) > MAX_BYTES:
        return False, (f"묶음이 너무 큽니다 ({len(raw) / 1048576:.1f}MB > 30MB) — "
                       "기간을 나눠 분석한 뒤 다시 시도하세요"), "blocked"
    # 저장한 본문에는 built 가 더 들어 있다. 서버는 member/files 만 보므로 그대로 보내도 되지만,
    # 계약을 명확히 하려고 두 키만 추려 보낸다.
    try:
        d = json.loads(raw.decode("utf-8-sig"))
        member = d.get("member") or {}
        files = d.get("files") or {}
        # 이름이 서버 규칙에 어긋날 때만 지금 설정으로 고쳐 각인한다 — 잘못된 이름 때문에 영구히
        # 거부되는 것은 막되, 다른 사람의 묶음을 대신 올릴 때(USB 로 옮겨 온 경우) 그 사람의
        # 이름이 올리는 사람 것으로 바뀌지 않게 한다.
        _ow = str(member.get("owner") or "")
        if not _ow or _ow != safe_owner(_ow) or len(_ow) > 40:
            member["owner"] = safe_owner(load_cfg().get("owner") or _ow
                                         or os.environ.get("USERNAME", ""))
        # 보내는 시점의 흔적 — 대리 업로드여도 '올린 PC'는 여기서 찍힌다(이름은 원저자 유지)
        member["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M")
        member["uploaded_from"] = os.environ.get("COMPUTERNAME", "")
        # G4 — 보내기 직전에도 팀 반출 변환을 한 번 더 건다. LM28 build 묶음은 이미 변환됐지만(다시 걸어도 같다),
        # 예전 판이 만든 묶음이 upload_pending 에 남아 있으면 신호 원문이 그대로 나갔다(WP7 지적).
        _cfg0 = load_cfg()
        for _n in list(files):
            _txt, _note = team_signals(_n, files[_n], _cfg0)
            if _note:
                print(f"[teamup] {_note}")
            if _txt is None:
                del files[_n]
            else:
                files[_n] = _txt
        if not files:
            return False, "보낼 수 있는 파일이 없습니다 — 신호 파일이 개인정보 관문에 막혔습니다(다시 분석하세요)", "blocked"
        stop = blockers(member, files)
        if stop:
            return False, stop[0], "blocked"
        body = json.dumps({"member": member, "files": files},
                          ensure_ascii=False).encode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False, "묶음 형식이 깨졌습니다 — 해당 기간을 다시 분석하세요", "blocked"
    if timeout is None or connect_timeout is None:
        lim = wait_limits(load_cfg())
        timeout = lim["timeout"] if timeout is None else timeout
        connect_timeout = lim["ping_timeout"] if connect_timeout is None else connect_timeout
    # 연결 단계 실패(거부·경로 없음·이름 풀이·연결 시간 초과)만 1번 다시 한다 — 서버는 본문을 받지 못했으니 다시 보내도 안전하다.
    # 본문을 다 보낸 뒤(wait) 답이 늦으면 다시 보내지 않는다: 서버가 이미 저장했을 수 있고, 느린 서버에 다시 보내면 기다림만 두 배다.
    for attempt in range(2):
        phase = ["connect"]
        try:
            res = _post_json(url + "/api/upload", body, connect_timeout, timeout, phase)
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except (OSError, http.client.HTTPException):
                pass
            return False, f"서버가 거부했습니다 (HTTP {e.code}) {detail}", "rejected"
        except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
            reason = getattr(e, "reason", e)
            if phase[0] == "connect":
                if attempt == 0:
                    time.sleep(RETRY_PAUSE)
                    continue
                return False, f"연결 실패(2번 시도): {reason}", "unreachable"
            if phase[0] == "send":
                return False, f"보내는 중 연결이 끊겼습니다: {reason}", "unreachable"
            if _is_timeout(e):
                return False, f"{SLOW_MSG} ({timeout:.0f}초 안에 답이 없었습니다)", "slow"
            return False, (f"답을 받기 전에 연결이 끊겼습니다({reason}) — 서버에 저장됐을 수 있습니다. "
                           "묶음은 대기로 남겨 다음 실행 때 다시 보냅니다(덮어쓰기라 결과는 같습니다)"), "unreachable"
        except ValueError:
            return False, "서버 응답을 해석하지 못했습니다", "rejected"
    if not isinstance(res, dict) or not res.get("ok"):
        return False, f"서버 거부: {res.get('error', '') if isinstance(res, dict) else ''}", "rejected"
    where = str(res.get("store") or "")
    host = str(res.get("host") or "")
    me = os.environ.get("COMPUTERNAME", "")
    same_pc = bool(host and me and host == me)
    other_folder = same_pc and os.path.normcase(os.path.abspath(str(res.get("root") or ""))) \
        != os.path.normcase(os.path.abspath(ROOT))
    note = ""
    if where:
        note = f" · 저장 위치: {where}" + (f" ({host})" if host and not same_pc else "")
    if other_folder:
        # 같은 PC 인데 다른 설치 폴더가 받았다 — 사용자가 겪은 바로 그 상황
        note += "  [!] 이 PC 의 다른 폴더가 받았습니다 — 그 폴더의 팀 취합에 들어갑니다"
    if res.get("queued"):
        # LM28 서버 — 저장하자마자 답하고 취합은 뒤에서 돈다(queued — aggregated 는 "queued"). 예전 서버는 취합을 마친 뒤 aggregated 로 답한다
        return True, f"{res.get('saved')}개 파일 저장됨 — 팀 취합은 서버가 이어서 갱신합니다" + note, "sent"
    return True, (f"{res.get('saved')}개 파일 저장, 팀 취합 "
                  f"{'갱신됨' if res.get('aggregated') else '갱신 실패(서버 로그 확인)'}" + note), "sent"


def upload_all(url, timeout=None, connect_timeout=None, budget=None, t0=None):
    """대기 묶음을 차례로 전송. 성공분만 upload_sent 로 옮긴다(실패분은 그대로 대기). 묶음마다 kind(upload_one 의 갈래).
    LM28 — 닿지 않거나(unreachable) 답이 늦으면(slow) 거기서 멈춘다: 같은 서버라 남은 묶음도 같은 기다림을 되풀이한다.
    t0(time.monotonic — 연결 확인 전 시각)부터 budget 초가 지나 다음 묶음의 답 상한까지 기다릴 여유가 없으면 새로 시작하지
    않는다(첫 묶음은 언제나 보낸다). 남긴 묶음은 대기 그대로 — 건수는 left, 사유는 stopped."""
    items = list_pending()
    results = []
    if not items:
        return {"ok": True, "sent": 0, "failed": 0, "results": [],
                "note": "보낼 대기 묶음이 없습니다 — 먼저 [분석 실행]을 하세요"}
    if timeout is None or connect_timeout is None:
        lim = wait_limits(load_cfg())
        timeout = lim["timeout"] if timeout is None else timeout
        connect_timeout = lim["ping_timeout"] if connect_timeout is None else connect_timeout
    budget = BUDGET_SEC if budget is None else budget
    t0 = time.monotonic() if t0 is None else t0
    os.makedirs(SENT, exist_ok=True)
    sent = failed = left = 0
    stopped = ""
    for i, it in enumerate(items):
        if i and time.monotonic() - t0 + timeout > budget:
            left = len(items) - i
            stopped = (f"시간 상한({budget:.0f}초)에 닿아 나머지 {left}건은 보내지 않고 대기로 남겼습니다 — "
                       "[팀 서버 업로드]를 다시 누르거나 다음 실행 때 이어서 보냅니다")
            break
        p = os.path.join(PENDING, it["file"])
        ok, msg, kind = upload_one(url, p, timeout, connect_timeout)
        if ok:
            sent += 1
            try:                            # 보낸 것은 옮겨 두 번 보내지 않는다(기록은 남긴다)
                shutil.move(p, os.path.join(SENT, it["file"]))
            except OSError:
                pass
            prune_sent()
        else:
            failed += 1
        results.append({"file": it["file"], "tag": it.get("tag", ""), "ok": ok, "msg": msg, "kind": kind})
        if not ok and kind in STOP_KINDS:
            left = len(items) - i - 1
            if left:
                stopped = (f"{'서버 응답 지연으로' if kind == 'slow' else '서버 연결 실패로'} 나머지 {left}건은 보내지 않고 "
                           "대기로 남겼습니다 — 다음 실행 때 다시 보냅니다")
            break
    r = {"ok": failed == 0 and not left, "sent": sent, "failed": failed, "left": left, "results": results}
    if stopped:
        r["stopped"] = stopped
    return r


def to_folder(share):
    """서버 대신 공유폴더로 — <공유폴더>\\<이름>\\ 에 파일과 member.json 을 쓴다(export.py 와 동일 형식)"""
    items = list_pending()
    if not items:
        return {"ok": True, "sent": 0, "failed": 0, "results": [],
                "note": "보낼 대기 묶음이 없습니다"}
    share = os.path.expandvars(str(share or "").strip().strip('"').strip("'"))
    if not share:
        return {"ok": False, "error": "공유폴더 경로가 비어 있습니다 (config.teamShareDir)"}
    # 상대경로·오타는 엉뚱한 폴더를 만들어 '저장됐다'고 믿게 만든다(검증 확정) — 미리 막는다
    if not os.path.isabs(share):
        return {"ok": False, "error": f"절대경로나 UNC 여야 합니다: {share}"}
    if not os.path.isdir(longp(share)):
        return {"ok": False, "error": f"공유폴더가 없거나 이 망에서 닿지 않습니다: {share}"}
    sent = failed = 0
    results = []
    os.makedirs(SENT, exist_ok=True)
    for it in items:
        p = os.path.join(PENDING, it["file"])
        try:
            d = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, ValueError):
            results.append({"file": it["file"], "ok": False, "msg": "묶음 형식이 깨졌습니다"})
            failed += 1
            continue
        m = d.get("member") or {}
        owner = m.get("owner") or "이름미상"
        dst = os.path.join(share, owner)
        try:
            # 공유폴더 자체는 이미 있어야 하므로 만들 것은 <이름> 한 단계뿐이다
            # (os.makedirs 는 확장 경로에서 부모까지 거슬러 올라가다 깨진다 — 한 단계만 만든다)
            if not os.path.isdir(longp(dst)):
                os.mkdir(longp(dst))
        except FileExistsError:
            pass
        except OSError as e:
            hint = " (경로가 260자를 넘습니다 — 더 짧은 공유폴더를 쓰세요)" if len(os.path.abspath(dst)) >= MAXP else ""
            results.append({"file": it["file"], "ok": False,
                            "msg": f"공유폴더 접근 실패: {e}{hint} — 이 망에서 닿지 않을 수 있습니다"})
            failed += 1
            continue
        want, cfg0 = {}, load_cfg()
        for name, text in (d.get("files") or {}).items():
            # 예전 판이 만든 묶음도 같은 팀 반출 변환을 거친다(이미 변환한 본문이면 그대로 — 멱등)
            txt, note = team_signals(name, text, cfg0)
            if note:
                print(f"[teamup] {note}")
            if txt is not None:
                want[name] = txt
        n_ok, bad = 0, []
        for name, text in want.items():
            try:
                with open(longp(os.path.join(dst, name)), "w", encoding="utf-8-sig", newline="") as f:
                    f.write(text)
                n_ok += 1
            except OSError as e:
                bad.append(f"{name}({type(e).__name__})")
        # 일부만 써 놓고 member.json 을 갱신하면 팀 취합이 '신호 없는 인원'으로 집계된다(검증 확정).
        # 전부 성공했을 때만 member.json 을 쓰고, 그럴 때만 대기열에서 뺀다.
        if n_ok == len(want) and want and not bad:
            try:
                # host 를 지우지 않는다 — 어느 PC 에서 나온 결과인지 팀장이 알아야 한다(사용자 요청)
                mm = dict(m)
                mm["uploaded_at"] = time.strftime("%Y-%m-%d %H:%M")
                mm["uploaded_from"] = os.environ.get("COMPUTERNAME", "")
                mm["via"] = "공유폴더"
                with open(longp(os.path.join(dst, "member.json")), "w", encoding="utf-8") as f:
                    json.dump(mm, f, ensure_ascii=False, indent=1)
            except OSError as e:
                bad.append(f"member.json({type(e).__name__})")
        if n_ok == len(want) and want and not bad:
            sent += 1
            # 개인 HTML 보고서(분석리포트·얼린 보고서)는 묶음이 아니라 여기서 따로 —
            # <share>\개인리포트\<이름>_<파일명>. 복사 실패는 알리되 묶음 저장 성공을 되돌리지 않는다.
            rep_msg = ""
            try:
                copied, rbad = push_reports(share, owner, m.get("tag") or it.get("tag") or "")
            except Exception as e:  # noqa: BLE001 - 부가 복사가 본 저장을 망치지 않게
                copied, rbad = [], [f"개인리포트({type(e).__name__})"]
            if copied:
                rep_msg += f" · 개인리포트 {len(copied)}개"
            if rbad:
                rep_msg += f" · 개인리포트 복사 실패: {', '.join(rbad[:2])}"
            results.append({"file": it["file"], "tag": it.get("tag", ""), "ok": True,
                            "msg": f"{os.path.abspath(dst)} 에 {n_ok}개 파일{rep_msg}",
                            "reports": copied})
            try:
                shutil.move(p, os.path.join(SENT, it["file"]))
            except OSError:
                pass
        else:
            failed += 1
            results.append({"file": it["file"], "tag": it.get("tag", ""), "ok": False,
                            "msg": f"{n_ok}/{len(want)}개만 저장됨 — 실패: {', '.join(bad[:3])} "
                                   "(대기 유지 — 잠금이 풀린 뒤 다시 시도하세요)"})
    return {"ok": failed == 0, "sent": sent, "failed": failed, "results": results,
            "dest": share}


def prune_sent(keep=20):
    """보낸 기록 보관 상한 — 묶음은 통째로 크므로 오래된 것부터 지운다"""
    try:
        ns = sorted((n for n in os.listdir(SENT) if n.endswith(".json")),
                    key=lambda n: os.path.getmtime(os.path.join(SENT, n)), reverse=True)
    except OSError:
        return
    for n in ns[keep:]:
        try:
            os.remove(os.path.join(SENT, n))
        except OSError:
            pass


def drop(which):
    """보낼 수 없는 묶음을 대기열에서 치운다(기록은 upload_sent 로 옮겨 남긴다)"""
    hits = [it for it in list_pending()
            if which in (it.get("file", ""), it.get("tag", ""))]
    if not hits:
        return {"ok": False, "error": f"대기 목록에 없습니다: {which}"}
    os.makedirs(SENT, exist_ok=True)
    for it in hits:
        try:
            shutil.move(os.path.join(PENDING, it["file"]),
                        os.path.join(SENT, "dropped_" + it["file"]))
        except OSError as e:
            return {"ok": False, "error": f"치우지 못했습니다: {e}"}
    return {"ok": True, "dropped": [it["file"] for it in hits], "pending": len(list_pending())}


def _tu_flag(cfg, key):
    """config.teamUpload 의 켬/끔 값 → bool. 없거나 null·빈 값이면 켬, false·"false"·0·"off"·"no" 면 끔(그 밖은 켬)."""
    tu = cfg.get("teamUpload") if isinstance(cfg, dict) else None
    v = tu.get(key) if isinstance(tu, dict) else None
    if v is None or (isinstance(v, str) and not v.strip()):
        return True
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def auto_report_on(cfg):
    r"""[분석 실행] 끝에 팀 서버로 자동 보고할까 → bool (LM28 사용자 요청 — "분석실행 마무리는 팀서버로 자동으로 레포팅까지").
    config.teamUpload.autoReport — 없거나 null·빈 값이면 켬(기본), false·"false"·0·"off"·"no" 면 끔. 이 키가 있으면 이것이 이긴다.
    옛 키 teamUpload.auto 는 보지 않는다: true 는 '켜기' 라 기본과 같고, false 는 LM19~LM24 배포 설정의 **기본값**이었을 뿐
    사용자가 고른 뜻이 아니다(끄기로 읽으면 옛 설정을 이어받은 PC 전부가 자동 보고를 못 받는다).
    run.py(보고 여부)·화면(카드 머리말)·status()(--list)가 모두 이 한 함수로 읽는다 — 해석이 갈리지 않게."""
    return _tu_flag(cfg, "autoReport")


def require_saved_on(cfg):
    r"""LM30 시험판 보호를 켤까 → bool — config.teamUpload.requireSavedAddress(배포 설정 true). 읽는 규칙은 autoReport 와 같다:
    없거나 null·빈 값이면 **켬** — LM28·LM29 의 config.json 을 옮겨 와 이 키가 없어도 기존 팀 서버로 새지 않게.
    false·"false"·0·"off"·"no" 면 끔(예전처럼 기본 주소로도 보낸다)."""
    return _tu_flag(cfg, "requireSavedAddress")


def upload_guard(cfg, url=None):
    r"""LM30 시험판 보호 → 보내지 않는 사유 문구 | ""(보내도 됨). requireSavedAddress 가 켜져 있을 때만 막는다.
    막는 경우: ① 보낼 주소가 기본 주소(core\teamaddr 의 DEFAULT_* = 기존 팀 서버) 그 자체 — 저장 파일이나 일회성
    --url·--host 로 같은 주소를 적어도 막는다 ② 설정 주소로 보내는데 서버 IP·포트 어느 것도 config\team_server.json 에서 오지
    않았다(teamaddr 의 source — 옛 판 config.json 에서 이어받은 주소). url = 이번에 보낼 주소(target_url) · None 이면 설정 주소.
    주소가 비었으면 ""(no_url 이 따로 말한다). run.py 자동 보고·화면 업로드 카드·main(--upload)이 모두 이 한 함수로 가른다."""
    if not require_saved_on(cfg):
        return ""
    import teamaddr
    a = teamaddr.load(ROOT)
    u = str(a.url if url is None else (url or "")).strip().rstrip("/").lower()
    if not u:
        return ""
    if u == f"http://{teamaddr.DEFAULT_HOST}:{teamaddr.DEFAULT_PORT}".lower():
        why = "기본 주소 = 기존 팀 서버"
    elif u == a.url.lower() and "file" not in (a.source.get("host"), a.source.get("port")):
        why = "이전 판 설정에서 이어받은 주소"
    else:
        return ""
    return f"{NO_TEST_MSG} (지금 주소: {why})"


def write_report_status(rep_dir, st):
    r"""report\team_report_status.json 쓰기(임시 파일 → 교체 — 화면이 반쪽 파일을 읽지 않게) → 경로 | None.
    at 이 없으면 지금 시각(초까지 — 화면이 이 값을 열쇠로 '끝난 실행 1번당 알림 1번' 을 가른다).
    싣는 것은 건수·사유·시각뿐이다(묶음 본문·메일 제목 없음). 쓰기 실패는 삼킨다 — 기록이 분석·업로드를 실패로 만들지 않게."""
    try:
        d = dict(st or {})
        d.setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
        os.makedirs(rep_dir, exist_ok=True)
        p = os.path.join(rep_dir, REPORT_STATUS)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
        return p
    except (OSError, TypeError, ValueError):
        return None


def read_report_status(rep_dir):
    """마지막 팀 서버 보고 결과(dict) — 없거나 깨졌으면 {}"""
    try:
        with open(os.path.join(rep_dir, REPORT_STATUS), encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _sent_status(r, via):
    """버튼·bat(--upload)·공유폴더(--to-folder)가 대기분을 **다** 보냈을 때만 '성공' 을 남긴다 — 자동 보고 실패 배너는
    다음 성공까지 뜨므로, 사람이 사내망에서 밀린 것을 보내면 그 배너가 내려가야 한다. 일부라도 실패면 지난 기록 그대로."""
    try:
        done = isinstance(r, dict) and r.get("ok") and int(r.get("sent") or 0) > 0 and not int(r.get("failed") or 0)
    except (TypeError, ValueError):
        done = False
    if done:
        write_report_status(REPORT, {"ok": True, "sent": int(r["sent"]), "failed": 0, "pending": len(list_pending()),
                                     "reason": "", "hint": "", "via": via})


def status(cfg, url=""):
    """대시보드용 현황 — 도달성 확인은 하지 않는다(누를 때만 한다). auto = [분석 실행] 끝 자동 보고 켬(auto_report_on).
    guard = LM30 시험판 보호에 걸리면 그 사유(upload_guard — 업로드 카드가 규칙을 보이고 버튼이 까닭을 말한다) · 아니면 ""."""
    url = url or target_url(cfg)
    return {"url": url, "share": (cfg.get("teamShareDir") or "").strip(),
            "auto": auto_report_on(cfg), "guard": upload_guard(cfg, url),
            "pending": list_pending(), "sent": list_sent(),
            # 묶음이 없어도 결과가 있으면 '지금 묶기'를 권할 수 있게(실측 제보)
            "available": buildable()}


def _out(js, obj, human=""):
    if human:
        print(human)
    if js:
        print(json.dumps(obj, ensure_ascii=False))


def main():
    cfg = load_cfg()
    js = "--json" in sys.argv
    if "--list" in sys.argv:
        st = status(cfg)
        lines = [f"[teamup] 서버: {st['url'] or '(미설정)'} · 대기 {len(st['pending'])}건"]
        if st.get("guard"):
            lines.append(f"         ! 보내지 않습니다 — {st['guard']}")
        for it in st["pending"]:
            lines.append(f"         - {it.get('tag', '?')}  {it.get('built', '')}  "
                         f"{it.get('files', 0)}개 파일  {it.get('bytes', 0) / 1024:.0f}KB")
        if not st["pending"]:
            lines.append("         (없음 — 분석을 실행하면 묶음이 준비됩니다)")
        _out(js, st, "\n".join(lines))
        return 0
    if "--scan" in sys.argv:
        r = {"ok": True, "tags": report_tags(), "buildable": buildable()}
        lines = [f"[teamup] report 에 결과가 있는 기간 {len(r['tags'])}개"]
        for t in r["tags"]:
            lines.append(f"         - {t['tag']}  ({' ~ '.join(t['period'])})  {t['at']}")
        _out(js, r, "\n".join(lines))
        return 0
    if "--build-all" in sys.argv or "--build-latest" in sys.argv:
        want = buildable()
        if "--build-latest" in sys.argv:
            want = want[:1]
        made, skipped = [], []
        for t in want:
            p = build(cfg, t["period"][0], t["period"][1])
            (made if p else skipped).append(t["tag"])
        r = {"ok": bool(made), "built": made, "skipped": skipped,
             "pending": len(list_pending())}
        if not made:
            r["error"] = "묶을 결과가 없습니다"
            r["hint"] = ("report 폴더에 mm_rows_<기간>.csv 가 없습니다 — 먼저 [분석 실행]을 하세요."
                         if not report_tags() else "이미 모든 기간의 묶음이 준비돼 있습니다.")
        _out(js, r, f"[teamup] 묶음 생성: {len(made)}개 {made} — 대기 {r['pending']}건"
                    + (f" · {r.get('hint', '')}" if r.get("hint") else ""))
        return 0 if made else 1
    if "--drop" in sys.argv:
        r = drop(arg("--drop"))
        _out(js, r, f"[teamup] {'치웠습니다' if r.get('ok') else '실패'}: "
                    f"{r.get('dropped') or r.get('error', '')}")
        return 0 if r.get("ok") else 1
    if "--ping" in sys.argv:
        r = ping(target_url(cfg))
        _out(js, r, f"[teamup] {'닿음' if r.get('ok') else '닿지 않음'}: {r.get('url', '')} "
                    f"{r.get('ms', '')}ms {r.get('error', '')}")
        return 0 if r.get("ok") else 1
    if "--build" in sys.argv:
        d0, d1 = arg("--from"), arg("--to")
        if not d0 or not d1:
            print("[teamup] 사용법: python teamup.py --build --from YYYY-MM-DD --to YYYY-MM-DD")
            return 1
        p = build(cfg, d0, d1)
        if not p:
            _out(js, {"ok": False, "error": "산출물 없음"},
                 f"[teamup] {d0}~{d1} 산출물이 없습니다 — 기간을 확인하세요")
            return 1
        info = _info(p)
        head = (f"[teamup] 업로드 묶음 준비됨: {info['tag']} ({info['files']}개 파일, "
                f"{info['bytes'] / 1024:.0f}KB) — 대기 {len(list_pending())}건")
        if info.get("blocked"):
            # 지금 알려 주지 않으면 며칠 뒤 서버망에서야 실패를 알게 된다
            head += "\n         ! 이대로는 보낼 수 없습니다: " + " / ".join(info["blocked"])
        else:
            head += "\n         서버에 닿는 망에서 대시보드 [팀 서버 업로드] 버튼을 누르면 전송됩니다."
        _out(js, {"ok": True, "bundle": info, "blocked": info.get("blocked") or []}, head)
        return 0
    if "--to-folder" in sys.argv:
        share = arg("--to-folder") or (cfg.get("teamShareDir") or "")
        r = to_folder(share)
        _sent_status(r, "folder")
        _out(js, r, f"[teamup] 공유폴더 저장: 성공 {r.get('sent', 0)} / 실패 {r.get('failed', 0)}"
                    + (f" — {r.get('error', '')}" if r.get("error") else ""))
        return 0 if r.get("ok") else 1
    if "--upload" in sys.argv:
        url = target_url(cfg)
        if not url:
            _out(js, {"ok": False, "error": "팀 서버 주소가 비었거나 형식이 틀렸습니다", "no_url": True,
                      "pending": len(list_pending())},
                 "[teamup] 팀 서버 주소가 비었거나 형식이 틀렸습니다 — LoadMonitor30-팀서버주소.bat 에서 "
                 "서버 IP·포트를 저장하세요")
            return 1
        why = upload_guard(cfg, url)
        if why:
            # LM30 시험판 보호 — 연결 확인도 하지 않는다(보낼 곳이 아니다). 실패가 아니라 '보내지 않음' 이라 종료 코드 0 ·
            # ok null · results 없음 · 묶음은 대기 그대로. run.py 자동 보고·화면은 kind 로 가른다(알림·배너 없음)
            n = len(list_pending())
            _out(js, {"ok": None, "kind": NO_TEST_KIND, NO_TEST_KIND: True, "note": why, "sent": 0, "failed": 0,
                      "results": [], "pending": n},
                 f"[teamup] 보내지 않았습니다 — {why}\n         올릴 주소: {url} · 대기 {n}건")
            return 0
        t0 = time.monotonic()                   # 시간 상한(BUDGET_SEC)은 연결 확인부터 잰다
        pg = ping(url)
        if not pg.get("ok"):
            _out(js, {"ok": False, "error": pg.get("error", ""), "hint": pg.get("hint", ""),
                      "unreachable": True, "pending": len(list_pending())},
                 f"[teamup] 이 망에서 서버에 닿지 않습니다 ({url} · {pg.get('tries', 1)}번 시도) — {pg.get('error', '')}\n"
                 f"         묶음 {len(list_pending())}건은 그대로 대기합니다. "
                 "서버망에서 다시 실행하면 한 번에 올라갑니다.")
            return 1
        r = upload_all(url, t0=t0)
        r["pending"] = len(list_pending())      # 보낸 뒤 남은 대기 수(LM28 — 자동 보고·화면 배너가 읽는다)
        _sent_status(r, "upload")
        lines = [f"[teamup] 전송 완료: 성공 {r['sent']} / 실패 {r['failed']}"]
        for x in r.get("results", []):
            lines.append(f"         - {x.get('tag', x['file'])}: {'OK' if x['ok'] else '실패'} {x['msg']}")
        for k in ("stopped", "note"):
            if r.get(k):
                lines.append("         " + r[k])
        _out(js, r, "\n".join(lines))
        return 0 if r.get("ok") else 1
    # 하위 호환: 예전처럼 --from/--to 만 주면 '준비 후 곧바로 전송 시도'
    d0, d1 = arg("--from"), arg("--to")
    if d0 and d1:
        p = build(cfg, d0, d1)
        if not p:
            print(f"[teamup] {d0}~{d1} 산출물이 없습니다")
            return 1
        url = target_url(cfg)
        if not url:
            print("[teamup] 주소 미설정 — 묶음만 준비했습니다 (대시보드에서 업로드)")
            return 0
        why = upload_guard(cfg, url)
        if why:                             # LM30 시험판 보호 — --upload 와 같다(묶음만 준비)
            print(f"[teamup] 묶음만 준비했습니다 — {why}")
            return 0
        t0 = time.monotonic()
        pg = ping(url)
        if not pg.get("ok"):
            print(f"[teamup] 이 망에서 서버에 닿지 않습니다 — 묶음은 대기합니다 ({pg.get('error', '')})")
            return 1
        r = upload_all(url, t0=t0)
        _sent_status(r, "upload")
        print(f"[teamup] 전송: 성공 {r['sent']} / 실패 {r['failed']}")
        for x in r.get("results", []):      # 무엇이 어떻게 됐는지 화면에 남긴다(서버 갱신 여부 포함)
            print(f"         - {x.get('tag', x['file'])}: {'OK' if x['ok'] else '실패'} {x['msg']}")
        if r.get("stopped"):
            print("         " + r["stopped"])
        return 0 if r.get("ok") else 1
    print(__doc__.strip().splitlines()[1])
    print("[teamup] --build / --list / --ping / --upload / --to-folder 중 하나를 주세요")
    return 1


if __name__ == "__main__":
    sys.exit(main())
