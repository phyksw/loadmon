# -*- coding: utf-8 -*-
r"""브리지 전송 계측(B §5.9·§11.7) — ``%LOCALAPPDATA%\LoadMonitor27\bridge\trace.jsonl`` 한 줄 = 전송 1회.

남기는 것: 단계·rid·단(rung)·단계(phase)·상태·길이·초·완료 판정 방식·회수 경로·모델 표기·업무 모드·웹 노출.
남기지 않는 것: 프롬프트·답 원문, 페이지 글, 경로, 이름(LM24 ``trace`` 원칙 계승). 허용 키 밖은 버리고,
문자열 값은 60자에서 자른다. ``bridge.traceMaxBytes`` 를 넘으면 ``trace.jsonl.1`` 로 갈아 끼운다.

계측 실패는 판정을 막지 않는다 — 쓰기 오류는 ``failures`` 로 세고 경고 1줄만 낸다.
"""
from __future__ import annotations

import json
import sys

from lm27.bridge import fsio, settings
from lm27.bridge.clock import iso_now

# 계측 줄 허용 키(B §5.9 + 질의·진단 보조). 값은 수·참거짓·짧은 코드 문자열만.
FIELDS = ("t", "run", "stage", "seq", "kind", "rid", "rung", "fresh", "chat_seq", "chat_turn", "phase", "status",
          "reason", "sec", "gen_sec", "first_token_sec", "in", "injected", "reply", "done_by", "pick", "busy_seen",
          "resent", "waited", "model_wanted", "model_used", "work_mode", "web_exposed", "transport", "role", "port",
          "launched", "origin_mode", "identity", "error")


def _clean(v):
    if v is None or isinstance(v, bool | int):
        return v
    if isinstance(v, float):
        return round(v, 1)
    if isinstance(v, str):
        return v.replace("\n", " ").replace("\r", " ")[:settings.TRACE_STR_MAX]
    return None


class Tracer:
    """``Tracer(paths, cfg, clock, run_id=…)``. ``write(**row)`` → 한 줄. ``enabled=False`` 면 메모리에만 남긴다(시험)."""

    def __init__(self, paths, cfg, clock, *, run_id: str = "", enabled: bool = True):
        self.paths = paths
        self.cfg = cfg
        self.clock = clock
        self.run_id = run_id or ""
        self.enabled = enabled
        self.seq = 0
        self.failures = 0
        self.rows: list[dict] = []           # 이 프로세스에서 쓴 줄(요약·시험용, 원문 없음)
        self._warned = False

    @property
    def path(self):
        return fsio.bridge_file(self.paths, "trace")

    def write(self, **row) -> dict:
        self.seq += 1
        out = {"t": iso_now(self.clock), "run": self.run_id, "seq": self.seq}
        for k in FIELDS:
            if k in row and k not in out:
                v = _clean(row[k])
                if v is not None:
                    out[k] = v
        self.rows.append(out)
        if self.enabled:
            try:
                fsio.rotate(self.path, self.cfg.trace_max_bytes)
                fsio.append_line(self.path, out)
            except OSError as e:
                self.failures += 1
                if not self._warned and sys.stderr is not None:
                    self._warned = True
                    sys.stderr.write(f"[경고] 브리지 계측 기록 실패({type(e).__name__}) — 판정에는 영향 없음\n")
        return out

    def send(self, req, res, *, stage: str = "", rung: int = 0, status: str = "", sec: float = 0.0,
             chat_turn: int | None = None, web_exposed: bool | None = None, kind: str = "send") -> dict:
        """전송 1회(``SendRequest`` + ``SendResult``) 기록."""
        return self.write(kind=kind, stage=stage or getattr(req, "stage", ""), rid=getattr(req, "rid", ""),
                          rung=rung, fresh=bool(getattr(req, "fresh", False)), chat_seq=getattr(res, "chat_seq", 0),
                          chat_turn=chat_turn, phase=res.phase, status=status, sec=sec, gen_sec=res.gen_sec,
                          first_token_sec=res.first_token_sec, **{"in": res.in_chars},
                          injected=res.injected_chars, reply=len(res.body or ""), done_by=res.done_by, pick=res.pick,
                          busy_seen=res.busy_seen, resent=res.resent, waited=res.waited_idle_sec,
                          model_wanted=getattr(req, "model", ""), model_used=res.model_used,
                          work_mode=res.work_mode, web_exposed=web_exposed, error=res.error)


def iter_rows(path):
    """계측 파일의 줄들(dict). 깨진 줄은 건너뛴다. 파일이 없으면 빈 반복."""
    raw = fsio.read_text(path)
    if not raw:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj
