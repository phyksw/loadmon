# -*- coding: utf-8 -*-
r"""명령 분배 — ``lm27 <명령>`` = ``"<ROOT>\python\python.exe" "<ROOT>\lm27_cli.py" <명령>``(계약 §7.1·§8.3).

  · 계약 §7.1 의 모든 명령을 정의하고, 각 명령은 소유 모듈의 계약 함수를 **지연 import** 로 부른다
    (``--help`` 는 어떤 하위 모듈도 import 하지 않는다). 대상 모듈·함수가 아직 없으면 ImportError 를 삼키지 않고
    ``find_spec`` 으로 먼저 확인해 rc 1 과 한국어 한 줄로 끝낸다.
  · 모든 명령은 rc 를 돌려준다: 0 성공 · 1 내부 오류 · 2 부분/사람 조치 · 3 환경 실패 · 4 할 일 없음(§8.3).
  · 화면이 띄우는 하위 명령은 끝에 ``--job <job_id> --events jsonl`` 을 붙인다 — 모든 명령이 받는다.
    ``--events jsonl`` 이면 표준 출력은 한 줄 JSON 이벤트(§8.6)만, 사람용 문구는 stderr.
  · ``bridge …`` 는 나머지 인자를 그대로 ``lm27.bridge.cli.main(argv)`` 에 넘긴다(``--job``·``--events`` 는 여기서 소비).
  · 예외 메시지는 원문이 섞일 수 있어 출력하지 않는다 — 예외 유형과 코드 위치(파일:줄)만.
"""
import argparse
import dataclasses
import importlib
import importlib.util
import json
import os
import re
import sys
import traceback
from datetime import date, datetime

from lm27 import LM27_VERSION
from lm27.util import events

RC_OK, RC_FAIL, RC_PARTIAL, RC_ENV, RC_NOOP = 0, 1, 2, 3, 4

_DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_JOB_RX = re.compile(r"^j\d{14}[0-9a-f]{4}$")
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_UNIT_RX = re.compile(r"^u_[0-9a-f]{10}$")
_NEED_RX = re.compile(r"^n_[0-9a-f]{6}$")
_ITEM_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,159}$")
_STAGE_ID_RX = re.compile(r"^[a-z][a-z_]*(?::[a-z][a-z_]*)?$")
_LOGICAL_RX = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]{1,40}$")

EXPORT_FORMATS = ("html", "csv", "json")
EXPORT_VARIANTS = ("full", "redacted")
# report ai-items --stage(WP-30 이 ai_in 을 쓰는 단계 — task_label 은 hier 쪽 단계라 여기 없다, W2 통합 WP-30 CR)
AI_ITEM_STAGES = ("workflow_label", "agentic_match", "subagent_review", "review_text")
# analyze --period-source(R RP8 기간 출처 — 화면 값, 'rerun' 은 파이프라인이 스스로 붙인다)
PERIOD_SOURCES = ("default", "this_month", "last_month", "this_year", "user")
# team send --trigger(TAB §2.8 재시도 계기 — 화면 기동·15분 타이머. collect·build 는 각 명령이 스스로 건다)
SEND_TRIGGERS = ("manual", "startup", "timer")

# 최상위 명령(계약 §7.1 표 순서) — --help 와 시험이 이 표를 쓴다
COMMANDS = (
    ("collect", "[수집] 한 번 — --auto 는 무질문 + 끝에 대기 업로드 전송"),
    ("agent", "에이전트 설치·확인·복구·제거(install [--only] [--reinstall] · status · repair · uninstall [--purge])"),
    ("bundle", "번들 관리(status · verify · merge <dir> · alias <pc_id> <logical> · unalias <pc_id> · redact)"),
    ("move-prepare", "이동 준비(도우미 PS 를 임시 폴더 사본으로 띄움)"),
    ("analyze", "분석 파이프라인(--from D --to D 또는 --rerun <run_id> --stages <ids>)"),
    ("report", "보고서(build · export · ai-items)"),
    ("bridge", "코파일럿 브리지(run · probe · calibrate · diagnose · manual-export · manual-import · replay · unlock)"),
    ("ui", "로컬 앱(127.0.0.1) — --check 는 기동 가능 여부만 확인"),
    ("team", "팀 묶음(build · list · preview · approve · send · drop · mask · drop-need · export · ping · registry-fetch)"),
    ("team-server", "팀 서버"),
    ("team-aggregate", "재취합(서버 하위 프로세스)"),
    ("team-import", "오프라인 묶음 반입"),
    ("team-firewall-diag", "방화벽 진단"),
    ("selftest", "정제 회귀 말뭉치 관문(selftest privacy [--update-lock])"),
)

_EPILOG = ("종료 코드: 0 성공 · 1 내부 오류 · 2 부분 성공/사람 조치 필요 · 3 환경 실패 · 4 할 일 없음.\n"
           "화면이 띄우는 하위 명령은 끝에 --job <job_id> --events jsonl 을 붙인다.")


# ── 오류·출력 ────────────────────────────────────────────────────────────────
class CliError(Exception):
    """사용자에게 한국어 한 줄로 보여 주고 rc 로 끝낼 오류."""

    def __init__(self, msg: str, rc: int = RC_FAIL):
        super().__init__(msg)
        self.msg = msg
        self.rc = rc


class _Exit(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


class _Parser(argparse.ArgumentParser):
    """argparse 의 sys.exit 를 예외로 바꾼다(--help = rc 0, 인자 오류 = rc 1)."""

    def error(self, message):
        raise CliError(f"인자 오류: {message} ({self.prog} --help 참고)", RC_FAIL)

    def exit(self, status=0, message=None):
        if message:
            _err(message.rstrip())
        raise _Exit(status)


class _NullIO:
    """pythonw 처럼 표준 스트림이 없을 때의 빈 출력."""

    def write(self, s):
        return len(s)

    def flush(self):
        pass


def _err(msg: str) -> None:
    st = sys.stderr
    if st is not None:
        st.write(msg + "\n")
        st.flush()


def _fail(msg: str) -> None:
    _err("[!] " + msg)
    if events.mode() == "jsonl":
        events.emit("warn", text_ko=msg)


def _jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj)


