# -*- coding: utf-8 -*-
r"""
freeze.py — 분석 결과를 '파일 하나' 보고서 3종으로 만든다 (LoadMonitor30v1).

  python freeze.py --from 2026-01-01 --to 2026-08-25            # 3종 전부 (= --all)
  python freeze.py --from ... --to ... --freeze [--summary]     # 얼린 보고서만 (--summary: 원문 제외)
  python freeze.py --from ... --to ... --island                 # 분석리포트만
  python freeze.py --from ... --to ... --word                   # 리포트(Word 친화)만
  (--from/--to 가 없으면 report\ 의 최신 결과 기간)

만드는 것
  ① 얼린 보고서   report\얼린보고서\LoadMonitor_보고서_<d0>_<d1>_<PC>_<ts>.html  +  고정명 report\보고서_<기간>.html
     — 설치된 ui\app.py 를 이 프로세스 안에서 잠깐 띄워(또는 떠 있는 대시보드의 base_url 로) 화면과
       탭 데이터 20종을 받아 HTML 하나에 굽는다. 프로그램 없는 PC 에서도 더블클릭으로 열린다.
  ② 분석리포트    report\분석리포트_<기간>.html (+ 얼린보고서\ 타임스탬프 사본)
     — 결과 파일만 읽어 만드는 한 장. 데이터 섬(lm-report-data, kind "lm-personal-report")을 팀 취합이 읽는다.
  ③ 리포트        report\리포트_<기간>.html / .doc  (report_out.py — Word 로 열리는 문서)

고정명(보고서_<기간>.html·분석리포트_<기간>.html)은 언제나 '원문 포함(full)' 본이다. --summary(원문 제외)는
보고서_<기간>_요약.html·분석리포트_<기간>_요약.html 로 따로 쓰고 고정명은 건드리지 않는다 — 공유폴더 배치
(teamup --to-folder, REPORT_HTML)는 고정명만 복사하므로 요약본이 원문본 자리에 나가는 일이 없다.
화면이 보여 주는 기간(최신 결과)이 요청 기간과 다르면 화면 기간 이름으로만 저장하고, 요청 기간의 고정명은
만들지 않는다(낡은 것이 있으면 지운다) — 결과는 ok:false·partial(종료 코드 2) 에 missing 으로 명시한다.
데이터 섬·_lm 의 stub:true 는 last_run.json 의 'AI 판정' 이 스텁(LM_COPILOT_STUB) 이었다는 표시다.

마지막 줄에 JSON 한 줄 {"ok","files","tag",...} — run.py(_run_capture)·대시보드가 읽는다.
종료 코드: 0 전부 성공 · 2 일부만 성공 · 1 아무것도 못 만듦.
HTML 은 팀 서버로 올리지 않는다(서버 NAME_OK 불변) — 공유폴더 저장(teamup --to-folder) 때만
<공유폴더>\개인리포트\<이름>_<파일명> 으로 복사된다.
LM30(2026-10-18): 그래서 ①·② 의 출퇴근·시간외 근무 카드·절은 주·달 합계만 싣는다 — 날짜별 출근·퇴근·평소 시각은 이 PC 의
대시보드와 ③ 리포트(복사되지 않는다)에만 있다(_att_summary_only · report_out.attendance_section(per_day=False)).
LM30v1(2026-10-19): 법정 채움 MM 도 ①·② 에는 달 합계만 — 근태 기록 시간·+@ 나눔과 '휴가 추정'·'근태·흔적 모두 없음' 날짜는
이 PC 의 대시보드와 ③ 리포트에만 있다(/api/dash 의 mm_local 을 빼고 · 분석리포트는 report_out.legal_section(local=None)).
"""
import csv
import glob
import html as _html
import io
import json
import os
import re
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(ROOT, "report")
FREEZE_DIR = os.path.join(REPORT, "얼린보고서")
KEEP_FROZEN = 10        # 얼린보고서\ 에 남길 과거본 수(같은 종류끼리). 0 이면 무제한.
# 분석을 한 번 돌 때마다 얼린 보고서와 분석리포트가 한 장씩(합쳐 약 0.6MB) 쌓인다. 아무도 읽지
# 않는 순수 적재라 오래 쓰면 이것만 수십 MB 가 되고, 그대로 다음 PC 로 따라간다. 원자료가 함께
# 옮겨 다니므로 과거본은 언제든 다시 구울 수 있다 — 최근 것만 남긴다.
# (tools\Make-MovePack.py 는 zip 을 만들 때만 2개로 잘랐는데, 실사용자는 zip 을 쓰지 않아
#  그 규칙이 한 번도 집행되지 않았다. 그래서 만드는 자리에서 바로 정리한다.)


def _prune_frozen(made_path):
    r"""방금 만든 파일과 **같은 계열**만 최근 KEEP_FROZEN 개로 줄인다.

    계열은 '무엇인가'(보고서 / 분석리포트)와 '원문본이냐 요약본이냐' 로만 가른다. 기간은 일부러
    키에 넣지 않는다 — 화면 기본 기간이 ytd 라 종료일이 매일 바뀌고, 기간을 키에 넣으면 매일이
    새 계열이 되어 한 장도 정리되지 않는다. 반대로 요약본을 원문본과 같은 계열로 묶으면 서로를
    밀어내 한쪽이 통째로 사라진다(첫 구현에서 실제로 요약본 2장이 전부 지워졌다 — 시험으로 확인).
    """
    if not KEEP_FROZEN or not made_path:
        return
    try:
        base = os.path.basename(made_path)
        stem = base.split("_20", 1)[0]          # 'LoadMonitor_보고서' / 'LoadMonitor_분석리포트'
        want_sum = "_요약" in base
        same = [os.path.join(FREEZE_DIR, f) for f in os.listdir(FREEZE_DIR)
                if f.lower().endswith(".html") and f.startswith(stem)
                and ("_요약" in f) == want_sum]
        if len(same) <= KEEP_FROZEN:
            return
        same.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for p in same[KEEP_FROZEN:]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_CORE = os.path.join(ROOT, "core")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
if __name__ == "__main__":      # import 시엔 건드리지 않는다(run.py·app.py 와 같은 관례)
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))  # 콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8


def _say(msg=""):
    print(msg, flush=True)


def _esc(s):
    """HTML 이스케이프 — 이름·경로 등 사람이 넣은 값은 화면에 넣기 전에 항상 거친다"""
    return _html.escape(str(s if s is not None else ""))


def _safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', "-", name)      # 파일명 금지 문자 방어


# 같은 프로세스 안의 보고서 생성 직렬화 — 대시보드(ui\app.py)가 이 모듈을 in-process 로 부르는데,
# 두 스레드가 동시에 만들면 같은 고정명 파일을 서로 교체하다 한쪽이 실패한다(검증 확정: 스레드 2개 8회 중
# 2회 '일부만 저장', 3개면 매회). 재진입 가능(RLock) — make_all 안에서 freeze() 가 다시 잡는다.
_MAKE_LOCK = threading.RLock()


def _write_atomic(path, text):
    """쓰다 만 파일이 남지 않게 — 같은 폴더의 '자기만의' .tmp 에 쓴 뒤 교체.
    tmp 이름은 tempfile.mkstemp 로 호출마다 유일하다. 예전엔 pid 만 붙어 같은 프로세스의 다른 스레드가
    서로의 tmp 를 덮어 쓰고 지웠다(os.replace 가 FileNotFoundError/PermissionError — 검증 확정)."""
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp",
                               dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        if os.name != "nt":
            os.chmod(tmp, 0o644)        # mkstemp 는 0600 — 결과 파일은 남이 읽는 보고서다(윈도우는 무관)
        os.replace(tmp, path)
        return path
    except OSError:
        pass
    # 열려 있는 파일(브라우저가 잡고 있는 HTML)은 교체가 막힐 수 있다 — 덮어쓰기로 재시도.
    # 그것도 실패하면 .tmp 를 남기지 않는다(재실행마다 쌓이던 것을 막는다). 지우는 것은 자기 tmp 뿐이다.
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return path


def _size_txt(p):
    """로그용 크기 — 다른 스레드·프로세스가 같은 파일을 갈아끼우는 순간이면 없을 수 있다(예외로 죽지 않게)"""
    try:
        return f"  ({os.path.getsize(p) / 1048576:.1f} MB)"
    except OSError:
        return ""


