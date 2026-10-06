# -*- coding: utf-8 -*-
r"""브리지 파일 쓰기 층(B §2.2·§9.5, 관문 G-B7·L-07) — ``lm27.util.fsx`` 를 감싸는 얇은 층(계약 X-176).

**브리지에서 디스크에 쓰는 유일한 파일.** 다른 브리지 모듈은 ``open(…, "w"|"a")``·``os.replace``·``os.remove`` 를
직접 부르지 않고 여기의 함수만 쓴다.

  쓰기 세 함수(B §2.2)
    append_line(path, row)        jsonl 한 줄(dict 는 정규 JSON) — 저널·계측
    write_atomic(path, data)      원자 쓰기(dict·list 는 ``canon_bytes``) — 결과 봉투·잠금 갱신·프로필 상태
    write_text_ttl(path, text, …) TTL 보존 텍스트 — **수동 붙여넣기 프롬프트·원문 캡처 전용**(호출은 manual.py·exchange.py 만)
  보조
    create_exclusive · move_aside · rename_dir · remove · rotate · prune_ttl · read_json · read_text · bridge_file

원문(프롬프트·답)은 ``write_text_ttl`` 로만 디스크에 닿는다 — 게이트를 통과한 텍스트이고 TTL 이 지나면 지운다(B §9.5).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from lm27.util import fsx

# 브리지 상태 파일(계약 §1.3 ``%LOCALAPPDATA%\LoadMonitor27\bridge\``) — 경로는 ``lm27.paths.Paths`` 메서드(계약 v1.2 §0.7 C19)
BRIDGE_FILES = {
    "bridge_profile": "bridge_profile",
    "profile_id": "bridge_profile_id",
    "trace": "bridge_trace",
    "probe_last": "bridge_probe_last",
    "rawcap": "bridge_rawcap",
    "diagnose": "bridge_diagnose",
}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,120}$")


def bridge_file(paths, which: str) -> Path:
    """브리지 상태 파일·폴더 경로 = ``Paths.bridge_profile()`` 등(계약 §1.3·B §2.4 · v1.2 C19 — 조립은 lm27.paths 한 벌)."""
    return Path(getattr(paths, BRIDGE_FILES[which])())


def child(base, name: str) -> Path:
    """폴더 아래 파일 하나(이름 검증 — 구분자·'..' 금지)."""
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError("fsio: 파일 이름 형식이 아닙니다")
    return Path(base) / name


def _to_bytes(data) -> bytes:
    if isinstance(data, dict | list | tuple):
        return fsx.canon_bytes(data)
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, bytes | bytearray | memoryview):
        return bytes(data)
    raise TypeError("fsio: dict·list·str·bytes 가 필요합니다")


# ── 쓰기 세 함수 ────────────────────────────────────────────────────────────
def append_line(path, row, *, fsync: bool = False) -> None:
    """jsonl 한 줄 덧붙이기. dict 는 정규 JSON 한 줄로, str 은 그대로(줄바꿈 금지). ``fsync=True`` 면 디스크까지 밀어 낸 뒤
    돌아온다(저널 커밋 — B §7.8 '커밋 = fsync 뒤', W1 통합 창 WP-24 CR)."""
    line = fsx.canon_bytes(row).decode("utf-8") if isinstance(row, dict) else row
    fsx.append_line(path, line, fsync=fsync)


def write_atomic(path, data, *, fsync: bool = True) -> None:
    """원자 쓰기(임시 ``.part`` → ``os.replace``). dict·list 는 ``canon_bytes``."""
    fsx.atomic_write(path, _to_bytes(data), fsync=fsync)


def write_text_ttl(path, text: str, *, ttl_days: int, clock, bom: bool = True, crlf: bool = True) -> int:
    """TTL 보존 텍스트 파일(수동 프롬프트 ``.prompt.txt`` = UTF-8 BOM + CRLF, 계약 §9.2). 같은 폴더의 TTL 지난
    파일을 함께 지운다. 반환: 지운 파일 수. **원문이 디스크에 닿는 두 경우(B §9.5) 전용** — 게이트 통과본만 넘긴다."""
    if not isinstance(text, str):
        raise TypeError("write_text_ttl: str 이 필요합니다")
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    raw = (b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8")
    p = Path(path)
    fsx.atomic_write(p, raw)
    return prune_ttl(p.parent, ttl_days, clock, keep=(p.name,))


# ── 보조 ───────────────────────────────────────────────────────────────────
def create_exclusive(path, data) -> bool:
    """없을 때만 만든다(``O_CREAT | O_EXCL`` — 원자적 생성, 잠금 획득용). 이미 있으면 False."""
    raw = _to_bytes(data)
    p = Path(path)
    fsx.ensure_dir(p.parent)
    try:
        fd = os.open(fsx.longp(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        return False
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def move_aside(path, dest) -> bool:
    """파일을 옆 이름으로 옮긴다(기록 보존 — 잠금 인수 ``.stale``). dest 가 있으면 덮는다. 원본이 없으면 False."""
    try:
        os.replace(fsx.longp(path), fsx.longp(dest))
        return True
    except FileNotFoundError:
        return False


def rename_dir(src, dst) -> bool:
    """폴더 이름 바꾸기(손상 프로필 → ``edge_copilot.bad-<시각>``). dst 가 이미 있으면 OSError."""
    try:
        os.rename(fsx.longp(src), fsx.longp(dst))
        return True
    except FileNotFoundError:
        return False


def remove(path) -> bool:
    """파일 하나 지우기. 없으면 False."""
    try:
        os.remove(fsx.longp(path))
        return True
    except FileNotFoundError:
        return False


def remove_tree(path) -> bool:
    """폴더째 지우기(오래된 ``.bad-*`` 프로필 정리). 없으면 False."""
    import shutil
    p = fsx.longp(path)
    if not os.path.isdir(p):
        return False
    shutil.rmtree(p, ignore_errors=True)
    return not os.path.isdir(p)


def rotate(path, max_bytes: int) -> bool:
    """파일이 max_bytes 를 넘으면 ``<이름>.1`` 로 갈아 끼운다(계측 4MB 교체, B §2.4). 갈았으면 True."""
    try:
        size = os.path.getsize(fsx.longp(path))
    except OSError:
        return False
    if size <= max_bytes:
        return False
    try:
        os.replace(fsx.longp(path), fsx.longp(str(path) + ".1"))
    except OSError:
        return False
    return True


def prune_ttl(folder, ttl_days: int, clock, *, keep=()) -> int:
    """폴더 안 파일 중 수정 시각이 ttl_days 보다 오래된 것을 지운다(하위 폴더는 보지 않는다). 반환: 지운 수."""
    d = Path(folder)
    if not d.is_dir():
        return 0
    limit = clock.now() - max(0, int(ttl_days)) * 86400
    n = 0
    for f in d.iterdir():
        if not f.is_file() or f.name in keep:
            continue
        try:
            if f.stat().st_mtime < limit:
                os.remove(fsx.longp(f))
                n += 1
        except OSError:
            continue
    return n


def read_json(path, default=None, *, want=dict):
    """엄격 JSON 읽기(``fsx.read_json`` — 없으면 default, 깨지면 default + 경고 1줄)."""
    return fsx.read_json(path, default, want=want)


def read_text(path, default: str | None = None) -> str | None:
    """작은 텍스트 파일 읽기(UTF-8, BOM 허용). 없거나 못 읽으면 default."""
    try:
        return fsx.read_bytes(path).decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return default


def read_text_any(path) -> tuple[str | None, str]:
    """사람이 저장한 텍스트 파일 → ``(글, 상태)``. UTF-8(BOM 허용) → 안 되면 CP949(한국어 Windows 메모장 'ANSI').
    상태 ``ok`` · ``enc``(둘 다 실패 — 글 None) · ``io``(잠김·없음 — 글 None, 다음에 다시 볼 수 있다)."""
    try:
        data = fsx.read_bytes(path)
    except OSError:
        return None, "io"
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc), "ok"
        except UnicodeDecodeError:
            continue
    return None, "enc"
