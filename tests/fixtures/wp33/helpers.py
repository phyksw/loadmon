# -*- coding: utf-8 -*-
r"""WP-33 시험 도우미 — %TEMP% 샌드박스(ROOT·LAD) · 시험 PC 신원 · 저장 행·세그먼트 · 가짜 수집기·파이프로 바꿔 띄우는
``FakeDeps``(``lm27.collect.run.Deps`` 하위 클래스 — 실제 작업 등록·메일·팀즈·PC 수집·네트워크 0).

모든 쓰기는 ``guard_write`` 로 확인한 %TEMP% 아래에만. 이름·주소·도메인은 자리표시자(홍길동·김철수·과제A·example).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.bundle.ids import PcIdentity
from lm27.collect import probe as probe_mod
from lm27.collect.run import Deps
from lm27.config import load_config
from lm27.paths import Paths
from lm27.util import fsx, proc
from tests.fixtures.tree import guard_write

TREE = Path(__file__).resolve().parents[3]
REGISTRY = TREE / "config" / "settings_registry.json"
HERE = Path(__file__).resolve().parent
FAKE_COLLECTOR = HERE / "fake_collector.py"
FAKE_PIPE = HERE / "fake_pipe.py"
PROBE_FACTS = HERE / "probe_facts.json"
NOW = datetime(2026, 10, 5, 3, 0, tzinfo=UTC)            # 로컬(+09:00) 2026-10-05 12:00
TODAY = "2026-10-05"
RULES_VER = "2026.10.0"
KID = "k3f9a1c2e"
# 가짜로 바꿔 띄울 수집기 — (스크립트 이름, 구분 인자) → 경로 ID
SCRIPT_SRC = {("Get-OutlookCom.ps1", "mail"): "mail.com", ("Get-OutlookCom.ps1", "cal"): "cal.com",
              ("Get-OutlookIndex.ps1", "mail"): "mail.index", ("Get-OutlookIndex.ps1", "cal"): "cal.index",
              ("Get-EventActivity.ps1", ""): "pc.events", ("Get-FileActivity.ps1", ""): "pc.files",
              ("Get-OfficeMru.ps1", ""): "pc.mru", ("Get-RecentFiles.ps1", ""): "pc.recent",
              ("Get-TeamsWindow.ps1", ""): "teams.uia", ("Get-LicenseUsage.ps1", ""): "pc.compute",
              ("Get-GitActivity.py", ""): "pc.git", ("Import-MailCal.py", "mail"): "mail.import",
              ("Import-MailCal.py", "cal"): "cal.import", ("Get-OutlookWeb.py", "mail"): "mail.owa",
              ("Get-OutlookWeb.py", "cal"): "cal.owa", ("Get-TeamsWeb.py", ""): "teams.web",
              ("Get-MailViaCopilot.py", ""): "mail.copilot", ("Get-TeamsViaCopilot.py", ""): "teams.copilot",
              ("Get-CalViaCopilot.py", ""): "cal.copilot"}
PLACEHOLDER_SCRIPTS = sorted({k[0] for k in SCRIPT_SRC if "Copilot" not in k[0]} | {"Invoke-CapabilityProbe.ps1"})


def pc_id_of(tag: str) -> str:
    return "pc_" + hashlib.sha256(("wp33-" + tag).encode()).hexdigest()[:16]


def install_of(tag: str) -> str:
    return hashlib.sha256(("wp33-inst-" + tag).encode()).hexdigest()[:32]


def ident(tag: str = "PC1", *, kind: str = "desktop", off: int = 540) -> PcIdentity:
    return PcIdentity(pc_id=pc_id_of(tag), id_source="machineguid", install_id=install_of(tag), agent_ver="0.1.0",
                      kind_guess=kind, tz={"utc_offset_min": off, "windows_tz": ""}, reasons=(),
                      kind_evidence={"battery": False}, install_source="agent_json")


def cfg_of(root: Path, **over):
    return load_config(registry_path=REGISTRY, config_path=Path(root) / "no_config.json", overrides=over or None)


class Sandbox:
    r"""%TEMP%\lm27t_wp33_*\{root\data, root\collect(자리 파일), lad}."""

    def __init__(self, prefix: str = "lm27t_wp33_", *, scripts: bool = True):
        self.dir = guard_write(tempfile.mkdtemp(prefix=prefix))
        self.root = self.dir / "root"
        (self.root / "data").mkdir(parents=True)
        self.lad = self.dir / "lad"
        self.lad.mkdir()
        self.work = self.dir / "work"
        self.work.mkdir()
        self.paths = Paths(self.root, lad=self.lad)
        if scripts:
            (self.root / "collect").mkdir()
            for name in PLACEHOLDER_SCRIPTS:
                (self.root / "collect" / name).write_bytes(b"# placeholder\n")

    def cfg(self, **over):
        return cfg_of(self.dir, **over)

    def write_json(self, name: str, obj) -> Path:
        p = self.work / name
        p.write_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        return p

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


# ── 저장 행·세그먼트 ────────────────────────────────────────────────────────
def stored_row(kind: str, src: str, pc_id: str, ts: str, *, seq: int = 0, precision: str = "minute",
               box: str | None = None, direction: str | None = None, chat: str | None = None) -> dict:
    """정제 후 저장 행 모양(합성 — 원문 없음)."""
    rid = hashlib.sha1(f"{src}|{pc_id}|{ts}|{seq}".encode()).hexdigest()[:16]
    r = {"id": rid, "kind": kind, "src": src, "pc_id": pc_id, "ts_utc": ts, "ts_local_offset": "+09:00",
         "ts_precision": precision, "act": "", "observed_at": ts, "rules_ver": RULES_VER, "kid": KID,
         "priv_class": "work", "confidence": 1.0}
    if kind in ("mail", "cal", "teams"):
        r["msg_key"] = ("e" if kind == "cal" else "m") + hashlib.sha1(f"mk|{rid}".encode()).hexdigest()[:24]
    if kind == "mail":
        r["box"] = box or "inbox"
        r["direction"] = direction or ("out" if r["box"] == "sent" else "in")
        r["folder_role"] = r["box"] if r["box"] in ("inbox", "sent") else "other"
    if kind == "teams":
        r["chat_key"] = chat or ("h" + hashlib.sha1(b"chat-1").hexdigest()[:16])
        r["chat_type"] = "group"
        r["direction"] = direction or "received"
    if kind == "pc_session":
        r.update({"session_state": "active", "layer": "L3",
                  "ts_end": (datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=1))
                  .strftime("%Y-%m-%dT%H:%M:%SZ")})
    return r


def local_noon_utc(day: str, hour: int = 10) -> str:
    """로컬(+09:00) 그 날 hour 시 → UTC 문자열."""
    d = date.fromisoformat(day)
    return (datetime(d.year, d.month, d.day, hour, 0, tzinfo=UTC) - timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_rows(paths: Paths, ident_: PcIdentity, kind: str, rows: list) -> dict:
    """세그먼트 1개 + manifest 저장(WP-12 함수 — 시험이 번들을 미리 채운다)."""
    from lm27.bundle import manifest as mf
    from lm27.bundle import segment as seg
    pcdir = paths.pc_dir(ident_.pc_id)
    fsx.ensure_dir(pcdir)
    m = mf.load_manifest(pcdir)
    info = seg.write_segment(pcdir, kind, ident_, rows, rules_ver=RULES_VER, kid=KID, manifest=m,
                             created="2026-10-05T00:00:00Z")
    m["segments"].append(info)
    mf.save_manifest(pcdir, m, now="2026-10-05T00:00:00Z")
    return info


def pc_json(paths: Paths, ident_: PcIdentity, *, kind: str = "desktop", label: str = "PC1", caps=None,
            first_seen: str = "2026-09-01T00:00:00Z") -> Path:
    """pc.json 을 직접 쓴다(시험 — 능력 이력 주입)."""
    pcdir = paths.pc_dir(ident_.pc_id)
    fsx.ensure_dir(pcdir)
    obj = {"schema": "lm27.pc/1", "pc_id": ident_.pc_id, "id_source": "machineguid", "label_auto": label,
           "label_user": "", "host_display": "", "host_class": "", "kind": kind, "kind_evidence": {},
           "kind_confirmed": False, "tz": {"utc_offset_min": 540, "windows_tz": "", "changes": []},
           "roles": [], "first_seen": first_seen, "last_seen": first_seen, "anchor_since": "2020-01-01T00:00:00Z",
           "installs": [], "visits": [], "flags": [], "capabilities": caps or {}}
    fsx.atomic_write(pcdir / "pc.json", fsx.canon_bytes(obj))
    return pcdir


def hist(*entries) -> dict:
    """능력 기록 하나 — entries = (date, status, [사유], sig)."""
    h = [{"date": d, "status": s, "reasons": list(r), "probe_sig": g} for d, s, r, g in entries]
    last = h[-1]
    return {"ok": last["status"] == "ok", "value": {}, "reasons": last["reasons"], "history": h, "verdict": ""}


# ── 가짜 실행 환경 ──────────────────────────────────────────────────────────
def probe_result(caps=None, *, rc=0, budget_hit=False, team=None) -> probe_mod.ProbeResult:
    """ProbeResult(합성 — 탐침 스크립트를 띄우지 않는 시험)."""
    pr = probe_mod.ProbeResult(rc=rc, budget_hit=budget_hit, team=team)
    for k, c in (caps or {}).items():
        pr.caps[k] = {"ok": c.get("ok"), "status": c.get("status", "ok"), "reasons": list(c.get("reasons") or ()),
                      "value": dict(c.get("value") or {}), "sig": c.get("sig", "aaaaaaaaaaaa")}
    return pr


class FakeDeps(Deps):
    """``Deps`` 의 실기계 부분을 합성으로 바꾼다. 수집기·파이프 자식은 ``fake_collector.py``·``fake_pipe.py`` 로 바꿔 띄운다
    (``real_pipe=True`` 면 파이프는 실제 ``lm27_pipe.py`` 그대로, ``real_collectors`` 에 든 경로는 진짜 수집기 그대로 — 복제
    트리 + 주입점 환경 시험). ``specs`` = {경로 ID: 가짜 수집기 spec}."""

    def __init__(self, sb, cfg, *, ident_=None, specs=None, pipe=None, agent=None, harvest=None, probe=None,
                 upload=None, location=None, now=NOW, real_pipe=False, real_collectors=(), env=None, export=None,
                 mono=None):
        super().__init__(sb.paths, cfg)
        self.sb = sb
        self.ident_ = ident_ or ident()
        self.specs = specs or {}
        self.pipe_behave = pipe or {"exit": 0}
        self.agent = agent if agent is not None else {"rc": 4, "impl": "py", "reasons": [],
                                                      "health": {"healthy": True, "reasons": []}}
        self.harvest = harvest
        self.probe_res = probe if probe is not None else probe_result()
        self.upload = upload
        self.location = location or {"ok": True, "status": "ok", "value": {"drive_type": "fixed", "writable": True},
                                     "reasons": []}
        self._now = now
        self.real_pipe = real_pipe
        self.real_collectors = set(real_collectors)
        self.env = env
        self.export_fn = export
        self.mono = mono
        self.calls = []                 # (종류, 경로 ID, argv)
        self.harvest_calls = []
        self.probe_calls = []
        self.agent_calls = 0

    def now(self):
        return self._now

    def monotonic(self):
        return self.mono() if self.mono is not None else super().monotonic()

    def identify(self):
        return self.ident_

    def bundle_location(self):
        return dict(self.location)

    def ensure_agent(self, ident_):
        self.agent_calls += 1
        if isinstance(self.agent, Exception):
            raise self.agent
        return dict(self.agent)

    def request_harvest_now(self, ident_, wait_s):
        self.harvest_calls.append(wait_s)
        return dict(self.harvest) if self.harvest is not None else {"rc": 2, "done": False, "timed_out": True}

    def probe(self, ident_, **kw):
        self.probe_calls.append(dict(kw))               # web·copilot — 웹·코파일럿 탐침을 부탁했나(계약 §6.7)
        return self.probe_res

    def send_due(self):
        if isinstance(self.upload, Exception):
            raise self.upload
        return self.upload

    def export(self, pcdir, ident_, **kw):
        if self.export_fn is not None:
            return self.export_fn(pcdir, ident_, **kw)
        return super().export(pcdir, ident_, **kw)

    def child_env(self):
        return self.env

    def _src_of(self, argv) -> str | None:
        a = [str(x) for x in argv]
        if "-File" in a:
            name = os.path.basename(a[a.index("-File") + 1])
            sub = a[a.index("-Only") + 1] if "-Only" in a else ""
            return SCRIPT_SRC.get((name, sub))
        for x in a:
            if x.endswith(".py") and os.path.basename(x) != "lm27_pipe.py":
                sub = a[a.index("--kind") + 1] if "--kind" in a else ""
                return SCRIPT_SRC.get((os.path.basename(x), sub)) or SCRIPT_SRC.get((os.path.basename(x), ""))
        return None

    def spawn(self, argv, **kw):
        a = [str(x) for x in argv]
        if any(os.path.basename(x) == "lm27_pipe.py" for x in a):
            self.calls.append(("pipe", a[a.index("--src") + 1], a))
            if not self.real_pipe:
                b = self.sb.write_json(f"pipe_{len(self.calls)}.json", self.pipe_behave)
                a = [sys.executable, "-X", "utf8", "-B", str(FAKE_PIPE), "--behave", str(b)] + a[5:]
            return proc.spawn(a, **kw)
        src = self._src_of(a)
        self.calls.append(("collector", src, a))
        if src in self.real_collectors:                 # 진짜 수집기(주입점 환경만 — 복제 트리 통합 시험)
            return proc.spawn(a, **kw)
        spec = dict(self.specs.get(src) or {"rc": 1, "records": [], "status": {"rc": 1, "reasons": []}})
        spec.setdefault("src", src)
        p = self.sb.write_json(f"spec_{len(self.calls)}.json", spec)
        return proc.spawn([sys.executable, "-X", "utf8", "-B", str(FAKE_COLLECTOR), "--spec", str(p), "--src", src or ""],
                          **kw)

    def collector_calls(self, src=None) -> list:
        return [c for c in self.calls if c[0] == "collector" and (src is None or c[1] == src)]


def raw_index_row(i: int, day: str, *, box: str = "inbox") -> dict:
    """색인 수집기 원시 레코드 모양(합성 — 제목·주소는 자리표시자)."""
    ts = local_noon_utc(day, 9 + (i % 8))
    return {"internet_message_id": f"<wp33.{day}.{i}@corp.example>", "conversation_id": "%032X" % (i + 1),
            "conversation_topic": f"과제A 진행 {i}", "box": box, "folder_role": box, "sender_addr": "kim@corp.example",
            "sender_name": "김철수", "to": [{"addr": "hong@corp.example", "name": "홍길동"}], "cc": [],
            "subject": f"과제A 진행 {i}", "attach_names": [], "sensitivity": 0, "categories": [], "importance": 1,
            "has_attach": False, "in_reply_to": None, "headers_text": "", "body_text": "", "focused_other": False,
            "ts_utc": ts, "ts_local_offset": "+09:00", "ts_precision": "minute", "observed_at": ts,
            "confidence": 1.0, "flags": {}}


def utc_now_str() -> str:
    return NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