def _is_stub():
    r"""이번 결과가 스텁 판정(LM_COPILOT_STUB — 테스트 전용, 실제 Copilot 아님)인가.
    report\last_run.json 의 'AI 판정' 단계 note 로 안다 — 팀 취합이 사본의 stub 표시를 보고 테스트 자료를
    실자료와 섞지 않는다. 파일이 없거나 형식이 다르면 False."""
    lr = _read_json(os.path.join(REPORT, "last_run.json"))
    stages = lr.get("stages") if isinstance(lr, dict) else None
    for st in (stages if isinstance(stages, list) else []):
        if isinstance(st, dict) and st.get("name") == "AI 판정":
            return "LM_COPILOT_STUB" in str(st.get("note") or "")
    return False


def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _cfg():
    return _read_json(os.path.join(ROOT, "config", "config.json")) or {}


def _owner():
    return (str(_cfg().get("owner") or "").strip()
            or os.environ.get("USERNAME", "")) or "이름미상"


def _host():
    return os.environ.get("COMPUTERNAME", "")


# ── 기간(tag) ───────────────────────────────────────────────────────────────
def tag_of(d0, d1):
    return f"{d0.replace('-', '')}-{d1.replace('-', '')}"


def tag_to_dates(tag):
    return f"{tag[:4]}-{tag[4:6]}-{tag[6:8]}", f"{tag[9:13]}-{tag[13:15]}-{tag[15:]}"


def latest_tag():
    """가장 최근 분석 결과의 기간 — mm_rows(화면과 같은 축) 우선, 없으면 mm_meta"""
    best, bt = "", 0
    pats = [(r"^mm_rows_(\d{8}-\d{8})(_refined)?\.csv$", "mm_rows_*.csv"),
            (r"^mm_meta_(\d{8}-\d{8})\.json$", "mm_meta_*.json")]
    for rx, g in pats:
        for p in glob.glob(os.path.join(REPORT, g)):
            m = re.match(rx, os.path.basename(p))
            if not m:
                continue
            try:
                t = os.path.getmtime(p)
            except OSError:
                continue
            if t > bt:
                best, bt = m.group(1), t
        if best:
            break
    return best


# ══ ① 얼린 보고서 (HTML 한 장) ══════════════════════════════════════════════
# 대시보드 화면을 다시 그리는 것이 아니라, 설치된 ui\app.py 를 띄워 지금 그 화면과 각 탭의
# 데이터를 전부 받아 파일 하나에 굽는다. 그래서 화면 모양·계산 로직이 설치된 그 버전과 언제나 같다.

FREEZE_EPS = ["/api/status", "/api/dash", "/api/projects", "/api/workflow",
              "/api/agentic", "/api/extra", "/api/teamserver", "/api/teamupload",
              "/api/sharedir", "/api/attendance",
              "/api/review?g=week", "/api/review?g=month", "/api/review?g=all",
              "/api/data?src=files", "/api/data?src=recent", "/api/data?src=mail",
              "/api/data?src=cal", "/api/data?src=git", "/api/data?src=pc",
              "/api/data?src=teams", "/api/data?src=act"]
# LM30(2026-10-18) — 출퇴근·시간외 근무 카드(/api/attendance)는 사본에 주·달 합계만 굽는다. 날짜별 출근·퇴근(days)·평소 시각(usual·
# usual_text)은 이 PC 화면에만 — 얼린 보고서 고정명은 공유폴더 저장 때 <공유폴더>\개인리포트\ 로 복사된다(teamup.REPORT_HTML).
# LM30(2026-10-19) +@ — 근태 기록(GERP 포함)과 견준 값(hr·records_text·hr 를 쓴 결론 줄)도 사본에 굳히지 않는다: hr 를 빼고, 합계에
# 섞인 근태 칸을 빼고(attendance.strip_hr), 결론 줄은 근태 없이 추정한 +@ 로 다시 쓰고, 근태 기록 비교 줄은 '본인 PC 에서만' 으로.
ATT_LOCAL_KEYS = ("days", "usual", "usual_text", "hr")


def _att_summary_only(v):
    """/api/attendance 답 → 사본용(날짜별 행·평소 시각·근태 기록과 견준 값을 뺀다 · frozen 표식 — 화면이 '날짜별 시각은 본인 PC
    에서만' 을 보인다)."""
    if not isinstance(v, dict):
        return v
    out = {k: x for k, x in v.items() if k not in ATT_LOCAL_KEYS}
    out["days"] = {}
    out["frozen"] = True
    try:
        import attendance as _att
    except ImportError:
        return out
    if isinstance(out.get("agg"), dict):
        out["agg"] = json.loads(json.dumps(out["agg"]))
        _att.strip_hr(out["agg"])
    if "plus_text" in out:
        per = out.get("period") if isinstance(out.get("period"), list) and len(out.get("period")) == 2 else ["", ""]
        cfg_ = out.get("cfg") if isinstance(out.get("cfg"), dict) else {}
        out["plus_text"] = _att.plus_line(out.get("agg"), None, per[1] or None, None, cfg_.get("standardDayHours"))
    if "records_text" in out:
        out["records_text"] = _att.FROZEN_REC_TEXT
    return out

INTERCEPT_JS = """(function(){
 "use strict";
 var el=document.getElementById("lm-frozen-data");
 var D={};try{D=JSON.parse(el.textContent);}catch(e){}
 function fake(body){return Promise.resolve({ok:true,status:200,
  json:function(){return Promise.resolve(body);},
  text:function(){return Promise.resolve(JSON.stringify(body));}});}
 var BLOCK={ok:false,error:"얼린 보고서 사본입니다 — 이 동작은 여기서 실행되지 않습니다."};
 window.fetch=function(url,opt){
  var m=((opt&&opt.method)||"GET").toUpperCase();
  var u=String(url).replace(/^https?:\\/\\/[^\\/]+/,"");
  if(m==="GET"&&Object.prototype.hasOwnProperty.call(D,u))return fake(D[u]);
  return fake(BLOCK);
 };
 window.confirm=function(){alert("얼린 보고서 사본입니다 — 동작 버튼은 실행되지 않습니다.");return false;};
 window.open=function(){alert("얼린 보고서 사본입니다 — 원본 프로그램에서 여세요.");return null;};
 document.addEventListener("click",function(ev){
  var a=ev.target&&ev.target.closest?ev.target.closest("a[href]"):null;
  if(!a)return;
  var h=a.getAttribute("href")||"";
  if(h.charAt(0)==="/"||h.indexOf("http://127.0.0.1")===0){
   ev.preventDefault();ev.stopPropagation();
   alert("얼린 보고서 사본입니다 — 이 화면은 원본 프로그램에서 여세요.");
  }
 },true);
})();"""


def bake(base_url, log=_say):
    """base_url 의 대시보드에서 화면("/")과 FREEZE_EPS 데이터를 받는다 → (html, baked)"""
    import urllib.error
    import urllib.request
    base_url = str(base_url or "").rstrip("/")

    def get(path, timeout=240):
        try:
            with urllib.request.urlopen(base_url + path, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            return None                      # 그 버전에 없는 화면 — 건너뛴다
        except Exception as e:  # noqa: BLE001 - 한 탭 실패로 전체가 죽지 않게
            log(f"    [!] {path} 읽기 실패: {type(e).__name__}")
            return None

    html = get("/")
    baked = {}
    for p in FREEZE_EPS:
        b = get(p)
        if b is None:
            continue
        try:
            baked[p] = json.loads(b.decode("utf-8"))
        except ValueError:
            pass
    return (html.decode("utf-8") if html else None), baked


def _serve_and_bake(log=_say):
    r"""설치본 ui\app.py 를 이 프로세스 안에서 임시 포트에 띄워 화면과 데이터를 전부 받는다.
    대시보드가 떠 있지 않은 run.py 경로(별도 프로세스)에서 쓴다."""
    ui_dir = os.path.join(ROOT, "ui")
    if ui_dir not in sys.path:
        sys.path.insert(0, ui_dir)
    import importlib
    try:
        app_mod = importlib.import_module("app")
    except Exception as e:  # noqa: BLE001 - 원인은 화면에 말한다
        log(f"    [!] ui\\app.py 를 불러오지 못했습니다: {type(e).__name__}: {str(e)[:120]}")
        return None, {}
    # 구판 app.py 는 임포트되는 순간 atexit 에 Copilot 전용 Edge 강제 종료를 등록했다(LM22 는 main()
    # 안으로 옮김). 어느 판이든 이 프로세스가 끝날 때 판정 왕복 Edge 를 죽이지 않게 방어적으로 푼다.
    try:
        import atexit
        fn = getattr(app_mod, "cleanup_children", None)
        if fn is not None:
            atexit.unregister(fn)
    except Exception:  # noqa: BLE001 - 훅 정리 실패가 얼리기를 막지 않게
        pass
    from http.server import ThreadingHTTPServer
    quiet = type("Quiet", (app_mod.H,), {"log_message": (lambda self, *a, **k: None)})
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), quiet)
    except OSError as e:
        log(f"    [!] 임시 서버를 열지 못했습니다: {e}")
        return None, {}
    port = srv.server_address[1]
    try:
        app_mod.PORT[0] = port
    except Exception:  # noqa: BLE001 - 없는 버전도 있다
        pass
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        return bake(f"http://127.0.0.1:{port}", log)
    finally:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:  # noqa: BLE001
            pass


