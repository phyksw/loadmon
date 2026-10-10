# -*- coding: utf-8 -*-
"""
run.py — LoadMonitor28 통합 실행기: 수집 → 추출 → (AI 판정·내러티브) → 팀 내보내기.

  python run.py --from 2026-05-19 --to 2026-08-17            # 수집 + 추출
  python run.py --from ... --to ... --skip-collect            # 이미 모은 데이터로 추출만
  python run.py --from ... --to ... --ai                      # AI 정제까지 (Copilot 무개입)
  python run.py                                               # 기간 생략 = 올해 1월 1일 ~ 오늘 (화면·bat 기본과 같다)
  python run.py --from ... --to ... --web-only mail|teams     # 웹 경로만(화면 버튼용 — 기간을 늘 넘긴다 · LM28)
  python run.py --reset-cursors ...                           # 수집 커서·일자×축 원장을 지우고 처음부터 읽기(LM28)

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
# LM28(WP6): 수집 단계는 core\proc.run_step(Job 으로 감싸 트리째 정리 · 60초 진행 줄)으로 돌리고, 마지막 줄 LMSTATUS 를
# core\collect_status 로 읽어 일자×축 원장(core\coverage — data\coverage_ledger.json)에 반영한다.
import collect_status  # noqa: E402 - core\ (sys.path 위에서 등록)
import coverage  # noqa: E402
import proc  # noqa: E402
_RUN_STEP = proc.run_step      # 시험이 바꿔 끼운다(사슬 시험 — 실제 수집기를 띄우지 않는다)
_CLOSE_EDGE = None             # 시험 주입 — None 이면 tools\copilot_auto.close_own_edge
REPORT_DIR = {"p": os.path.join(ROOT, "report")}     # last_run.json 위치(시험은 임시 폴더로 바꾼다)
MAIL_AXES = coverage.MAIL_AXES
EDGE = {"closed": False}       # 이 실행에서 Edge 정리를 이미 했나(수집만·웹만은 수집 끝, 전체 실행은 마지막 finally 1회)
STATE = {"login_pending": False}   # 이 실행의 웹 경로 상태(rc 2 → login_pending — 남은 웹 경로·Edge 닫기 건너뜀)


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


def record(name, ok, sec=0.0, note="", rc=None, reason="", counts=None, census=""):
    r"""단계 결과를 report\last_run.json 에 즉시 반영 (강제 종료돼도 흔적 보존).
    LM28(F-34): 수집기 단계는 rc·reason·counts(짧은 숫자만)도 싣는다 — '불가' 사유는 실측 전까지 '의심'으로 적는다.
    census = 수집기가 찍은 화면 구조 한 줄(웹 경로) — 수집 진단 화면이 note 아래에 그대로 보여 준다(사진 한 장으로 원인 확정)."""
    RUN["stages"] = [x for x in RUN["stages"] if x["name"] != name]
    ent = {"name": name, "ok": bool(ok), "sec": round(sec, 1), "note": (note or "")[:300]}
    if census:
        ent["census"] = str(census)[:400]
    if rc is not None:
        ent.update(rc=int(rc), reason=str(reason or "")[:120], counts=collect_status.compact(counts))
    RUN["stages"].append(ent)
    try:
        rep_dir = REPORT_DIR["p"]
        os.makedirs(rep_dir, exist_ok=True)
        with open(os.path.join(rep_dir, "last_run.json"), "w", encoding="utf-8") as f:
            json.dump(RUN, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def run_collector(name, cmd, timeout=420, src="", led=None):
    r"""수집기 한 단계(LM28) → 해석한 상태 dict(collect_status.parse — rc·reason·counts·ranges·ok).
    · core\proc.run_step: Job(KILL_ON_JOB_CLOSE·BREAKAWAY_OK)으로 감싸 시간 초과 때 손자까지 정리하고(W1-07, taskkill 없음),
      60초마다 '진행 중' 줄을 낸다(화면의 15분 정체 감시 — W1-06). 전용 Edge 는 Job 에서 이탈해 띄워지므로 산다.
    · 마지막 줄 LMSTATUS 를 읽는다(없으면 LM24 종료 코드 해석). 화면·last_run.json 에는 그 앞의 사람용 줄과 rc·사유를 쓴다.
    · led(원장)를 주면 ranges 를 일자×축 원장에 반영하고 바로 저장한다(강제 종료돼도 흔적 보존)."""
    print(f"\n── {name}")
    t0 = time.time()
    rc, tail, how = _RUN_STEP(cmd, timeout, name)
    st = collect_status.parse(tail, rc, src=src, how=how)
    # 마지막 12줄 — 수집기가 '왜 0건인지' 적는 줄이 잘려 나가지 않게(팀즈 0건 실측). LMSTATUS 줄은 화면에 찍지 않는다.
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


def step(name, cmd, timeout=420, src="", led=None):
    """단계 실행 → 성공 여부(rc 0 정상·1 대상 없음·4 새 행 0 은 실패가 아니다). 성공해도 요약 줄을 남긴다 —
    "PC 가동 2건"처럼 값이 이상할 때 어느 수집기가 무엇을 찾았는지 last_run.json 만으로 원격 진단이 되게 한다."""
    return run_collector(name, cmd, timeout, src=src, led=led)["ok"]


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
    """수집기 실행 → (종료 코드, 출력 꼬리 6줄). 시간 초과 -1 · 실행 실패 -2. 단계 기록은 호출측이 한다.
    LM28: core\\proc.run_step(Job — 시간 초과 때 트리째 정리)을 쓴다. 뜻 있는 해석은 run_collector(LMSTATUS)를 쓴다."""
    rc, tail, _how = _RUN_STEP(cmd, timeout, os.path.basename(str(cmd[-1] if cmd else "")))
    return rc, list(tail)[-6:]


def collect_headless(c):
    r"""[수집만] 모드에서 생략하는 것은 **Copilot 경로(메일·팀즈)만**이다(Copilot 은 판정 전용).
    LM28: 예전(LM24)에는 Outlook 웹·팀즈 웹도 '본 PC 가 같은 사서함을 수집' 한다고 보고 건너뛰었다. 그런데 새 Outlook 인 PC
    (COM·색인 없음)에서는 그러면 메일·일정·팀즈를 가져올 길이 하나도 남지 않았다(실측 2026-10-07 — 279일 전부 관측 없음).
    그래서 웹 경로는 수집만 모드에서도 원장의 미검증 날에 대해 돈다 — 겹치는 행은 분석이 중복 제거한다."""
    return "--collect-only" in sys.argv and bool(c.get("collectOnlyHeadless", True))


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


def _only(gaps, flag):
    """원장 공백 → 수집기 종류 인자(메일·일정 둘 다 비면 [] = 둘 다)"""
    m = bool(gaps.get("mail_in") or gaps.get("mail_out"))
    k = bool(gaps.get("cal"))
    if (m and k) or not (m or k):
        return []
    return [flag, "mail" if m else "cal"]


def _edge_rc2(st, state, name, what):
    """웹 경로 rc 2(로그인) — 이 실행의 남은 웹 경로는 건너뛴다(login_pending · F-17). 로그인은 사람이 1회."""
    if st.get("rc") != 2:
        return
    state["login_pending"] = True
    record(name, False, 0.0,
           f"로그인 필요 — 전용 Edge 창(Copilot 과 같은 창)의 {what} 탭에서 회사 계정을 1회 선택/로그인한 뒤 다시 실행"
           + (f" ({st.get('reason')})" if st.get("reason") else ""), rc=2, reason=st.get("reason"), counts=st.get("counts"))


def _skip_login(name):
    record(name, True, 0.0, "건너뜀 — 이번 실행에서 웹 경로가 로그인을 기다리는 중(login_pending · 전용 Edge 창에서 로그인 1회)")


def seed_legacy(data):
    r"""첫 실행(data\outlook\src 가 없을 때) — LM24 의 공용 파일을 출처 'legacy'(우선순위 최하)로 옮겨 둔다. 읽기만 한다:
    mail.csv → src\mail_legacy.csv · calendar.csv → src\cal_legacy.csv · mail_source.json → src\mail_source_legacy.json(me[])."""
    src_dir = os.path.join(data, "outlook", "src")
    if os.path.isdir(src_dir):
        return []
    import shutil
    done = []
    for a, b in (("mail.csv", "mail_legacy.csv"), ("calendar.csv", "cal_legacy.csv"),
                 ("mail_source.json", "mail_source_legacy.json")):
        p = os.path.join(data, "outlook", a)
        if not os.path.isfile(p) or (a.endswith(".csv") and not _csv_has_rows(p)):
            continue
        try:
            os.makedirs(src_dir, exist_ok=True)
            shutil.copyfile(p, os.path.join(src_dir, b))
            done.append(b)
        except OSError:
            pass
    if done:
        print(f"   (첫 실행 — 지난 메일·일정 자료를 출처 'legacy'(최하 우선)로 보존: {', '.join(done)})")
    return done


def _import_files(data):
    r"""data\import 에 반입할 파일(.eml·.ics·.csv)이 있나 — 없으면 Import-MailCal 을 띄우지 않는다(프로세스 절약)."""
    base = os.path.join(data, "import")
    for _b, _d, fs in os.walk(base):
        if any(os.path.splitext(n)[1].lower() in (".eml", ".ics", ".csv") for n in fs):
            return base
    return ""


def g1_mail(c, data):
    r"""G1(수집 직후 정제) — data\outlook\src\*.csv 의 제목·대화·장소를 core\privacy.scrub_csv 로 제자리 정제한다(머리글·열 불변).
    웹·Copilot 출처는 정제 뒤 같은 키(편지함·시각·보낸이·제목 / 시작·끝·제목)를 접는다 — 그 수집기가 다음 실행에 원문 행을
    다시 붙여도(키가 원문이라 못 알아봄) 1행이 된다. COM·색인·반입은 접지 않는다(같은 분 같은 제목 알림은 실제 2통)."""
    import glob
    import privacy
    ctx = privacy.make_ctx(c, data)
    tot = {"files": 0, "dropped": 0, "folded": 0, "fail": []}
    for p in sorted(glob.glob(os.path.join(data, "outlook", "src", "*.csv"))):
        n = os.path.basename(p).lower()
        tag = n.split("_", 1)[1][:-4] if "_" in n else ""
        if n.startswith("mail_"):
            cols, keys = ["subject", "conversation"], (["box", "time", "sender", "subject"] if tag in ("owa", "copilot") else None)
        elif n.startswith("cal_"):
            cols, keys = ["subject", "location"], (["start", "end", "subject"] if tag in ("owa", "copilot") else None)
        else:
            continue
        info = privacy.scrub_csv(p, cols, key_cols=keys, ctx=ctx, data_dir=data)
        _g1_tally(tot, n, info)
    return _g1_record("개인정보 정제(G1) — 메일·일정 출처 파일", tot)


def g1_teams(c, data):
    r"""G1 — data\m365\teams_*.csv(summary·chat)와 undated_teams_window.csv 를 정제하고, 정제된 키(날짜·시각·보낸이·방·요지)로
    같은 메시지를 접는다 — 창 읽기(PS)는 원문 키로 중복을 거르므로 정제 뒤 다시 붙은 원문 행을 여기서 1행으로 만든다."""
    import glob
    import privacy
    ctx = privacy.make_ctx(c, data)
    tot = {"files": 0, "dropped": 0, "folded": 0, "fail": []}
    items = [(p, ["time", "from", "chat", "summary"])
             for p in sorted(glob.glob(os.path.join(data, "m365", "teams_*.csv")))]
    und = os.path.join(data, "m365", "undated_teams_window.csv")
    if os.path.isfile(und):
        items.append((und, ["hm", "from", "chat", "summary"]))
    for p, keys in items:
        info = privacy.scrub_csv(p, ["summary", "chat"], key_cols=keys, ctx=ctx, data_dir=data)
        _g1_tally(tot, os.path.basename(p), info)
    return _g1_record("개인정보 정제(G1) — 팀즈 파일", tot)


def _g1_tally(tot, name, info):
    if not info.get("ok"):
        tot["fail"].append(f"{name}({info.get('error', '?')})")
        return
    tot["files"] += 1
    tot["dropped"] += int(info.get("dropped") or 0)
    tot["folded"] += int(info.get("folded") or 0)


def _g1_record(name, tot):
    if not tot["files"] and not tot["fail"]:
        return True
    note = (f"파일 {tot['files']}개 정제 · 자격증명 행 제외 {tot['dropped']} · 같은 메시지 접음 {tot['folded']}"
            + (f" · 실패 {', '.join(tot['fail'])[:120]} — 다음 실행에서 다시" if tot["fail"] else ""))
    print(f"\n── {name}\n   {note}")
    record(name, not tot["fail"], 0.0, note)
    return not tot["fail"]


def merge_mail(c, data, led, d0, d1):
    r"""출처별 파일 → data\outlook\mail.csv·calendar.csv·mail_source.json(core\mailmerge — 분석이 읽는 공용 파일은 여기만 쓴다)."""
    import mailmerge
    import privacy
    ctx = privacy.make_ctx(c, data)
    t0 = time.time()
    info = mailmerge.merge(os.path.join(data, "outlook", "src"), os.path.join(data, "outlook"),
                           verified=(led.is_verified if led is not None else None), period=(d0, d1),
                           norm=lambda s: privacy.sanitize(s, "subject", ctx)[0])
    if info.get("error") == "no_sources":
        return info
    srcs = " · ".join(f"{k} {v}" for k, v in sorted((info.get("sources") or {}).items(), key=lambda kv: -kv[1]))
    note = (f"메일 {info.get('mail', 0)}건({srcs or '없음'}) · 일정 {info.get('calendar', 0)}건 · 중복 제외 {info.get('dup', 0)}"
            + (f" · Copilot 증인 행 {info['copilot']}" if info.get("copilot") else "")
            + (f" · {info['error']}" if info.get("error") else ""))
    print(f"\n── 메일·일정 병합 (출처별 → mail.csv·calendar.csv)\n   {note}")
    record("메일·일정 병합", bool(info.get("ok")), time.time() - t0, note)
    return info


def _axis_ko(ax):
    return {"mail_in": "받은 메일", "mail_out": "보낸 메일", "cal": "일정", "teams": "팀즈", "pc": "PC"}.get(ax, ax)


def report_gaps(led, d0, d1, axes, name):
    """원장의 남은 공백(오늘 제외)을 화면·last_run.json 에 — 미관측 날은 0시간이 아니라 '근거 없음'(C-31)."""
    hi = _yday(d1)
    if hi < d0:
        return
    g = led.gaps(axes, d0, hi)
    parts = [f"{_axis_ko(ax)} {coverage.n_days(rs)}일" for ax, rs in g.items() if rs]
    na = [_axis_ko(ax) for ax in axes if led.na.get(ax)]
    if not parts:
        note = "기간의 모든 날을 확인했습니다(오늘 제외)" + (f" · 해당 없음: {', '.join(na)}" if na else "")
    else:
        note = (f"미확인 날 {' · '.join(parts)} — 그 날은 0시간이 아니라 '관측 없음'입니다(의심·실측 전, 다음 실행이 다시 읽습니다)"
                + (f" · 해당 없음: {', '.join(na)}" if na else ""))
    print(f"   [{name}] {note}")
    record(name, not parts, 0.0, note)


def mail_fallbacks(c, d0, d1, data, ps, col, t_run=None, led=None, state=None):
    r"""LM28 메일 사슬(P3·REQ-18·F-13·C-09) — COM(collect_outlook) 다음에 돈다. 첫 성공에서 멈추지 않는다:
      ① Windows Search 색인 — **늘**(COM 과 별개로) 돌려 일자별로 대조한다(COM zero_ok 인데 색인 행이 있거나 색인/COM>1.3 이면
         그날은 'COM 누락 의심' — 원장이 확인으로 치지 않는다).
      ② 원장(일자×축)에 미검증 날이 남으면 Outlook 웹 — 그 날의 범위만(--from·--to = 공백의 처음~끝, --only 메일|일정).
      ③ 그래도 남고 mailViaCopilot 이면 Copilot — 남은 날만 --ranges(Copilot 은 증인 — '읽음'을 만들지 않고, 이미 답한 날은 다시
         묻지 않는다). ④ data\import 에 반입 파일이 있으면 Import-MailCal.
      → G1 정제(core\privacy.scrub_csv) → mailmerge(공용 mail.csv·calendar.csv·mail_source.json).
    출처마다 자기 파일(data\outlook\src\mail_<tag>.csv·cal_<tag>.csv·mail_source_<tag>.json)만 쓴다 — LM24 의 'COM 이 0건을
    썼으면 대체 경로 생략'과 'COM 달별 완료 표(coverage.json) 삭제'는 없앴다(0건이 정상인지는 원장이 일자 단위로 말한다).
    한 실행에서 웹 경로가 rc 2(로그인)면 남은 웹 경로(Copilot·팀즈 웹)는 login_pending 으로 건너뛴다(state).
    반환: 병합 정보 dict."""
    state = state if isinstance(state, dict) else {}
    led = led if led is not None else open_ledger(c, data)
    src_dir = os.path.join(data, "outlook", "src")
    seed_legacy(data)
    os.makedirs(src_dir, exist_ok=True)
    # ① 색인 — 늘. COM 과 별개(Outlook 을 띄우지 않고 읽는다). 반복 회의 마스터가 있으면 일정은 partial(웹이 다시 읽는다).
    run_collector("Outlook 대체① Windows Search 색인 (늘 — COM 과 일자 대조)",
                  ps + [os.path.join(col, "Get-OutlookIndex.ps1"), "-From", d0, "-To", d1,
                        "-OutDir", src_dir, "-Tag", "index"], 240, src="index", led=led)
    sus = led.comgap(coverage.src_counts(src_dir, "com"), coverage.src_counts(src_dir, "index"), d0, d1)
    if sus:
        days = sorted({d for d, _a in sus})
        note = (f"COM 누락 의심 {len(days)}일({days[0]}~{days[-1]}) — 색인에는 메일·일정이 더 있습니다. COM 이 다른 프로필·계정에"
                " 붙었거나 필터가 어긋났을 수 있어(의심·실측 전) 그 날은 대체 경로로 계속 확인합니다")
        print(f"   [!] {note}")
        record("메일 COM↔색인 대조", True, 0.0, note)
    led.save()
    headless = collect_headless(c)
    # ② Outlook 웹 — 미검증 날만. 버전 무관·LLM 무관(지어낸 행 없음). 전용 Edge 프로필에 회사 계정 로그인 1회 필요.
    gaps = led.gaps(MAIL_AXES, d0, d1)
    sp = coverage.span(gaps)
    if isinstance(c.get("collect"), dict) and _truthy(c["collect"].get("mailAllPaths")):
        gaps, sp = {}, (d0, d1)            # collect.mailAllPaths — 앞 경로가 기간을 확인했어도 웹을 기간 전체로 돌려 합친다
    name2 = "Outlook 대체② Outlook 웹 (전용 Edge 프로필 — 미검증 날만)"
    if not sp:
        record(name2, True, 0.0, "건너뜀 — 원장에 미검증 날 없음(COM·색인이 기간을 확인)")
    elif state.get("login_pending"):
        _skip_login(name2)
    elif c.get("mailViaWeb", True) and "--no-mail-web" not in sys.argv:
        st2 = run_collector(name2, [sys.executable, os.path.join(col, "Get-OutlookWeb.py"), "--from", sp[0], "--to", sp[1],
                                    "--out-dir", src_dir, "--tag", "owa"] + _only(gaps, "--only"),
                            180 + 150 * _months(sp[0], sp[1]), src="owa", led=led)
        _edge_rc2(st2, state, name2, "Outlook")
    else:
        record(name2, True, 0.0, "건너뜀(config.mailViaWeb=false)")
    # ③ Copilot — 남은 날만(증인). 이미 증언·답한 날은 다시 묻지 않는다.
    name3 = "Outlook 대체③ Copilot 메일·일정 (남은 날만 — 증인)"
    if headless:
        record(name3, True, 0.0, "수집만 모드 — Copilot 은 판정 전용, 추가 PC 수집엔 쓰지 않습니다(config.collectOnlyHeadless)")
    elif not c.get("mailViaCopilot", True) or "--no-mail-copilot" in sys.argv:
        record(name3, True, 0.0, "건너뜀(config.mailViaCopilot=false)")
    elif state.get("login_pending"):
        _skip_login(name3)
    else:
        # 오늘은 묻지 않는다 — 아직 메일이 오는 날이고(웹·COM 도 partial), 매 실행 오늘 하루를 위해 왕복하지 않게
        g3 = led.gaps(MAIL_AXES, d0, _yday(d1), witness="copilot") if _yday(d1) >= d0 else {}
        rm = coverage.union(g3, ("mail_in", "mail_out"))
        rc_ = g3.get("cal") or []
        jobs = ([("", rm)] if rm and rm == rc_ else [(k, r) for k, r in (("mail", rm), ("cal", rc_)) if r])
        if not jobs:
            record(name3, True, 0.0, "건너뜀 — 남은 미검증 날 없음(또는 이미 Copilot 이 답한 날)")
        for kind, rs in jobs:
            if state.get("login_pending"):
                _skip_login(name3)
                break
            nm = name3 + (f" — {'메일' if kind == 'mail' else '일정'}" if kind else "")
            st3 = run_collector(nm, [sys.executable, os.path.join(col, "Get-MailViaCopilot.py"), "--from", d0, "--to", d1,
                                     "--ranges", coverage.fmt_ranges(rs), "--out-dir", src_dir, "--tag", "copilot"]
                                + (["--only", kind] if kind else []),
                                300 + 600 * 2 * max(1, coverage.n_days(rs) // 30 + 1), src="copilot", led=led)
            _edge_rc2(st3, state, nm, "Copilot")
    # ④ 반입 파일(사람이 넣은 .eml·.ics·.csv) — 있을 때만
    imp = _import_files(data)
    if imp:
        run_collector("메일·일정 반입 파일 (data\\import — .eml·.ics·.csv)",
                      [sys.executable, os.path.join(col, "Import-MailCal.py"), "--in", imp, "--out-dir", src_dir,
                       "--from", d0, "--to", d1], 300, src="import", led=led)
    g1_mail(c, data)
    info = merge_mail(c, data, led, d0, d1)
    report_gaps(led, d0, d1, MAIL_AXES, "메일·일정 원장(미확인 날)")
    led.save()
    return info


def _outlook_budget(c, d0, d1):
    """Outlook COM 수집 한 회차의 시간 예산(초) — config.outlookBudgetSec(0 = 자동). 자동은 240 + 60×개월(360~900).
    수집기가 달 단위로 이어서 읽으므로(data\\outlook\\src\\coverage_com.json) 예산 안에 못 끝내도 다음 회차·다음 실행이
    남은 달을 잇는다 — 예전 고정 360초는 메일이 많은 PC 에서 오래된 달을 영영 빠뜨렸다(실측 제보: 1~5월 공백)."""
    months = max(1, (date.fromisoformat(d1) - date.fromisoformat(d0)).days // 30 + 1)
    try:
        v = int(c.get("outlookBudgetSec") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else max(360, min(900, 240 + 60 * months))


def collect_outlook(c, d0, d1, data, ps, col, led=None):
    r"""Outlook COM 수집 — 기간의 달을 최신 달부터 읽고, 예산에 닿아 못 읽은 달(coverage: partial)이 남으면
    진행이 있는 한 같은 실행 안에서 최대 2회 더 이어서 읽는다(회차마다 완료된 달은 건너뛰므로 앞으로만 간다).
    그래도 남으면 last_run.json 에 미수집 달을 적고 화면(수집 데이터 현황·주간 활동 추이)이 그것을 보여 준다.
    LM28: 출처별 파일(-OutDir data\outlook\src -Tag com → mail_com.csv·cal_com.csv·mail_source_com.json·coverage_com.json)에
    쓰고, LMSTATUS ranges 를 원장(led)에 반영한다. 종료 코드: 0 정상 · 1 기간 0행 · 3 건너뜀·실패(사유)."""
    budget = _outlook_budget(c, d0, d1)
    seed_legacy(data)                      # COM 이 src 폴더를 만들기 전에 — 첫 실행의 옛 공용 파일 보존
    src_dir = os.path.join(data, "outlook", "src")
    src_p = os.path.join(src_dir, "mail_source_com.json")
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
        st = run_collector(name, ps + [os.path.join(col, "Get-OutlookData.ps1"), "-From", d0, "-To", d1,
                                       "-BudgetSec", str(budget), "-OutDir", src_dir, "-Tag", "com"]
                           + (["-NoRefresh"] if i else []), budget + 120, src="com", led=led)
        ok = st["ok"]
        src = _fresh_src(t_pass)
        if st["rc"] not in (0, 1) or src.get("source") != "com" or src.get("coverage_complete", True):
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
import watch as _watch_mod  # noqa: E402
from watch import stage_limits as _core_stage_limits  # noqa: E402
from watch import watch_child as _core_watch_child  # noqa: E402
# LM28(P6·F-23): 이 프로세스 안에서 감시기가 멈춘 단계를 끊을 때 taskkill 대신 Job 으로(core\proc.kill_tree — 자식을 띄울 때
# proc.attach 로 Job 에 넣어 둔다). 전용 Edge 는 Job 에서 이탈해 떠 있으므로 같이 죽지 않는다.
_watch_mod.kill_tree = proc.kill_tree
kill_tree = proc.kill_tree  # 기존 호출부 이름 유지

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
    job = proc.attach(p)                 # LM28: 단계가 끝나면(정상·중단) 남은 손자까지 Job 째 정리 — Edge 는 이탈해 산다
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
        # 시작 쪽 확장 — 브라우저 힌트(≈90일)가 아직 닿는 범위만. 그보다 먼 과거는 어떤
        # 재수집으로도 못 메우므로 매 실행 헛수고를 만들지 않는다(최종 검증 INFO).
        return True, f"저장된 기록은 {dates[0]} 부터입니다 (요청 {d0} — 힌트가 닿는 만큼 보강)"
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
            # 보관하며 data\activity·data\pc 를 통째로 옮기면 그 폴더가 사라진다 — 빈 폴더를 되만들어
            # 둔다(이 PC 의 새 수집이 같은 자리에 쌓인다).
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


def open_ledger(c, data):
    r"""일자×축 원장(data\coverage_ledger.json) — 판(LM28-COV-1|collect.cursorEpoch)·PC 가 다르면 비운 채로 연다."""
    try:
        epoch = int(((c.get("collect") or {}).get("cursorEpoch")) or 1)
    except (TypeError, ValueError, AttributeError):
        epoch = 1
    host = machine_id() or os.environ.get("COMPUTERNAME", "")
    led = coverage.Ledger.load(os.path.join(data, coverage.FILE_NAME), ver=f"{coverage.LEDGER_VER}|{epoch}", host=host)
    if led.dropped:
        print("   (수집 원장을 처음부터 — " + ("collect.cursorEpoch 가 바뀌었습니다" if led.dropped == "ver"
                                          else "다른 PC 의 원장입니다") + ")")
    elif led.dropped_src:
        names = {"owa": "Outlook 웹", "teams_web": "팀즈 웹"}
        print("   (" + "·".join(names.get(s, s) for s in led.dropped_src)
              + " 의 지난 '읽음' 표시를 지우고 그 날들을 다시 읽습니다 — 확인 규칙이 바뀌었습니다)")
    return led


def reset_cursors(c, data):
    r"""--reset-cursors — 수집기 커서와 원장을 지운다(다음 수집이 기간 전체를 처음부터 읽는다):
    COM 달별 완료 표(data\outlook\src\coverage_com.json·옛 data\outlook\coverage.json) · 팀즈 웹 방 커서
    (data\m365\teams_web_rooms.json) · 원장(모든 축 not_attempted). 수집한 행(CSV)은 지우지 않는다."""
    gone = []
    for rel in (("outlook", "src", "coverage_com.json"), ("outlook", "coverage.json"), ("m365", "teams_web_rooms.json")):
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


def close_edge_once(state, why):
    r"""우리가 띄운 전용 Edge 를 닫는다(tools\copilot_auto.close_own_edge — owner.json 이 있을 때만, CDP Browser.close).
    한 실행에 1회. 이 실행의 웹 경로가 로그인을 기다리는 중(rc 2)이면 닫지 않고 안내만 한다 — 사람이 그 창에서
    로그인하는 중일 수 있고, 다음 실행이 owner.json 의 Edge 를 다시 쓴다(F-17)."""
    if EDGE["closed"]:
        return None
    EDGE["closed"] = True
    if isinstance(state, dict) and state.get("login_pending"):
        print("\n   전용 Edge 창은 닫지 않았습니다 — 그 창에서 회사 계정으로 로그인한 뒤 다시 실행하면 이어서 읽습니다.")
        return {"closed": False, "why": "login_pending"}
    fn = _CLOSE_EDGE
    if fn is None:
        try:
            tools = os.path.join(ROOT, "tools")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import copilot_auto
            fn = copilot_auto.close_own_edge
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


def _teams_rows(data, d0, d1):
    r"""data\m365\teams_*.csv 의 기간 안 행 수(팀즈 na 판정 — 모든 출처 0행인가)"""
    import glob
    n = 0
    for p in glob.glob(os.path.join(data, "m365", "teams_*.csv")):
        try:
            with open(p, encoding="utf-8-sig", errors="replace", newline="") as f:
                n += sum(1 for r in csv.DictReader(f) if d0 <= str(r.get("time") or "")[:10] <= d1)
        except (OSError, csv.Error):
            continue
    return n


def collect_teams(c, d0, d1, data, ps, col, led=None, state=None):
    r"""LM28 팀즈 사슬(W1-01·F-08·REQ-18) — Graph(clientId 있을 때) → 앱 창 읽기(늘 · 단락 없음) → 웹(Graph 가 기간을
    다 확인하지 못했으면) → Copilot(teamsViaCopilot · 원장 teams 공백만) → G1 정제.
    앱 창에서 새 줄을 얻었다고 웹을 건너뛰지 않는다 — 창 읽기는 화면에 그려진 대화만 읽는 보조 경로다(LM24 preferApp 단락
    제거). rc 4(새 행 0)는 실패가 아니다. 웹 경로가 rc 2 면 남은 웹 경로는 login_pending 으로 건너뛴다.
    팀즈 흔적(counts.teams_present)도 행도 없으면 teams 축을 na(해당 없음)로 둔다."""
    if "--no-teams" in sys.argv:
        return
    state = state if isinstance(state, dict) else {}
    led = led if led is not None else open_ledger(c, data)
    headless = collect_headless(c)
    present, graph_full = False, False
    if (c.get("graph") or {}).get("clientId"):
        # 비대화 모드 — 토큰이 만료됐을 때 device-code 입력을 기다리며 300초를 버리지 않는다
        # (여기엔 콘솔이 없어 사용자는 그 프롬프트를 볼 수도 없다). 로그인은 --login-only 로.
        # Graph 의 R-GRAPH-LOGIN(rc 3)은 Edge 로그인과 별개 — login_pending 으로 보지 않는다.
        stg = run_collector("팀즈 채팅 (Graph)", [sys.executable, os.path.join(col, "Get-TeamsChats.py"),
                                              "--from", d0, "--to", d1, "--non-interactive"], 300, src="teams_graph", led=led)
        yday = _yday(d1)
        graph_full = stg["rc"] == 0 and not stg["reasons"] and (yday < d0 or not led.gaps(("teams",), d0, yday)["teams"])
    # 앱 창 읽기 — 늘(보조 · 화면에 그려진 대화만). 웹을 건너뛰는 근거로 쓰지 않는다.
    stw = run_collector("팀즈 채팅 (앱 창 읽기 — 보조, 켜져 있는 대화)", ps + [os.path.join(col, "Get-TeamsWindow.ps1")],
                        120, src="teams_window", led=led)
    present = present or bool(stw["counts"].get("teams_present"))
    name_w = "팀즈 채팅 (웹 — 전용 Edge, 앱이 꺼져 있어도)"
    if graph_full:
        record(name_w, True, 0.0, "건너뜀 — Graph 가 기간 전체를 확인")
    elif state.get("login_pending"):
        _skip_login(name_w)
    elif c.get("teamsWeb", True):
        stb = run_collector(name_w, [sys.executable, os.path.join(col, "Get-TeamsWeb.py"), "--from", d0, "--to", d1],
                            1200, src="teams_web", led=led)
        present = present or bool(stb["counts"].get("teams_present"))
        _edge_rc2(stb, state, name_w, "Teams")
    # 팀즈 흔적(설치·프로세스·웹 목록의 방)도 행도 없으면 해당 없음(na) — 그 PC 의 팀즈 공백을 '미관측'으로 세지 않는다
    led.set_na("teams", not present and _teams_rows(data, d0, d1) == 0)
    led.save()
    # Copilot 은 '판정 엔진'이다. 팀즈 조회는 테넌트에 커넥터가 있어야만 되는 별개 기능이라, 없는 환경에서 계속 물으면
    # 판정에 쓸 세션만 소진된다(실측) — 켜져 있어도 원장 teams 공백(이미 답한 날 제외)만 묻는다.
    name_c = "팀즈 채팅 (Copilot — 원장 공백만)"
    if headless:
        pass
    elif not c.get("teamsViaCopilot"):
        print("\n── 팀즈 채팅 (Copilot 경로 건너뜀 — config.teamsViaCopilot=false)")
        print("   팀즈는 앱 창 읽기·웹 경로(전용 Edge)·Graph 로 모읍니다.")
        print("   Copilot 은 AI 판정 전용으로 아껴 둡니다.")
        record("팀즈 채팅", True, 0.0, "Copilot 경로 건너뜀(설정)")
    elif state.get("login_pending"):
        _skip_login(name_c)
    else:
        g = led.gaps(("teams",), d0, _yday(d1), witness="teams_copilot")["teams"] if _yday(d1) >= d0 else []
        if not g:
            record(name_c, True, 0.0, "건너뜀 — 원장에 팀즈 미검증 날 없음(또는 이미 Copilot 이 답한 날)")
        else:
            stc = run_collector(name_c, [sys.executable, os.path.join(col, "Get-TeamsViaCopilot.py"), "--from", d0, "--to", d1,
                                         "--ranges", coverage.fmt_ranges(g)],
                                300 + 600 * max(1, coverage.n_days(g) // 30 + 1), src="teams_copilot", led=led)
            _edge_rc2(stc, state, name_c, "Copilot")
    led.save()
    g1_teams(c, data)
    report_gaps(led, d0, d1, ("teams",), "팀즈 원장(미확인 날)")


def web_only(c, kind, d0, d1, data, col):
    r"""--web-only mail|teams — 화면의 [Outlook 웹 읽기]·[팀즈 웹 읽기]용(LM28 F-14): 기간(d0·d1)을 늘 넘기고, 읽은 뒤
    원장·G1 정제(·메일은 병합)까지 한다. 사람이 누른 것이라 공백만이 아니라 기간 전체를 읽는다. 끝에 이 실행이 띄운
    전용 Edge 를 닫는다(로그인 대기면 둔다). → 종료 코드(0 정상 · 2 로그인 필요 · 1 실패)"""
    state = {}
    led = open_ledger(c, data)
    sts = []
    if kind in ("mail", "all"):
        src_dir = os.path.join(data, "outlook", "src")
        seed_legacy(data)
        os.makedirs(src_dir, exist_ok=True)
        nm = "Outlook 대체② Outlook 웹 (전용 Edge 프로필 — 화면에서 실행)"
        st = run_collector(nm, [sys.executable, os.path.join(col, "Get-OutlookWeb.py"), "--from", d0, "--to", d1,
                                "--out-dir", src_dir, "--tag", "owa"], 180 + 150 * _months(d0, d1), src="owa", led=led)
        _edge_rc2(st, state, nm, "Outlook")
        sts.append(st)
        g1_mail(c, data)
        merge_mail(c, data, led, d0, d1)
        report_gaps(led, d0, d1, MAIL_AXES, "메일·일정 원장(미확인 날)")
    if kind in ("teams", "all"):
        nm = "팀즈 채팅 (웹 — 화면에서 실행)"
        if state.get("login_pending"):
            _skip_login(nm)
        else:
            st = run_collector(nm, [sys.executable, os.path.join(col, "Get-TeamsWeb.py"), "--from", d0, "--to", d1],
                               1200, src="teams_web", led=led)
            _edge_rc2(st, state, nm, "Teams")
            sts.append(st)
            g1_teams(c, data)
            report_gaps(led, d0, d1, ("teams",), "팀즈 원장(미확인 날)")
    led.save()
    close_edge_once(state, "web_only")
    if state.get("login_pending"):
        return 2
    return 0 if sts and all(s["ok"] for s in sts) else 1


def main():
    """실행 전체 — 마지막 finally 에서 이 실행이 띄운 전용 Edge 를 1회 닫는다(로그인 대기면 둔다 · P6)."""
    try:
        return _main()
    finally:
        close_edge_once(STATE, "run_end")


def _main():
    c = cfg()
    # 기본 기간은 화면(UI 칩 '올해')·LoadMonitor28.bat 과 같은 '올해 1월 1일부터' — 셋이 달라(이번 달 1일 / 최근 3개월 /
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
    print(f"[LoadMonitor28] {d0} ~ {d1}"
          + ("  · AI 판정 포함" if "--ai" in sys.argv else "  · AI 판정 없음(규칙 결과만)"))
    if "--reset-cursors" in sys.argv:
        reset_cursors(c, data)
    wo = arg("--web-only")
    if "--web-only" in sys.argv:
        if wo not in ("mail", "teams", "all"):
            print("[!] --web-only 뒤에 mail · teams · all 중 하나를 적으세요 (예: --web-only mail --from 2026-01-01 --to 2026-06-30)")
            return 1
        rc_w = web_only(c, wo, d0, d1, data, col)
        RUN["finished"] = time.strftime("%Y-%m-%d %H:%M")
        record("완료(웹 읽기)", rc_w == 0, 0.0, {0: "", 2: "로그인 필요 — 전용 Edge 창에서 회사 계정 1회"}.get(rc_w, "일부 실패"))
        return rc_w

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
        led = open_ledger(c, data)         # 일자×축 원장 — 수집기 LMSTATUS ranges 가 쌓이고, 메일·팀즈 사슬이 공백을 본다
        step("PC 가동 이력", ps + [os.path.join(col, "Get-PcOnHistory.ps1"), "-From", d0, "-To", d1], 300,
             src="pc_events", led=led)
        # 이벤트 로그가 롤오버로 기간을 못 덮으면 브라우저 '방문 시각'만으로 보강
        # (URL·제목은 조회하지 않는다)
        step("PC 가동 보강 (브라우저 방문 시각 — URL 미수집)",
             [sys.executable, os.path.join(col, "Get-PcOnHints.py"), "--from", d0, "--to", d1], 240,
             src="pc_hints", led=led)
        # 메일: COM(달 단위 이어서 · 최대 3회) → 색인(늘) → 원장 공백만 웹 → 남은 날만 Copilot → 반입 → G1 → 병합
        collect_outlook(c, d0, d1, data, ps, col, led)
        mail_fallbacks(c, d0, d1, data, ps, col, None, led, STATE)
        step("파일 수정 이력", ps + [os.path.join(col, "Get-FileActivity.ps1"), "-From", d0, "-To", d1], 300, src="files")
        step("최근 문서 (Recent·MRU)", ps + [os.path.join(col, "Get-RecentFiles.ps1"), "-From", d0, "-To", d1], 180,
             src="recent", led=led)
        step("git 커밋 (SW개발)", [sys.executable, os.path.join(col, "Get-GitActivity.py"),
                                "--from", d0, "--to", d1], 240, src="git", led=led)
        # 팀즈: Graph(설정 시) → 앱 창(늘 · 보조) → 웹(전용 Edge) → Copilot(원장 공백만) → G1
        collect_teams(c, d0, d1, data, ps, col, led, STATE)
        led.save()
        if "--collect-only" in sys.argv:
            close_edge_once(STATE, "collect_end")    # 수집만 — 수집 끝에 닫는다(로그인 대기면 둔다)

    if "--collect-only" in sys.argv:
        # 근무시간 실측을 **로드바 안에서** 계산·저장한다 — 예전에는 화면이 열릴 때 재계산해
        # '끝났는데 탐색하듯 도는' CPU 가 로드바 밖에 있었다(제보). 실패해도 수집은 유효.
        try:
            from progress import progress as _pg
            import extract as _XW
            _pg("근무시간 실측", 0, 1)
            print("\n── 근무시간 실측(추이 실선 재료 — 이 계산까지가 수집입니다)")
            _cfgw = _XW.load_cfg()
            # 제외어 = 내장 ∪ config.excludePathKeywords — core\privacy 한 곳(LM28: mine 을 임포트하면 sys.stdout 이 바뀐다)
            import privacy as _PV
            _exw = _PV.excluded_keywords(_cfgw)
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

    _job_m = proc.attach(p)                                  # 멈춰 끊을 때 Job 째(taskkill 없음 · LM28)
    stop_m = watch_child(p, _on_mine, "업무 로드 추출")   # 멈추면 끊는다(정체 감지)
    rc_m = p.wait()
    proc.release(_job_m, p.pid)
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
    # 버튼(또는 LoadMonitor28-팀업로드.bat)으로 밀린 것까지 한 번에 보낸다.
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
    if (c.get("teamUpload") or {}).get("auto"):
        # 원하는 사람만 켜는 자동 전송(기본 꺼짐). 실패해도 묶음은 대기로 남는다.
        # v5: 주소는 팀 서버 주소 설정(core\teamaddr.py)이 늘 준다 — config.teamServerUrl 을 따로 보지 않는다.
        import teamaddr
        print(f"\n── 팀 서버 자동 업로드 (config.teamUpload.auto → {teamaddr.load(ROOT).url})")
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
