# -*- coding: utf-8 -*-
"""
run.py — LoadMonitor24 통합 실행기: 수집 → 추출 → (AI 판정·내러티브) → 팀 내보내기.

  python run.py --from 2026-05-19 --to 2026-08-17            # 수집 + 추출
  python run.py --from ... --to ... --skip-collect            # 이미 모은 데이터로 추출만
  python run.py --from ... --to ... --ai                      # AI 정제까지 (Copilot 무개입)
  python run.py                                               # 기간 생략 = 올해 1월 1일 ~ 오늘 (화면·bat 기본과 같다)

설계 원칙 (v5):
  · MM = 인정 근무시간 / (8h × 그 달 평일수) — 평일 표준 8h 기준, 근태 부재 차감, 야근·주말은 산출물 있을 때만 가산.
  · 산출물(파일·커밋)이 회의보다 무겁다 → 설계·SW개발이 누락되지 않는다.
  · AI는 분류기가 아니라 **판정자**다 → raw 원문을 읽고 [업무여부·과제·유형·세부업무]를 계층 판정.
  · 배분(비중)은 신호 가중치, 총량(MM)은 가동시간 — 비율과 시간을 분리해 둘 다 정확하게.
"""
import io
import json
import os
import subprocess
from datetime import datetime, timedelta
import csv
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
if __name__ == "__main__":      # import 시엔 건드리지 않는다 — 임포트한 쪽의 stdout 이
    # 교체·GC 되면서 버퍼가 닫혀 이후 출력이 전부 죽는다(refine.py 와 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8
NO_WIN = 0x08000000
_AI_T0 = None            # AI 마감 기준 시각(선예약 반환용)
_AI_TOT_MIN = None