def _strip_evidence(o):
    """원문 조각(evidence)을 재귀적으로 뺀다 — 요약본용"""
    if isinstance(o, dict):
        return {k: _strip_evidence(v) for k, v in o.items() if k != "evidence"}
    if isinstance(o, list):
        return [_strip_evidence(x) for x in o]
    return o


def freeze(tag, full=True, base_url=None, log=_say, info=None):
    """대시보드를 얼려 HTML 파일 하나로 → 만든 파일 경로 목록([] 이면 실패).
    full=False 면 원문(메일·회의 제목, 데이터 원문, 근거 조각) 제외 — 고정명은 보고서_<기간>_요약.html.
    base_url 이 있으면 떠 있는 그 대시보드에서 받고, 없으면 ui\\app.py 를 임시로 띄운다.
    info(dict) 를 주면 화면 기간이 요청 기간과 다를 때 mismatch/requested/shown/missing 을 채워 준다."""
    with _MAKE_LOCK:        # 임시 서버·app.PORT 전역·고정명 교체가 스레드 사이에 겹치지 않게
        return _freeze(tag, full, base_url, log, info)


def _freeze(tag, full, base_url, log, info):
    log("  설치된 화면을 잠깐 띄워 지금 모습 그대로 받아옵니다…" if not base_url
        else f"  떠 있는 대시보드({base_url})에서 화면을 받아옵니다…")
    html, baked = bake(base_url, log) if base_url else _serve_and_bake(log)
    if not html:
        log("    [!] 화면을 받지 못해 만들지 못했습니다.")
        return []
    if "/api/dash" not in baked or not isinstance(baked.get("/api/dash"), dict):
        log("    [!] 대시보드 데이터를 받지 못해 만들지 못했습니다.")
        return []
    log(f"    화면 + 데이터 {len(baked)}종 수신")

    # 사본에 '실행 중/stale' 이 굳지 않게 — 대시보드가 분석 중이어도 사본은 읽기 전용 결과다
    if isinstance(baked.get("/api/status"), dict):
        baked["/api/status"]["running"] = False
        baked["/api/status"]["step"] = ""
    baked["/api/dash"]["stale"] = False
    # 내 PC 의 사설 IP 를 사본에 굳히지 않는다 — /api/teamserver 의 urls 는 ui/app.py 의 local_ips() 가 NIC 에서
    # 실측한 값이라(설정값이 아니다) 얼린 사본을 팀·사외로 넘기면 그 PC 가 물린 내부망 대역·호스트가 함께 나간다
    # (샘플 보고서 검사에서 실측 확인). 화면에는 살아 있는 대시보드에서만 필요하다.
    # occupant 은 그 포트를 쥔 프로세스의 이름·실행 경로·명령줄·계정이라 사본에 굳을 이유가 없다.
    ts = baked.get("/api/teamserver")
    if isinstance(ts, dict):
        for k in ("urls", "here", "ip", "ips", "host", "occupant"):
            if k in ts:
                ts[k] = [] if isinstance(ts.get(k), list) else ""
    # LM30(2026-10-18) — 출퇴근 카드는 주·달 합계만(날짜별 출근·퇴근·평소 시각은 사본에 굳히지 않는다 — 공유폴더로 복사되는 파일).
    # /api/dash 의 meta(mm_meta 그대로)도 한 번 더 거른다 — 옛 사본에 이 PC 전용 칸이 남아 있어도 사본에는 싣지 않는다(teamup·export 와
    # 같은 관문 core\attendance.scrub_meta)
    if "/api/attendance" in baked:
        baked["/api/attendance"] = _att_summary_only(baked["/api/attendance"])
    # LM30v1(2026-10-19) 법정 채움 MM — 'MM 산정 근거' 카드의 근태 기록 시간·+@ 나눔과 표시 날짜(mm_local — attendance 파일)는 사본에
    # 굽지 않는다. 사본의 카드는 mm_meta 의 달 합계(1MM 기준·법정 채움·근무·투입·가용·로드율·LM30 방식)만 그린다
    baked["/api/dash"].pop("mm_local", None)
    if isinstance(baked["/api/dash"].get("meta"), dict):
        try:
            import attendance as _att
            _att.scrub_meta(baked["/api/dash"]["meta"])
        except ImportError:
            pass

    dash = baked["/api/dash"]
    meta = (dash.get("meta") or {}) if isinstance(dash.get("meta"), dict) else {}
    period = meta.get("period") or ["", ""]
    d0, d1 = (period[0] or ""), (period[-1] or "")
    m = re.search(r"(\d{8})-(\d{8})", str(dash.get("file") or ""))
    if m:
        d0 = d0 or f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
        d1 = d1 or f"{m.group(2)[:4]}-{m.group(2)[4:6]}-{m.group(2)[6:]}"
    if not d0 or not d1:
        d0, d1 = tag_to_dates(tag)
    shown = tag_of(d0, d1) if (d0 and d1 and "기간미상" not in (d0, d1)) else tag
    if tag and shown != tag:
        # 화면은 '가장 최근 결과'를 보여 준다. 요청 기간과 다르면 다른 기간의 이름을 붙이지 않는다 —
        # 화면 기간 이름으로만 저장하고, 요청 기간의 고정명은 '만들지 않은 것' 으로 결과에 명시한다(ok:false).
        # 예전 실행의 낡은 보고서_<요청기간>.html 을 남겨 두면 공유폴더 배치(teamup --to-folder)가 그것을
        # 지금 것으로 복사한다 — 지운다.
        fixed_req = f"보고서_{tag}{'' if full else '_요약'}.html"
        log(f"    [!] 화면이 보여 주는 기간({shown})이 요청 기간({tag})과 다릅니다 — 화면 기간으로 저장하고 "
            f"요청 기간의 고정명 {fixed_req} 은 만들지 않습니다")
        stale_left = ""
        sp = os.path.join(REPORT, fixed_req)
        if os.path.exists(sp):
            try:
                os.remove(sp)
                log(f"    낡은 고정명 사본을 지웠습니다: {fixed_req}")
            except OSError as e:
                stale_left = f"{type(e).__name__}"
                log(f"    [!] 낡은 고정명 사본을 지우지 못했습니다({stale_left}): {fixed_req} — 열려 있으면 닫고 다시")
        if isinstance(info, dict):
            info.update(mismatch=True, requested=tag, shown=shown, missing=[fixed_req],
                        stale_left=stale_left)
        tag = shown

    if not full:
        for g in ("week", "month", "all"):
            k = f"/api/review?g={g}"
            if k in baked:
                baked[k] = {"gran": g, "groups": []}
        for s in ("files", "recent", "mail", "cal", "git", "pc", "teams", "act"):
            k = f"/api/data?src={s}"
            if k in baked:
                baked[k] = {"file": "", "cols": [], "rows": [], "total": 0, "shown": 0}
        if isinstance(baked.get("/api/extra"), dict):
            ex = baked["/api/extra"]
            ex.pop("narratives", None)
            ex.pop("entities", None)
            if isinstance(ex.get("pivots"), dict):
                # 에피소드의 오더→산출 페어(req/done)에는 메일·팀즈 원문 조각이 들어 있다
                ex["pivots"].pop("episodes", None)
            baked["/api/extra"] = _strip_evidence(ex)
        for k in ("/api/workflow", "/api/agentic"):
            if k in baked:
                baked[k] = _strip_evidence(baked[k])

    owner, host = _owner(), _host()
    stub = _is_stub()
    # 팀 취합이 이 사본을 읽을 때 '누구 것인가'를 파일명 추측이 아니라 여기서 읽는다.
    # stub: 판정이 스텁(LM_COPILOT_STUB, 테스트 전용)이었던 결과 — 취합이 실자료와 구분한다.
    baked["_lm"] = {"kind": "frozen", "owner": owner, "host": host,
                    "period": [d0, d1], "tag": tag, "full": bool(full), "stub": stub,
                    "generated": time.strftime("%Y-%m-%d %H:%M"), "generator": "LoadMonitor30v1 freeze.py"}
    who = f"{os.environ.get('USERNAME', '?')}@{host or '?'}"
    ts = time.strftime("%Y-%m-%d %H:%M")
    mode_txt = ("메일·회의 제목 등 원문 근거가 들어 있습니다 — <b>팀 밖 공유 금지</b>"
                if full else "원문 근거(메일·회의 제목, 데이터 원문)를 뺀 <b>요약 사본</b>")
    banner = (
        '<div style="background:#14324f;color:#fff;padding:10px 16px;font-size:13px;'
        "font-family:'Malgun Gothic',sans-serif;line-height:1.5\">"
        f"❄ <b>얼린 보고서 사본</b> · {_esc(owner)} ({_esc(who)}) · 기간 {_esc(d0)} ~ {_esc(d1)} · "
        f"{ts} 생성"
        + (" · <b>스텁 판정(테스트 전용 — 실제 Copilot 판정 아님)</b>" if stub else "") + "<br>"
        f'<span style="opacity:.8">사내 전용 · {mode_txt} · 파일 하나로 열리는 읽기 전용 '
        "화면입니다 — 실행·수집·업로드 버튼은 동작하지 않습니다.</span></div>")

    data_txt = json.dumps(baked, ensure_ascii=False).replace("<", "\\u003c")
    inj = ('<script type="application/json" id="lm-frozen-data">' + data_txt
           + "</script>\n<script>" + INTERCEPT_JS + "</script>\n" + banner)
    mb = re.search(r"<body[^>]*>", html)
    pos = mb.end() if mb else 0
    out = html[:pos] + inj + html[pos:]
    out = re.sub(r"<title>[^<]*</title>",
                 f"<title>LoadMonitor 얼린 보고서 {_esc(owner)} {d0}~{d1}</title>", out, count=1)

    made = []
    name = _safe_name(f"LoadMonitor_보고서_{d0}_{d1}_{host or 'PC'}"
                      f"_{time.strftime('%Y%m%d_%H%M')}{'' if full else '_요약'}.html")
    try:
        os.makedirs(FREEZE_DIR, exist_ok=True)
        made.append(_write_atomic(os.path.join(FREEZE_DIR, name), out))
        _prune_frozen(made[-1])
    except OSError as e:
        log(f"    [!] 저장 실패({type(e).__name__}) — report 폴더 권한·잠금을 확인하세요.")
    try:
        # 고정 이름 — 공유폴더 배치(teamup --to-folder)가 이 이름을 찾는다. 재실행 시 갈아끼운다.
        # 요약본(full=False)은 _요약 이름으로 따로 — 원문본 고정명을 요약본으로 덮지 않는다(검증 확정).
        made.append(_write_atomic(os.path.join(REPORT, f"보고서_{tag}{'' if full else '_요약'}.html"), out))
    except OSError as e:
        log(f"    [!] 고정명 사본 저장 실패({type(e).__name__})")
    for p in made:
        log(f"    → {p}{_size_txt(p)}")
    return made


