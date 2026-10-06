# -*- coding: utf-8 -*-
r"""WP-11 시험 도우미 — %TEMP% 샌드박스(ROOT + LAD), 설정, 고정 시험 키링, 레코드 문맥, kind 별 합성 원시 레코드.

모든 쓰기는 ``guard_write`` 로 확인한 %TEMP% 아래에만 한다(실제 트리·실제 %LOCALAPPDATA% 미접촉 — ``Paths(root, lad=…)``).
키는 시험 전용 고정 바이트(실제 키링 아님). 이름·주소·도메인은 자리표시자(홍길동·김철수·고객사A·과제A·example).
"""
from __future__ import annotations

import gzip
import shutil
import tempfile
from pathlib import Path

from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import context as C
from lm27.privacy import keys as K
from lm27.privacy.detect import subkey
from tests.fixtures.tree import guard_write

REAL_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_JSON = REAL_ROOT / "config" / "settings_registry.json"
PC1 = "pc_0a1b2c3d4e5f6a7b"                         # 9자리 이상 연속 숫자 없음(감사 T20 검사)
PC2 = "pcx_9f8e7d6c5b4a3f2e"
MASTER = bytes(range(1, 33))                       # 시험 전용 주 키(32바이트)
MASTER2 = bytes(range(101, 133))
ME = "hong@corp.example"
KIM = "kim@corp.example"
CUST = "sales@custa.example"
REGISTRY = {"internal_domains": ["corp.example"],
            "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}],
            "partners": [{"id": "V01", "names": ["협력사A"], "domains": ["vendor.example"]}],
            "projects": [{"id": "P-0001", "codenames": ["과제A"]}]}
OS_NAMES = ["hongtest", "홍길동"]                 # 본인 표시 이름(self_name_set 주입 — 실제 OS 미조회)
TS = "2026-09-15T01:02:00Z"                        # 2026-09-15(화) 10:02 KST — 표준창 안
OBS = "2026-09-15T02:00:00Z"


def keyring(master: bytes = MASTER) -> K.Keyring:
    kid = K.kid_of(master)
    return K.Keyring(primary_kid=kid, primary_secret=master, all={kid: master})


def agent_keys(master: bytes = MASTER, purposes=K.AGENT_PURPOSES) -> K.AgentKeys:
    return K.AgentKeys(kid=K.kid_of(master), subkeys={p: subkey(master, p) for p in purposes})


class Sandbox:
    """%TEMP%\\lm27t_wp11_*\\{root\\data, lad} — 시험 하나의 ROOT·LAD. ``cleanup()`` 으로 지운다."""

    def __init__(self, prefix: str = "lm27t_wp11_"):
        self.dir = guard_write(tempfile.mkdtemp(prefix=prefix))
        self.root = self.dir / "root"
        (self.root / "data").mkdir(parents=True)
        self.lad = self.dir / "lad"
        self.paths = Paths(self.root, lad=self.lad)

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def cfg(self, **over):
        return load_config(registry_path=REGISTRY_JSON, config_path=self.dir / "no_config.json", overrides=over or None)

    def rc(self, src: str, pc_id: str = PC1, *, kr=None, my_addrs=(ME,), registry=None, local=None, cfg=None,
           **kw):
        """프로그램 폴더 모드 레코드 문맥(고정 시험 키링·시험 레지스트리·OS 이름 주입)."""
        return C.make_record_context(self.root, src, pc_id, paths=self.paths, cfg=cfg or self.cfg(),
                                     keyring=kr or keyring(), registry=REGISTRY if registry is None else registry,
                                     local=local, os_names=OS_NAMES, my_addrs=my_addrs, **kw)

    def files(self, base: Path | None = None) -> list:
        b = base or self.dir
        return sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())

    def all_bytes(self) -> bytes:
        """샌드박스 안 모든 파일 바이트(.gz 는 풀어서) — 카나리아 검사용."""
        out = []
        for p in sorted(self.dir.rglob("*")):
            if p.is_file():
                data = p.read_bytes()
                if p.suffix == ".gz":
                    try:
                        data = gzip.decompress(data)
                    except (OSError, EOFError):
                        pass
                out.append(data)
        return b"\n".join(out)


# ───────────────────────────── 합성 원시 레코드(P §10.2 원시 이름) ─────────────────────────────
def _common(**over) -> dict:
    d = {"ts_utc": TS, "ts_local_offset": "+09:00", "ts_precision": "minute", "observed_at": OBS, "confidence": 1.0}
    d.update(over)
    return d


