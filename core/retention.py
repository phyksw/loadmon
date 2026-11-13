# -*- coding: utf-8 -*-
r"""
retention.py — 보관기한·자동 삭제 단일원(spec §6.3 · D13 · D20). 화면 시작·분석 시작/끝·매일 예약 작업이 부른다.

분류(CLASSES — 설치 폴더 기준 상대 경로. data\ 와 report\ 밖은 지우지 않는다 — ui_error.log 하나만 빼고)
  keep          지우지 않음(나이로는): data\install.json · data\share_receipts.json · data\withdrawal.json ·
                data\af32_edge\**(전용 Edge 로그인 프로필) 와 그 옆 상태 파일(EDGE_SIDE — .chats.json·.busy.lock·.state.json·
                .throttle.json·.pace.json·.wait.json). 프로필의 Outlook·M365 사이트 자료는 copilot_auto.clear_site_data 가 단계마다,
                Edge 가 꺼져 있으면 purge 가 디스크에서(clear_edge_site_files — 쿠키·로그인 정보는 남긴다) 지운다.
  raw           data\outlook\** · data\coverage_ledger.json — 수집 자료와 수집기 상태(수집기 상태는 data\outlook\ 아래에 둔다).
                통째로만 지운다: 가장 새 파일이 rawDays 보다 오래되면 전부. 지우면 coverage_ledger.json 도 함께 지워진다(초기화).
                data\af32_edge.bad-*\**(죽어서 바꿔 둔 옛 전용 Edge 프로필 — 로그인 쿠키가 든다)도 raw — 사본마다 따로 통째로.
  intermediate  report\{signals_*,work_rows_*,run_meta_*,pivots_*,entities_*,ai_judgments_*,refine_map_*,dropped_signals_*,
                stage_state_*,evidence_*,judge_*.md,judge_cache.json,*.stale,collect_diag.txt,last_run.json} · data\cache\**
                (data\cache\name_hashes.json 은 파일 나이와 따로 해시마다 마지막으로 본 날로도 자른다 — privacy.prune_name_hashes)
  result        report\{agentic_*,workflow_*} · report\name_hashes_<tag>.json(그 tag 의 결과에 나온 이름을 가리는 해시 — 결과와
                같은 기한 · 그 tag 의 분석 자료가 다 지워지면 privacy.prune_name_hashes 가 함께 지운다)
  html          report\*.html(바로 아래)
  share         report\share\**
  other         그 밖에 data\·report\ 아래 모든 파일(intermediateDays) · 설치 폴더의 ui_error.log · %TEMP%\af32_* 파일(폴더는 아님)
                Copilot 계측 기록은 날짜별 파일(report\copilot_trace_YYYYMMDD.jsonl)이라 지난날 것이 파일 나이로 지워진다 —
                예전 꼴의 한 파일 기록(OLD_FORM_FILES — report\copilot_trace.jsonl·.1)은 보이면 나이와 상관없이 지운다.
                예전 판이 남기던 data\consent.json 도 OLD_FORM_FILES 다 — 읽지 않고, 보이면 지운다.
  나이 = 파일 수정 시각. 기한(일)은 core\afcfg 의 retention.*(D13 상한 적용). 날짜로 자른다 — 그 날 만든 파일은 expiry_date 가 알리는
  날(만든 날 + 기한)의 첫 정리 때 지워진다(시각까지 따져 하루 더 남지 않는다).
  run_meta_<tag>.json 은 같은 tag 의 결과(agentic_·workflow_)·html 파일이 남아 있는 동안 남긴다 — 결과를 읽는 쪽이 run_meta 의
  product 표식으로 tag 를 확인하기 때문이다(그 파일들이 기한으로 지워지면 run_meta 도 intermediateDays 규칙을 따른다).

API
  purge(root, cfg, *, now=None, dry_run=False) -> {"deleted": n, "by_class": {class: n}, "errors": [...], "paths": [...],
                                                  "links": [...], "edge_site": {...}, "name_hashes": ...}
  purge_classes(root, classes, *, dry_run=False) -> 같은 형식   (D9 제한 고객 목록이 바뀌면 raw·intermediate·result·html·share)
  purge_legacy(root, *, temp_dir=None, dry_run=False) -> {"deleted", "paths", "errors"}   (D20 — 시작할 때마다 가장 먼저)
  purge_all(root, *, keep_consent=False, keep_edge=False, temp_dir=None, keep=(), last=LAST_FILES) -> {"deleted", "paths", "errors"}
      keep_consent=True 면 install.json·share_receipts.json·withdrawal.json(설치 정보·공유 영수증·지우기 기록)을 남긴다 —
      자료만 지울 때. keep_edge=True 면 전용 Edge 프로필(옛 사본 .bad-* 는 지운다). keep = 남길 상대 경로 ·
      last = 맨 끝에 지울 것(설치 정보).
      이 프로세스가 쥔 분석 잠금(data\run.lock)은 지우지 않는다.
  drop_raw(root) -> int     data\outlook\raw 바로 아래의 보통 파일을 지운 수(연결은 따라가지 않는다) · raw_left(root) -> [경로]
  run_lock_path(root) · run_lock_pid(root) -> pid|None · run_active(root) -> bool
      run.py 는 실행 내내 data\run.lock {pid, date} 를 쥔다. run_active = 그 pid 가 살아 있는 이 폴더의 run.py 이거나
      consent._busy(root)(이 폴더의 분석·수집 프로세스). 화면·retention.py --purge-all 은 참이면 지우기를 거절한다.
  restricted_stale(root, tag, restricted) -> bool   report\run_meta_<tag>.json 의 restricted_sha256 이 없거나 지금 목록과 다르면 참
  clear_edge_site_files(root, *, dry_run=False) · edge_running(root)   전용 Edge 가 꺼져 있을 때 Outlook·M365 사이트 자료 지우기
  expiry_table(root, cfg, *, now=None) -> [{"class","label","where","days","files","oldest","next_delete","server"}]
  kept_table(root) -> [{"class","label","where","files","until"}]   보관기한 없이 [모두 지우기] 때까지 남는 것(전용 Edge 프로필·영수증)
  expiry_date(cfg, cls, *, when=None) -> 'YYYY-MM-DD'      (그 날 만든 cls 파일이 지워지는 날)
  task_name(root) · register_task(root) -> bool · unregister_task(root) -> bool · task_registered(root) -> bool|None
      매일 1회 사용자 예약 작업 'AgentFinder32 보관기한 정리 <h6>' = python\pythonw.exe -I -X utf8 -B core\retention.py
      --purge --root <root>. 실패는 False(예외를 던지지 않는다) — 화면은 '화면을 열 때와 분석 시작·끝에 지웁니다' 로 알린다.
  sync_task(root, cfg, *, starting_run=False) -> {"task": True|False|None, "message": str}
      시작할 때마다(화면 시작 · run.py 의 시작 확인 뒤) 그 작업을 설정 retention.scheduledPurge 에 맞춘다: 켜져 있으면 없을 때
      만들고, 꺼져 있으면 있을 때 지운다. 만드는 것은 지울 것이 있을 때만 — 분석이 시작할 때(starting_run=True · run.py)나 이
      설치에 자료가 있을 때(install.owned_data). 빈 설치에서 화면만 열면 만들지 않는다(None). 같은 날에는 data\task_state.json 만
      읽는다. AF32_NO_TASK 가 있으면 건드리지 않는다(None).
  errors 항목 = {"path": 상대 경로, "why": 까닭(한국어), "holder": 잡고 있는 프로그램 이름|""}.
지우기 규칙(ui\app.py reset_files 에서 옮김): 읽기 전용은 풀고 다시 · 잠깐 잠긴 파일은 쉬었다 다시 · 그래도 남으면 RETRY_SEC 뒤
한 번 더 · 끝내 남으면 Restart Manager 로 잡고 있는 프로그램 이름 · 260자 넘는 경로는 확장 경로(\\?\) · 정션·심볼릭 링크 폴더에는
들어가지 않는다(그 너머를 지우지 않는다) · '지웠다' 는 지운 뒤 정말 없을 때만 센다 · 설치 폴더 밖(과 %TEMP%\af32_* ·
purge_legacy 가 이름으로 짚은 옛 LoadMonitor 임시 항목)은 지우지 않는다.
CLI  python core\retention.py --purge [--root R] [--dry-run] [--json]
         끊긴 [모두 지우기] 마저 하기(consent.resume_withdrawal) → purge_legacy → purge → 남은 서버 사본 다시 지우기 → 분석이 돌지
         않으면 수집 원자료 지우기 → data\purge_status.json {date, deleted, errors, …}(날짜만 — 화면이 '매일 정리' 로 보인다)
         종료 코드: 0 · 1(못 지운 것이 있다) · 3(RC_WIPED — 끝나지 않은 [모두 지우기]를 이 호출이 마쳤다: AgentFinder32.bat 은
         그 시작에서 분석하지 않고 끝낸다. 매일 정리 작업은 같은 명령을 쓰지만 종료 코드를 보지 않는다 — 그 작업은 방금 지워졌다)
     python core\retention.py --legacy | --expiry | --register | --unregister | --task-status  [--root R]
     python core\retention.py --purge-all [--keep-consent] [--root R] [--json]   (다른 사용자·주인을 모르는 자료 지우기 — D17)
         분석이 돌면 거절한다(종료 코드 1 · 아무것도 지우지 않는다). 공유 영수증이 있으면 그 서버 사본부터 지운다(지우기만).
         서버에서 못 지운 영수증이 남으면 [모두 지우기] 순서(consent.withdraw)로 지운다 — 영수증에 표시("withdraw")를 붙여
         남기고 data\withdrawal.json 을 써서 다음 시작 때 다시 지운다. 남은 영수증이 없으면 모두 지운다(설치 정보를 맨 끝에).
         매일 정리 작업도 지운다. --keep-consent 는 설치 정보·영수증·지우기 기록만 남기고 지운다(자료만 지우기).
"""
import fnmatch
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import afcfg  # noqa: E402
import lmname  # noqa: E402