def _show(obj, *, text=True) -> None:
    """명령 결과를 보인다 — jsonl 이면 ``result`` 이벤트, 아니면(``text=True`` 일 때만) stdout 에 JSON.
    실행형 명령(설치·합치기·전송 등)은 ``text=False`` — 사람용 출력은 소유 모듈의 이벤트·안내가 맡는다."""
    data = _jsonable(obj)
    if events.mode() == "jsonl":
        events.emit("result", data=data)
        return
    if not text:
        return
    st = sys.stdout
    if st is not None:
        st.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n")
        st.flush()


def rc_of(result, default: int = RC_OK) -> int:
    """계약 함수의 반환값 → rc. int(0~4) · bool · ``rc`` 키/속성 · 에이전트 상태 dict(healthy) 를 안다."""
    if result is None:
        return default
    if isinstance(result, bool):
        return RC_OK if result else RC_FAIL
    if isinstance(result, int):
        return result if 0 <= result <= 4 else RC_FAIL
    rc = result.get("rc") if isinstance(result, dict) else getattr(result, "rc", None)
    if isinstance(rc, int) and not isinstance(rc, bool):
        return rc if 0 <= rc <= 4 else RC_FAIL
    if isinstance(result, dict) and isinstance(result.get("healthy"), bool):
        return RC_OK if result["healthy"] else RC_PARTIAL
    return default


# ── 지연 import ──────────────────────────────────────────────────────────────
def module_present(modname: str) -> bool:
    """모듈(과 그 부모 패키지)이 트리에 있는가 — import 하지 않고 ``find_spec`` 으로 한 단계씩 본다."""
    parts = modname.split(".")
    for i in range(1, len(parts) + 1):
        if importlib.util.find_spec(".".join(parts[:i])) is None:
            return False
    return True


def resolve(modname: str, attr: str):
    """계약 함수를 지연 import 로 얻는다. 없으면 CliError(rc 1, 한국어 한 줄)."""
    if not module_present(modname):
        raise CliError(f"이 명령의 모듈({modname})이 아직 이 판에 없습니다 — 이 명령은 아직 쓸 수 없습니다", RC_FAIL)
    mod = importlib.import_module(modname)
    fn = getattr(mod, attr, None)
    if fn is None:
        raise CliError(f"{modname}.{attr} 가 아직 없습니다 — 이 명령은 아직 쓸 수 없습니다", RC_FAIL)
    return fn


# ── 실행 문맥 ────────────────────────────────────────────────────────────────
class Ctx:
    """명령 하나의 실행 문맥: 인자 · 경로 · (필요할 때만) 설정 · PC 식별."""

    def __init__(self, args, paths=None):
        self.args = args
        self._paths = paths
        self._cfg = None
        self._ident = None

    @property
    def paths(self):
        if self._paths is None:
            from lm27.paths import Paths
            self._paths = Paths()
        return self._paths

    def cfg(self, overrides=None):
        """``lm27.config.load_config(paths)``. 명령줄 덮어쓰기가 있으면 ``overrides=`` 로 넘긴다(CR — 계약 §2.1 보강).

        명령줄 값은 **엄격**하다: 레지스트리 범위·형식(``lm27.config.check_value``)에 어긋나면 기본값으로 조용히 바꾸지
        않고 rc 1 로 끝낸다 — '--host 오타' 가 0.0.0.0(모든 인터페이스) 바인드로, '--port 1000' 이 9310 으로 바뀌어
        rc 0 으로 도는 일을 막는다(config.json 의 '기본값 + 경고' 규칙은 개인 설정 파일에만)."""
        if self._cfg is None or overrides:
            load = resolve("lm27.config", "load_config")
            ov = {k: v for k, v in (overrides or {}).items() if v is not None}
            if ov:
                check = resolve("lm27.config", "check_value")
                for k, v in ov.items():
                    why = check(k, v, path=self.paths.settings_registry())
                    if why:
                        raise CliError(f"{_FLAG_OF.get(k, k)}: {why} — 명령줄 값은 기본값으로 바꾸지 않습니다", RC_FAIL)
            cfg = load(self.paths, overrides=ov) if ov else load(self.paths)
            bad = [w for w in getattr(cfg, "config_warnings", ()) if isinstance(w, dict) and w.get("key") in ov]
            if bad:
                w = bad[0]
                raise CliError(f"{_FLAG_OF.get(w['key'], w['key'])}: {w.get('text_ko', '설정 값 오류')}", RC_FAIL)
            self._cfg = cfg
        return self._cfg

    def ident(self):
        if self._ident is None:
            from lm27.bundle.ids import identify_pc
            self._ident = identify_pc(self.paths)
        return self._ident

    def bundle_lock(self, purpose: str):
        lock = resolve("lm27.bundle.lock", "BundleLock")
        return lock(self.paths, purpose, self.cfg()["bundle.lockTimeoutSec"])


# ── 인자 형 ──────────────────────────────────────────────────────────────────
def _date_arg(s: str) -> str:
    if not _DATE_RX.match(s or ""):
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD")
    try:
        date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("없는 날짜입니다") from None
    return s


def _ts_arg(s: str) -> str:
    try:
        datetime.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("시각은 ISO 8601(예 2026-10-05T18:00:00+09:00)") from None
    return s


