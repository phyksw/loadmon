# -*- coding: utf-8 -*-
r"""로컬 원장 쓰기 — **SanitizedRow 를 받는 유일한 저장 지점**(계약 §2.3 · TAB R-7 · §1.6.7 · P I2 · L-11 ③).

``SegmentWriter(paths, pc_id, kind, src)``: ``append(row)`` 는 봉인 행만 받는다(``row._seal is records._SEAL`` 아니면
TypeError — 수집기가 dict 를 넣으면 즉시 실패) 그리고 행의 열 집합을 ``SCHEMAS[kind]`` 로 한 번 더 검증한다. ``flush()`` 는
모은 행을 메모리에서 gzip 멤버 하나로 만들어 **쓰기(플러시) 시각의 UTC 날짜** 파일
``agent\store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz`` 끝에 한 번의 write + flush + fsync 로 덧붙이고 닫는다
(핸들 보유 금지). 이벤트 날짜로 파일을 고르지 않는다 — (파일, 마지막 완전한 멤버 끝) 커서가 늦게 수확된 과거 사건까지
빠짐없이 잡는다(TAB R-7). 매 플러시 폴더를 확인하고 없으면 만든다. 읽는 쪽은 완전한 멤버까지만 읽는다(``reader``).

그 밖: ``write_rows_file(path, rows)`` — 정제 파이프 ``--mode new``(시험·일회성 출력) 전용, 봉인 검사 뒤 원자 쓰기 ·
``prune_store`` — 보존(``agent.storeKeepDays``) · ``purge_store`` — 에이전트 제거 ``--purge``(계약 O-16: 커서 잠금
``raw_cursor.json.lock`` 을 쥔 채 지운다 — 동시에 커서를 쓰는 파이프와 엇갈리지 않게). 감사 파일 삭제는 ``lm27.privacy.audit``.

쓰기 open 은 이 파일에만 있다(L-07 허용 — ``lm27\util\fsx.py``·``lm27\store\writer.py``·``lm27\bridge\fsio.py``).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.privacy import records as _rec
from lm27.util import fsx

from .cursor import CURSOR_LOCK_TIMEOUT_S, file_lock

__all__ = ["SegmentWriter", "member_bytes", "prune_store", "purge_store", "write_rows_file"]

_MONTH_RX = re.compile(r"^\d{6}$")
_DAY_RX = re.compile(r"^(\d{4})(\d{2})(\d{2})\.jsonl\.gz$")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")


def _sealed(row) -> None:
    if not isinstance(row, _rec.SanitizedRow) or getattr(row, "_seal", None) is not _rec._SEAL:
        raise TypeError("SegmentWriter: SanitizedRow(sanitize_record 통과 행)만 받습니다")
    _rec.check_row(row)


def member_bytes(rows) -> bytes:
    """봉인 행들 → 결정적 gzip 멤버 하나(``canon_bytes`` 한 줄씩 — mtime=0·filename='')."""
    raw = b"".join(fsx.canon_bytes(_rec.row_dict(r)) + b"\n" for r in rows)
    return fsx.gzip_bytes(raw)


class SegmentWriter:
    """한 (pc_id, kind, src) 의 로컬 원장 쓰기. ``clock`` = 지금 UTC 를 돌려주는 함수(시험 주입 — 파일 날짜)."""

    def __init__(self, paths, pc_id: str, kind: str, src: str, *, clock=None):
        if kind not in _rec.KINDS:
            raise ValueError("SegmentWriter: 알 수 없는 kind")
        if src not in _rec.SRCS_BY_KIND[kind]:
            raise ValueError("SegmentWriter: 경로 ID 와 kind 가 맞지 않습니다")
        if not isinstance(pc_id, str) or not _PC_RX.match(pc_id):
            raise ValueError("SegmentWriter: pc_id 형식이 아닙니다")
        self.paths, self.pc_id, self.kind, self.src = paths, pc_id, kind, src
        self.clock = clock
        self._rows: list = []
        self.written = 0
        self.last_path: Path | None = None
        self.last_member_sha256: str | None = None
        self.closed = False

    def append(self, row) -> None:
        """봉인 행 1개 추가(메모리). dict·위조 행은 TypeError, 열 위반·다른 kind·src·pc_id 는 ValueError."""
        if self.closed:
            raise ValueError("SegmentWriter: 닫힌 기록기")
        _sealed(row)
        d = row.data
        if row.kind != self.kind or d.get("src") != self.src or d.get("pc_id") != self.pc_id:
            raise ValueError("SegmentWriter: 행의 kind·src·pc_id 가 기록기와 다릅니다")
        self._rows.append(row)

    @property
    def pending(self) -> int:
        return len(self._rows)

    def _today(self) -> date:
        now = self.clock() if self.clock is not None else datetime.now(UTC)
        if isinstance(now, str):
            return date.fromisoformat(now[:10])
        return (now if now.tzinfo else now.replace(tzinfo=UTC)).astimezone(UTC).date()

    def flush(self) -> int:
        """모은 행을 gzip 멤버 1개로 덧붙인다(write + flush + fsync 후 닫기). 쓴 행 수(없으면 0)."""
        if not self._rows:
            return 0
        member = member_bytes(self._rows)
        path = self.paths.store_file(self.pc_id, self.kind, self.src, self._today())
        fsx.ensure_dir(path.parent)
        with open(fsx.longp(path), "ab") as fh:
            fh.write(member)
            fh.flush()
            os.fsync(fh.fileno())
        n = len(self._rows)
        self._rows = []
        self.written += n
        self.last_path = path
        self.last_member_sha256 = hashlib.sha256(member).hexdigest()
        return n

    def close(self) -> None:
        """남은 행이 있으면 덧붙이고 닫는다."""
        if self.closed:
            return
        try:
            self.flush()
        finally:
            self.closed = True

    def __enter__(self) -> SegmentWriter:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.close()
        else:
            self._rows = []                          # 예외 중에는 반쪽 묶음을 쓰지 않는다
            self.closed = True


def write_rows_file(path, rows) -> str:
    """정제 파이프 ``--mode new`` 출력(시험·일회성): 봉인 행 전부를 검사한 뒤 한 파일로 원자 쓰기(``.gz`` 면 gzip 멤버,
    아니면 평문 JSONL). 반환 = 쓴 바이트의 sha256 16진. 중간 실패면 파일이 생기지 않는다."""
    rows = list(rows)
    for r in rows:
        _sealed(r)
    raw = b"".join(fsx.canon_bytes(_rec.row_dict(r)) + b"\n" for r in rows)
    data = fsx.gzip_bytes(raw) if str(path).lower().endswith(".gz") else raw
    fsx.atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


def _src_dir(paths, pc_id: str, kind: str, src: str) -> Path:
    """그 흐름의 일자 파일들이 있는 폴더(일자 파일 경로의 두 단계 위 — 경로를 조립하지 않는다, L-08)."""
    return paths.store_file(pc_id, kind, src, "2020-01-01").parent.parent


def prune_store(paths, pc_id: str | None, keep_days: int, *, today=None) -> int:
    """보존(``agent.storeKeepDays``): 쓰기 날짜가 오늘(UTC) − keep_days 보다 이른 일자 파일을 지운다. 지운 파일 수.
    커서보다 앞선 파일이 지워지면 내보내기가 manifest ``gaps`` 에 ``store_pruned`` 로 남긴다(조용한 손실 금지).
    ``pc_id=None`` = store 아래 모든 pc_id(W1 통합 창 — WP-13 CR: MachineGuid 변경 TAB-B26 뒤 옛 pc_id 원장도 보존 기한에
    정리된다. 에이전트는 store 경로를 직접 지울 수 없다 — L-11)."""
    if isinstance(keep_days, bool) or not isinstance(keep_days, int) or keep_days < 1:
        raise ValueError("prune_store: keep_days 는 1 이상")
    if pc_id is None:
        root = paths.store_root()
        if not root.is_dir():
            return 0
        return sum(prune_store(paths, d.name, keep_days, today=today) for d in sorted(root.iterdir())
                   if d.is_dir() and _PC_RX.match(d.name))
    t = today if isinstance(today, date) else datetime.now(UTC).date()
    cutoff = t - timedelta(days=keep_days)
    n = 0
    for kind in _rec.KINDS:
        for src in _rec.SRCS_BY_KIND[kind]:
            base = _src_dir(paths, pc_id, kind, src)
            if not base.is_dir():
                continue
            for mdir in sorted(base.iterdir()):
                if not mdir.is_dir() or not _MONTH_RX.match(mdir.name):
                    continue
                for f in sorted(mdir.iterdir()):
                    m = _DAY_RX.match(f.name)
                    if not m:
                        continue
                    try:
                        fd = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
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


def purge_store(paths, pc_id: str | None = None, *, timeout_s: float = CURSOR_LOCK_TIMEOUT_S) -> int:
    """에이전트 제거 ``--purge`` 의 로컬 원장 삭제(계약 O-16 · L-11). ``pc_id`` 를 주면 그 PC 폴더만, 없으면 store 아래
    모든 pc_id 폴더(감사 폴더 ``privacy_audit`` 는 ``lm27.privacy.audit.purge_audit``). 그 PC 의 커서 잠금
    (``raw_cursor.json.lock``)을 쥔 채 지우고, 잠금을 놓은 뒤 잠금 파일과 폴더를 지운다. 지운 파일 수.
    다른 프로세스가 커서를 쓰는 중이면 ``LockTimeout``(아무것도 지우지 않는다)."""
    if pc_id is None:
        root = paths.store_root()
        if not root.is_dir():
            return 0
        return sum(purge_store(paths, d.name, timeout_s=timeout_s) for d in sorted(root.iterdir())
                   if d.is_dir() and _PC_RX.match(d.name))
    sdir = paths.store_dir(pc_id)
    if not sdir.is_dir():
        return 0
    lock = paths.raw_cursor_lock(pc_id)
    n = 0
    with file_lock(lock, timeout_s):
        for p in sorted(sdir.iterdir()):
            if p.name == lock.name:
                continue
            if p.is_dir():
                n += sum(1 for x in p.rglob("*") if x.is_file())
                shutil.rmtree(fsx.longp(p))
            else:
                os.remove(fsx.longp(p))
                n += 1
    shutil.rmtree(fsx.longp(sdir))
    return n
