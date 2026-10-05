# -*- coding: utf-8 -*-
r"""번들 세그먼트 ``lm27.seg/1``(계약 §3.6, TAB §1.3) — 쓰기·읽기·검증·분할.

  · 위치·이름: ``data\pcs\<pc_id>\seg\<kind>\<seq:06d>-<inst8>-<t0>-<t1>-<sha8>.jsonl.gz``.
    t0·t1 = 첫·마지막 레코드 ``ts_utc`` 의 ``YYYYMMDDTHHMMZ``, inst8 = install_id 앞 8자, sha8 = 압축 바이트 sha256 앞 8자.
    이름에 install·sha 가 있어 두 사본 번들을 합쳐도 이름이 충돌하지 않는다.
  · 본문: 결정적 gzip(``fsx.gzip_bytes`` — mtime 0·이름 없음·level 6) 안의 JSONL, 줄마다 ``canon_bytes``.
    첫 줄 머리말 ``{_h:1, schema, kind, pc_id, install_id, seq, t0, t1, n, srcs, rules_ver, kid, agent_ver, created,
    src_from, src_to, redacted_from?}``, 끝 줄 꼬리말 ``{_f:1, n}``. 레코드는 (ts_utc, id) 순, 세그먼트 안 id 중복 금지,
    레코드의 pc_id 는 폴더의 pc_id 와 같아야 한다(다르면 쓰기 거부).
  · 불변: 덮어쓰지 않는다. 같은 이름 파일이 이미 있으면 같은 바이트일 때만 받아들이고(멱등) 다르면 ``SegmentConflict``.
  · 분할(``split_records``): 로컬 달(ts_utc + ts_local_offset) 경계 / ``bundle.segmentMaxRecords`` /
    ``bundle.segmentMaxRawMb``(비압축 바이트).

쓰기는 번들 잠금(``BundleLock``)을 쥔 채로만 한다(호출자 책임). manifest 갱신은 세그먼트를 쓴 **뒤에** 한다(2단계) —
그 사이에 죽으면 ``manifest.adopt_orphans`` 가 다음 내보내기 때 편입한다.
"""
import gzip
import os
import re
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.util import fsx

SCHEMA = "lm27.seg/1"
SEG_KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual", "privacy_audit")
DEFAULT_MAX_RECORDS = 50000      # bundle.segmentMaxRecords 선언 기본값(설정 없이 부를 때)
DEFAULT_MAX_RAW_MB = 16          # bundle.segmentMaxRawMb 선언 기본값
MAX_RAW_READ = 512 << 20         # 압축 해제 상한(손상·폭탄 방어)

NAME_RX = re.compile(r"^(\d{6})-([0-9a-f]{8})-(\d{8}T\d{4}Z)-(\d{8}T\d{4}Z)-([0-9a-f]{8})\.jsonl\.gz$")
_ID_RX = re.compile(r"^[0-9a-f]{16}$")
_PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
_INST_RX = re.compile(r"^[0-9a-f]{32}$")
_UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_OFF_RX = re.compile(r"^([+-])(\d{2}):(\d{2})$")


class SegmentError(Exception):
    """세그먼트 형식 오류의 기반."""


class SegmentConflict(SegmentError):
    """같은 이름의 다른 내용 세그먼트가 이미 있다(덮어쓰지 않는다)."""