def _rx_arg(rx, what):
    def f(s):
        if not isinstance(s, str) or not rx.match(s):
            raise argparse.ArgumentTypeError(f"{what} 형식이 아닙니다")
        return s
    f.__name__ = what
    return f


def _port_arg(s: str, lo: int = 1) -> int:
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("포트는 정수") from None
    if not lo <= n <= 65535:
        raise argparse.ArgumentTypeError(f"포트 범위는 {lo}~65535")
    return n


def _bind_port_arg(s: str) -> int:
    """듣는 포트(ui·team-server) — 레지스트리 ``ui.port``·``teamServer.bindPort`` 범위 1024~65535 와 같게.
    (--help 가 lm27.config 를 import 하지 않도록 여기 적는다. 실제 판정은 Ctx.cfg 의 check_value 가 한 번 더 한다.)"""
    return _port_arg(s, 1024)


_bind_port_arg.__name__ = "포트"
# 명령줄 덮어쓰기 키 → 사용자에게 보일 인자 이름
_FLAG_OF = {"teamServer.bindHost": "--host", "teamServer.bindPort": "--port", "teamServer.storeDir": "--store",
            "team.serverHost": "--host", "team.serverPort": "--port"}


def _nonneg_int(s: str) -> int:
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError("0 이상의 정수") from None
    if n < 0:
        raise argparse.ArgumentTypeError("0 이상의 정수")
    return n


def _months_arg(s: str) -> int:
    try:
        v = int(s)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("개월 수는 정수") from None
    if not 1 <= v <= 36:
        raise argparse.ArgumentTypeError("개월 수는 1~36")
    return v


def _csv(s):
    if s is None:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]


def _csv_choice(allowed, what):
    def f(s):
        vals = _csv(s)
        bad = [v for v in vals if v not in allowed]
        if not vals or bad:
            raise argparse.ArgumentTypeError(f"{what} 는 {','.join(allowed)} 중에서 쉼표로")
        return vals
    f.__name__ = what
    return f


def _existing_dir(s: str) -> str:
    if not os.path.isdir(s):
        raise argparse.ArgumentTypeError("폴더가 없습니다")
    return s


# ── 명령 처리기 ──────────────────────────────────────────────────────────────
def _cmd_collect(ctx):
    a = ctx.args
    if a.auto and a.mode not in (None, "auto"):
        raise CliError("--auto 는 --mode auto 와만 함께 쓸 수 있습니다")
    mode = a.mode or "auto"
    if mode == "recollect" and not (a.since and a.until):
        raise CliError("--mode recollect 에는 --since 와 --until 이 필요합니다")
    if a.since and a.until and a.since > a.until:
        raise CliError("--since 가 --until 보다 늦습니다")
    fn = resolve("lm27.collect.run", "collect_here")
    res = fn(ctx.paths, ctx.cfg(), mode=mode, since=a.since, until=a.until, pc_role=a.pc_role,
             only=_csv(a.only), budget_sec=a.budget_sec)
    return rc_of(res)


def _write_pc_json(ctx) -> int:
    r"""설치 전용 진입점: 번들에 ``pcs\<pc_id>\pc.json`` 만 쓴다(TAB §1.6.6). 실패는 rc 2(설치는 됐음)."""
    ensure_pc_dir = resolve("lm27.bundle.pcreg", "ensure_pc_dir")
    try:
        with ctx.bundle_lock("fg-write"):
            ensure_pc_dir(ctx.paths, ctx.ident())
    except CliError:
        raise
    except Exception as e:                       # 번들 쓰기 불가·잠금 시간 초과 — 설치 자체는 성공
        _fail(f"에이전트는 설치했지만 번들에 이 PC 기록을 남기지 못했습니다({type(e).__name__})")
        return RC_PARTIAL
    return RC_OK


def _cmd_agent_install(ctx):
    """설치 → 번들에 pc.json 만(TAB §1.6.6). cli 는 수집·탐침·내보내기를 부르지 않으므로 ``--only`` 유무와
    관계없이 설치 전용으로 동작한다(``--only`` 없는 형식의 추가 동작은 계약 미정 — 완료 보고 CR)."""
    a = ctx.args
    ensure_agent = resolve("lm27.agent.install", "ensure_agent")
    if a.reinstall:
        resolve("lm27.agent.install", "uninstall")(ctx.ident(), False)
    res = ensure_agent(ctx.ident())
    rc = rc_of(res)
    _show(res, text=False)
    if rc in (RC_OK, RC_NOOP):
        rc2 = _write_pc_json(ctx)
        if rc2 != RC_OK:
            rc = rc2
    return rc


def _cmd_agent_status(ctx):
    h = resolve("lm27.agent.install", "agent_health")(ctx.ident())
    _show(h)
    return rc_of(h, RC_PARTIAL)


def _cmd_agent_repair(ctx):
    res = resolve("lm27.agent.install", "ensure_agent")(ctx.ident())
    _show(res, text=False)
    return rc_of(res)


def _cmd_agent_uninstall(ctx):
    res = resolve("lm27.agent.install", "uninstall")(ctx.ident(), ctx.args.purge)
    return rc_of(res)


def _cmd_bundle_status(ctx):
    res = resolve("lm27.bundle.loader", "bundle_status")(ctx.paths)
    _show(res)
    return rc_of(res)


def _cmd_bundle_verify(ctx):
    res = resolve("lm27.bundle.loader", "verify_bundle")(ctx.paths)
    _show(res)
    return rc_of(res)


def _cmd_bundle_merge(ctx):
    res = resolve("lm27.bundle.merge", "merge_bundle")(ctx.paths, ctx.args.dir)
    _show(res, text=False)
    return rc_of(res)


def _cmd_bundle_alias(ctx):
    fn = resolve("lm27.bundle.aliases", "record_alias")
    with ctx.bundle_lock("fg-write"):
        res = fn(ctx.paths, ctx.args.pc_id, ctx.args.logical, rule="manual")
    return rc_of(res)


