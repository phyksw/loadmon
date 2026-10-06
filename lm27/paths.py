# -*- coding: utf-8 -*-
r"""경로 로더 단일원(계약 §1·§2.1, L-08) — 모든 데이터 경로를 여기서만 만든다.

다른 모듈은 경로 문자열을 조립하지 않고 ``Paths`` 메서드를 부른다(예외: ``data\pcs`` 아래 세부는
``lm27\bundle`` 의 7개 모듈 — 계약 §9.3). 이 클래스는 **순수**하다: 경로를 계산할 뿐 폴더·파일을 만들지 않는다
(만드는 일은 ``lm27.util.fsx.atomic_write``·``ensure_dir`` 이 쓰기 직전에 한다).

두 가지 모드(계약 §7.3 끝):
  · ``program`` — 프로그램 폴더(``<ROOT>``: ``lm27_cli.py``·``data\`` 가 있는 곳). 번들·개인 자료는 ``<ROOT>\data\``.
  · ``agent``   — 에이전트 bin 사본(``%LOCALAPPDATA%\LoadMonitor27\agent\bin\<ver>\``). ROOT 를 참조하지 않는다.
  PC 에 남는 것(``%LOCALAPPDATA%\LoadMonitor27\``, 계약 §1.3)은 두 모드에서 같다.

인자 검증: 경로 조각이 되는 ID(pc_id·run_id·kind·src·stage·판·이름)는 형식을 확인하고 어긋나면 ValueError —
``..``·구분자·드라이브 문자로 트리 밖을 가리키는 일을 막는다.

이 모듈은 에이전트 bin 사본에도 들어가므로 표준 라이브러리만 쓴다.
"""
import os
import re
from datetime import UTC, date, datetime
from pathlib import Path

APP_DIR = "LoadMonitor27"

PC_ID_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
RUN_ID_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
JOB_ID_RX = re.compile(r"^j\d{14}[0-9a-f]{4}$")
_KIND_RX = re.compile(r"^[a-z][a-z0-9_]{1,23}$")
_SRC_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)$")
_STAGE_RX = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_VER_RX = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,31}$")
_NAME_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_DATE_RX = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")

OUTBOX_STATES = ("pending", "sent", "failed", "dropped")
OFFLINE_REGISTRY_NAME = "lm27_registry.json"     # team.offlineDir·teamServer.publishDir 안 오프라인 레지스트리 사본(TAB §5.3)
_RAND_RX = re.compile(r"^[0-9a-f]{4,32}$")


def _check(rx, value, what):
    if not isinstance(value, str) or not rx.match(value) or ".." in value:
        raise ValueError(f"paths: {what} 형식이 아닙니다")
    return value


def _ymd(d, what="날짜"):
    """date · datetime(aware 면 UTC 로 환산) · 'YYYY-MM-DD' · 'YYYYMMDD' → ('YYYY', 'MM', 'DD')."""
    if isinstance(d, datetime):
        if d.tzinfo is not None:
            d = d.astimezone(UTC)
        d = d.date()
    if isinstance(d, date):
        return f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}"
    if isinstance(d, str):
        m = _DATE_RX.match(d)
        if m:
            y, mo, dd = m.groups()
            date(int(y), int(mo), int(dd))          # 없는 날짜면 ValueError
            return y, mo, dd
    raise ValueError(f"paths: {what} 형식이 아닙니다")


def _rel_parts(rel, what):
    """'agent/agent.ps1' 같은 상대 경로를 검증된 조각 목록으로."""
    if not isinstance(rel, str) or not rel or os.path.isabs(rel) or ":" in rel:
        raise ValueError(f"paths: {what} 형식이 아닙니다")
    parts = [p for p in re.split(r"[\\/]", rel) if p]
    if not parts:
        raise ValueError(f"paths: {what} 형식이 아닙니다")
    for p in parts:
        _check(_NAME_RX, p, what)
    return parts


