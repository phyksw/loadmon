# -*- coding: utf-8 -*-
r"""로컬 원장 읽기(계약 §2.3 · §3.7 · TAB R-7 · TAB-B25) — 완전한 gzip 멤버까지만, 커서 이후분을 쓰기 순서대로.

``read_store_since(paths, pc_id, kind, src, cursor) -> (records, new_cursor, gap | None)``
  · 일자 파일(쓰기 UTC 날짜 이름)을 이름 순으로, ``cursor.file`` 부터 ``cursor.offset``(압축 바이트) 뒤를 읽는다.
  · ``.jsonl.gz``: 멤버를 하나씩 끝까지 풀 수 있을 때만 받는다 — 잘린 마지막 멤버(쓰는 중이거나 깨짐)는 읽지 않고 오프셋을
    그 앞에 둔다(다음 읽기가 마저 받는다). 깨진 멤버(zlib 오류) 뒤에 다음 멤버가 있으면 건너뛰고 ``gap`` 을 남긴다
    (``store_corrupt`` — 조용한 손실 금지).
  · ``kind = "privacy_audit"``(src 는 흐름 이름 ``agent``): pc 구분 없는 평문 ``store\privacy_audit\YYYYMM\YYYYMMDD.jsonl``
    을 마지막 ``\n`` 까지만.
  · 커서 파일이 지워졌으면(보존 정리) 그 뒤 파일부터 읽고 ``gap = {from_t, to_t, reason: "store_pruned"}``.
  · 커서 ``file`` 은 ``agent\store`` 기준 ``/`` 상대 경로(계약 §3.7): 증거 ``<pc_id>/evidence/<kind>/<src>/YYYYMM/YYYYMMDD.jsonl.gz``,
    감사 ``privacy_audit/YYYYMM/YYYYMMDD.jsonl``. ``offset`` = 마지막 완전한 멤버 끝(평문은 마지막 ``\n`` 다음).

``iter_store(paths, pc_id, kind, src, d0, d1)`` — 쓰기 날짜 [d0, d1] 일자 파일의 레코드(완전한 멤버만).
행은 dict 그대로 돌려준다(이미 정제된 저장 행 — 다시 봉인하지 않는다). 깨진 JSON 줄은 건너뛴다.
"""
from __future__ import annotations

import re
import zlib
from datetime import date

from lm27.util import fsx

__all__ = ["AUDIT_KIND", "iter_store", "read_store_since", "store_files"]

AUDIT_KIND = "privacy_audit"
CHUNK = 64 * 1024
_MONTH_RX = re.compile(r"^\d{6}$")
_GZ_RX = re.compile(r"^(\d{8})\.jsonl\.gz$")
_PLAIN_RX = re.compile(r"^(\d{8})\.jsonl$")
_GZ_MAGIC = b"\x1f\x8b\x08"


def store_files(paths, pc_id: str, kind: str, src: str) -> list:
    """[(상대 경로('/' — agent\\store 기준), 절대 경로, 'YYYYMMDD')] 이름(=쓰기 날짜) 순."""
    if kind == AUDIT_KIND:
        base = paths.privacy_audit_file("2020-01-01").parent.parent
        pre, rx = "privacy_audit", _PLAIN_RX
    else:
        base = paths.store_file(pc_id, kind, src, "2020-01-01").parent.parent
        pre, rx = f"{pc_id}/evidence/{kind}/{src}", _GZ_RX
    if not base.is_dir():
        return []
    out = []
    for mdir in base.iterdir():
        if not mdir.is_dir() or not _MONTH_RX.match(mdir.name):
            continue
        for f in mdir.iterdir():
            m = rx.match(f.name)
            if m and m.group(1)[:6] == mdir.name and f.is_file():
                out.append((f"{pre}/{mdir.name}/{f.name}", f, m.group(1)))
    return sorted(out)


def _loads_lines(raw: bytes, recs: list) -> int:
    bad = 0
    for ln in raw.split(b"\n"):
        if not ln.strip():
            continue
        try:
            obj = fsx.loads_strict(ln)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            recs.append(obj)
        else:
            bad += 1
    return bad