def _cmd_bundle_unalias(ctx):
    fn = resolve("lm27.bundle.aliases", "undo_alias")
    with ctx.bundle_lock("fg-write"):
        res = fn(ctx.paths, ctx.args.pc_id)
    return rc_of(res)


def _cmd_bundle_redact(ctx):
    fn = resolve("lm27.bundle.merge", "redact_rewrite_own")
    pcdir = ctx.paths.pc_dir(ctx.ident().pc_id)
    with ctx.bundle_lock("redact"):
        res = fn(pcdir)
    return rc_of(res)


def _cmd_move_prepare(ctx):
    res = resolve("lm27.bundle.move", "prepare_move")(ctx.paths, ctx.cfg())
    return rc_of(res)


def _cmd_analyze(ctx):
    a = ctx.args
    if a.rerun:
        if a.from_ or a.to:
            raise CliError("--rerun 과 --from/--to 는 함께 쓸 수 없습니다")
        if not a.stages:
            raise CliError("--rerun 에는 --stages 가 필요합니다")
    else:
        if not (a.from_ and a.to):
            raise CliError("--from 과 --to 가 필요합니다(또는 --rerun <run_id> --stages <ids>)")
        if a.stages:
            raise CliError("--stages 는 --rerun 과 함께만 씁니다")
        if a.from_ > a.to:
            raise CliError("--from 이 --to 보다 늦습니다")
    stages = _csv(a.stages)
    for s in stages or ():
        if not _STAGE_ID_RX.match(s):
            raise CliError("--stages 형식이 아닙니다(예 classify,time,mining,report)")
    fn = resolve("lm27.pipeline.analyze", "analyze")
    kw = {}
    # 기간 출처(R RP8 — 화면이 넘긴다, W2 통합 WP-32·36 CR). 없으면 넘기지 않는다(파이프라인 기본: user·rerun).
    if getattr(a, "period_source", None):
        kw["period_source"] = a.period_source
    if getattr(a, "period_months", None) is not None:
        kw["period_months"] = a.period_months
    cancel = _job_cancel(ctx)
    if cancel is not None:
        kw["cancel"] = cancel
    res = fn(ctx.paths, ctx.cfg(), from_=a.from_, to=a.to, as_of=a.as_of, ai=not a.no_ai, rerun=a.rerun,
             stages=stages, **kw)
    return rc_of(res)


# ── 협조형 취소(계약 §8.7 — W2 통합 WP-35 CR) ─────────────────────────────────
_STOP_POLL_S = 0.5


def _job_stop_flag(ctx):
    r"""화면 작업이면 그 작업의 정지 플래그 경로(``Paths.ui_job_stop_flag``), 아니면 None."""
    job = getattr(ctx.args, "job", None)
    fn = getattr(ctx.paths, "ui_job_stop_flag", None) if job else None
    if not callable(fn):
        return None
    try:
        return fn(job)
    except ValueError:
        return None


def _job_cancel(ctx):
    """분석처럼 단계 사이에서 멈출 수 있는 명령에 넘길 ``cancel()`` — 정지 플래그가 생기면 참."""
    flag = _job_stop_flag(ctx)
    if flag is None:
        return None
    return lambda: os.path.exists(os.fspath(flag))


class _StopWatch:
    r"""``--job`` 명령의 정지 플래그 감시(데몬 스레드). 화면이 [취소] 로 플래그를 쓰면 주 스레드에 KeyboardInterrupt 를
    보내 명령이 저널·커서를 정리하고 rc 2(사용자 중단)로 끝나게 한다 — 5초 뒤 kill_tree 는 화면 쪽 마지막 수단."""

    def __init__(self, flag):
        import threading
        self.flag = os.fspath(flag)
        self.stop = threading.Event()
        self.fired = False
        self.thread = threading.Thread(target=self._loop, name="lm27-cli-stopwatch", daemon=True)

    def _loop(self):
        import _thread
        while not self.stop.wait(_STOP_POLL_S):
            if os.path.exists(self.flag):
                self.fired = True
                _thread.interrupt_main()
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(2.0)
        return False


def _unsupported(flag: str, why: str):
    """계약 함수 시그니처에 자리가 없는 인자 — 조용히 무시하거나 없는 인자로 부르지 않고 rc 1 로 막는다(CR 대기)."""
    raise CliError(f"아직 지원하지 않는 인자입니다: {flag} — {why}(계약 보강 요청 중)", RC_FAIL)


def _cmd_report_build(ctx):
    # R 부록 A: build_report(run_id, *, force=False) — 계약 O-14 ③ 해소(W2 통합, WP-31 CR). force 는 있을 때만 넘긴다.
    fn = resolve("lm27.report", "build_report")
    res = fn(ctx.args.run, force=True) if ctx.args.force else fn(ctx.args.run)
    return rc_of(res)


def _cmd_report_export(ctx):
    a = ctx.args
    fn = resolve("lm27.report.export", "export")
    res = fn(a.run, a.formats, a.variant, a.out)
    _show(res)
    return rc_of(res)


def _cmd_report_ai_items(ctx):
    fn = resolve("lm27.report.analysis.ai_items", "write_ai_items")
    res = fn(ctx.args.run, ctx.args.stage)
    _show(res)
    if isinstance(res, dict) and all(isinstance(v, int) for v in res.values()):
        return RC_OK if sum(res.values()) > 0 else RC_NOOP
    return rc_of(res)


def _cmd_ui(ctx):
    a = ctx.args
    cfg = ctx.cfg()
    if a.check:
        return rc_of(resolve("lm27.ui.server", "check")(cfg, port=a.port), RC_ENV)
    return rc_of(resolve("lm27.ui.server", "serve")(cfg, port=a.port, open_browser=not a.no_browser))