# ══ ② 개인 분석 리포트 (HTML 한 장) ═════════════════════════════════════════
# 얼린 보고서(대시보드 통째)와 달리, 분석 '결과'만 읽기 좋게 정리한 한 장.
# 팀 취합이 이 파일의 데이터 섬(lm-report-data)을 모아 팀 워크플로우를 분석한다.

def _read_rows(tag):
    plain = os.path.join(REPORT, f"mm_rows_{tag}.csv")
    ref = os.path.join(REPORT, f"mm_rows_{tag}_refined.csv")
    p = plain
    try:
        if os.path.exists(ref) and (not os.path.exists(plain)
                                    or os.path.getmtime(ref) >= os.path.getmtime(plain)):
            p = ref
    except OSError:
        p = ref if os.path.exists(ref) else plain
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(p, encoding=enc) as f:
                return list(csv.DictReader(f)), os.path.basename(p)
        except UnicodeDecodeError:
            continue
        except (OSError, csv.Error):
            return [], ""
    try:
        with open(p, encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f)), os.path.basename(p)
    except (OSError, csv.Error):
        return [], ""


def _apply_details(rows, log=_say):
    """세부업무 대표 이름 병합(core/details) — 모듈이 아직 없거나 깨져도 리포트는 만든다"""
    try:
        import details  # core/details.py
    except ImportError:
        return rows, 0
    try:
        amap = details.load_detail_aliases() or {}
        if amap:
            details.apply_detail_map(rows, None, amap)
        before = len(rows)
        rows = details.merge_report_rows(rows)
        return rows, before - len(rows)
    except Exception as e:  # noqa: BLE001 - 병합 실패가 리포트를 막지 않게
        log(f"    [!] 세부업무 병합 건너뜀({type(e).__name__}: {str(e)[:80]})")
        return rows, 0


# 시각 규칙: 잉크는 글자 토큰, 시리즈 색은 표식에만. agent 가능성은 색 + 항상 글자 라벨.
# 원본 대시보드(ui/app.py AGENT_C)와 같은 색
_AGENT_C = {"상": "#1d8a4a", "중": "#c98a00", "하": "#8b929b"}
_PAL = ["#2a78d6", "#0e8c7a", "#a61b4a", "#e08a00", "#6c4fb8", "#3d8f3d",
        "#c05a78", "#4a7f9e", "#8a6d3b", "#556270"]


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


_TOOL_NOTE = "참고 지표 — 투입 MM·로드율과 무관 · 실행 기록은 Windows 가 사용자 계정에 남긴 실행 흔적(관리자 권한 불필요)"


