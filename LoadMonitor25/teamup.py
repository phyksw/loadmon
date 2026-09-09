# -*- coding: utf-8 -*-
r"""
teamup.py — 분석 결과를 팀 저장소로 올린다 (LoadMonitor25: 자동 전송이 아니라 '대기 → 버튼')

팀 서버(예: http://10.115.147.68:9310)는 특정 망에서만 닿는다. 분석은 아무 망에서나 하니
분석 때마다 자동 전송을 시도하면 대부분 실패하고, 그 결과가 조용히 사라진다(실측).
그래서 LM19 는 이렇게 나눈다:

  1) 분석이 끝나면  → 보낼 묶음을 report\upload_pending\ 에 만들어 둔다 (전송 안 함)
  2) 서버에 닿는 망에서 → 대시보드 [팀 서버 업로드] 버튼(또는 이 스크립트)으로 한 번에 보낸다
     밀린 기간이 여러 개면 전부 함께 올라가고, 보낸 묶음은 report\upload_sent\ 로 옮긴다

  python teamup.py --build --from 2026-05-19 --to 2026-08-17   묶음 준비(전송 안 함)
  python teamup.py --list                                      대기 목록
  python teamup.py --ping [--url http://...]                   이 망에서 닿는지 확인(빠름)
  python teamup.py --upload [--url http://...]                 대기분 전부 전송
  python teamup.py --to-folder "\\서버\공유\LoadMonitor"          공유폴더로 대신 저장
      (개인 HTML 보고서 분석리포트_<기간>.html·보고서_<기간>.html 이 있으면
       <폴더>\개인리포트\<이름>_<파일명> 으로 함께 복사 — 팀 서버 묶음에는 넣지 않는다)
  (--json 을 붙이면 마지막 줄에 결과 JSON 한 줄 — 대시보드가 이걸 읽는다)

묶음 내용은 팀 공유폴더 내보내기(export.py)와 동일하다 — 이미 excludePathKeywords 로 걸러진
판정 결과다. 사내망 전용.
"""
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
MAX_BYTES = 30 * 1024 * 1024        # 서버 상한과 같다 — 넘으면 보내기 전에 알려 준다
if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8


FLAGS = {"--build", "--build-all", "--build-latest", "--scan", "--list", "--ping",
         "--upload", "--to-folder", "--drop", "--json", "--url", "--from", "--to"}


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


def target_url(cfg, override=""):
    return (override or arg("--url") or cfg.get("teamServerUrl") or "").strip().rstrip("/")


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
    out["programs"] = [{"name": str(p.get("name") or "")[:40], "kind": str(p.get("kind") or "")[:6],
                        "cat": str(p.get("cat") or "")[:10], "hours": _hours(p.get("hours")),
                        "bg_hours": _hours(p.get("bg_hours")), "days": _count(p.get("days"))}
                       for p in progs if isinstance(p, dict)][:12]
    for k in ("by_cat", "by_kind"):
        v = tu.get(k)
        if isinstance(v, list):
            out[k] = [[str(x[0])[:12], _hours(x[1])] for x in v
                      if isinstance(x, (list, tuple)) and len(x) >= 2][:8]
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