def _field(obj, name):
    """결과 객체의 필드 — dict 키 또는 속성(계약 반환형이 dataclass·dict 어느 쪽이어도)."""
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _current_run_id(ctx) -> str:
    r"""지금 보고 있는 분석 결과의 run_id — ``data\derived\analysis\current.json``(R §2.4). 없으면 rc 2(분석 먼저)."""
    from lm27.util import fsx
    cur = fsx.read_json(ctx.paths.analysis_current(), None, want=dict)
    rid = cur.get("run_id") if isinstance(cur, dict) else None
    if not isinstance(rid, str) or not _RUN_RX.match(rid):
        raise CliError("분석 결과가 없습니다 — 먼저 [분석](lm27 analyze)을 실행하세요", RC_PARTIAL)
    return rid


def _cmd_team_build(ctx):
    r"""TAB §2.7: ``build_and_queue(analysis, period, cfg) -> QueueItem``. analysis 를 무엇으로 적재할지는 계약에 없다
    (CR) — 그 전까지 지금 분석 결과의 보고서 모델(R 부록 A ``load_model(run_id)``)을 넘긴다."""
    a = ctx.args
    if a.from_ > a.to:
        raise CliError("--from 이 --to 보다 늦습니다")
    cfg = ctx.cfg()
    analysis = resolve("lm27.report", "load_model")(_current_run_id(ctx))
    res = resolve("lm27.team.build", "build_and_queue")(analysis, {"from": a.from_, "to": a.to}, cfg)
    _show(res, text=False)
    return rc_of(res)


def _item_name(it) -> str:
    p = _field(it, "path")
    return os.path.basename(os.fspath(p)) if p is not None else str(_field(it, "name") or "")


def _queue_item(name: str):
    r"""명령줄 <item>(대기열 파일 이름, ``.json`` 생략 가능) → ``list_items()`` 의 QueueItem(TAB §2.7·§5.1 — 계약 함수는
    item.path·item.meta 를 쓴다. 문자열을 그대로 넘기지 않는다). 없으면 rc 4."""
    for it in resolve("lm27.team.queue", "list_items")() or ():
        nm = _item_name(it)
        if name in (nm, nm[:-5] if nm.endswith(".json") else nm):
            return it
    raise CliError(f"대기열에 그 항목이 없습니다: {name} — lm27 team list 로 확인하세요", RC_NOOP)


def _cmd_team_list(ctx):
    items = resolve("lm27.team.queue", "list_items")()
    _show(items)
    if isinstance(items, (list, tuple)):
        return RC_OK if items else RC_NOOP
    return rc_of(items)


def _cmd_team_preview(ctx):
    # 미리보기 함수는 계약에 이름이 없다(TAB §2.7 은 화면 동작만 — CR). 받는 것은 QueueItem.
    item = _queue_item(ctx.args.item)
    res = resolve("lm27.team.queue", "preview")(item)
    _show(res)
    return rc_of(res)


def _cmd_team_approve(ctx):
    item = _queue_item(ctx.args.item)
    return rc_of(resolve("lm27.team.queue", "approve")(item))


def _cmd_team_send(ctx):
    """TAB §8.2: ``send_due(cfg)`` — 승인된 대기분 전송. ``team send <item>`` = 계약 O-14 ① 결정(W2 통합, WP-34 CR):
    ``lm27.team.queue.send_item(item, cfg)``(승인 + 전송, rc = item.rc — 0 보냄 · 2 대기·인증·다른 서버·막힘 · 1 실패 ·
    4 보낼 상태 아님)."""
    a = ctx.args
    if a.item and a.all:
        raise CliError("<item> 과 --all 은 함께 쓸 수 없습니다")
    if a.item and getattr(a, "trigger", None):
        raise CliError("--trigger 는 대기분 전송(--all)에만 씁니다")
    if a.item:
        item = _queue_item(a.item)
        res = resolve("lm27.team.queue", "send_item")(item, ctx.cfg())
        _show(res, text=False)
        return rc_of(res)
    trig = getattr(a, "trigger", None)
    fn = resolve("lm27.team.queue", "send_due")
    # --trigger(화면 기동·15분 타이머 — TAB §2.8): 안 닿아도 시도 횟수를 올리지 않는 계기. 없으면 수동(manual)
    res = fn(ctx.cfg(), trigger=trig) if trig else fn(ctx.cfg())
    _show(res, text=False)
    return rc_of(res)


def _cmd_team_drop(ctx):
    item = _queue_item(ctx.args.item)
    return rc_of(resolve("lm27.team.queue", "mark")(item, "dropped", "사용자가 치웠습니다"))


def _cmd_team_mask(ctx):
    return rc_of(resolve("lm27.team.build", "set_mask")(ctx.paths, ctx.args.unit_id, ctx.args.mode))


def _cmd_team_drop_need(ctx):
    return rc_of(resolve("lm27.team.build", "drop_need")(ctx.paths, ctx.args.need_id))


def _cmd_team_export(ctx):
    item = _queue_item(ctx.args.item)
    res = resolve("lm27.team.offline", "export_to_dir")(item, ctx.args.dir)
    _show(res)
    return rc_of(res)


def _team_base(ctx, host=None, port=None) -> str:
    """팀 서버 주소 ``http://<host>:<port>`` — 명령줄 값이 없으면 설정(team.serverHost·serverPort). 명령줄 호스트는 레지스트리
    형식으로 검사한다(기본 주소 자체는 바꾸지 않는다 — 이번 실행에만)."""
    cfg = ctx.cfg()
    if host is not None:
        why = resolve("lm27.config", "check_value")("team.serverHost", host, path=ctx.paths.settings_registry())
        if why:
            raise CliError(f"--host: {why}", RC_FAIL)
    h = host if host is not None else cfg["team.serverHost"]
    p = port if port is not None else cfg["team.serverPort"]
    if ":" in h and not h.startswith("["):
        h = f"[{h}]"                                     # IPv6 리터럴
    return f"http://{h}:{p}"


