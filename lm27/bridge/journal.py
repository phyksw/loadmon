# -*- coding: utf-8 -*-
r"""저널·항목 저장소(B §7.8~§7.10 · 계약 §3.17) — 항목 단위 커밋·재개·접기.

  항목 저장소 ``data\ai\store\<stage>.items.jsonl``(``Paths.ai_store``) — 커밋 기록, 실행을 넘어 유지(다시 묻지 않기 위한 캐시,
      번들 합치기 대상). 한 줄 = 커밋 하나 = 커널 덧붙이기 한 번(``fsio.append_line``) — 프로세스가 어느 순간에 죽어도
      잃는 것은 진행 중이던 질의 1건뿐(B7). 끊긴 마지막 줄은 읽을 때 건너뛰고 ``torn_lines`` 를 센다.
      ``{t:"commit", ts, stage, schema, ck, key, reg, run, rid, by, asks, final, ans, why?, retry_runs?, confirm?, reg_set?}``
  저널 ``data\ai\runs\<run_id>\<stage>.jsonl`` — ``req``·``resp``·``gate_blocked``·``exported``(원문 없음: 길이·해시·번호·
      key·ck·상태·사유 코드만).
  결과 봉투 ``…\<stage>.result.json`` · 조회 능력 ``…\capabilities.json``.

``ans`` 는 검증·정규화·입수 게이트를 통과한 답 필드다. 한 줄이 ``LINE_MAX`` 를 넘으면 가장 긴 문자열부터 잘라 ``trunc`` 표식.
저장소가 ``COMPACT_BYTES`` 를 넘으면(호출 시작 때만, 번들 잠금 안에서) ck 마다 마지막 커밋만 남겨 원자 교체한다.

경로: 실행 폴더 안 파일은 ``lm27.paths.Paths`` 의 ``ai_journal``·``ai_result``·``ai_capabilities`` 메서드를 쓴다(계약
§3.17 — CR). 메서드가 아직 없으면 ``Paths.ai_run(run_id)`` 폴더 아래 같은 이름(B §2.4·계약 §3.17 표 그대로).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from lm27.bridge import fsio
from lm27.bridge.clock import iso_now, iso_to_epoch

LINE_MAX = 64 * 1024                 # 저널·커밋 한 줄 상한(B §7.8)
COMPACT_BYTES = 20 * 1024 * 1024     # 저장소 정리 문턱(B §7.8)
LOCK_WAIT_S = 5.0                    # 저장소 정리 번들 잠금 대기(못 잡으면 이번엔 정리하지 않는다)
BY_VALUES = ("ai", "manual", "rule")
_RUN_FILES = {"journal": ("ai_journal", "{stage}.jsonl"), "result": ("ai_result", "{stage}.result.json"),
              "capabilities": ("ai_capabilities", "capabilities.json")}


def run_file(paths, run_id: str, which: str, stage: str | None = None) -> Path:
    """실행 폴더 안 파일 경로(저널·결과 봉투·조회 능력). ``Paths`` 메서드가 있으면 그것."""
    meth, pattern = _RUN_FILES[which]
    fn = getattr(paths, meth, None)
    if callable(fn):
        return Path(fn(run_id, stage) if stage is not None else fn(run_id))
    base = Path(paths.ai_run(run_id))
    return fsio.child(base, pattern.format(stage=stage or ""))


def _clip_line(rec: dict) -> dict:
    """한 줄이 LINE_MAX 를 넘으면 가장 긴 문자열 값부터 잘라 ``trunc`` 표식(B §7.8)."""
    raw = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= LINE_MAX:
        return rec
    rec = json.loads(raw)

    def strings(o, out):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str):
                    out.append((len(v), o, k))
                else:
                    strings(v, out)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, str):
                    out.append((len(v), o, i))
                else:
                    strings(v, out)
        return out
    for _n, holder, key in sorted(strings(rec.get("ans"), []), key=lambda x: -x[0]):
        holder[key] = holder[key][:max(0, len(holder[key]) // 4)]
        rec["trunc"] = True
        if len(json.dumps(rec, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= LINE_MAX:
            return rec
    rec["ans"] = None
    rec["trunc"] = True
    return rec


def _parse_lines(raw: str | None):
    """jsonl → (dict 목록, 끊긴 줄 수)."""
    rows, torn = [], 0
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            torn += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            torn += 1
    return rows, torn


def _order(c: dict, idx: int):
    """같은 ck 의 커밋 순서 — ts(epoch) → rid → 파일 순서(접기 멱등, B §7.10)."""
    t = iso_to_epoch(str(c.get("ts") or ""))
    return (t if t is not None else float("-inf"), str(c.get("rid") or ""), idx)


class Store:
    """단계 하나의 항목 저장소. ``last(ck)`` = 그 ck 의 마지막 커밋."""

    def __init__(self, paths, stage: str, clock):
        self.paths = paths
        self.stage = stage
        self.clock = clock
        self.path = Path(paths.ai_store(stage))
        self.torn_lines = 0
        self._last: dict[str, dict] = {}
        self._rank: dict[str, tuple] = {}
        self._n = 0
        self.loaded = False

    def load(self) -> Store:
        rows, torn = _parse_lines(fsio.read_text(self.path))
        self.torn_lines = torn
        self._last, self._rank, self._n = {}, {}, 0
        for c in rows:
            self._take(c)
        self.loaded = True
        return self

    def _take(self, c: dict) -> None:
        if c.get("t") != "commit" or not isinstance(c.get("ck"), str):
            return
        self._n += 1
        r = _order(c, self._n)
        ck = c["ck"]
        if ck not in self._rank or r >= self._rank[ck]:
            self._last[ck] = c
            self._rank[ck] = r

    def last(self, ck: str) -> dict | None:
        if not self.loaded:
            self.load()
        return self._last.get(ck)

    def all_last(self) -> dict:
        if not self.loaded:
            self.load()
        return dict(self._last)

    def commit(self, rec: dict) -> dict:
        """커밋 한 줄(원자 덧붙이기). ``ts``·``t``·``stage`` 는 여기서 채운다."""
        out = {"t": "commit", "ts": iso_now(self.clock), "stage": self.stage}
        out.update({k: v for k, v in rec.items() if v is not None or k == "ans"})
        out = _clip_line(out)
        fsio.append_line(self.path, out)
        if self.loaded:
            self._take(out)
        return out

    def compact(self, *, lock_factory=None) -> bool:
        """파일이 COMPACT_BYTES 를 넘으면 ck 마다 마지막 커밋만 남겨 원자 교체(번들 잠금 안). 했으면 True."""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return False
        if size <= COMPACT_BYTES:
            return False
        from lm27.bundle.lock import BundleBusy, BundleLock
        if lock_factory is None:
            def lock_factory():
                return BundleLock(self.paths, "fg-write", LOCK_WAIT_S)
        try:
            with lock_factory():
                self.load()
                keep = sorted(self._last.values(), key=lambda c: _order(c, 0))
                body = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                               for c in keep)
                fsio.write_atomic(self.path, body.encode("utf-8"))
                self.load()
        except BundleBusy:
            return False
        return True


class Journal:
    """실행 1회·단계 1개의 질의 저널(원문 없음)."""

    def __init__(self, paths, run_id: str, stage: str, clock, *, enabled: bool = True):
        self.path = run_file(paths, run_id, "journal", stage)
        self.stage = stage
        self.clock = clock
        self.enabled = enabled
        self.rows: list[dict] = []

    def write(self, t: str, **fields) -> dict:
        rec = {"t": t, "ts": iso_now(self.clock), "stage": self.stage}
        rec.update({k: v for k, v in fields.items() if v is not None})
        rec = _clip_line(rec)
        self.rows.append(rec)
        if self.enabled:
            fsio.append_line(self.path, rec)
        return rec

    def read(self) -> list[dict]:
        rows, _torn = _parse_lines(fsio.read_text(self.path))
        return rows


def read_journal(paths, run_id: str, stage: str) -> list[dict]:
    rows, _torn = _parse_lines(fsio.read_text(run_file(paths, run_id, "journal", stage)))
    return rows


def write_json(path, obj) -> None:
    """결과 봉투·능력 기록 원자 쓰기(정규 JSON)."""
    fsio.write_atomic(path, obj)