class SegmentCorrupt(SegmentError):
    """세그먼트를 읽을 수 없거나 자기 검증(머리말·꼬리말·sha)에 실패. ``reason`` = 짧은 코드."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ── 이름·시각 ────────────────────────────────────────────────────────────────
def stamp(ts_utc: str) -> str:
    """``2026-10-04T23:00:00Z`` → ``20261004T2300Z``(파일 이름 스탬프, 콜론 없음)."""
    if not isinstance(ts_utc, str) or not _UTC_RX.match(ts_utc):
        raise ValueError("stamp: ts_utc 형식이 아닙니다")
    return ts_utc[0:4] + ts_utc[5:7] + ts_utc[8:10] + "T" + ts_utc[11:13] + ts_utc[14:16] + "Z"


def segment_name(seq: int, install_id: str, t0: str, t1: str, sha: str) -> str:
    return f"{int(seq):06d}-{install_id[:8]}-{stamp(t0)}-{stamp(t1)}-{sha[:8]}.jsonl.gz"


def parse_segment_name(name: str):
    """세그먼트 파일 이름 → ``{seq, inst8, t0, t1, sha8}``(형식이 아니면 None)."""
    m = NAME_RX.match(os.path.basename(name or ""))
    if not m:
        return None
    return {"seq": int(m.group(1)), "inst8": m.group(2), "t0": m.group(3), "t1": m.group(4), "sha8": m.group(5)}


def _offset_min(s) -> int:
    m = _OFF_RX.match(s) if isinstance(s, str) else None
    if not m:
        return 0
    v = int(m.group(2)) * 60 + int(m.group(3))
    return -v if m.group(1) == "-" else v


def _utc(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def local_month(rec: dict) -> str:
    """레코드의 로컬 달 ``YYYY-MM``(ts_utc + ts_local_offset — 오프셋이 없으면 UTC)."""
    ts = rec.get("ts_utc")
    if not isinstance(ts, str) or not _UTC_RX.match(ts):
        raise ValueError("local_month: ts_utc 형식이 아닙니다")
    return (_utc(ts) + timedelta(minutes=_offset_min(rec.get("ts_local_offset")))).strftime("%Y-%m")


def _sort_key(r):
    return (r["ts_utc"], r["id"])


# ── 분할 ─────────────────────────────────────────────────────────────────────
def split_limits(cfg=None):
    """(최대 레코드 수, 최대 비압축 바이트) — 설정 ``bundle.segmentMaxRecords``·``bundle.segmentMaxRawMb``."""
    if cfg is None:
        return DEFAULT_MAX_RECORDS, DEFAULT_MAX_RAW_MB << 20
    return int(cfg["bundle.segmentMaxRecords"]), int(cfg["bundle.segmentMaxRawMb"]) << 20


def split_records(records, cfg=None, *, max_records=None, max_raw_bytes=None):
    """레코드를 (ts_utc, id) 로 정렬한 뒤 로컬 달 경계·건수·비압축 크기로 나눈 묶음 목록(빈 입력 → [])."""
    lim_n, lim_b = split_limits(cfg)
    if max_records is not None:
        lim_n = int(max_records)
    if max_raw_bytes is not None:
        lim_b = int(max_raw_bytes)
    if lim_n < 1 or lim_b < 1:
        raise ValueError("split_records: 상한은 1 이상")
    out, cur, cur_b, cur_m = [], [], 0, None
    for r in sorted(records, key=_sort_key):
        m = local_month(r)
        sz = len(fsx.canon_bytes(r)) + 1
        if cur and (m != cur_m or len(cur) >= lim_n or cur_b + sz > lim_b):
            out.append(cur)
            cur, cur_b = [], 0
        cur.append(r)
        cur_b += sz
        cur_m = m
    if cur:
        out.append(cur)
    return out


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def _check_records(recs, kind, pc_id):
    seen = set()
    for r in recs:
        if not isinstance(r, dict):
            raise ValueError("write_segment: 레코드는 dict")
        rid = r.get("id")
        if not isinstance(rid, str) or not _ID_RX.match(rid):
            raise ValueError("write_segment: id 형식이 아닙니다")
        if not isinstance(r.get("ts_utc"), str) or not _UTC_RX.match(r["ts_utc"]):
            raise ValueError("write_segment: ts_utc 형식이 아닙니다")
        if r.get("kind") != kind or r.get("pc_id") != pc_id:
            raise ValueError("foreign record")
        if any(isinstance(k, str) and k.startswith("_") for k in r):
            raise ValueError("write_segment: 밑줄로 시작하는 열(로더 부착 열)은 쓰지 않습니다")
        if rid in seen:
            raise ValueError("dup id")
        seen.add(rid)


def _next_seq(pcdir: Path, kind: str, manifest) -> int:
    """(pc_id, kind) 별 다음 seq = manifest 와 디스크 양쪽의 최대 seq + 1(고아·격리 대기분과도 겹치지 않게)."""
    mx = 0
    for s in (manifest or {}).get("segments", ()):
        if isinstance(s, dict) and s.get("kind") == kind and isinstance(s.get("seq"), int):
            mx = max(mx, s["seq"])
    d = pcdir / "seg" / kind
    try:
        names = os.listdir(fsx.longp(d))
    except FileNotFoundError:
        names = []
    for nm in names:
        p = parse_segment_name(nm)
        if p:
            mx = max(mx, p["seq"])
    return mx + 1


def seg_info(rel_file: str, head: dict, gz_len: int, sha: str) -> dict:
    """manifest ``segments[]`` 한 항목(계약 §3.7)."""
    return {"kind": head["kind"], "seq": head["seq"], "file": rel_file, "install_id": head["install_id"],
            "t0": head["t0"], "t1": head["t1"], "n": head["n"], "bytes": gz_len, "sha256": sha,
            "rules_ver": head["rules_ver"], "kid": head["kid"], "created": head["created"],
            "src_to": head.get("src_to")}


def build_segment(kind, pc_id, ident, records, *, seq, rules_ver, kid, src_from=None, src_to=None, created=None,
                  redacted_from=None):
    """(머리말, 정렬된 레코드, gzip 바이트, sha256) — 디스크에 쓰지 않는다(시험·소급 가림 재작성용)."""
    if kind not in SEG_KINDS:
        raise ValueError("write_segment: kind 가 아닙니다")
    recs = sorted(records, key=_sort_key)
    if not recs:
        raise ValueError("empty")
    _check_records(recs, kind, pc_id)
    if not isinstance(ident.install_id, str) or not _INST_RX.match(ident.install_id):
        raise ValueError("write_segment: install_id 형식이 아닙니다")
    head = {"_h": 1, "schema": SCHEMA, "kind": kind, "pc_id": pc_id, "install_id": ident.install_id,
            "seq": int(seq), "t0": recs[0]["ts_utc"], "t1": recs[-1]["ts_utc"], "n": len(recs),
            "srcs": sorted({r.get("src") for r in recs if isinstance(r.get("src"), str)}),
            "rules_ver": rules_ver, "kid": kid, "agent_ver": ident.agent_ver,
            "created": created or fsx.utcnow_iso(), "src_from": src_from, "src_to": src_to}
    if redacted_from:
        head["redacted_from"] = redacted_from
    raw = b"\n".join([fsx.canon_bytes(head), *map(fsx.canon_bytes, recs),
                      fsx.canon_bytes({"_f": 1, "n": len(recs)})]) + b"\n"
    gz = fsx.gzip_bytes(raw)
    return head, recs, gz, fsx.sha256_hex(gz)


def write_segment(pcdir, kind, ident, records, *, rules_ver, kid, src_from=None, src_to=None, created=None,
                  seq=None, manifest=None, redacted_from=None) -> dict:
    r"""세그먼트 1개를 원자적으로 쓰고 manifest ``segments[]`` 항목을 돌려준다(manifest 는 호출자가 저장).

    ``pcdir`` = ``data\pcs\<pc_id>``(폴더 이름이 pc_id). 레코드의 pc_id·kind 가 폴더·인자와 다르면 ValueError.
    ``seq`` 를 주지 않으면 manifest·디스크의 최대 seq + 1. ``created`` 를 주면 그 값(결정성 시험)."""
    pcdir = Path(pcdir)
    pc_id = pcdir.name
    if not _PC_RX.match(pc_id):
        raise ValueError("write_segment: pcdir 이름이 pc_id 가 아닙니다")
    if getattr(ident, "pc_id", pc_id) != pc_id:
        raise ValueError("foreign record")
    if seq is None:
        if manifest is None:
            from lm27.bundle.manifest import load_manifest
            manifest = load_manifest(pcdir)
        seq = _next_seq(pcdir, kind, manifest)
    head, _recs, gz, sha = build_segment(kind, pc_id, ident, records, seq=seq, rules_ver=rules_ver, kid=kid,
                                         src_from=src_from, src_to=src_to, created=created,
                                         redacted_from=redacted_from)
    name = segment_name(head["seq"], ident.install_id, head["t0"], head["t1"], sha)
    dst = pcdir / "seg" / kind / name
    rel = f"seg/{kind}/{name}"
    lp = fsx.longp(dst)
    if os.path.exists(lp):
        if fsx.sha256_hex(fsx.read_bytes(dst)) == sha:
            return seg_info(rel, head, len(gz), sha)
        raise SegmentConflict(name)
    fsx.atomic_write(dst, gz)
    return seg_info(rel, head, len(gz), sha)


# ── 읽기·검증 ────────────────────────────────────────────────────────────────
def _gunzip(data: bytes) -> bytes:
    """gzip 멤버(들)를 모두 푼다. 잘렸거나 깨졌으면 SegmentCorrupt."""
    out, pos = [], 0
    total = 0
    while pos < len(data):
        d = zlib.decompressobj(wbits=31)
        try:
            chunk = d.decompress(data[pos:], MAX_RAW_READ - total)
        except zlib.error:
            raise SegmentCorrupt("gzip_error") from None
        if d.unconsumed_tail:
            raise SegmentCorrupt("too_large")
        if not d.eof:
            raise SegmentCorrupt("truncated")
        total += len(chunk)
        out.append(chunk)
        pos = len(data) - len(d.unused_data)
        if d.unused_data and not d.unused_data.strip(b"\x00"):
            break
    return b"".join(out)


def parse_segment_bytes(gz: bytes, *, expect_sha=None, name=None):
    """세그먼트 바이트 → (머리말, 레코드 목록). 자기 검증 실패면 SegmentCorrupt(reason)."""
    sha = fsx.sha256_hex(gz)
    if expect_sha is not None and sha != expect_sha:
        raise SegmentCorrupt("sha_mismatch")
    if name is not None:
        p = parse_segment_name(name)
        if p is None:
            raise SegmentCorrupt("bad_name")
        if p["sha8"] != sha[:8]:
            raise SegmentCorrupt("sha_name_mismatch")
    try:
        raw = _gunzip(gz)
    except (OSError, EOFError, gzip.BadGzipFile):
        raise SegmentCorrupt("gzip_error") from None
    lines = [ln for ln in raw.split(b"\n") if ln.strip()]
    if len(lines) < 2:
        raise SegmentCorrupt("too_short")
    try:
        objs = [fsx.loads_strict(ln) for ln in lines]
    except ValueError:
        raise SegmentCorrupt("bad_json") from None
    head, foot, recs = objs[0], objs[-1], objs[1:-1]
    if not isinstance(head, dict) or head.get("_h") != 1 or head.get("schema") != SCHEMA:
        raise SegmentCorrupt("no_header")
    if not isinstance(foot, dict) or foot.get("_f") != 1:
        raise SegmentCorrupt("no_footer")
    if foot.get("n") != len(recs) or head.get("n") != len(recs):
        raise SegmentCorrupt("count_mismatch")
    kind, pc_id = head.get("kind"), head.get("pc_id")
    if kind not in SEG_KINDS or not isinstance(pc_id, str) or not _PC_RX.match(pc_id):
        raise SegmentCorrupt("bad_header")
    if not isinstance(head.get("install_id"), str) or not _INST_RX.match(head["install_id"]):
        raise SegmentCorrupt("bad_header")
    seen, prev = set(), None
    for r in recs:
        if not isinstance(r, dict) or r.get("kind") != kind or r.get("pc_id") != pc_id:
            raise SegmentCorrupt("foreign_record")
        rid = r.get("id")
        if not isinstance(rid, str) or rid in seen:
            raise SegmentCorrupt("dup_id")
        seen.add(rid)
        k = (r.get("ts_utc") or "", rid)
        if prev is not None and k < prev:
            raise SegmentCorrupt("order")
        prev = k
    if recs and (recs[0].get("ts_utc") != head.get("t0") or recs[-1].get("ts_utc") != head.get("t1")):
        raise SegmentCorrupt("span_mismatch")
    if name is not None:
        p = parse_segment_name(name)
        if p["seq"] != head.get("seq") or p["inst8"] != head["install_id"][:8] \
                or p["t0"] != stamp(head["t0"]) or p["t1"] != stamp(head["t1"]):
            raise SegmentCorrupt("name_mismatch")
    return head, recs


def read_segment_full(path, expect_sha=None):
    """세그먼트 파일 → (머리말, 레코드 목록). 파일이 없으면 FileNotFoundError, 손상이면 SegmentCorrupt."""
    data = fsx.read_bytes(path)
    return parse_segment_bytes(data, expect_sha=expect_sha, name=os.path.basename(os.fspath(path)))


def read_segment(path, expect_sha=None):
    """세그먼트의 레코드(머리말·꼬리말 제외)를 차례로 낸다. 검증은 다 읽기 전에 끝난다(손상이면 하나도 내지 않는다)."""
    _head, recs = read_segment_full(path, expect_sha)
    yield from recs


def verify_segment(path, expect_sha=None):
    """(ok, reason) — reason ∈ '' · missing · gzip_error · truncated · bad_json · no_header · no_footer ·
    count_mismatch · foreign_record · dup_id · order · span_mismatch · sha_mismatch · sha_name_mismatch · bad_name …"""
    try:
        read_segment_full(path, expect_sha)
    except FileNotFoundError:
        return False, "missing"
    except SegmentCorrupt as e:
        return False, e.reason
    except OSError:
        return False, "unreadable"
    return True, ""


def read_head(path):
    """머리말만(검증 포함 — 전체를 읽는다). 손상이면 SegmentCorrupt."""
    head, _recs = read_segment_full(path)
    return head
