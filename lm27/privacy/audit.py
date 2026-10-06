# -*- coding: utf-8 -*-
r"""정제 감사 기록기(P §15 · 계약 §3.13 · C10) — 범주별 건수·규칙 판·해시만. 원문·정제문·예시·경로·도메인 0(I8).

위치(계약 §1.3 · §3.13): 에이전트·프로그램 폴더 실행 모두 ``%LOCALAPPDATA%\LoadMonitor27\agent\store\privacy_audit\
YYYYMM\YYYYMMDD.jsonl``(평문 JSONL, 덧붙이기 — ``fsx.append_line``). [수집]의 내보내기(``lm27.bundle.export``)가 그
PC 의 ``privacy_audit`` 세그먼트로 옮기며 봉투 ``id``·``kind``·``src``(단계 이름)를 붙인다. ``data\pcs`` 에는 직접 쓰지
않는다(L-08 — 세그먼트는 ``write_segment`` 만).

이벤트 본문 키는 P §15.2 의 18개뿐이며, 경로 ID 키 이름은 ``path_id`` 다(계약 v1.2 C10 — 봉투 ``src`` = 단계 이름과
겹치지 않게): ``ev ts_utc pc_id stage path_id rules_ver rules_hash config_hash kid rows_in rows_out dropped masked priv
ad err out_sha256 dur_ms``. 값은 숫자·판·16진 해시·범주 코드·경로 ID·단계 이름뿐.

계수기(``add(counter, key, n)``) → 본문 사전: ``masked``·``remask`` → masked(게이트 재가림 범주) · ``dropped`` → dropped ·
``priv`` → priv · ``ad`` → ad · ``err`` → err · 그 밖 이름공간(``key``·``cfg``·``merge``·``gate_team``·``selftest`` …)은
err 에 ``<이름공간>.<코드>``(예 ``key.created``·``cfg.bad_regex``)로 싣는다 — 본문 키 18개를 지키면서 P §20 표의 코드를 남긴다.

버린 행 계수 책임(WP-15 질의 확정): ``sanitize_record`` 가 행마다 결과(stored·dropped 사유·가린 범주·공사·광고)를
이 기록기에 스스로 센다(``_note_outcome``) — 수집기가 잊어도 '조용한 삭제'가 생기지 않는다(I9). 수집기가 같은 사유를
``add("dropped", 사유, n)`` 로 또 넘기면 **사유별로 큰 쪽**을 쓴다(이중 계수 방지). ``rows_in``·``rows_out`` 도 기록기가 센
값이 기본이고 ``flush(rows_in=…, rows_out=…)`` 로 넘기면 그 값을 쓴다.

기록 실패(읽기 전용·잠김)는 수집을 멈추지 않는다: 계수기를 그대로 두고 다음 ``flush`` 에 합쳐 쓰며 ``failed`` 를 센다
(P §20 '감사 결손'). 이 모듈은 에이전트 bin 사본에도 들어간다(표준 라이브러리 + ``lm27.paths``·``lm27.util``).
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

from lm27.paths import Paths
from lm27.util import fsx

from .rules import RULES_VERSION

__all__ = ["AUDIT_EVS", "AUDIT_KEYS", "AuditSink", "audit_paths", "prune_audit", "purge_audit"]

AUDIT_KEYS = ("ev", "ts_utc", "pc_id", "stage", "path_id", "rules_ver", "rules_hash", "config_hash", "kid", "rows_in",
              "rows_out", "dropped", "masked", "priv", "ad", "err", "out_sha256", "dur_ms")
AUDIT_EVS = ("collect_batch", "load_resanitize", "gate_copilot", "gate_prompt", "gate_team", "rewrite_redact", "key",
             "config", "selftest", "merge")
BODY_DICTS = ("dropped", "masked", "priv", "ad", "err")
_COUNTER_BODY = {"masked": "masked", "remask": "masked", "dropped": "dropped", "priv": "priv", "ad": "ad", "err": "err"}
_NUM_FIELDS = ("rows_in", "rows_out", "dur_ms")
_STR_FIELDS = ("out_sha256", "config_hash", "kid")
_COUNTER_RX = re.compile(r"^[a-z][a-z_]{1,15}$")
_CODE_RX = re.compile(r"^(?:[a-z][a-z0-9_.:\-]{0,47}|[A-Z][A-Za-z0-9_]{0,47})$")
_DIGITS9 = re.compile(r"\d{9,}")
_STAGE_RX = re.compile(r"^[a-z][a-z0-9_:\-]{0,47}$")
_PATH_ID_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|[a-z][a-z0-9_]{1,15})$")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_HEX16_RX = re.compile(r"^[0-9a-f]{16}$")
_SHA_RX = re.compile(r"^[0-9a-f]{16}(?:[0-9a-f]{48})?$")
_KID_RX = re.compile(r"^k[0-9a-f]{8}$")
_INVALID = "invalid"


def _default_ev(stage: str) -> str:
    """단계 이름 → 기본 이벤트 이름(P §15.2)."""
    head = stage.split(":", 1)[0]
    return {"agent": "collect_batch", "collect": "collect_batch", "load": "load_resanitize", "copilot": "gate_copilot",
            "team": "gate_team", "team_server": "gate_team", "key": "key", "config": "config", "selftest": "selftest",
            "merge": "merge", "redact": "rewrite_redact"}.get(head, "collect_batch")


def _code(key) -> str:
    """계수기 코드 검증 — 값이 아니라 코드만 싣는다(형식 밖이면 'invalid')."""
    k = str(key) if isinstance(key, str) else ""
    return k if k and _CODE_RX.match(k) and not _DIGITS9.search(k) and "@" not in k else _INVALID


def audit_paths(data_dir=None, agent_dir=None, paths=None) -> Paths:
    r"""감사 파일 위치를 아는 ``Paths``: ``agent_dir`` 가 있으면 그 부모를 LAD 로, 아니면 ``data_dir`` 의 부모를 ROOT 로."""
    if paths is not None:
        return paths
    if agent_dir is not None:
        return Paths(lad=Path(os.fspath(agent_dir)).parent)
    if data_dir is not None:
        return Paths(Path(os.fspath(data_dir)).parent)
    return Paths()


class _StoreAuditWriter:
    """이벤트 1건 → 그 날(UTC) 감사 파일에 한 줄(canon JSON). 실패는 OSError 로 올린다."""

    def __init__(self, paths: Paths):
        self.paths = paths

    def __call__(self, ev: dict) -> None:
        day = ev["ts_utc"][:10]
        fsx.append_line(self.paths.privacy_audit_file(day), fsx.canon_bytes(ev).decode("utf-8"))


class AuditSink:
    """감사 기록기. ``AuditSink(writer, pc_id, stage, src)`` — writer 는 이벤트 dict 를 받는 호출 가능 객체
    (``AuditSink.open`` 은 감사 파일 쓰기를 붙인다 — 브리지·게이트·팀 업로더는 이것만 쓴다)."""

    def __init__(self, writer, pc_id: str, stage: str, src: str, *, clock=None, kid: str | None = None,
                 config_hash: str | None = None, rules_hash: str | None = None):
        if not isinstance(stage, str) or not _STAGE_RX.match(stage):
            raise ValueError("AuditSink: 단계 이름 형식")
        if not isinstance(src, str) or not _PATH_ID_RX.match(src):
            raise ValueError("AuditSink: 경로 ID 형식")
        if pc_id is not None and (not isinstance(pc_id, str) or not _PC_RX.match(pc_id)):
            raise ValueError("AuditSink: pc_id 형식")
        self.writer = writer
        self.pc_id = pc_id
        self.stage = stage
        self.src = src
        self.kid = kid
        self.config_hash = config_hash
        self.rules_hash = rules_hash
        self.clock = clock
        self.failed = 0                     # 기록 실패 횟수(감사 결손 표시용)
        self.written = 0
        self.after_flush = None             # 묶음 끝 훅(기록 성공 뒤) — 레코드 문맥이 로컬 사전 갱신을 붙인다
        self._reset()

    @classmethod
    def open(cls, data_dir, pc_id: str, stage: str, src: str, agent_dir=None, *, paths=None, clock=None) -> AuditSink:
        r"""경로 해석(P §15.1 · 계약 §3.13): 감사 파일은 언제나 ``Paths.privacy_audit_file(UTC 날짜)``. ``agent_dir``
        (에이전트 모드) 또는 ``data_dir``(프로그램 폴더 ``<ROOT>\data``)로 LAD 를 정한다."""
        return cls(_StoreAuditWriter(audit_paths(data_dir, agent_dir, paths)), pc_id, stage, src, clock=clock)

    # ── 계수 ──────────────────────────────────────────────────────────
    def _reset(self) -> None:
        self._d = {k: {} for k in BODY_DICTS}
        self._auto_drop: dict = {}
        self._man_drop: dict = {}
        self._auto_in = 0
        self._auto_out = 0

    def add(self, counter: str, key: str, n: int = 1) -> None:
        """계수기 하나 더하기. counter ∈ masked·remask·dropped·priv·ad·err 또는 다른 이름공간(err 에 '이름.코드')."""
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("AuditSink.add: n 은 0 이상의 정수")
        if not n:
            return
        c = counter if isinstance(counter, str) and _COUNTER_RX.match(counter) else "err"
        code = _code(key)
        if c == "dropped":
            self._man_drop[code] = self._man_drop.get(code, 0) + n
            return
        body = _COUNTER_BODY.get(c)
        if body is None:
            body, code = "err", _code(c + "." + code) if code != _INVALID else c + "." + _INVALID
        d = self._d[body]
        d[code] = d.get(code, 0) + n

    def _note_outcome(self, status: str, reason: str | None, hits: dict | None, priv: str | None = None,
                      ad: str | None = None, ad_partial: bool = False) -> None:
        """``sanitize_record`` 전용 — 행 결과 하나를 센다(입력 1, 저장이면 출력 1, 버림 사유·가린 범주·공사·광고)."""
        self._auto_in += 1
        if status == "stored":
            self._auto_out += 1
            for k, v in (hits or {}).items():
                self.add("masked", k, int(v))
            if priv:
                self.add("priv", priv)
        elif status == "dropped":
            code = _code(reason or "unknown")
            self._auto_drop[code] = self._auto_drop.get(code, 0) + 1
        if ad:
            self.add("ad", ad)
            if ad_partial:
                self.add("ad", "partial")

    def counts(self) -> dict:
        """지금까지 센 것(쓰기 전) — 시험·화면용 사본."""
        out = {k: dict(v) for k, v in self._d.items()}
        out["dropped"] = self._dropped()
        out["rows_in"], out["rows_out"] = self._auto_in, self._auto_out
        return out

    def _dropped(self) -> dict:
        keys = set(self._auto_drop) | set(self._man_drop)
        return {k: max(self._auto_drop.get(k, 0), self._man_drop.get(k, 0)) for k in sorted(keys)}

    # ── 기록 ──────────────────────────────────────────────────────────
    def _now(self) -> str:
        if self.clock is not None:
            t = self.clock()
            if isinstance(t, str):
                return t
            return (t if t.tzinfo else t.replace(tzinfo=UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def event(self, ev: str | None = None, **numbers) -> dict:
        """지금 계수로 이벤트 본문(P §15.2 18키 — 값 없는 선택 키는 뺀다)을 만든다. 계수기는 그대로 둔다."""
        from .rules import RULES_HASH
        e = {"ev": ev if ev in AUDIT_EVS else _default_ev(self.stage), "ts_utc": self._now(), "stage": self.stage,
             "path_id": self.src, "rules_ver": RULES_VERSION, "rules_hash": self.rules_hash or RULES_HASH}
        if self.pc_id:
            e["pc_id"] = self.pc_id
        for k in BODY_DICTS:
            e[k] = dict(sorted(self._d[k].items())) if k != "dropped" else self._dropped()
        e["rows_in"], e["rows_out"] = self._auto_in, self._auto_out
        bad = 0
        for k, v in numbers.items():
            if k in _NUM_FIELDS and not isinstance(v, bool) and isinstance(v, (int, float)) and v >= 0:
                e[k] = int(v)
            elif k == "out_sha256" and isinstance(v, str) and _SHA_RX.match(v):
                e[k] = v
            elif k == "config_hash" and isinstance(v, str) and _HEX16_RX.match(v):
                e[k] = v
            elif k == "kid" and isinstance(v, str) and _KID_RX.match(v):
                e[k] = v
            elif v is not None:
                bad += 1
        if "kid" not in e and self.kid and _KID_RX.match(self.kid):
            e["kid"] = self.kid
        if "config_hash" not in e and self.config_hash and _HEX16_RX.match(self.config_hash):
            e["config_hash"] = self.config_hash
        if bad:
            e["err"] = dict(sorted({**e["err"], "audit.bad_field": e["err"].get("audit.bad_field", 0) + bad}.items()))
        return e

    def flush(self, ev: str | None = None, **numbers) -> bool:
        """이벤트 1줄 기록 후 계수기 초기화. ``numbers`` = rows_in·rows_out·dur_ms·out_sha256·config_hash·kid(그 밖은
        err ``audit.bad_field`` 로 센다). 기록 실패면 계수기를 그대로 두고 False(다음 flush 에 합쳐 쓴다)."""
        e = self.event(ev, **numbers)
        try:
            self.writer(e)
        except OSError:
            self.failed += 1
            return False
        self.written += 1
        self._reset()
        hook = self.after_flush
        if hook is not None:
            hook()
        return True


# ───────────────────────────── 보존·제거(P §15.1 · 계약 O-16) ─────────────────────────────
_MONTH_RX = re.compile(r"^\d{6}$")
_DAYFILE_RX = re.compile(r"^(\d{4})(\d{2})(\d{2})\.jsonl$")


def _audit_root(paths: Paths) -> Path:
    """감사 폴더(``store\\privacy_audit``) — 일자 파일 경로의 두 단계 위(경로를 조립하지 않는다 — L-08)."""
    return paths.privacy_audit_file("2020-01-01").parent.parent


def prune_audit(paths: Paths, keep_months: int, *, today=None) -> int:
    """에이전트 로컬 감사 원장 보존(``privacy.audit.retentionMonths``): 오늘(UTC)로부터 keep_months 달보다 오래된
    일자 파일을 지운다. 지운 파일 수. 번들 세그먼트는 건드리지 않는다."""
    if isinstance(keep_months, bool) or not isinstance(keep_months, int) or keep_months < 1:
        raise ValueError("prune_audit: keep_months 는 1 이상")
    d = today if isinstance(today, date) else datetime.now(UTC).date()
    y, m = d.year, d.month - keep_months
    while m <= 0:
        y, m = y - 1, m + 12
    cutoff = date(y, m, 1)                              # 이 달 1일보다 앞선 일자 파일을 지운다
    root = _audit_root(paths)
    n = 0
    if not root.is_dir():
        return 0
    for mdir in sorted(root.iterdir()):
        if not mdir.is_dir() or not _MONTH_RX.match(mdir.name):
            continue
        for f in sorted(mdir.iterdir()):
            mm = _DAYFILE_RX.match(f.name)
            if not mm or not f.is_file():
                continue
            try:
                fd = date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
            except ValueError:
                continue
            if fd < cutoff:
                try:
                    os.remove(fsx.longp(f))
                    n += 1
                except OSError:
                    continue
        try:
            if not any(mdir.iterdir()):
                os.rmdir(fsx.longp(mdir))
        except OSError:
            pass
    return n


def purge_audit(paths: Paths) -> int:
    """에이전트 제거 ``--purge`` 의 감사 파일 삭제(계약 O-16 · L-11 — 감사 파일은 ``lm27.privacy`` 함수로만).
    지운 파일 수. 폴더가 없으면 0."""
    root = _audit_root(paths)
    if not root.is_dir():
        return 0
    n = sum(1 for p in root.rglob("*") if p.is_file())
    shutil.rmtree(fsx.longp(root), ignore_errors=False)
    return n
