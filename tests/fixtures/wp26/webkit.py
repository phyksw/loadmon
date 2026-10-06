# -*- coding: utf-8 -*-
r"""WP-26 시험 도우미 — %TEMP% 샌드박스(ROOT + LAD) · 설정 · 고정 시험 키링 · 실물 정제·저장 묶음(WP-11) · 화면 응답
(``LM_OWA_FAKE`` · ``LM_TEAMSWEB_FAKE`` 모양 — ``tests\fixtures\synth\inject.py`` 머리 표 + 수집기 머리말의 선택 키) 만들기.

모든 쓰기는 ``guard_write`` 로 확인한 %TEMP% 아래에만 한다(``Paths(root, lad=…)`` — 실제 트리·실제 %LOCALAPPDATA% 미접촉).
키는 시험 전용 고정 바이트(실제 키링 아님). 이름·주소·도메인은 자리표시자(홍길동·김철수·동료B·과제A·example).
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27.config import load_config
from lm27.paths import Paths
from lm27.privacy import keys as K
from lm27.store import read_store_since
from tests.fixtures.tree import guard_write

TREE = Path(__file__).resolve().parents[3]
FIX = Path(__file__).resolve().parent
PC = "pc_0a1b2c3d4e5f6a7b"
MASTER = bytes(range(41, 73))                       # 시험 전용 주 키(32바이트)
ME = "홍길동"
KIM = "김철수"
PEER = "동료B"
REGISTRY = {"internal_domains": ["corp.example"],
            "customers": [{"id": "C01", "names": ["고객사A"], "domains": ["custa.example"]}],
            "projects": [{"id": "P-0001", "codenames": ["과제A"]}]}
OFF = 540                                          # 시험 시계의 로컬 오프셋(+09:00)
NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)      # 2026-10-01(목) 09:00 KST
TODAY = date(2026, 10, 1)


def off_fn(_dt) -> int:
    return OFF


def _load(fname: str, modname: str):
    m = sys.modules.get(modname)
    if m is not None:
        return m
    spec = importlib.util.spec_from_file_location(modname, TREE / "collect" / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


# 수집기와 같은 모듈 이름으로 불러 한 벌을 함께 쓴다(Get-TeamsWeb.py·탐침이 Get-OutlookWeb.py 를 이 이름으로 부른다)
OWA = _load("Get-OutlookWeb.py", "lm27_collect_owa_web")
TW = _load("Get-TeamsWeb.py", "lm27_collect_teams_web")
POWA = _load("probe_owa.py", "lm27_collect_probe_owa")
PTW = _load("probe_teamsweb.py", "lm27_collect_probe_teamsweb")


def keyring(master: bytes = MASTER) -> K.Keyring:
    kid = K.kid_of(master)
    return K.Keyring(primary_kid=kid, primary_secret=master, all={kid: master})


class Sandbox:
    """%TEMP%\\lm27t_wp26_*\\{root\\{data,config}, lad} — 시험 하나의 ROOT·LAD. ``cleanup()`` 으로 지운다."""

    def __init__(self, **cfg_over):
        self.dir = guard_write(tempfile.mkdtemp(prefix="lm27t_wp26_"))
        self.root = self.dir / "root"
        (self.root / "data").mkdir(parents=True)
        (self.root / "config").mkdir()
        shutil.copy2(TREE / "config" / "settings_registry.json", self.root / "config" / "settings_registry.json")
        self.lad = self.dir / "lad"
        self.paths = Paths(self.root, lad=self.lad)
        self.cfg = load_config(self.paths, overrides=cfg_over or None)

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def api(self, *, registry=None, os_names=("홍길동",), kr=None, local=None) -> dict:
        """실물 정제·저장 묶음(``lm27.privacy.sanitize`` · ``lm27.store``) — 레코드 문맥만 시험 키·사전·본인 이름으로."""
        real = OWA.store_api()
        mk = real["make_record_context"]
        k = kr or keyring()
        reg = REGISTRY if registry is None else registry
        self.contexts = []

        def mrc(root, src, pc_id, **kw):
            kw.pop("cfg", None)
            kw.pop("paths", None)
            rc = mk(root, src, pc_id, paths=self.paths, cfg=self.cfg, keyring=k, registry=reg, local=local,
                    os_names=list(os_names), **kw)
            self.contexts.append(rc)
            return rc

        real["make_record_context"] = mrc
        return real

    def write_json(self, name: str, obj) -> Path:
        p = guard_write(self.dir / name)
        p.write_bytes(json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
        return p

    def rows(self, kind: str, src: str) -> list:
        return read_store_since(self.paths, PC, kind, src, None)[0]

    def cursor(self, src: str) -> dict:
        return (OWA.store_api()["load_raw_cursor"](self.paths, PC) or {}).get(src) or {}

    def store_bytes(self) -> bytes:
        parts = []
        root = self.paths.store_root()
        for f in sorted(root.rglob("*")) if root.is_dir() else []:
            if f.is_file() and not f.name.endswith(".lock"):
                data = f.read_bytes()
                parts.append(gzip.decompress(data) if f.suffix == ".gz" else data)
        return b"\n".join(parts)

    def audit_lines(self) -> list:
        base = self.paths.privacy_audit_file("2026-10-01").parent.parent
        out = []
        for f in sorted(base.rglob("*.jsonl")) if base.is_dir() else []:
            out += [json.loads(x) for x in f.read_bytes().splitlines() if x.strip()]
        return out


def run_owa(sb: Sandbox, argv: list, *, fake=None, environ=None, now=NOW, clock=None, api=None, cost=0.0,
            session_factory=None):
    """Get-OutlookWeb.run(…) → (rc, 상태 dict, stderr 글)."""
    import io
    from lm27.bridge.clock import VirtualClock
    env = dict(environ or {})
    if fake is not None:
        env["LM_OWA_FAKE"] = str(sb.write_json("owa_fake.json", fake))
    err = io.StringIO()
    rc = OWA.run([*argv, "--pc", PC, "--events", "off"], paths=sb.paths, cfg=sb.cfg, api=api or sb.api(), now=now,
                 clock=clock or VirtualClock(), off_fn=off_fn, environ=env, err=err, fake_cost_s=cost,
                 session_factory=session_factory)
    return rc, status_of(err.getvalue()), err.getvalue()


def run_tw(sb: Sandbox, argv: list, *, fake=None, environ=None, now=NOW, clock=None, api=None, cost=0.0,
           session_factory=None):
    """Get-TeamsWeb.run(…) → (rc, 상태 dict, stderr 글)."""
    import io
    from lm27.bridge.clock import VirtualClock
    env = dict(environ or {})
    if fake is not None:
        env["LM_TEAMSWEB_FAKE"] = str(sb.write_json("tw_fake.json", fake))
    err = io.StringIO()
    rc = TW.run([*argv, "--pc", PC, "--events", "off"], paths=sb.paths, cfg=sb.cfg, api=api or sb.api(), now=now,
                clock=clock or VirtualClock(), off_fn=off_fn, environ=env, err=err, fake_cost_s=cost,
                session_factory=session_factory)
    return rc, status_of(err.getvalue()), err.getvalue()


def status_of(err_text: str) -> dict:
    """stderr 마지막 줄의 ``{"_status": …}``(계약 v1.2 C1)."""
    lines = [x for x in err_text.splitlines() if x.strip()]
    last = json.loads(lines[-1]) if lines else {}
    return last.get("_status") or {}


# ───────────────────────────── 화면 응답 만들기(합성) ─────────────────────────────
def owa_item(who: str, subject: str, when: str, *, key: str | None = None, preview: str = "", head=None,
             extra_texts=()) -> dict:
    """메일 목록 항목(aria-label · title · 잎 글자). ``head`` = 보낸 항목을 열었을 때 읽기 창 머리(선택 키 open)."""
    texts = [who, subject] + ([preview] if preview else []) + [when, *extra_texts]
    label = f"{who}, {subject}, {when}"
    it = {"key": key or ("k|" + label[:60]), "label": label, "titles": [subject], "texts": texts}
    if head is not None:
        it["open"] = {"head": list(head)}
    return it


def kdate(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def ampm(h: int, m: int) -> str:
    return f"{'오전' if h < 12 else '오후'} {h % 12 or 12}:{m:02d}"


def owa_event(subject: str, d: date, start: tuple, end: tuple, place: str = "", *, extra: str = "") -> dict:
    t = f"{ampm(*start)} - {ampm(*end)}"
    label = f"{subject}, {kdate(d)} {t}, {place}" + (f", {extra}" if extra else "")
    return {"label": label, "texts": [subject, t, place]}


def tw_sep(d: date) -> dict:
    return {"t": "sep", "text": kdate(d)}


def tw_msg(author: str, body: str, *, h: int = 9, m: int = 5, d: date | None = None, mid: str = "", iso: bool = False,
           files=(), me=None) -> dict:
    """대화 화면 메시지(inject.py 모양). ``iso`` 면 <time datetime>(UTC) — d 가 있어야 한다."""
    it = {"t": "msg", "label": f"{author} {ampm(h, m)} {body[:60]}", "author": author, "ts": ampm(h, m),
          "iso": [], "titles": list(files), "body": body, "texts": [author, body, *files], "mid": mid}
    if iso and d is not None:
        it["iso"] = [(datetime(d.year, d.month, d.day, h, m, tzinfo=UTC) - timedelta(minutes=OFF))
                     .strftime("%Y-%m-%dT%H:%M:%SZ")]
    if me is not None:
        it["me"] = me
    return it


def tw_room(idx, tid: str, label: str) -> dict:
    return {"idx": idx, "label": label, "texts": [label], "tid": tid}


def tw_fake(rooms: list, msgs: dict, **extra) -> dict:
    out = {"login": False, "chats": {"how": "[role=treeitem]", "n": len(rooms), "items": rooms},
           "msgs": {str(k): v for k, v in msgs.items()}}
    out.update(extra)
    return out


def tid(n: int, kind: str = "group") -> str:
    """대화 ID 모양(19:…@thread… — 도메인 자리는 실제 모양, 내용은 합성 16진)."""
    h = f"{n:032x}"
    return {"group": f"19:{h}@thread.v2", "channel": f"19:{h}@thread.tacv2", "one": f"19:{h}_{h}@unq.gbl.spaces",
            "plain": f"19:{h}@thread.example"}[kind]
