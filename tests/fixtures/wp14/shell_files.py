# -*- coding: utf-8 -*-
r"""Windows 셸 파일 합성기(시험 전용, WP-14) — 실제 사용자 폴더·레지스트리 없이 수집기 입력을 만든다.

    write_lnk(path, target, mtime=None)            Shell Link(.lnk, MS-SHLLINK) — LinkInfo(로컬 경로, 유니코드)만 가진 바로가기
    write_jumplist(path, entries, version=4)       Jump List(*.automaticDestinations-ms) = 복합 문서(CFB v3) 안 DestList 스트림
    destlist(entries, version=4)                   DestList 스트림 바이트(판 1 = Windows 7 배치, 판 3·4 = Windows 10·11 배치)

entries = [(경로, datetime(UTC))]. 모든 파일은 호출자가 고른 %TEMP% 아래 경로에만 쓴다(tests.fixtures.tree.guard_write).
"""
from __future__ import annotations

import os
import struct
from datetime import UTC, datetime
from pathlib import Path

from tests.fixtures.tree import guard_write

_FT_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")      # {00021401-0000-0000-C000-000000000046}
_CFB_SIG = bytes.fromhex("d0cf11e0a1b11ae1")
FREESECT, ENDOFCHAIN, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
SECTOR = 512
MINI = 64
CUTOFF = 4096


def filetime(dt: datetime) -> int:
    """aware datetime → FILETIME(1601-01-01 UTC 부터 100ns) 정수(부동소수 없이)."""
    d = dt.astimezone(UTC) - _FT_EPOCH
    return (d.days * 86400 + d.seconds) * 10_000_000 + d.microseconds * 10


def _put(path, data: bytes, mtime: datetime | None = None) -> Path:
    p = guard_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if mtime is not None:
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))
    return p


# ── .lnk ────────────────────────────────────────────────────────────────────
def lnk_bytes(target: str, *, when: datetime | None = None, size: int = 0) -> bytes:
    """LinkInfo(VolumeIDAndLocalBasePath, 머리말 0x24 — 유니코드 경로 포함)만 있는 Shell Link 바이트."""
    ft = filetime(when or datetime(2026, 9, 1, tzinfo=UTC))
    flags = 0x02 | 0x80                                   # HasLinkInfo | IsUnicode
    header = struct.pack("<I16sIIQQQIiIHHII", 0x4C, _LINK_CLSID, flags, 0x20, ft, ft, ft, size & 0xFFFFFFFF, 0, 1, 0, 0,
                         0, 0)
    assert len(header) == 0x4C
    label = b"\x00"
    volume = struct.pack("<IIII", 0x10 + len(label), 3, 0x1234ABCD, 0x10) + label
    base_ansi = target.encode("mbcs", errors="replace") if os.name == "nt" else target.encode("ascii", "replace")
    base_ansi += b"\x00"
    suffix_ansi = b"\x00"
    base_u = target.encode("utf-16-le") + b"\x00\x00"
    suffix_u = b"\x00\x00"
    hdr_size = 0x24
    off_vol = hdr_size
    off_base = off_vol + len(volume)
    off_suffix = off_base + len(base_ansi)
    off_base_u = off_suffix + len(suffix_ansi)
    off_suffix_u = off_base_u + len(base_u)
    total = off_suffix_u + len(suffix_u)
    info = struct.pack("<IIIIIIIII", total, hdr_size, 0x1, off_vol, off_base, 0, off_suffix, off_base_u, off_suffix_u)
    info += volume + base_ansi + suffix_ansi + base_u + suffix_u
    assert len(info) == total
    return header + info + struct.pack("<I", 0)          # TerminalBlock


def write_lnk(path, target: str, *, mtime: datetime | None = None) -> Path:
    """path(.lnk)에 target 을 가리키는 바로가기를 쓰고, 파일 수정 시각(= 열람 시각)을 mtime 으로 맞춘다."""
    return _put(path, lnk_bytes(target, when=mtime), mtime)


# ── DestList · CFB ──────────────────────────────────────────────────────────
def destlist(entries, *, version: int = 4) -> bytes:
    """DestList 스트림: 머리말 32바이트 + 항목들. 판 ≥3 은 경로 길이 0x7C·경로 0x7E·끝 4바이트, 판 1 은 0x6C·0x6E."""
    items = []
    for i, (path, when) in enumerate(entries, 1):
        p = path.encode("utf-16-le")
        n = len(path)
        fixed = bytearray(0x7E if version >= 3 else 0x6E)
        nb = b"PCEXAMPLE01".ljust(16, b"\x00")
        fixed[0x48:0x58] = nb
        struct.pack_into("<I", fixed, 0x58, i)
        struct.pack_into("<Q", fixed, 0x60, filetime(when))
        struct.pack_into("<I", fixed, 0x68, 0xFFFFFFFF)
        if version >= 3:
            struct.pack_into("<I", fixed, 0x6C, 0xFFFFFFFF)
            struct.pack_into("<I", fixed, 0x70, 1)
            struct.pack_into("<H", fixed, 0x7C, n)
            items.append(bytes(fixed) + p + b"\x00" * 4)
        else:
            struct.pack_into("<H", fixed, 0x6C, n)
            items.append(bytes(fixed) + p)
    head = struct.pack("<IIIfIIII", version, len(items), 0, 0.0, len(items), 0, len(items), 0)
    return head + b"".join(items)