class Paths:
    r"""경로 로더. ``Paths()`` = 이 패키지가 들어 있는 폴더를 ROOT 로.
    ``lad`` = ``%LOCALAPPDATA%\LoadMonitor27`` 대신 쓸 폴더(시험 주입). 주지 않으면 환경 변수 LOCALAPPDATA 를 쓴다."""

    def __init__(self, root=None, *, lad=None):
        base = root if root is not None else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.root = Path(os.path.abspath(os.fspath(base)))
        self._lad = Path(os.path.abspath(os.fspath(lad))) if lad is not None else None

    def __repr__(self):
        return f"Paths(root={str(self.root)!r}, mode={self.mode()!r})"

    # ── 모드·프로그램 폴더 ────────────────────────────────────────────────
    def mode(self) -> str:
        r"""``program``(옆에 ``data\`` 가 있거나 ``lm27_cli.py`` 가 있음) 또는 ``agent``(bin 사본)."""
        if (self.root / "data").is_dir() or (self.root / "lm27_cli.py").is_file():
            return "program"
        return "agent"

    def python_dir(self) -> Path:
        r"""동봉 파이썬 폴더 — 프로그램 폴더 ``python\``, 에이전트 사본 ``py311\``."""
        return self.root / ("python" if self.mode() == "program" else "py311")

    def python_exe(self) -> Path:
        return self.python_dir() / "python.exe"

    def pythonw_exe(self) -> Path:
        return self.python_dir() / "pythonw.exe"

    def cli_script(self) -> Path:
        return self.root / "lm27_cli.py"

    def pipe_script(self) -> Path:
        return self.root / "lm27_pipe.py"

    def agent_main_script(self) -> Path:
        r"""에이전트 bin 사본의 진입 스크립트(``agent_main.py`` — 원본 ``lm27\agent\main.py``, CR-04)."""
        return self.root / "agent_main.py"

    def package_dir(self) -> Path:
        return self.root / "lm27"

    def collect_script(self, rel: str) -> Path:
        r"""수집 스크립트. 프로그램 폴더 ``collect\<rel>``(예 ``agent/agent.ps1``), 에이전트 사본 ``ps\<파일 이름>``."""
        parts = _rel_parts(rel, "스크립트 이름")
        if self.mode() == "agent":
            return self.root / "ps" / parts[-1]
        return self.root.joinpath("collect", *parts)

    def web_file(self, rel: str) -> Path:
        r"""``web\`` 아래 정적 파일(예 ``app/index.html``)."""
        return self.root.joinpath("web", *_rel_parts(rel, "웹 파일 이름"))

    def config_dir(self) -> Path:
        return self.root / "config"

    def settings_registry(self) -> Path:
        return self.config_dir() / "settings_registry.json"

    def calendar_json(self) -> Path:
        return self.config_dir() / "calendar.json"

    def config_json(self) -> Path:
        """개인 덮어쓰기(비밀 없음, 폴더와 동행, 패키지 제외)."""
        return self.config_dir() / "config.json"

    # ── data\ (번들 + 개인 자료) ─────────────────────────────────────────
    def data(self) -> Path:
        return self.root / "data"

    def bundle_json(self) -> Path:
        return self.data() / "bundle.json"

    def bundle_lock(self) -> Path:
        return self.data() / ".bundle.lock"

    def pc_aliases(self) -> Path:
        return self.data() / "pc_aliases.json"

    def pcs(self) -> Path:
        return self.data() / "pcs"

    def pc_dir(self, pc_id: str) -> Path:
        return self.pcs() / _check(PC_ID_RX, pc_id, "pc_id")

    def pc_json(self, pc_id: str) -> Path:
        return self.pc_dir(pc_id) / "pc.json"

    def manifest(self, pc_id: str) -> Path:
        return self.pc_dir(pc_id) / "manifest.json"

    def manifest_prev(self, pc_id: str) -> Path:
        return self.pc_dir(pc_id) / "manifest.prev.json"

    def move_ready(self, pc_id: str) -> Path:
        return self.pc_dir(pc_id) / "move_ready.json"

    def quarantine(self, pc_id: str) -> Path:
        return self.pc_dir(pc_id) / "quarantine"

    def seg_dir(self, pc_id: str, kind: str) -> Path:
        return self.pc_dir(pc_id) / "seg" / _check(_KIND_RX, kind, "kind")

    def keys(self) -> Path:
        return self.data() / "keys"

    def keyring(self) -> Path:
        return self.keys() / "privacy_keyring.json"

    def secrets(self) -> Path:
        return self.keys() / "secrets.json"

    def local_only(self) -> Path:
        return self.data() / "local_only"

    def local_only_file(self, name: str) -> Path:
        r"""``local_only\<name>``(person_dir.json · corresp_domains.json · ad_lists.json · private_chats.json ·
        redact_overlay.json · person_alias.json · tag_feedback.json)."""
        return self.local_only() / _check(_NAME_RX, name, "파일 이름")

    def hier_local(self) -> Path:
        return self.local_only() / "hier"

    def hier_local_file(self, name: str) -> Path:
        r"""``local_only\hier\<name>``(registry_local.json · title_cache.json · proposals.json · corrections.jsonl …)."""
        return self.hier_local() / _check(_NAME_RX, name, "파일 이름")

    def team_dir(self) -> Path:
        return self.data() / "team"

    def registry_cache(self) -> Path:
        """팀 레지스트리 캐시(pepper 포함 — 반출 금지)."""
        return self.team_dir() / "registry.json"

    def registry_etag(self) -> Path:
        return self.team_dir() / "registry.etag"

    def team_overrides(self) -> Path:
        return self.team_dir() / "overrides.json"

    def outbox(self, state: str) -> Path:
        if state not in OUTBOX_STATES:
            raise ValueError(f"paths: outbox 상태는 {OUTBOX_STATES} 중 하나")
        return self.data() / "outbox" / "team" / state

    def outbox_file(self, state: str, name: str) -> Path:
        r"""팀 업로드 대기열 파일 ``data\outbox\team\<state>\<name>``(묶음·``.meta.json``·``.lease`` — 계약 v1.2 C19)."""
        return self.outbox(state) / _check(_NAME_RX, name, "파일 이름")

    def ai_store(self, stage: str) -> Path:
        r"""AI 답 보존소 항목 커밋 ``data\ai\store\<stage>.items.jsonl``."""
        return self.data() / "ai" / "store" / (_check(_STAGE_RX, stage, "단계 이름") + ".items.jsonl")

    def ai_store_dir(self) -> Path:
        r"""AI 답 보존소 폴더 ``data\ai\store\``(번들 합치기의 단계 파일 열거 — 계약 v1.2 C19)."""
        return self.data() / "ai" / "store"

    def ai_run(self, run_id: str) -> Path:
        return self.data() / "ai" / "runs" / _check(RUN_ID_RX, run_id, "run_id")

    def ai_journal(self, run_id: str, stage: str) -> Path:
        r"""브리지 단계 저널 ``data\ai\runs\<run_id>\<stage>.jsonl``(B §7.8 · 계약 §3.17)."""
        return self.ai_run(run_id) / (_check(_STAGE_RX, stage, "단계 이름") + ".jsonl")

    def ai_result(self, run_id: str, stage: str) -> Path:
        r"""브리지 단계 결과 봉투 ``data\ai\runs\<run_id>\<stage>.result.json``(B §7.11)."""
        return self.ai_run(run_id) / (_check(_STAGE_RX, stage, "단계 이름") + ".result.json")

    def ai_capabilities(self, run_id: str) -> Path:
        r"""그 실행의 조회 능력 기록 ``data\ai\runs\<run_id>\capabilities.json``."""
        return self.ai_run(run_id) / "capabilities.json"

    def bundle_probe(self, rand: str) -> Path:
        r"""번들 위치 쓰기 시험 파일 ``data\.probe_<rand>``(계약 §1.5 — 만들고 곧 지운다, rand = 16진 4~32자)."""
        return self.data() / (".probe_" + _check(_RAND_RX, rand, "임의 값"))

    def import_dir(self) -> Path:
        return self.data() / "import"

    def derived(self) -> Path:
        return self.data() / "derived"

    def coverage_ledger(self) -> Path:
        return self.derived() / "coverage_ledger.jsonl"

    def teams_coverage(self) -> Path:
        return self.derived() / "teams_coverage.jsonl"

    def todo(self) -> Path:
        return self.derived() / "todo.json"

    def verify_cache(self) -> Path:
        return self.derived() / "verify_cache.json"

    def collect_runs(self) -> Path:
        r"""수집 실행 폴더들의 부모 ``data\derived\collect\``(원장이 모든 실행의 단계 결과를 나열 — W2 통합, WP-33 CR)."""
        return self.derived() / "collect"

    def collect_stage_results(self, run_id: str) -> Path:
        r"""수집 실행 폴더 ``data\derived\collect\<run_id>\``."""
        return self.collect_runs() / _check(RUN_ID_RX, run_id, "run_id")

    def stage_result_file(self, run_id: str, stage: str) -> Path:
        r"""``data\derived\collect\<run_id>\stage_result_<stage>.json``(계약 §8.5)."""
        return self.collect_stage_results(run_id) / f"stage_result_{_check(_STAGE_RX, stage, '단계 이름')}.json"

    def blanks_file(self, run_id: str, src: str) -> Path:
        r"""백필 빈칸 파일 ``data\derived\collect\<run_id>\blanks_<src>.json``(X-315)."""
        return self.collect_stage_results(run_id) / f"blanks_{_check(_SRC_RX, src, '경로 ID')}.json"

    def ai_in(self, stage: str) -> Path:
        return self.derived() / "ai_in" / (_check(_STAGE_RX, stage, "단계 이름") + ".jsonl")

    def ai_out(self, stage: str) -> Path:
        return self.derived() / "ai_out" / (_check(_STAGE_RX, stage, "단계 이름") + ".json")

    def analysis_root(self) -> Path:
        r"""분석 실행 폴더들의 부모 ``data\derived\analysis\``(보관 정리·이력 나열 — W2 통합, WP-32 CR)."""
        return self.derived() / "analysis"

    def analysis(self, run_id: str) -> Path:
        return self.analysis_root() / _check(RUN_ID_RX, run_id, "run_id")

    def analysis_current(self) -> Path:
        return self.analysis_root() / "current.json"

    def run_status_file(self, run_id: str) -> Path:
        r"""분석 실행 상태 ``data\derived\analysis\<run_id>\run_status.json``(``lm27.runstatus/1`` — 계약 §3.23, W2 통합)."""
        return self.analysis(run_id) / "run_status.json"

    def analysis_time(self, run_id: str) -> Path:
        r"""시간 코어 결과 폴더 ``data\derived\analysis\<run_id>\time\``(계약 §3.14)."""
        return self.analysis(run_id) / "time"

    def analysis_time_file(self, run_id: str, name: str) -> Path:
        r"""시간 코어 결과 파일 ``…\time\<name>``(env_slots.jsonl · day_ledger.jsonl · tasks.json 등 9종 — 계약 §3.14)."""
        return self.analysis_time(run_id) / _check(_NAME_RX, name, "파일 이름")

    def analysis_hier(self, run_id: str) -> Path:
        r"""분류 결과 폴더 ``data\derived\analysis\<run_id>\hier\``(계약 §3.15)."""
        return self.analysis(run_id) / "hier"

    def analysis_hier_file(self, run_id: str, name: str) -> Path:
        r"""분류 결과 파일 ``…\hier\<name>``(labels.json · groups.json · queue.json · hier_meta.json 등 — 계약 §3.15)."""
        return self.analysis_hier(run_id) / _check(_NAME_RX, name, "파일 이름")

    def analysis_report(self, run_id: str) -> Path:
        r"""보고서 모델 폴더 ``data\derived\analysis\<run_id>\report\``(계약 §3.16)."""
        return self.analysis(run_id) / "report"

    def analysis_report_file(self, run_id: str, name: str) -> Path:
        r"""보고서 모델 파일 ``…\report\<name>``(report_model.json · model_meta.json — 계약 §3.16·§3.23)."""
        return self.analysis_report(run_id) / _check(_NAME_RX, name, "파일 이름")

    def calibration_report(self) -> Path:
        r"""보정 보고서 기본 위치 ``data\derived\calibration_report.json``(``lm27.calibration/1`` — W §8.3, 화면 [보정] 이
        읽는다. ``tools\calibrate.py --out`` 으로 이 파일을 고르면 화면에 보인다 — 자동 적용 없음)."""
        return self.derived() / "calibration_report.json"

    def logs(self) -> Path:
        return self.data() / "logs"

    # ── out\ ────────────────────────────────────────────────────────────
    def out_dir(self) -> Path:
        return self.root / "out"

    def out_personal(self, from_, to, run_id: str) -> Path:
        r"""``out\personal\<from>_<to>_<run8>``(run8 = run_id 끝 8자)."""
        f = "-".join(_ymd(from_, "from"))
        t = "-".join(_ymd(to, "to"))
        rid = _check(RUN_ID_RX, run_id, "run_id")
        return self.out_dir() / "personal" / f"{f}_{t}_{rid[-8:]}"

    def out_personal_file(self, from_, to, run_id: str, rel: str) -> Path:
        r"""개인 보고서 내보내기 파일 ``out\personal\<from>_<to>_<run8>\<rel>``(rel = ``report_full.html`` ·
        ``csv_full/units.csv`` 처럼 '/' 조각 — 조각마다 이름 검증, W2 통합 WP-31 CR)."""
        return self.out_personal(from_, to, run_id).joinpath(*_rel_parts(rel, "내보내기 파일 이름"))

    # ── %LOCALAPPDATA%\LoadMonitor27\ (PC 에 남는 것) ─────────────────────
    def lad(self) -> Path:
        r"""``%LOCALAPPDATA%\LoadMonitor27``. 에이전트 사본(``…\LoadMonitor27\agent\bin\<ver>\``)에서는 환경 변수가 아니라
        사본 위치에서 정한다(W1 통합 창 — WP-13 CR: 폴더 리디렉션·runas 세션에서 lm27_pipe 와 감독 루프가 서로 다른 LAD 로
        가지 않게, ``lm27.agent.main.bin_paths`` 와 같은 규칙)."""
        if self._lad is not None:
            return self._lad
        r = self.root
        if r.parent.name.lower() == "bin" and r.parent.parent.name.lower() == "agent" and self.mode() == "agent":
            return r.parent.parent.parent
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return Path(os.path.abspath(base)) / APP_DIR

    def agent_dir(self) -> Path:
        return self.lad() / "agent"

    def agent_json(self) -> Path:
        return self.agent_dir() / "agent.json"

    def agent_config(self) -> Path:
        return self.agent_dir() / "agent_config.json"

    def context_cache(self) -> Path:
        return self.agent_dir() / "context_cache.json"

    def heartbeat(self) -> Path:
        return self.agent_dir() / "heartbeat.json"

    def person_dir_delta(self) -> Path:
        return self.agent_dir() / "person_dir_delta.json"

    def export_log(self) -> Path:
        return self.agent_dir() / "export_log.jsonl"

    def agent_subkeys(self) -> Path:
        """에이전트 하위 키(주 키 없음)."""
        return self.agent_dir() / "keys" / "subkeys.json"

    def agent_bin_root(self) -> Path:
        return self.agent_dir() / "bin"

    def agent_bin(self, ver: str) -> Path:
        return self.agent_bin_root() / _check(_VER_RX, ver, "판")

    def agent_run(self) -> Path:
        return self.agent_dir() / "run"

    def stop_flag(self) -> Path:
        return self.agent_run() / "stop.flag"

    def harvest_now_flag(self) -> Path:
        return self.agent_run() / "harvest_now.flag"

    def harvest_done(self) -> Path:
        return self.agent_run() / "harvest_done.json"

    def harvest_lock(self) -> Path:
        return self.agent_run() / ".harvest.lock"

    def harvest_pid(self) -> Path:
        """감독 루프가 띄운 수확 자식의 pid(``{pid, install_id, started_at}`` — 원문 없음). 감독 루프가 먼저 죽어도
        ``stop_agent``·``uninstall`` 이 남은 수확 트리를 끌 수 있게(W1b)."""
        return self.agent_run() / "harvest.pid"

    def agent_logs(self) -> Path:
        return self.agent_dir() / "logs"

    def agent_log_file(self, utc_date) -> Path:
        y, m, d = _ymd(utc_date)
        return self.agent_logs() / f"agent_{y}{m}{d}.log"

    def copilot_manual(self) -> Path:
        return self.agent_dir() / "copilot_manual"

    def store_root(self) -> Path:
        return self.agent_dir() / "store"

    def store_dir(self, pc_id: str) -> Path:
        return self.store_root() / _check(PC_ID_RX, pc_id, "pc_id")

    def store_file(self, pc_id: str, kind: str, src: str, utc_date) -> Path:
        r"""로컬 원장 일자 파일 ``store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz``
        — 날짜는 쓰기(플러시) 시각의 **UTC** 날짜(계약 §3.10, TAB R-7)."""
        y, m, d = _ymd(utc_date, "utc_date")
        return (self.store_dir(pc_id) / "evidence" / _check(_KIND_RX, kind, "kind") / _check(_SRC_RX, src, "경로 ID")
                / f"{y}{m}" / f"{y}{m}{d}.jsonl.gz")

    def raw_cursor(self, pc_id: str) -> Path:
        return self.store_dir(pc_id) / "raw_cursor.json"

    def raw_cursor_lock(self, pc_id: str) -> Path:
        """커서 잠금 파일(msvcrt.locking, X-301)."""
        return self.store_dir(pc_id) / "raw_cursor.json.lock"

    def exe_meta(self, pc_id: str) -> Path:
        return self.store_dir(pc_id) / "exe_meta.json"

    def privacy_audit_file(self, utc_date) -> Path:
        r"""정제 감사 ``store\privacy_audit\YYYYMM\YYYYMMDD.jsonl``."""
        y, m, d = _ymd(utc_date, "utc_date")
        return self.store_root() / "privacy_audit" / f"{y}{m}" / f"{y}{m}{d}.jsonl"

    def edge_profile(self) -> Path:
        """코파일럿 전용 Edge 프로필(번들 밖)."""
        return self.lad() / "edge_copilot"

    def bridge_dir(self) -> Path:
        return self.lad() / "bridge"

    # 브리지 상태 파일(계약 §1.3 bridge\ · B §2.4 — 계약 v1.2 C19)
    def bridge_profile(self) -> Path:
        return self.bridge_dir() / "bridge_profile.json"

    def bridge_profile_id(self) -> Path:
        return self.bridge_dir() / "profile_id.txt"

    def bridge_trace(self) -> Path:
        return self.bridge_dir() / "trace.jsonl"

    def bridge_probe_last(self) -> Path:
        return self.bridge_dir() / "probe_last.json"

    def bridge_rawcap(self) -> Path:
        return self.bridge_dir() / "rawcap"

    def bridge_diagnose(self) -> Path:
        return self.bridge_dir() / "diagnose"

    def edge_lock(self) -> Path:
        return self.bridge_dir() / "session.lock.json"

    def ui_dir(self) -> Path:
        return self.lad() / "ui"

    def ui_server_json(self) -> Path:
        return self.ui_dir() / "ui_server.json"

    def ui_start_error(self) -> Path:
        return self.ui_dir() / "ui_start_error.txt"

    def ui_logs(self) -> Path:
        return self.ui_dir() / "logs"

    def ui_jobs(self) -> Path:
        return self.ui_dir() / "jobs"

    def ui_log_file(self, utc_date) -> Path:
        r"""화면 요청 로그 ``ui\logs\ui_YYYYMMDD.log``(UTC 날짜 — 메서드·경로·상태·ms 만, W2 통합 WP-35 CR)."""
        y, m, d = _ymd(utc_date, "utc_date")
        return self.ui_logs() / f"ui_{y}{m}{d}.log"

    def ui_job_file(self, job_id: str) -> Path:
        return self.ui_jobs() / (_check(JOB_ID_RX, job_id, "job_id") + ".json")

    def ui_job_stop_flag(self, job_id: str) -> Path:
        r"""화면 작업 정지 플래그 ``ui\jobs\<job_id>.stop``(협조형 취소 — cli ``--job`` 이 감시, 계약 §8.7, W2 통합)."""
        return self.ui_jobs() / (_check(JOB_ID_RX, job_id, "job_id") + ".stop")

    def offline_registry(self, offline_dir) -> Path:
        r"""오프라인 레지스트리 사본 ``<offline_dir>\lm27_registry.json``(사용자가 고른 바깥 폴더 ``team.offlineDir`` ·
        ``teamServer.publishDir`` — 계약 §5.1-7 예외 경로, 계약 v1.2 C19). 빈 값이면 ValueError."""
        if offline_dir is None or not os.fspath(offline_dir) or not str(os.fspath(offline_dir)).strip():
            raise ValueError("paths: 오프라인 폴더가 비었습니다")
        return Path(os.fspath(offline_dir)) / OFFLINE_REGISTRY_NAME

    def teamserver_default(self) -> Path:
        """팀 서버 저장소 기본 위치(``teamServer.storeDir`` 가 비었을 때)."""
        return self.lad() / "teamserver"