def _cmd_team_ping(ctx):
    """TAB §2.9 hello 판정만: ``hello(base, timeout) -> Hello``. result 가 ok 면 rc 0, 아니면(다른 판·LM24·응답 없음) rc 2."""
    a = ctx.args
    base = _team_base(ctx, a.host, a.port)
    h = resolve("lm27.team.client", "hello")(base, ctx.cfg()["team.connectTimeoutSec"])
    _show(h)
    return RC_OK if _field(h, "result") == "ok" else RC_PARTIAL


def _cmd_team_registry_fetch(ctx):
    r"""'지금 받기' — 계약 O-14 ② 결정(W2 통합, WP-34 CR): ``lm27.team.client.refresh_registry(paths, cfg, force=True)``
    가 받아서 캐시까지 교체한다(``fetch_registry`` 는 HTTP 만 — cli 는 캐시 파일을 다루지 않는다, L-22).
    rc = 결과의 rc(0 받아 저장 · 4 이미 최신 · 2 받지 못함). rc 가 없고 HTTP 상태만 있으면 200·304 → 0, 그 밖 → 2."""
    r = resolve("lm27.team.client", "refresh_registry")(ctx.paths, ctx.cfg(), force=True)
    _show(r, text=False)
    rc = _field(r, "rc")
    if isinstance(rc, int) and not isinstance(rc, bool):
        return rc_of(r)
    st = _field(r, "status")
    if isinstance(st, int) and not isinstance(st, bool):
        return RC_OK if st in (200, 304) else RC_PARTIAL
    return rc_of(r)


def _server_overrides(a):
    return {"teamServer.bindHost": getattr(a, "host", None), "teamServer.bindPort": getattr(a, "port", None),
            "teamServer.storeDir": getattr(a, "store", None)}


def _cmd_team_server(ctx):
    cfg = ctx.cfg(_server_overrides(ctx.args))
    return rc_of(resolve("lm27.team.server", "serve")(cfg), RC_OK)


def _cmd_team_aggregate(ctx):
    cfg = ctx.cfg(_server_overrides(ctx.args))
    store = resolve("lm27.team.store", "open_store")(cfg)
    res = resolve("lm27.team.aggregate", "aggregate")(store, ctx.args.gen)
    return rc_of(res)


def _cmd_team_import(ctx):
    cfg = ctx.cfg(_server_overrides(ctx.args))
    store = resolve("lm27.team.store", "open_store")(cfg)
    res = resolve("lm27.team.offline", "import_files")(store, ctx.args.path, cfg)
    _show(res, text=False)
    return rc_of(res)


def _cmd_team_firewall_diag(ctx):
    """TAB §8.2: ``firewall_diag(exe_path) -> dict``. --store 의 자리가 계약 함수에 없다(CR) — 넘기지 않고 막는다."""
    if ctx.args.store:
        _unsupported("--store", "firewall_diag(exe_path) 에 팀 서버 저장소 인자가 없습니다")
    res = resolve("lm27.team.firewall", "firewall_diag")(str(ctx.paths.python_exe()))
    _show(res)
    return rc_of(res)


def _cmd_selftest_privacy(ctx):
    rc = resolve("lm27.privacy.selftest", "run_selftest")(update_lock=ctx.args.update_lock)
    return rc_of(rc)


def _bridge(argv) -> int:
    """``bridge …`` — 남은 인자를 그대로 ``lm27.bridge.cli.main(argv)`` 로(--job·--events 는 여기서 소비)."""
    rest, job, ev, i = [], None, None, 0
    while i < len(argv):
        t = argv[i]
        if t in ("--job", "--events") and i + 1 < len(argv):
            if t == "--job":
                job = argv[i + 1]
            else:
                ev = argv[i + 1]
            i += 2
            continue
        if t.startswith("--job="):
            job = t.split("=", 1)[1]
        elif t.startswith("--events="):
            ev = t.split("=", 1)[1]
        else:
            rest.append(t)
        i += 1
    if job is not None and not _JOB_RX.match(job):
        raise CliError("--job 형식이 아닙니다(j + 14자리 시각 + 4hex)")
    if ev not in (None, "jsonl", "text"):
        raise CliError("--events 는 jsonl 또는 text")
    events.configure(mode=ev or "text", job=job)
    return rc_of(resolve("lm27.bridge.cli", "main")(rest), RC_OK)


