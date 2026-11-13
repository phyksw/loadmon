# -*- coding: utf-8 -*-
r"""
run.py — AgentFinder32 통합 실행기: 시작 검사 → 내 Outlook 메일·일정 수집(G1 정제) → 업무 분류 추출 →
(AI 판정·정제·Agentic AI 후보·업무 흐름) → 개인 리포트(이 PC 안) → 보관기한 정리.

  python run.py                                      # 기간 생략 = 최근 3개월(어제까지 92일)
  python run.py --from 2026-08-01 --to 2026-10-31    # 기간 지정 — 오늘은 넣지 않고 period.maxDays 일까지로 줄인다
  python run.py ... --skip-collect                   # 이미 모은 자료로 분석만
  python run.py ... --ai                             # Copilot 으로 판정·정제·Agentic AI 후보·업무 흐름까지
  python run.py ... --web-only mail                  # Outlook 웹 읽기만(화면 버튼)
  python run.py ... --reset-cursors                  # 수집 커서·일자 원장을 지우고 처음부터 읽기
  python run.py ... --no-mail-web | --no-mail-copilot   # 이번 실행에서 Outlook 웹 · Copilot 경로를 건너뜀

원칙
  · 목적은 Agentic AI 로 바꿀 만한 업무를 찾는 것 하나입니다. 사람을 평가하거나 근태·업무량을 보는 데 쓰지 않습니다.
  · 내 Outlook 메일·일정만 읽습니다(collect.channels — Outlook 앱 · Outlook 웹 · M365 Copilot). 오늘은 넣지 않습니다.
  · 수집 직후 G1(core\privacy)이 비공개·휴가·행방·사외·제한 고객·민감·식별번호 항목을 빼고 이름을 가립니다.
    Outlook 앱의 원자료(data\outlook\raw)는 정제한 뒤 바로 지웁니다(중간에 멈췄으면 다음 시작 때).
  · 결과는 이 PC 에 남습니다. 이 실행기는 조직장에게 아무것도 보내지 않습니다(AI 분석은 회사 M365 Copilot 을 씁니다) —
    공유는 화면의 [공유] 탭에서 본인이 고를 때만.

시작 순서: 설치 위치·옛 LoadMonitor 파일·설치 폴더 권한(core\install.startup_check) → 끝나지 않은 [모두 지우기] 마저 하기
  (consent.resume_withdrawal) → 분석 잠금(data\run.lock — 이 폴더의 다른 실행이 돌면 멈춤 · 실행 내내 쥔다) →
  옛 자료 정리(retention.purge_legacy) → 보관기한 정리(retention.purge) → 시작 확인(consent.require — 이 폴더의 자료가 다른
  사용자의 것이거나 주인을 모르면 종료 코드 4 · [모두 지우기]가 끝나지 않았으면 3) → 매일 정리 작업 맞추기(retention.sync_task) →
  제한 고객 목록(privacy.load_restricted — 없으면 4) → 기간(period.clamp). 사내 메일 도메인은 수집 경로가 붙은 뒤에
  확인합니다(모르면 4).
  이 실행기는 쓰겠다는 뜻을 묻지 않습니다(서면으로 따로 받습니다). 시작할 때 끝나지 않은 [모두 지우기]를 만나면 마저 지우고,
  그 시작에서는 분석하지 않습니다(종료 코드 3 — 다 지웠으면 다음 시작은 새 설치로 바로 씁니다).
  시작 확인은 Outlook 앱 원자료 정제·병합·각 분석 단계 직전에 다시 합니다 — 그 사이 [모두 지우기]가 시작됐거나 설치 정보가
  사라졌으면 이 실행이 쓴 수집·분석 파일과 원자료·실행 기록을 지우고 멈춥니다(종료 코드 3 · 주인을 모르게 됐으면 4).
종료 코드: 0 정상 · 1 실패 · 2 일부만(로그인 필요·AI 단계 일부·리포트 못 만듦) · 3 [모두 지우기]가 끝나지 않음 ·
  4 다른 사용자의 자료·주인을 모르는 자료 · 설정 거부(제한 고객 목록·사내 도메인·설치 위치·옛 파일). 자식의 종료 코드를 그대로
  돌려주지 않습니다.
"""
import glob
import io
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(refine.py 와 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
import afcfg  # noqa: E402 - core\ (sys.path 위에서 등록)
import collect_status  # noqa: E402
import consent  # noqa: E402
import coverage  # noqa: E402
import install  # noqa: E402
import lmname  # noqa: E402
import period  # noqa: E402
import proc  # noqa: E402
import retention  # noqa: E402

NO_WIN = 0x08000000
EXIT_OK, EXIT_FAIL, EXIT_PARTIAL, EXIT_CONSENT, EXIT_SETUP = 0, 1, 2, 3, 4
# EXIT_CONSENT(이름은 예전 그대로) = [모두 지우기]가 끝나지 않아 멈춤 · EXIT_SETUP = 다른 사용자의 자료·주인을 모르는 자료 · 설정 거부
_AI_T0 = None            # AI 마감 기준 시각(선예약 반환용)
_AI_TOT_MIN = None
_AI_RES = {"flow": 0.0, "ag": 0.0}   # 선예약 몫(분) — 업무 흐름·Agentic AI 후보. Agentic 직전·flow 직전에 돌려준다
# 수집 단계는 core\proc.run_step(Job 으로 감싸 트리째 정리 · 60초 진행 줄)으로 돌리고, 마지막 줄 AF32STATUS 를
# core\collect_status 로 읽어 일자×축 원장(core\coverage — data\coverage_ledger.json)에 반영한다.
_RUN_STEP = proc.run_step      # 시험이 바꿔 끼운다(사슬 시험 — 실제 수집기를 띄우지 않는다)
_CLOSE_EDGE = None             # 시험 주입 — None 이면 tools\copilot_auto.close_own_edge
_CLEAR_SITE = None             # 시험 주입 — None 이면 tools\copilot_auto.clear_site_data(Outlook·M365 사이트 자료 지우기)
_CHAT_TOTALS = None            # 시험 주입 — None 이면 tools\copilot_auto.chat_totals(Copilot 채팅 정리 누계)
_CHAT_REPORT = None            # 시험 주입 — None 이면 tools\copilot_auto.chat_run_report(이번 실행의 Copilot 채팅 셈)
CHATS = {"t0": None}           # 이 실행 시작 때의 Copilot 채팅 정리 누계 — 실행 끝 단계 'Copilot 채팅 정리' 를 남길 실행인지의 표식
CHAT_STAGE = "Copilot 채팅 정리"
CHAT_LINE_HEAD = "[copilot] 채팅 정리"   # 단계 로그의 정리 한 줄(copilot_auto.CHAT_LINE_HEAD) — 실패 사유 줄로 집지 않는다
REPORT_DIR = {"p": os.path.join(ROOT, "report")}     # last_run.json 위치(시험은 임시 폴더로 바꾼다)
MAIL_AXES = coverage.MAIL_AXES
# 이 실행에서 Edge 정리를 했나(closed) · Outlook 웹·Copilot 이 전용 Edge 를 썼나(used — 쓴 뒤에는 그 사이트 자료를 지운다)
EDGE = {"closed": False, "used": False}
STATE = {"login_pending": False}   # 이 실행의 웹 경로 상태(rc 2 → login_pending — 남은 웹 경로·Edge 닫기 건너뜀)
CFG = {"c": {}}                    # 이 실행의 실효 설정(_main 이 채운다 — 사이트 자료 지우기의 포트)
MINE_STAGE = "업무 분류 추출"
REPORT_STAGE = "개인 리포트 만들기"
SETUP_STAGE = "설정 확인 필요"
CONSENT_STAGE = "시작 확인"        # 시작 확인(consent.require)에 걸려 멈춘 실행의 단계 이름(상수 이름은 예전 그대로)
# 자식 단계(수집기·분석 단계)는 시작 확인에 걸렸다고 하는데 여기서 다시 물으면 지나갈 때의 한 줄(자식이 확인하지 못했거나 그 사이 풀렸다)
GATE_CHILD_MSG = "수집·분석 단계가 시작 확인(이 폴더의 자료가 내 것인지 · 지우는 중이 아닌지)을 지나지 못해 멈췄습니다"
# 이 시작이 끝나지 않은 [모두 지우기]를 마쳤을 때 — 그 시작에서는 분석하지 않는다
WIPED_MSG = "자료를 모두 지웠습니다 — 이번에는 분석하지 않습니다. 다시 시작하면 새로 시작합니다."
# 수집기가 AF32STATUS 사유로 알리는 시작 거부(종료 코드 3·4) — 시작 확인(R-CONSENT: 내 자료가 아님 · 지우는 중) · 제한 고객 목록 ·
# 사내 메일 도메인
R_CONSENT, R_NORESTRICTED, R_NODOMAIN = "R-CONSENT", "R-NORESTRICTED", "R-NODOMAIN"
EXCL_KO = {"private": "비공개", "admin": "휴가·행방", "sensitive": "민감", "identifier": "식별번호", "external": "사외",
           "external_unknown": "사내 확인 불가", "restricted": "제한 고객"}


class RunStop(Exception):
    """실행을 여기서 멈춘다(종료 코드 code · 사람에게 보일 message · last_run.json 단계 이름 stage)."""

    def __init__(self, code, message, stage=SETUP_STAGE):
        super().__init__(message)
        self.code, self.message, self.stage = code, message, stage


def cfg(verbose=False):
    r"""config\config.json → 실효 설정(core\afcfg.effective — 기본값 + D22 하한). 깨져도 실행은 계속한다(기본 설정).
    설정가이드가 메모장 편집을 안내하므로 JSON 손상·ANSI 재저장은 예정된 사고다 — verbose 면 한 번 알린다."""
    p = os.path.join(ROOT, "config", "config.json")
    raw = {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raw = {}
            if verbose:
                print("[!] config\\config.json 형식이 맞지 않습니다 — 기본 설정으로 진행합니다.")
    except FileNotFoundError:
        if verbose:
            print("[!] config\\config.json 이 없습니다 — 기본 설정으로 진행합니다 (복사 누락?)")
        raw = afcfg.load(ROOT)
    except (ValueError, UnicodeDecodeError, OSError) as e:
        if verbose:
            print(f"[!] config\\config.json 을 읽지 못했습니다 ({type(e).__name__}) — 기본 설정으로 진행합니다.")
            print("    메모장 저장 시 인코딩은 UTF-8, JSON 문법(마지막 쉼표·역슬래시)을 확인하세요.")
        raw = {}
    eff, warns = afcfg.effective(raw)
    if verbose:
        for w in warns:
            print(f"   [설정] {w}")
    return eff


def arg(flag, dflt=""):
    if flag not in sys.argv:
        return dflt
    i = sys.argv.index(flag) + 1
    # 값이 없거나 다음이 플래그면 기본값 — bat 에서 날짜가 비면 인자가 밀린다
    if i >= len(sys.argv) or sys.argv[i].startswith("--"):
        return dflt
    return sys.argv[i]


def _child_env(**extra):
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", **extra)


# ── 실행 이력 — 중단돼도 '어디까지 갔는지'가 남아야 원인을 안다 ──────────
# AF32 산출물 표식(D20) — 읽는 쪽(화면)은 이 표식이 있는 last_run.json 만 믿는다. PC 이름 같은 식별자는 싣지 않는다.
RUN = {"product": lmname.PRODUCT, "stages": []}
RUN_T0 = {"t": None}            # 이번 실행의 시작 시각(초) — 걸린 시간 셈에만. last_run.json 에는 날짜만 쓴다(D10)


def _today():
    r"""report\ 에 남기는 실행 날짜('YYYY-MM-DD' — 시각은 남기지 않는다 · D10)."""
    return time.strftime("%Y-%m-%d")


def _no_clock(o, depth=0):
    r"""report\last_run.json 에 싣는 글(단계 note · 수집기 구조 줄 · counts)의 하루 중 시각 → [시각](privacy.mask_clock · D10).
    수집기가 화면에서 옮긴 시각(못 읽은 일정 막대 꼴 등)이 report\ 에 남지 않게 — 수집기 출력 자체는 바꾸지 않는다."""
    import privacy
    if isinstance(o, str):
        return privacy.mask_clock(o)
    if depth < 8 and isinstance(o, dict):
        return {k: _no_clock(v, depth + 1) for k, v in o.items()}
    if depth < 8 and isinstance(o, list):
        return [_no_clock(v, depth + 1) for v in o]
    return o


def record(name, ok, sec=0.0, note="", rc=None, reason="", counts=None, census=""):
    r"""단계 결과를 report\last_run.json 에 즉시 반영 (강제 종료돼도 흔적 보존).
    수집기 단계는 rc·reason·counts(짧은 숫자만)도 싣는다 — '불가' 사유는 실측 전까지 '의심'으로 적는다.
    census = 수집기가 찍은 화면 구조 한 줄(웹 경로) — 수집 진단 화면이 note 아래에 그대로 보여 준다.
    report\ 아래에는 날짜만 둔다(D10) — note·census·counts 의 시각은 [시각] 으로 가린다."""
    RUN["stages"] = [x for x in RUN["stages"] if x["name"] != name]
    ent = {"name": name, "ok": bool(ok), "sec": round(sec, 1), "note": _no_clock((note or "")[:300])}
    if census:
        ent["census"] = _no_clock(str(census)[:820])
    if rc is not None:
        ent.update(rc=int(rc), reason=str(reason or "")[:120], counts=_no_clock(collect_status.compact(counts)))
    RUN["stages"].append(ent)
    _save_run()


def _save_run():
    r"""RUN 을 report\last_run.json 에 쓴다(실패는 조용히 — 기록이 실행을 막지 않는다). 표식 "product" 는 늘 싣는다(D20)."""
    try:
        rep_dir = REPORT_DIR["p"]
        os.makedirs(rep_dir, exist_ok=True)
        with open(os.path.join(rep_dir, "last_run.json"), "w", encoding="utf-8") as f:
            json.dump(dict(RUN, product=lmname.PRODUCT), f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def run_collector(name, cmd, timeout=420, src="", led=None):
    r"""수집기 한 단계 → 해석한 상태 dict(collect_status.parse — rc·reason·counts·ranges·ok).
    · core\proc.run_step: Job(KILL_ON_JOB_CLOSE·BREAKAWAY_OK)으로 감싸 시간 초과 때 손자까지 정리하고,
      60초마다 '진행 중' 줄을 낸다(화면의 정체 감지). 전용 Edge 는 Job 에서 이탈해 띄워지므로 산다.
    · 마지막 줄 AF32STATUS 를 읽는다. 화면·last_run.json 에는 그 앞의 사람용 줄과 rc·사유를 쓴다.
    · led(원장)를 주면 ranges 를 일자×축 원장에 반영하고 바로 저장한다(강제 종료돼도 흔적 보존)."""
    print(f"\n── {name}")
    t0 = time.time()
    rc, tail, how = _RUN_STEP(cmd, timeout, name)
    st = collect_status.parse(tail, rc, src=src, how=how)
    for ln in st["lines"][-12:]:
        print("   " + ln)
    if st["rc"] or st["reason"]:
        print("   → " + collect_status.describe(st))
    record(name, st["ok"], time.time() - t0, collect_status.note(st),
           rc=st["rc"], reason=st["reason"], counts=st["counts"], census=collect_status.census_line(st))
    if led is not None:
        led.apply(st)
        led.save()
    return st


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            o = json.load(f)
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def _n(v):
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


def _months(a, b):
    try:
        return max(1, (date.fromisoformat(b) - date.fromisoformat(a)).days // 30 + 1)
    except (TypeError, ValueError):
        return 1


def _truthy(v):
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


def _yday(d1):
    """min(d1, 어제) — Copilot·'전 기간 확인' 판정은 아직 진행 중인 오늘을 빼고 본다"""
    y = (date.today() - timedelta(days=1)).isoformat()
    return d1 if d1 < y else y


def channels(c):
    """이번 실행에 쓰는 수집 경로(collect.channels ⊂ com·owa·copilot — afcfg 가 정리한 값)."""
    ch = afcfg.get(c, "collect.channels")
    return [x for x in (ch if isinstance(ch, list) else []) if x in afcfg.CHANNELS]


def _only(gaps, flag):
    """원장 공백 → 수집기 종류 인자(메일·일정 둘 다 비면 [] = 둘 다)"""
    m = bool(gaps.get("mail_in") or gaps.get("mail_out"))
    k = bool(gaps.get("cal"))
    if (m and k) or not (m or k):
        return []
    return [flag, "mail" if m else "cal"]


def _edge_rc2(st, state, name, what):
    """웹 경로 rc 2(로그인) — 이 실행의 남은 웹 경로는 건너뛴다(login_pending). 로그인은 사람이 1회."""
    if st.get("rc") != 2:
        return
    state["login_pending"] = True
    record(name, False, 0.0,
           f"로그인 필요 — 전용 Edge 창(Copilot 과 같은 창)의 {what} 탭에서 회사 계정을 1회 선택/로그인한 뒤 다시 실행"
           + (f" ({st.get('reason')})" if st.get("reason") else ""), rc=2, reason=st.get("reason"), counts=st.get("counts"))


def _skip_login(name):
    record(name, True, 0.0, "건너뜀 — 이번 실행에서 웹 경로가 로그인을 기다리는 중(login_pending · 전용 Edge 창에서 로그인 1회)")


# ── G1(수집 직후 정제) — Outlook 앱 원자료 → 정제 파일 ─────────────────────────────────────────────────
def raw_dir(data):
    r"""Outlook 앱 수집기의 원자료 폴더 data\outlook\raw(§5.0 — 정제한 뒤 바로 지운다)."""
    return os.path.join(data, "outlook", "raw")


def _raw_left(data):
    r"""data\outlook\raw 바로 아래의 보통 파일 경로 목록(retention.raw_left — 폴더·연결은 보지 않는다)."""
    return retention.raw_left(os.path.dirname(os.path.abspath(data)))


def drop_raw(data):
    r"""정제하지 않고 원자료 폴더의 파일을 모두 지운다(시작 거부로 멈출 때·정제 뒤 남은 것 — 원자료는 남기지 않는다)
    → 지운 수(retention.drop_raw — 화면·강제 종료·매일 정리와 같은 함수).
    다른 사용자의 자료(D17 — 시작 확인의 other_user)에는 부르지 않는다: 그 자료는 본인이 화면·AgentFinder32.bat 에서 고를 때만 지운다."""
    return retention.drop_raw(os.path.dirname(os.path.abspath(data)))


# ── 실행 중 시작 확인 다시 하기(L2-06) ────────────────────────────────────────────────────────
def _drop_run_writes(data):
    r"""실행 중 시작 확인에 걸렸을 때(그 사이 [모두 지우기]가 시작됨 · 설치 정보 사라짐) — 이 실행이 시작 확인을 지난 뒤 쓴 것을
    지운다 → 지운 수.
      · Outlook 앱 원자료(data\outlook\raw\* — 이 실행이 모은 것이다: 지난 실행의 것은 시작할 때 정제하거나 지웠다)
      · 그 뒤에 바뀐 수집·분석 파일: data\outlook\**·data\cache\**(연결 폴더에는 들어가지 않는다) · data\coverage_ledger.json ·
        report\ 바로 아래(실행 기록 last_run.json 포함)
    앞 단계의 실행 기록(수집 건수 등)도 비운다 — 이 뒤에 남기는 last_run.json 에는 멈춘 단계와 까닭만 들어간다. 시작 확인을 지나기
    전(RUN_T0 없음)에는 아무것도 하지 않는다 — 그때의 파일은 이 실행의 것이 아니다. 시작 전의 파일은 건드리지 않는다([모두 지우기]가
    시작됐다면 그것이 지운다)."""
    t0 = RUN_T0.get("t")
    if not t0:
        return 0
    RUN["stages"] = []
    n = drop_raw(data)
    since = float(t0)
    root = os.path.dirname(os.path.abspath(data))

    def mine(p):
        try:
            st = os.lstat(p)
        except OSError:
            return False
        return st.st_mtime >= since

    tops = [(os.path.join(data, "outlook"), True), (os.path.join(data, "cache"), True),
            (os.path.join(root, "report"), False)]
    if retention._link_dir(data):
        tops = tops[2:]
    for top, deep in tops:
        if not os.path.isdir(top) or retention._link_dir(top):
            continue
        for cur, dirs, files in os.walk(top, onerror=lambda e: None):
            dirs[:] = [d for d in dirs if deep and not retention._link_dir(os.path.join(cur, d))]
            for fn in files:
                p = os.path.join(cur, fn)
                if mine(p) and retention._rm_file(p):
                    n += 1
    led = os.path.join(data, coverage.FILE_NAME)
    if not retention._link_dir(data) and os.path.isfile(led) and mine(led) and retention._rm_file(led):
        n += 1
    return n


def gate_code(reason):
    """시작 확인이 막은 까닭(consent.ConsentRequired.reason) → 이 실행의 종료 코드. "other_user"(다른 사용자의 자료 · 주인을
    모르는 자료)는 4, 그 밖("withdrawn" — [모두 지우기]가 끝나지 않음)은 3."""
    return EXIT_SETUP if reason == "other_user" else EXIT_CONSENT


def gate_reason():
    """지금 시작 확인(consent.require — 이 폴더의 자료가 이 사용자의 것인가 · [모두 지우기]가 끝나지 않았나)이 막는 까닭
    → (reason, 한국어 한 줄) | None(막지 않는다). 이 확인은 설정에 달려 있지 않다 — 설정 파일을 다시 읽지 않는다."""
    try:
        consent.require(ROOT, CFG.get("c") or {})
    except consent.ConsentRequired as e:
        return e.reason, e.message
    return None


def gate_refused(data, reason="", msg=""):
    r"""실행 중 시작 확인에 걸려 멈춘다 → RunStop(던지지 않고 돌려준다 · 단계 이름 CONSENT_STAGE). 이 실행이 쓴 수집·분석 파일과
    원자료를 지운다(_drop_run_writes): 시작할 때는 이 사용자의 자료였으므로 그 뒤에 쓴 파일은 이 실행의 것이다 — 지금 '주인 모름'
    으로 보여도(그 사이 설치 정보가 지워졌다) 지운다.
    reason·msg = 부르는 쪽이 아는 까닭과 문장(자식 단계가 마지막 줄 JSON 으로 알린 것). 비어 있으면 지금 시작 확인에 묻고(gate_reason),
    그것이 지나가면(자식이 확인하지 못했거나 그 사이 풀렸다) GATE_CHILD_MSG 와 종료 코드 3."""
    if not (reason and msg):
        now = gate_reason() or ("", "")
        reason, msg = reason or now[0], msg or now[1]
    n = _drop_run_writes(data)
    note = (msg or GATE_CHILD_MSG) + (f" — 이 실행이 쓴 파일 {n}개를 지웠습니다" if n else "")
    return RunStop(gate_code(reason), note, CONSENT_STAGE)


def recheck_consent(data, stage):
    r"""단계 직전에 시작 확인을 다시 한다(함수 이름은 예전 그대로) → 그대로면 None. 시작한 뒤 [모두 지우기]가 시작됐거나(화면·
    다른 창) 설치 정보가 사라졌으면 이 실행이 쓴 수집·분석 파일과 원자료를 지우고(gate_refused) RunStop(3 · 주인을 모르게 됐으면 4)."""
    now = gate_reason()
    if now is None:
        return None
    e = gate_refused(data, now[0], now[1])
    record(stage, False, 0.0, e.message)
    raise e


def g1_note(res):
    """G1 결과 한 줄(숫자만) — '남김 받은 메일 N · 보낸 메일 M · 회의 K · 뺀 항목 X(사외 a · …)'."""
    k = (res or {}).get("kept") or {}
    ex = {a: _n(b) for a, b in ((res or {}).get("excluded") or {}).items() if _n(b)}
    s = f"남김 받은 메일 {_n(k.get('mail_in'))} · 보낸 메일 {_n(k.get('mail_out'))} · 회의 {_n(k.get('meetings'))}"
    if ex:
        s += f" · 뺀 항목 {sum(ex.values())}(" + " · ".join(f"{EXCL_KO.get(a, a)} {b}" for a, b in ex.items()) + ")"
    oop = _n((res or {}).get("out_of_period"))
    if oop:
        s += f" · 기간 밖 {oop}"
    return s


def g1_com(c, data, d0, d1, name="개인정보 정제(G1) — Outlook 앱"):
    r"""Outlook 앱 원자료(data\outlook\raw\mail_com.csv·cal_com.csv·com_manifest.json) → core\mailmerge.g1_com(privacy.g1_file ·
    이번에 읽은 달 구간만 옛 행과 바꿔 합침) → data\outlook\src\mail_com.csv·cal_com.csv. 원자료·구간 표는 결과와 상관없이
    지우고, 원자료 폴더에 남은 그 밖의 파일도 지운다(원자료는 남기지 않는다).
    제한 고객 목록 없음·사내 도메인 없음(privacy.SetupRefused)은 RunStop(4). → g1_com 결과 dict | None(정제할 원자료 없음).
    정제 직전에 시작 확인을 다시 한다 — 수집하는 사이 [모두 지우기]가 시작됐으면 원자료를 정제하지 않고 지운 뒤 RunStop(3)."""
    import mailmerge
    import privacy
    if _raw_left(data):
        recheck_consent(data, name)
    t0 = time.time()
    try:
        res = mailmerge.g1_com(ROOT, c, period=(d0, d1), tag="com")
    except privacy.SetupRefused as e:
        drop_raw(data)
        record(name, False, time.time() - t0, e.message)
        raise RunStop(EXIT_SETUP, e.message) from None
    except Exception as e:  # noqa: BLE001 - 정제 실패가 실행을 멈추지 않는다(그 달들은 다음 실행이 다시 읽는다)
        drop_raw(data)
        note = f"정제하지 못했습니다({type(e).__name__}) — 원자료는 지웠고 그 달들은 다음 실행이 다시 읽습니다"
        print(f"\n── {name}\n   [!] {note}")
        record(name, False, time.time() - t0, note)
        return None
    drop_raw(data)
    if not res.get("ran"):
        if res.get("error"):
            note = "구간 표 없이 남은 원자료 — 합치지 않고 지웠습니다(그 달들은 다음 실행이 다시 읽습니다)"
            print(f"\n── {name}\n   {note}")
            record(name, False, time.time() - t0, note)
        return None
    note = g1_note(res) + ("" if res.get("committed") else " · 완료 표는 확정하지 않음(다음 실행이 그 달을 다시 읽습니다)")
    print(f"\n── {name}\n   {note}")
    record(name, True, time.time() - t0, note)
    return res


def recover_raw(c, data, d0, d1):
    r"""시작 때 — 지난 실행이 중간에 멈춰 남긴 원자료가 있으면 G1 으로 정제하고 지운다."""
    if not _raw_left(data):
        return None
    print("\n── 지난 실행이 남긴 수집 원자료 — 정제(G1)한 뒤 지웁니다")
    return g1_com(c, data, d0, d1, name="개인정보 정제(G1) — 남은 원자료")


def check_rules(c):
    r"""G1 규칙(privacy 설정·제한 고객 목록·제목 저장·일정 본문)이 지난 정제 때와 다르면 지난 정제 파일·공용 파일·원장을 지운다
    (core\mailmerge.check_rules — 새 규칙으로 다시 모은다). → 지웠나(그러면 이번 실행은 수집부터 한다)."""
    import mailmerge
    try:
        r = mailmerge.check_rules(ROOT, c)
    except Exception as e:  # noqa: BLE001 - 규칙 확인 실패가 실행을 막지 않는다(다음 시작 때 다시)
        print(f"   (정제 규칙 확인 건너뜀: {type(e).__name__})")
        return False
    if not r.get("changed"):
        return False
    note = (f"정제 규칙(개인정보 설정·제한 고객 목록 등)이 바뀌어 지난 정제 자료 {len(r.get('deleted') or [])}개를 지웠습니다"
            " — 새 규칙으로 다시 모읍니다")
    print(f"\n[!] {note}")
    record("정제 규칙 바뀜", True, 0.0, note)
    return True


def check_setup(st, data):
    r"""수집기가 시작을 거부했나(AF32STATUS 사유 R-CONSENT · R-NORESTRICTED · R-NODOMAIN) → 원자료를 지우고 RunStop(3·4).
    R-CONSENT = 수집기의 시작 확인(내 자료가 아님 · 지우는 중 · 확인하지 못함). 여기서 다시 물어 지금도 막히면 이 실행이 쓴 파일까지
    지우고 그 까닭으로 멈춘다(gate_refused). 지나가면(수집기가 확인하지 못했다 — 예 확인할 파이썬이 없음) 원자료만 지우고 3."""
    rs = set(st.get("reasons") or [])
    if not rs & {R_CONSENT, R_NORESTRICTED, R_NODOMAIN}:
        return
    import privacy
    drop_raw(data)
    if R_CONSENT in rs:
        now = gate_reason()
        if now:
            raise gate_refused(data, now[0], now[1])
        raise RunStop(EXIT_CONSENT, GATE_CHILD_MSG, CONSENT_STAGE)
    if R_NORESTRICTED in rs:
        raise RunStop(EXIT_SETUP, privacy.RESTRICTED_MSG)
    raise RunStop(EXIT_SETUP, privacy.INTERNAL_MSG)


def merge_mail(c, data, led, d0, d1):
    r"""출처별 정제 파일 → data\outlook\mail.csv·calendar.csv·mail_source.json(core\mailmerge — 분석이 읽는 공용 파일은 여기만
    쓴다). 기간(d0~d1) 밖 행은 공용 파일에 넣지 않고 출처 파일·원장에서도 지운다. collect.channels 밖의 출처 파일은 읽지 않는다.
    병합 직전에 시작 확인을 다시 한다(recheck_consent — 걸리면 이 실행이 쓴 정제 파일을 지우고 RunStop)."""
    import mailmerge
    recheck_consent(data, "메일·일정 병합")
    t0 = time.time()
    info = mailmerge.merge(os.path.join(data, "outlook", "src"), os.path.join(data, "outlook"),
                           verified=(led.is_verified if led is not None else None), period=(d0, d1),
                           cfg=c, channels=channels(c), ledger=led)
    if info.get("error") == "no_sources":
        print("\n── 메일·일정 병합 — 정제된 출처 파일이 없습니다(이번 실행에서 남긴 메일·일정 없음)")
        record("메일·일정 병합", False, time.time() - t0, "정제된 출처 파일 없음 — 수집 경로의 단계 기록을 확인하세요")
        return info
    srcs = " · ".join(f"{k} {v}" for k, v in sorted((info.get("sources") or {}).items(), key=lambda kv: -kv[1]))
    note = (f"메일 {info.get('mail', 0)}건({srcs or '없음'}) · 일정 {info.get('calendar', 0)}건 · 중복 제외 {info.get('dup', 0)}"
            + (f" · Copilot 확인 행 {info['copilot']}" if info.get("copilot") else "")
            + (f" · {info['error']}" if info.get("error") else ""))
    print(f"\n── 메일·일정 병합 (출처별 → mail.csv·calendar.csv)\n   {note}")
    record("메일·일정 병합", bool(info.get("ok")), time.time() - t0, note)
    return info


def write_summary(c, data, d0, d1, clamp, rcs, info):
    r"""data\outlook\collect_summary.json(§5.3 — 이 PC 안에서만: 화면의 수집·제외 현황 · 개인 리포트) — mailmerge.write_summary.
    rcs = {경로: 이번 실행의 종료 코드 | None(돌지 않음)}. 경로별 G1 건수는 mailmerge 가 data\outlook\src\g1_<경로>.json 에서 모은다."""
    try:
        import mailmerge
        o = mailmerge.write_summary(os.path.join(data, "outlook"), period=(d0, d1),
                                    clamp=(clamp if isinstance(clamp, dict) and clamp.get("clamped") else None),
                                    channels=dict(rcs), g1_counts=None, merge_info=(info if isinstance(info, dict) else {}))
    except Exception as e:  # noqa: BLE001 - 요약을 못 써도 분석은 계속한다(화면이 그 칸을 비워 둔다)
        record("수집 요약", False, 0.0, f"collect_summary.json 을 쓰지 못했습니다({type(e).__name__}: {str(e)[:80]})")
        return None
    note = g1_note(o if isinstance(o, dict) else {})
    print(f"\n── 수집 요약 (data\\outlook\\collect_summary.json — 이 PC 안에서만)\n   {note}")
    record("수집 요약", True, 0.0, note)
    return o


def _axis_ko(ax):
    return {"mail_in": "받은 메일", "mail_out": "보낸 메일", "cal": "일정"}.get(ax, ax)


def _owa_read_days(led, gaps):
    """받은 메일을 확인하지 못한 날 가운데 Outlook 웹이 읽은 날(그날의 보낸 메일 칸이 '읽음')이 있나."""
    for ax in coverage.SRC_BLIND.get("owa", ()):
        for a, b in gaps.get(ax) or []:
            day, end = date.fromisoformat(a), date.fromisoformat(b)
            while day <= end:
                if led.src_status(day.isoformat(), "mail_out", "owa") in coverage.VERIFIED:
                    return True
                day += timedelta(days=1)
    return False


def report_gaps(led, d0, d1, axes, name):
    """원장의 남은 공백(오늘 제외)을 화면·last_run.json 에 — 확인하지 못한 날은 '없음'이 아니라 '아직 모름'이다."""
    hi = _yday(d1)
    if hi < d0:
        return
    g = led.gaps(axes, d0, hi)
    parts = [f"{_axis_ko(ax)} {coverage.n_days(rs)}일" for ax, rs in g.items() if rs]
    na = [_axis_ko(ax) for ax in axes if led.na.get(ax)]
    if not parts:
        note = "기간의 모든 날을 확인했습니다(오늘 제외)" + (f" · 해당 없음: {', '.join(na)}" if na else "")
    else:
        note = (f"확인하지 못한 날 {' · '.join(parts)} — 그 날의 메일·일정은 아직 확인하지 못했습니다"
                "(의심·실측 전, 다음 실행이 다시 읽습니다)" + (f" · 해당 없음: {', '.join(na)}" if na else ""))
        if _owa_read_days(led, g):
            note += " · " + OWA_BLIND_NOTE
    print(f"   [{name}] {note}")
    record(name, not parts, 0.0, note)


def copilot_witness_jobs(rm, rc):
    r"""Copilot 메일·일정 확인 단계의 프로세스 목록 → [(종류 꼬리 ''|'mail'|'cal', 추가 인자, 물을 날 수)].
    메일(rm)·일정(rc) 모두 물을 날이 있으면 구간이 달라도 **한 프로세스**로 부른다(--ranges 메일 · --ranges-cal 일정) —
    그 프로세스의 채팅 하나를 메일·일정이 이어 쓴다(채팅이 늘어나지 않게). 한쪽만 있으면 그 종류만(--only)."""
    if rm and rc:
        if rm == rc:
            return [("", ["--ranges", coverage.fmt_ranges(rm)], coverage.n_days(rm))]
        return [("", ["--ranges", coverage.fmt_ranges(rm), "--ranges-cal", coverage.fmt_ranges(rc)],
                 coverage.n_days(rm) + coverage.n_days(rc))]
    return [(k, ["--ranges", coverage.fmt_ranges(r), "--only", k], coverage.n_days(r))
            for k, r in (("mail", rm), ("cal", rc)) if r]


# Outlook 웹은 받은 메일을 확인하지 못한다 — 목록이 받는 사람을 보여 주지 않아 그 행을 모두 뺀다(D7 · coverage.SRC_BLIND).
OWA_BLIND_SKIP = "건너뜀 — 남은 것은 받은 메일뿐입니다(Outlook 웹은 받는 사람을 볼 수 없어 받은 메일을 남기지 않습니다)"
OWA_BLIND_NOTE = ("Outlook 웹이 읽은 날의 받은 메일은 남기지 않습니다(받는 사람을 볼 수 없음 — 받은 메일은 Outlook 앱이나 "
                  "Copilot 으로 채웁니다)")


def mail_fallbacks(c, d0, d1, data, col, led, state, rcs):
    r"""Outlook 앱(COM) 다음 — 원장(일자×축)에 확인하지 못한 날이 남으면
      ① Outlook 웹(collect.channels 에 owa · --no-mail-web 아님) — 그 날의 범위만(--from·--to = 공백의 처음~끝, --only 메일|일정).
         보낸 메일·일정에 확인하지 못한 날이 있을 때만 돈다 — Outlook 웹은 받은 메일을 확인하지 못한다(목록에 받는 사람이 없어 그
         행을 뺀다 · coverage.SRC_BLIND). Outlook 웹이 읽은 날도 받은 메일은 확인하지 못한 날로 남아 ② 가 묻는다.
      ② M365 Copilot(collect.channels 에 copilot · --no-mail-copilot 아님) — 남은 날만 --ranges(Copilot 은 확인용 —
         '읽음'을 만들지 않고, 이미 답한 날은 다시 묻지 않는다).
    두 수집기는 항목마다 privacy.g1_row 로 정제해 data\outlook\src\mail_<출처>.csv·cal_<출처>.csv 에 쓴다(원자료 파일 없음).
    한 실행에서 웹 경로가 rc 2(로그인)면 남은 웹 경로는 login_pending 으로 건너뛴다(state). rcs[경로] = 이번 실행의 종료 코드."""
    chans = channels(c)
    src_dir = os.path.join(data, "outlook", "src")
    os.makedirs(src_dir, exist_ok=True)
    gaps = led.gaps(MAIL_AXES, d0, d1)
    blind = coverage.SRC_BLIND.get("owa", ())           # Outlook 웹이 확인하지 못하는 축(받은 메일) — 그 공백으로는 웹을 돌리지 않는다
    only_blind = any(gaps.get(ax) for ax in blind)
    gaps = {ax: rs for ax, rs in gaps.items() if ax not in blind}
    sp = coverage.span(gaps)
    only_blind = only_blind and not sp
    if _truthy(afcfg.get(c, "collect.mailAllPaths")):
        gaps, sp = {}, (d0, d1)            # collect.mailAllPaths — 앞 경로가 기간을 확인했어도 웹을 기간 전체로 돌려 합친다
    name2 = "Outlook 웹 (전용 Edge — 확인하지 못한 날만)"
    if "owa" not in chans:
        record(name2, True, 0.0, "건너뜀 — collect.channels 에 owa 가 없습니다")
    elif "--no-mail-web" in sys.argv:
        record(name2, True, 0.0, "건너뜀(--no-mail-web)")
    elif not sp:
        record(name2, True, 0.0, OWA_BLIND_SKIP if only_blind
               else "건너뜀 — 원장에 확인하지 못한 날 없음(Outlook 앱이 기간을 확인)")
    elif state.get("login_pending"):
        _skip_login(name2)
    else:
        EDGE["used"] = True
        st2 = run_collector(name2, [sys.executable, os.path.join(col, "Get-OutlookWeb.py"), "--from", sp[0], "--to", sp[1],
                                    "--out-dir", src_dir, "--tag", "owa"] + _only(gaps, "--only"),
                            180 + 150 * _months(sp[0], sp[1]), src="owa", led=led)
        check_setup(st2, data)
        rcs["owa"] = st2.get("rc")
        _edge_rc2(st2, state, name2, "Outlook")
    name3 = "M365 Copilot 메일·일정 (남은 날만 — 확인용)"
    if "copilot" not in chans:
        record(name3, True, 0.0, "건너뜀 — collect.channels 에 copilot 이 없습니다")
        return
    if "--no-mail-copilot" in sys.argv:
        record(name3, True, 0.0, "건너뜀(--no-mail-copilot)")
        return
    if state.get("login_pending"):
        _skip_login(name3)
        return
    # 오늘은 묻지 않는다 — 기간 끝은 늘 어제다(period.clamp)
    g3 = led.gaps(MAIL_AXES, d0, _yday(d1), witness="copilot") if _yday(d1) >= d0 else {}
    rm = coverage.union(g3, ("mail_in", "mail_out"))
    rc_ = g3.get("cal") or []
    jobs = copilot_witness_jobs(rm, rc_)
    if not jobs:
        record(name3, True, 0.0, "건너뜀 — 남은 날 없음(또는 이미 Copilot 이 답한 날)")
    for kind, extra, ndays in jobs:
        if state.get("login_pending"):
            _skip_login(name3)
            break
        EDGE["used"] = True
        nm = name3 + (f" — {'메일' if kind == 'mail' else '일정'}" if kind else "")
        st3 = run_collector(nm, [sys.executable, os.path.join(col, "Get-MailViaCopilot.py"), "--from", d0, "--to", d1]
                            + extra + ["--out-dir", src_dir, "--tag", "copilot"],
                            300 + 600 * 2 * max(1, ndays // 30 + 1), src="copilot", led=led)
        check_setup(st3, data)
        rcs["copilot"] = st3.get("rc")
        _edge_rc2(st3, state, nm, "Copilot")


def _outlook_budget(c, d0, d1):
    """Outlook 앱 수집 한 회차의 시간 예산(초) — config.outlookBudgetSec(0 = 자동). 자동은 240 + 60×개월(360~900).
    수집기가 달 단위로 이어서 읽으므로 예산 안에 못 끝내도 다음 회차·다음 실행이 남은 달을 잇는다."""
    months = max(1, (date.fromisoformat(d1) - date.fromisoformat(d0)).days // 30 + 1)
    try:
        v = int(afcfg.get(c, "outlookBudgetSec") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else max(360, min(900, 240 + 60 * months))


def collect_outlook(c, d0, d1, data, ps, col, led, rcs):
    r"""Outlook 앱(COM) — 내 기본 사서함의 메일·일정. 기간의 달을 최신 달부터 읽고, 예산에 닿아 못 읽은 달이 남으면
    진행이 있는 한 같은 실행 안에서 최대 2회 더 이어서 읽는다(회차마다 완료된 달은 건너뛰므로 앞으로만 간다).
    수집기는 원자료를 data\outlook\raw\mail_com.csv·cal_com.csv 에 쓰고(§5.0) 상태를 -OutDir(data\outlook\src)의
    mail_source_com.json 에 둔다. 회차가 끝날 때마다 바로 g1_com(mailmerge.g1_com — privacy.g1_file)이 정제하고 원자료를 지운다.
    종료 코드: 0 정상 · 1 기간 0행 · 3 건너뜀·실패(사유)."""
    budget = _outlook_budget(c, d0, d1)
    src_dir = os.path.join(data, "outlook", "src")
    os.makedirs(src_dir, exist_ok=True)
    src_p = os.path.join(src_dir, "mail_source_com.json")
    ok, prev_unc, src = False, None, {}

    def _fresh_src(t_start):
        """이번 회차가 쓴 mail_source_com.json 만 믿는다 — 건너뜀·실패·시간 초과 뒤에는 지난 실행의 파일이 남아 있다"""
        mt = _mtime(src_p)
        return (_read_json(src_p) or {}) if (mt is not None and mt >= t_start - 2) else {}

    for i in range(3):
        name = ("Outlook 앱 메일·일정 (클래식 Outlook 을 켜 두세요)" if i == 0
                else f"Outlook 앱 메일·일정 이어서 수집 {i + 1}/3 (남은 달)")
        # 2회차부터는 -NoRefresh — 1회차가 이미 읽은 최신·재수집 달을 건너뛰고 못 읽은 달만 잇는다
        t_pass = time.time()
        st = run_collector(name, ps + [os.path.join(col, "Get-OutlookData.ps1"), "-From", d0, "-To", d1,
                                       "-BudgetSec", str(budget), "-OutDir", src_dir, "-Tag", "com"]
                           + (["-NoRefresh"] if i else []), budget + 120, src="com", led=led)
        check_setup(st, data)
        rcs["com"] = st.get("rc")
        g1_com(c, data, d0, d1)                          # 수집기가 끝나자마자 — 원자료는 여기서 정제되고 지워진다
        ok = st["ok"]
        src = _fresh_src(t_pass)
        if st["rc"] not in (0, 1) or src.get("source") != "com" or src.get("coverage_complete", True):
            break
        unc = list(src.get("uncovered_months") or [])
        partial = list(src.get("partial_months") or [])
        if prev_unc is not None and len(unc) >= len(prev_unc) and not partial:
            print("   (진행이 없어 이어서 수집을 멈춥니다 — Outlook 이 느리거나 응답하지 않습니다)")
            break
        prev_unc = unc
        print(f"   읽지 못한 달 {len(unc)}개({', '.join(unc[:6])}{' …' if len(unc) > 6 else ''}) — 이어서 읽습니다")
    if src.get("source") == "com":
        ri = list(src.get("refresh_incomplete") or [])
        if ri:
            print(f"   [!] 다시 읽기가 끊긴 달 {', '.join(ri)} — 지난 수집분을 그대로 두었습니다(새 메일·일정 변경은 다음 실행에서)")
            record("Outlook 앱 다시 읽기", False, 0.0, f"끊긴 달: {', '.join(ri)} — 지난 수집분 유지, 다음 실행에서 다시")
        if not src.get("coverage_complete", True):
            unc = list(src.get("uncovered_months") or [])
            print(f"   [!] 메일·일정을 읽지 못한 달 {len(unc)}개: {', '.join(unc)} — 다음 [분석 실행]이 이어서 읽습니다"
                  " (그동안 이 달들의 메일·회의는 과제 발굴 근거에 들어가지 않습니다)")
            record("Outlook 앱 수집 범위", False, 0.0,
                   f"읽지 못한 달 {len(unc)}개: {', '.join(unc)} — 다음 실행이 이어서 수집(그 달의 메일·회의는 아직 빠짐)")
    return ok


def collect(c, d0, d1, data, clamp):
    r"""수집 전체(§4): Outlook 앱 → G1 → Outlook 웹 → Copilot → 병합 → 수집 요약 → 전용 Edge 의 Outlook·M365 사이트 자료 지우기.
    사내 메일 도메인은 수집 경로가 붙은 뒤에 확인한다 — 끝내 모르면 RunStop(4). → 병합 정보 dict."""
    import privacy
    ps = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    col = os.path.join(ROOT, "collect")
    chans = channels(c)
    if not chans:
        raise RunStop(EXIT_SETUP, "수집 경로가 없습니다 — 설정의 collect.channels 에 com·owa·copilot 중 하나 이상을 두세요")
    led = open_ledger(c, data)
    rcs = dict.fromkeys(chans)
    if "com" in chans:
        collect_outlook(c, d0, d1, data, ps, col, led, rcs)
    else:
        record("Outlook 앱 메일·일정", True, 0.0, "건너뜀 — collect.channels 에 com 이 없습니다")
    mail_fallbacks(c, d0, d1, data, col, led, STATE, rcs)
    led.save()
    attached = any(rc in (0, 1) for rc in rcs.values())      # 수집 경로가 하나라도 내 사서함에 붙었나
    if attached and not privacy.internal_domains(c, privacy.me_list(data)):
        drop_raw(data)
        raise RunStop(EXIT_SETUP, privacy.INTERNAL_MSG)
    info = merge_mail(c, data, led, d0, d1)
    report_gaps(led, d0, d1, MAIL_AXES, "메일·일정 원장(확인하지 못한 날)")
    led.save()
    write_summary(c, data, d0, d1, clamp, rcs, info)
    clear_edge_site_data("collect_end")
    return info


# 다시 보내도 같은 벽에 닿는 중단 갈래(자식 마지막 줄 JSON 의 stop_kind) — 재시도하지 않는다.
# budget(시간 예산) · gate(개인정보 관문) · login/fatal(사람이 손대야 풀림) · throttle(Copilot 사용량 제한)
NO_RETRY_KINDS = ("budget", "gate", "login", "fatal", "throttle")
AI2_STAGES = ("agentic.py", "flow.py")    # 판정 뒤 Copilot 단계 — 지난 결과 이어받기(--carry)·긴 재시도 대기

# Copilot 사용량 제한(「요청이 너무 많음」)으로 이번 실행의 AI 단계를 멈춘 경우. 어느 단계든 강한 제한에 닿으면 이 실행의
# 표식(AF32_RUN_ID — start_run_id)과 함께 기록하고(copilot_auto.note_throttle), 같은 실행의 뒤 단계는 Copilot 에 보내지 않고 바로
# 접는다(copilot_auto.run_stopped). run.py 는 그것을 진행 로그에 한 줄로 알리고(실행에 1회) 단계 기록에 사유를 싣는다 — 멈춘 단계에는
# THR_LINE 을 앞에, 멈춘 뒤에 돈 단계에는 일반 실패 대신 THR_SKIP. 개인 리포트는 그대로 만든다.
# 한 실행에서 Copilot 때문에 쉬는 시간은 모든 단계를 합쳐 copilotAuto.runWaitMaxSec(기본 5분) 안이다(copilot_auto.run_wait_left).
THR_LINE = ("Copilot 사용량 제한(요청이 너무 많음) — 이번 실행의 AI 단계를 멈췄습니다. 여기까지의 결과는 지켰고, "
            "1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행]을 누르면 남은 것만 이어서 합니다.")
THR_SKIP = ("건너뜀 — Copilot 사용량 제한(요청이 너무 많음)으로 이번 실행의 AI 단계를 멈춰 Copilot 에 보내지 않았습니다 "
            "(지난 결과·규칙 결과 유지 · 1~2시간 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행])")
THR = {"said": False}          # THR_LINE 을 이 실행에서 이미 찍었나
_RUN_STOPPED = None            # 시험 주입 — None 이면 tools\copilot_auto.run_stopped
_RUN_WAIT_LEFT = None          # 시험 주입 — None 이면 tools\copilot_auto.run_wait_left
_ADD_RUN_WAIT = None           # 시험 주입 — None 이면 tools\copilot_auto.add_run_wait
RETRY_WAIT_MIN = 15            # 재시도 대기의 바닥(초) — 자식 프로세스를 다시 띄우기 전 숨 돌리기(쉬는 시간 합계와 무관한 몫)


def start_run_id():
    """이번 실행의 표식을 정해 AF32_RUN_ID 에 싣는다(자식 — 수집기·판정·정제·Agentic·업무 흐름이 물려받는다). 날짜 + PID + 임의
    값이라 실행마다 다르다(시각은 넣지 않는다 — last_run.json 에 남는다 · D10). 사용량 제한으로 멈춘 기록이 '이번 실행' 것인지 가르는 데만 쓴다."""
    rid = f"{time.strftime('%Y%m%d')}-{os.getpid()}-{os.urandom(3).hex()}"
    os.environ["AF32_RUN_ID"] = rid
    RUN["run_id"] = rid
    THR["said"] = False
    return rid


def run_throttled():
    """이번 실행이 Copilot 사용량 제한으로 AI 단계를 멈췄는가(copilot_auto.run_stopped) — 못 읽으면 False(멈추지 않은 것으로)."""
    try:
        fn = _RUN_STOPPED if _RUN_STOPPED is not None else _copilot_mod().run_stopped
        return bool(fn())
    except Exception:  # noqa: BLE001 - 기록을 못 읽어도 실행은 계속한다
        return False


def retry_wait_sec(want):
    """재시도 전에 쉴 초 — RETRY_WAIT_MIN(15초)을 넘는 대기는 이번 실행의 남은 쉬는 시간(copilot_auto.run_wait_left —
    copilotAuto.runWaitMaxSec)으로 줄인다(바닥 15초). 실행 표식이 없거나 못 읽으면 바라는 그대로."""
    if want <= RETRY_WAIT_MIN:
        return want
    try:
        fn = _RUN_WAIT_LEFT if _RUN_WAIT_LEFT is not None else _copilot_mod().run_wait_left
        left = float(fn())
    except Exception:  # noqa: BLE001 - 합계를 못 읽어도 실행은 계속한다
        return want
    return want if left >= want else max(RETRY_WAIT_MIN, int(left))


def note_retry_wait(sec):
    """방금 sec 초 쉬었다 — 이번 실행의 쉬는 시간 합계에 더한다(copilot_auto.add_run_wait). 기록 실패는 무시한다."""
    try:
        fn = _ADD_RUN_WAIT if _ADD_RUN_WAIT is not None else _copilot_mod().add_run_wait
        fn(sec)
    except Exception:  # noqa: BLE001
        pass


def say_throttle():
    """THR_LINE 을 진행 로그에 한 번 — 이미 찍었으면 False."""
    if THR["said"]:
        return False
    THR["said"] = True
    print(f"\n   [!] {THR_LINE}", flush=True)
    return True


def ai_note(before, note=""):
    """AI 단계(정제·Agentic·업무 흐름) 하나가 끝난 뒤의 기록 문구. before = 단계를 시작할 때 이미 사용량 제한으로 멈춰 있었나 —
    그 단계는 Copilot 에 보내지 않았으니 일반 실패 문구 대신 THR_SKIP. 이 단계에서 멈췄으면 THR_LINE 을 한 번 찍고 앞에 붙인다."""
    if before:
        return THR_SKIP
    if run_throttled():
        say_throttle()
        return THR_LINE + (f" · {note}" if note else "")
    return note


def ai_reserves(c, tot):
    r"""AI 단계 전체 마감(tot 분) 안에서 미리 떼어 두는 몫 → (업무 흐름 몫, Agentic AI 후보 몫) 분.
    업무 흐름 몫은 flowBudgetMin 과 전체의 40% 중 작은 쪽(최소 60분). Agentic 몫은 config.agenticReserveMin
    (없으면 전체의 10%를 15~30분으로) — 판정·정제가 마감을 다 쓰면 Agentic 이 15분 하한만 받아 업무 대부분을 보내지 못했다."""
    try:
        fb = float(c.get("flowBudgetMin", 120) or 0) or 120.0
    except (ValueError, TypeError):
        fb = 120.0
    flow_res = min(max(60.0, fb), max(60.0, tot * 0.4))
    try:
        ag = float(c.get("agenticReserveMin") or 0)
    except (ValueError, TypeError):
        ag = 0.0
    ag_res = ag if ag > 0 else min(30.0, max(15.0, tot * 0.1))
    return flow_res, ag_res


def start_ai_clock(c, tot, now=None):
    """--ai 시작 — AI 단계 전체 마감 기준(T0)과 선예약 몫을 정하고, 판정·정제가 쓸 마감을 AF32_AI_DEADLINE 에 싣는다.
    = T0 + (전체 − 업무 흐름 몫 − Agentic 몫). Agentic 직전(agentic_deadline)·flow 직전(전체)에 몫을 돌려준다.
    반환: (업무 흐름 몫, Agentic 몫, 판정·정제 몫) 분."""
    global _AI_T0, _AI_TOT_MIN
    flow_res, ag_res = ai_reserves(c, tot)
    _AI_T0, _AI_TOT_MIN = (time.time() if now is None else now), tot
    _AI_RES.update(flow=flow_res, ag=ag_res)
    pre = max(0.0, tot - flow_res - ag_res)
    os.environ["AF32_AI_DEADLINE"] = str(_AI_T0 + pre * 60.0)
    return flow_res, ag_res, pre


def agentic_deadline(now=None):
    """Agentic AI 후보 찾기 직전의 전체 마감(epoch 초) — 선예약한 Agentic 몫을 돌려준다.
    = max(T0 + (전체 − 업무 흐름 몫), 지금 + Agentic 몫). --ai 마감이 꺼져 있으면 None."""
    if _AI_T0 is None or not _AI_TOT_MIN:
        return None
    now = time.time() if now is None else now
    return max(_AI_T0 + (_AI_TOT_MIN - _AI_RES["flow"]) * 60.0, now + _AI_RES["ag"] * 60.0)


def consent_lost(stage):
    """방금 끝난 단계가 시작 확인(details.consent_gate — 마지막 줄 JSON code "no_consent" · reason other_user | withdrawn)에
    걸려 멈췄으면 이 실행이 쓴 파일을 지우고 RunStop(3 · 주인을 모르게 됐으면 4), 제한 고객 목록 없음(details.restricted_gate —
    code "no_restricted")으로 멈췄으면 RunStop(4). 시작할 때 확인했어도 그 사이 [모두 지우기]가 시작되거나 설치 정보·목록이
    지워지면 단계가 스스로 멈춘다 — 다시 보내지 않는다(함수 이름은 예전 그대로)."""
    code = str(LAST_JSON.get("code") or "")
    if code == "no_consent":
        e = gate_refused(os.path.join(ROOT, "data"), str(LAST_JSON.get("reason") or ""), str(LAST_JSON.get("error") or ""))
        record(stage, False, 0.0, e.message)
        raise e
    if code == "no_restricted":
        import privacy
        msg = str(LAST_JSON.get("error") or privacy.RESTRICTED_MSG)
        record(stage, False, 0.0, msg)
        raise RunStop(EXIT_SETUP, msg)


def run_ai_stage(script, d0, d1, retry_wait=None, extra=()):
    """판정 뒤 단계(Agentic AI 후보·업무 흐름 등)를 돌린다. Copilot 은 긴 판정 뒤에 일시적으로
    응답을 거부하는 일이 있어(실측: 뒤 단계만 실패), 실패하면 잠시 쉬고 1회 재시도한다.
    · agentic.py·flow.py 는 늘 --carry — 기간 끝날짜가 바뀌어도 지난 결과를 이어받고 남은 것만 묻는다.
    · 재시도 대기는 그 둘이 120초, 나머지는 15초. 15초를 넘는 대기는 이번 실행의 쉬는 시간 합계 안에서만 쉰다(바닥 15초).
      업무 흐름 재시도는 --no-merge(세부 병합 왕복을 다시 하지 않는다 — 규칙 병합과 캐시만).
    · 자식 마지막 줄 JSON 의 stop_kind 가 budget·gate·login·fatal·throttle 이거나 사유가 Copilot 사용량 제한이면
      재시도하지 않는다 — 다시 보내도 같은 벽이다.
    반환: (rc, note)."""
    base = os.path.basename(script)
    ai2 = base in AI2_STAGES
    if retry_wait is None:
        retry_wait = 120 if ai2 else 15
    cmd = [sys.executable, os.path.join(ROOT, script), "--from", d0, "--to", d1]
    if ai2 and "--carry" not in extra:
        cmd.append("--carry")
    cmd += [str(x) for x in extra]
    env = _child_env(AF32_LAUNCHER="run")
    _tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    _stage_id = {"agentic.py": "agentic", "flow.py": "flow", "refine.py": "refine",
                 "judge.py": "judge"}.get(base, base)
    _state_p = os.path.join(ROOT, "report", f"stage_state_{_tag}_{_stage_id}.json")
    _WATCH_STATE_PATH["p"] = _state_p
    try:
        rc, why = _run_capture(cmd, env)
    finally:
        _WATCH_STATE_PATH["p"] = None
    lj = dict(LAST_JSON)
    if rc == 0:
        return 0, ""
    consent_lost(_stage_id)
    if rc == 2:
        # rc 규약: 2 = 부분(이어가기 가능 — 예산·정체 자가 중단으로 남은 묶음이 있다). 재시도하지 않고 뒤 단계는 계속.
        return 2, str(why or "부분 완료 — 다시 실행하면 남은 것만 이어서")
    if "중단했습니다" in str(why or ""):
        # 정체 감지·시간 상한으로 끊은 것은 다시 보내도 같은 벽에 닿는다
        print(f"   {script} 를 중단했습니다 — 같은 벽에 다시 닿으므로 재시도하지 않습니다")
        return rc, why
    if run_throttled():
        print(f"   {script}: 이번 실행은 Copilot 사용량 제한으로 AI 단계를 멈춰 재시도하지 않습니다")
        return rc, why
    kind = str(lj.get("stop_kind") or "")
    if kind in NO_RETRY_KINDS or "사용량 제한" in str(why or "") or "R-THROTTLE" in str(why or ""):
        _k = {"budget": "시간 예산", "gate": "개인정보 관문", "login": "Copilot 로그인", "fatal": "사람이 손대야 풀리는 상태",
              "throttle": "Copilot 사용량 제한"}.get(kind, "Copilot 사용량 제한")
        print(f"   {script} 실패 사유가 {_k}라 다시 보내도 같습니다 — 재시도하지 않습니다")
        return rc, why
    if base == "flow.py" and "--no-merge" not in cmd:
        cmd.append("--no-merge")             # 재시도는 흐름 왕복만 — 세부 병합 왕복은 첫 시도가 이미 했다
    wait = retry_wait_sec(retry_wait)
    print(f"   첫 시도 실패(코드 {rc}) - {wait}초 뒤 1회 재시도합니다"
          + (" (이번 실행의 Copilot 쉬는 시간 합계 안 — copilotAuto.runWaitMaxSec)" if wait < retry_wait else ""))
    time.sleep(wait)
    if retry_wait > RETRY_WAIT_MIN:
        note_retry_wait(wait)
    _WATCH_STATE_PATH["p"] = _state_p
    try:
        rc, why2 = _run_capture(cmd, env)
    finally:
        _WATCH_STATE_PATH["p"] = None
    if rc == 0:
        return 0, "1회 재시도 후 성공"
    if rc == 2:
        return 2, "1회 재시도 후 부분 완료" + (f" — {why2}" if why2 else " — 다시 실행하면 남은 것만 이어서")
    return rc, (f"재시도에도 실패: {why2 or why}" if (why2 or why)
                else f"재시도에도 실패(코드 {rc}) - 탭의 수동 실행으로 다시")


# 정체 감지기 한 벌 — core/watch. 자식은 상태 파일 하트비트로 생존을 알린다 — 긴 왕복의 stdout 침묵을 죽음으로 오진하지 않는다.
import watch as _watch_mod  # noqa: E402
from watch import stage_limits as _core_stage_limits  # noqa: E402
from watch import watch_child as _core_watch_child  # noqa: E402

# 멈춘 단계를 끊을 때 taskkill 대신 Job 으로(core\proc.kill_tree — 자식을 띄울 때 proc.attach 로 Job 에 넣어 둔다).
# 전용 Edge 는 Job 에서 이탈해 떠 있으므로 같이 죽지 않는다.
_watch_mod.kill_tree = proc.kill_tree
kill_tree = proc.kill_tree  # 기존 호출부 이름 유지

_WATCH_STATE_PATH = {"p": None}      # 다음 watch_child 호출이 볼 상태 파일 — run_ai_stage 가 세팅
LAST_JSON = {}                       # 마지막 _run_capture 자식의 마지막 줄 JSON — run_ai_stage 가 stop_kind 를 본다


def _stage_limits():
    return _core_stage_limits(cfg())


def watch_child(p, on_line, label, beat_sec=120):
    return _core_watch_child(p, on_line, label, beat_sec=beat_sec, cfg_dict=cfg(),
                             state_path=_WATCH_STATE_PATH.get("p"))


def _run_capture(cmd, env):
    r"""자식 출력을 화면에 그대로 흘리면서, 실패 사유만 따로 건져 낸다.

    자식은 마지막 줄에 JSON 한 줄을 낸다({"ok":false,"error":...}). 그 줄을 잡아 last_run.json 에 실어야 화면이
    '왜 안 됐는지' 를 말할 수 있다. 그 JSON 전체는 LAST_JSON 에도 남긴다(run_ai_stage 의 stop_kind · 개인 리포트의 html)."""
    LAST_JSON.clear()
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, bufsize=1, text=True,
                             encoding="utf-8", errors="replace")
    except OSError as e:
        return 1, f"실행 실패({type(e).__name__})"
    job = proc.attach(p)                 # 단계가 끝나면(정상·중단) 남은 손자까지 Job 째 정리 — Edge 는 이탈해 산다
    tail, last_json = [], {}
    label = os.path.basename(str(cmd[1] if len(cmd) > 1 else "단계"))

    def _on(line):
        print(line, flush=True)          # [progress] 줄이 UI 진행 바에 바로 닿게(텍스트 층 버퍼링 방지)
        if line.strip():
            tail.append(line.strip())
            del tail[:-6]
        if line.startswith("{") and line.rstrip().endswith("}"):
            try:
                o = json.loads(line)
                if isinstance(o, dict):
                    last_json.update(o)
            except ValueError:
                pass

    stopped = watch_child(p, _on, label)
    rc = p.wait()
    proc.release(job, p.pid)
    LAST_JSON.update(last_json)
    if stopped:
        return (rc or 1), stopped
    if rc == 0:
        return 0, ""
    why = str(last_json.get("error") or "")
    if last_json.get("hint"):
        why = (why + " — " + str(last_json["hint"]))[:200] if why else str(last_json["hint"])[:200]
    if not why:
        # 단계 끝의 '[copilot] 채팅 정리:' 줄(숫자만)은 실패 사유가 아니다 — 그 앞의 줄을 집는다
        why = next((x for x in reversed(tail) if not x.startswith("{") and not x.startswith(CHAT_LINE_HEAD)), "")[:200]
    return rc, why


def invalidate_ai_outputs(d0, d1):
    r"""업무 분류 추출 성공 직후 — 같은 tag 의 지난 판정 산출물(정제본·버림 장부·정제 매핑)을 <이름>.stale 로 바꾼다.
    무AI 재실행·판정 실패·중단 뒤에도 옛 정제본이 '현재 결과' 로 남아 화면과 리포트가 서로 다른 값을 보이지 않게 한다.
    agentic/workflow 결과는 남긴다 — 화면이 '재추출 이후 결과' 로 표시하고, 무AI 실행이면 후보의 근거 건수만 새 행으로 다시 센다.
    .stale 은 중간 자료라 보관기한(retention intermediateDays)에 지워진다. 반환: (바꾼 이름 목록, 실패 목록)."""
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    rep = os.path.join(ROOT, "report")
    # ai_judgments 는 무효화하지 않는다 — judge 가 내용 sig 로 유효분만 회수한다('이어서 판정').
    names = [f"work_rows_{tag}_refined.csv", f"dropped_signals_{tag}.csv", f"refine_map_{tag}.json"]
    done, failed = [], []
    for n in names:
        p = os.path.join(rep, n)
        if not os.path.exists(p):
            continue
        try:
            os.replace(p, p + ".stale")
            done.append(n)
        except OSError as e:
            failed.append(f"{n}({type(e).__name__})")
    if done:
        print(f"   지난 판정 산출물 무효화(.stale): {', '.join(done)}")
    if failed:
        print(f"   [!] 무효화 실패: {', '.join(failed)} — 그 파일을 연 프로그램을 닫고 재실행하세요")
    return done, failed


def agentic_recalc_inproc(d0, d1):
    """agentic_<tag>.json 후보의 근거 건수를 지금 행으로 다시 센다(agentic.recalc_file, Copilot 왕복 없음 · 프로세스 없음).
    업무 흐름 단계 뒤에 부른다 — 세부업무 병합 맵(data\\cache\\detail_aliases.json)이 그때 처음 생기기 때문.
    어떤 실패도 분석 전체를 실패로 만들지 않는다. 반환: 저장했으면 True."""
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import agentic
        ap = agentic.recalc_file(tag, log=lambda m: print("   " + str(m)))
        if not ap:
            print("   (Agentic 근거 건수 다시 세기 생략 — agentic 결과 파일이나 업무 행이 없음)")
        return bool(ap)
    except Exception as e:  # noqa: BLE001 - 재계산 실패는 무시(기존 agentic 파일 그대로)
        print(f"   (Agentic 근거 건수 다시 세기 건너뜀: {type(e).__name__}: {str(e)[:80]})")
        return False


def open_ledger(c, data):
    r"""일자×축 원장(data\coverage_ledger.json) — 판(AF32-COV-1|collect.cursorEpoch)·설치가 다르면 비운 채로 연다.
    설치 표식은 data\install.json 의 install_id 앞 12자(폴더째 옮겨도 같은 설치 — 메일·일정은 계정에 있다)."""
    try:
        epoch = int(afcfg.get(c, "collect.cursorEpoch") or 1)
    except (TypeError, ValueError):
        epoch = 1
    try:
        host = "i:" + install.install_id(ROOT)[:12]
    except OSError:
        host = ""
    led = coverage.Ledger.load(os.path.join(data, coverage.FILE_NAME), ver=f"{coverage.LEDGER_VER}|{epoch}", host=host)
    if led.dropped:
        why = {"ver": "collect.cursorEpoch 가 바뀌었습니다",
               "raw_purged": "보관기한이 지나 수집 자료를 지워 처음부터 읽습니다"}.get(led.dropped, "다른 설치의 원장입니다")
        print("   (수집 원장을 처음부터 — " + why + ")")
    elif led.dropped_src:
        names = {"owa": "Outlook 웹"}
        print("   (" + "·".join(names.get(s, s) for s in led.dropped_src)
              + " 의 지난 '읽음' 표시를 지우고 그 날들을 다시 읽습니다 — 확인 규칙이 바뀌었습니다)")
    return led


def reset_cursors(c, data):
    r"""--reset-cursors — 수집기 커서와 원장을 지운다(다음 수집이 기간 전체를 처음부터 읽는다):
    Outlook 앱 달별 완료 표(data\outlook\src\coverage_com.json) · 원장(모든 축 not_attempted).
    정제된 행(CSV)은 지우지 않는다."""
    gone = []
    for rel in (("outlook", "src", "coverage_com.json"),):
        p = os.path.join(data, *rel)
        try:
            os.remove(p)
            gone.append("\\".join(rel))
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"   [!] {chr(92).join(rel)} 를 지우지 못했습니다({type(e).__name__}) — 그 파일을 연 프로그램을 닫으세요")
    led = open_ledger(c, data)
    led.reset()
    led.save()
    note = "커서 " + (", ".join(gone) if gone else "없음") + " 삭제 · 원장 초기화(모든 축 not_attempted)"
    print(f"\n── 수집 커서 초기화(--reset-cursors)\n   {note}")
    record("수집 커서 초기화", True, 0.0, note)
    return led


def _cdp_port():
    """전용 Edge 디버그 포트 — copilotAuto.port(옛 판 포트면 lmname.CDP_PORT)."""
    try:
        port = int(afcfg.get(CFG["c"], "copilotAuto.port") or lmname.CDP_PORT)
    except (TypeError, ValueError):
        port = lmname.CDP_PORT
    return lmname.CDP_PORT if lmname.is_old_edge(port=port) else port


def clear_edge_site_data(why):
    r"""Outlook 웹·Copilot 단계 뒤 — 전용 Edge 프로필의 Outlook·M365 사이트 자료(캐시·저장소)를 지운다(쿠키는 남긴다 —
    로그인 유지 · tools\copilot_auto.clear_site_data). 이 실행이 전용 Edge 를 썼을 때만, 로그인 대기 중이면 두고 안내만 한다.
    실패해도 실행은 계속한다. → 결과 dict | None."""
    if not EDGE.get("used"):
        return None
    if STATE.get("login_pending"):
        print("   (전용 Edge 가 로그인을 기다리는 중이라 사이트 자료는 다음 실행 끝에 지웁니다)")
        return None
    EDGE["used"] = False
    fn = _CLEAR_SITE
    try:
        if fn is None:
            fn = _copilot_mod().clear_site_data
        r = fn(_cdp_port())
    except Exception as e:  # noqa: BLE001 - 정리 실패가 실행 결과를 바꾸지 않는다
        EDGE["used"] = True
        record("전용 Edge 사이트 자료 지우기", False, 0.0, f"지우지 못했습니다({type(e).__name__}) — 다음 실행 끝에 다시 지웁니다")
        return None
    if isinstance(r, dict) and r.get("skipped"):
        return r                    # 전용 Edge 가 떠 있지 않다(또는 그 포트가 우리 프로필이 아니다) — 지울 것이 없다
    errs = [str(x) for x in (r.get("errors") or [])] if isinstance(r, dict) else []
    ok = not errs and not (isinstance(r, dict) and r.get("ok") is False and not (r.get("cleared") or r.get("cache")))
    note = ("Outlook·M365 사이트의 캐시·저장소를 지웠습니다(로그인은 그대로)" if ok
            else f"지우지 못했습니다({', '.join(errs[:3]) or '사유 미상'}) — 다음 실행 끝에 다시 지웁니다")
    print(f"   ({note})")
    record("전용 Edge 사이트 자료 지우기", ok, 0.0, note)
    if not ok:
        EDGE["used"] = True
    return r


def close_edge_once(state, why):
    r"""우리가 띄운 전용 Edge 를 닫는다(tools\copilot_auto.close_own_edge — owner.json 이 있을 때만, CDP Browser.close).
    한 실행에 1회. 닫기 전에 이 실행이 쓴 Outlook·M365 사이트 자료를 지운다(clear_edge_site_data). 이 실행의 웹 경로가
    로그인을 기다리는 중(rc 2)이면 닫지 않고 안내만 한다 — 사람이 그 창에서 로그인하는 중일 수 있다.
    close_own_edge 가 닫기 전에 마지막 우리 Copilot 채팅을 지운다 — 그 뒤 단계 'Copilot 채팅 정리'(chat_stage)를 남긴다."""
    if EDGE["closed"]:
        return None
    EDGE["closed"] = True
    try:
        clear_edge_site_data(why)
        return _close_edge(state, why)
    finally:
        chat_stage()


def _close_edge(state, why):
    """close_edge_once 의 본문 — 로그인 대기면 두고, 아니면 close_own_edge(시험은 _CLOSE_EDGE)."""
    if isinstance(state, dict) and state.get("login_pending"):
        print("\n   전용 Edge 창은 닫지 않았습니다 — 그 창에서 회사 계정으로 로그인한 뒤 다시 실행하면 이어서 읽습니다.")
        return {"closed": False, "why": "login_pending"}
    fn = _CLOSE_EDGE
    if fn is None:
        try:
            fn = _copilot_mod().close_own_edge
        except Exception as e:  # noqa: BLE001 - 정리 실패가 실행 결과를 바꾸지 않는다
            print(f"   (전용 Edge 정리 건너뜀: {type(e).__name__})")
            return None
    try:
        r = fn(None, why)
    except Exception as e:  # noqa: BLE001
        print(f"   (전용 Edge 정리 실패: {type(e).__name__}: {str(e)[:80]})")
        return None
    if isinstance(r, dict) and r.get("closed"):
        print("   (이 실행이 띄운 전용 Edge 를 닫았습니다)")
    return r


def _copilot_mod():
    r"""tools\copilot_auto(같은 프로세스에 이미 올라와 있으면 그것) — Edge 닫기·사이트 자료 지우기·채팅 정리 누계."""
    tools = os.path.join(ROOT, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import copilot_auto
    return copilot_auto


def chat_totals():
    r"""Copilot 채팅 정리 누계(copilot_auto.chat_totals — 숫자·사유 코드만) · 못 읽으면 None."""
    try:
        fn = _CHAT_TOTALS if _CHAT_TOTALS is not None else _copilot_mod().chat_totals
        t = fn(None)
        return t if isinstance(t, dict) else None
    except Exception:  # noqa: BLE001 - 정리 기록이 실행을 막지 않는다
        return None


END_STAGES = ("완료", "종료")
SLOW_MIN_SEC = 180             # 이보다 오래 걸린 단계만 '오래 걸린 단계' 줄에 적는다


def slow_stages(stages=None, top=4, min_sec=SLOW_MIN_SEC, started=None, now=None):
    r"""실행 끝 한 줄 — '총 1시간 45분 · 오래 걸린 단계: M365 Copilot 메일·일정 38분 · AI 판정 25분 …'(min_sec 넘은 단계를
    긴 순으로 top 개 · 이름은 괄호 앞까지). 오래 걸린 단계가 없으면 "". started = 시작 시각('%Y-%m-%d %H:%M' — 시험용) ·
    없으면 이번 실행의 RUN_T0(last_run.json 에는 날짜만 있어 그것으로는 걸린 시간을 셀 수 없다)."""
    st = [x for x in (RUN["stages"] if stages is None else stages) if isinstance(x, dict)]

    def _sec(x):
        try:
            return float(x.get("sec") or 0)
        except (TypeError, ValueError):
            return 0.0

    slow = sorted((x for x in st if _sec(x) >= min_sec), key=lambda x: -_sec(x))[:max(1, int(top))]
    if not slow:
        return ""

    def _min(sec):
        m = int(round(sec / 60.0))
        return f"{m // 60}시간 {m % 60}분" if m >= 60 else f"{max(1, m)}분"
    parts = [f"{str(x.get('name') or '').split(' (')[0].strip()} {_min(_sec(x))}" for x in slow]
    head = ""
    try:
        t0 = (time.mktime(time.strptime(str(started), "%Y-%m-%d %H:%M")) if started is not None else RUN_T0["t"])
        head = f"총 {_min(max(0.0, (now if now is not None else time.time()) - t0))} · " if t0 else ""
    except (ValueError, OverflowError, TypeError):
        head = ""
    return head + "오래 걸린 단계: " + " · ".join(parts)


def chat_report():
    r"""이번 실행의 Copilot 채팅 셈(copilot_auto.chat_run_report — 숫자·사유 코드와 한 줄) · 못 읽으면 None."""
    try:
        fn = _CHAT_REPORT if _CHAT_REPORT is not None else _copilot_mod().chat_run_report
        r = fn(None, RUN.get("run_id") or None)
        return r if isinstance(r, dict) else None
    except Exception:  # noqa: BLE001 - 정리 기록이 실행을 막지 않는다
        return None


def chat_stage():
    r"""실행 끝 단계 'Copilot 채팅 정리' — 한 실행에 1회(close_edge_once 끝).
    이번 실행의 셈(copilot_auto.chat_run_report)으로 한 줄을 만든다: 'Copilot 채팅: 이번 실행에서 연 N개 · 지운 M개 · 남긴 K개
    (까닭: …)'. 진행 로그·last_run.json(단계 note · chats 숫자 · chats_line)에 남는다. 제목·글은 없다.
    시작 때 표식(CHATS['t0'])이 없으면 적지 않는다 · 연·지운·남긴 것이 없으면 적지 않는다. 끝 단계(완료·종료) 앞에 둔다."""
    t0 = CHATS.get("t0")
    CHATS["t0"] = None
    if t0 is None:
        return None
    rep = chat_report()
    if rep is None:
        return None
    try:
        ca = _copilot_mod()
        if not ca.chat_run_busy(rep):
            return None
        line = str(rep.get("line") or ca.chat_run_line(rep))
        fail = any(k in ca.CHAT_FAIL for k in (rep.get("why") or {}))
    except Exception:  # noqa: BLE001
        return None
    print(f"\n── {CHAT_STAGE}\n   {line}", flush=True)
    RUN["chats"] = dict({k: int(rep.get(k) or 0) for k in ("made", "deleted", "kept", "gone", "deleted_old", "gone_old",
                                                           "old_left", "left_old", "savefail")},
                        why={str(k): int(v or 0) for k, v in (rep.get("why") or {}).items()}, hold=str(rep.get("hold") or ""))
    RUN["chats_line"] = line[:600]
    record(CHAT_STAGE, not (fail or rep.get("hold")), 0.0, line)
    st = RUN["stages"]
    ent = st.pop()                                  # 방금 붙인 이 단계 — 끝 단계(완료·종료) 앞으로 옮긴다
    k = len(st)
    while k > 0 and str(st[k - 1].get("name") or "").startswith(END_STAGES):
        k -= 1
    st.insert(k, ent)
    _save_run()
    return rep


def web_only(c, kind, d0, d1, data, col, clamp=None):
    r"""--web-only mail — 화면의 [Outlook 웹 읽기]: 기간(d0·d1) 전체를 Outlook 웹으로 읽고(수집기 안에서 G1) 원장·병합·수집 요약까지
    한다. 끝에 사이트 자료를 지우고 이 실행이 띄운 전용 Edge 를 닫는다(로그인 대기면 둔다).
    → 종료 코드(0 정상 · 2 로그인 필요 · 1 실패). 시작 거부(시작 확인·제한 고객·사내 도메인)는 RunStop."""
    if kind != "mail":
        print("[!] --web-only 뒤에는 mail 만 쓸 수 있습니다 (예: --web-only mail)")
        return EXIT_FAIL
    nm = "Outlook 웹 (전용 Edge — 화면에서 실행)"
    if "owa" not in channels(c):
        print(f"\n── {nm} — collect.channels 에 owa 가 없어 읽지 않았습니다")
        record(nm, False, 0.0, "건너뜀 — collect.channels 에 owa 가 없습니다")
        return EXIT_FAIL
    led = open_ledger(c, data)
    src_dir = os.path.join(data, "outlook", "src")
    os.makedirs(src_dir, exist_ok=True)
    EDGE["used"] = True
    st = run_collector(nm, [sys.executable, os.path.join(col, "Get-OutlookWeb.py"), "--from", d0, "--to", d1,
                            "--out-dir", src_dir, "--tag", "owa"], 180 + 150 * _months(d0, d1), src="owa", led=led)
    check_setup(st, data)
    _edge_rc2(st, STATE, nm, "Outlook")
    info = merge_mail(c, data, led, d0, d1)
    report_gaps(led, d0, d1, MAIL_AXES, "메일·일정 원장(확인하지 못한 날)")
    led.save()
    write_summary(c, data, d0, d1, clamp, {"owa": st.get("rc")}, info)
    close_edge_once(STATE, "web_only")
    if STATE.get("login_pending"):
        return EXIT_PARTIAL
    return EXIT_OK if st["ok"] else EXIT_FAIL


STOP_STAGE = "중단(창 닫힘)"      # last_run.json 단계 이름(ui\app.py 와 같다) — 다음 화면이 '마지막 단계: 중단(창 닫힘)' 으로 말한다
EDGE_FAST_SEC = 2.5              # 콘솔 창 닫기 때 전용 Edge 닫기를 기다리는 상한(윈도는 처리기에 약 5초를 준다)


def console_close(ev=None, budget=EDGE_FAST_SEC):
    r"""콘솔 창(AgentFinder32.bat)을 닫을 때(core\proc.on_console_close) — 윈도가 주는 몇 초 안에 끝나는 것만 한다.
    Job 에 든 자식(수집기·mine·judge·copilot_auto)은 이 프로세스와 함께 끝나지만, Job 에서 이탈한 전용 Edge 는 남는다 —
    Job 을 먼저 끝내고(proc.kill_all) 그 Edge 를 채팅 정리 없이(tidy=False) budget 초까지만 기다려 닫는다.
    로그인 대기 중(rc 2)이면 Edge 는 두고, last_run.json 에 '중단(창 닫힘)' 을 남긴다. 예외를 내지 않는다.
    Outlook 앱 원자료가 남았으면 지운다(정제할 시간이 없다 — 원자료는 남기지 않는다)."""
    try:
        proc.kill_all()
    except Exception:  # noqa: BLE001
        pass
    try:
        drop_raw(os.path.join(ROOT, "data"))
    except Exception:  # noqa: BLE001
        pass
    try:
        drop_run_lock()
    except Exception:  # noqa: BLE001
        pass
    try:
        if RUN.get("started") and not RUN.get("finished"):
            record(STOP_STAGE, False, 0.0, "콘솔 창이 닫혀 실행 중이던 작업을 멈췄습니다 — 지금까지의 결과는 report\\에 남아 있습니다")
    except Exception:  # noqa: BLE001
        pass
    if isinstance(STATE, dict) and STATE.get("login_pending"):
        return
    try:
        proc.run_within(lambda: _copilot_mod().close_own_edge(None, "console_close", tidy=False), budget)
    except Exception:  # noqa: BLE001
        pass


def keep_awake_wanted(c=None):
    """config.keepAwakeDuringRun — 기본 켬. false·"false"·0·"off"·"no" 면 끔(분석 중에도 PC 가 평소처럼 절전에 들어간다).
    c 가 없으면 config.json 을 조용히 읽는다(깨졌으면 기본 켬 — 경고는 _main 의 cfg() 가 한 번 낸다)."""
    if c is None:
        try:
            with open(os.path.join(ROOT, "config", "config.json"), encoding="utf-8-sig") as f:
                c = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            c = {}
    v = c.get("keepAwakeDuringRun", True) if isinstance(c, dict) else True
    return not (v is False or str(v).strip().lower() in ("false", "0", "off", "no"))


# ── 시작 검사 ─────────────────────────────────────────────────────────────────────────────────────
LOCK = {"path": None}           # 이 실행이 쥔 data\run.lock(놓을 때 내 pid 의 것만 지운다)
LOCK_MSG = "이 폴더의 분석이 이미 돌고 있습니다(pid {pid}) — 그 실행이 끝난 뒤 다시 하세요"


def take_run_lock():
    r"""분석 잠금 data\run.lock {product, pid, date} 를 쥔다(C5 — 실행 내내 · 날짜만) → None(쥠) | 이미 쥔 다른 실행의 pid.
    화면의 지우기([모두 지우기] 포함)와 retention.py --purge-all 이 이것을 보고(retention.run_active) 거절한다. 끝난 실행이 남긴 잠금은 치우고
    쥔다. 임시 파일에 다 쓴 뒤 이름을 바꿔 쥔다(윈도의 rename 은 같은 이름이 있으면 실패한다 — 두 실행이 함께 쥐지 못한다).
    잠금을 쓰지 못하면(자료 폴더에 쓸 수 없음) 알리고 잠금 없이 계속한다 — 그런 폴더에서는 뒤 단계가 스스로 멈춘다."""
    p = retention.run_lock_path(ROOT)
    tmp = f"{p}.{os.getpid()}.tmp"
    try:
        for _ in range(3):
            other = retention.run_lock_pid(ROOT)
            if other and other != os.getpid():
                return other
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.lexists(p):
                retention._rm_file(p)                      # 끝난 실행이 남긴 잠금
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"product": lmname.PRODUCT, "pid": os.getpid(), "date": _today()}, f, ensure_ascii=False)
            try:
                os.rename(tmp, p)
            except FileExistsError:
                continue                                   # 다른 실행이 방금 쥐었다 — 누구인지 다시 본다
            LOCK["path"] = p
            return None
        return retention.run_lock_pid(ROOT) or None
    except OSError as e:
        print(f"   (분석 잠금을 쓰지 못했습니다: {type(e).__name__})")
        return None
    finally:
        if os.path.lexists(tmp):
            retention._rm_file(tmp)


def drop_run_lock():
    r"""쥔 분석 잠금을 놓는다 — data\run.lock 의 pid 가 이 실행일 때만 지운다."""
    p = LOCK.get("path")
    LOCK["path"] = None
    if not p:
        return
    d = _read_json(p)
    if isinstance(d, dict) and d.get("pid") == os.getpid():
        retention._rm_file(p)


def resume_withdrawal(c):
    r"""끝나지 않은 [모두 지우기]를 마저 한다(consent.resume_withdrawal — data\withdrawal.json 의 state 가 in_progress 일 때만
    일한다) → 그 결과 dict | None(할 일이 없었다). 한 일은 한 줄로 알린다. 실패는 알리기만 한다(다음 시작 때 다시)."""
    try:
        res = consent.resume_withdrawal(ROOT, c)
    except Exception as e:  # noqa: BLE001 - 시작을 막지 않는다(다음 시작 때 다시)
        print(f"[지우기] 끝나지 않은 [모두 지우기]를 마저 하지 못했습니다({type(e).__name__}) — 다음 시작 때 다시 합니다")
        return None
    if not isinstance(res, dict):
        return None
    print("[지우기] 끝나지 않은 [모두 지우기]를 이어서 했습니다 — " + consent.withdraw_message(res))
    return res


def startup_purge(c):
    r"""옛 LoadMonitor 자료 정리(retention.purge_legacy — D20) → 보관기한이 지난 자료 정리(retention.purge — D13) →
    [모두 지우기] 뒤 남은 서버 사본 다시 지우기. 끝나지 않은 [모두 지우기] 마저 하기(resume_withdrawal)는 _main 이 분석 잠금을
    쥐기 전에 한다.
    실패는 알리기만 하고 실행은 계속한다. → (옛 자료 지운 수, 기한 지난 자료 지운 수)."""
    try:
        lg = retention.purge_legacy(ROOT)
    except Exception as e:  # noqa: BLE001 - 정리 실패가 실행을 막지 않는다(다음 시작 때 다시)
        lg = {"deleted": 0, "errors": [{"path": "", "why": type(e).__name__}]}
    try:
        pg = retention.purge(ROOT, c)
    except Exception as e:  # noqa: BLE001
        pg = {"deleted": 0, "errors": [{"path": "", "why": type(e).__name__}]}
    n1, n2 = _n(lg.get("deleted")), _n(pg.get("deleted"))
    errs = len(lg.get("errors") or []) + len(pg.get("errors") or [])
    if n1 or n2 or errs:
        print(f"[보관기한] 옛 LoadMonitor 자료 {n1}개 · 보관기한이 지난 자료 {n2}개를 지웠습니다"
              + (f" · 지우지 못한 것 {errs}개(다음 시작 때 다시)" if errs else ""))
    retry_withdrawals(c)
    return n1, n2


def retry_withdrawals(c):
    r"""[모두 지우기] 뒤 조직장 서버에서 아직 못 지운 공유가 남았으면 다시 지운다(spec §6.2 — 시작할 때마다 ·
    teamup.retry_withdrawals: data\withdrawal.json 과 표시("withdraw")한 영수증이 있을 때만). 시작 확인보다 먼저 — 지우는 중이어도
    서버 사본은 지운다. 실패해도 실행은 계속한다."""
    if ROOT not in sys.path:
        sys.path.append(ROOT)        # 동봉 파이썬(._pth)은 스크립트 폴더를 sys.path 에 넣지 않는다 — teamup.py 는 ROOT 에 있다
    try:
        import teamup
        r = teamup.retry_withdrawals(ROOT, c, timeout=5)
    except Exception as e:  # noqa: BLE001 - 서버 사본 지우기 실패는 다음 시작 때 다시
        print(f"[지우기] 조직장 서버 사본 다시 지우기를 건너뜀({type(e).__name__})")
        return None
    if r is None:
        return None
    left = int(r.get("left") or 0) if isinstance(r, dict) else 0
    print("[지우기] " + ("조직장 서버에 남아 있던 공유를 지웠습니다" if not left
                      else f"조직장 서버에서 아직 지우지 못한 공유 {left}건 — 다음 시작 때 다시 지웁니다"))
    return r


def end_purge(c):
    r"""실행 끝 보관기한 정리(retention.purge) — 지운 것·못 지운 것이 있을 때만 단계로 남긴다."""
    try:
        pg = retention.purge(ROOT, c)
    except Exception as e:  # noqa: BLE001
        pg = {"deleted": 0, "errors": [{"path": "", "why": type(e).__name__}]}
    n, errs = _n(pg.get("deleted")), pg.get("errors") or []
    if n or errs:
        note = f"보관기한이 지난 파일 {n}개를 지웠습니다" + (f" · 지우지 못한 것 {len(errs)}개(다음 시작 때 다시)" if errs else "")
        print(f"\n── 보관기한 정리\n   {note}")
        record("보관기한 정리", not errs, 0.0, note)
    return n


def _latest_run_meta():
    r"""report\run_meta_*.json 중 가장 새 AgentFinder32 것 → dict | {}."""
    best, best_t = {}, -1.0
    for p in glob.glob(os.path.join(ROOT, "report", "run_meta_*.json")):
        t = _mtime(p) or 0.0
        if t <= best_t:
            continue
        m = _read_json(p)
        if m.get("product") == lmname.PRODUCT:
            best, best_t = m, t
    return best


def restricted_changed(restricted):
    r"""제한 고객 목록이 지난 분석 이후 바뀌었나(D9) — 가장 새 run_meta 의 restricted_sha256 과 지금 파일의 sha256 이 다르면 True.
    지난 기록이 없으면 False."""
    prev = str(_latest_run_meta().get("restricted_sha256") or "").strip().lower()
    cur = str(getattr(restricted, "sha256", "") or "").strip().lower()
    return bool(prev) and bool(cur) and prev != cur


def _stop(e):
    """RunStop → 화면·last_run.json 에 남기고 종료 코드."""
    print(f"\n[!] {e.message}")
    if RUN.get("started"):
        record(e.stage, False, 0.0, e.message)
        RUN["finished"] = _today()
        record("종료", False, 0.0, e.message)
    return e.code


def main():
    """실행 전체 — 마지막 finally 에서 이 실행이 띄운 전용 Edge 를 1회 닫는다(로그인 대기면 둔다).
    콘솔 창을 X 로 닫으면 finally 가 돌지 않는다 — console_close 가 그 몇 초 안에 작업 트리와 전용 Edge 를 정리한다
    (Ctrl+C 는 KeyboardInterrupt → finally)."""
    proc.on_console_close(console_close)
    proc.quiet_errors()          # 수집기가 못 켜질 때 Windows 오류 창(0xc0000142)이 떠 [확인]까지 멈추지 않게 — 자식이 물려받는다
    start_run_id()               # 이번 실행의 표식(AF32_RUN_ID): 사용량 제한으로 멈춘 기록이 이번 실행 것인지 가른다
    # 분석이 도는 동안 PC 가 절전에 들어가지 않게(화면 꺼짐·화면 보호기·잠금은 그대로). 끄기: config.json keepAwakeDuringRun=false
    if keep_awake_wanted():
        proc.keep_awake(True)
    try:
        return _main()
    finally:
        close_edge_once(STATE, "run_end")


def _main():
    data = os.path.join(ROOT, "data")
    # ① 설치 위치(클라우드·네트워크 동기화 폴더)·옛 LoadMonitor 프로그램 파일·설치 폴더 권한 — 아무것도 쓰지 않고 멈춘다
    msg = install.startup_check(ROOT)
    if msg:
        EDGE["closed"] = True
        print(f"[!] {msg}")
        return EXIT_SETUP
    if install.acl_note():
        print(f"   {install.acl_note()}")
    c = cfg(verbose=True)
    CFG["c"] = c
    # ② 끝나지 않은 [모두 지우기] 마저 하기 — 분석 잠금보다 먼저(data\ 를 통째로 지운다 · 지우는 중에는 어떤 실행도 돌지 않는다)
    wiped = resume_withdrawal(c)
    # ③ 분석 잠금 — 이 폴더의 다른 실행(화면·bat)이 돌면 멈춘다. 실행 내내 쥐고 끝에 놓는다
    other = take_run_lock()
    if other:
        EDGE["closed"] = True
        print(f"[!] {LOCK_MSG.format(pid=other)}")
        return EXIT_FAIL
    try:
        return _main_locked(data, c, wiped)
    except install.OwnerUnknown:
        # 실행 중 설치 정보가 사라졌다(그 사이 지워졌다) — 이 실행이 쓴 파일을 지우고 주인을 모르는 자료로 멈춘다(종료 코드 4)
        return _stop(gate_refused(data, "other_user", install.UNKNOWN_OWNER_MSG))
    finally:
        drop_run_lock()


def skip_prune(c, data, d0, d1):
    r"""--skip-collect(다시 읽지 않고 분석만) — 수집을 건너뛰어도 기간 창 밖 행은 지운다(D13): data\outlook\src\*.csv·mail.csv·
    calendar.csv 의 창 밖 행과 원장의 창 밖 날(mailmerge.prune_window). 원장은 지운 날이 있을 때만 다시 쓴다. → 지운 행 수."""
    import mailmerge
    try:
        led = open_ledger(c, data)
        res = mailmerge.prune_window(data, (d0, d1), c, ledger=led)
        if res.get("ledger_days"):
            led.save()
    except Exception as e:  # noqa: BLE001 - 정리 실패가 분석을 막지 않는다(다음 실행 때 다시)
        print(f"   (기간 밖 행 정리 건너뜀: {type(e).__name__})")
        return 0
    n = _n(res.get("rows"))
    if n:
        note = f"기간 밖 행 {n}개를 지웠습니다({', '.join(res.get('files') or [])})"
        print(f"\n── 기간 밖 자료 정리\n   {note}")
        record("기간 밖 자료 정리", True, 0.0, note)
    return n


def _main_locked(data, c, wiped=None):
    # ④ 옛 자료 정리 → 보관기한 정리
    startup_purge(c)
    # ⑤ 시작 확인 — 다른 사용자의 자료·주인을 모르는 자료이거나 [모두 지우기]가 끝나지 않았으면 아무것도 읽지 않는다.
    #    쓰겠다는 뜻은 묻지 않는다(서면으로 따로 받는다 — consent.PAPER_CONSENT_LINE)
    try:
        consent.require(ROOT, c)
    except consent.ConsentRequired as e:
        EDGE["closed"] = True
        if e.reason != "other_user":
            # 내 설치의 자료([모두 지우기]가 끝나지 않았다) — 지난 실행이 남긴 원자료(§5.0, 다른 사람 이름·주소)는 정제할 수
            # 없으니 읽지 않고 지운다. 다른 사용자의 자료(D17)는 지우지 않는다 — 본인이 화면·AgentFinder32.bat 에서 고를 때만.
            drop_raw(data)
        print(f"[!] {e.message}")
        if e.reason == "other_user":
            print("    AgentFinder32.bat 또는 화면(AgentFinder32-UI.bat)에서 이 자료를 지운 뒤 새로 시작할 수 있습니다.")
        else:
            print("    지우지 못한 파일을 연 프로그램을 닫고 다시 시작하면 마저 지웁니다.")
        return gate_code(e.reason)
    if wiped:
        # 이 시작이 끝나지 않은 [모두 지우기]를 마쳤다 — 자료를 다 지운 그 시작에서 곧바로 다시 모으지 않는다(다음 시작은 새 설치)
        EDGE["closed"] = True
        print(f"[!] {WIPED_MSG}")
        return EXIT_CONSENT
    # 매일 정리 예약 작업을 설정(retention.scheduledPurge)에 맞춘다 — 하루 한 번만 작업 스케줄러에 묻는다(AF32_NO_TASK 면 아무것도 안 함).
    # 분석이 시작한다(starting_run) — 이제 지울 자료가 생기므로 빈 설치여도 그 작업을 만든다(화면만 열 때는 자료가 있을 때만)
    task = retention.sync_task(ROOT, c, starting_run=True)
    if isinstance(task, dict) and task.get("message"):
        print(f"[보관기한] {task['message']}")
    RUN_T0["t"] = time.time()
    RUN.update(started=_today(), finished=None, ai_requested=("--ai" in sys.argv),
               skip_collect=("--skip-collect" in sys.argv))
    # ⑥ 제한 고객 목록 — 없거나 형식이 틀리면 분석하지 않는다(D9)
    import privacy
    try:
        restricted = privacy.load_restricted(c, ROOT)
    except privacy.SetupRefused as e:
        EDGE["closed"] = True
        drop_raw(data)                     # 지난 실행이 남긴 원자료(이름·주소가 든 §5.0)는 정제 없이 지운다 — g1_com 과 같다
        return _stop(RunStop(EXIT_SETUP, e.message))
    # ⑦ 기간 — 오늘은 넣지 않고 어제까지, 최대 period.maxDays 일(D2)
    try:
        d0d, d1d, clamp = period.clamp(arg("--from") or None, arg("--to") or None, c)
    except ValueError as e:
        EDGE["closed"] = True
        drop_raw(data)                     # 기간 없이는 정제하지 못한다 — 남은 원자료는 지운다(그 달들은 다음 실행이 다시 읽는다)
        return _stop(RunStop(EXIT_FAIL, str(e), "기간 확인 필요"))
    d0, d1 = d0d.isoformat(), d1d.isoformat()
    os.environ["AF32_CLAMP"] = json.dumps(clamp, ensure_ascii=False)    # 단계 CLI 가 run_meta.clamped 에 싣는다
    notice = period.notice_text(clamp, d0d, d1d, c)
    # 제한 고객 목록이 바뀌었으면 지난 수집·분석 자료를 먼저 지운다(D9) — last_run.json 도 지워지므로 기록보다 먼저
    force_collect, rnote = False, ""
    if restricted_changed(restricted):
        res = retention.purge_classes(ROOT)
        force_collect = True
        rnote = (f"제한 고객 목록이 바뀌어 지난 수집·분석 자료 {_n(res.get('deleted'))}개를 지웠습니다 — 수집부터 다시 합니다")
    RUN.update(period=[d0, d1], clamped=clamp)
    record("시작", True, 0.0, notice)
    if force_collect:
        print(f"\n[!] {rnote}")
        record("제한 고객 목록 바뀜", True, 0.0, rnote)
    CHATS["t0"] = chat_totals()            # Copilot 채팅 정리 누계 — 실행 끝 단계 'Copilot 채팅 정리' 가 이 차이를 적는다
    print(f"[{lmname.PRODUCT}] {d0} ~ {d1}"
          + ("  · AI 판정 포함" if "--ai" in sys.argv else "  · AI 판정 없음(규칙 결과만)"))
    print("   이 도구는 Agentic AI 로 바꿀 만한 업무를 찾는 데만 씁니다. 결과는 이 PC 에 남고, "
          "공유는 화면의 [공유] 탭에서 고를 때만 보냅니다.")
    if notice:
        print(f"   [기간] {notice}")
    try:
        if check_rules(c):                 # 정제 규칙이 바뀌었으면 지난 정제 자료를 지웠다 — 이번에는 수집부터
            force_collect = True
        if "--reset-cursors" in sys.argv:
            reset_cursors(c, data)
        recover_raw(c, data, d0, d1)       # 지난 실행이 남긴 원자료 — 정제하고 지운다
        if "--web-only" in sys.argv:
            rc_w = web_only(c, arg("--web-only"), d0, d1, data, os.path.join(ROOT, "collect"), clamp)
            RUN["finished"] = _today()
            record("완료(웹 읽기)", rc_w == EXIT_OK, 0.0,
                   {EXIT_OK: "", EXIT_PARTIAL: "로그인 필요 — 전용 Edge 창에서 회사 계정 1회"}.get(rc_w, "일부 실패"))
            return rc_w
        skip = "--skip-collect" in sys.argv and not force_collect
        if "--skip-collect" in sys.argv and force_collect:
            print("   ([다시 읽지 않고 분석만]을 골랐지만 지난 자료를 지웠으므로 이번에는 수집부터 합니다)")
        if skip:
            skip_prune(c, data, d0, d1)    # 다시 읽지 않아도 기간 창 밖 행은 지운다(D13)
        else:
            collect(c, d0, d1, data, clamp)
        recheck_consent(data, MINE_STAGE)
    except RunStop as e:
        return _stop(e)

    rc_m = run_mine(data, d0, d1)
    if rc_m is not None:
        return rc_m
    try:
        ai_partial = run_ai(c, d0, d1) if "--ai" in sys.argv else no_ai(d0, d1)
        recheck_consent(data, REPORT_STAGE)
    except RunStop as e:
        return _stop(e)
    report_ok = build_report(d0, d1)
    end_purge(c)
    print("\n   공유는 화면(AgentFinder32-UI.bat)의 [공유] 탭에서 본인이 고를 때만 합니다 — "
          "이 실행은 조직장에게 아무것도 보내지 않았습니다(AI 분석은 회사 M365 Copilot 을 씁니다).")
    _slow = slow_stages()
    if _slow:
        print(f"\n── {_slow}")
    rc = EXIT_PARTIAL if (STATE.get("login_pending") or ai_partial or not report_ok) else EXIT_OK
    if STATE.get("login_pending"):
        print("\n[!] 전용 Edge 창에서 회사 계정으로 로그인한 뒤 다시 실행하면 남은 날을 이어서 읽습니다.")
    RUN["finished"] = _today()
    record("완료", True, 0.0, (_slow + (" · " if _slow else "") + "일부만 끝났습니다") if rc else _slow)
    return rc


def run_mine(data, d0, d1):
    r"""업무 분류 추출(mine.py <data> --from --to) — 출력을 흘려보내면서 꼬리를 보관한다(mine 이 죽으면 마지막 오류 줄이
    last_run.json 에 실려 화면 배너로 보인다). 성공이면 None, 아니면 이 실행의 종료 코드."""
    print(f"\n── {MINE_STAGE} (메일·일정 신호 → 업무 분류)")
    _t = time.time()
    try:
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "mine.py"), data, "--from", d0, "--to", d1],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_child_env(),
                             text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        record(MINE_STAGE, False, time.time() - _t, f"실행 실패({type(e).__name__})")
        RUN["finished"] = _today()
        record("종료", False, 0.0, f"{MINE_STAGE} 실행 실패")
        return EXIT_FAIL
    tail = []

    def _on_mine(line):
        print(line, flush=True)
        tail.append(line)
        del tail[:-12]

    _job_m = proc.attach(p)                                  # 멈춰 끊을 때 Job 째(taskkill 없음)
    stop_m = watch_child(p, _on_mine, MINE_STAGE)            # 멈추면 끊는다(정체 감지)
    rc_m = p.wait()
    proc.release(_job_m, p.pid)
    t_end = _today()
    if stop_m:
        record(MINE_STAGE, False, time.time() - _t, stop_m)
        RUN["finished"] = t_end
        record("종료", False, 0.0, stop_m)
        return EXIT_FAIL
    if rc_m == 0:
        # 지난 판정 산출물은 이 시점부터 '옛것' 이다 — 정제본이 화면에 그대로 남지 않게 이름을 바꾼다
        _inv, _inv_fail = invalidate_ai_outputs(d0, d1)
        record(MINE_STAGE, True, time.time() - _t,
               (f"지난 판정 산출물 {len(_inv)}개 무효화(.stale)" if _inv else "")
               + (f" · 무효화 실패: {', '.join(_inv_fail)}" if _inv_fail else ""))
        return None
    if rc_m == 3 or (rc_m == 4 and gate_reason()):
        # mine 이 시작 확인에 걸려 멈췄다(그 사이 [모두 지우기]가 시작됐거나 설치 정보가 사라졌다 — mine 은 지우는 중이면 3,
        # 주인을 모르면 4 로 끝난다) — 이 실행이 쓴 파일을 남기지 않는다
        e = gate_refused(data)
        record(MINE_STAGE, False, time.time() - _t, e.message)
        RUN["finished"] = t_end
        record("종료", False, 0.0, e.message)
        return e.code
    if rc_m == 4:
        why = next((ln.split("] ", 1)[-1] for ln in reversed(tail) if ln.startswith("[mine]")), "") or "설정 확인 필요"
        record(MINE_STAGE, False, time.time() - _t, why[:200])
        RUN["finished"] = t_end
        record("종료", False, 0.0, why[:200])
        return EXIT_SETUP
    if rc_m == 5:
        record(MINE_STAGE, False, time.time() - _t, "결과 파일이 다른 프로그램(Excel 등)에서 열려 있어 저장 실패")
        print("\n[!] 결과 CSV/MD 가 열려 있어 저장하지 못했습니다 — 해당 파일을 닫고 다시 실행하세요.")
        RUN["finished"] = t_end
        record("종료", False, 0.0, "결과 파일 잠김 — Excel 등에서 열어둔 결과 파일을 닫고 재실행")
        return EXIT_FAIL
    if rc_m == 2:
        record(MINE_STAGE, False, time.time() - _t, "신호 0건")
        print("\n[!] 이 기간에 분석할 메일·일정이 없습니다 — 화면의 [수집·제외 현황]에서 남긴 행과 뺀 항목을 확인하세요.")
        print("    (Outlook 앱은 클래식 Outlook 이 켜져 있어야 합니다 · Outlook 웹은 전용 Edge 창에서 로그인 1회가 필요합니다)")
        RUN["finished"] = t_end
        record("종료", False, 0.0, "신호 0건 — 수집 자료가 기간과 맞는지 확인")
        return EXIT_FAIL
    err = next((ln for ln in reversed(tail) if "Error" in ln or "오류" in ln or "Traceback" in ln), tail[-1] if tail else "")
    record(MINE_STAGE, False, time.time() - _t, f"오류로 중단: {err[:200]}")
    print(f"\n[!] {MINE_STAGE}이 오류로 중단됐습니다 — 위 오류 줄을 확인하세요.")
    RUN["finished"] = t_end
    record("종료", False, 0.0, f"{MINE_STAGE} 오류: {err[:200]}")
    return EXIT_FAIL


def no_ai(d0, d1):
    """--ai 없이 — 판정은 건너뛰고, 지난 AI 실행의 후보가 있으면 근거 건수만 다시 센다. → 일부만인가(False)."""
    record("AI 판정", False, 0.0, "AI 판정을 켜지 않고 실행했습니다(--ai 없음)")
    if os.path.exists(os.path.join(ROOT, "report", f"agentic_{d0.replace('-', '')}-{d1.replace('-', '')}.json")):
        print("\n── Agentic AI 후보는 지난 AI 실행 것 — 근거 건수만 새 업무 행으로 다시 셉니다(화면에 '재추출 이후 결과' 표시)")
        agentic_recalc_inproc(d0, d1)
    print(f"\n다음: python run.py --from {d0} --to {d1} --skip-collect --ai   (AI 판정)")
    return False


def run_ai(c, d0, d1):
    r"""--ai — 판정(judge) → 정제(refine) → Agentic AI 후보(agentic) → 업무 흐름(flow). Copilot 은 회사 테넌트 안에서만
    (tools\copilot_auto). → 일부만인가(어느 단계든 0 이 아니게 끝났으면 True)."""
    EDGE["used"] = True                     # 판정 단계들이 전용 Edge 의 Copilot 을 쓴다 — 끝에 사이트 자료를 지운다
    partial = False
    try:
        _tot = float(c.get("aiTotalBudgetMin", 300) or 0)
    except (ValueError, TypeError):
        _tot = 300.0
    if _tot > 0:
        # 한 번의 [분석 실행] 전체(판정+정제+Agentic+업무 흐름) 마감을 자식들에게 물려준다. 업무 흐름(마지막 단계)·Agentic 몫은
        # 선예약 — 앞 단계에는 전체 − 예약분만 물려주고, 그 단계 직전에 돌려준다(합계는 aiTotalBudgetMin 안).
        _flow_reserve, _ag_reserve, _pre = start_ai_clock(c, _tot)
        print(f"   (AI 단계 전체 마감 {_tot:.0f}분 — 업무 흐름 몫 {_flow_reserve:.0f}분·Agentic 몫 {_ag_reserve:.0f}분"
              f" 선예약, 판정·정제는 {_pre:.0f}분 안에서 · config.aiTotalBudgetMin/flowBudgetMin/agenticReserveMin)")
    data = os.path.join(ROOT, "data")
    recheck_consent(data, "AI 판정")       # 단계마다 직전에 시작 확인을 다시 한다(그 사이 [모두 지우기]가 시작됐으면 보내지 않고 멈춘다)
    print("\n── AI 판정 (과제·유형·세부업무 분류) — 시간이 걸립니다")
    _t2 = time.time()
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    # 판정 0건(왕복 전부 실패)이면 judge 는 코드 3 과 {"ok":false,"error","hint"} 를 낸다
    _WATCH_STATE_PATH["p"] = os.path.join(ROOT, "report", f"stage_state_{tag}_judge.json")
    try:
        rc, why_j = _run_capture([sys.executable, os.path.join(ROOT, "judge.py"), "--from", d0, "--to", d1], _child_env())
    finally:
        _WATCH_STATE_PATH["p"] = None
    if rc:
        consent_lost("AI 판정")
    _stub = "스텁 판정(AF32_COPILOT_STUB — 테스트 전용, 실제 Copilot 아님)" if os.environ.get("AF32_COPILOT_STUB") else ""
    if rc == 0:
        _note_j = _stub
    elif rc == 3:
        _note_j = "AI 판정 실패(왕복 전부 실패)"
        if why_j and not why_j.startswith(_note_j):
            _note_j += f" — {why_j}"
        elif why_j:
            _note_j = why_j
    else:
        _note_j = f"judge.py 종료코드 {rc}" + (f" — {why_j}" if why_j else "")
    if _stub and rc != 0:
        _note_j += " · " + _stub
    _thr = run_throttled()
    if _thr:
        say_throttle()
        _note_j = THR_LINE + (f" · {_note_j}" if _note_j else "")
    record("AI 판정", rc in (0, 2), time.time() - _t2,
           ("부분 판정 — 다시 실행하면 남은 신호만 이어서 · " if rc == 2 else "") + str(_note_j or ""))
    if _stub:
        print(f"   [!] {_stub}")
    if rc != 0:
        partial = True
    # 판정이 0 이 아니게 끝났어도 이번 실행에서 판정된 행이 있으면 뒤 단계를 계속한다(정제할 재료는 있다)
    _partial_ok = False
    if rc not in (0, 2):
        _jp = os.path.join(ROOT, "report", f"ai_judgments_{tag}.json")
        try:
            if os.path.exists(_jp) and os.path.getmtime(_jp) >= _t2 - 5:
                with open(_jp, encoding="utf-8") as _f:
                    _jj = json.load(_f)
                _n_judged = int(_jj.get("judged") or 0)
                if _n_judged > 0:
                    _partial_ok = True
                    print(f"   [!] 판정이 끝까지 가지 못했지만 {_n_judged}건은 판정됐습니다 — "
                          "그 결과로 정제·Agentic AI 후보·업무 흐름을 계속합니다")
                    print("       (남은 신호는 다시 실행하면 이어서 판정합니다)")
                    _note_j += f" · 부분 판정 {_n_judged}건으로 뒤 단계 계속"
                    record("AI 판정", False, time.time() - _t2, _note_j)
        except (OSError, ValueError, TypeError, AttributeError):
            _partial_ok = False
    if rc not in (0, 2) and not _partial_ok:
        _skip = (THR_SKIP if _thr else "AI 판정 왕복 전부 실패로 건너뜀" if rc == 3 else "판정 실패로 건너뜀")
        print("   [!] AI 판정 실패 — 화면의 과제는 AI 가 정리한 것이 아니라 규칙이 뽑은")
        print("       임시 결과입니다. 위 judge 로그의 마지막 오류를 보세요.")
        if rc == 3:
            print(f"       판정 왕복이 전부 실패했습니다({why_j[:120] if why_j else '사유 없음'})")
            print("       이번 화면의 '상위(업무 성격)' 분류는 비어 있습니다 — 그 값은 AI 정제가 채우는 것이고,"
                  " 판정이 실패하면 정제를 돌리지 않습니다.")
            print("       → 위 사유를 해결한 뒤 [다시 읽지 않고 분석만]을 켜고 [분석 실행]을 누르면 상위 분류까지 다시 채워집니다.")
            _note_j += " · 상위(업무 성격) 분류 비어 있음 — 해결 후 [다시 읽지 않고 분석만]을 켜고 [분석 실행]"
            record("AI 판정", False, time.time() - _t2, _note_j)
        if not _thr:
            print("       흔한 원인: ① Copilot 로그인 만료(UI [AI 연결 진단]으로 확인)")
            print("                  ② 모델 선택 실패 ③ 회사망 차단")
        print("   → AI 정제·Agentic AI 후보·업무 흐름 건너뜀 (판정 없는 결과를 정제하면 낡은 정제본만 남습니다)")
        record("AI 정제", False, 0.0, _skip)
        record("Agentic 니즈 발굴", False, 0.0, _skip)
        record("워크플로우 분석", False, 0.0, _skip)
        return True
    recheck_consent(data, "AI 정제")
    print("\n── AI 정제 (Level1·상세설명 문장화)")
    _t3 = time.time()
    _WATCH_STATE_PATH["p"] = os.path.join(ROOT, "report", f"stage_state_{tag}_refine.json")
    try:
        # 판정이 사용량 제한으로 멈췄어도 정제는 띄운다 — 보내지 않고 곧바로 접히며(copilot_auto.run_stopped) 기록만 '건너뜀'
        rc2, why_r = _run_capture([sys.executable, os.path.join(ROOT, "refine.py"), "--from", d0, "--to", d1], _child_env())
    finally:
        _WATCH_STATE_PATH["p"] = None
    if rc2:
        consent_lost("AI 정제")
    record("AI 정제", rc2 in (0, 2), time.time() - _t3,
           ai_note(_thr, ("부분 완료 — 다시 실행하면 남은 것만 이어서 · " if rc2 == 2 else "") + str(why_r or "")))
    partial = partial or rc2 != 0
    if rc2 not in (0, 2) and not run_throttled():
        print("   AI 정제 실패 — 화면의 업무 분류 탭에서 다시 실행할 수 있습니다")
    # Agentic AI 후보 — 반복 업무에서 Agentic AI 로 바꿀 만한 후보만 찾는다. 선예약한 Agentic 몫을 돌려준다
    _dl_ag = agentic_deadline()
    if _dl_ag is not None:
        os.environ["AF32_AI_DEADLINE"] = str(_dl_ag)
    recheck_consent(data, "Agentic 니즈 발굴")
    print("\n── Agentic AI 전환 후보 찾기 (반복 업무에서)")
    _t3 = time.time()
    _pre = run_throttled()
    rc2, note2 = run_ai_stage("agentic.py", d0, d1)
    record("Agentic 니즈 발굴", rc2 in (0, 2), time.time() - _t3, ai_note(_pre, note2))
    partial = partial or rc2 != 0
    if rc2 not in (0, 2) and not run_throttled():
        print("   Agentic AI 후보 찾기 실패 — 화면의 Agentic AI 후보 탭에서 다시 시도하세요")
    # 업무 흐름 — 과제별 일의 순서·Agent 가능성(실패해도 분석은 유효). 선예약분 반환 — 마감을 전체로 되돌린다
    if _AI_T0 is not None and _AI_TOT_MIN:
        os.environ["AF32_AI_DEADLINE"] = str(_AI_T0 + _AI_TOT_MIN * 60.0)
    recheck_consent(data, "워크플로우 분석")
    print("\n── 업무 흐름 (일의 순서·Agent 가능성)")
    _t3 = time.time()
    _pre = run_throttled()
    rc2, note2 = run_ai_stage("flow.py", d0, d1)
    record("워크플로우 분석", rc2 in (0, 2), time.time() - _t3, ai_note(_pre, note2))
    partial = partial or rc2 != 0
    if rc2 not in (0, 2) and not run_throttled():
        print("   업무 흐름 분석 실패 — 화면의 워크플로우 탭에서 다시 시도하세요")
    # 업무 흐름 단계가 만든 세부업무 병합 맵을 후보의 근거 건수에 반영 — 왕복 없음·실패 무시
    agentic_recalc_inproc(d0, d1)
    return partial


def build_report(d0, d1):
    r"""개인 리포트(report_out.py --variant local — report\개인리포트_<tag>.html, 이 PC 안에서만). AI 없이 돌려도 만든다.
    → 만들었나."""
    print(f"\n── {REPORT_STAGE} (이 PC 안에서만 — 공유는 화면의 [공유] 탭에서 본인이 고를 때만)")
    t = time.time()
    rc, why = _run_capture([sys.executable, os.path.join(ROOT, "report_out.py"), "--from", d0, "--to", d1,
                            "--variant", "local"], _child_env())
    lj = dict(LAST_JSON)
    ok = rc == 0 and lj.get("ok") is not False
    html = str(lj.get("html") or "")
    note = (os.path.basename(html) if html else "") if ok else (why or str(lj.get("error") or "") or f"report_out.py 종료 코드 {rc}")
    record(REPORT_STAGE, ok, time.time() - t, note)
    if ok:
        if html:
            print(f"   → report\\{os.path.basename(html)}")
    else:
        print("   [!] 개인 리포트를 만들지 못했습니다 — 화면에서 다시 만들 수 있습니다")
    return ok


if __name__ == "__main__":
    sys.exit(main())
