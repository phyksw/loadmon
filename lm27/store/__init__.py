# -*- coding: utf-8 -*-
r"""로컬 원장 쓰기·읽기(계약 §2.3 · TAB R-7 · §1.6.7 · P I2) — ``%LOCALAPPDATA%\LoadMonitor27\agent\store\``.

  · ``SegmentWriter(paths, pc_id, kind, src)`` — 봉인 행(``SanitizedRow``)만 받는 유일한 저장 지점(``writer``).
  · ``read_store_since(paths, pc_id, kind, src, cursor)`` · ``iter_store(...)`` — 완전한 gzip 멤버까지만(``reader``).
  · ``load_raw_cursor(paths, pc_id)`` · ``save_raw_cursor(paths, pc_id, src, value)`` — 수집 증분 커서(``cursor``, X-301).
  · ``prune_store`` · ``purge_store`` — 보존·에이전트 제거(계약 O-16). 감사 파일은 ``lm27.privacy.audit``.

번들 세그먼트(``data\pcs``)는 이 패키지가 아니라 ``lm27.bundle.segment.write_segment`` 만 쓴다(X-175).
"""
from .cursor import LockTimeout, file_lock, load_raw_cursor, save_raw_cursor
from .reader import iter_store, read_store_since, store_files
from .writer import SegmentWriter, member_bytes, prune_store, purge_store, write_rows_file

__all__ = [
    "LockTimeout", "SegmentWriter", "file_lock", "iter_store", "load_raw_cursor", "member_bytes", "prune_store",
    "purge_store", "read_store_since", "save_raw_cursor", "store_files", "write_rows_file",
]