# ── 파서 ─────────────────────────────────────────────────────────────────────
def _common() -> argparse.ArgumentParser:
    c = _Parser(add_help=False)
    g = c.add_argument_group("화면 작업 공통")
    g.add_argument("--job", type=_rx_arg(_JOB_RX, "job_id"), help="화면 작업 id(j + 14자리 시각 + 4hex)")
    g.add_argument("--events", choices=("jsonl", "text"), help="jsonl = 표준 출력에 한 줄 JSON 이벤트(§8.6)")
    return c


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    help_of = dict(COMMANDS)
    p = _Parser(prog="lm27", description=f"LoadMonitor27 {LM27_VERSION} — 명령 목록(계약 §7.1)",
                epilog=_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"LoadMonitor27 {LM27_VERSION}")
    sub = p.add_subparsers(dest="command", metavar="<명령>", parser_class=_Parser)

    def leaf(sp, name, func, help_ko, **kw):
        q = sp.add_parser(name, help=help_ko, description=help_ko, parents=[common], **kw)
        q.set_defaults(func=func)
        return q

    def group(name):
        g = sub.add_parser(name, help=help_of[name], description=help_of[name])
        return g.add_subparsers(dest="sub", metavar="<하위 명령>", parser_class=_Parser, required=True)

    # collect
    q = leaf(sub, "collect", _cmd_collect, help_of["collect"])
    q.add_argument("--auto", action="store_true", help="--mode auto 무질문 + 끝에 대기 업로드 전송")
    q.add_argument("--mode", choices=("auto", "probe-only", "recollect"))
    q.add_argument("--since", type=_date_arg, metavar="D")
    q.add_argument("--until", type=_date_arg, metavar="D")
    q.add_argument("--pc-role", dest="pc_role", choices=("pc1", "pc2", "cloud"))
    q.add_argument("--only", metavar="<src,…>", help="경로 ID 목록(쉼표)")
    q.add_argument("--budget-sec", dest="budget_sec", type=_nonneg_int, metavar="N")

    # agent
    ag = group("agent")
    q = leaf(ag, "install", _cmd_agent_install, "에이전트 설치(--only = 설치 전용: 수집·탐침·내보내기 없음)")
    q.add_argument("--only", action="store_true")
    q.add_argument("--reinstall", action="store_true", help="작업을 지우고 다시 설치(store 는 남김)")
    leaf(ag, "status", _cmd_agent_status, "에이전트 생존 확인")
    leaf(ag, "repair", _cmd_agent_repair, "에이전트 자동 복구")
    q = leaf(ag, "uninstall", _cmd_agent_uninstall, "에이전트 제거(--purge = store 까지 삭제)")
    q.add_argument("--purge", action="store_true")

    # bundle
    bd = group("bundle")
    leaf(bd, "status", _cmd_bundle_status, "번들 상태")
    leaf(bd, "verify", _cmd_bundle_verify, "세그먼트 sha 검증")
    q = leaf(bd, "merge", _cmd_bundle_merge, "다른 사본의 data 폴더를 합집합으로 합치기")
    q.add_argument("dir", type=_existing_dir, metavar="<dir>")
    q = leaf(bd, "alias", _cmd_bundle_alias, "논리 PC 별칭 지정")
    q.add_argument("pc_id", type=_rx_arg(_PC_RX, "pc_id"), metavar="<pc_id>")
    q.add_argument("logical", type=_rx_arg(_LOGICAL_RX, "논리 PC 이름"), metavar="<logical>")
    q = leaf(bd, "unalias", _cmd_bundle_unalias, "별칭 되돌리기")
    q.add_argument("pc_id", type=_rx_arg(_PC_RX, "pc_id"), metavar="<pc_id>")
    leaf(bd, "redact", _cmd_bundle_redact, "소급 가림 재작성(이 PC 세그먼트)")

    # move-prepare
    leaf(sub, "move-prepare", _cmd_move_prepare, help_of["move-prepare"])

    # analyze
    q = leaf(sub, "analyze", _cmd_analyze, help_of["analyze"])
    q.add_argument("--from", dest="from_", type=_date_arg, metavar="D")
    q.add_argument("--to", type=_date_arg, metavar="D")
    q.add_argument("--as-of", dest="as_of", type=_ts_arg, metavar="T")
    q.add_argument("--no-ai", dest="no_ai", action="store_true")
    q.add_argument("--rerun", type=_rx_arg(_RUN_RX, "run_id"), metavar="<run_id>")
    q.add_argument("--stages", metavar="<ids>", help="예 classify,time,mining,report")
    q.add_argument("--period-source", dest="period_source", choices=PERIOD_SOURCES,
                   help="기간 출처(R RP8 — 화면이 넘긴다)")
    q.add_argument("--period-months", dest="period_months", type=_months_arg, metavar="N", help="기간 개월 수(1~36)")

    # report
    rp = group("report")
    q = leaf(rp, "build", _cmd_report_build, "보고서 모델 만들기")
    q.add_argument("--run", required=True, type=_rx_arg(_RUN_RX, "run_id"), metavar="<run_id>")
    q.add_argument("--force", action="store_true")
    q = leaf(rp, "export", _cmd_report_export, "내보내기(html·csv·json × full·redacted)")
    q.add_argument("--run", required=True, type=_rx_arg(_RUN_RX, "run_id"), metavar="<run_id>")
    q.add_argument("--formats", required=True, type=_csv_choice(EXPORT_FORMATS, "--formats"))
    q.add_argument("--variant", required=True, type=_csv_choice(EXPORT_VARIANTS, "--variant"))
    q.add_argument("--out", metavar="<dir>")
    q = leaf(rp, "ai-items", _cmd_report_ai_items, "코파일럿 단계 ai_in 쓰기")
    q.add_argument("--run", required=True, type=_rx_arg(_RUN_RX, "run_id"), metavar="<run_id>")
    q.add_argument("--stage", choices=AI_ITEM_STAGES, metavar="<stage>",
                   help="코파일럿 단계(" + "·".join(AI_ITEM_STAGES) + ")")

    # bridge — 도움말용(실행은 _bridge 가 인자를 그대로 넘긴다)
    q = sub.add_parser("bridge", help=help_of["bridge"], description=help_of["bridge"], add_help=False)
    q.add_argument("rest", nargs=argparse.REMAINDER)

    # ui
    q = leaf(sub, "ui", _cmd_ui, help_of["ui"])
    q.add_argument("--port", type=_bind_port_arg, metavar="N", help="1024~65535")
    q.add_argument("--no-browser", dest="no_browser", action="store_true")
    q.add_argument("--check", action="store_true")

    # team
    tm = group("team")
    q = leaf(tm, "build", _cmd_team_build, "팀 묶음 만들기(대기열에 넣음)")
    q.add_argument("--from", dest="from_", required=True, type=_date_arg, metavar="D")
    q.add_argument("--to", required=True, type=_date_arg, metavar="D")
    leaf(tm, "list", _cmd_team_list, "대기열 목록")
    for name, func, h in (("preview", _cmd_team_preview, "미리보기(= 실전송 내용)"),
                          ("approve", _cmd_team_approve, "전송 승인"),
                          ("drop", _cmd_team_drop, "대기 항목 버리기")):
        q = leaf(tm, name, func, h)
        q.add_argument("item", type=_rx_arg(_ITEM_RX, "item"), metavar="<item>")
    q = leaf(tm, "send", _cmd_team_send, "전송(<item> 하나 또는 --all)")
    q.add_argument("item", nargs="?", type=_rx_arg(_ITEM_RX, "item"), metavar="<item>")
    q.add_argument("--all", action="store_true")
    q.add_argument("--trigger", choices=SEND_TRIGGERS, help="재시도 계기(화면이 붙인다 — 기본 수동)")
    q = leaf(tm, "mask", _cmd_team_mask, "단위업무 제목 가림")
    q.add_argument("unit_id", type=_rx_arg(_UNIT_RX, "unit_id"), metavar="<unit_id>")
    q.add_argument("mode", choices=("title", "detail", "none"))
    q = leaf(tm, "drop-need", _cmd_team_drop_need, "필요 항목 빼기")
    q.add_argument("need_id", type=_rx_arg(_NEED_RX, "need_id"), metavar="<need_id>")
    q = leaf(tm, "export", _cmd_team_export, "오프라인 내보내기(공유폴더)")
    q.add_argument("item", type=_rx_arg(_ITEM_RX, "item"), metavar="<item>")
    q.add_argument("--dir", required=True, metavar="<폴더>")
    q = leaf(tm, "ping", _cmd_team_ping, "팀 서버 hello 만")
    q.add_argument("--host", metavar="H")
    q.add_argument("--port", type=_port_arg, metavar="N")
    leaf(tm, "registry-fetch", _cmd_team_registry_fetch, "팀 레지스트리 받기")

    # team-server · team-aggregate · team-import · team-firewall-diag
    q = leaf(sub, "team-server", _cmd_team_server, help_of["team-server"])
    q.add_argument("--host", metavar="H")
    q.add_argument("--port", type=_bind_port_arg, metavar="N", help="1024~65535(teamServer.bindPort)")
    q.add_argument("--store", metavar="DIR")
    q = leaf(sub, "team-aggregate", _cmd_team_aggregate, help_of["team-aggregate"])
    q.add_argument("--store", required=True, metavar="<dir>")
    q.add_argument("--gen", required=True, type=_nonneg_int, metavar="N")
    q = leaf(sub, "team-import", _cmd_team_import, help_of["team-import"])
    q.add_argument("path", metavar="<파일|폴더>")
    q.add_argument("--store", metavar="DIR")
    q = leaf(sub, "team-firewall-diag", _cmd_team_firewall_diag, help_of["team-firewall-diag"])
    q.add_argument("--store", metavar="DIR")

    # selftest
    st = group("selftest")
    q = leaf(st, "privacy", _cmd_selftest_privacy, "정제 회귀 말뭉치(= tools\\lm27_selftest.py)")
    q.add_argument("--update-lock", dest="update_lock", action="store_true")
    return p