def raw_mail(**over) -> dict:
    d = _common(internet_message_id="<m1.s0@corp.example>", conversation_id="CONV0001", conversation_topic="견적 검토",
                box="inbox", folder_role="inbox", sender_addr=KIM, sender_name="김철수",
                to=[{"addr": ME, "name": "홍길동"}], cc=[], subject="견적 검토 요청", attach_names=["견적_v2.xlsx"],
                sensitivity=0, categories=[], importance=1, has_attach=True, in_reply_to=False,
                body_text="검토 부탁드립니다", focused_other=False)
    d.update(over)
    return d


def raw_cal(**over) -> dict:
    d = {"global_appointment_id": "GID0001", "start_utc": TS, "end_utc": "2026-09-15T02:02:00Z", "subject": "과제A 주간 회의",
         "organizer": {"addr": KIM, "name": "김철수"}, "attendees": [{"addr": ME, "name": "홍길동"}],
         "busy_status": "busy", "response_status": 3, "meeting_status": 1, "location": "3층 회의실",
         "is_recurring": True, "all_day": False, "online": False, "sensitivity": 0, "categories": [],
         "body_text": "", "ts_local_offset": "+09:00", "ts_precision": "minute", "observed_at": OBS, "confidence": 1.0}
    d.update(over)
    return d


def raw_teams(**over) -> dict:
    d = _common(message_id=None, chat_id="uia:과제a 채널", chat_type="group", n_participants=4, reply_to_id=None,
                author_addr=None, author_name="김철수", is_me=False, participants=[{"name": "김철수"}, {"name": "홍길동"}],
                mentions_me=False, file_names=[], body_text="도면 검토 부탁드립니다", chat_title="과제A 설계",
                flags={})
    d.update(over)
    return d


def raw_sampler(**over) -> dict:
    d = _common(fg_exe="excel.exe", app_id="excel", app_class="office", fg_title="견적_v2.xlsx - Excel",
                fg_doc_name="견적_v2.xlsx", session_state="active", idle_sec=3, layer="L3", interval_sec=60,
                ts_precision="exact")
    d.update(over)
    return d


def raw_event(**over) -> dict:
    d = _common(event_class="boot", session_state="active", layer="L0", ts_end="2026-09-15T09:00:00Z",
                flags={"end_uncertain": False})
    d.update(over)
    return d


def raw_file(**over) -> dict:
    d = _common(path=r"C:\Users\hongtest\Documents\과제A\견적_v2.xlsx", op="modify", size=120000,
                ooxml_totaltime=30, ooxml_revision=4, ooxml_last_modified_by="홍길동",
                target_mtime=TS, pdf_sibling=False, folder_role="documents", root_id=None, flags={})
    d.update(over)
    return d


def raw_git(**over) -> dict:
    d = _common(repo_root=r"C:\Users\hongtest\src\firmware", commit_sha="0123456789abcdef0123456789abcdef01234567",
                subject="센서 보정 로직 수정", n_commits=1, n_files=3, exts=[".c", ".h"], flags={})
    d.update(over)
    return d


def raw_compute(**over) -> dict:
    d = _common(fg_exe="fluent.exe", app_id="fluent", cpu_core=3.5, ts_end="2026-09-15T03:02:00Z",
                ts_precision="exact", flags={"solver": True})
    d.update(over)
    return d


def raw_manual(**over) -> dict:
    d = {"category": "현장 점검", "hours": 1.5, "date": "2026-09-15", "start": "14:00", "end": "15:30",
         "note": "과제A 장비 점검", "entity": "", "project_id": "P-0001", "role_field": "MECH", "role_func": "TEST",
         "man_kind": "work", "ref_keys": [], "retract_of": None, "ts_local_offset": "+09:00", "observed_at": OBS,
         "confidence": 1.0}
    d.update(over)
    return d


RAW = {"mail": ("mail.com", raw_mail), "cal": ("cal.com", raw_cal), "teams": ("teams.uia", raw_teams),
       "pc_session": ("pc.sampler", raw_sampler), "pc_file": ("pc.files", raw_file), "pc_git": ("pc.git", raw_git),
       "pc_compute": ("pc.compute", raw_compute), "manual": ("manual", raw_manual)}