def build(cfg, d0, d1):
    """report 의 산출물로 업로드 묶음(서버 전송 본문 그대로)을 만든다 → 경로 또는 None.
    같은 기간을 다시 분석하면 그 기간 대기 묶음을 갈아끼운다(같은 것이 쌓이지 않게)."""
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
              # A30 — 비업무 제외 후 시간 재산정 여부·뺀 시간(h)
              "rehours": bool(mj.get("rehours")), "dropped_h": _hours(mj.get("dropped_h")),
              "host": os.environ.get("COMPUTERNAME", ""),
              # 누가·언제·어디서 — 팀장이 "이 숫자는 누구 것이고 언제 것인가"를 묻는다(사용자 요청)
              "analyzed_at": time.strftime("%Y-%m-%d %H:%M")}
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
def ping(url, timeout=4.0):
    """이 망에서 서버에 닿는가 — 빠르게 확인한다(응답이 오면 도달로 본다)"""
    if not url:
        return {"ok": False, "error": "주소가 비어 있습니다 (config.teamServerUrl)"}
    t0 = time.time()
    try:
        req = urllib.request.Request(url + "/api/team", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(2048)
            code = r.status
    except urllib.error.HTTPError as e:      # 404 라도 서버는 살아 있다 = 이 망에서 닿는다
        code = e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", e)
        return {"ok": False, "url": url, "ms": int((time.time() - t0) * 1000),
                "error": f"{reason}",
                "hint": "이 망에서는 팀 서버에 닿지 않습니다 — 서버망(사내망)에서 다시 눌러 주세요. "
                        "묶음은 그대로 대기합니다."}
    return {"ok": True, "url": url, "code": code, "ms": int((time.time() - t0) * 1000)}


def upload_one(url, path, timeout=360.0):
    """대기 묶음 한 개 전송 → (ok, 메시지)"""
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        return False, f"묶음을 읽지 못했습니다: {e}"
    if len(raw) > MAX_BYTES:
        return False, (f"묶음이 너무 큽니다 ({len(raw) / 1048576:.1f}MB > 30MB) — "
                       "기간을 나눠 분석한 뒤 다시 시도하세요")
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
        stop = blockers(member, files)
        if stop:
            return False, stop[0]
        body = json.dumps({"member": member, "files": files},
                          ensure_ascii=False).encode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False, "묶음 형식이 깨졌습니다 — 해당 기간을 다시 분석하세요"
    req = urllib.request.Request(url + "/api/upload", data=body,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except OSError:
            pass
        return False, f"서버가 거부했습니다 (HTTP {e.code}) {detail}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"연결 실패: {getattr(e, 'reason', e)}"
    except ValueError:
        return False, "서버 응답을 해석하지 못했습니다"
    if not res.get("ok"):
        return False, f"서버 거부: {res.get('error', '')}"
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
    return True, (f"{res.get('saved')}개 파일 저장, 팀 취합 "
                  f"{'갱신됨' if res.get('aggregated') else '갱신 실패(서버 로그 확인)'}" + note)


def upload_all(url, timeout=360.0):
    """대기 묶음을 전부 전송. 성공분만 upload_sent 로 옮긴다(실패분은 그대로 대기)."""
    items = list_pending()
    results = []
    if not items:
        return {"ok": True, "sent": 0, "failed": 0, "results": [],
                "note": "보낼 대기 묶음이 없습니다 — 먼저 [분석 실행]을 하세요"}
    os.makedirs(SENT, exist_ok=True)
    sent = failed = 0
    for it in items:
        p = os.path.join(PENDING, it["file"])
        ok, msg = upload_one(url, p, timeout)
        if ok:
            sent += 1
            try:                            # 보낸 것은 옮겨 두 번 보내지 않는다(기록은 남긴다)
                shutil.move(p, os.path.join(SENT, it["file"]))
            except OSError:
                pass
            prune_sent()
        else:
            failed += 1
        results.append({"file": it["file"], "tag": it.get("tag", ""), "ok": ok, "msg": msg})
    return {"ok": failed == 0, "sent": sent, "failed": failed, "results": results}


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
        want = d.get("files") or {}
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


def status(cfg, url=""):
    """대시보드용 현황 — 도달성 확인은 하지 않는다(누를 때만 한다)"""
    return {"url": url or target_url(cfg), "share": (cfg.get("teamShareDir") or "").strip(),
            "auto": bool((cfg.get("teamUpload") or {}).get("auto")),
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
        _out(js, r, f"[teamup] 공유폴더 저장: 성공 {r.get('sent', 0)} / 실패 {r.get('failed', 0)}"
                    + (f" — {r.get('error', '')}" if r.get("error") else ""))
        return 0 if r.get("ok") else 1
    if "--upload" in sys.argv:
        url = target_url(cfg)
        if not url:
            _out(js, {"ok": False, "error": "config.teamServerUrl 미설정"},
                 "[teamup] 팀 서버 주소가 없습니다 — config\\config.json 의 teamServerUrl 을 적으세요")
            return 1
        pg = ping(url)
        if not pg.get("ok"):
            _out(js, {"ok": False, "error": pg.get("error", ""), "hint": pg.get("hint", ""),
                      "unreachable": True, "pending": len(list_pending())},
                 f"[teamup] 이 망에서 서버에 닿지 않습니다 ({url}) — {pg.get('error', '')}\n"
                 f"         묶음 {len(list_pending())}건은 그대로 대기합니다. "
                 "서버망에서 다시 실행하면 한 번에 올라갑니다.")
            return 1
        r = upload_all(url)
        lines = [f"[teamup] 전송 완료: 성공 {r['sent']} / 실패 {r['failed']}"]
        for x in r.get("results", []):
            lines.append(f"         - {x.get('tag', x['file'])}: {'OK' if x['ok'] else '실패'} {x['msg']}")
        if r.get("note"):
            lines.append("         " + r["note"])
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
        pg = ping(url)
        if not pg.get("ok"):
            print(f"[teamup] 이 망에서 서버에 닿지 않습니다 — 묶음은 대기합니다 ({pg.get('error', '')})")
            return 1
        r = upload_all(url)
        print(f"[teamup] 전송: 성공 {r['sent']} / 실패 {r['failed']}")
        for x in r.get("results", []):      # 무엇이 어떻게 됐는지 화면에 남긴다(서버 갱신 여부 포함)
            print(f"         - {x.get('tag', x['file'])}: {'OK' if x['ok'] else '실패'} {x['msg']}")
        return 0 if r.get("ok") else 1
    print(__doc__.strip().splitlines()[1])
    print("[teamup] --build / --list / --ping / --upload / --to-folder 중 하나를 주세요")
    return 1


if __name__ == "__main__":
    sys.exit(main())
