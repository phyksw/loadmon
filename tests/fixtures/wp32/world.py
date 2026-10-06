# -*- coding: utf-8 -*-
r"""WP-32 시험 도우미 — %TEMP% 임시 프로그램 폴더(lm27t_wp32_*)에 합성 번들을 쓰고 분석 파이프라인을 돌린다.

    w = World()                                   # data\ 가 있는 임시 ROOT + 전용 %LOCALAPPDATA%(_lad) + 시험용 Paths
    w.put(rows())                                 # 합성 저장 행(WP-05 synth.stored_rows) → pc_id·kind 별 세그먼트 + manifest
    w.keyring()                                   # 주 키링(시험 트리 data\keys — 실제 키 아님)
    rc = w.analyze(ai=False)                      # lm27.pipeline.analyze.analyze(…, team_client=None, copilot_role=…)
    st = w.status()                               # 마지막 실행의 run_status.json

- 행은 WP-05 공용 생성기(``tests.fixtures.synth.stored_rows``)가 만든 '정제가 끝난 모양'이다 — 자리표시자 토큰뿐, 원문 없음.
- ``TPaths`` 는 이 WP 가 ``lm27\paths.py`` 에 CR 로 요청한 분석 폴더 하위 경로 메서드(``run_status_file``·
  ``analysis_time_file``·``analysis_hier``·``analysis_hier_file``·``analysis_report_file``·``analysis_root``)를 시험 안에서만
  흉내 낸다(WP-20·22·31 이 요청한 이름과 같다). 달력·설정 레지스트리는 시험 트리의 원본을 읽기만 한다.
- ``FakeBridge`` = 브리지 프로세스 대신 부르는 가짜(코파일럿 접속 없음). 호출을 기록하고 단계별 rc·요약을 돌려준다.
- 쓰기는 ``guard_write`` 로 확인한 %TEMP% 아래에만 한다(실제 트리·실제 %LOCALAPPDATA% 미접촉).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.bundle.ids import PcIdentity
from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import RULES_VERSION, load_keyring
from tests.fixtures.synth import stored_rows
from tests.fixtures.tree import guard_write

REPO = Path(__file__).resolve().parents[3]
REGISTRY = REPO / "config" / "settings_registry.json"
CALENDAR = REPO / "config" / "calendar.json"
D0, D1 = "2026-09-01", "2026-09-11"
AS_OF = "2026-09-12T09:00:00+09:00"
NOW = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)          # '지금'(시험 시계) — 기준 시각보다 늦다
CREATED = "2026-09-13T00:00:00Z"
TIME_FILES = ("env_slots.jsonl", "day_ledger.jsonl", "interval_ledger.jsonl", "tasks.json", "attrib.jsonl",
              "team_tables.json", "mm_month.json", "confirm_queue.json", "run_meta.json")
HIER_FILES = ("labels.json", "groups.json", "evidence_tags.jsonl", "queue.json", "proposals_snapshot.json",
              "hier_meta.json")


class TPaths(Paths):
    """시험용 Paths — 분석 하위 경로 메서드(CR 흉내)와 저장소 원본 달력(읽기만)."""

    def run_status_file(self, run_id):
        return self.analysis(run_id) / "run_status.json"

    def analysis_root(self):
        return self.analysis_current().parent

    def analysis_time_file(self, run_id, name):
        return self.analysis(run_id) / "time" / name

    def analysis_hier(self, run_id):
        return self.analysis(run_id) / "hier"

    def analysis_hier_file(self, run_id, name):
        return self.analysis(run_id) / "hier" / name

    def analysis_report_file(self, run_id, name):
        return self.analysis(run_id) / "report" / name

    def calendar_json(self):
        return CALENDAR


def rows(d0: str = D0, d1: str = D1, **kw) -> list[dict]:
    """합성 저장 행(WP-05 공용 생성기 — 기본 2026-09-01~09-11, 한 PC)."""
    return stored_rows(d0=date.fromisoformat(d0), d1=date.fromisoformat(d1), **kw)


def ident(pc_id: str) -> PcIdentity:
    return PcIdentity(pc_id=pc_id, id_source="machineguid", install_id=hashlib.sha256(pc_id.encode()).hexdigest()[:32],
                      agent_ver="0.1.0", kind_guess="cloud" if pc_id.startswith("pcx_") else "desktop",
                      tz={"utc_offset_min": 540, "windows_tz": ""}, reasons=(), kind_evidence={},
                      install_source="agent_json")


class FakeBridge:
    """브리지 호출 대역. ``rc`` = {분석 단계 id 또는 브리지 단계: rc}(기본 0), ``summary`` = {브리지 단계: 요약}.
    ``on_call(paths, run_id, stage, names)`` 로 ai_out 쓰기 같은 부작용을 흉내 낼 수 있다."""

    def __init__(self, rc=None, summary=None, on_call=None, raise_on=None):
        self.rc = dict(rc or {})
        self.summary = dict(summary or {})
        self.on_call = on_call
        self.raise_on = set(raise_on or ())
        self.calls: list[tuple[str, tuple[str, ...], str]] = []

    def __call__(self, paths, cfg, run_id, stage, names, cancel=None):
        self.calls.append((stage, tuple(names), run_id))
        if stage in self.raise_on:
            raise OSError("가짜 브리지 기동 실패")
        if self.on_call is not None:
            self.on_call(paths, run_id, stage, names)
        rc = self.rc.get(stage, max([self.rc.get(n, 0) for n in names] or [0]))
        stages = {n: self.summary[n] for n in names if n in self.summary}
        return {"rc": rc, "stages": stages}

    def stages(self) -> list[str]:
        return [c[0] for c in self.calls]


class World:
    r"""%TEMP%\lm27t_wp32_<rand>\ — data\ 가 있는 프로그램 폴더 모양 + 전용 %LOCALAPPDATA%(_lad)."""

    def __init__(self, prefix: str = "lm27t_wp32_"):
        self.root = guard_write(Path(tempfile.mkdtemp(prefix=prefix)))
        (self.root / "data").mkdir()
        self.lad = self.root / "_lad"
        self.paths = TPaths(self.root, lad=self.lad)
        self.runs: list[str] = []

    def cfg(self, overrides=None):
        return load_config(registry_path=REGISTRY, config_path=self.root / "no_config.json", overrides=overrides)

    def put(self, rws, *, split: int = 1, reverse: bool = False) -> int:
        """행을 (pc_id, kind) 별 세그먼트 ``split`` 개로 나눠 쓰고 manifest 에 올린다(순서 섞기 시험용 reverse). 세그먼트 수."""
        groups: dict = {}
        for r in rws:
            groups.setdefault((r["pc_id"], r["kind"]), []).append(r)
        keys = sorted(groups, reverse=reverse)
        n = 0
        for pc_id, kind in keys:
            lst = sorted(groups[(pc_id, kind)], key=lambda r: (r["ts_utc"], r["id"]))
            idt = ident(pc_id)
            pcreg.ensure_pc_dir(self.paths, idt, host="", now="2026-09-01T00:00:00Z")
            d = self.paths.pc_dir(pc_id)
            size = max(1, -(-len(lst) // max(1, split)))
            chunks = [lst[i:i + size] for i in range(0, len(lst), size)]
            if reverse:
                chunks.reverse()
            for ch in chunks:
                m = mf.load_manifest(d)
                info = seg.write_segment(d, kind, idt, ch, rules_ver=RULES_VERSION, kid=ch[0]["kid"], created=CREATED,
                                         manifest=m)
                m["segments"].append(info)
                mf.save_manifest(d, m)
                n += 1
        return n

    def keyring(self, same_as: World | None = None):
        """주 키링(시험 트리 data\\keys). ``same_as`` 를 주면 그 세계의 키링 파일을 그대로 옮긴다(같은 입력 = 같은 키 — T-02)."""
        if same_as is not None:
            from lm27.util.fsx import atomic_write
            atomic_write(self.paths.keyring(), same_as.paths.keyring().read_bytes())
        return load_keyring(self.paths.data(), None, create=True)

    def analyze(self, cfg=None, **kw) -> int:
        """분석 한 번(시험 시계는 실행마다 1분씩 — run_id 시각 부분이 실행 순서를 따른다)."""
        from lm27.pipeline.analyze import analyze, last_result
        args = {"from_": D0, "to": D1, "as_of": AS_OF, "ai": False, "now": NOW + timedelta(minutes=len(self.runs)),
                "team_client": None, "copilot_role": True}
        if kw.get("rerun"):
            args.pop("from_")
            args.pop("to")
            args.pop("as_of")
        args.update(kw)
        rc = analyze(self.paths, cfg if cfg is not None else self.cfg(), **args)
        rid = last_result().get("run_id")
        if rid:
            self.runs.append(rid)
        return rc

    @property
    def last(self) -> str:
        return self.runs[-1]

    def status(self, run_id: str | None = None) -> dict:
        return json.loads(self.paths.run_status_file(run_id or self.last).read_text(encoding="utf-8"))

    def stage(self, sid: str, run_id: str | None = None) -> dict:
        return next(s for s in self.status(run_id)["stages"] if s["id"] == sid)

    def current(self) -> dict | None:
        p = self.paths.analysis_current()
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def time_bytes(self, name: str, run_id: str | None = None) -> bytes:
        return self.paths.analysis_time_file(run_id or self.last, name).read_bytes()

    def hier_bytes(self, name: str, run_id: str | None = None) -> bytes:
        return self.paths.analysis_hier_file(run_id or self.last, name).read_bytes()

    def model_bytes(self, run_id: str | None = None) -> bytes:
        return self.paths.analysis_report_file(run_id or self.last, "report_model.json").read_bytes()

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
