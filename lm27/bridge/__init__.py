# -*- coding: utf-8 -*-
r"""LM27 코파일럿 브리지(B §2.2 · 계약 §2.12) — 공개 API: ``run_stages`` ``probe`` ``calibrate`` ``diagnose``
``manual_export`` ``manual_import``.

브리지 5계층: L0 세션(``session``·``cdp``·``js``·``env``) · L1 전송(``transport``·``transport_stub``·``manual``) · L2 교환
(``exchange``·``jsonx``·``gate``) · L3 배치 실행기(``runner``·``journal``·``budget``·``calibrate``·``capability``) · L4 단계
(``stages.*``). 분석 모듈과는 ``data\derived\ai_in``·``ai_out`` 파일로만 만난다.

이 패키지는 여러 작업 패키지가 나눠 가진다 — 이 ``__init__`` 은 하위 모듈을 최상위에서 import 하지 않고 공개 함수 안에서
지연 import 한다(계약 §2 머리 · CR-09). 그래서 ``lm27.bridge.stages.*`` import 는 세션·파일을 건드리지 않는다(L-30).
"""
from __future__ import annotations

__all__ = ["calibrate", "diagnose", "manual_export", "manual_import", "probe", "run_stages"]


def run_stages(run_id: str | None = None, stages=None, *, mode: str | None = None, paths=None, **kw) -> int:
    """단계들을 한 프로세스·한 세션에서 차례로(B §2.3) → rc(단계 rc 최악값 failed 1 > partial 2 > done·skipped 0)."""
    from lm27.bridge import runner
    specs = runner.resolve_specs(list(stages) if stages else None)
    rt = runner.open_runtime(paths, run_id, mode=mode, calibrate_model=specs[0].model_class if specs else None, **kw)
    try:
        runner.inbox_import(rt, {s.id: s for s in specs})
        results = runner.run_stages(rt, specs)
    finally:
        runner.close_runtime(rt)
    return runner.worst_rc(results)


def probe(*, roundtrip: bool = True, lookup: bool = False, paths=None, **env) -> dict:
    """연결 진단(B §12.2) → ``{ok, recommend, sec, env, checks[], rc}``(``probe_last.json`` 에도). P-CP 어댑터가 부른다."""
    from lm27.bridge import cli
    env = dict(env)
    env["paths"] = paths
    return cli.do_probe(env, roundtrip=roundtrip, lookup=lookup)


def __getattr__(name: str):
    """``lm27.bridge.calibrate`` — 공개 함수 이름과 하위 모듈 이름이 같다. 파이썬은 하위 모듈을 import 하면 패키지 속성을
    그 모듈로 덮어쓰므로(순서에 따라 함수였다 모듈이 된다), 함수를 두지 않고 **부를 수 있는 모듈**
    (``lm27.bridge.calibrate(force=…, model=…, paths=…)``)을 처음 쓸 때 지연 import 한다(PEP 562)."""
    if name == "calibrate":
        import importlib
        return importlib.import_module("lm27.bridge.calibrate")
    raise AttributeError(f"module 'lm27.bridge' has no attribute {name!r}")


def diagnose(*, model: bool = False, paths=None, **env) -> int:
    """화면 구조 덤프(B §12.4) → rc 0·1."""
    from lm27.bridge import cli
    env = dict(env)
    env["paths"] = paths

    class _A:
        pass
    a = _A()
    a.model = bool(model)
    return cli.cmd_diagnose(a, env)


def manual_export(stages=None, *, run_id: str | None = None, paths=None, **kw) -> int:
    """수동 묶음 내보내기(B §10.3) → rc(0 내보낼 것 없음 · 2 대기 생김 · 1 실패)."""
    from lm27.bridge import runner
    specs = runner.resolve_specs(list(stages) if stages else None)
    rt = runner.open_runtime(paths, run_id, mode="manual", **kw)
    try:
        results = runner.run_stages(rt, specs)
        k = rt.transport.open_count() if getattr(rt.transport, "kind", "") == "manual" else 0
    finally:
        runner.close_runtime(rt)
    worst = runner.worst_rc(results)
    return 1 if worst == 1 else (2 if k > 0 else 0)


def manual_import(text: str, *, paths=None, **kw) -> dict:
    """붙여넣은 답 반입(B §10.4) → 보고 ``{results, rejected, error, open, committed, retry, rc}``."""
    from lm27.bridge import runner
    table = {s.id: s for s in runner.resolve_specs(None)}
    rt = runner.open_runtime(paths, None, mode="manual", **kw)
    try:
        return runner.manual_import(text, rt=rt, specs=table)
    finally:
        runner.close_runtime(rt)
