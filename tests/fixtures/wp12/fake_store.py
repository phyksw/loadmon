# -*- coding: utf-8 -*-
r"""계약 §3.10 형 가짜 로컬 원장 — WP-11(lm27.store) 완료 전 WP-12 내보내기 시험용(계획 §4 이음매 '가짜').

  · ``append_member(paths, pc_id, kind, src, utc_date, rows)`` — 정제된 행 묶음을 gzip 멤버 1개로 그 날(쓰기 UTC 날짜)
    파일 끝에 덧붙인다(``store\<pc_id>\evidence\<kind>\<src>\YYYYMM\YYYYMMDD.jsonl.gz``).
  · ``append_audit(paths, utc_date, events)`` — 정제 감사 평문 JSONL(``store\privacy_audit\YYYYMM\YYYYMMDD.jsonl``).
  · ``read_store_since(paths, pc_id, kind, src, cursor) -> (records, new_cursor, gap|None)`` — 계약 시그니처 그대로.
    일자 파일을 이름(=쓰기 날짜) 순으로 cursor.file 부터 읽는다. .jsonl.gz 는 cursor.offset(압축 바이트)부터 멤버를
    하나씩 풀고, 끝나지 않은(잘린) 마지막 멤버는 버리고 오프셋을 그 앞에 둔다. .jsonl 은 마지막 '\n' 까지만.
    cursor.file 이 지워졌으면 다음 파일부터 읽고 gap(store_pruned)을 돌려준다.
시험 전용 — 제품 코드가 아니므로 쓰기에 open 을 바로 쓴다.
"""
from __future__ import annotations

import json
import os
import zlib
from pathlib import Path

from lm27.util import fsx


def _date_parts(utc_date: str):
    y, m, d = utc_date.split("-")
    return y, m, d


def store_file(paths, pc_id, kind, src, utc_date) -> Path:
    return Path(paths.store_file(pc_id, kind, src, utc_date))


def member_bytes(rows) -> bytes:
    raw = b"".join(fsx.canon_bytes(r) + b"\n" for r in rows)
    return fsx.gzip_bytes(raw)


def append_member(paths, pc_id, kind, src, utc_date, rows, *, truncate_to=None) -> Path:
    """멤버 하나 덧붙이기. ``truncate_to`` 를 주면 그 바이트 수만 써서 '쓰는 중 잘린 멤버'를 흉내 낸다."""
    p = store_file(paths, pc_id, kind, src, utc_date)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = member_bytes(rows)
    if truncate_to is not None:
        data = data[:truncate_to]
    with open(p, "ab") as fh:
        fh.write(data)
    return p


def finish_member(path: Path, rows, already: int) -> None:
    """잘라 둔 멤버의 나머지 바이트를 마저 쓴다(같은 rows 여야 같은 바이트)."""
    data = member_bytes(rows)
    with open(path, "ab") as fh:
        fh.write(data[already:])


def append_audit(paths, utc_date, events) -> Path:
    p = Path(paths.privacy_audit_file(utc_date))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "ab") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return p


def _files(paths, pc_id, kind, src):
    """[(상대 경로(agent\\store 기준, '/'), 절대 경로)] 이름 순."""
    if kind == "privacy_audit":
        base = Path(paths.store_root()) / "privacy_audit"
        pat, pre = "*/*.jsonl", "privacy_audit"
    else:
        base = Path(paths.store_dir(pc_id)) / "evidence" / kind / src
        pat, pre = "*/*.jsonl.gz", f"{pc_id}/evidence/{kind}/{src}"
    if not base.is_dir():
        return []
    out = []
    for p in base.glob(pat):
        out.append((f"{pre}/{p.parent.name}/{p.name}", p))
    return sorted(out)


def _read_gz(data: bytes, pos: int):
    """pos 부터 완전한 멤버만 → (레코드, 끝 오프셋)."""
    recs = []
    while pos < len(data):
        d = zlib.decompressobj(wbits=31)
        try:
            raw = d.decompress(data[pos:])
        except zlib.error:
            break
        if not d.eof:
            break                                   # 잘린 마지막 멤버 — 다음에 다시 본다
        for ln in raw.split(b"\n"):
            if ln.strip():
                recs.append(json.loads(ln))
        pos = len(data) - len(d.unused_data)
    return recs, pos


def _read_plain(data: bytes, pos: int):
    end = data.rfind(b"\n")
    if end < pos:
        return [], pos
    recs = [json.loads(ln) for ln in data[pos:end + 1].split(b"\n") if ln.strip()]
    return recs, end + 1


def _day_start(rel: str) -> str:
    name = os.path.basename(rel)[:8]
    return f"{name[0:4]}-{name[4:6]}-{name[6:8]}T00:00:00Z"


def read_store_since(paths, pc_id, kind, src, cursor):
    files = _files(paths, pc_id, kind, src)
    gap = None
    start_idx, start_off = 0, 0
    if isinstance(cursor, dict) and cursor.get("file"):
        rels = [r for r, _p in files]
        if cursor["file"] in rels:
            start_idx = rels.index(cursor["file"])
            start_off = int(cursor.get("offset") or 0)
        else:
            later = [i for i, r in enumerate(rels) if r > cursor["file"]]
            start_idx = later[0] if later else len(files)
            gap = {"from_t": cursor.get("last_ts"),
                   "to_t": _day_start(rels[start_idx]) if later else None, "reason": "store_pruned"}
    if start_idx >= len(files):
        return [], (dict(cursor) if isinstance(cursor, dict) else None), gap
    out, last = [], dict(cursor) if isinstance(cursor, dict) else None
    for i in range(start_idx, len(files)):
        rel, p = files[i]
        data = p.read_bytes()
        pos = start_off if i == start_idx else 0
        recs, end = (_read_plain if kind == "privacy_audit" else _read_gz)(data, pos)
        out.extend(recs)
        last_ts = max([str(r.get("ts_utc") or "") for r in recs] + [str((last or {}).get("last_ts") or "")])
        last = {"file": rel, "offset": end, "last_ts": last_ts or None}
    return out, last, gap
