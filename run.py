# -*- coding: utf-8 -*-
"""
run.py — LoadMonitor22 통합 실행기: 수집 → 추출 → (AI 판정·내러티브) → 팀 내보내기.

  python run.py --from 2026-05-19 --to 2026-08-17            # 수집 + 추출
  python run.py --from ... --to ... --skip-collect            # 이미 모은 데이터로 추출만
  python run.py --from ... --to ... --ai                      # AI 정제까지 (Copilot 무개입)

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
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    rc, why = _run_capture(cmd, env)
    if rc == 0:
        return 0, ""
    print(f"   첫 시도 실패(코드 {rc}) - {retry_wait}초 뒤 1회 재시도합니다")
    time.sleep(retry_wait)
    rc, why2 = _run_capture(cmd, env)
    if rc == 0:
        return 0, "1회 재시도 후 성공"
    # 사유를 기록에 남긴다 — 예전에는 '코드 1' 만 남아 사용자도 나도 원인을 볼 수 없었다
    return rc, (f"재시도에도 실패: {why2 or why}" if (why2 or why)
                else f"재시도에도 실패(코드 {rc}) - 탭의 수동 실행으로 다시")


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
    for line in p.stdout:
        line = line.rstrip("\n")
        print(line, flush=True)          # [progress] 줄이 UI 진행 바에 바로 닿게(텍스트 층 버퍼링 방지)
        if line.strip():
            tail.append(line.strip())
            del tail[:-6]
        if line.startswith("{") and line.rstrip().endswith("}"):
            try:
                o = json.loads(line)
                if isinstance(o, dict):
                    last_json = o
            except ValueError:
                pass
    rc = p.wait()
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
    names = [f"mm_rows_{tag}_refined.csv", f"ai_judgments_{tag}.json",
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


def archive_other_pc(data):
    r"""추가 PC 취합 — 폴더째 다른 PC 로 옮겨 왔으면, 지난 PC 의 수집 데이터를
    data\추가PC\<지난 PC 이름>\ 으로 보관하고 이번 PC 것을 새로 수집하게 한다.
    분석은 본 폴더 + 추가PC\* 를 전부 합쳐 계산한다(중복은 자동 제거)."""
    try:
        name_f = os.path.join(data, "pc_name.txt")
        here = os.environ.get("COMPUTERNAME", "").strip()
        prev = ""
        if os.path.exists(name_f):
            prev = open(name_f, encoding="utf-8-sig").read().strip()
        if prev and here and prev != here:
            keep = os.path.join(data, "추가PC", prev)
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
    d0 = arg("--from") or (date.today().replace(day=1)).isoformat()
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
    print(f"[LoadMonitor22] {d0} ~ {d1}"
          + ("  · AI 판정 포함" if "--ai" in sys.argv else "  · AI 판정 없음(규칙 결과만)"))

    # 추가 PC 취합 — 폴더째 옮겨 온 경우 지난 PC 데이터를 자동 보관 (분석 시 합산)
    if "--skip-collect" not in sys.argv:
        archive_other_pc(data)
        ensure_sampler(c, data, col)       # 멈춘 창 샘플러 재기동 (있던 PC 만)

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
        if not teams_ok and "--no-teams" not in sys.argv and c.get("teamsWeb", True):
            teams_ok = step("팀즈 채팅 (웹 — 전용 Edge, 앱이 꺼져 있어도)",
                            [sys.executable, os.path.join(col, "Get-TeamsWeb.py"),
                             "--from", d0, "--to", d1], 1200)
        # Copilot 은 '판정 엔진'이다. 팀즈 조회는 테넌트에 커넥터가 있어야만 되는 별개
        # 기능이라, 없는 환경에서 계속 물으면 판정에 쓸 세션만 소진된다(실측).
        use_cp_teams = bool(c.get("teamsViaCopilot"))
        if not teams_ok and not use_cp_teams and "--no-teams" not in sys.argv:
            print("\n── 팀즈 채팅 (Copilot 경로 건너뜀 — config.teamsViaCopilot=false)")
            print("   팀즈는 웹 경로(전용 Edge)·상시 샘플러(collect\\Start-TeamsSampler.ps1)·Graph 로 모읍니다.")
            print("   Copilot 은 AI 판정 전용으로 아껴 둡니다.")
            record("팀즈 채팅", True, 0.0, "Copilot 경로 건너뜀(설정)")
        if not teams_ok and use_cp_teams and "--no-teams" not in sys.argv:
            teams_ok = step("팀즈 채팅 (Copilot 무개입 — Graph 불가 시 대체)",
                            [sys.executable, os.path.join(col, "Get-TeamsViaCopilot.py"),
                             "--from", d0, "--to", d1],
                            300 + 600 * max(1, ((date.fromisoformat(d1)
                                                 - date.fromisoformat(d0)).days // 30 + 1)))
        if not teams_ok and "--no-teams" not in sys.argv:
            step("팀즈 채팅 (열린 창 읽기 — 앱이 켜져 있으면)",
                 ps + [os.path.join(col, "Get-TeamsWindow.ps1")], 120)

    if "--collect-only" in sys.argv:
        print("\n[수집만] 이 PC 의 데이터 수집을 마쳤습니다 — 분석은 하지 않았습니다.")
        print("        폴더째 본 PC 로 가져가 [분석 실행]을 누르면 두 PC 데이터가 합산됩니다")
        print("        (같은 메일·일정 등 중복 자료는 분석 때 자동 제외).")
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
    for raw in p.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        print(line, flush=True)
        tail.append(line)
        del tail[:-12]
    rc_m = p.wait()
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
        print("\n── AI 판정 (계층 엔티티: 과제↔유형↔세부업무 + 월별 내러티브) — 시간이 걸립니다")
        _t2 = time.time()
        # 출력을 흘려보내며 마지막 줄 JSON 을 건진다 — judge 는 판정 0건(왕복 전부 실패)이면
        # 코드 3 과 {"ok":false,"error","hint"} 를 낸다(F3). 예전에는 그 경우도 0 이라
        # 'AI 판정 ok' 로 적히고 정제·Agentic·워크플로우가 빈손으로 계속 돌았다.
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
        record("AI 판정", rc == 0, time.time() - _t2, _note_j)
        if _stub:
            print(f"   [!] {_stub}")
        if rc != 0:
            _skip = ("AI 판정 왕복 전부 실패로 건너뜀" if rc == 3 else "판정 실패로 건너뜀")
            print("   [!] AI 판정 실패 — 화면의 과제는 AI가 정리한 것이 아니라 규칙이 뽑은")
            print("       임시 결과입니다. 위 judge 로그의 마지막 오류를 보세요.")
            if rc == 3:
                print(f"       판정 왕복이 전부 실패했습니다({why_j[:120] if why_j else '사유 없음'})")
                print("       — 지난 실행의 내러티브·과제 체계 파일은 그대로 보존됩니다.")
            print("       흔한 원인: ① Copilot 로그인 만료(UI [AI 연결 진단]으로 확인)")
            print("                  ② 모델 선택 실패 ③ 회사망 차단")
            print("   → AI 정제·Agentic 매칭·워크플로우 건너뜀 (판정 없는 결과를 정제하면 낡은 정제본만 남습니다)")
            record("AI 정제", False, 0.0, _skip)
            record("Agentic 매칭", False, 0.0, _skip)
            record("워크플로우 분석", False, 0.0, _skip)
        else:
            print("\n── AI 정제 (Level1·상세설명 문장화)")
            _t3 = time.time()
            rc2 = subprocess.run([sys.executable, os.path.join(ROOT, "refine.py"),
                                  "--from", d0, "--to", d1], cwd=ROOT,
                                 env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                          PYTHONUNBUFFERED="1")).returncode
            record("AI 정제", rc2 == 0, time.time() - _t3)
            if rc2 != 0:
                print("   AI 정제 실패 — report 폴더의 evidence 파일을 Copilot에 붙여넣어도 됩니다")

            # Agentic AI 매칭 — 판정 후 12과제 매칭·발굴·오할당 검증을 자동 수행
            print("\n── Agentic AI 매칭 (12과제 적합·신규 발굴·오할당 검증)")
            _t3 = time.time()
            rc2, note2 = run_ai_stage("agentic.py", d0, d1)
            record("Agentic 매칭", rc2 == 0, time.time() - _t3, note2)
            if rc2 != 0:
                print("   Agentic 매칭 실패 — UI Agentic AI 탭의 [재매칭]으로 다시 시도하세요")

            # 담당자 워크플로우 — 과제별 역할·일의 순서·Agent 가능성 (실패해도 분석은 유효)
            print("\n── 담당자 워크플로우 (역할·순서·Agent 가능성)")
            _t3 = time.time()
            rc2, note2 = run_ai_stage("flow.py", d0, d1)
            record("워크플로우 분석", rc2 == 0, time.time() - _t3, note2)
            if rc2 != 0:
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
    # 버튼(또는 LoadMonitor22-팀업로드.bat)으로 밀린 것까지 한 번에 보낸다.
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
