# -*- coding: utf-8 -*-
r"""분석 결과 보관 정리(계약 §2.13 · R §5.3.4 · 설정 ``report.analysisKeep``).

    prune_analysis(paths, keep) -> list[str]      지운 run_id(이름순)
    keep_of(cfg) -> int                           ``report.analysisKeep``(이 모듈이 읽는 곳 — 레지스트리 owner)
    list_runs(paths) -> list[str]                 분석 실행 폴더 run_id(이름순 = 시각순)

규칙:
- ``data\derived\analysis\<run_id>\`` 폴더를 run_id 순(로컬 시각 ``YYYYMMDD-HHMMSS`` 이 앞이라 이름순 = 시각순)으로 세어
  **새것 ``keep`` 개**를 남기고 그보다 오래된 것을 지운다. ``keep`` 이 1 보다 작으면 1 로 본다.
- ``current.json`` 이 가리키는 실행(지금 화면이 보는 결과)은 몇 번째든 지우지 않는다(R §5.3.4).
- ``protect`` 로 넘긴 실행(진행 중인 분석·재분석 원본)도 지우지 않는다.
- run_id 모양이 아닌 이름·파일은 건드리지 않는다(``Paths.analysis(run_id)`` 가 모양을 다시 확인한다 — 트리 밖을 가리킬 수
  없다). 지우기는 폴더째(``shutil.rmtree``) — 화면이 파일을 쥐고 있어 실패하면 그 실행은 남기고 다음 정리 때 다시 본다.
- 지운 분석 실행과 **같은 run_id** 의 브리지 저널 폴더(``data\ai\runs\<run_id>``)도 함께 지운다(재개할 분석이 없다 — W2
  검토 L10). 그 밖의 ``data\ai``(다른 run_id 의 저널 — 수동 내보내기·반입 등, AI 답 보존소 ``data\ai\store``)와 내보내기
  (``out\personal`` — 자기 보관 설정 ``report.export.keep``)는 건드리지 않는다.

경로는 ``lm27.paths`` 메서드로만 만든다(L-08): 실행 폴더 = ``Paths.analysis(run_id)``, 그 부모(나열용) =
``Paths.analysis_root()``(있으면 — CR) 또는 ``Paths.analysis_current()`` 의 부모 폴더. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable

from lm27.util import fsx

__all__ = ["KEEP_MIN", "keep_of", "list_runs", "prune_analysis"]

KEEP_MIN = 1
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")          # 계약 §4.1 run_id


def keep_of(cfg) -> int:
    """보관 개수 설정(``report.analysisKeep`` — 기본 10, 하한 1)."""
    try:
        n = int(cfg["report.analysisKeep"])
    except (TypeError, ValueError):
        n = KEEP_MIN
    return max(KEEP_MIN, n)


def _root(paths):
    fn = getattr(paths, "analysis_root", None)
    return fn() if fn is not None else paths.analysis_current().parent


def list_runs(paths) -> list[str]:
    """분석 실행 폴더 이름(run_id 모양인 폴더만, 이름순). 분석 폴더가 없으면 빈 목록."""
    try:
        names = os.listdir(fsx.longp(_root(paths)))
    except OSError:
        return []
    out = []
    for nm in names:
        if not _RUN_RX.match(nm):
            continue
        try:
            if os.path.isdir(fsx.longp(paths.analysis(nm))):
                out.append(nm)
        except ValueError:
            continue
    return sorted(out)


def _current_run(paths) -> str | None:
    cur = fsx.read_json(paths.analysis_current(), None, want=dict)
    rid = cur.get("run_id") if isinstance(cur, dict) else None
    return rid if isinstance(rid, str) and _RUN_RX.match(rid) else None


def prune_analysis(paths, keep, *, protect: Iterable[str] = ()) -> list[str]:
    """새것 ``keep`` 개 + 현재 결과(current.json) + ``protect`` 를 남기고 나머지 실행 폴더를 지운다 → 지운 run_id 목록."""
    try:
        k = max(KEEP_MIN, int(keep))
    except (TypeError, ValueError):
        k = KEEP_MIN
    runs = list_runs(paths)
    keep_set = set(runs[-k:]) | {r for r in protect if isinstance(r, str)}
    cur = _current_run(paths)
    if cur:
        keep_set.add(cur)
    removed = []
    for rid in runs:
        if rid in keep_set:
            continue
        try:
            shutil.rmtree(fsx.longp(paths.analysis(rid)))
        except OSError:
            continue                                       # 화면이 쥐고 있음 — 다음 정리 때 다시
        _drop_bridge_run(paths, rid)
        removed.append(rid)
    return removed


def _drop_bridge_run(paths, rid: str) -> None:
    r"""정리한 분석 실행과 **같은 run_id** 의 브리지 저널 폴더(``data\ai\runs\<run_id>`` — 단계 저널·결과 봉투·조회 능력,
    B §7.8~§7.11)를 지운다. 분석 결과가 정리된 실행의 저널은 재개할 곳이 없다(W2 검토 L10 — 예전에는 끝없이 쌓였다).
    다른 run_id 의 저널(수동 내보내기·반입, 수집의 코파일럿 조회 등 분석 밖 브리지 실행)과 AI 답 보존소(``data\ai\store`` —
    실행을 넘어 쓰는 캐시)는 건드리지 않는다. 지우지 못하면(쥐고 있음) 남겨 둔다."""
    fn = getattr(paths, "ai_run", None)
    if fn is None:
        return
    try:
        d = fsx.longp(fn(rid))
    except ValueError:
        return
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