def _member(mv: memoryview, pos: int):
    """pos 에서 시작하는 gzip 멤버 하나 → (평문, 끝 오프셋) · 잘렸으면 (None, pos). 깨졌으면 zlib.error."""
    d = zlib.decompressobj(wbits=31)
    out, fed, n = [], pos, len(mv)
    while fed < n:
        chunk = mv[fed:fed + CHUNK]
        fed += len(chunk)
        out.append(d.decompress(chunk))
        if d.eof:
            return b"".join(out), fed - len(d.unused_data)
    return None, pos


def _read_gz(data: bytes, pos: int):
    """pos 부터 완전한 멤버만 → (레코드, 끝 오프셋, 깨짐 여부)."""
    recs, corrupt = [], False
    mv = memoryview(data)
    while pos < len(data):
        try:
            raw, end = _member(mv, pos)
        except zlib.error:
            nxt = data.find(_GZ_MAGIC, pos + 1)
            if nxt < 0:
                break
            corrupt, pos = True, nxt
            continue
        if raw is None:
            break                                     # 잘린 마지막 멤버 — 다음에 다시 본다
        _loads_lines(raw, recs)
        pos = end
    return recs, pos, corrupt


def _read_plain(data: bytes, pos: int):
    end = data.rfind(b"\n")
    if end < pos:
        return [], pos, False
    recs: list = []
    _loads_lines(data[pos:end + 1], recs)
    return recs, end + 1, False


def _day_start(day8: str) -> str:
    return f"{day8[0:4]}-{day8[4:6]}-{day8[6:8]}T00:00:00Z"


def read_store_since(paths, pc_id: str, kind: str, src: str, cursor):
    """커서 이후 레코드 → ``(records, new_cursor, gap | None)``. 새것이 없으면 records 는 빈 목록이고 커서는 그대로
    (파일이 하나도 없으면 받은 커서를 돌려준다)."""
    files = store_files(paths, pc_id, kind, src)
    cur = dict(cursor) if isinstance(cursor, dict) else None
    gap = None
    start_idx, start_off = 0, 0
    if cur and isinstance(cur.get("file"), str) and cur["file"]:
        rels = [r for r, _p, _d in files]
        if cur["file"] in rels:
            start_idx = rels.index(cur["file"])
            off = cur.get("offset")
            start_off = off if isinstance(off, int) and not isinstance(off, bool) and off >= 0 else 0
        else:
            later = [i for i, r in enumerate(rels) if r > cur["file"]]
            start_idx = later[0] if later else len(files)
            gap = {"from_t": cur.get("last_ts"), "to_t": _day_start(files[start_idx][2]) if later else None,
                   "reason": "store_pruned"}
    if start_idx >= len(files):
        return [], cur, gap
    out: list = []
    last_ts = (cur or {}).get("last_ts") if isinstance((cur or {}).get("last_ts"), str) else None
    new_cur = cur
    for i in range(start_idx, len(files)):
        rel, p, _day = files[i]
        data = fsx.read_bytes(p)
        pos = start_off if i == start_idx else 0
        if pos > len(data):                            # 파일이 짧아졌다(바뀐 파일) — 처음부터
            pos = 0
        recs, end, corrupt = (_read_plain if kind == AUDIT_KIND else _read_gz)(data, pos)
        if corrupt and gap is None:
            gap = {"from_t": last_ts, "to_t": None, "reason": "store_corrupt"}
        out.extend(recs)
        for r in recs:
            t = r.get("ts_utc")
            if isinstance(t, str) and (last_ts is None or t > last_ts):
                last_ts = t
        new_cur = {"file": rel, "offset": end, "last_ts": last_ts}
    return out, new_cur, gap


def _as_day8(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, date):
        return d.strftime("%Y%m%d")
    s = str(d).replace("-", "")[:8]
    return s if re.fullmatch(r"\d{8}", s) else None


def iter_store(paths, pc_id: str, kind: str, src: str, d0=None, d1=None):
    """쓰기 날짜(UTC) [d0, d1] 일자 파일의 레코드(완전한 멤버만, 파일 순서). d0·d1 은 date 또는 'YYYY-MM-DD'·None."""
    a, b = _as_day8(d0), _as_day8(d1)
    for _rel, p, day in store_files(paths, pc_id, kind, src):
        if (a and day < a) or (b and day > b):
            continue
        data = fsx.read_bytes(p)
        recs, _end, _c = (_read_plain if kind == AUDIT_KIND else _read_gz)(data, 0)
        yield from recs