ROOT = os.path.dirname(_HERE)
RETRY_SEC = 1.5            # 첫 번에 못 지운 파일을 한 번 더 지우기 전 쉼(초) — 백신 검사·미리보기·동기화처럼 잠깐 잡은 것
HOLDER_MAX = 20            # 잡고 있는 프로그램 이름을 물어볼 파일 수 상한
LEGACY_TEMP_GRACE_SEC = 600   # %TEMP% 의 옛 판 임시 항목 중 이 시간(초) 안에 바뀐 것은 지금 쓰는 중으로 보고 남긴다
NO_WIN = 0x08000000
_REPARSE_POINT = 0x400     # FILE_ATTRIBUTE_REPARSE_POINT
_NAME_SURROGATE = 0x20000000   # 다른 경로를 가리키는 재분석 태그(정션·심볼릭 링크)

EDGE = lmname.EDGE_PROFILE_NAME.lower()
# 전용 Edge 프로필 옆 상태 파일(copilot_auto._side_path) — 프로필과 함께 keep
EDGE_SIDE = (".busy.lock", ".state.json", ".throttle.json", ".pace.json", ".wait.json", ".chats.json")
EDGE_BAD = EDGE + ".bad-"  # copilot_auto.recreate_profile 이 바꿔 둔 죽은 프로필 — raw(사본마다 통째로)
KEEP_FILES = ("data/install.json", "data/share_receipts.json", "data/withdrawal.json")
CONSENT_FILES = KEEP_FILES   # purge_all(keep_consent=True) 가 남기는 것 — 설치 정보 · 공유 영수증 · 지우기 기록
LAST_FILES = ("data/install.json",)   # purge_all 이 맨 끝에 지운다(중간에 끊겨도 남은 자료의 주인을 안다)
RAW_FILES = ("data/coverage_ledger.json",)
ROOT_FILES = ("ui_error.log",)      # 설치 폴더 바로 아래의 작업 파일(화면이 못 켜질 때 남기는 원인) — other
# 이제 쓰지 않는 파일 — 보이면 나이와 상관없이 지운다(읽지 않는다).
#   · report\copilot_trace.jsonl·.1 — 예전 꼴의 Copilot 계측 기록(한 파일에 날마다 덧붙어 파일 나이로는 지워지지 않았다). 지금은
#     날짜별 파일 report\copilot_trace_YYYYMMDD.jsonl 을 쓴다(copilot_auto.TRACE_LEGACY 와 같은 이름).
#   · data\consent.json — 예전 판이 이 PC 에 남기던 기록. 이 도구는 그 파일을 쓰지도 읽지도 않는다.
OLD_RECORD = "data/consent.json"
OLD_FORM_FILES = ("report/copilot_trace.jsonl", "report/copilot_trace.jsonl.1", OLD_RECORD)
RUN_LOCK = "run.lock"               # data\run.lock — run.py 가 실행 내내 쥔다 {pid, date}
TASK_STATE = "task_state.json"      # data\task_state.json — sync_task 가 맞춘 날(날짜만 · 같은 날에는 다시 묻지 않는다 · other 분류)
NO_TASK_ENV = "AF32_NO_TASK"        # 값이 있으면 sync_task 가 작업 스케줄러를 건드리지 않는다(시험 — tests\_boot.py)
TASK_FAIL_MSG = "매일 정리 작업을 등록하지 못했습니다 — 화면을 열 때와 분석 시작·끝에 보관기한이 지난 자료를 지웁니다"
RC_WIPED = 3                        # retention.py --purge 의 종료 코드 — 끝나지 않은 [모두 지우기]를 이 호출이 마쳤다(run.py 의 3 과 같은 뜻)
TASK_REMOVE_FAIL_MSG = "예전에 만든 매일 정리 작업('{task}')을 지우지 못했습니다 — Windows 작업 스케줄러에서 직접 지울 수 있습니다"
PURGE_STATUS = "purge_status.json"  # data\purge_status.json — retention.py --purge(매일 정리)의 마지막 결과(날짜만 · 화면의
#                                     /api/retention 이 이 이름으로 읽는다 · other 분류 — 설치의 자료로 세지 않는다)
INTERMEDIATE_PATTERNS = ("signals_*", "work_rows_*", "run_meta_*", "pivots_*", "entities_*", "ai_judgments_*",
                         "refine_map_*", "dropped_signals_*", "stage_state_*", "evidence_*", "judge_*.md",
                         "judge_cache.json", "*.stale", "collect_diag.txt", "last_run.json")
RESULT_PATTERNS = ("agentic_*", "workflow_*")
HASH_PATTERNS = ("name_hashes_*",)  # report\name_hashes_<tag>.json — result 분류(run_meta 를 붙잡는 '살아 있는 결과'로는 세지 않는다)
CLASSES = ("keep", "raw", "intermediate", "result", "html", "share", "other")
DAYS_KEY = {"raw": "rawDays", "intermediate": "intermediateDays", "result": "resultDays", "html": "htmlDays",
            "share": "shareDays", "other": "intermediateDays"}
LABELS = {
    "raw": ("수집 자료(메일·일정 목록)", "data\\outlook"),
    "intermediate": ("중간 자료(신호·업무 분류·근거·캐시)", "report\\signals_* 등 · data\\cache"),
    "result": ("분석 결과(Agentic AI 후보·워크플로우)", "report\\agentic_* · workflow_* · name_hashes_*"),
    "html": ("리포트(HTML)", "report\\*.html"),
    "share": ("공유 미리보기·보낸 사본", "report\\share"),
    "other": ("그 밖의 작업 파일", "data\\ · report\\ 의 나머지 · ui_error.log · %TEMP%\\af32_*"),
}
SERVER_ROWS = (("serverPersonal", "serverPersonalDays", "조직장 서버의 개인 리포트(공유한 경우)"),
               ("serverTeam", "serverTeamDays", "조직장 서버의 익명 팀 집계(공유한 경우)"))
# 전용 Edge 가 꺼져 있을 때 디스크에서 지우는 사이트 자료(쿠키·로그인 정보는 남긴다) — 프로필 Default\ 아래
EDGE_SITE_DIRS = ("Service Worker", "Cache", "Code Cache")
EDGE_SITE_ORIGINS = ("outlook", "office.com", "office365.com", "cloud.microsoft", "microsoft365.com", "sharepoint.com")

# D20 — 옛 LoadMonitor 자료
LEGACY_DATA_DIRS = ("pc", "m365", "files", "manual", "import", "추가PC", "근태", "programs", "activity",
                    lmname.OLD_PROFILE)     # 마지막 = LM24 의 전용 Edge 프로필 폴더
LEGACY_DATA_FILES = ("git_source.json", "files_excluded.json")
LEGACY_DATA_PATTERNS = ("lm*_edge", "lm*_edge.*", lmname.OLD_PROFILE + ".*", "teams*")
LEGACY_REPORT_PATTERNS = ("mm_rows_*", "mm_meta_*", "attendance_*", "day_hours_*", "admin_days_*", "ai_narratives_*",
                          "보고서_*", "분석리포트_*", "리포트_*", "team_report_status.json", "member*.json")
LEGACY_REPORT_DIRS = ("얼린보고서", "upload_pending", "upload_sent")
LEGACY_CONFIG_FILES = ("team_server.json", "detail_aliases.json", "project_aliases.json", "excluded_work.json")
# %TEMP% 의 옛 LoadMonitor 임시 항목 — 그 판들이 실제로 쓴 이름만(같은 머리 lm_ 를 쓰는 다른 프로그램의 것은 건드리지 않는다).
#   파일: <머리>_from.txt·_to.txt(bat 의 기간) · _diag_prompt.txt(진단 프롬프트) · _hist_copy·_pccmp_hist(브라우저 방문 기록 사본과
#         그 SQLite 곁 파일 -wal·-shm·-journal) · 예약 작업 XML · 이동 준비 스크립트 · 자가 시험 기록
#   폴더: <머리>_pc_compare(가동 시간 비교 작업 폴더) — 정확한 이름의 폴더만 지운다(모르는 폴더 안으로는 들어가지 않는다)
_LEGACY_TAGS = ("lm", "lm28", "lm29", "lm30", "lm30v1")      # LM17~25 는 lm_ · 그 뒤는 판 이름
_SQLITE_SIDE = ("", "-wal", "-shm", "-journal")
LEGACY_TEMP_NAMES = (tuple(f"{t}_{n}" for t in _LEGACY_TAGS for n in ("from.txt", "to.txt", "diag_prompt.txt"))
                     + tuple(f"{t}_{n}{s}" for t in _LEGACY_TAGS for n in ("hist_copy", "pccmp_hist") for s in _SQLITE_SIDE))
LEGACY_TEMP_DIRS = tuple(f"{t}_pc_compare" for t in _LEGACY_TAGS)
LEGACY_TEMP_PATTERNS = ("lm_task_*.xml", "lm27_task_*.xml", "lm27_move_*.ps1", "lm27_selftest_*.jsonl",
                        "lm[0-9][0-9]-prepare-move.ps1", "lm[0-9][0-9]v[0-9]-prepare-move.ps1",
                        "lm[0-9][0-9]-prepare-move-*.ps1")       # 무늬는 파일에만 쓴다
# 운영 문서(운영기준 'LoadMonitor 정리')가 그대로 적는 꼴 — 위 세 목록의 모든 이름이 이 중 하나에 맞는다(tests\test_p59)
LEGACY_TEMP_DOC = ("lm*_from.txt", "lm*_to.txt", "lm*_diag_prompt.txt", "lm*_hist_copy*", "lm*_pccmp_hist*", "lm*_pc_compare",
                   "lm_task_*.xml", "lm27_task_*.xml", "lm27_move_*.ps1", "lm27_selftest_*.jsonl", "LM*-Prepare-Move*.ps1")
TASK_TIME = "12:30"


# ── 경로 도우미(ui\app.py 에서 옮김) ───────────────────────────────────────────────────────
def _xlong(p):
    r"""확장 경로(\\?\ — 260자 넘는 경로도 읽고 지운다). 걷는 뿌리에 붙이면 os.walk 가 내놓는 모든 경로가 확장 경로가 된다."""
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


def _rel(p, base):
    """기준 폴더 기준 상대 경로(화면·기록용) — 드라이브가 다르면 절대 경로 그대로."""
    q = _plain(p)
    try:
        return os.path.relpath(q, _plain(base))
    except ValueError:
        return q


