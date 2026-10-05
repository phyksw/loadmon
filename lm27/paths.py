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

    def ai_store(self, stage: str) -> Path:
        r"""AI 답 보존소 항목 커밋 ``data\ai\store\<stage>.items.jsonl``."""
        return self.data() / "ai" / "store" / (_check(_STAGE_RX, stage, "단계 이름") + ".items.jsonl")

    def ai_run(self, run_id: str) -> Path:
        return self.data() / "ai" / "runs" / _check(RUN_ID_RX, run_id, "run_id")

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

    def collect_stage_results(self, run_id: str) -> Path:
        r"""수집 실행 폴더 ``data\derived\collect\<run_id>\``."""
        return self.derived() / "collect" / _check(RUN_ID_RX, run_id, "run_id")

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

    def analysis(self, run_id: str) -> Path:
        return self.derived() / "analysis" / _check(RUN_ID_RX, run_id, "run_id")

    def analysis_current(self) -> Path:
        return self.derived() / "analysis" / "current.json"

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

    # ── %LOCALAPPDATA%\LoadMonitor27\ (PC 에 남는 것) ─────────────────────
    def lad(self) -> Path:
        if self._lad is not None:
            return self._lad
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

    def ui_job_file(self, job_id: str) -> Path:
        return self.ui_jobs() / (_check(JOB_ID_RX, job_id, "job_id") + ".json")

    def teamserver_default(self) -> Path:
        """팀 서버 저장소 기본 위치(``teamServer.storeDir`` 가 비었을 때)."""
        return self.lad() / "teamserver"
