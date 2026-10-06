# -*- coding: utf-8 -*-
r"""WP-18 시험 도우미 — 정제 후 저장 행 모양(계약 §3.1~§3.3) 합성 작성기 + %TEMP% 임시 번들 루트(lm27t_wp18_*).

정제기를 흉내 내지 않는다: 텍스트 열은 이미 정제된 모양(자리표시자 토큰 ``[과제:P-0001]``·``[사람]``)이고, 키는 시험 전용
해시(실제 키링 아님 — 형식만 지킨다). 이름·주소는 자리표시자뿐(홍길동·김철수·고객사A). 쓰기는 ``guard_write`` 로 확인한
%TEMP% 아래에만 한다(실제 트리·실제 %LOCALAPPDATA% 미접촉 — ``Paths(root, lad=…)``).
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from lm27.bundle import manifest as mf
from lm27.bundle import pcreg
from lm27.bundle import segment as seg
from lm27.bundle.ids import PcIdentity
from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import RULES_VERSION
from lm27.util import events
from tests.fixtures.tree import guard_write

TREE = Path(__file__).resolve().parents[3]
REGISTRY = TREE / "config" / "settings_registry.json"
RULES_VER = RULES_VERSION
OLD_RULES = "2026.9.0"                       # 지금 규칙보다 낮은 판(G2 재정제 대상)
KID = "k3f9a1c2e"
CREATED = "2026-10-05T09:02:11Z"


def _h(prefix: str, *parts, n: int = 16) -> str:
    return prefix + hashlib.sha256(("wp18|" + "|".join(str(p) for p in parts)).encode("utf-8")).hexdigest()[:n]


def mk(seed) -> str:
    """메시지 키(m + 24hex)."""
    return _h("m", "msg", seed, n=24)


def ek(seed) -> str:
    """일정 키(e + 24hex)."""
    return _h("e", "cal", seed, n=24)


def who(seed) -> str:
    return _h("w", "who", seed)


def chat(seed) -> str:
    return _h("h", "chat", seed)


def thread(seed) -> str:
    return _h("t", "thread", seed)


def doc(seed) -> str:
    return _h("d", "doc", seed)


PC1 = _h("pc_", "pc", "PC1")
PC2 = _h("pc_", "pc", "PC2")
CLOUD = _h("pcx_", "pc", "CLOUD")
ME, KIM, LEE = "self", who("김철수"), who("동료B")


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def plus(ts: str, **delta) -> str:
    return iso(utc(ts) + timedelta(**delta))


def rid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def base(kind: str, src: str, pc: str, ts: str, *, prec: str = "minute", off: str = "+09:00",
         observed: str | None = None, rules_ver: str = RULES_VER, seq=0, **kw) -> dict:
    r = {"kind": kind, "src": src, "pc_id": pc, "ts_utc": ts, "ts_local_offset": off, "ts_precision": prec,
         "act": "", "observed_at": observed or plus(ts, minutes=5), "rules_ver": rules_ver, "kid": KID, "san": {},
         "priv_class": "work", "priv_why": [], "confidence": 1.0}
    r.update(kw)
    r["id"] = rid(src, pc, ts, seq, r.get("msg_key") or r.get("doc_key") or "",
                  r.get("subject_masked") or r.get("body_masked") or r.get("text_masked") or "")
    return r


def mail(ts: str, *, src: str = "mail.com", pc: str = PC1, box: str = "inbox", subject: str = "[과제:P-0001] 설계 검토",
         msg=None, thr="T1", sender: str | None = KIM, cps=(KIM,), rcv: str | None = None, cues=(), prec="minute",
         flags=None, **kw) -> dict:
    out = box == "sent"
    d = {"msg_key": msg if msg and msg.startswith("m") else mk(msg or subject), "box": box,
         "folder_role": box if box in ("inbox", "sent") else "other", "direction": "out" if out else "in",
         "sender_key": "self" if out else sender, "sender_label": "사내", "counterpart_keys": sorted(set(cps)),
         "n_participants": len(set(cps)) + 1, "rcv": rcv or ("na" if out else "to"), "subject_masked": subject,
         "attach_names_masked": [], "attach_keys": [], "attach_exts": [], "categories_masked": [], "is_reply": False,
         "refw_depth": 0, "ad_score": -3, "ad_band": "keep", "ad_why": [], "ad_partial": src != "mail.com",
         "abs_hint": "none", "thread_key": thread(thr) if thr else None, "act_cues": list(cues), "priv_score": -3}
    d.update(kw)
    r = base("mail", src, pc, ts, prec=prec, **d)
    if flags:
        r["flags"] = dict(flags)
        r["id"] = rid(r["id"], sorted(flags))
    return r


def teams(ts: str, *, src: str = "teams.uia", pc: str = PC1, body: str = "[과제:P-0001] 설계 자료 확인했습니다",
          msg=None, room="R1", author: str | None = KIM, direction: str | None = None, chat_type: str = "1:1",
          cues=(), prec="minute", flags=None, base_score=-2, **kw) -> dict:
    d = {"msg_key": msg if msg and msg.startswith("m") else mk(msg or (room, ts, body)), "chat_key": chat(room),
         "chat_type": chat_type, "author_key": author,
         "direction": direction or ("sent" if author == "self" else "received"), "counterpart_keys": [KIM],
         "n_participants": 2 if chat_type == "1:1" else 6, "body_masked": body, "file_names_masked": [],
         "file_keys": [], "priv_score_base": base_score, "priv_score": base_score, "thread_key": None,
         "act_cues": list(cues)}
    d.update(kw)
    r = base("teams", src, pc, ts, prec=prec, **d)
    if flags:
        r["flags"] = dict(flags)
        r["id"] = rid(r["id"], sorted(flags))
    return r


def cal(ts: str, end: str, *, src: str = "cal.com", pc: str = PC1, subject: str = "[과제:P-0001] 주간 회의",
        msg=None, abs_hint: str = "none", busy: str = "busy", location: str = "room", flags=None, prec="minute",
        off: str = "+09:00", **kw) -> dict:
    d = {"msg_key": msg if msg and msg.startswith("e") else ek(msg or (subject, ts)), "ts_end": end,
         "subject_masked": subject, "counterpart_keys": [KIM], "n_participants": 2, "busy": busy,
         "location_class": location, "categories_masked": [], "abs_hint": abs_hint, "act_cues": [], "priv_score": -2}
    d.update(kw)
    r = base("cal", src, pc, ts, prec=prec, off=off, **d)
    r["flags"] = dict(flags or {"response": 3, "meeting_status": 1})
    r["id"] = rid(r["id"], sorted(r["flags"].items()))
    return r


def session(ts: str, *, pc: str = PC1, minutes: int = 1, app: str = "excel", **kw) -> dict:
    return base("pc_session", "pc.sampler", pc, ts, prec="exact", ts_end=plus(ts, minutes=minutes), app_id=app,
                fg_exe=app + ".exe", app_class="office", title_masked="[과제:P-0001] 설계서 - Excel",
                doc_key=doc("설계서"), session_state="active", idle_sec=3, layer="L3", **kw)


def git(ts: str, *, pc: str = PC1, msg: str = "[과제:P-0001] 해석 스크립트 수정", **kw) -> dict:
    return base("pc_git", "pc.git", pc, ts, prec="exact", doc_key=_h("r", "repo", "R1"),
                commit_key=_h("g", "commit", ts, msg), msg_masked=msg, n_commits=1, n_files=2, exts=[".py"], **kw)


def manual(ts: str, *, pc: str = PC1, text: str = "현장 장비 점검 / [고객사:C01]", man_kind: str = "work", **kw) -> dict:
    return base("manual", "manual", pc, ts, prec="date", work_category="현장지원", hours=2.0, text_masked=text,
                man_kind=man_kind, ref_keys=[], retract_of=None, **kw)


def ident(pc_id: str, *, off: int = 540) -> PcIdentity:
    return PcIdentity(pc_id=pc_id, id_source="machineguid", install_id=hashlib.sha256(pc_id.encode()).hexdigest()[:32],
                      agent_ver="0.1.0", kind_guess="cloud" if pc_id.startswith("pcx_") else "desktop",
                      tz={"utc_offset_min": off, "windows_tz": ""}, reasons=(), kind_evidence={},
                      install_source="agent_json")


class Sandbox:
    r"""%TEMP%\lm27t_wp18_<rand>\ — data\ 가 있는 프로그램 폴더 모양 + 전용 %LOCALAPPDATA%(_lad)."""

    def __init__(self, prefix: str = "lm27t_wp18_"):
        self.root = guard_write(Path(tempfile.mkdtemp(prefix=prefix)))
        (self.root / "data").mkdir()
        self.lad = self.root / "_lad"
        self.paths = Paths(self.root, lad=self.lad)

    def cfg(self, **overrides):
        return load_config(registry_path=REGISTRY, config_path=self.root / "no_config.json", overrides=overrides)

    def put(self, rows, *, created: str = CREATED) -> list[dict]:
        """행들을 (pc_id, kind) 별 세그먼트 1개씩으로 쓰고 manifest 에 등록한다. 세그먼트 정보 목록."""
        groups: dict = {}
        for r in rows:
            groups.setdefault((r["pc_id"], r["kind"]), []).append(r)
        infos = []
        for (pc_id, kind), lst in sorted(groups.items()):
            idt = ident(pc_id)
            pcreg.ensure_pc_dir(self.paths, idt, host="", now="2026-09-01T00:00:00Z")
            d = self.paths.pc_dir(pc_id)
            m = mf.load_manifest(d)
            info = seg.write_segment(d, kind, idt, lst, rules_ver=RULES_VER, kid=KID, created=created, manifest=m)
            m["segments"].append(info)
            mf.save_manifest(d, m)
            infos.append(info)
        return infos

    def audit_lines(self) -> list[bytes]:
        """%LOCALAPPDATA%(_lad) 감사 원장 줄(바이트)."""
        out = []
        base_dir = self.lad
        if base_dir.is_dir():
            for p in sorted(base_dir.rglob("*.jsonl")):
                out.extend(x for x in p.read_bytes().splitlines() if x)
        return out

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class SandboxCase(unittest.TestCase):
    """시험마다 새 임시 번들 루트(``self.sb``) — 표준 출력 이벤트는 끈다."""

    def setUp(self):
        super().setUp()
        events.configure("off")
        self.addCleanup(events.configure, "text")
        self.sb = Sandbox()
        self.addCleanup(self.sb.remove)
        self.paths = self.sb.paths