def cfg():
    """config 이 깨져도 실행은 계속한다 — 무방비면 [분석 실행]이 시작도 전에 매번 죽고
    화면은 옛 결과를 계속 보여준다(실측). 설정가이드가 메모장 편집을 안내하므로
    JSON 손상·ANSI 재저장은 예정된 사고다."""
    p = os.path.join(ROOT, "config", "config.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        print("[!] config\\config.json 이 없습니다 — 기본값으로 진행합니다 (복사 누락?)")
        return {}
    except (ValueError, UnicodeDecodeError, OSError) as e:
        print(f"[!] config\\config.json 을 읽지 못했습니다 ({type(e).__name__}) — 기본값으로 진행.")
        print("    메모장 저장 시 인코딩은 UTF-8, JSON 문법(마지막 쉼표·역슬래시)을 확인하세요.")
        return {}


def arg(flag, dflt=""):
    if flag not in sys.argv:
        return dflt
    i = sys.argv.index(flag) + 1
    # 값이 없거나 다음이 플래그면 기본값 — bat 에서 날짜가 비면 인자가 밀린다
    if i >= len(sys.argv) or sys.argv[i].startswith("--"):
        return dflt
    return sys.argv[i]


# ── 실행 이력 — 중단돼도 '어디까지 갔는지'가 남아야 원인을 안다 ──────────
# host 를 남긴다 — 배포본에 남의 report\ 가 딸려 오면 화면이 그것을 '남의 결과'로
# 표시할 수 있어야 한다(실측: 배포 zip 에 개발 PC 산출물 17개가 동봉돼 있었다)
RUN = {"stages": [], "host": os.environ.get("COMPUTERNAME", "")}


def record(name, ok, sec=0.0, note=""):
    r"""단계 결과를 report\last_run.json 에 즉시 반영 (강제 종료돼도 흔적 보존)"""
    RUN["stages"] = [x for x in RUN["stages"] if x["name"] != name]
    RUN["stages"].append({"name": name, "ok": bool(ok), "sec": round(sec, 1),
                          "note": (note or "")[:300]})
    try:
        rep_dir = os.path.join(ROOT, "report")
        os.makedirs(rep_dir, exist_ok=True)
        with open(os.path.join(rep_dir, "last_run.json"), "w", encoding="utf-8") as f:
            json.dump(RUN, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def step(name, cmd, timeout=420):
    print(f"\n── {name}")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        # 마지막 6줄만 찍던 것을 12줄로 — 수집기가 '왜 0건인지' 적는 줄이 정확히 0건일 때
        # 잘려 나가 화면에는 엉뚱한 원인만 남았다(팀즈 0건 실측: '채팅 목록으로 N줄 제외'가 잘렸다).
        tail = out.strip().splitlines()[-12:]
        for ln in tail:
            print("   " + ln)
        # 성공해도 요약 줄을 남긴다 — "PC 가동 2건"처럼 값이 이상할 때 어느 수집기가
        # 무엇을 찾았는지 last_run.json 만으로 원격 진단이 되게 한다.
        record(name, p.returncode == 0, time.time() - t0,
               (tail[-1][:200] if tail else "") if p.returncode == 0
               else " / ".join(tail[-2:]))
        return p.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"   시간 초과({timeout}s) — 건너뜀")
        record(name, False, time.time() - t0, f"시간 초과 {timeout}s")
        return False
    except OSError as e:
        print(f"   실행 실패: {e}")
        record(name, False, time.time() - t0, str(e)[:200])
        return False


def _csv_has_rows(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return sum(1 for ln in f if ln.strip()) > 1
    except OSError:
        return False


def _csv_rows(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return max(0, sum(1 for ln in f if ln.strip()) - 1)
    except OSError:
        return 0


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


def _run_rc(cmd, timeout):
    """수집기 실행 → (종료 코드, 출력 꼬리 6줄). 시간 초과 -1 · 실행 실패 -2. 단계 기록은 호출측이 한다 —
    색인 폴백의 exit 3(저장했지만 일정 불완전)처럼 0 이 아닌 코드에도 뜻이 있을 때 쓴다."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=ROOT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"), creationflags=NO_WIN)
        out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode, out.strip().splitlines()[-6:]
    except subprocess.TimeoutExpired:
        return -1, [f"시간 초과({timeout}s) — 건너뜀"]
    except OSError as e:
        return -2, [f"실행 실패: {e}"[:200]]


def collect_headless(c):
    r"""[수집만] 모드의 무창 수집 — 창을 여는 경로(아웃룩 웹·Copilot·팀즈 웹·팀즈 Copilot)를 생략한다.
    추가 PC 의 메일·팀즈는 계정 단위라 **본 PC 가 같은 사서함을 수집**하고 분석이 중복을 제거한다 —
    추가 PC 의 몫은 그 기계의 로그(PC 가동·파일·git·샘플러)다(제보: "로그만 가져오면 되는 것 아닌가").
    본 PC 분석 실행에는 영향이 없다. 추가 PC 가 유일한 아웃룩인 예외 환경만 false 로."""
    return "--collect-only" in sys.argv and bool(c.get("collectOnlyHeadless", True))


def mail_fallbacks(c, d0, d1, data, ps, col, t_run):
    """Outlook COM 이 이번 실행에서 채우지 못한 파일의 대체 경로 — PC 마다 Outlook 이 달라(새 Outlook
    전용·2016 시작 마법사·COM 미등록) 메일이 통째로 비는 실측(회사 PC3)에 대응한다.
      ① Windows Search 색인(Outlook 을 띄우지 않고 읽음) → ② Outlook 웹 → ③ Copilot 메일·일정 왕복(설정)
    기준은 '신선도'다: COM 이 이번 실행(t_run 이후)에 쓴 파일은 비어 있어도 건드리지 않고(기간에 메일이
    없는 정상 PC 가 매번 Copilot 왕복을 하지 않게), 그렇지 않은 파일은 지난 폴백 자료가 남아 있어도
    --force 로 갱신한다(COM 없는 PC 의 자료가 첫 수집일에 얼어붙지 않게 — 검증에서 확정된 결함).
    폴백은 행을 얻었을 때만 파일을 쓰므로, 재질의가 실패하면 지난 자료는 그대로 남는다.
    · 색인은 반복 회의를 전개하지 못한다(마스터 1건, 감사 outlook-7) — mail_source.json 의 calendar_complete=false
      (exit 3) 면 일정('cal')을 남겨 웹(주 보기 = 회차 전개)으로 다시 읽고, 끝내 못 읽으면 힌트를 남긴다.
    · COM 수집기는 달마다 CSV 를 쓰고 달별 완료 표(coverage.json)를 남긴다. 대체 경로가 CSV 를 다시 쓰면 그 표는
      CSV 와 맞지 않으므로 지운다(수집기도 mail_source.source 가 com 이 아니면 표를 버린다 — 이중 안전장치)."""
    paths = {"mail": os.path.join(data, "outlook", "mail.csv"),
             "cal": os.path.join(data, "outlook", "calendar.csv")}
    src_p = os.path.join(data, "outlook", "mail_source.json")
    cov_p = os.path.join(data, "outlook", "coverage.json")
    cal_incomplete = {"n": 0, "mtime": None}    # 색인이 남긴 불완전한 일정 — calendar.csv 가 그 뒤 다시 쓰이면 해소

    def needs(k):            # COM 이 이번 실행에서 쓰지 않은 파일(없거나 t_run 이전 것) — 색인의 불완전한 일정도 '필요'
        mt = _mtime(paths[k])
        if mt is None or mt < t_run:
            return True
        if k == "cal" and cal_incomplete["mtime"] is not None and mt <= cal_incomplete["mtime"]:
            return True
        return False

    def finish():
        """마무리 — 대체 경로가 이번 실행에서 CSV 를 썼으면(mail_source.source 가 com 이 아님) COM 의 달별 완료 표를 지운다.
        표를 두면 다음 COM 실행이 '완료된 달'을 건너뛰어 색인·웹 자료(반복 회의 미전개 등)가 영영 남는다(재검증 지적)."""
        src_now = _read_json(src_p) if (_mtime(src_p) or 0) >= t_run - 2 else {}
        if isinstance(src_now, dict) and src_now.get("source") and src_now.get("source") != "com":
            try:
                if os.path.exists(cov_p):
                    os.remove(cov_p)
                    print(f"   (COM 달별 완료 표 삭제 — {src_now.get('source')} 경로가 메일·일정을 다시 썼으므로 다음 COM 수집은 처음부터)")
            except OSError:
                pass
        if cal_incomplete["mtime"] is not None and needs("cal"):
            record("Outlook 일정 완전성", False, 0.0,
                   f"색인 경로: 반복 회의 {cal_incomplete['n']}건 미전개(회의 시간 과소) — 전용 Edge 창의 Outlook 탭에 "
                   "회사 계정으로 로그인한 뒤 [Outlook 웹 읽기] 또는 재실행")
        return not needs("mail")

    # COM 이 이번 실행에 쓰긴 했는데 0건인 파일 — 위 '신선도' 기준에 따라 대체 경로를 돌리지 않는다.
    # 그 판단은 'COM 이 제대로 붙었다' 가 참일 때만 옳다. 보조 계정·다른 기본 프로필에 붙었거나
    # Restrict 로캘이 어긋난 PC 에서는 0건이 정상이 아닌데, 지금까지 이 상태는 화면 어디에도
    # 뜨지 않아 메일 신호가 통째로 빈 채 로드율이 나왔다(감사 지적). 절충은 그대로 두고 알리기만 한다.
    blank = [{"mail": "메일", "cal": "일정"}[k] for k in ("mail", "cal")
             if not needs(k) and not _csv_has_rows(paths[k])]
    if blank:
        why = (f"Outlook COM 이 {'·'.join(blank)}을(를) 0건으로 채웠습니다 — 대체 경로(색인·웹·Copilot)는 "
               "설계상 건너뜁니다. 이 기간에 정말 없었다면 정상이고, 아니라면 COM 이 다른 프로필·계정에 "
               "붙은 것입니다 → 대시보드 [Outlook 웹 읽기] 로 확인하세요")
        print(f"\n   [!] {why}")
        record("Outlook 메일 0건 점검", True, 0.0, why)

    kinds = [k for k in ("mail", "cal") if needs(k)]
    if not kinds:
        return finish()
    stale = [k for k in kinds if _csv_has_rows(paths[k])]
    print("\n── Outlook 결과를 이번 실행에서 얻지 못해 대체 경로로 다시 시도합니다 (이 PC 의 Outlook 버전·상태 때문일 수 있음)"
          + (f" — 지난 대체 수집 자료({', '.join(stale)}) 갱신" if stale else ""))
    only = ["-Only", kinds[0]] if len(kinds) == 1 else []
    name1 = "Outlook 대체① Windows Search 색인 (COM 불가 PC)"
    print(f"\n── {name1}")
    t1 = time.time()
    rc1, tail1 = _run_rc(ps + [os.path.join(col, "Get-OutlookIndex.ps1"), "-From", d0, "-To", d1, "-Force"] + only, 240)
    for ln in tail1:
        print("   " + ln)
    src = _read_json(src_p) if (_mtime(src_p) or 0) >= t1 - 2 else {}     # 이번 색인 실행이 쓴 것만(파일 시각 해상도 여유 2초)
    if src.get("source") == "index" and src.get("calendar_complete") is False:
        cal_incomplete = {"n": int(src.get("calendar_recurring_masters") or 0), "mtime": _mtime(paths["cal"]) or 0}
    if rc1 == 3:
        record(name1, True, time.time() - t1,
               f"저장했지만 일정 불완전 — 반복 회의 마스터 {cal_incomplete['n']}건 미전개(색인 한계) → Outlook 웹으로 일정 재시도")
    else:
        record(name1, rc1 == 0, time.time() - t1,
               (tail1[-1][:200] if tail1 else "") if rc1 == 0 else " / ".join(tail1[-2:]))
    kinds = [k for k in kinds if needs(k)]
    if not kinds:
        return finish()
    months = max(1, (date.fromisoformat(d1) - date.fromisoformat(d0)).days // 30 + 1)
    # ② Outlook 웹 — 버전 무관·LLM 무관(지어낸 행 없음). 전용 Edge 프로필에 회사 계정 로그인 1회 필요.
    #    종료 코드 2 = 로그인 필요 → 단계는 실패로 남되 사유를 명확히 적는다(화면이 그대로 보여준다).
    if collect_headless(c):
        record("Outlook 대체② Outlook 웹", True, 0.0,
               "수집만 모드 — 창 여는 경로 생략(메일은 본 PC 가 같은 계정으로 수집 · 분석 때 중복 제거)")
        record("Outlook 대체③ Copilot 메일·일정", True, 0.0,
               "수집만 모드 — Copilot 은 판정 전용, 추가 PC 수집엔 쓰지 않습니다(config.collectOnlyHeadless)")
        return finish()
    if c.get("mailViaWeb", True) and "--no-mail-web" not in sys.argv:
        only = ["--only", kinds[0]] if len(kinds) == 1 else []
        name2 = "Outlook 대체② Outlook 웹 (전용 Edge 프로필 — 버전 무관)"
        t2 = time.time()
        try:
            p2 = subprocess.run([sys.executable, os.path.join(col, "Get-OutlookWeb.py"),
                                 "--from", d0, "--to", d1, "--force"] + only,
                                capture_output=True, timeout=180 + 150 * months, cwd=ROOT,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=NO_WIN)
            out2 = (p2.stdout or b"").decode("utf-8", "replace") + (p2.stderr or b"").decode("utf-8", "replace")
            tail2 = out2.strip().splitlines()[-6:]
            print(f"\n── {name2}")
            for ln in tail2:
                print("   " + ln)
            if p2.returncode == 2:
                record(name2, False, time.time() - t2,
                       "로그인 필요 — 전용 Edge 창(Copilot 과 같은 창)의 Outlook 탭에서 회사 계정을 1회 선택/로그인한 뒤 다시 실행")
            else:
                record(name2, p2.returncode == 0, time.time() - t2,
                       (tail2[-1][:200] if tail2 else "") if p2.returncode == 0 else " / ".join(tail2[-2:]))
        except subprocess.TimeoutExpired:
            print(f"\n── {name2}\n   시간 초과 — 건너뜀")
            record(name2, False, time.time() - t2, "시간 초과")
        except OSError as e:
            record(name2, False, time.time() - t2, str(e)[:200])
        kinds = [k for k in kinds if needs(k)]
        if not kinds:
            return finish()
    else:
        record("Outlook 대체② Outlook 웹", True, 0.0, "건너뜀(config.mailViaWeb=false)")
    if not c.get("mailViaCopilot", True) or "--no-mail-copilot" in sys.argv:
        record("Outlook 대체③ Copilot 메일·일정", True, 0.0, "건너뜀(config.mailViaCopilot=false)")
        return finish()
    only = ["--only", kinds[0]] if len(kinds) == 1 else []
    step("Outlook 대체③ Copilot 메일·일정 왕복 (COM·색인·웹 모두 불가 PC)",
         [sys.executable, os.path.join(col, "Get-MailViaCopilot.py"), "--from", d0, "--to", d1, "--force"] + only,
         300 + 600 * months * 2)
    return finish()


def _outlook_budget(c, d0, d1):
    """Outlook COM 수집 한 회차의 시간 예산(초) — config.outlookBudgetSec(0 = 자동). 자동은 240 + 60×개월(360~900).
    수집기가 달 단위로 이어서 읽으므로(data\\outlook\\coverage.json) 예산 안에 못 끝내도 다음 회차·다음 실행이
    남은 달을 잇는다 — 예전 고정 360초는 메일이 많은 PC 에서 오래된 달을 영영 빠뜨렸다(실측 제보: 1~5월 공백)."""
    months = max(1, (date.fromisoformat(d1) - date.fromisoformat(d0)).days // 30 + 1)
    try:
        v = int(c.get("outlookBudgetSec") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else max(360, min(900, 240 + 60 * months))


def collect_outlook(c, d0, d1, data, ps, col):
    r"""Outlook COM 수집 — 기간의 달을 최신 달부터 읽고, 예산에 닿아 못 읽은 달(coverage: partial)이 남으면
    진행이 있는 한 같은 실행 안에서 최대 2회 더 이어서 읽는다(회차마다 완료된 달은 건너뛰므로 앞으로만 간다).
    그래도 남으면 last_run.json 에 미수집 달을 적고 화면(수집 데이터 현황·주간 활동 추이)이 그것을 보여 준다."""
    budget = _outlook_budget(c, d0, d1)
    src_p = os.path.join(data, "outlook", "mail_source.json")
    ok, prev_unc, src = False, None, {}

    def _fresh_src(t_start):
        """이번 회차가 쓴 mail_source.json 만 믿는다 — 건너뜀·실패·시간 초과 뒤에는 지난 실행의 파일이 남아 있다(재검증 지적)"""
        mt = _mtime(src_p)
        return (_read_json(src_p) or {}) if (mt is not None and mt >= t_start - 2) else {}

    for i in range(3):
        name = ("Outlook 메일·일정 (클래식 Outlook을 켜두세요)" if i == 0
                else f"Outlook 메일·일정 이어서 수집 {i + 1}/3 (남은 달)")
        # 2회차부터는 -NoRefresh — 1회차가 이미 읽은 최신·재수집 달을 건너뛰고 못 읽은 달만 잇는다(예산이 작으면
        # 최신 달 재수집에 예산이 다 닳아 옛 달에 영영 못 가던 것, 재검증 실측)
        t_pass = time.time()
        ok = step(name, ps + [os.path.join(col, "Get-OutlookData.ps1"), "-From", d0, "-To", d1,
                              "-BudgetSec", str(budget)] + (["-NoRefresh"] if i else []), budget + 120)
        src = _fresh_src(t_pass)
        if not ok or src.get("source") != "com" or src.get("coverage_complete", True):
            break
        unc = list(src.get("uncovered_months") or [])
        partial = list(src.get("partial_months") or [])
        # 진행 = 미수집 달이 줄었거나, 같은 달을 이어 읽는 중(부분 표식) — 둘 다 아니면 멈춘다
        if prev_unc is not None and len(unc) >= len(prev_unc) and not partial:
            print("   (진행이 없어 이어서 수집을 멈춥니다 — Outlook 이 느리거나 응답하지 않습니다)")
            break
        prev_unc = unc
        print(f"   미수집 달 {len(unc)}개({', '.join(unc[:6])}{' …' if len(unc) > 6 else ''}) — 이어서 읽습니다")
    if src.get("source") == "com":
        ri = list(src.get("refresh_incomplete") or [])
        if ri:
            print(f"   [!] 재수집이 끊긴 달 {', '.join(ri)} — 지난 수집분을 그대로 두었습니다(새 메일·일정 변경은 다음 실행에서)")
            record("Outlook 재수집", False, 0.0, f"끊긴 재수집: {', '.join(ri)} — 지난 수집분 유지, 다음 실행에서 다시")
        if not src.get("coverage_complete", True):
            unc = list(src.get("uncovered_months") or [])
            print(f"   [!] 메일·일정 미수집 달 {len(unc)}개: {', '.join(unc)} — 다음 [분석 실행]이 이어서 읽습니다"
                  " (그동안 이 달들의 메일·회의는 로드율·주간 추이에 빠져 있습니다)")
            record("Outlook 수집 범위", False, 0.0,
                   f"미수집 달 {len(unc)}개: {', '.join(unc)} — 다음 실행이 이어서 수집(그 달의 메일·회의는 아직 빠짐)")
    return ok


def _sampler_running():
    """Start-ActivitySampler.ps1 을 돌리는 PowerShell 프로세스 수 (확인 불가면 None)"""
    try:
        # 점검 프로세스 자신의 명령줄에도 이 문자열이 있다 — $PID 는 뺀다
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                            "@(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe' or Name='pwsh.exe'\" "
                            "| Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like '*Start-ActivitySampler*' }).Count"],
                           capture_output=True, timeout=40, creationflags=NO_WIN)
        return int((p.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
        return None


def ensure_sampler(c, data, col):
    """수집 시작 시 창 샘플러 생존 점검(config.autoRestartSampler, 기본 true) — 마지막 샘플이 10분 이상 오래됐으면
    schtasks 기본 '3일 실행 제한' 등으로 조용히 멈춘 것이므로 Start-ActivitySampler.ps1 을 분리 실행한다(감사 A26).
    샘플러를 한 번도 켜지 않은 PC(activity 파일 없음)는 건드리지 않고, 이미 도는 인스턴스가 있으면 두 개를 띄우지 않는다."""
    if not c.get("autoRestartSampler", True) or "--no-sampler" in sys.argv:
        return
    import glob
    act = glob.glob(os.path.join(data, "activity", "activity_*.csv"))
    if not act:
        return
    age_min = (time.time() - max((_mtime(p) or 0) for p in act)) / 60
    if age_min <= 10:
        return
    script = os.path.join(col, "Start-ActivitySampler.ps1")
    if not os.path.exists(script):
        return
    n_run = _sampler_running()
    if n_run is None or n_run > 0:
        why = (f"프로세스 {n_run}개가 살아 있어 재기동하지 않음" if n_run else "프로세스 확인 실패 — 재기동하지 않음")
        print(f"\n── 창 샘플러 점검: 마지막 기록 {age_min:.0f}분 전 · {why}")
        record("창 샘플러 점검", True, 0.0, f"마지막 기록 {age_min:.0f}분 전 · {why}")
        return
    try:
        # 분리 실행 — 중간 PowerShell 이 Start-Process 로 띄우고 바로 끝나므로 샘플러는 run.py 의 프로세스 트리 밖에
        # 남는다(대시보드가 분석을 중단해도 살아남음, 숨김 창·입출력 없음). 로그온 시 자동 시작은 설정가이드 §4.
        launcher = ("Start-Process -FilePath powershell -WindowStyle Hidden -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', "
                    "'-ExecutionPolicy', 'Bypass', '-File', '\"" + script.replace("'", "''") + "\"')")
        p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", launcher],
                           cwd=ROOT, capture_output=True, timeout=60, creationflags=NO_WIN)
        ok = p.returncode == 0
        err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:] if not ok else []
        print(f"\n── 창 샘플러 재기동: 마지막 기록 {age_min:.0f}분 전 → collect\\Start-ActivitySampler.ps1 분리 실행 (config.autoRestartSampler)"
              + ("" if ok else f" — 실패: {' '.join(err)[:120]}"))
        record("창 샘플러 재기동", ok, 0.0, f"마지막 기록 {age_min:.0f}분 전 — 분리 실행" + ("" if ok else f" 실패: {' '.join(err)[:150]}"))
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"\n── 창 샘플러 재기동 실패: {e}")
        record("창 샘플러 재기동", False, 0.0, str(e)[:200])


def run_ai_stage(script, d0, d1, retry_wait=15):
    """판정 뒤 단계(Agentic·워크플로우)를 돌린다. Copilot 은 긴 판정 뒤에 일시적으로
    응답을 거부하는 일이 있어(실측: 뒤 단계만 실패), 실패하면 잠시 쉬고 1회 재시도한다.
    반환: (rc, note)."""
    cmd = [sys.executable, os.path.join(ROOT, script), "--from", d0, "--to", d1]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", LM_LAUNCHER="run")
    _tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    _stage_id = {"agentic.py": "agentic", "flow.py": "flow", "refine.py": "refine",
                 "judge.py": "judge"}.get(os.path.basename(script), os.path.basename(script))
    _WATCH_STATE_PATH["p"] = os.path.join(ROOT, "report", f"stage_state_{_tag}_{_stage_id}.json")
    try:
        rc, why = _run_capture(cmd, env)
    finally:
        _WATCH_STATE_PATH["p"] = None
    if rc == 0:
        return 0, ""
    if rc == 2:
        # v3 rc 규약: 2 = 부분(이어가기 가능 — 예산·정체 자가 중단으로 남은 묶음이 있다).
        # 다음 실행이 이어서 하므로 재시도하지 않고, 뒤 단계는 계속 진행한다.
        return 2, str(why or "부분 완료 — 다시 실행하면 남은 것만 이어서")
    if "중단했습니다" in str(why or ""):
        # 정체 감지·시간 상한으로 끊은 것은 다시 보내도 같은 벽에 닿는다 — 예전에는 이 경우도 재시도해
        # 한 단계가 상한을 두 번 썼다(최악 360분, 감사 실측).
        print(f"   {script} 를 중단했습니다 — 같은 벽에 다시 닿으므로 재시도하지 않습니다")
        return rc, why
    print(f"   첫 시도 실패(코드 {rc}) - {retry_wait}초 뒤 1회 재시도합니다")
    time.sleep(retry_wait)
    rc, why2 = _run_capture(cmd, env)
    if rc == 0:
        return 0, "1회 재시도 후 성공"
    # 사유를 기록에 남긴다 — 예전에는 '코드 1' 만 남아 사용자도 나도 원인을 볼 수 없었다
    return rc, (f"재시도에도 실패: {why2 or why}" if (why2 or why)
                else f"재시도에도 실패(코드 {rc}) - 탭의 수동 실행으로 다시")


# v3: 감시기 한 벌 — core/watch (run.py·ui/app.py 복제 3함수를 모았다 · 구조 감사 4계층).
# 신판 자식은 상태 파일 하트비트로 생존을 알린다 — 긴 왕복의 stdout 침묵을 죽음으로 오진하지 않는다.
from watch import kill_tree  # noqa: E402,F401 - 기존 호출부 이름 유지
from watch import stage_limits as _core_stage_limits  # noqa: E402
from watch import watch_child as _core_watch_child  # noqa: E402

_WATCH_STATE_PATH = {"p": None}      # 다음 watch_child 호출이 볼 상태 파일 — run_ai_stage 가 세팅


def _stage_limits():
    return _core_stage_limits(cfg() if "cfg" in globals() else {})


def watch_child(p, on_line, label, beat_sec=120):
    return _core_watch_child(p, on_line, label, beat_sec=beat_sec,
                             cfg_dict=(cfg() if "cfg" in globals() else {}),
                             state_path=_WATCH_STATE_PATH.get("p"))


def _run_capture(cmd, env):
    r"""자식 출력을 화면에 그대로 흘리면서, 실패 사유만 따로 건져 낸다.

    자식은 마지막 줄에 JSON 한 줄을 낸다({"ok":false,"error":...}). 그 줄을 잡아
    last_run.json 에 실어야 화면이 '왜 안 됐는지' 를 말할 수 있다."""
    try:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, bufsize=1, text=True,
                             encoding="utf-8", errors="replace")
    except OSError as e:
        return 1, f"실행 실패({type(e).__name__})"
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
    if stopped:
        return (rc or 1), stopped
    if rc == 0:
        return 0, ""
    why = str(last_json.get("error") or "")
    if last_json.get("hint"):
        why = (why + " — " + str(last_json["hint"]))[:200] if why else str(last_json["hint"])[:200]
    if not why:
        why = next((x for x in reversed(tail) if not x.startswith("{")), "")[:200]
    return rc, why


def invalidate_ai_outputs(d0, d1):
    r"""'업무 로드 추출' 성공 직후 — 같은 tag 의 지난 판정 산출물(정제본·판정 기록·버림 장부·정제 매핑)을
    <이름>.stale 로 개명한다(V-01). 예전에는 무AI 재실행·판정 실패·중단 뒤에도 옛 정제본이 '현재 결과' 로 남아
    대시보드 표(옛 정제본)·KPI(새 meta)·분석리포트(새 원본)가 서로 다른 값을 보였다. agentic/workflow 결과는
    남긴다 — 화면이 '재추출 이후 결과' 로 표시하고, 무AI 실행이면 MM 실측만 새 행으로 다시 센다.
    반환: (개명한 이름 목록, 실패 목록). 실패해도 화면은 mtime 규칙(정제본 < 원본)으로 원본을 고른다."""
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    rep = os.path.join(ROOT, "report")
    # v3: ai_judgments 는 무효화하지 않는다 — judge 가 내용 sig 로 유효분만 회수한다('이어서 판정').
    # v2 는 매 실행 .stale 개명이 재개 자료를 없애, 부분 실패의 재개 단위가 '스테이지 전체'였다.
    names = [f"mm_rows_{tag}_refined.csv",
             f"dropped_signals_{tag}.csv", f"refine_map_{tag}.json"]
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
    """agentic_<tag>.json 의 load_mm 을 실측으로 다시 센다(agentic.recalc_file, Copilot 왕복 없음).
    워크플로우 단계 뒤에 부른다 — 세부업무 병합 맵이 그때 처음 생기기 때문(F5). 어떤 실패도
    분석 전체를 실패로 만들지 않는다. 반환: 저장했으면 True."""
    tag = f"{d0.replace('-', '')}-{d1.replace('-', '')}"
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import agentic
        ap = agentic.recalc_file(tag, log=lambda m: print("   " + str(m)))
        if not ap:
            print("   (Agentic 실측 재계산 생략 — agentic 결과 파일이나 업무 행이 없음)")
        return bool(ap)
    except Exception as e:  # noqa: BLE001 - 재계산 실패는 무시(기존 agentic 파일 그대로)
        print(f"   (Agentic 실측 재계산 건너뜀: {type(e).__name__}: {str(e)[:80]})")
        return False


def machine_id():
    r"""이 PC 의 안정적인 식별자(없으면 빈 문자열).

    클라우드·VDI 는 접속할 때마다 COMPUTERNAME 이 바뀌는 경우가 있다. 이름만으로 '다른 PC' 를
    판정하면 실행할 때마다 data\추가PC\<새 이름>\ 이 하나씩 생기고 매번 전량 재수집이 걸려,
    프로필을 줄여 놔도 폴더가 이쪽으로 다시 부푼다(설계 검증 지적). 레지스트리의 MachineGuid 는
    OS 설치 단위로 고정이라 세션 이름이 바뀌어도 같은 값이다. 못 읽으면 이름 비교로 되돌아간다.
    """
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return str(winreg.QueryValueEx(k, "MachineGuid")[0]).strip()
    except (OSError, ImportError, IndexError, ValueError):
        return ""


def register_sampler_once(ps, col):
    r"""창 샘플러 등록이 없으면 1회 등록한다(schtasks/COM 은 Register-Samplers.ps1 이 판단).
    이미 등록돼 있으면 그 스크립트가 아무것도 바꾸지 않는다 — 매 실행 호출해도 부작용이 없다.
    실패(정책·권한)는 기록만 하고 진행한다."""
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", "LoadMonitor24-Sampler"],
                           capture_output=True, timeout=30, creationflags=NO_WIN)
        if r.returncode == 0:
            return True                     # 이미 등록돼 있다
    except (OSError, subprocess.SubprocessError):
        pass
    ok = step("창 샘플러 자동 등록(1회 · 등록 즉시 + 로그온마다 시작)",
              ps + [os.path.join(col, "Register-Samplers.ps1")], 180)
    if ok:
        print("   샘플러가 지금부터 백그라운드로 기록합니다(창 1분·팀즈 5분 주기) — 수집의 일부입니다.")
    if not ok:
        print("   샘플러 자동 등록이 되지 않았습니다 — 보안 정책이 막는 환경일 수 있습니다."
              " LoadMonitor24-샘플러등록.bat 을 한 번 실행해 주세요(없어도 분석은 됩니다).")
    return ok


def pc_history_gap(data, d0, d1, fresh_hours=None):
    r"""저장된 PC 가동 기록이 요청 기간을 못 덮거나 오래됐나 → (갱신 필요, 사유).
    화면의 추이 선과 분석의 PC 하한은 **저장된 data\pc** 만 본다. 그래서 수집이 그 기간에 대해
    한 번도 돌지 않았거나(=0h) 오래된 채로 [재분석만] 을 눌러도 숫자가 낫지 않았다(제보 실측:
    지금 수집하면 704.7h 인데 저장된 파일은 0h). 이 판단으로 PC 이력만 자동 보강한다."""
    try:
        fresh_hours = float(cfg().get("pcRefreshHours", 12) if fresh_hours is None else fresh_hours)
    except (ValueError, TypeError):
        fresh_hours = 12.0
    pcdir = os.path.join(data, "pc")
    on_p = os.path.join(pcdir, "pc_on.csv")
    if not os.path.exists(on_p) or os.path.getsize(on_p) < 40:
        return True, "저장된 PC 가동 기록이 없습니다"
    # v3: 판정 근거를 pc_source.json 의 range(파생 캐시의 자기 신고)에서 **원장 실측**으로.
    # v2 는 짧은 기간 수집이 range 를 좁혀 써서 '기간 못 덮음' 오판 → 12h 마다 파괴적 재작성이
    # 반복됐다(구조 감사 실측). v3 재수집은 append 전용이라 잦아도 해가 없지만, 판정 자체를
    # 실제 데이터로 한다. 요청 시작이 원장 첫 기록보다 훨씬 앞서는 것은 롤오버로 못 되살리는
    # 과거라 재수집 사유가 아니다 — 끝(최근) 쪽만 본다.
    dates = []
    for f2 in (os.path.join(pcdir, "pc_on.csv"),):
        try:
            with open(f2, encoding="utf-8-sig", errors="replace", newline="") as fh:
                dates = sorted({(r.get("date") or "")[:10] for r in csv.DictReader(fh)
                                if (r.get("date") or "")[:10]})
        except (OSError, csv.Error):
            dates = []
    if not dates:
        return True, "저장된 PC 가동 기록이 비어 있습니다"
    if dates[-1] < d1:
        return True, f"저장된 기록은 {dates[-1]} 까지입니다 (요청 {d1})"
    _hint_floor = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    if dates[0] > d0 and dates[0] > _hint_floor:
        # 시작 쪽 확장 — 브라우저 힌트(≈90일)·샘플러가 아직 닿는 범위만. 그보다 먼 과거는 어떤
        # 재수집으로도 못 메우므로 매 실행 헛수고를 만들지 않는다(최종 검증 INFO).
        return True, f"저장된 기록은 {dates[0]} 부터입니다 (요청 {d0} — 힌트·샘플러가 닿는 만큼 보강)"
    if fresh_hours > 0:
        age_h = (time.time() - os.path.getmtime(on_p)) / 3600.0
        if age_h > fresh_hours:
            return True, f"저장된 기록이 {age_h:.0f}시간 전 것입니다"
    return False, ""


def collect_pc_only(data, d0, d1, ps, col, why=""):
    r"""PC 가동 이력·힌트만 모은다 — [재분석만] 에서도 PC 시간이 최신이 되게(수집 전체는 켜지 않는다)."""
    print("\n" + f"[PC 이력] {why} — PC 가동 기록만 다시 모읍니다(수십 초 · 수집 전체는 하지 않습니다)")
    ok1 = step("PC 가동 이력(자동 보강)",
               ps + [os.path.join(col, "Get-PcOnHistory.ps1"), "-From", d0, "-To", d1], 300)
    step("PC 가동 보강 (브라우저 방문 시각 — URL 미수집)",
         [sys.executable, os.path.join(col, "Get-PcOnHints.py"), "--from", d0, "--to", d1], 240)
    return ok1


def migrate_extra_pc_ledgers(data):
    r"""추가PC\<이름>\pc 를 v3 원장으로 1회 이행한다(멱등 — 앵커가 생기면 다시 안 한다).
    이행되면 그 폴더도 '캐시 ≡ 파생' 이 되어 본 PC 와 같은 규칙으로 읽힌다. 남의 폴더라
    앵커는 그 폴더 자신의 첫 물리 이벤트로만 잡는다(--foreign)."""
    base = os.path.join(data, "추가PC")
    if not os.path.isdir(base):
        return
    try:
        sys.path.insert(0, os.path.join(ROOT, "core"))
        import pc_ledger
    except ImportError:
        return
    for name in sorted(os.listdir(base)):
        pcdir = os.path.join(base, name, "pc")
        if not os.path.isdir(pcdir) or os.path.exists(os.path.join(pcdir, "pc_anchor.json")):
            continue
        try:
            r = pc_ledger.ingest(pcdir, own_pc=False)
            if r["migrated"] or r["days"]:
                print("[원장] 추가PC" + chr(92) + f"{name}: 구판 기록 이행 {r['migrated']}건 · 파생 {r['days']}일")
        except (OSError, ValueError) as e:
            print("[원장] 추가PC" + chr(92) + f"{name}: 이행 보류({type(e).__name__}) — 기존 기록 그대로")


def own_data_empty(data):
    r"""이 PC 가 직접 모은 자료가 없는가 — data\ 의 수집 폴더(추가PC 제외)에 쓸 만한 CSV 가 하나도 없으면 True.

    폴더째 옮겨 오면 지난 PC 자료는 data\추가PC\<지난 PC>\ 로 보관되고 이 PC 것은 아직 없다. 그 상태에서
    [재분석만]을 누르면 예전에는 수집을 건너뛰어 **옮겨 온 PC 의 자료만** 분석했다(제보). 이 함수로 그 상태를 알아낸다."""
    for sub in ("outlook", "files", "pc", "m365", "activity", "manual"):
        p = os.path.join(data, sub)
        if not os.path.isdir(p):
            continue
        try:
            for n in os.listdir(p):
                if n.lower().endswith(".csv") and os.path.getsize(os.path.join(p, n)) > 200:
                    return False
        except OSError:
            continue
    return True


def has_extra_pc(data):
    r"""data\추가PC\<PC>\ 보관본이 하나라도 있는가"""
    base = os.path.join(data, "추가PC")
    try:
        return os.path.isdir(base) and any(os.path.isdir(os.path.join(base, n)) for n in os.listdir(base))
    except OSError:
        return False

def archive_other_pc(data):
    r"""추가 PC 취합 — 폴더째 다른 PC 로 옮겨 왔으면, 지난 PC 의 수집 데이터를
    data\추가PC\<지난 PC 이름>\ 으로 보관하고 이번 PC 것을 새로 수집하게 한다.
    분석은 본 폴더 + 추가PC\* 를 전부 합쳐 계산한다(중복은 자동 제거)."""
    try:
        name_f = os.path.join(data, "pc_name.txt")
        id_f = os.path.join(data, "pc_id.txt")
        here = os.environ.get("COMPUTERNAME", "").strip()
        here_id = machine_id()
        prev = prev_id = ""
        if os.path.exists(name_f):
            prev = open(name_f, encoding="utf-8-sig").read().strip()
        if os.path.exists(id_f):
            prev_id = open(id_f, encoding="utf-8-sig").read().strip()
        # 둘 다 식별자가 있으면 식별자로 판정한다(이름이 바뀌는 VDI 대응). 하나라도 없으면 —
        # 예전 판본에서 올라온 폴더이거나 레지스트리를 못 읽는 환경 — 기존대로 이름으로 판정한다.
        if prev_id and here_id:
            moved_pc = prev_id != here_id
        else:
            moved_pc = bool(prev and here and prev != here)
        if moved_pc:
            # 폴더 이름은 사람이 읽는 것이라 이름표를 쓴다. 이름표가 없는데 식별자만 다른 경우
            # (예전 판본에서 올라온 폴더)에도 폴더 이름은 있어야 하므로 대체 이름을 만든다.
            keep = os.path.join(data, "추가PC", prev or ("이전PC-" + time.strftime("%Y%m%d")))
            # 이미 있는 보관본은 지우지 않는다 — 옮기다 실패하면 그 PC 자료를 통째로 잃는다
            # (검증 확정). 분석은 추가PC\* 를 전부 합치므로 형제 폴더로 두면 된다.
            if os.path.isdir(keep):
                keep = keep + "-" + time.strftime("%Y%m%d-%H%M%S")
            os.makedirs(keep, exist_ok=True)
            moved, failed = [], []
            for sub in ("outlook", "files", "pc", "m365", "activity"):
                src_d = os.path.join(data, sub)
                if not os.path.isdir(src_d):
                    continue
                try:
                    # 같은 볼륨 rename 은 원자적 — 실패해도 원본이 그대로 남는다.
                    # shutil.move 는 복사+삭제로 넘어가며 실패 시 원본을 훼손할 수 있다.
                    os.rename(src_d, os.path.join(keep, sub))
                    moved.append(sub)
                except OSError as ex2:
                    failed.append(f"{sub}({type(ex2).__name__})")
            # 보관하며 data\activity 를 통째로 옮기면 그 폴더가 사라진다. 그런데 샘플러는 루프에 들어가기
            # **전에 한 번만** 폴더를 만들므로, 돌고 있던 샘플러는 살아서 CPU 만 쓰고 한 줄도 못 쓰는
            # 좀비가 된다(오류 로그도 같은 사라진 폴더에 쓰려 해서 안 남는다 — 실측). 게다가 그 좀비가
            # 뮤텍스를 쥐고 있어 자동 재기동도 '이미 실행 중' 으로 즉사한다. 폴더만 되만들어 주면
            # 다음 틱에 스스로 기록을 재개하는 것을 확인했다.
            for sub in ("activity", "pc"):
                try:
                    os.makedirs(os.path.join(data, sub), exist_ok=True)
                except OSError:
                    pass
            print(f"\n[추가 PC 취합] 지난 수집({prev})을 {os.path.basename(keep)} 폴더로 보관했습니다"
                  f" ({', '.join(moved) or '없음'})")
            if failed:
                print(f"               옮기지 못한 폴더: {', '.join(failed)} — 그 폴더를 쓰는 프로그램"
                      "(탐색기·Excel 등)을 닫고 다시 실행하면 함께 보관됩니다. 자료는 지우지 않았습니다.")
            print(f"               이번 PC({here})의 데이터를 새로 수집하고, 분석은 두 PC 를 합쳐 계산합니다.")
            record("추가 PC 보관", not failed, 0.0,
                   f"{prev} → {os.path.basename(keep)}"
                   + (f" · 옮기지 못함: {', '.join(failed)}" if failed else ""))
        if here_id:
            # 식별자도 어떤 경우에도 남긴다(이름표와 같은 이유). 이것이 있어야 다음 실행이
            # 이름이 바뀐 같은 PC 를 '다른 PC' 로 오해하지 않는다.
            try:
                with open(id_f, "w", encoding="utf-8") as f:
                    f.write(here_id)
            except OSError:
                pass
        if here:
            # 이름표는 어떤 경우에도 남긴다 — 남기지 않으면 다음 실행이 같은 보관을 또 시도해
            # 한 번의 일시적 오류가 영구 손실로 번진다(검증 지적)
            try:
                with open(name_f, "w", encoding="utf-8") as f:
                    f.write(here)
            except OSError:
                pass
    except OSError as ex:
        print(f"[추가 PC 취합] 보관 건너뜀({type(ex).__name__}) — 이번 수집이 기존 데이터를 덮습니다")


def main():
    c = cfg()
    # 기본 기간은 화면(UI 칩 '올해')·LoadMonitor24.bat 과 같은 '올해 1월 1일부터' — 셋이 달라(이번 달 1일 / 최근 3개월 /
    # 올해) 나중에 돈 짧은 결과가 mtime 최신 규칙으로 화면을 차지해 "1월부터 보던 추이가 2주짜리가 됐다" 로 읽혔다(감사 재현).
    d0 = arg("--from") or date.today().replace(month=1, day=1).isoformat()
    d1 = arg("--to") or date.today().isoformat()
    data = os.path.join(ROOT, "data")
    ps = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    col = os.path.join(ROOT, "collect")
    try:                                   # 잘못된 날짜로 수집기 전부를 헛돌리지 않는다
        if date.fromisoformat(d0) > date.fromisoformat(d1):
            print(f"[!] 시작일이 종료일보다 늦습니다: {d0} > {d1}")
            return 1
    except ValueError:
        print(f"[!] 날짜 형식이 잘못됐습니다 (YYYY-MM-DD): --from {d0} --to {d1}")
        return 1
    RUN.update(period=[d0, d1], started=time.strftime("%Y-%m-%d %H:%M"),
               ai_requested=("--ai" in sys.argv), skip_collect=("--skip-collect" in sys.argv),
               finished=None)
    record("시작", True, 0.0)
    print(f"[LoadMonitor24] {d0} ~ {d1}"
          + ("  · AI 판정 포함" if "--ai" in sys.argv else "  · AI 판정 없음(규칙 결과만)"))

    # 추가 PC 취합 — 폴더째 옮겨 온 경우 지난 PC 데이터를 자동 보관 (분석 시 합산)
    # ★ [재분석만](--skip-collect)이어도 **이 PC 자료가 하나도 없고 옮겨 온 보관본이 있으면** 한 번은 수집한다.
    #   예전에는 수집을 통째로 건너뛰어 옮겨 온 PC 의 자료만으로 분석됐다(제보: "현재 PC 것도 추가 집계돼야 한다").
    #   이 PC 자료가 이미 있으면 예전대로 건너뛴다 — [재분석만] 의 뜻(수집 없이 판정만)을 지킨다.
    _skip = "--skip-collect" in sys.argv
    # [재분석만] 이어도 **PC 가동 기록만** 최신으로 만든다 — 화면의 추이 선·PC 하한은 저장된 파일만
    # 보기 때문에, 오래된 채로 다시 눌러도 숫자가 낫지 않았다(제보: "한 번에 되게 하라").
    if _skip:
        _need, _why = pc_history_gap(data, d0, d1)
        if _need:
            collect_pc_only(data, d0, d1, ps, col, _why)
    if _skip and own_data_empty(data) and has_extra_pc(data):
        print("\n[추가 집계] 이 PC 에서 모은 자료가 없고 옮겨 온 보관본(data\\추가PC)만 있습니다 —")
        print("           [재분석만] 이지만 이 PC 자료를 한 번 수집한 뒤 두 PC 를 합쳐 분석합니다.")
        record("추가 집계", True, 0.0, "이 PC 자료 없음 + 추가PC 보관본 있음 — 재분석만이어도 이 PC 수집 1회")
        _skip = False
    if not _skip:
        archive_other_pc(data)
        migrate_extra_pc_ledgers(data)     # 추가PC 보관본 1회 이행(v3 원장·멱등) — 실패해도 계속
        ensure_sampler(c, data, col)       # 멈춘 창 샘플러 재기동 (있던 PC 만)
        # 등록이 아예 없으면 **자동으로 1회 등록**한다 — 이벤트 로그는 롤오버되지만(이 PC 실측:
        # 199일 중 90일만 남음) 샘플러가 돌면 그 뒤 구간은 로그와 무관하게 pc_spans 에 쌓인다.
        # 사용자가 bat 을 따로 돌리지 않아도 되게(제보: "한 번에 되게 하라"). 실패하면 안내만 남긴다.
        if c.get("autoRegisterSampler", True):
            register_sampler_once(ps, col)

        step("PC 가동 이력", ps + [os.path.join(col, "Get-PcOnHistory.ps1"), "-From", d0, "-To", d1], 300)
        # 이벤트 로그가 롤오버로 기간을 못 덮으면 브라우저 '방문 시각'만으로 보강
        # (URL·제목은 조회하지 않는다)
        step("PC 가동 보강 (브라우저 방문 시각 — URL 미수집)",
             [sys.executable, os.path.join(col, "Get-PcOnHints.py"), "--from", d0, "--to", d1], 240)
        t_outlook = time.time()
        collect_outlook(c, d0, d1, data, ps, col)             # 달 단위 이어서 수집 — 예산에 못 끝내면 진행이 있는 한 최대 3회
        mail_fallbacks(c, d0, d1, data, ps, col, t_outlook)   # COM 이 못 채운 파일만 색인 → Copilot 순으로 대체 (PC별 Outlook 차이)
        step("파일 수정 이력", ps + [os.path.join(col, "Get-FileActivity.ps1"), "-From", d0, "-To", d1], 300)
        step("최근 문서 (Recent·MRU)", ps + [os.path.join(col, "Get-RecentFiles.ps1"), "-From", d0, "-To", d1], 180)
        step("git 커밋 (SW개발)", [sys.executable, os.path.join(col, "Get-GitActivity.py"),
                                "--from", d0, "--to", d1], 240)
        # 팀즈: Graph(설정 시) → 실패하면 Copilot 무개입 추출로 자동 대체
        #       (회사 정책이 device code·사용자 동의를 막아도 Copilot 경로는 동작한다)
        teams_ok = False
        if (c.get("graph") or {}).get("clientId"):
            # 비대화 모드 — 토큰이 만료됐을 때 device-code 입력을 기다리며 300초를 버리지 않는다
            # (여기엔 콘솔이 없어 사용자는 그 프롬프트를 볼 수도 없다). 로그인은 --login-only 로.
            teams_ok = step("팀즈 채팅 (Graph)",
                            [sys.executable, os.path.join(col, "Get-TeamsChats.py"),
                             "--from", d0, "--to", d1, "--non-interactive"], 300)
        # 웹 경로 — 메일(Get-OutlookWeb.py)과 같은 방식으로 전용 Edge 프로필에서 팀즈를 읽는다.
        # 앱이 꺼져 있어도 되고, 창 읽기(UIA)처럼 화면에 그려진 부분만 긁는 것이 아니라 문서 구조를
        # 읽으므로 창 크기·테마·팀즈 버전에 좌우되지 않는다(PC 마다 0건이던 제보의 원인).
        # 로그인이 필요하면 2로 끝나 아래 경로로 이어진다 — 그 안내는 수집기가 화면에 남긴다.
        # 앱 우선(config.preferApp, 기본 true) — 켜져 있는 팀즈 **앱 창**을 먼저 읽는다. 새 줄을 얻으면
        # 웹·Copilot 경로를 건너뛰어 Edge 탭이 아예 뜨지 않는다(제보: "팀즈·아웃룩은 최대한 앱을 쓰라",
        # "창이 여러 개 뜬다"). 앱이 꺼져 있거나 렌더된 것이 없으면 수집기가 종료코드 4 를 주고 웹으로 넘어간다.
        if not teams_ok and "--no-teams" not in sys.argv and c.get("preferApp", True):
            teams_ok = step("팀즈 채팅 (앱 창 읽기 — 켜져 있는 대화)",
                            ps + [os.path.join(col, "Get-TeamsWindow.ps1")], 120)
            if not teams_ok:
                print("   앱 창에서 새 줄을 얻지 못했습니다 — 웹 경로로 이어서 시도합니다"
                      " (앱을 켜 두고 대화를 열어 두면 앱 경로만으로 끝납니다)")
        if not teams_ok and collect_headless(c) and "--no-teams" not in sys.argv:
            print("\n── 팀즈 채팅 (수집만 모드 — 웹·Copilot 경로 생략)")
            print("   추가 PC 의 팀즈는 앱 창 읽기·Graph·상시 샘플러로만 — 창을 열지 않습니다.")
            record("팀즈 채팅", True, 0.0, "수집만 모드 — 창 여는 경로 생략(본 PC 가 같은 계정으로 수집)")
        if (not teams_ok and "--no-teams" not in sys.argv and c.get("teamsWeb", True)
                and not collect_headless(c)):
            teams_ok = step("팀즈 채팅 (웹 — 전용 Edge, 앱이 꺼져 있어도)",
                            [sys.executable, os.path.join(col, "Get-TeamsWeb.py"),
                             "--from", d0, "--to", d1], 1200)
        # Copilot 은 '판정 엔진'이다. 팀즈 조회는 테넌트에 커넥터가 있어야만 되는 별개
        # 기능이라, 없는 환경에서 계속 물으면 판정에 쓸 세션만 소진된다(실측).
        use_cp_teams = bool(c.get("teamsViaCopilot"))
        if not teams_ok and not use_cp_teams and "--no-teams" not in sys.argv and not collect_headless(c):
            print("\n── 팀즈 채팅 (Copilot 경로 건너뜀 — config.teamsViaCopilot=false)")
            print("   팀즈는 웹 경로(전용 Edge)·상시 샘플러(collect\\Start-TeamsSampler.ps1)·Graph 로 모읍니다.")
            print("   Copilot 은 AI 판정 전용으로 아껴 둡니다.")
            record("팀즈 채팅", True, 0.0, "Copilot 경로 건너뜀(설정)")
        if not teams_ok and use_cp_teams and "--no-teams" not in sys.argv and not collect_headless(c):
            teams_ok = step("팀즈 채팅 (Copilot 무개입 — Graph 불가 시 대체)",
                            [sys.executable, os.path.join(col, "Get-TeamsViaCopilot.py"),
                             "--from", d0, "--to", d1],
                            300 + 600 * max(1, ((date.fromisoformat(d1)
                                                 - date.fromisoformat(d0)).days // 30 + 1)))
        if not teams_ok and "--no-teams" not in sys.argv and not c.get("preferApp", True):
            # preferApp 이면 위에서 이미 앱 창을 읽었다 — 두 번 읽지 않는다
            step("팀즈 채팅 (열린 창 읽기 — 앱이 켜져 있으면)",
                 ps + [os.path.join(col, "Get-TeamsWindow.ps1")], 120)

    if "--collect-only" in sys.argv:
        # 근무시간 실측을 **로드바 안에서** 계산·저장한다 — 예전에는 화면이 열릴 때 재계산해
        # '끝났는데 탐색하듯 도는' CPU 가 로드바 밖에 있었다(제보). 실패해도 수집은 유효.
        try:
            from progress import progress as _pg
            import extract as _XW
            _pg("근무시간 실측", 0, 1)
            print("\n── 근무시간 실측(추이 실선 재료 — 이 계산까지가 수집입니다)")
            _cfgw = _XW.load_cfg()
            try:
                from mine import EXCLUDE as _EX0
            except ImportError:
                _EX0 = ()
            _exw = sorted(set(_EX0) | {str(k) for k in _XW.cfg_list(_cfgw, "excludePathKeywords")
                                       if str(k).strip()})
            from datetime import date as _date
            _dd0, _dd1 = _date.fromisoformat(d0), _date.fromisoformat(d1)
            _rows, _metaw = _XW.load_signals(data, _dd0, _dd1, _exw, _cfgw)
            if _rows:
                _wh, _hi = _XW.day_work_hours(data, _rows, _dd0, _dd1, _cfgw,
                                              file_times=_metaw.get("file_times"))
                _XW.save_day_hours(os.path.join(ROOT, "report"),
                                   f"{d0.replace('-', '')}-{d1.replace('-', '')}", _wh)
                print(f"   근무 실측 {len(_wh)}일 저장 — 본 PC 추이 실선에 그대로 쓰입니다")
            _pg("근무시간 실측", 1, 1)
        except Exception as _e:  # noqa: BLE001
            print(f"   근무 실측 저장 보류({type(_e).__name__}) — 본 PC 분석 때 다시 계산됩니다")
        print("\n[수집만] 이 PC 의 데이터 수집을 마쳤습니다 — 분석은 하지 않았습니다.")
        print("        폴더째 본 PC 로 가져가 [분석 실행]을 누르면 두 PC 데이터가 합산됩니다")
        print("        (같은 메일·일정 등 중복 자료는 분석 때 자동 제외).")
        print("        ※ 창 샘플러(1분 주기)·팀즈 샘플러(5분 주기)는 **백그라운드로 계속** 활동을")
        print("          기록합니다 — 이것이 수집의 일부입니다(끝난 뒤 도는 프로그램이 그것입니다).")
        print("          멈추려면: schtasks /End /TN LoadMonitor24-Sampler (등록 해제는 /Delete)")
        RUN["finished"] = time.strftime("%Y-%m-%d %H:%M")
        record("완료(수집만)", True, 0.0, "추가 PC 수집 모드 — 분석은 본 PC 에서")
        return 0

    print("\n── 업무 로드 추출 (주40h 근무일 기준)")
    _t = time.time()
    # 출력을 흘려보내면서 꼬리를 보관한다 — mine 이 죽으면 마지막 오류 줄이 last_run.json 에
    # 실려 화면 배너로 보인다. 예전엔 모든 실패가 "신호 0건"으로 기록돼(실측: 회사 PC 에
    # 신호 수천 건이 있는데도 그 메시지) 원격 진단이 불가능했다.
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, "mine.py"), data,
                          "--from", d0, "--to", d1,
                          "--name", c.get("owner") or os.environ.get("USERNAME", ""),
                          "--func", c.get("function", "")],
                         cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
    tail = []

    def _on_mine(line):
        print(line, flush=True)
        tail.append(line)
        del tail[:-12]

    stop_m = watch_child(p, _on_mine, "업무 로드 추출")   # 멈추면 끊는다(정체 감지)
    rc_m = p.wait()
    if stop_m:
        record("업무 로드 추출", False, time.time() - _t, stop_m)
        record("종료", False, 0.0, stop_m)
        return 1
    if rc_m == 0:
        # 지난 판정 산출물은 이 시점부터 '옛것' 이다(V-01) — 정제본이 화면에 그대로 남지 않게 개명한다
        _inv, _inv_fail = invalidate_ai_outputs(d0, d1)
        record("업무 로드 추출", True, time.time() - _t,
               (f"지난 판정 산출물 {len(_inv)}개 무효화(.stale)" if _inv else "")
               + (f" · 무효화 실패: {', '.join(_inv_fail)}" if _inv_fail else ""))
    elif rc_m == 4:
        record("업무 로드 추출", False, time.time() - _t, "결과 파일이 다른 프로그램(Excel 등)에서 열려 있어 저장 실패")
        print("\n[!] 결과 CSV/MD 가 열려 있어 저장하지 못했습니다 — 해당 파일을 닫고 다시 실행하세요.")
        record("종료", False, 0.0, "결과 파일 잠김 — Excel 등에서 열어둔 결과 파일을 닫고 재실행")
        return 1
    elif rc_m == 2:
        record("업무 로드 추출", False, time.time() - _t, "신호 0건")
        print("\n[!] 신호가 없습니다 — config.watchFolders 를 실제 작업 폴더로 바꾸고 다시 실행하세요.")
        record("종료", False, 0.0, "신호 0건 — 수집 데이터가 기간과 맞는지 확인")
        return 1
    else:
        err = next((ln for ln in reversed(tail)
                    if "Error" in ln or "오류" in ln or "Traceback" in ln), tail[-1] if tail else "")
        record("업무 로드 추출", False, time.time() - _t, f"오류로 중단: {err[:200]}")
        print("\n[!] 업무 로드 추출이 오류로 중단됐습니다 — 위 오류 줄을 확인하세요.")
        record("종료", False, 0.0, f"업무 로드 추출 오류: {err[:200]}")
        return 1

    if "--ai" in sys.argv:
        # 한 번의 [분석 실행] 전체(판정+정제+Agentic+워크플로우) 마감을 자식들에게 물려준다.
        # 예전에는 단계마다 독립 상한이라 합계가 몇 시간이 될 수 있었다(감사 실측). 0 이면 끔.
        try:
            _tot = float(c.get("aiTotalBudgetMin", 300) or 0)
        except (ValueError, TypeError):
            _tot = 300.0
        if _tot > 0:
            # flow(마지막 단계) 몫 **선예약** — 앞 단계에는 전체 − 예약분만 물려준다. 예전에는 앞
            # 단계가 전체를 소진하면 flow 가 15분 floor 로 굶어 워크플로우가 반쪽이 됐다(실측:
            # 잔여 0분에서 120업무 중 60개 소실). 총 벽시계 상한은 그대로다 — flow 직전에 마감을
            # 전체로 되돌리므로 합계는 여전히 aiTotalBudgetMin 안이다.
            try:
                _fb = float(c.get("flowBudgetMin", 120) or 0) or 120.0
            except (ValueError, TypeError):
                _fb = 120.0
            _flow_reserve = min(max(60.0, _fb), max(60.0, _tot * 0.4))
            global _AI_T0, _AI_TOT_MIN
            _AI_T0, _AI_TOT_MIN = time.time(), _tot
            os.environ["LM_AI_DEADLINE"] = str(_AI_T0 + (_tot - _flow_reserve) * 60.0)
            print(f"   (AI 단계 전체 마감 {_tot:.0f}분 — 워크플로우 몫 {_flow_reserve:.0f}분 선예약,"
                  f" 판정·정제·Agentic 은 {_tot - _flow_reserve:.0f}분 안에서"
                  " · config.aiTotalBudgetMin/flowBudgetMin)")
        print("\n── AI 판정 (계층 엔티티: 과제↔유형↔세부업무 + 월별 내러티브) — 시간이 걸립니다")
        _t2 = time.time()
        # 출력을 흘려보내며 마지막 줄 JSON 을 건진다 — judge 는 판정 0건(왕복 전부 실패)이면
        # 코드 3 과 {"ok":false,"error","hint"} 를 낸다(F3). 예전에는 그 경우도 0 이라
        # 'AI 판정 ok' 로 적히고 정제·Agentic·워크플로우가 빈손으로 계속 돌았다.
        _WATCH_STATE_PATH["p"] = os.path.join(ROOT, "report",
                                              f"stage_state_{d0.replace('-', '')}-{d1.replace('-', '')}_judge.json")
        rc, why_j = _run_capture([sys.executable, os.path.join(ROOT, "judge.py"),
                                  "--from", d0, "--to", d1],
                                 dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
        _stub = "스텁 판정(LM_COPILOT_STUB — 테스트 전용, 실제 Copilot 아님)"             if os.environ.get("LM_COPILOT_STUB") else ""
        if rc == 0:
            _note_j = _stub
        elif rc == 3:
            _note_j = "AI 판정 실패(왕복 전부 실패)"
            if why_j and not why_j.startswith(_note_j):
                _note_j += f" — {why_j}"
            elif why_j:
                _note_j = why_j              # judge 가 이미 같은 머리말로 사유를 적어 보냈다
        else:
            _note_j = f"judge.py 종료코드 {rc}" + (f" — {why_j}" if why_j else "")
        if _stub and rc != 0:
            _note_j += " · " + _stub
        record("AI 판정", rc in (0, 2), time.time() - _t2,
               ("부분 판정 — 다시 실행하면 남은 신호만 이어서 · " if rc == 2 else "") + str(_note_j or ""))
        if _stub:
            print(f"   [!] {_stub}")
        # 판정이 0 이 아니게 끝났어도 **이번 실행에서 판정된 행이 있으면** 뒤 단계를 계속한다.
        # 예전에는 무조건 건너뛰어, 정체 감지·상한에 한 번 걸리면 정제·Agentic·워크플로우가 전부
        # 사라졌다(제보: "진행되다가 안 된다"). 판정 결과가 남아 있으면 정제할 재료는 있는 것이다.
        _partial_ok = False
        if rc not in (0, 2):
            _jp = os.path.join(ROOT, "report",
                               f"ai_judgments_{d0.replace('-', '')}-{d1.replace('-', '')}.json")
            try:
                if os.path.exists(_jp) and os.path.getmtime(_jp) >= _t2 - 5:
                    with open(_jp, encoding="utf-8") as _f:
                        _jj = json.load(_f)
                    _n_judged = int(_jj.get("judged") or 0)
                    if _n_judged > 0:
                        _partial_ok = True
                        print(f"   [!] 판정이 끝까지 가지 못했지만 {_n_judged}건은 판정됐습니다 — "
                              "그 결과로 정제·Agentic·워크플로우를 계속합니다")
                        print("       (남은 신호는 다시 실행하면 이어서 판정합니다)")
                        _note_j += f" · 부분 판정 {_n_judged}건으로 뒤 단계 계속"
                        record("AI 판정", False, time.time() - _t2, _note_j)
            except (OSError, ValueError, TypeError):
                _partial_ok = False
        if rc not in (0, 2) and not _partial_ok:
            _skip = ("AI 판정 왕복 전부 실패로 건너뜀" if rc == 3 else "판정 실패로 건너뜀")
            print("   [!] AI 판정 실패 — 화면의 과제는 AI가 정리한 것이 아니라 규칙이 뽑은")
            print("       임시 결과입니다. 위 judge 로그의 마지막 오류를 보세요.")
            if rc == 3:
                print(f"       판정 왕복이 전부 실패했습니다({why_j[:120] if why_j else '사유 없음'})")
                print("       — 지난 실행의 내러티브·과제 체계 파일은 그대로 보존됩니다.")
                # 정제본은 추출 직후 이미 .stale 로 개명됐다(V-01) — 즉 이번 화면의 '상위(업무 성격)'
                # 칸은 비어 있다. 예전에는 그것을 아무도 말해 주지 않아 '상위과제 분류가 고장났다'
                # 로 보였다(실측 제보). 무엇이 비었고 무엇을 하면 되는지 화면 배너에도 실어 보낸다.
                print("       이번 화면의 '상위(업무 성격)' 분류는 비어 있습니다 — 그 값은 AI 정제가"
                      " 채우는 것이고, 판정이 실패하면 정제를 돌리지 않습니다.")
                print("       → 위 사유를 해결한 뒤 [재분석만]을 누르면 상위 분류까지 다시 채워집니다.")
                _note_j += " · 상위(업무 성격) 분류 비어 있음 — 해결 후 [재분석만]"
                record("AI 판정", False, time.time() - _t2, _note_j)
            print("       흔한 원인: ① Copilot 로그인 만료(UI [AI 연결 진단]으로 확인)")
            print("                  ② 모델 선택 실패 ③ 회사망 차단")
            print("   → AI 정제·Agentic 매칭·워크플로우 건너뜀 (판정 없는 결과를 정제하면 낡은 정제본만 남습니다)")
            record("AI 정제", False, 0.0, _skip)
            record("Agentic 매칭", False, 0.0, _skip)
            record("워크플로우 분석", False, 0.0, _skip)
        else:
            print("\n── AI 정제 (Level1·상세설명 문장화)")
            _t3 = time.time()
            # 다른 AI 단계와 같은 감시를 받게 한다 — 예전에는 timeout 도 정체 감지도 없는
            # subprocess.run 이어서 정제가 멈추면 분석 전체가 여기서 영원히 서 있었다(실측 감사).
            _WATCH_STATE_PATH["p"] = os.path.join(ROOT, "report",
                                                  f"stage_state_{d0.replace('-', '')}-{d1.replace('-', '')}_refine.json")
            rc2, why_r = _run_capture([sys.executable, os.path.join(ROOT, "refine.py"),
                                       "--from", d0, "--to", d1],
                                      dict(os.environ, PYTHONIOENCODING="utf-8",
                                           PYTHONUNBUFFERED="1"))
            record("AI 정제", rc2 in (0, 2), time.time() - _t3,
                   ("부분 완료 — 다시 실행하면 남은 것만 이어서 · " if rc2 == 2 else "") + str(why_r or ""))
            if rc2 not in (0, 2):
                print("   AI 정제 실패 — report 폴더의 evidence 파일을 Copilot에 붙여넣어도 됩니다")

            # Agentic AI 매칭 — 판정 후 12과제 매칭·발굴·오할당 검증을 자동 수행
            print("\n── Agentic AI 매칭 (12과제 적합·신규 발굴·오할당 검증)")
            _t3 = time.time()
            rc2, note2 = run_ai_stage("agentic.py", d0, d1)
            record("Agentic 매칭", rc2 in (0, 2), time.time() - _t3, note2)
            if rc2 not in (0, 2):
                print("   Agentic 매칭 실패 — UI Agentic AI 탭의 [재매칭]으로 다시 시도하세요")

            # 담당자 워크플로우 — 과제별 역할·일의 순서·Agent 가능성 (실패해도 분석은 유효)
            # 선예약분 반환 — 마감을 전체로 되돌린다(앞 단계가 일찍 끝났으면 flow 가 잔여를 다 쓴다)
            if _AI_T0 is not None and _AI_TOT_MIN:
                os.environ["LM_AI_DEADLINE"] = str(_AI_T0 + _AI_TOT_MIN * 60.0)
            print("\n── 담당자 워크플로우 (역할·순서·Agent 가능성)")
            _t3 = time.time()
            rc2, note2 = run_ai_stage("flow.py", d0, d1)
            record("워크플로우 분석", rc2 in (0, 2), time.time() - _t3, note2)
            if rc2 not in (0, 2):
                print("   워크플로우 분석 실패 — UI 담당자 워크플로우 탭의 [재분석]으로 다시 시도하세요")
            # 워크플로우 단계가 만든 세부업무 병합 맵(config\detail_aliases.json)을 Agentic 실측에 반영 —
            # agentic 이 flow 보다 먼저 돌아 첫 --ai 실행(캐시 없음·리셋 뒤)의 load_mm 이 맵 없이
            # 계산돼 같은 실행의 workflow mm 과 어긋났다(F5). 왕복 없음·실패 무시.
            agentic_recalc_inproc(d0, d1)
    else:
        record("AI 판정", False, 0.0, "AI 판정을 켜지 않고 실행했습니다(--ai 없음)")
        # 지난 AI 실행의 Agentic 결과가 남아 있으면 MM 실측만 재추출된 행으로 다시 센다(왕복 없음) — 매칭 자체는
        # 옛 행 기준이라 화면이 '재추출 이후 결과' 로 표시한다(V-01). 보고서 생성 전에 해야 리포트 섬과 KPI 가 맞는다.
        if os.path.exists(os.path.join(ROOT, "report", f"agentic_{d0.replace('-', '')}-{d1.replace('-', '')}.json")):
            print("\n── Agentic 매칭 결과는 지난 AI 실행 것 — MM 실측만 재추출된 행으로 다시 셉니다(화면에 '재추출 이후 결과' 표시)")
            agentic_recalc_inproc(d0, d1)
        print(f"\n다음: python run.py --from {d0} --to {d1} --skip-collect --ai   (AI 판정)")

    # 보고서 3종(리포트·분석리포트·얼린 보고서) — AI 없이 돌려도 만든다(규칙 결과도 얼릴 수 있다).
    # teamup --build 보다 먼저 돌아야 공유폴더 저장 때 개인리포트가 함께 간다. HTML 은 팀 서버로
    # 올리지 않는다(서버 파일명 규칙 불변) — 공유폴더(개인리포트\) 경로로만 간다.
    print("\n── 보고서 생성 (리포트·분석리포트·얼린 보고서)")
    _t = time.time()
    rc_f, note_f = _run_capture([sys.executable, os.path.join(ROOT, "freeze.py"),
                                 "--from", d0, "--to", d1, "--all"],
                                dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
    # 0 전부 · 2 일부만(무엇이 빠졌는지는 note 에) · 그 밖은 실패 — 보고서가 없어도 묶음·업로드는 계속
    record("보고서 생성", rc_f in (0, 2), time.time() - _t,
           "" if rc_f == 0 else (note_f or f"freeze.py 종료코드 {rc_f}"))
    if rc_f not in (0, 2):
        print("   [!] 보고서 생성 실패 — 대시보드의 [보고서 만들기] 버튼으로 다시 시도할 수 있습니다")

    # 팀 업로드는 '준비'까지만 한다 — 팀 서버는 특정 망에서만 닿는데 분석은 아무 망에서나
    # 하기 때문이다(실측: 자동 전송이 대부분 실패하고 결과가 조용히 사라짐). 묶음을
    # report\upload_pending\ 에 만들어 두고, 서버에 닿는 망에서 대시보드 [팀 서버 업로드]
    # 버튼(또는 LoadMonitor24-팀업로드.bat)으로 밀린 것까지 한 번에 보낸다.
    _t4 = time.time()
    _p4 = subprocess.run([sys.executable, os.path.join(ROOT, "teamup.py"),
                          "--build", "--from", d0, "--to", d1], cwd=ROOT, capture_output=True,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                  PYTHONUNBUFFERED="1"))
    rcb = _p4.returncode
    _o4 = ((_p4.stdout or b"").decode("utf-8", "replace")
           + (_p4.stderr or b"").decode("utf-8", "replace")).strip()
    for _ln in _o4.splitlines():
        print("   " + _ln)
    _why = " / ".join(_o4.splitlines()[-2:]) if _o4 else ""
    n_pend = 0
    try:
        pend = os.path.join(ROOT, "report", "upload_pending")
        n_pend = len([x for x in os.listdir(pend) if x.endswith(".json")]) if os.path.isdir(pend) else 0
    except OSError:
        pass
    # 실패 사유는 teamup 이 말한 것을 그대로 옮긴다 — '산출물 없음'으로 단정하면 잠금·권한 오류가 가려진다
    record("팀 업로드 묶음 준비", rcb == 0, time.time() - _t4,
           (f"대기 {n_pend}건 — 서버망에서 [팀 서버 업로드] 버튼을 누르면 전송됩니다"
            + (" · " + _why if "보낼 수 없습니다" in _why else "")
            if rcb == 0 else (_why or "묶음 준비 실패")))
    if (c.get("teamUpload") or {}).get("auto") and (c.get("teamServerUrl") or "").strip():
        # 원하는 사람만 켜는 자동 전송(기본 꺼짐). 실패해도 묶음은 대기로 남는다.
        print("\n── 팀 서버 자동 업로드 (config.teamUpload.auto)")
        _t5 = time.time()
        rc3 = subprocess.run([sys.executable, os.path.join(ROOT, "teamup.py"), "--upload"],
                             cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                                PYTHONUNBUFFERED="1")).returncode
        record("팀 서버 자동 업로드", rc3 == 0, time.time() - _t5,
               "" if rc3 == 0 else "이 망에서 서버에 닿지 않아 대기로 남겼습니다 — 서버망에서 버튼으로 보내세요")

    if (c.get("teamShareDir") or "").strip():
        print("\n── 팀 공유폴더 내보내기")
        subprocess.run([sys.executable, os.path.join(ROOT, "export.py"),
                        "--from", d0, "--to", d1], cwd=ROOT,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"))
    RUN["finished"] = time.strftime("%Y-%m-%d %H:%M")
    record("완료", True, 0.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