def _dir_entry(name: str, typ: int, start: int, size: int, child: int = NOSTREAM) -> bytes:
    e = bytearray(128)
    nm = name.encode("utf-16-le") + b"\x00\x00"
    e[0:len(nm)] = nm
    struct.pack_into("<HBB", e, 0x40, len(nm), typ, 1)
    struct.pack_into("<III", e, 0x44, NOSTREAM, NOSTREAM, child)
    struct.pack_into("<IQ", e, 0x74, start, size)
    return bytes(e)


def cfb_bytes(streams: dict[str, bytes]) -> bytes:
    """스트림 몇 개를 담은 복합 문서(CFB v3, 512바이트 섹터). 4,096바이트 미만 스트림은 미니 스트림에 넣는다."""
    names = list(streams)
    mini_data, mini_fat, regular = bytearray(), [], []
    placed = {}
    for n in names:
        data = streams[n]
        if len(data) < CUTOFF:
            first = len(mini_data) // MINI
            k = max(1, -(-len(data) // MINI))
            mini_fat += [first + j + 1 for j in range(k - 1)] + [ENDOFCHAIN]
            mini_data += data + b"\x00" * (k * MINI - len(data))
            placed[n] = ("mini", first, len(data))
        else:
            regular.append(n)
    # 섹터 배치: 0 FAT, 1 디렉터리, 2 미니 FAT, 3… 미니 스트림, 그다음 큰 스트림들
    fat = [FATSECT, ENDOFCHAIN, ENDOFCHAIN]
    sectors = [b"", b"", b""]
    mini_start = ENDOFCHAIN
    if mini_data:
        k = -(-len(mini_data) // SECTOR)
        mini_start = len(sectors)
        for j in range(k):
            fat.append(len(sectors) + 1 if j < k - 1 else ENDOFCHAIN)
            sectors.append(bytes(mini_data[j * SECTOR:(j + 1) * SECTOR]).ljust(SECTOR, b"\x00"))
    for n in regular:
        data = streams[n]
        k = -(-len(data) // SECTOR)
        start = len(sectors)
        for j in range(k):
            fat.append(len(sectors) + 1 if j < k - 1 else ENDOFCHAIN)
            sectors.append(data[j * SECTOR:(j + 1) * SECTOR].ljust(SECTOR, b"\x00"))
        placed[n] = ("reg", start, len(data))
    if len(fat) > SECTOR // 4:
        raise ValueError("합성 CFB 는 FAT 섹터 1개(128 섹터)까지만")
    fat += [FREESECT] * (SECTOR // 4 - len(fat))
    sectors[0] = struct.pack(f"<{SECTOR // 4}I", *fat)
    entries = [_dir_entry("Root Entry", 5, mini_start, len(mini_data), child=1 if names else NOSTREAM)]
    for n in names:
        _kind, start, size = placed[n]
        entries.append(_dir_entry(n, 2, start, size))
    if len(entries) > 4:
        raise ValueError("합성 CFB 는 디렉터리 섹터 1개(항목 4개)까지만")
    sectors[1] = b"".join(entries).ljust(SECTOR, b"\x00")
    mf = mini_fat + [FREESECT] * (SECTOR // 4 - len(mini_fat))
    sectors[2] = struct.pack(f"<{SECTOR // 4}I", *mf)
    difat = [0] + [FREESECT] * 108
    header = bytearray(SECTOR)
    header[0:8] = _CFB_SIG
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 0x28, 0, 1, 1, 0, CUTOFF, 2 if mini_fat else ENDOFCHAIN, 1 if mini_fat else 0,
                     ENDOFCHAIN, 0)
    struct.pack_into("<109I", header, 0x4C, *difat)
    return bytes(header) + b"".join(sectors)


def write_jumplist(path, entries, *, version: int = 4) -> Path:
    """Jump List 파일(*.automaticDestinations-ms) — DestList 스트림 하나."""
    return _put(path, cfb_bytes({"DestList": destlist(entries, version=version)}))
