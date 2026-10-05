# -*- coding: utf-8 -*-
"""WP-12 시험 도우미 — %TEMP% 아래 임시 번들 루트(lm27t_wp12_*), 합성 저장 행, 설정, PC 신원.

실명·실주소 없음(합성 pc_id·키만). 쓰기는 tests.fixtures.tree.guard_write 로 %TEMP% 아래인지 확인한 곳에만 한다.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.bundle.ids import PcIdentity
from lm27.config import load_config
from lm27.paths import Paths
from lm27.util import events, fsx
from tests.fixtures.tree import guard_write

TREE = Path(__file__).resolve().parents[3]
REGISTRY = TREE / "config" / "settings_registry.json"
RULES_VER = "2026.10.0"
KID = "k3f9a1c2e"
TEXT_COL = {"mail": "subject_masked", "cal": "subject_masked", "teams": "body_masked", "pc_session": "title_masked",
            "pc_file": "name_masked", "pc_git": "msg_masked", "pc_compute": None, "manual": "text_masked"}
SRC_OF = {"mail": "mail.com", "cal": "cal.com", "teams": "teams.uia", "pc_session": "pc.sampler",
          "pc_file": "pc.files", "pc_git": "pc.git", "pc_compute": "pc.compute", "manual": "manual"}


def pc_id_of(tag: str) -> str:
    return "pc_" + hashlib.sha256(("wp12-" + tag).encode()).hexdigest()[:16]


def install_of(tag: str) -> str:
    return hashlib.sha256(("wp12-inst-" + tag).encode()).hexdigest()[:32]


def ident(tag: str = "PC1", *, inst: str | None = None, kind: str = "desktop", off: int = 540,
          pc_id: str | None = None) -> PcIdentity:
    return PcIdentity(pc_id=pc_id or pc_id_of(tag), id_source="machineguid", install_id=inst or install_of(tag),
                      agent_ver="0.1.0", kind_guess=kind, tz={"utc_offset_min": off, "windows_tz": ""},
                      reasons=(), kind_evidence={"battery": False}, install_source="agent_json")


def fmt_off(off_min: int) -> str:
    sign = "-" if off_min < 0 else "+"
    h, m = divmod(abs(off_min), 60)
    return f"{sign}{h:02d}:{m:02d}"


def utc(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(kind: str, pc_id: str, ts: str, *, seq: int = 0, src: str | None = None, off: int = 540,
        observed: str | None = None, text: str | None = None, **extra) -> dict:
    """정제 후 저장 행 모양(합성). id 는 (src, pc_id, ts, seq, 텍스트) 해시 16자."""
    src = src or SRC_OF[kind]
    tcol = TEXT_COL.get(kind)
    body = text if text is not None else f"[과제:P-0001] 합성 {kind} {seq}"
    rid = hashlib.sha1(f"{src}|{pc_id}|{ts}|{seq}|{body}".encode()).hexdigest()[:16]
    r = {"id": rid, "kind": kind, "src": src, "pc_id": pc_id, "ts_utc": ts, "ts_local_offset": fmt_off(off),
         "ts_precision": "minute", "act": "", "observed_at": observed or ts, "rules_ver": RULES_VER, "kid": KID,
         "priv_class": "work", "confidence": 1.0}
    if tcol:
        r[tcol] = body
    if kind == "pc_session":
        r.update({"session_state": "active", "layer": "L3", "ts_end": iso(utc(ts) + timedelta(minutes=1))})
    if kind in ("mail", "teams", "cal"):
        r["msg_key"] = ("e" if kind == "cal" else "m") + hashlib.sha1(f"mk|{rid}".encode()).hexdigest()[:24]
    if kind == "teams":
        r["chat_key"] = "h" + hashlib.sha1(b"chat-1").hexdigest()[:16]
        r["chat_type"] = "group"
    r.update(extra)
    return r


def rows(kind: str, pc_id: str, n: int, *, start: str = "2026-09-01T00:00:00Z", step_min: int = 1, **kw) -> list:
    t0 = utc(start)
    return [row(kind, pc_id, iso(t0 + timedelta(minutes=i * step_min)), seq=i, **kw) for i in range(n)]


class BundleRoot:
    """%TEMP%\\lm27t_wp12_<rand>\\ — data\\ 가 있는 프로그램 폴더 모양 + 전용 %LOCALAPPDATA%(_lad)."""

    def __init__(self, prefix: str = "lm27t_wp12_"):
        self.root = guard_write(Path(tempfile.mkdtemp(prefix=prefix)))
        (self.root / "data").mkdir()
        self.lad = self.root / "_lad"
        self.paths = Paths(self.root, lad=self.lad)

    def cfg(self, **overrides):
        return load_config(registry_path=REGISTRY, config_path=self.root / "no_config.json", overrides=overrides)

    def pcdir(self, pc_id: str) -> Path:
        return self.paths.pc_dir(pc_id)

    def write_bundle_json(self, person_key: str = "p_0123456789ab") -> None:
        fsx.atomic_write(self.paths.bundle_json(), fsx.canon_bytes({
            "schema": "lm27.bundle/1", "bundle_id": "0" * 32, "person_key": person_key,
            "created_at": "2026-09-01T00:00:00Z", "created_on_pc": pc_id_of("PC1"), "lm27_version": "0.1.0"}))

    def snapshot(self, sub: Path | None = None) -> dict:
        """상대 경로 → 바이트(불변 단언용). 잠금 파일·검증 캐시는 뺀다."""
        base = sub or self.paths.data()
        out = {}
        for dp, _dn, fns in os.walk(base):
            for fn in fns:
                if fn in (".bundle.lock", "verify_cache.json"):
                    continue
                p = Path(dp) / fn
                out[str(p.relative_to(base))] = p.read_bytes()
        return out

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class BundleTestCase(unittest.TestCase):
    """테스트마다 새 임시 번들 루트(self.b). 이벤트 출력은 끈다."""

    def setUp(self):
        super().setUp()
        events.configure("off")
        self.addCleanup(events.configure, "text")
        self.b = BundleRoot()
        self.addCleanup(self.b.remove)
        self.paths = self.b.paths
