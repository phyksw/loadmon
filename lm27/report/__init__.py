# -*- coding: utf-8 -*-
r"""보고서 — 공개 API(R §2.2 · §2.4 · 부록 A, 계약 §2.14 · §3.16 · §3.23 · §7.1 · §8.3).

    build_report(run_id) -> BuildResult       `lm27 report build --run <run_id>` — rc 0 만듦 · 4 다이제스트·판 같음(건너뜀) ·
                                              2 입력 일부 없음(만들되 경고) · 1 시간 결과 없음·모델 등식 실패(이전 보고서 유지)
    load_model(run_id, variant="full") -> dict   `report_model.json`(가림판은 허용 목록으로 다시 만든 사본)
    export(run_id, formats, variants, out_dir=None) -> ExportResult   `lm27 report export`(lm27.report.export)

`report_model.json`·`model_meta.json` 은 `data\derived\analysis\<run_id>\report\` 에 원자 쓰기(`Paths.analysis_report_file` —
CR). `model_meta.json` = `{report_version, inputs{논리 이름: sha16|missing}, cfg_used{읽은 키: 값}, built_at, model_sha16}`.
모델 안에는 `built_at` 을 넣지 않는다(같은 입력 = 같은 모델 바이트 — G-R1). 입력 다이제스트·보고서 판·읽은 설정 값이 모두
같고 모델 파일이 있으면 건너뛴다(rc 4, `force=True` 면 다시 만든다 — 계약 O-14 `report build --force` 자리).

이 `__init__` 은 하위 모듈을 최상위에서 import 하지 않는다(여러 작업 패키지가 나눠 가진 패키지 — 계약 §2 머리 · CR-09).
`lm27.report.export` 는 하위 모듈 이름과 R §2.2 재수출 함수 이름이 같다 — 패키지 속성 `export` 는 늘 그 하위 모듈이고, 모듈
객체를 부르면 `export(run_id, formats, variants, out_dir)` 가 돈다(`from lm27.report import export; export(...)` 가 import
순서와 관계없이 같다). cli 는 `lm27.report.export.export` 를 부른다(계약 §7.1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["MODEL_FILE", "META_FILE", "REPORT_VERSION", "SCHEMA", "SCHEMA_VERSION", "BuildResult", "ModelNotFound",
           "build_report", "export", "load_model", "model_status"]

REPORT_VERSION = "report/1"
SCHEMA = "lm27.report"
SCHEMA_VERSION = "1.0"
MODEL_FILE = "report_model.json"
META_FILE = "model_meta.json"
RC_OK, RC_FAIL, RC_PARTIAL, RC_NOOP = 0, 1, 2, 4


class ModelNotFound(FileNotFoundError):
    """그 실행의 보고서 모델이 아직 없다 — `lm27 report build --run <run_id>` 를 먼저."""


@dataclass
class BuildResult:
    """`build_report` 결과 — cli 는 `rc` 를 읽는다(계약 §8.3 `rc_of`). path = 모델 파일."""
    rc: int
    run_id: str
    path: str | None = None
    skipped: bool = False
    missing: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    problems: list = field(default_factory=list)
    message: str = ""

    def __fspath__(self) -> str:
        return self.path or ""


def _defaults(paths, cfg):
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    return paths, cfg


def _now_iso(cfg, now=None) -> str:
    """사람에게 보이는 시각 — 근무 시간대 ISO 8601 + 오프셋(계약 §9.4)."""
    from datetime import UTC, datetime

    from lm27.util.tz import fmt_offset, to_local
    off = int(cfg["time.tzOffsetMin"])
    n = now or datetime.now(UTC)
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    return to_local(n, off).strftime("%Y-%m-%dT%H:%M:%S") + fmt_offset(off)


def _cfg_same(prev_used, cfg) -> bool:
    """지난 빌드가 읽은 설정 값이 지금과 같은가(키가 없어졌으면 다름)."""
    from lm27.util.fsx import canon_bytes
    if not isinstance(prev_used, dict):
        return False
    try:
        now = {k: cfg[k] for k in sorted(prev_used)}
    except KeyError:
        return False
    return canon_bytes(now) == canon_bytes(dict(sorted(prev_used.items())))


def _rel(paths, p) -> str:
    a = os.path.abspath(os.fspath(p))
    root = os.path.abspath(os.fspath(paths.root))
    try:
        r = os.path.relpath(a, root)
    except ValueError:
        return a
    return a if r.startswith("..") else r.replace("\\", "/")


def build_report(run_id: str, *, force: bool = False, paths=None, cfg=None, inputs=None, now=None,
                 fallback=None) -> BuildResult:
    """R §2.4.1 `report build`: load_inputs → 분석층 → 모델 → 등식 검사 → 원자 쓰기(모델 → meta).
    키워드는 시험·파이프라인 주입점(paths·cfg·inputs·now·fallback — fallback = 브리지 단계 폴백 대체)."""
    from lm27.report import inputs as I
    from lm27.report import model as M
    from lm27.util import fsx
    paths, cfg = _defaults(paths, cfg)
    c = cfg.derive({})                       # 모델(분석층·보고서)이 읽은 키만 cfg_used 에(G-R9 — 읽힘 기록 분리).
    try:
        inp = inputs if inputs is not None else I.load_inputs(run_id, paths=paths, cfg=cfg)   # 적재 설정은 다이제스트가 덮는다
        mpath = I.report_file(paths, run_id, MODEL_FILE)
        meta_path = I.report_file(paths, run_id, META_FILE)
    except I.PathsMethodMissing as e:
        return BuildResult(rc=RC_FAIL, run_id=run_id, problems=[str(e)], message=str(e))
    codes = [w.get("code") for w in inp.warnings]
    if inp.refused:
        return BuildResult(rc=RC_FAIL, run_id=run_id, missing=sorted(inp.refused), warnings=codes,
                           problems=[f"시간 결과 없음: {', '.join(sorted(inp.refused))}"],
                           message="보고서 만들기 실패(시간 결과 없음) — 이전 보고서를 그대로 둡니다")
    digest = dict(sorted(inp.digests.items()))
    if not force:
        prev = fsx.read_json(meta_path, None, want=dict)
        if (isinstance(prev, dict) and prev.get("report_version") == REPORT_VERSION and prev.get("inputs") == digest
                and os.path.isfile(os.fspath(mpath)) and _cfg_same(prev.get("cfg_used"), c)):
            return BuildResult(rc=RC_NOOP, run_id=run_id, path=_rel(paths, mpath), skipped=True,
                               missing=sorted(inp.missing), warnings=codes, message="보고서가 이미 최신입니다")
    try:
        model = M.build_model(inp, c, fallback=fallback)
    except M.ModelCheckError as e:
        return BuildResult(rc=RC_FAIL, run_id=run_id, missing=sorted(inp.missing), warnings=codes,
                           problems=list(e.problems),
                           message="보고서 검사에 실패해 이전 보고서를 그대로 보여 줍니다")
    data = M.model_bytes(model)
    fsx.atomic_write(mpath, data)
    meta = {"report_version": REPORT_VERSION, "schema": SCHEMA, "schema_version": SCHEMA_VERSION, "inputs": digest,
            "cfg_used": c.used(), "built_at": _now_iso(cfg, now), "model_sha16": I.sha16(data)}
    fsx.atomic_write(meta_path, fsx.canon_bytes(meta))
    codes = [w.get("code") for w in model["flags"]["warnings"]]
    return BuildResult(rc=RC_PARTIAL if inp.missing else RC_OK, run_id=run_id, path=_rel(paths, mpath),
                       missing=sorted(inp.missing), warnings=codes,
                       message="보고서를 만들었습니다" + (" — 일부 입력이 없어 그 절은 비어 있습니다" if inp.missing else ""))


def load_model(run_id: str, variant: str = "full", *, paths=None, cfg=None, person_dir=None, registry=None) -> dict:
    """그 실행의 보고서 모델(R 부록 A). variant = full(파일 그대로) · redacted(허용 목록으로 다시 만든 가림판).
    파일이 없으면 `ModelNotFound`(cli 는 한국어 한 줄로 끝낸다)."""
    from lm27.report.inputs import report_file
    from lm27.util import fsx
    if variant not in ("full", "redacted"):
        raise ValueError("variant 는 full · redacted 중 하나입니다")
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    try:
        raw = fsx.read_bytes(report_file(paths, run_id, MODEL_FILE))
    except FileNotFoundError:
        raise ModelNotFound(f"보고서 모델이 없습니다 — 먼저 'lm27 report build --run {run_id}' 를 실행하세요") from None
    model = fsx.loads_strict(raw)
    if variant == "full":
        return model
    from lm27.report.model import redact_model
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    if person_dir is None:
        person_dir = fsx.read_json(paths.local_only_file("person_dir.json"), None, want=dict)
    return redact_model(model, registry, person_dir=person_dir, title_mode=str(cfg["team.unitTitleMode"]))


def model_status(run_id: str, *, paths=None) -> str:
    """'ok' · 'missing'(모델 없음) · 'stale'(보고서 판·스키마 MAJOR 가 다름 — 화면이 report_build 를 자동 1회, R §2.4.3)."""
    from lm27.report.inputs import report_file
    from lm27.util import fsx
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    meta = fsx.read_json(report_file(paths, run_id, META_FILE), None, want=dict)
    if not os.path.isfile(os.fspath(report_file(paths, run_id, MODEL_FILE))):
        return "missing"
    if not isinstance(meta, dict) or meta.get("report_version") != REPORT_VERSION or \
            str(meta.get("schema_version", "")).split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        return "stale"
    return "ok"


def __getattr__(name: str):
    """`lm27.report.export` — R §2.2 재수출. 하위 모듈과 이름이 같아 늘 그 모듈(호출 가능 — `export(run_id, formats,
    variants, out_dir)` 와 같은 일)을 돌려준다(함수·모듈이 import 순서에 따라 바뀌지 않게)."""
    if name == "export":
        import importlib
        return importlib.import_module("lm27.report.export")
    raise AttributeError(f"module 'lm27.report' has no attribute {name!r}")