def _tool_usage_html(tu):
    """프로그램 사용(참고) 조각 — 새 meta(출처·실행 횟수·포커스 시간·마지막 실행·파일 일수 + 자체·프로토타입(추정))와
    옛 meta(창기록만 — src·runs 칸 없음) 둘 다 그린다. 비면 ''(이유가 있으면 이유 한 줄).
    ★ 참고 지표라는 문구를 늘 붙인다 — 안 그러면 '투입 시간' 으로 읽힌다(core/programs.py 머리말). 값은 전부 _esc 를 거친다."""
    tu = tu if isinstance(tu, dict) else {}
    progs = [x for x in (tu.get("programs") or []) if isinstance(x, dict) and x.get("name")]
    inh = [x for x in (tu.get("inhouse") or []) if isinstance(x, dict) and x.get("name")]
    hidden = int(_num(tu.get("inhouse_hidden")))
    if not progs and not inh and not hidden:
        why = str(tu.get("why") or "").strip()
        return f"<div class='note'><b>프로그램 사용(참고)</b> <span class='dim'>{_esc(why)}</span></div>" if why else ""

    def cnt(v, c):          # 증가분을 모르면(스냅샷 1장) 누적으로 — 지어내지 않는다
        if v is None:
            return "–" if c is None else f"<span class='dim'>누적 {int(_num(c)):,}</span>"
        return f"{int(_num(v)):,}회"

    def hrs(v, c):
        if v is None:
            return f"<span class='dim'>누적 {_num(c):.1f}h</span>" if _num(c) else "–"
        return f"{_num(v):.1f}h"

    def side(x):            # 창기록(옛 샘플러) 시간 — 전면 0h · 배경만 있는 솔버는 '배경 Nh'(0.0h 로 적으면 안 쓴 것처럼 읽힌다)
        h, bg = _num(x.get("hours")), _num(x.get("bg_hours"))
        if h >= 0.05:
            return f"{h:.1f}h" + (f"<span class='dim'>(배경 {bg:.0f}h)</span>" if bg >= 1 else "")
        return f"<span class='dim'>배경 {bg:.0f}h</span>" if bg >= 1 else "–"

    rows = []
    for x in progs[:25]:
        src = x.get("src") if isinstance(x.get("src"), list) else ["창기록"]
        kc = _esc(x.get("kind")) + (f" · {_esc(x.get('cat'))}" if x.get("cat") else "")
        fd = int(_num(x.get("file_days")))
        rows.append(f"<tr><td><b>{_esc(x['name'])}</b></td><td class='dim'>{kc}</td>"
                    f"<td class='dim'>{_esc('·'.join(str(s) for s in src))}</td>"
                    f"<td>{cnt(x.get('runs'), x.get('runs_cum'))}</td><td>{hrs(x.get('focus_h'), x.get('focus_h_cum'))}</td>"
                    f"<td class='dim'>{_esc(str(x.get('last_run') or '')[:16]) or '–'}</td>"
                    f"<td>{f'{fd}일' if fd else '–'}</td><td>{side(x)}</td></tr>")
    kinds = [x for x in (tu.get("by_kind_n") or []) if isinstance(x, (list, tuple)) and len(x) >= 2]
    srcs = tu.get("sources") if isinstance(tu.get("sources"), dict) else {}
    reg = srcs.get("실행기록") if isinstance(srcs.get("실행기록"), dict) else {}
    win = reg.get("window") if isinstance(reg.get("window"), list) and len(reg.get("window")) == 2 else None
    basis = (f"실행 횟수·포커스 시간 = 실행 기록 스냅샷 {_esc(win[0])}~{_esc(win[1])} 사이 증가분"
             if reg.get("basis") == "delta" and win else
             ("실행 기록 스냅샷이 1장뿐이라 횟수·시간은 이 계정의 누적값입니다(다음 수집부터 기간 안 증가분이 보입니다)"
              if reg.get("basis") == "cum" else ""))
    h = ["<div class='note'><b>프로그램 사용(참고)</b> — " + _esc(tu.get("note") or _TOOL_NOTE)]
    if kinds:
        h.append(" · 구분 " + " · ".join(f"{_esc(k)} {int(_num(v))}개" for k, v in kinds))
    if _num(tu.get("solver_bg_h")) >= 1:
        h.append(f" · 배경 솔버 가동 {_num(tu.get('solver_bg_h')):.0f}h")
    if basis:
        h.append(f"<br><span class='dim'>{basis}</span>")
    if rows:
        h.append("<table style='margin-top:4px'><tr><th>프로그램</th><th>구분·분류</th><th>출처</th><th>실행 횟수</th>"
                 "<th>포커스 시간</th><th>마지막 실행</th><th>파일 일수</th><th>창기록</th></tr>" + "".join(rows) + "</table>")
        if len(progs) > 25:
            h.append(f"<div class='dim'>… 외 {len(progs) - 25}개</div>")
    h.append("</div>")
    if inh or hidden:
        items = " · ".join(
            f"{_esc(x['name'])} <span class='dim'>("
            + (f"{int(_num(x.get('runs')))}회" if x.get("runs") is not None else f"누적 {int(_num(x.get('runs_cum')))}회")
            + (f" · {_esc(str(x.get('last_run'))[:10])}" if x.get("last_run") else "") + ")</span>"
            for x in inh[:12])
        h.append("<div class='note'><b>자체·프로토타입(추정)</b> " + items
                 + (f" · 이름을 가린 도구 {hidden}개" if hidden else "")
                 + " <span class='dim'>— 카탈로그에 없는 실행 파일이 사용자 폴더·다른 드라이브·네트워크에서 돈 것입니다"
                   "(무료 휴대용 도구일 수도 있습니다)</span></div>")
    unk = int(_num(tu.get("unknown_n")))        # 카탈로그 밖 설치 프로그램 — 개수만(이름은 사적 앱이 섞여 싣지 않는다)
    amb = [x for x in (tu.get("ambiguous_files") or []) if isinstance(x, (list, tuple)) and len(x) >= 2]
    more = []
    if unk:
        more.append(f"카탈로그 밖 설치 프로그램 {unk}개(이름은 싣지 않습니다)")
    if amb:
        more.append("도구 불명 파일: " + " · ".join(f"{_esc(x[0])} {int(_num(x[1]))}개" for x in amb[:6]))
    if reg.get("track_off"):
        more.append("<b>앱 실행 추적이 꺼져 있습니다</b>(설정 &gt; 개인 정보 &gt; 일반 또는 회사 정책) — 실행 횟수가 늘지 않아 "
                    "안 쓴 것처럼 보일 수 있습니다")
    if more:
        h.append("<div class='note dim'>" + " / ".join(more) + "</div>")
    return "".join(h)