# ── 진입 ─────────────────────────────────────────────────────────────────────
def _setup_stdio() -> None:
    """표준 출력 UTF-8(진입점에서만, 계약 §9.1). pythonw 처럼 스트림이 없으면 빈 출력으로."""
    for name in ("stdout", "stderr"):
        st = getattr(sys, name)
        if st is None:
            setattr(sys, name, _NullIO())
            continue
        reconf = getattr(st, "reconfigure", None)
        if reconf is not None:
            try:
                reconf(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _where(e: BaseException) -> str:
    """예외가 난 코드 위치(파일:줄 함수) — 메시지(원문이 섞일 수 있음)는 쓰지 않는다."""
    tb = traceback.extract_tb(e.__traceback__)[-4:]
    return " < ".join(f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(tb)) or "?"


def _run(argv) -> int:
    if argv and argv[0] == "bridge":
        return _bridge(argv[1:])
    parser = build_parser()
    if not argv:
        parser.print_help(sys.stdout)
        raise CliError("명령이 필요합니다", RC_FAIL)
    args = parser.parse_args(argv)
    events.configure(mode=getattr(args, "events", None) or "text", job=getattr(args, "job", None))
    func = getattr(args, "func", None)
    if func is None:
        raise CliError("명령이 필요합니다", RC_FAIL)
    ctx = Ctx(args)
    flag = _job_stop_flag(ctx)
    if flag is None:
        return func(ctx)
    with _StopWatch(flag):                       # 화면 [취소] = 정지 플래그 → KeyboardInterrupt → rc 2(계약 §8.7)
        return func(ctx)


def main(argv: list[str] | None = None) -> int:
    """``lm27 <명령>`` 의 진입. rc 를 돌려준다(sys.exit 는 lm27_cli.py 가 한다)."""
    _setup_stdio()
    events.configure(mode="text")                # 프로세스 진입 = 사람용 출력으로 시작(명령이 --events 로 바꾼다)
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        rc = _run(argv)
    except _Exit as e:
        rc = RC_OK if e.status == 0 else RC_FAIL
    except CliError as e:
        _fail(e.msg)
        rc = e.rc
    except KeyboardInterrupt:
        _fail("사용자가 중단했습니다 — 다시 실행하면 이어서 합니다")
        rc = RC_PARTIAL
    except Exception as e:
        _fail(f"내부 오류({type(e).__name__}) — 위치: {_where(e)}")
        rc = RC_FAIL
    if events.mode() == "jsonl":
        events.emit("run_end", rc=rc)
    return rc