def _link_dir(p):
    """정션·심볼릭 링크처럼 다른 곳을 가리키는 폴더인가. lstat 을 못 하면 참(들어가지 않는다 — 모르면 지우지 않는 쪽)."""
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
    """파일 하나 지우기 → 지웠나(이미 없으면 참). 읽기 전용은 풀고 다시, 잠깐 잠긴 파일은 쉬었다 다시. 지운 뒤 정말 없을 때만 참."""
    lp = _xlong(path)
    for i in range(max(1, int(tries))):
        try:
            os.remove(lp)
        except FileNotFoundError:
            pass
        except PermissionError:
            try:
                os.chmod(lp, stat.S_IWRITE)
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
    """그 파일을 열고 있는 프로세스 → [(pid, 앱 이름, 서비스 이름)] (Windows Restart Manager · ctypes 한 세션). 오류면 []."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _UniqueProcess(ctypes.Structure):
            _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

        class _ProcessInfo(ctypes.Structure):
            _fields_ = [("Process", _UniqueProcess), ("strAppName", wintypes.WCHAR * 256),
                        ("strServiceShortName", wintypes.WCHAR * 64),
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
        key = ctypes.create_unicode_buffer(33)
        if rm.RmStartSession(ctypes.byref(sess), 0, key) != 0:
            return []
        try:
            q = _plain(path)
            q = q if len(q) < 260 else str(path)
            if rm.RmRegisterResources(sess, 1, (wintypes.LPCWSTR * 1)(q), 0, None, 0, None) != 0:
                return []
            reasons, n = wintypes.DWORD(0), 0
            for _ in range(3):
                need, have = wintypes.UINT(0), wintypes.UINT(n)
                buf = (_ProcessInfo * n)() if n else None
                rc = rm.RmGetList(sess, ctypes.byref(need), ctypes.byref(have), buf, ctypes.byref(reasons))
                if rc == 0:
                    return ([(int(buf[i].Process.dwProcessId), str(buf[i].strAppName or "").strip(),
                              str(buf[i].strServiceShortName or "").strip()) for i in range(min(have.value, n))]
                            if buf is not None else [])
                if rc != 234:                      # ERROR_MORE_DATA 가 아니면 모른다
                    return []
                n = int(need.value) + 2
            return []
        finally:
            rm.RmEndSession(sess)
    except Exception:  # noqa: BLE001 - 이름은 덤이다
        return []


def file_holders(paths):
    """못 지운 파일을 누가 열고 있나 → {경로(받은 그대로): '이름 · 이름'} (HOLDER_MAX 개까지). 이 프로세스는 '이 프로그램'."""
    out = {}
    if os.name != "nt" or not paths:
        return out
    me = os.getpid()
    for p in list(paths)[:HOLDER_MAX]:
        names = []
        for pid, app_name, svc in _rm_holders(p):
            nm = "이 프로그램" if pid == me else (app_name or svc or f"프로그램(pid {pid})")
            if nm not in names:
                names.append(nm)
        if names:
            out[p] = " · ".join(names[:4])
    return out


def _inside(path, base):
    try:
        a = os.path.normcase(os.path.abspath(_plain(path))).rstrip("\\/")
        b = os.path.normcase(os.path.abspath(_plain(base))).rstrip("\\/")
    except (TypeError, ValueError):
        return False
    return bool(b) and a.startswith(b + os.sep)


def _temp_dir(temp_dir=None):
    return os.path.abspath(temp_dir or tempfile.gettempdir())


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _today():
    return date.today().isoformat()


# ── 분류 ────────────────────────────────────────────────────────────────────────────────
def _edge_kept(name):
    """data\\ 바로 아래 이름이 전용 Edge 프로필이나 그 상태 파일인가(keep)."""
    return name == EDGE or name in {EDGE + s for s in EDGE_SIDE}


def classify(rel):
    r"""설치 폴더 기준 상대 경로 → 분류(CLASSES) 또는 None(data\·report\ 밖 — 지우지 않음 · ui_error.log 는 other)."""
    r = str(rel).replace("\\", "/").strip("/").lower()
    if r in ROOT_FILES:
        return "other"
    parts = r.split("/")
    if not parts or parts[0] not in ("data", "report") or len(parts) < 2:
        return None
    if r in KEEP_FILES:
        return "keep"
    if parts[0] == "data":
        if _edge_kept(parts[1]):
            return "keep"
        if parts[1].startswith(EDGE_BAD):
            return "raw"
        if parts[1] == "outlook" or r in RAW_FILES:
            return "raw"
        if parts[1] == "cache":
            return "intermediate"
        return "other"
    name = parts[-1]
    if parts[1] == "share":
        return "share"
    if len(parts) == 2:
        if any(fnmatch.fnmatchcase(name, p.lower()) for p in INTERMEDIATE_PATTERNS):
            return "intermediate"
        if any(fnmatch.fnmatchcase(name, p.lower()) for p in RESULT_PATTERNS + HASH_PATTERNS):
            return "result"
        if name.endswith(".html"):
            return "html"
    return "other"


def _raw_group(rel):
    r"""raw 파일의 통째 묶음 — 'outlook'(data\outlook\** · coverage_ledger.json) 또는 옛 Edge 프로필 사본 하나('data/af32_edge.bad-…')."""
    parts = str(rel).replace("\\", "/").strip("/").lower().split("/")
    if len(parts) > 1 and parts[1].startswith(EDGE_BAD):
        return "data/" + parts[1]
    return "outlook"


def _days(cfg):
    return {c: int(afcfg.get(cfg, "retention." + k)) for c, k in DAYS_KEY.items()}


def _now_ts(now):
    if now is None:
        return time.time()
    if isinstance(now, datetime):
        return now.timestamp()
    if isinstance(now, date):
        return datetime(now.year, now.month, now.day).timestamp()
    return float(now)


def _cuts(days, ts):
    r"""분류별 자르는 시각 — 그 날(ts 의 날짜) 0시에서 (기한−1)일 전. 수정 날짜 + 기한 ≤ 오늘인 파일이 걸린다(expiry_date 와 같다)."""
    today = datetime.fromtimestamp(ts).date()
    base = datetime(today.year, today.month, today.day)
    return {c: (base - timedelta(days=int(d) - 1)).timestamp() for c, d in days.items()}


def _scan(root, *, include_edge=False):
    """data\\·report\\ 를 걷는다 → (파일 [(상대 경로, 확장 경로, 분류, mtime)], 들어가지 않은 연결 [상대], 못 읽은 폴더 [(상대, 까닭)]).
    keep 폴더(전용 Edge 프로필)는 include_edge 가 아니면 들어가지 않는다. 설치 폴더 바로 아래의 ROOT_FILES 도 싣는다."""
    files, links, stuck = [], [], []
    root = os.path.abspath(root)

    def onerr(e):
        if isinstance(e, (FileNotFoundError, NotADirectoryError)):
            return
        stuck.append((_rel(getattr(e, "filename", "") or "", root),
                      "폴더를 읽지 못함(" + ("권한 없음" if isinstance(e, PermissionError) else type(e).__name__) + ")"))

    for top in ("data", "report"):
        base = os.path.join(root, top)
        if _link_dir(base) and os.path.lexists(base):
            links.append(top)
            continue
        xb = _xlong(base)
        if not os.path.isdir(xb):
            continue
        for cur, dirs, fns in os.walk(xb, onerror=onerr):
            keep = []
            for dn in dirs:
                full = os.path.join(cur, dn)
                rel = _rel(full, root)
                if _link_dir(full):
                    links.append(rel)
                    continue
                if not include_edge and classify(rel + "/x") == "keep":
                    continue                     # 전용 Edge 프로필 — 통째로 남긴다(들어가지 않는다)
                keep.append(dn)
            dirs[:] = keep
            for fn in fns:
                full = os.path.join(cur, fn)
                rel = _rel(full, root)
                cls = classify(rel)
                if cls is None:
                    continue
                try:
                    mt = os.lstat(full).st_mtime
                except OSError:
                    continue
                files.append((rel, full, cls, mt))
    for name in ROOT_FILES:
        p = os.path.join(root, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and not (getattr(st, "st_file_attributes", 0) or 0) & _REPARSE_POINT:
            files.append((name, _xlong(p), "other", st.st_mtime))
    return files, links, stuck


def _temp_files(prefixes, temp_dir=None, *, dirs=False):
    """%TEMP% 바로 아래의 접두가 맞는 항목 → [(이름, 경로, mtime, 폴더인가)]. 링크는 뺀다."""
    td = _temp_dir(temp_dir)
    out = []
    try:
        names = os.listdir(td)
    except OSError:
        return out
    low = tuple(p.lower() for p in prefixes)
    for n in names:
        if not n.lower().startswith(low):
            continue
        p = os.path.join(td, n)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        isdir = stat.S_ISDIR(st.st_mode)
        if stat.S_ISLNK(st.st_mode) or (isdir and _link_dir(p)):
            continue
        if isdir and not dirs:
            continue
        out.append((n, p, st.st_mtime, isdir))
    return out


def _legacy_temp_items(temp_dir=None):
    r"""%TEMP% 바로 아래의 옛 LoadMonitor 임시 항목(이름이 정확히 맞는 것만) → [(이름, 경로, mtime, 폴더인가)].
    파일: LEGACY_TEMP_NAMES(정확한 이름) · LEGACY_TEMP_PATTERNS(무늬). 폴더: LEGACY_TEMP_DIRS(정확한 이름)만. 링크는 뺀다."""
    td = _temp_dir(temp_dir)
    try:
        names = os.listdir(td)
    except OSError:
        return []
    files = {x.lower() for x in LEGACY_TEMP_NAMES}
    folders = {x.lower() for x in LEGACY_TEMP_DIRS}
    pats = tuple(x.lower() for x in LEGACY_TEMP_PATTERNS)
    out = []
    for n in names:
        low = n.lower()
        p = os.path.join(td, n)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if stat.S_ISLNK(st.st_mode) or (getattr(st, "st_file_attributes", 0) or 0) & _REPARSE_POINT:
            continue
        if stat.S_ISDIR(st.st_mode):
            if low in folders:
                out.append((n, p, st.st_mtime, True))
        elif stat.S_ISREG(st.st_mode) and (low in files or any(fnmatch.fnmatchcase(low, x) for x in pats)):
            out.append((n, p, st.st_mtime, False))
    return out


def _allowed(plain, root, extra):
    """지워도 되는 자리인가 — 설치 폴더 안이거나, 부르는 쪽이 이름으로 짚은 %TEMP% 항목(extra — 파일 또는 그 폴더 안)."""
    if _inside(plain, root):
        return True
    a = os.path.normcase(os.path.abspath(plain)).rstrip("\\/")
    for x in extra:
        b = os.path.normcase(os.path.abspath(_plain(x))).rstrip("\\/")
        if a == b or a.startswith(b + os.sep):
            return True
    return False


def _delete(items, root, *, dry_run=False, extra=()):
    """[(상대 경로, 경로, 분류)] 지우기 → (지운 [(상대, 분류)], errors). 설치 폴더 밖은 extra(%TEMP% 의 짚은 항목)만."""
    done, left, errors = [], [], []
    for rel, path, cls in items:
        plain = _plain(path)
        if not _allowed(plain, root, extra):
            errors.append({"path": rel, "why": "설치 폴더 밖이라 지우지 않음", "holder": ""})
            continue
        if dry_run:
            done.append((rel, cls))
            continue
        if _rm_file(path):
            done.append((rel, cls))
        else:
            left.append((rel, path, cls))
    if left:
        time.sleep(RETRY_SEC)
        again = []
        for rel, path, cls in left:
            if _rm_file(path, tries=1):
                done.append((rel, cls))
            else:
                again.append((rel, path, cls))
        names = file_holders([_plain(p) for _r, p, _c in again]) if again else {}
        for rel, path, _cls in again:
            h = names.get(_plain(path), "")
            errors.append({"path": rel, "why": "다른 프로그램이 쓰고 있어 지우지 못함" if h else "지우지 못함",
                           "holder": h})
    return done, errors


def _rm_tree(path, root, *, dry_run=False, extra=()):
    """폴더 하나를 안전하게 지운다(링크 폴더에는 들어가지 않는다) → (지운 상대 경로 목록, errors)."""
    items, errors, dirs_seen = [], [], []
    xp = _xlong(path)
    if not os.path.isdir(xp) or _link_dir(xp):
        return [], ([{"path": _rel(path, root), "why": "연결 폴더라 들어가지 않음", "holder": ""}]
                    if os.path.lexists(xp) and _link_dir(xp) else [])
    for cur, dirs, fns in os.walk(xp, onerror=lambda e: None):
        dirs[:] = [d for d in dirs if not _link_dir(os.path.join(cur, d))]
        dirs_seen.append(cur)
        for fn in fns:
            full = os.path.join(cur, fn)
            items.append((_rel(full, root), full, "legacy"))
    done, errs = _delete(items, root, dry_run=dry_run, extra=extra)
    errors += errs
    if not dry_run and _allowed(_plain(xp), root, extra):
        for d in sorted(dirs_seen, key=len, reverse=True):
            try:
                os.rmdir(d)
            except OSError:
                pass
    return [r for r, _c in done], errors


def _prune(dirs, stop):
    """지운 파일이 있던 폴더를 아래에서부터 비었으면 지운다(stop 폴더는 남긴다)."""
    stop_n = {os.path.normcase(_plain(s)).rstrip("\\/") for s in stop}
    for d in sorted(set(dirs), key=len, reverse=True):
        cur = d
        while True:
            key = os.path.normcase(_plain(cur)).rstrip("\\/")
            if key in stop_n or not key:
                break
            try:
                os.rmdir(cur)
            except OSError:
                break
            cur = os.path.dirname(cur)


def _result(done, errors, links=(), by_class=None):
    out = {"deleted": len(done), "paths": [r for r, _c in done], "errors": errors}
    if by_class is not None:
        out["by_class"] = by_class
        out["links"] = list(links)
    return out


def _tags_alive(files, cut):
    """결과(agentic_·workflow_)·html 중 지우지 않을 파일이 가진 tag 집합(run_meta 를 남길 근거). 이름 해시 파일
    (name_hashes_<tag>.json)은 세지 않는다 — 결과가 다 지워진 tag 의 run_meta 를 그 파일이 붙잡지 않게."""
    alive = set()
    for rel, _p, cls, mt in files:
        if cls in ("result", "html") and mt >= cut.get(cls, 0):
            name = os.path.basename(rel)
            if any(fnmatch.fnmatchcase(name.lower(), p) for p in HASH_PATTERNS):
                continue
            m = re.search(r"(\d{8}-\d{8})", name)
            if m:
                alive.add(m.group(1))
    return alive


def _not_mine(root):
    r"""이 폴더의 자료가 지금 Windows 사용자의 것이 아닌가(다른 사용자의 설치 · 설치 정보 없이 남은 자료 — install.is_mine 이
    False) — 읽기만 한다. 정리는 시작 확인보다 먼저 돈다: 내 자료가 아닌 폴더에서는 기한이 지난 것을 지우기만 하고, 파일을 새로
    쓰거나 고쳐 쓰지 않는다(이름 해시 고쳐 쓰기 · 정리 기록). 알 수 없으면 False(내 자료일 때와 같이 한다)."""
    try:
        import install
        return install.is_mine(root) is False
    except Exception:  # noqa: BLE001 - 모르면 정리는 평소대로 한다
        return False


def _prune_name_hashes(root, cfg, dry_run, ts=None):
    r"""이름 조각 해시의 항목별 기한(privacy.prune_name_hashes) — data\cache\name_hashes.json 은 마지막으로 본 날 +
    intermediateDays, report\name_hashes_<tag>.json 은 + resultDays(그 tag 의 분석 자료가 없으면 파일째). 파일 나이로는 자르지
    못한다(새 이름이 보일 때마다 파일이 새로 쓰인다). ts = 정리 기준 시각(purge 의 now). → 그 결과 dict | None(dry_run).
    내 자료가 아닌 폴더(_not_mine)에서는 하지 않는다 — 그 손질은 파일을 고쳐 쓴다. 그런 폴더는 더 쓰이지 않으므로 그 파일들은
    파일 나이(중간 자료·결과의 기한)로 지워진다."""
    if dry_run or _not_mine(root):
        return None
    try:
        import privacy
        fn = getattr(privacy, "prune_name_hashes", None)
        if fn is None:
            return None
        today = datetime.fromtimestamp(ts).date() if ts is not None else None
        return fn(root, cfg, today=today)
    except Exception as e:  # noqa: BLE001 - 정리는 실행을 막지 않는다(다음 정리 때 다시)
        return {"error": type(e).__name__}


def purge(root=None, cfg=None, *, now=None, dry_run=False, temp_dir=None):
    """보관기한이 지난 파일을 지운다(분류·기한은 모듈 설명). → {"deleted", "by_class", "errors", "paths", "links",
    "edge_site", "name_hashes"}. dry_run=True 면 지우지 않고 지울 목록만. 실패는 errors 에 남기고 예외를 던지지 않는다.
    전용 Edge 가 꺼져 있으면 그 프로필의 Outlook·M365 사이트 자료도 지운다(edge_site — 쿠키·로그인 정보는 남긴다)."""
    root = os.path.abspath(str(root or ROOT))
    if cfg is None:
        cfg, _w = afcfg.load_effective(root)
    days = _days(cfg)
    ts = _now_ts(now)
    cut = _cuts(days, ts)
    try:
        files, links, stuck = _scan(root)
    except Exception as e:  # noqa: BLE001 - 정리는 실행을 막지 않는다
        return {"deleted": 0, "by_class": {}, "errors": [{"path": "", "why": f"자료 폴더를 읽지 못함({type(e).__name__})",
                                                          "holder": ""}], "paths": [], "links": [], "edge_site": {},
                "name_hashes": None}
    todo = []
    groups = {}
    for f in files:
        if f[2] == "raw":
            groups.setdefault(_raw_group(f[0]), []).append(f)
    for grp in groups.values():
        if max(f[3] for f in grp) < cut["raw"]:
            todo += [(r, p, c) for r, p, c, _m in grp]       # 수집 자료는 통째로(원장 초기화 포함) · 옛 Edge 사본은 사본마다
    alive = _tags_alive(files, cut)
    for rel, path, cls, mt in files:
        if _norm_rel(rel) in OLD_FORM_FILES:
            todo.append((rel, path, cls))                    # 이제 쓰지 않는 파일(예전 꼴의 기록) — 나이와 상관없이 지운다
            continue
        if cls in ("keep", "raw") or mt >= cut[cls]:
            continue
        if cls == "intermediate" and os.path.basename(rel).lower().startswith("run_meta_"):
            m = re.search(r"(\d{8}-\d{8})", os.path.basename(rel))
            if m and m.group(1) in alive:
                continue
        todo.append((rel, path, cls))
    tmp_items = [(os.path.join("%TEMP%", n), p, "other") for n, p, mt, _d in _temp_files((lmname.TMP_PREFIX,), temp_dir)
                 if mt < cut["other"]]
    done, errors = _delete(todo + tmp_items, root, dry_run=dry_run, extra=[p for _r, p, _c in tmp_items])
    errors = [{"path": r, "why": w, "holder": ""} for r, w in stuck] + errors
    if not dry_run and done:
        _prune([os.path.dirname(os.path.join(root, r)) for r, _c in done if not r.startswith("%TEMP%")],
               [root, os.path.join(root, "data"), os.path.join(root, "report")])
    by_class = {}
    for _r, c in done:
        by_class[c] = by_class.get(c, 0) + 1
    out = _result(done, errors, links, by_class)
    try:
        out["edge_site"] = clear_edge_site_files(root, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 - 사이트 자료 지우기 실패가 정리를 막지 않는다
        out["edge_site"] = {"deleted": 0, "skipped": type(e).__name__, "errors": []}
    out["name_hashes"] = _prune_name_hashes(root, cfg, dry_run, ts)
    return out


def purge_classes(root=None, classes=("raw", "intermediate", "result", "html", "share"), *, dry_run=False):
    """나이와 상관없이 그 분류의 파일을 모두 지운다(D9 — 제한 고객 목록이 바뀌면 분석 전에). keep 은 지우지 않는다."""
    root = os.path.abspath(str(root or ROOT))
    want = {c for c in classes if c in CLASSES and c != "keep"}
    files, links, stuck = _scan(root)
    todo = [(r, p, c) for r, p, c, _m in files if c in want]
    done, errors = _delete(todo, root, dry_run=dry_run)
    errors = [{"path": r, "why": w, "holder": ""} for r, w in stuck] + errors
    if not dry_run and done:
        _prune([os.path.dirname(os.path.join(root, r)) for r, _c in done],
               [root, os.path.join(root, "data"), os.path.join(root, "report")])
    by_class = {}
    for _r, c in done:
        by_class[c] = by_class.get(c, 0) + 1
    return _result(done, errors, links, by_class)


def purge_legacy(root=None, *, temp_dir=None, dry_run=False):
    r"""옛 LoadMonitor 자료를 한 번에 지운다(D20) — 시작할 때마다 가장 먼저(없으면 몇 ms). → {"deleted", "paths", "errors"}.
    data\{pc,m365,files,manual,import,추가PC,근태,programs,activity,<LM24 Edge 프로필>}\ · data\lm*_edge(.*) · data\teams* ·
    data\{git_source.json,files_excluded.json} · report\{mm_rows_*,mm_meta_*,attendance_*,day_hours_*,admin_days_*,
    ai_narratives_*,보고서_*,분석리포트_*,리포트_*,team_report_status.json,member*.json} · report\{얼린보고서,upload_pending,
    upload_sent}\ · config\{team_server.json,detail_aliases.json,project_aliases.json,excluded_work.json} ·
    %TEMP% 의 옛 판 임시 항목 — LEGACY_TEMP_NAMES·LEGACY_TEMP_PATTERNS(파일)·LEGACY_TEMP_DIRS(정확한 이름의 폴더)만. 같은 머리
    (lm_ 등)를 쓰는 다른 프로그램의 항목과 모르는 폴더는 건드리지 않는다. 최근 LEGACY_TEMP_GRACE_SEC 초 안에 바뀐 것은 다른 판이
    쓰는 중으로 보고 남긴다."""
    root = os.path.abspath(str(root or ROOT))
    done, errors = [], []
    data, rep, conf = (os.path.join(root, x) for x in ("data", "report", "config"))

    def tree(p, extra=()):
        d, e = _rm_tree(p, root, dry_run=dry_run, extra=extra)
        done.extend((r, "legacy") for r in d)
        errors.extend(e)
        if not d and not e and not dry_run and os.path.isdir(p) and not _link_dir(p):
            try:
                os.rmdir(p)                       # 빈 폴더
            except OSError:
                pass

    def files(items, extra=()):
        d, e = _delete(items, root, dry_run=dry_run, extra=extra)
        done.extend(d)
        errors.extend(e)

    def listing(d):
        try:
            return os.listdir(d)
        except OSError:
            return []

    singles = []
    for n in listing(data):
        p = os.path.join(data, n)
        low = n.lower()
        if os.path.isdir(p) and not os.path.islink(p):
            if (n in LEGACY_DATA_DIRS or low in LEGACY_DATA_DIRS
                    or any(fnmatch.fnmatchcase(low, pat) for pat in LEGACY_DATA_PATTERNS)):
                if low == EDGE or low.startswith(EDGE + "."):
                    continue
                tree(p)
        elif os.path.isfile(p):
            if low in LEGACY_DATA_FILES or any(fnmatch.fnmatchcase(low, pat) for pat in LEGACY_DATA_PATTERNS):
                if low.startswith(EDGE + "."):
                    continue
                singles.append((_rel(p, root), p, "legacy"))
    for n in listing(rep):
        p = os.path.join(rep, n)
        if os.path.isdir(p) and not os.path.islink(p):
            if n in LEGACY_REPORT_DIRS:
                tree(p)
        elif os.path.isfile(p) and any(fnmatch.fnmatchcase(n.lower(), pat.lower()) for pat in LEGACY_REPORT_PATTERNS):
            singles.append((_rel(p, root), p, "legacy"))
    for n in LEGACY_CONFIG_FILES:
        p = os.path.join(conf, n)
        if os.path.isfile(p):
            singles.append((_rel(p, root), p, "legacy"))
    files(singles)
    now = time.time()
    tmp_singles = []
    for n, p, mt, isdir in _legacy_temp_items(temp_dir):
        if now - mt < LEGACY_TEMP_GRACE_SEC:
            continue
        if isdir:
            tree(p, extra=(p,))
        else:
            tmp_singles.append((os.path.join("%TEMP%", n), p, "legacy"))
    files(tmp_singles, extra=[p for _r, p, _c in tmp_singles])
    return {"deleted": len(done), "paths": [r for r, _c in done], "errors": errors}


def _norm_rel(x):
    return str(x).replace("\\", "/").strip("/").lower()


def purge_all(root=None, *, keep_consent=False, keep_edge=False, temp_dir=None, keep=(), last=LAST_FILES):
    r"""내 자료 모두 지우기 — data\·report\ 아래 전부 + ui_error.log + %TEMP%\af32_* 파일. → {"deleted", "paths", "errors"}.
    keep_consent=True: install.json·share_receipts.json·withdrawal.json(설치 정보·공유 영수증·지우기 기록)을 남긴다 — 자료만 지울 때.
    keep_edge=True: 전용 Edge 프로필(data\af32_edge\ · 그 옆 상태 파일)을 남긴다 — 옛 사본(af32_edge.bad-*)은 지운다.
    keep: 더 남길 상대 경로(예 [모두 지우기]가 먼저 쓴 data\withdrawal.json·data\share_receipts.json).
    last: 맨 끝에 지운다(기본 설치 정보) — 중간에 끊겨도 남은 자료의 주인을 안다.
    config\ 와 teamdata\ 는 건드리지 않는다. 이 프로세스가 쥔 분석 잠금(data\run.lock)은 남긴다(실행이 끝날 때 스스로 놓는다).
    [모두 지우기](consent.withdraw)는 큰 자료를 keep_consent=True · keep_edge=False 로 먼저 지우고(먼저
    copilot_auto.close_own_edge 로 Edge 를 닫는다) 설치 정보를 맨 끝에 지운다. 예전 판이 남기던 data\consent.json 은 어느
    경우에도 남기지 않는다."""
    root = os.path.abspath(str(root or ROOT))
    files, links, stuck = _scan(root, include_edge=not keep_edge)
    keep_set = {_norm_rel(k) for k in keep or ()}
    try:
        mine = run_lock_pid(root) == os.getpid()
    except Exception:  # noqa: BLE001 - 잠금을 읽지 못해도 지우기는 한다
        mine = False
    if mine:
        keep_set.add(_norm_rel("data/" + RUN_LOCK))      # 이 프로세스(run.py)가 쥔 분석 잠금 — 실행이 끝날 때 스스로 놓는다
    last_l = [_norm_rel(x) for x in last or ()]
    todo, tail = [], {}
    for rel, path, cls, _mt in files:
        r = _norm_rel(rel)
        if keep_consent and r in CONSENT_FILES:
            continue
        if keep_edge and cls == "keep" and r not in CONSENT_FILES:
            continue
        if r in keep_set:
            continue
        if r in last_l:
            tail[r] = (rel, path, cls)
            continue
        todo.append((rel, path, cls))
    tmp_items = [(os.path.join("%TEMP%", n), p, "other") for n, p, _mt, _d in _temp_files((lmname.TMP_PREFIX,), temp_dir)]
    done, errors = _delete(todo + tmp_items, root, extra=[p for _r, p, _c in tmp_items])
    for r in last_l:                       # 하나씩(다시 시도까지) 끝낸 뒤 다음 것
        if r in tail:
            d, e = _delete([tail[r]], root)
            done += d
            errors += e
    errors = [{"path": r, "why": w, "holder": ""} for r, w in stuck] + errors
    errors += [{"path": x, "why": "연결 폴더라 들어가지 않음", "holder": ""} for x in links]
    # 빈 폴더 정리 — data\·report\ 자신은 남긴다. 연결 폴더에는 들어가지 않는다(그 너머의 빈 폴더를 지우지 않게)
    for top in ("data", "report"):
        base = _xlong(os.path.join(root, top))
        if not os.path.isdir(base) or _link_dir(base):
            continue
        seen = []
        for cur, dirs, _fns in os.walk(base, onerror=lambda e: None):
            dirs[:] = [d for d in dirs if not _link_dir(os.path.join(cur, d))
                       and not (keep_edge and classify(_rel(os.path.join(cur, d), root) + "/x") == "keep")]
            if os.path.normcase(cur) != os.path.normcase(base):
                seen.append(cur)
        for cur in sorted(seen, key=len, reverse=True):
            try:
                os.rmdir(cur)
            except OSError:
                pass
    return {"deleted": len(done), "paths": [r for r, _c in done], "errors": errors}


# ── 수집 원자료(C2) ─────────────────────────────────────────────────────────────────────────
def raw_left(root=None):
    r"""data\outlook\raw 바로 아래의 보통 파일 경로(정렬). data·outlook·raw 중 하나라도 연결(정션·링크)이면 [] — 따라가지 않는다."""
    r = os.path.abspath(str(root or ROOT))
    chain = [os.path.join(r, "data"), os.path.join(r, "data", "outlook"), os.path.join(r, "data", "outlook", "raw")]
    if not os.path.isdir(chain[-1]) or any(_link_dir(p) for p in chain):
        return []
    out = []
    try:
        ents = list(os.scandir(chain[-1]))
    except OSError:
        return out
    for e in ents:
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode) and not (getattr(st, "st_file_attributes", 0) or 0) & _REPARSE_POINT:
            out.append(e.path)
    return sorted(out)


def drop_raw(root=None):
    r"""Outlook 앱 수집기의 원자료(data\outlook\raw\* — 사외 사람 이름·주소가 든다)를 정제 없이 지운다 → 지운 파일 수.
    바로 아래의 보통 파일만 · 연결은 따라가지 않는다 · 읽지 않는다(지우기만). 도는 수집이 쓰는 중일 수 있으므로 부르는 쪽이
    run_active 를 먼저 본다(멈춘 직후는 바로).
    부르는 곳: run.py(시작 거부·정제 뒤·실행 중 시작 확인에 걸렸을 때·콘솔 닫기) · 화면([중지]·창 닫기·시작 — run_active 가 거짓일 때) ·
    강제 종료(이 폴더의 작업이 하나도 남지 않았을 때) · retention.py --purge(매일 정리 — run_active 가 거짓일 때)."""
    return sum(1 for p in raw_left(root) if _rm_file(p))


# ── 분석 잠금(C5) ───────────────────────────────────────────────────────────────────────────
def run_lock_path(root=None):
    return os.path.join(os.path.abspath(str(root or ROOT)), "data", RUN_LOCK)


_PY_NAMES = ("python.exe", "pythonw.exe", "py.exe")


def _runs_run_py(cmd, root):
    r"""명령줄이 이 폴더의 run.py 를 돌리나 — '<root>\run.py' 또는 상대 경로 'run.py'(bat 이 cd 한 뒤 띄운 꼴)."""
    c = str(cmd or "").replace("/", "\\")
    key = os.path.normcase(os.path.join(os.path.abspath(str(root)), "run.py"))
    for tok in re.findall(r'"([^"]*)"|(\S+)', c):
        t = (tok[0] or tok[1]).strip()
        if os.path.basename(t).lower() != "run.py":
            continue
        if t.lower() == "run.py" or os.path.normcase(os.path.abspath(os.path.join(str(root), t))) == key \
                or os.path.normcase(t) == key:
            return True
    return False


def run_lock_pid(root=None):
    r"""data\run.lock 을 쥔 실행 → pid(그 pid 가 살아 있고 이 폴더의 run.py 를 돌리는 파이썬일 때) | None(없음·끝남·다른 프로그램).
    명령줄을 읽지 못하는 살아 있는 파이썬(다른 세션의 것 포함)이면 도는 것으로 본다(모르면 지우지 않는 쪽). 그 pid 가 파이썬이
    아닌 프로그램의 것이면(끝난 실행의 pid 를 다른 프로그램이 다시 받았다) 끝난 것으로 본다. 읽기만 한다."""
    d = _read_json(run_lock_path(root))
    try:
        pid = int((d or {}).get("pid") or 0) if isinstance(d, dict) else 0
    except (TypeError, ValueError):
        pid = 0
    if pid <= 0:
        return None
    if pid == os.getpid():
        return pid
    import proc
    alive, exe, cmd = proc.process_info(pid)
    if alive is False:
        return None
    name = os.path.basename(str(exe or "")).lower() if alive else ""
    if not name:                      # 열 수 없거나 실행 파일을 모르는 프로세스 — 프로세스 목록의 이름으로만 본다
        if not any(p == pid for p, _c in proc.process_list(_PY_NAMES)):
            return None
    elif name not in _PY_NAMES:
        return None
    if not cmd:
        return pid                    # 살아 있는 파이썬인데 명령줄을 읽지 못한다 — 도는 것으로 본다
    return pid if _runs_run_py(cmd, root or ROOT) else None


def run_active(root=None):
    """이 설치 폴더의 분석·수집이 도는가(C5) — data\\run.lock 의 pid 가 살아 있는 이 폴더의 run.py 이거나 consent._busy(root).
    화면의 지우기([모두 지우기] 포함), retention.py --purge-all 은 참이면 'busy' 로 거절한다."""
    r = os.path.abspath(str(root or ROOT))
    try:
        if run_lock_pid(r):
            return True
    except Exception:  # noqa: BLE001 - 잠금을 확인하지 못하면 프로세스 목록으로만 본다
        pass
    try:
        import consent
        return bool(consent._busy(r))
    except Exception:  # noqa: BLE001 - 모르면 막지 않는다(consent._busy 와 같은 규칙)
        return False


# ── 제한 고객 목록이 바뀐 결과(C7) ─────────────────────────────────────────────────────────────
def restricted_stale(root, tag, restricted):
    r"""report\run_meta_<tag>.json 의 결과가 지금 제한 고객 목록으로 만든 것이 아닌가 — 그 파일이 없거나(AgentFinder32 표식 없음 포함)
    restricted_sha256 이 없거나 restricted.sha256 과 다르면 참(teamup 미리보기·공유와 화면이 거절·재분석한다)."""
    m = _read_json(os.path.join(os.path.abspath(str(root or ROOT)), "report", f"run_meta_{tag}.json"))
    if not isinstance(m, dict) or m.get("product") != lmname.PRODUCT:
        return True
    prev = str(m.get("restricted_sha256") or "").strip().lower()
    cur = str(getattr(restricted, "sha256", "") or "").strip().lower()
    return not prev or not cur or prev != cur


# ── 전용 Edge 의 사이트 자료(디스크) ─────────────────────────────────────────────────────────
def _edge_profile(root):
    return os.path.join(os.path.abspath(str(root or ROOT)), "data", lmname.EDGE_PROFILE_NAME)


def edge_running(root=None):
    r"""이 폴더의 전용 Edge(data\af32_edge)가 떠 있나 — 프로필의 lockfile 을 Edge 가 쥐고 있거나, 명령줄의 --user-data-dir 가 이
    프로필인 msedge.exe 가 있으면 참. 읽기만 한다(프로세스 명령줄·파일 열기)."""
    prof = _edge_profile(root)
    lock = os.path.join(prof, "lockfile")
    if os.path.lexists(lock):
        try:
            fd = os.open(lock, os.O_RDONLY)
            os.close(fd)
        except OSError:
            return True                       # Edge 가 잡고 있다(또는 모른다 — 건드리지 않는 쪽)
    import proc
    key = os.path.normcase(prof).rstrip("\\/")
    for _pid, cmd in proc.process_list(("msedge.exe",)):
        c = os.path.normcase(str(cmd or "").replace("/", "\\"))
        i = c.find("--user-data-dir=")
        if i >= 0 and c[i + len("--user-data-dir="):].lstrip('"').startswith(key):
            return True
    return False


def _edge_site_targets(root):
    r"""지울 사이트 자료 폴더 — <프로필>\Default\{Service Worker, Cache, Code Cache} · Default\IndexedDB\https_<Outlook·M365 원점>*."""
    base = os.path.join(_edge_profile(root), "Default")
    if not os.path.isdir(base) or _link_dir(_edge_profile(root)) or _link_dir(base):
        return []
    out = [os.path.join(base, d) for d in EDGE_SITE_DIRS if os.path.isdir(os.path.join(base, d))]
    idb = os.path.join(base, "IndexedDB")
    try:
        names = os.listdir(idb) if os.path.isdir(idb) and not _link_dir(idb) else []
    except OSError:
        names = []
    for n in names:
        low = n.lower()
        if low.startswith("https_") and any(o in low for o in EDGE_SITE_ORIGINS):
            out.append(os.path.join(idb, n))
    return out


def clear_edge_site_files(root=None, *, dry_run=False):
    r"""전용 Edge 가 꺼져 있을 때 그 프로필의 Outlook·M365 사이트 자료(서비스 워커·캐시·IndexedDB)를 디스크에서 지운다 — 쿠키·로그인
    정보(Network\Cookies·Login Data)는 남긴다. Edge 가 떠 있으면 건너뛴다(copilot_auto.clear_site_data 가 단계마다 지운다).
    → {"deleted": n, "skipped": ""|"edge_running", "errors": [...]}"""
    root = os.path.abspath(str(root or ROOT))
    targets = _edge_site_targets(root)
    if not targets:
        return {"deleted": 0, "skipped": "", "errors": []}
    if edge_running(root):
        return {"deleted": 0, "skipped": "edge_running", "errors": []}
    n, errors = 0, []
    for t in targets:
        if _link_dir(t):
            continue
        d, e = _rm_tree(t, root, dry_run=dry_run)
        n += len(d)
        errors += e
    return {"deleted": n, "skipped": "", "errors": errors}


# ── 보관기한 표 ─────────────────────────────────────────────────────────────────────────────
def expiry_date(cfg, cls, *, when=None):
    """그 날(when — date·datetime·epoch, 없으면 오늘) 만든 cls 파일이 지워지는 날 'YYYY-MM-DD' — 그 날의 첫 정리 때 지운다.
    cls 는 raw·intermediate·result·html·share·other 또는 serverPersonal·serverTeam."""
    key = DAYS_KEY.get(cls) or {"serverPersonal": "serverPersonalDays", "serverTeam": "serverTeamDays"}.get(cls)
    if not key:
        raise ValueError(f"모르는 분류: {cls}")
    base = datetime.fromtimestamp(_now_ts(when)).date()
    return (base + timedelta(days=int(afcfg.get(cfg, "retention." + key)))).isoformat()


def expiry_table(root=None, cfg=None, *, now=None):
    """보관기한 표(화면 [내 데이터] 탭) — PC 분류별 줄 + 서버 줄.
    [{"class","label","where","days","files","oldest","next_delete","server"}] — 날짜는 'YYYY-MM-DD' 또는 None.
    next_delete = 그 분류에서 다음에 지워질 날(raw 는 묶음마다 가장 새 파일 + 기한 중 이른 날, 그 밖은 가장 오래된 파일 + 기한)."""
    root = os.path.abspath(str(root or ROOT))
    if cfg is None:
        cfg, _w = afcfg.load_effective(root)
    days = _days(cfg)
    try:
        files, _links, _stuck = _scan(root)
    except Exception:  # noqa: BLE001 - 표는 덤 — 읽지 못해도 기한은 보인다
        files = []

    def d(ts):
        return datetime.fromtimestamp(ts).date().isoformat() if ts else None

    def plus(ts, n):
        return (datetime.fromtimestamp(ts).date() + timedelta(days=n)).isoformat()
    rows = []
    for cls in ("raw", "intermediate", "result", "html", "share", "other"):
        mts = [f[3] for f in files if f[2] == cls]
        label, where = LABELS[cls]
        nxt = None
        if mts and cls == "raw":
            groups = {}
            for f in files:
                if f[2] == "raw":
                    g = _raw_group(f[0])
                    groups[g] = max(groups.get(g, 0.0), f[3])
            nxt = min(plus(t, days[cls]) for t in groups.values())
        elif mts:
            nxt = plus(min(mts), days[cls])
        rows.append({"class": cls, "label": label, "where": where, "days": days[cls], "files": len(mts),
                     "oldest": d(min(mts)) if mts else None, "next_delete": nxt, "server": False})
    for cls, key, label in SERVER_ROWS:
        rows.append({"class": cls, "label": label, "where": "조직장 PC 의 팀 서버", "days": int(afcfg.get(cfg, "retention." + key)),
                     "files": None, "oldest": None, "next_delete": None, "server": True})
    return rows


def kept_table(root=None):
    r"""보관기한 없이 [모두 지우기]를 할 때까지 남는 것 — 화면이 보관기한 표 아래에 보인다.
    [{"class","label","where","files","until"}] — 전용 Edge 로그인 프로필(data\af32_edge) · 공유 영수증(data\share_receipts.json)."""
    root = os.path.abspath(str(root or ROOT))
    prof = _edge_profile(root)
    n = 0
    if os.path.isdir(prof) and not _link_dir(prof):
        for cur, dirs, fns in os.walk(prof, onerror=lambda e: None):
            dirs[:] = [x for x in dirs if not _link_dir(os.path.join(cur, x))]
            n += len(fns)
    rec = _read_json(os.path.join(root, "data", "share_receipts.json"))
    lst = rec.get("receipts") if isinstance(rec, dict) else rec
    return [{"class": "edge", "label": "전용 Edge 로그인 프로필(Copilot·Outlook 웹 로그인)", "where": "data\\" + EDGE,
             "files": n, "until": "[모두 지우기]를 할 때까지"},
            {"class": "receipts", "label": "공유 영수증(조직장 서버 사본을 지울 때 씀)", "where": "data\\share_receipts.json",
             "files": len(lst) if isinstance(lst, list) else 0, "until": "[모두 지우기]로 서버 사본을 지울 때까지"}]


# ── 매일 정리 예약 작업 ─────────────────────────────────────────────────────────────────────
def task_name(root=None):
    """사용자 예약 작업 이름 'AgentFinder32 보관기한 정리 <h6>'(설치 폴더마다 하나)."""
    return f"{lmname.PRODUCT} 보관기한 정리 {lmname.h6(root or ROOT)}"


def task_command(root=None):
    r"""(실행 파일, 인자) — <root>\python\pythonw.exe -I -X utf8 -B "<root>\core\retention.py" --purge --root "<root>"."""
    r = os.path.abspath(str(root or ROOT))
    exe = os.path.join(r, "python", "pythonw.exe")
    args = f'-I -X utf8 -B "{os.path.join(r, "core", "retention.py")}" --purge --root "{r}"'
    return exe, args


def _xml_esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _task_xml(root):
    exe, args = task_command(root)
    user = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    start = date.today().isoformat() + "T" + TASK_TIME + ":00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{_xml_esc(lmname.PRODUCT)} 보관기한이 지난 자료를 지웁니다</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{_xml_esc(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{_xml_esc(exe)}</Command><Arguments>{_xml_esc(args)}</Arguments><WorkingDirectory>{_xml_esc(os.path.abspath(str(root or ROOT)))}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def _schtasks(args, timeout=30):
    try:
        p = subprocess.run(["schtasks.exe"] + list(args), capture_output=True, timeout=timeout,
                           creationflags=NO_WIN if os.name == "nt" else 0)
        return p.returncode
    except (OSError, subprocess.SubprocessError, ValueError):
        return -1


def register_task(root=None):
    """매일 1회 보관기한 정리 사용자 예약 작업을 만든다(있으면 바꾼다) → 성공 여부. 예외를 던지지 않는다."""
    try:
        if os.name != "nt":
            return False
        r = os.path.abspath(str(root or ROOT))
        exe, _a = task_command(r)
        if not os.path.isfile(exe):
            return False
        xml = os.path.join(tempfile.gettempdir(), f"{lmname.TMP_PREFIX}task_{lmname.h6(r)}_{os.getpid()}.xml")
        _drop_task_state(r)                # 작업이 바뀐다 — sync_task 가 그날 확인해 둔 결과를 다시 보게
        try:
            with open(xml, "w", encoding="utf-16") as f:
                f.write(_task_xml(r))
            rc = _schtasks(["/Create", "/TN", task_name(r), "/XML", xml, "/F"])
        finally:
            try:
                os.remove(xml)
            except OSError:
                pass
        return rc == 0
    except Exception:  # noqa: BLE001 - 실패는 False(화면이 대신 알린다)
        return False


def unregister_task(root=None):
    """예약 작업을 지운다 → 지웠거나 원래 없으면 True. 예외를 던지지 않는다."""
    try:
        if os.name != "nt":
            return False
        _drop_task_state(root)             # 작업이 바뀐다 — sync_task 가 그날 확인해 둔 결과를 다시 보게
        if task_registered(root) is False:
            return True
        return _schtasks(["/Delete", "/TN", task_name(root), "/F"]) == 0
    except Exception:  # noqa: BLE001
        return False


def task_registered(root=None):
    """예약 작업이 있나 → True/False, 알 수 없으면 None."""
    try:
        if os.name != "nt":
            return None
        rc = _schtasks(["/Query", "/TN", task_name(root)])
        return None if rc < 0 else rc == 0
    except Exception:  # noqa: BLE001
        return None


def _task_state_path(root):
    return os.path.join(os.path.abspath(str(root or ROOT)), "data", TASK_STATE)


def _drop_task_state(root):
    r"""sync_task 의 확인 기록(data\task_state.json)을 지운다 — 작업을 따로 만들거나 지운 뒤에는 다음 시작이 다시 확인하게."""
    try:
        p = _task_state_path(root)
        if os.path.lexists(p) and not _link_dir(os.path.dirname(p)):
            os.remove(p)
    except OSError:
        pass


def _has_data(root):
    r"""이 설치에 자료가 있는가(install.owned_data — 수집 자료 · 캐시 · 전용 Edge 프로필 · 분석 기록 · 서버에 살아 있는 공유의
    영수증). sync_task 가 묻는다 — 지울 것이 없는 빈 설치에는 매일 정리 작업을 만들지 않는다. 알 수 없으면 True(작업을 둔다)."""
    try:
        import install
        return bool(install.owned_data(root))
    except Exception:  # noqa: BLE001 - 모르면 지울 것이 있다고 본다
        return True


def sync_task(root=None, cfg=None, *, starting_run=False):
    r"""매일 정리 예약 작업을 설정(retention.scheduledPurge)에 맞춘다 → {"task": True | False | None, "message": str}.
    시작할 때마다 부른다 — 화면은 시작할 때, run.py 는 시작 확인(내 자료인가 · 지우는 중이 아닌가)을 지난 뒤에(starting_run=True).
    다른 사용자의 자료·주인을 모르는 자료에는 부르지 않는다(부르는 쪽이 그 확인 뒤에 부른다).
      · 설정이 켜져 있으면 작업이 없을 때 만든다 → task True(있다 · 만들었다) | False 와 TASK_FAIL_MSG(만들지 못했다).
        만드는 것은 지울 것이 있을 때만이다: 분석이 시작할 때(starting_run) 또는 이 설치에 자료가 있을 때(_has_data). 빈 설치에서
        화면만 연 때는 만들지 않는다 → task None, 기록도 남기지 않는다(그날의 첫 분석이 만든다). [모두 지우기]로 작업까지 지운
        사람이 화면만 열어 보고 폴더를 지워도 작업이 남지 않는다.
      · 설정이 꺼져 있으면 작업이 있을 때 지운다 → task False(없다 · 지웠다) | True 와 TASK_REMOVE_FAIL_MSG(지우지 못했다)
      · AF32_NO_TASK 가 있으면(시험) · 윈도가 아니면 아무것도 읽지도 바꾸지도 않는다 → task None
      · 작업이 있는지 알 수 없고 할 일도 정하지 못하면 task None
    task = 이 호출 뒤 작업이 있는가. 설정대로 맞춘 날은 data\task_state.json {product, date, want, name, task}(날짜만)에 적어
    두고, 같은 날 같은 설정이면 그 파일만 읽는다 — 시작마다 작업 스케줄러에 묻지 않는다(하루 한 번 확인). 맞추지 못한 때(만들지·
    지우지 못함 · 알 수 없음)는 적지 않는다 — 다음 시작이 다시 해 본다. 예외를 던지지 않는다."""
    none = {"task": None, "message": ""}
    try:
        if os.environ.get(NO_TASK_ENV) or os.name != "nt":
            return none
        r = os.path.abspath(str(root or ROOT))
        if cfg is None:
            cfg, _w = afcfg.load_effective(r)
        want = bool(afcfg.get(cfg, "retention.scheduledPurge"))
        name = task_name(r)
        sp = _task_state_path(r)
        st = _read_json(sp)
        if (isinstance(st, dict) and st.get("product") == lmname.PRODUCT and st.get("date") == _today()
                and st.get("want") is want and st.get("name") == name and st.get("task") is want):
            return {"task": want, "message": ""}             # 오늘 이미 맞췄다
        have = task_registered(r)
        task, msg = have, ""
        if want and have is not True:
            if starting_run or _has_data(r):
                task = bool(register_task(r))
                msg = "" if task else TASK_FAIL_MSG
            else:
                task = None                                  # 지울 것이 아직 없다(빈 설치) — 분석이 시작할 때 만든다
        elif not want and have is True:
            gone = _schtasks(["/Delete", "/TN", name, "/F"]) == 0
            task, msg = (False, "") if gone else (True, TASK_REMOVE_FAIL_MSG.format(task=name))
        if task is want:                                     # 설정대로 맞췄다 — 오늘은 다시 묻지 않는다
            try:
                if not (os.path.lexists(os.path.join(r, "data")) and _link_dir(os.path.join(r, "data"))):
                    _write_json(sp, {"product": lmname.PRODUCT, "date": _today(), "want": want, "name": name, "task": task})
            except OSError:
                pass
        else:
            _drop_task_state(r)                              # 맞추지 못했다 — 다음 시작이 다시 해 본다
        return {"task": task, "message": msg}
    except Exception:  # noqa: BLE001 - 예약 작업 맞추기가 시작을 막지 않는다(화면을 열 때와 분석 시작·끝에도 지운다)
        return none


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────
def _root_mod(name, root):
    r"""설치 폴더 바로 아래 모듈(teamup 등 — 이미 불렀으면 그것) — 동봉 파이썬(._pth)과 -I 는 그 폴더를 sys.path 에 넣지 않는다."""
    if name in sys.modules:
        return sys.modules[name]
    if root not in sys.path:
        sys.path.append(root)
    return __import__(name)


def _resume_withdrawal(root, cfg):
    r"""끊긴 [모두 지우기]를 마저 한다(consent.resume_withdrawal — data\withdrawal.json 의 state 가 in_progress 일 때만 일한다)."""
    try:
        import consent
        fn = getattr(consent, "resume_withdrawal", None)
        return fn(root, cfg) if fn is not None else None
    except Exception as e:  # noqa: BLE001 - 다음 정리 때 다시
        return {"ok": False, "error": type(e).__name__}


def _resume_line(res):
    """이어서 한 [모두 지우기]의 결과 한 줄(consent.withdraw_message — 지운 수 · 못 지운 수 · 서버에 남은 공유)."""
    try:
        import consent
        return str(consent.withdraw_message(res))
    except Exception:  # noqa: BLE001 - 한 줄을 만들지 못해도 정리는 끝났다
        return f"이 PC 의 자료 {int((res or {}).get('deleted') or 0)}개를 지웠습니다"


def _retry_withdrawals(root, cfg):
    r"""[모두 지우기] 뒤 서버에서 아직 못 지운 공유를 다시 지운다(teamup.retry_withdrawals — data\withdrawal.json 과 표시
    ("withdraw")가 붙은 영수증이 있을 때만 · 5초)."""
    if not os.path.isfile(os.path.join(root, "data", "withdrawal.json")):
        return None
    try:
        return _root_mod("teamup", root).retry_withdrawals(root, cfg, timeout=5)
    except Exception as e:  # noqa: BLE001 - 다음 시작·정리 때 다시
        return {"ok": False, "error": type(e).__name__}


def purge_status_path(root=None):
    r"""data\purge_status.json — retention.py --purge(매일 정리 · AgentFinder32.bat 시작)의 마지막 결과."""
    return os.path.join(os.path.abspath(str(root or ROOT)), "data", PURGE_STATUS)


def write_purge_status(root, out):
    r"""마지막 정리 결과를 data\purge_status.json 에 남긴다(날짜만 — 화면의 [내 데이터] 탭이 '매일 정리' 상태로 보인다).
    {product, date, deleted(기한이 지나 지운 수), legacy(옛 자료), raw(수집 원자료), errors(못 지운 수), error_paths(앞 5개 —
    설치 폴더 기준 경로만), withdrawal_left([모두 지우기] 뒤 서버에서 아직 못 지운 공유 수 | None)}. 못 쓰면 조용히 넘어간다.
    내 자료가 아닌 폴더(_not_mine — 다른 사용자의 설치 · 주인을 모르는 자료)에는 쓰지 않는다(그 dict 만 돌려준다)."""
    pg, lg = out.get("purge") or {}, out.get("legacy") or {}
    errs = [e for e in list(lg.get("errors") or []) + list(pg.get("errors") or []) if isinstance(e, dict)]
    retry = out.get("retry")
    st = {"product": lmname.PRODUCT, "date": _today(), "deleted": int(pg.get("deleted") or 0),
          "legacy": int(lg.get("deleted") or 0), "raw": int(out.get("raw") or 0), "errors": len(errs),
          "error_paths": [str(e.get("path") or "") for e in errs[:5]],
          "withdrawal_left": (int(retry.get("left") or 0) if isinstance(retry, dict) else None)}
    try:
        if _not_mine(root):
            return st
        if not (os.path.lexists(os.path.join(root, "data")) and _link_dir(os.path.join(root, "data"))):
            _write_json(purge_status_path(root), st)        # 연결(정션)된 자료 폴더 너머에는 쓰지 않는다
    except OSError:
        pass
    return st


def read_purge_status(root=None):
    r"""data\purge_status.json → dict | None(없음·깨짐·AgentFinder32 표식 없음)."""
    d = _read_json(purge_status_path(root))
    return d if isinstance(d, dict) and d.get("product") == lmname.PRODUCT else None


def _receipts_n(root):
    r"""data\share_receipts.json 에 남은 영수증 수(읽기만 — 못 읽으면 0)."""
    rec = _read_json(os.path.join(root, "data", "share_receipts.json"))
    lst = rec.get("receipts") if isinstance(rec, dict) else rec
    return sum(1 for x in lst if isinstance(x, dict)) if isinstance(lst, list) else 0


def _wipe(root, cfg):
    r"""--purge-all — 공유 영수증이 있으면 그 서버 사본부터 지운다(지우기만 · teamup.withdraw_all).
    · 서버에서 못 지운 영수증이 남으면 [모두 지우기] 순서로 지운다(consent.withdraw — 영수증에 표시를 붙여 남기고 data\withdrawal.json
      을 쓴다 → 다음 시작 때 teamup.retry_withdrawals 가 다시 지운다).
    · 남은 영수증이 없으면 모두 지운다(purge_all — 설치 정보를 맨 끝에).
    어느 쪽이든 매일 정리 작업을 지운다. → {"deleted","errors","pending_receipts","task_removed","server", …}
    분석이 그 사이 시작됐으면(consent.WithdrawBusy) {"error": "busy"}."""
    server = None
    if _receipts_n(root):
        try:
            server = _root_mod("teamup", root).withdraw_all(root, cfg, timeout=10)
        except Exception as e:  # noqa: BLE001 - 서버 사본 지우기 실패는 영수증이 남아 다음 시작 때 다시 한다
            server = {"ok": False, "error": type(e).__name__}
    left = _receipts_n(root)
    if left:
        import consent
        try:
            res = dict(consent.withdraw(root, cfg, server_withdrawal=server))
        except getattr(consent, "WithdrawBusy", ()):
            return {"ok": False, "error": "busy", "deleted": 0, "errors": [], "server": server}
    else:
        res = purge_all(root)
        res["pending_receipts"] = 0
        res["task_removed"] = unregister_task(root)
    res["server"] = server
    return res


def _say_errors(errors, limit=3):
    """못 지운 것의 까닭을 몇 줄로(경로 — 까닭 · 잡고 있는 프로그램). bat 이 이 줄을 보라고 안내한다."""
    for e in [x for x in errors or [] if isinstance(x, dict)][:limit]:
        who = f" · {e.get('holder')}" if e.get("holder") else ""
        print(f"   · {e.get('path') or '(자료 폴더)'} — {e.get('why') or '지우지 못함'}{who}")
    more = len(errors or []) - limit
    if more > 0:
        print(f"   · 그 밖에 {more}개")


def _main(argv):
    def arg(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None
    root = os.path.abspath(arg("--root") or ROOT)
    as_json = "--json" in argv
    out = {}
    rc = 0
    if "--purge" in argv:
        dry = "--dry-run" in argv
        cfg, _w = afcfg.load_effective(root)
        if not dry:
            out["resume"] = _resume_withdrawal(root, cfg)
        out["legacy"] = purge_legacy(root, dry_run=dry)
        out["purge"] = purge(root, cfg, dry_run=dry)
        if not dry:
            out["retry"] = _retry_withdrawals(root, cfg)
            out["raw"] = drop_raw(root) if raw_left(root) and not run_active(root) else 0
            out["status"] = write_purge_status(root, out)
        failed = bool(out["legacy"]["errors"] or out["purge"]["errors"])
        resumed = out.get("resume") if isinstance(out.get("resume"), dict) else None
        # 끝나지 않은 [모두 지우기]를 이 호출이 마쳤으면 3(RC_WIPED) — 부른 쪽(AgentFinder32.bat)은 그 시작에서 분석하지 않는다
        rc = RC_WIPED if (resumed and resumed.get("state") == "done") else (1 if failed else 0)
        if not as_json:
            p = out["purge"]
            if resumed:                                      # 끝나지 않은 [모두 지우기]가 있었다 — 무엇을 지웠는지 먼저 알린다
                print("[지우기] 끝나지 않은 [모두 지우기]를 이어서 했습니다 — " + _resume_line(resumed))
                _say_errors(resumed.get("errors"))
            print(f"[보관기한] 옛 자료 {out['legacy']['deleted']}개 · 기한 지난 자료 {p['deleted']}개 지움"
                  + (f" · 수집 원자료 {out['raw']}개 지움" if out.get("raw") else "")
                  + (f" · 못 지운 것 {len(p['errors']) + len(out['legacy']['errors'])}개" if failed else ""))
    elif "--purge-all" in argv:
        busy_line = "[지우기] 이 폴더의 분석·수집이 돌고 있어 지우지 않았습니다 — 그 작업이 끝난 뒤 다시 실행할 수 있습니다"
        if run_active(root):
            out = {"ok": False, "error": "busy", "deleted": 0, "errors": []}
            rc = 1
            if not as_json:
                print(busy_line)
        elif "--keep-consent" in argv:
            out = purge_all(root, keep_consent=True)
            rc = 1 if out["errors"] else 0
            if not as_json:
                print(f"[지우기] {out['deleted']}개 지움" + (f" · 못 지운 것 {len(out['errors'])}개" if rc else ""))
                _say_errors(out["errors"])
        else:
            cfg, _w = afcfg.load_effective(root)
            out = _wipe(root, cfg)
            rc = 1 if (out.get("errors") or out.get("error")) else 0
            if not as_json and out.get("error") == "busy":
                print(busy_line)
            elif not as_json:
                left = int(out.get("pending_receipts") or 0)
                srv = out.get("server") if isinstance(out.get("server"), dict) else {}
                gone = int(srv.get("removed") or 0)
                print(f"[지우기] {int(out.get('deleted') or 0)}개 지움"
                      + (f" · 조직장 서버의 공유 {gone}건 지움" if gone else "")
                      + (f" · 못 지운 것 {len(out['errors'])}개" if out.get("errors") else "")
                      + (f" · 조직장 서버에서 아직 지우지 못한 공유 {left}건은 다음 시작 때 다시 지웁니다" if left else ""))
                _say_errors(out.get("errors"))
    elif "--legacy" in argv:
        out = purge_legacy(root, dry_run="--dry-run" in argv)
        rc = 1 if out["errors"] else 0
    elif "--expiry" in argv:
        cfg, _w = afcfg.load_effective(root)
        out = {"rows": expiry_table(root, cfg), "kept": kept_table(root)}
    elif "--register" in argv:
        out = {"ok": register_task(root), "task": task_name(root)}
        rc = 0 if out["ok"] else 1
    elif "--unregister" in argv:
        out = {"ok": unregister_task(root), "task": task_name(root)}
        rc = 0 if out["ok"] else 1
    elif "--task-status" in argv:
        out = {"registered": task_registered(root), "task": task_name(root)}
    else:
        print(__doc__)
        return 2
    if as_json or not ("--purge" in argv or "--purge-all" in argv):
        print(json.dumps(out, ensure_ascii=False, default=str))
    return rc


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