def report_island(tag, full=True, log=_say):
    r"""분석 리포트 HTML 한 장 → 만든 파일 경로 목록. report\ 의 결과 파일만 읽는다(서버·프로그램 불필요)."""
    if not tag:
        log("    [!] 분석 결과가 없어 만들 수 없습니다.")
        return []
    d0, d1 = tag_to_dates(tag)
    meta = _read_json(os.path.join(REPORT, f"mm_meta_{tag}.json")) or {}
    try:        # LM30(2026-10-18) — 이 파일은 공유폴더로 복사된다: 옛 사본의 이 PC 전용 칸(날짜별 시각)을 한 번 더 뗀다
        import attendance as _att
        if isinstance(meta, dict):
            _att.scrub_meta(meta)
    except ImportError:
        pass
    # 프로그램 사용(참고) — 투입 MM 과 다른 값이다(실행 흔적·파일·옛 창 기록). 그 점을 문구로 못 박는다(_tool_usage_html).
    _tu = meta.get("tool_usage")
    if not isinstance(_tu, dict):
        _tu = (meta.get("mm_basis") or {}).get("tool_usage")
    tool_note = _tool_usage_html(_tu)       # 창기록·실행기록·파일 + 자체·프로토타입(추정) — 옛 meta(창기록만)도 그린다
    rows, rows_file = _read_rows(tag)
    if not rows and not meta:
        log(f"    [!] {tag} 결과(mm_rows·mm_meta)가 없어 분석리포트를 만들지 못했습니다.")
        return []
    wf = _read_json(os.path.join(REPORT, f"workflow_{tag}.json")) or {}
    # LM29부터 — Agentic AI 니즈 후보만(팀 과제 매칭·오할당 없음). LM28 이 남긴 파일의 match·misassigned 는 섬에도 싣지 않는다.
    _ag = _read_json(os.path.join(REPORT, f"agentic_{tag}.json"))
    _ag = _ag if isinstance(_ag, dict) else {}
    ag_new =[n for n in (_ag.get("new") if isinstance(_ag.get("new"), list) else []) if isinstance(n, dict)]
    if not full:
        wf = _strip_evidence(wf)
        ag_new = _strip_evidence(ag_new)
    owner, host = _owner(), _host()

    rows, n_merged = _apply_details(rows, log)
    for r in rows:
        r["mm"] = round(_num(r.get("mm")), 2)
    rows.sort(key=lambda r: -r["mm"])
    total = round(sum(r["mm"] for r in rows), 2)
    avail = meta.get("avail_mm")
    pct = meta.get("load_pct")
    if pct is None and avail:
        try:
            pct = round(total / float(avail) * 100)
        except (TypeError, ValueError, ZeroDivisionError):
            pct = None

    def _snap_l1(v):        # 옛 정제본의 스냅 전 값(기술내재화 등)을 새 이름으로 접어 표시(제보 ③)
        try:
            import details
            return details.snap1(v) or (v or "")
        except Exception:  # noqa: BLE001
            return v or ""
    mmax = max([r["mm"] for r in rows] or [1]) or 1
    row_html = "".join(
        f"<tr><td>{_esc(_snap_l1(r.get('Level 1')))}</td><td>{_esc(r.get('유형'))}</td>"
        f"<td><b>{_esc(r.get('Level 2'))}</b></td><td>{_esc(r.get('Level 3'))}</td>"
        f"<td class='desc'>{_esc(r.get('상세설명'))}</td>"
        f"<td class='num'><b>{r['mm']:.2f}</b></td>"
        f"<td style='width:100px'><span class='mmbar' "
        f"style='width:{max(2, round(r['mm'] / mmax * 90))}px'></span></td></tr>"
        for r in rows[:60])

    # 과제별 MM 배분 — 대시보드의 '프로젝트 내 업무 로드'와 같은 세그먼트 바
    by_pj = {}
    for r in rows:
        k = (r.get("Level 2") or "공통")
        by_pj[k] = by_pj.get(k, 0.0) + r["mm"]
    by_pj = sorted(by_pj.items(), key=lambda kv: -kv[1])
    ptot = sum(v for _k, v in by_pj) or 1
    pj_bar = ""
    if by_pj:
        pj_bar = ('<div class="bigbar">'
                  + "".join(f'<i style="width:{v / ptot * 100:.1f}%;background:{_PAL[i % len(_PAL)]}"'
                            f' title="{_esc(k)} {v:.2f} MM"></i>'
                            for i, (k, v) in enumerate(by_pj))
                  + '</div><div class="leg">'
                  + "".join(f'<div><span class="dot" style="background:{_PAL[i % len(_PAL)]}"></span>'
                            f'{_esc(k)}<span class="v">{v:.2f} MM</span></div>'
                            for i, (k, v) in enumerate(by_pj))
                  + "</div>")

    # 담당자 워크플로우 — 화면과 같은 접이식 + 단계 표
    flows = wf.get("flows") or []
    try:                          # 읽기 경계 스냅 — 옛 workflow_*.json 의 스냅 전 상위 이름(v3 구조 감사 무스냅 통로)
        import details as _dsn
        for _fl in flows:
            if isinstance(_fl, dict) and _fl.get("level1"):
                _fl["level1"] = _dsn.snap1(_fl["level1"]) or _fl["level1"]
    except Exception:  # noqa: BLE001
        pass
    import details as _dl
    _L1C = {n: _dl.l1_color(n) for n in list(_dl.L1_META) + list(_dl.LEVEL1_ALIAS)}   # 단일원 파생
    _l1_prev = None                # 상위가 바뀌는 자리에만 머리말을 넣는다
    _pj_prev = None                # 과제(중위)가 바뀌는 자리에도 — 담당업무 카드가 자기 과제 밑에 모이게

    fl_cards = []
    for i, f in enumerate(flows):
        mm = f.get("mm") or {}
        if not isinstance(mm, dict):
            mm = {}
        det = [(k, _num(v)) for k, v in (mm.get("details") or {}).items()]
        dtot = sum(v for _k, v in det) or 1
        dbar = ""
        if det:
            dbar = ('<div class="bigbar" style="margin:4px 0">'
                    + "".join(f'<i style="width:{v / dtot * 100:.1f}%;'
                              f'background:{_PAL[j % len(_PAL)]}" title="{_esc(k)} {v} MM"></i>'
                              for j, (k, v) in enumerate(det))
                    + '</div><div class="leg">'
                    + "".join(f'<div><span class="dot" style="background:{_PAL[j % len(_PAL)]}">'
                              f'</span>{_esc(k)}<span class="v">{v} MM</span></div>'
                              for j, (k, v) in enumerate(det))
                    + "</div>")
        steps = "".join(
            f'<tr><td class="ord"><b>{_esc(s.get("order", j + 1))}</b></td>'
            f'<td class="stn"><b>{_esc(s.get("name"))}</b>'
            + (f'<div class="sub">{_esc(s.get("cycle"))}</div>' if s.get("cycle") else "")
            + f'</td><td>{_esc(s.get("desc"))}'
            + (f'<div class="sub">근거: {_esc(s.get("evidence"))}</div>'
               if s.get("evidence") else "")
            + f'</td><td class="agc"><span class="pill" '
            f'style="background:{_AGENT_C.get(s.get("agent") or "중", "#8b929b")}">'
            f'Agent {_esc(s.get("agent") or "중")}</span>'
            + (f'<div class="sub" style="color:#4a5159">{_esc(s.get("agent_how"))}</div>'
               if s.get("agent_how") else "")
            + "</td></tr>"
            for j, s in enumerate(f.get("steps") or []) if isinstance(s, dict))
        mm_txt = f"{mm.get('mm')} MM · " if isinstance(mm.get("mm"), (int, float)) else ""
        role0 = str(f.get("role") or "판단 유보").split("—")[0].strip()
        # 상위(Level 1)로도 묶어 읽히게 — 계층은 상위 > 과제 > 담당업무. flow 가 상위로 정렬해 내보낸다.
        _l1 = str(f.get("level1") or "")
        _pj = str(f.get("project") or f.get("model") or "")
        _det = str(f.get("detail") or "")
        if _l1 != _l1_prev:
            _n1 = len({str(x.get("project") or x.get("model") or "") for x in flows
                       if isinstance(x, dict) and str(x.get("level1") or "") == _l1})
            fl_cards.append('<div style="margin:14px 0 6px;font-size:12px;color:#4a5159">'
                            f'<b>{_esc(_l1 or "상위 미분류")}</b> '
                            f'<span class="dim">— {_n1}개 과제</span></div>')
            _l1_prev = _l1
            _pj_prev = None
        if _det and _pj != _pj_prev:
            _nd = sum(1 for x in flows if isinstance(x, dict)
                      and str(x.get("project") or x.get("model") or "") == _pj
                      and str(x.get("level1") or "") == _l1)
            fl_cards.append('<div style="margin:8px 0 4px 6px;font-size:13px">'
                            f'<b>{_esc(_pj)}</b> <span class="dim">— 담당 업무 {_nd}개</span></div>')
        _pj_prev = _pj
        _l1b = (f'<span style="display:inline-block;padding:0 7px;border-radius:9px;color:#fff;'
                f'font-size:11px;background:{_L1C.get(_l1, "#8b929b")};margin-right:6px">{_esc(_l1)}</span>'
                if _l1 else "")
        _ttl = (f'<span title="{_esc(_pj)}">{_esc(_det)}</span>' if _det else _esc(f.get("model")))
        fl_cards.append(
            f'<details{" open" if i == 0 else ""}{" style=margin-left:6px" if _det else ""}>'
            f'<summary>{"" if _det else _l1b}{_ttl}'
            + (f'<span class="dim"> · {_esc(f.get("branch"))}</span>' if f.get("branch") else "")
            + f'<span class="state">{mm_txt}단계 {len(f.get("steps") or [])}개 · '
            f'{_esc(role0)}</span></summary><div class="body">'
            + (('<div class="note" style="margin:2px 0 6px">'
                + ('← 앞 업무: <b>' + _esc(str(f.get("upstream")).split(" / ")[-1]) + '</b>' if f.get("upstream") else '')
                + (' &nbsp;·&nbsp; ' if (f.get("upstream") and f.get("downstream")) else '')
                + ('→ 다음 업무: <b>' + _esc(str(f.get("downstream")).split(" / ")[-1]) + '</b>' if f.get("downstream") else '')
                + '</div>') if (f.get("upstream") or f.get("downstream")) else '')
            + f'<div style="margin:2px 0 6px"><b>역할:</b> {_esc(f.get("role")) or "판단 유보"}</div>'
            + (f'<div class="note" style="margin:0 0 6px">{_esc(f.get("summary"))}</div>'
               if f.get("summary") else "")
            + dbar
            + '<table style="margin-top:6px"><tr><th></th><th>단계</th><th>무슨 일</th>'
            '<th>Agent 가능성</th></tr>' + steps + "</table></div></details>")
    flows_html = "".join(fl_cards) or (
        '<div class="card"><div class="note">워크플로우 분석이 없습니다 — '
        '대시보드 [담당자 워크플로우] 탭의 [재분석]으로 만들 수 있습니다.</div></div>')

    # 4. Agentic AI 니즈 후보 — 내 반복 업무에서 찾은 자동화 니즈(MM 없이 근거 업무 행 수만 — RP4)
    new_html = "".join(
        f'<div style="border-left:3px solid #6c4fb8;padding:4px 0 4px 12px;margin:10px 0">'
        f'<b>{_esc(n.get("name"))}</b>'
        + (f' <span class="state">근거 업무 {int(_num(n.get("evidence_rows")))}행</span>'
           if n.get("evidence_rows") is not None else "")
        + (f'<div style="font-size:12px;margin-top:3px"><b>동작 로직:</b> {_esc(n.get("logic"))}</div>'
           if n.get("logic") else "")
        + (f'<div class="sub" style="margin-top:2px"><b>발굴 사유:</b> {_esc(n.get("reason"))}</div>'
           if n.get("reason") else "")
        + ("<div style='margin-top:3px'>" + "".join(f'<span class="tag">{_esc(w)}</span>'
                                                   for w in (n.get("work") or [])[:12]) + "</div>"
           if isinstance(n.get("work"), list) and n.get("work") else "")
        + "</div>"
        for n in ag_new)
    if _ag.get("failed_chunks"):
        new_html += (f'<div class="note" style="color:#c0122f">묶음 {_esc(_ag.get("failed_chunks"))}/'
                     f'{_esc(_ag.get("chunks") or "?")}개 실패 — 후보가 실제보다 적을 수 있습니다</div>')
    ag_html = ('<div class="card"><h2>4. Agentic AI 니즈 후보 <span class="state">팀 과제와 매칭하지 않고, 반복 업무에서 '
               'Agentic AI 로 자동화할 만한 니즈만 · 근거 업무 N행 = 근거가 된 업무 행 수(MM 아님)</span></h2>'
               + (new_html or ('<div class="note">근거가 충분한 니즈 후보가 없습니다.</div>' if _ag else
                               '<div class="note">니즈 후보 발굴 결과가 없습니다 — 대시보드 [Agentic AI] 탭의 '
                               '[니즈 후보 발굴 실행]으로 만들 수 있습니다.</div>'))
               + "</div>")

    # LM28(WP9): 초과근무 세분·미관측 · 산출 방식(PC 가동 하한의 근거·날짜별 방식) · 동료 · 연관 업무 · 업무 영역·과제
    # 워크플로 요약(단위업무 등급) — 리포트(report_out)와 같은 함수. 요약판(--summary)은 동료 이름을 [사람] 으로.
    extra_html = ""
    try:
        import report_out as _ro
        _b = meta.get("mm_basis") if isinstance(meta.get("mm_basis"), dict) else {}
        _ot = _ro.overtime_rows(meta, _b)
        if _ot:
            extra_html += ('<div class="card"><h2>5. 근무 꼬리표 · 초과근무 세분 · 미관측</h2><table>'
                           + "".join(f"<tr><th style='width:260px'>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in _ot)
                           + "</table></div>")
        # LM30v1(2026-10-19) 법정 채움 MM — 리포트 1절과 같은 함수(legal_section). 분석리포트는 공유폴더로 복사되므로 달 합계만
        # (local=None — 근태 기록 시간·+@ 나눔과 표시 날짜는 싣지 않는다)
        _lg = _ro.legal_section(meta, _b, None, head="<h2>MM 산정 근거 — 달 합계(1MM = 그달 평일 × 8시간 · 법정 채움)</h2>")
        if _lg:
            extra_html += '<div class="card">' + "\n".join(_lg) + "</div>"
        # LM30(2026-10-18) 출퇴근·시간외 근무 — 리포트 §8 과 같은 함수. 분석리포트는 공유폴더(개인리포트\)로 복사되므로 날짜별
        # 출근·퇴근·평소 시각은 싣지 않는다(per_day=False — attendance 파일은 넘기지 않고 mm_meta 의 주·달 합계만)
        _as = _ro.attendance_section(meta, _b, None, per_day=False)
        if _as:
            extra_html += '<div class="card">' + "\n".join(_as) + "</div>"
        extra_html += '<div class="card">' + "\n".join(_ro.floor_section(meta, _b)) + "</div>"
        _sig = _ro._rows(os.path.join(REPORT, f"signals_{tag}.csv"))
        _pv = _read_json(os.path.join(REPORT, f"pivots_{tag}.json")) or {}
        extra_html += ('<div class="card">'
                       + "\n".join(_ro.new_sections(_sig, wf, rows, _pv, summary=not full, ctx=_ro._privacy_ctx(), n0=6))
                       + "</div>")
    except Exception as e:  # noqa: BLE001 - 새 절의 실패가 분석리포트를 막지 않는다
        log(f"    [!] 분석리포트 보조 절 건너뜀({type(e).__name__}: {str(e)[:80]})")

    generated = time.strftime("%Y-%m-%d %H:%M")
    stub = _is_stub()
    # 데이터 섬 — 팀 취합(팀보완툴·LM22 팀 취합)이 읽는 계약: kind/owner/host/period/tag/rows/workflow/agentic
    # LM29부터: 계약 키 "agentic" 에는 니즈 후보만 싣는다 — {"kind": "needs", "new": [...]}(과제 매칭·오할당 없음).
    # stub: 판정이 스텁(LM_COPILOT_STUB, 테스트 전용)이었던 결과 — 취합이 실자료와 구분한다.
    island = json.dumps({
        "kind": "lm-personal-report", "owner": owner, "host": host,
        "period": [d0, d1], "tag": tag, "total_mm": total,
        "avail_mm": avail, "load_pct": pct, "rows_file": rows_file,
        "rows": rows, "workflow": wf, "agentic": {"kind": "needs", "new": ag_new},
        "generated": generated, "generator": "LoadMonitor30v1 freeze.py",
        "merged_rows": n_merged, "full": bool(full), "stub": stub},
        ensure_ascii=False).replace("<", "\\u003c")
    stub_txt = " · <b>스텁 판정(테스트 전용 — 실제 Copilot 판정 아님)</b>" if stub else ""

    pct_txt = "–" if pct is None else f"{pct}%"
    top_pj = by_pj[0][0] if by_pj else "—"
    avail_txt = "–" if avail is None else format(_num(avail), ".2f")
    # LM30v1(2026-10-19) 법정 채움 MM 이면 가용은 휴가를 빼지 않은 '지난 평일의 비율'이다(휴가는 투입에 법정 시간으로 채운다)
    try:
        import attendance as _att_k
        avail_nt = "지난 평일의 비율(휴가는 채움)" if _att_k.mm_rule_of(meta) == "legal" else "연차·휴가 차감"
    except ImportError:
        avail_nt = "연차·휴가 차감"
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>업무 분석 리포트 — {_esc(owner)} {d0}~{d1}</title><style>
body{{font:13px/1.55 'Malgun Gothic','Segoe UI',sans-serif;color:#2c333b;background:#f4f6f8;margin:0}}
.wrap{{max-width:1080px;margin:0 auto;padding:16px 20px 60px}}
h1{{font-size:18px;margin:10px 0 2px;color:#1c232b}}
.card{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:16px;margin-bottom:12px}}
.card h2{{font-size:13px;margin:0 0 10px;color:#2c333b}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:12px}}
.kpi{{background:#fff;border:1px solid #e4e7eb;border-radius:8px;padding:12px 14px}}
.kpi .lb{{font-size:10.5px;color:#8b929b}}
.kpi .vl{{font-size:21px;font-weight:800;margin:2px 0;letter-spacing:-0.5px}}
.kpi .nt{{font-size:10.5px;color:#5a626b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:520px){{.kpis{{grid-template-columns:1fr}}.wrap{{padding:12px}}}}
.state{{font-size:12px;color:#5a626b;font-weight:400;margin-left:8px}}
.note{{font-size:10.5px;color:#8b929b;margin-top:8px;line-height:1.6}}
.dim{{color:#8b929b;font-size:11.5px}}
.sub{{color:#8b929b;font-size:11px}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.leg{{font-size:11px;color:#4a5159;line-height:1.9}}
.leg .v{{float:right;font-weight:700}}
.bigbar{{height:26px;border-radius:5px;overflow:hidden;display:flex;margin:6px 0 10px}}
.bigbar i{{display:block;height:100%}}
details{{margin-bottom:12px}}
details summary{{cursor:pointer;font-size:13px;font-weight:700;color:#2c333b;padding:12px 16px;
background:#fff;border:1px solid #e4e7eb;border-radius:8px;list-style:none}}
details summary::-webkit-details-marker{{display:none}}
details summary::before{{content:"▸ ";color:#8b929b}}
details[open] summary{{border-radius:8px 8px 0 0}}
details[open] summary::before{{content:"▾ "}}
details .body{{background:#fff;border:1px solid #e4e7eb;border-top:0;border-radius:0 0 8px 8px;
padding:14px 16px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:#f6f8fa;color:#3d4a5c;text-align:left;padding:6px 8px;font-weight:700;
border-bottom:2px solid #e4e7eb;font-size:11px}}
td{{padding:6px 8px;border-bottom:1px solid #eef0f3;vertical-align:top}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.ord{{width:26px;text-align:center;color:#8b929b}}
td.stn{{width:170px}} td.agc{{width:210px}} td.desc{{max-width:300px}}
.pill{{display:inline-block;padding:1px 8px;border-radius:9px;color:#fff;font-size:11px}}
.tag{{display:inline-block;background:#f0f3f7;border-radius:3px;padding:1px 7px;
margin:1px 3px 1px 0;font-size:10.5px;color:#3d444c}}
.mmbar{{display:inline-block;height:9px;border-radius:4px;background:#2a78d6;vertical-align:middle}}
.top{{background:#1c2b3a;color:#fff;padding:9px 14px;font-size:12px}}
</style></head><body>
<div class="top">개인 업무 분석 리포트 · {_esc(owner)}@{_esc(host)} · {d0} ~ {d1} ·
{generated} 생성 · 사내 전용 — 팀 취합용 데이터 포함{stub_txt}</div>
<div class="wrap">
<h1>{_esc(owner)} — 업무 로드 분석</h1>
<div class="dim">근거 {_esc(rows_file) or '(결과 행 없음)'} · 신호 {_esc(meta.get('signals'))}건
{(' · 같은 업무 ' + str(n_merged) + '행 병합') if n_merged else ''}</div>

<div class="kpis" style="margin-top:10px">
<div class="kpi"><div class="lb">로드율 (투입 ÷ 가용)</div><div class="vl">{pct_txt}</div>
<div class="nt">야근은 상한 없이 반영</div></div>
<div class="kpi"><div class="lb">투입 MM</div><div class="vl">{total:.2f}</div>
<div class="nt">주력 {_esc(top_pj)}</div></div>
<div class="kpi"><div class="lb">가용 MM</div><div class="vl">{avail_txt}</div>
<div class="nt">{avail_nt}</div></div>
<div class="kpi"><div class="lb">업무 항목</div><div class="vl">{len(rows)}</div>
<div class="nt">과제 {len(by_pj)}개</div></div>
</div>

<div class="card"><h2>1. 과제별 업무 로드 <span class="state">과제별 MM 배분</span></h2>
{pj_bar or '<div class="note">표시할 배분이 없습니다</div>'}{tool_note}</div>

<div class="card"><h2>2. 업무별 상세 <span class="state">MM 순 · 업무 영역 / 과제 / 세부업무 / 업무분류</span></h2>
<table><tr><th style="width:70px">업무 영역</th><th style="width:52px">업무분류</th>
<th style="width:140px">과제</th><th style="width:120px">세부업무</th><th>상세설명</th>
<th class="num" style="width:52px">MM</th><th></th></tr>{row_html}</table></div>

<h1 style="font-size:15px;margin:18px 0 8px">3. 담당자 워크플로우
<span class="state">역할 → 일의 순서 → 단계별 Agent 가능성</span></h1>
{flows_html}

{ag_html}
{extra_html}

<div class="note">이 파일 하나로 공유됩니다. 팀 취합 분석은 아래 데이터 섬을 읽어 수행합니다.</div>
</div>
<script type="application/json" id="lm-report-data">{island}</script>
</body></html>"""

    made = []
    sfx = "" if full else "_요약"      # 요약본은 고정명(원문본)을 덮지 않는다 — 얼린 보고서와 같은 규칙
    try:
        made.append(_write_atomic(os.path.join(REPORT, f"분석리포트_{tag}{sfx}.html"), doc))
    except OSError as e:
        log(f"    [!] 분석리포트 저장 실패({type(e).__name__})")
    try:
        os.makedirs(FREEZE_DIR, exist_ok=True)
        name = _safe_name(f"LoadMonitor_분석리포트_{d0}_{d1}_{host or 'PC'}_{time.strftime('%Y%m%d_%H%M')}{sfx}.html")
        made.append(_write_atomic(os.path.join(FREEZE_DIR, name), doc))
        _prune_frozen(made[-1])
    except OSError as e:
        log(f"    [!] 분석리포트 사본 저장 실패({type(e).__name__})")
    for p in made:
        log(f"    → {p}")
    return made


# ══ ③ 리포트 (Word 친화, report_out.py) ═════════════════════════════════════
def report_word(tag, log=_say):
    r"""report_out.build(tag) → report\리포트_<기간>.html / .doc → 만든 파일 경로 목록"""
    try:
        import report_out
    except ImportError as e:
        log(f"    [!] report_out.py 를 불러오지 못했습니다: {e}")
        return []
    try:
        doc = report_out.build(tag)
    except Exception as e:  # noqa: BLE001 - 리포트 한 종의 실패가 나머지를 막지 않게
        log(f"    [!] 리포트 생성 실패: {type(e).__name__}: {str(e)[:120]}")
        return []
    if not doc:
        log(f"    [!] mm_meta_{tag}.json 이 없어 리포트를 만들지 못했습니다.")
        return []
    made = []
    for ext in ("html", "doc"):          # .doc 은 같은 내용 — 더블클릭하면 Word 로 열린다
        p = os.path.join(REPORT, f"리포트_{tag}.{ext}")
        try:
            made.append(_write_atomic(p, doc))
        except OSError as e:
            log(f"    [!] {os.path.basename(p)} 저장 실패({type(e).__name__}) — 열려 있으면 닫고 다시")
    for p in made:
        log(f"    → {p}")
    return made


# ══ 묶음 ════════════════════════════════════════════════════════════════════
def make_all(tag, base_url=None, full=True, log=_say, want=("word", "island", "freeze")):
    """보고서 3종(리포트·분석리포트·얼린 보고서) → {"ok","files","tag","made","errors"}.
    ok = 요청한 것을 전부 만들었을 때. 일부만 되면 ok=False 에 files 는 채워진다(partial=True)."""
    tag = tag or latest_tag()
    if not tag:
        return {"ok": False, "files": [], "tag": "", "made": {}, "errors": ["분석 결과가 없습니다"],
                "error": "no result", "hint": "report 폴더에 분석 결과가 없습니다 — 먼저 [분석 실행]"}
    files, made, errors = [], {}, []
    finfo = {}          # freeze() 가 '화면 기간 ≠ 요청 기간' 을 여기에 남긴다
    # 각 종은 파일 2개(본체 + 사본/.doc)를 만든다 — 한쪽만 되면 '일부만' 으로 알린다
    steps = [("word", "리포트(Word)", 2, lambda: report_word(tag, log)),
             ("island", "분석리포트", 2, lambda: report_island(tag, full, log)),
             ("freeze", "얼린 보고서", 2, lambda: freeze(tag, full, base_url, log, info=finfo))]
    with _MAKE_LOCK:    # 같은 프로세스의 동시 호출은 줄을 선다 — 같은 고정명을 서로 갈아끼우지 않게
        for key, label, n_expect, fn in steps:
            if key not in want:
                continue
            log(f"  · {label}")
            try:
                got = fn() or []
            except Exception as e:  # noqa: BLE001 - 한 종의 예외가 나머지를 막지 않게
                log(f"    [!] {label} 실패: {type(e).__name__}: {str(e)[:120]}")
                got = []
            made[key] = got
            files += got
            if not got:
                errors.append(f"{label} 실패")
            elif len(got) < n_expect:
                errors.append(f"{label} 일부만 저장({len(got)}/{n_expect})")
            if key == "freeze" and finfo.get("mismatch"):
                # 요청 기간의 고정명은 만들지 않았다 — ok:false(partial) 로 알리고 missing 에 이름을 명시한다
                errors.append(f"{label}: 화면 기간({finfo['shown']})이 요청 기간({tag})과 달라 화면 기간으로만 "
                              f"저장 — {', '.join(finfo.get('missing') or [])} 미생성"
                              + (f"(낡은 사본 삭제 실패: {finfo['stale_left']})" if finfo.get("stale_left") else ""))
    r = {"ok": not errors and bool(files), "files": files, "tag": tag, "made": made,
         "errors": errors, "partial": bool(errors) and bool(files)}
    if finfo.get("mismatch"):
        r["missing"] = list(finfo.get("missing") or [])
        r["shown_tag"] = finfo.get("shown", "")
    if errors:
        r["error"] = " / ".join(errors)
        if finfo.get("mismatch"):
            r["hint"] = (f"대시보드는 가장 최근 결과({finfo['shown']})를 보여 줍니다 — 요청 기간({tag})의 얼린 보고서가 "
                         "필요하면 그 기간을 다시 [분석 실행] 한 뒤 만드세요")
        else:
            r["hint"] = ("나머지는 만들었습니다 — 열려 있는 파일을 닫고 다시 만들면 됩니다" if files else
                         "report 폴더 권한·잠금(열린 HTML)과 ui\\app.py 를 확인하세요")
    return r


def _arg(flag, d=""):
    if flag not in sys.argv:
        return d
    i = sys.argv.index(flag) + 1
    if i >= len(sys.argv) or sys.argv[i].startswith("--"):
        return d
    return sys.argv[i]


def main():
    d0, d1 = _arg("--from"), _arg("--to")
    tag = tag_of(d0, d1) if (d0 and d1) else latest_tag()
    if not tag:
        print("[freeze] 분석 결과가 없습니다 — 먼저 [분석 실행]")
        print(json.dumps({"ok": False, "error": "no result", "files": [], "tag": ""}, ensure_ascii=False))
        return 1
    want = [k for k, fl in (("freeze", "--freeze"), ("island", "--island"), ("word", "--word"))
            if fl in sys.argv]
    if not want or "--all" in sys.argv:
        want = ["word", "island", "freeze"]
    full = "--summary" not in sys.argv
    base_url = _arg("--base-url")
    print(f"[freeze] {tag} · {', '.join(want)}" + ("" if full else " · 요약(원문 제외)"))
    r = make_all(tag, base_url=base_url or None, full=full, want=tuple(want))
    print(f"[freeze] 만든 파일 {len(r['files'])}개" + (f" · {r['error']}" if r.get("error") else ""))
    print(json.dumps(r, ensure_ascii=False))
    if r["ok"]:
        return 0
    return 2 if r["files"] else 1


if __name__ == "__main__":
    sys.exit(main())
