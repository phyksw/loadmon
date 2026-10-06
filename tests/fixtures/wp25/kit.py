# -*- coding: utf-8 -*-
r"""WP-25 시험 도우미 — 합성 레지스트리(자리표시자만) · 작업 항목·단계 문맥·조립 · 정제 게이트 · %TEMP% 샌드박스(ROOT + LAD) ·
조회 어댑터 실행(스텁 전송 — 실제 Edge·Copilot 접속 0) · 로컬 금지어 목록(낱말을 출력하지 않는다).

모든 쓰기는 ``guard_write`` 로 확인한 %TEMP% 아래에만 한다(``Paths(root, lad=…)`` — 실제 트리·%LOCALAPPDATA% 미접촉).
키는 시험 전용 고정 바이트(실제 키링 아님). 이름·주소·도메인은 자리표시자(홍길동·김철수·과제A·고객사A·example).
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from lm27.bridge import exchange as X
from lm27.bridge.clock import VirtualClock
from lm27.bridge.env import CopilotEnv
from lm27.bridge.gate import GateBase
from lm27.bridge.messages import Notices
from lm27.bridge.runner import WorkItem
from lm27.bridge.stages import REGISTRY
from lm27.bridge.stages import base as B
from lm27.bridge.transport_stub import StubTransport
from lm27.config import Cfg, load_config, load_registry
from lm27.paths import Paths
from lm27.privacy import keys as K
from lm27.privacy.detect import SanitizeContext
from tests.fixtures.tree import guard_write

TREE = Path(__file__).resolve().parents[3]
SETTINGS = TREE / "config" / "settings_registry.json"
PC = "pc_0a1b2c3d4e5f6a7b"
RUN = "20261001-090000-ab12"
RUN2 = "20261002-090000-cd34"
NOW = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)          # 2026-10-01(목) 09:00 KST
MASTER = bytes(range(41, 73))                          # 시험 전용 주 키(32바이트)
ENV_SAFE = {"COMPUTERNAME": "DESKTOP-ZZTEST1", "USERNAME": "lm27tester", "USERDOMAIN": "EXAMPLEDOM"}
TEAM = {
    "schema": "lm27.registry/1", "version": 3,
    "projects": [
        {"id": "P-0007", "name": "과제A", "domain": "DEV", "codenames": ["PROJ-A"], "copilot_desc": "광학 모듈 신규 개발"},
        {"id": "P-0012", "name": "과제D", "domain": "EXT", "copilot_desc": "대학 공동연구 지원"},
    ],
    "agents": [
        {"id": "AG01", "name": "문서 초안 도우미", "copilot_desc": "문서 초안 작성", "step_types": ["DOC_DOC", "DOC_PPT"],
         "inputs": ["표", "메모"], "outputs": ["문서 초안"], "desc": "팀 화면 설명(코파일럿에 보내지 않음)"},
        {"id": "AG02", "name": "표 정리 도우미", "copilot_desc": "표 계산 결과 정리", "step_types": ["DOC_XLS"],
         "inputs": ["표"], "outputs": ["요약 표"]},
        {"id": "AG09", "name": "퇴역 도우미", "status": "retired", "copilot_desc": "옛 도구", "step_types": ["DOC_XLS"]},
    ],
    "agents_meta": {"catalog_version": "c1"},
}
DICT_REG = {"version": 12, "codes": {"projects": ["P-0007", "P-0012", "P-0003"], "vocab.field": ["MECH", "OPT", "ETC"],
                                     "vocab.func": ["DESIGN", "ANALYSIS", "ETC"], "vocab.wtype": ["DEV", "OFFICE"],
                                     "catalog": ["AG01", "AG02"]}}

_CFG: list = []


def cfg() -> Cfg:
    """선언 기본값 설정(개인 config.json 없음)."""
    if not _CFG:
        _CFG.append(Cfg(load_registry(SETTINGS)))
    return _CFG[0]


def reg(team=None):
    """유효 레지스트리(H §3.4 — 합성 팀 레지스트리, 개인 로컬 없음)."""
    from lm27.hier.registry import merge
    return merge(TEAM if team is None else team, None, cfg())


def big_team(n: int) -> dict:
    """과제 n 개 팀 레지스트리(설명 길이가 서로 다르게)."""
    doms = ["DEV", "MP", "EXT", "COM", "AX"]
    ps = [{"id": f"P-{i:04d}", "name": f"과제{i}", "domain": doms[i % 5],
           "copilot_desc": ("광학 모듈 과제 설명 " + "가" * (i % 17) + str(i))[:40]} for i in range(1, n + 1)]
    return {"schema": "lm27.registry/1", "version": 1, "projects": ps}


def work_env(**kw) -> CopilotEnv:
    base = {"tier": "premium", "work_toggle": "present", "work_mode": "work", "web_grounding": "off",
            "web_exposed": False}
    base.update(kw)
    return CopilotEnv(**base)


def exposed_env(**kw) -> CopilotEnv:
    base = {"tier": "unknown", "work_toggle": "unknown", "work_mode": "unknown", "web_grounding": "unknown",
            "web_exposed": True}
    base.update(kw)
    return CopilotEnv(**base)


def wi(key: str, fields: dict, rule=None, group: str = "", meta=None) -> WorkItem:
    return WorkItem(key=key, group=group, fields=dict(fields), rule=dict(rule or {}), ck="ck_" + key,
                    meta=dict(meta or {"priv_class": "work", "ad_band": "keep", "rules_ver": "2026.10.0"}))


def ctx_for(spec, registry=None, *, web: bool = False, settings=None, pack_out: int = 0) -> B.StageCtx:
    c = B.StageCtx(run_id=RUN, registry=registry, registry_version=B.registry_version(registry),
                   env=exposed_env() if web else work_env(), cfg=settings, pack_out=pack_out)
    c.codes_map = dict(spec.code_sets(c) or {})
    return c


def settings(overrides=None):
    from lm27.bridge.settings import from_cfg
    return from_cfg(cfg().derive(overrides) if overrides else cfg())


def assemble(spec, batch, ctx, rid: str = "R7F3QK", **kw):
    return X.assemble(spec, batch, ctx, rid, **kw)


def gate_base(paths=None, sctx=None) -> GateBase:
    return GateBase(sctx or SanitizeContext(), None, None, paths=paths, pc_id=None, policy="strict",
                    environ=dict(ENV_SAFE), machine_guid="")


def forbidden_words() -> list[str]:
    """로컬 금지어 목록(CR-06) — 시험이 대조에만 쓰고 출력하지 않는다. 없으면 []."""
    cands = [os.environ.get("LM27T_FORBIDDEN_WORDS") or ""]
    lad = os.environ.get("LOCALAPPDATA") or ""
    if lad:
        cands.append(os.path.join(lad, "LoadMonitor27", "dev", "forbidden_words.txt"))
    for p in cands:
        if p and os.path.isfile(p):
            with open(p, "rb") as fh:
                raw = fh.read().decode("utf-8-sig", errors="replace")
            return [w.strip() for w in raw.splitlines() if w.strip() and not w.strip().startswith("#")]
    return []


def spec(stage_id: str):
    return REGISTRY[stage_id]


# ───────────────────────── 어댑터(collect\Get-*ViaCopilot.py) ─────────────────────────
def _load(fname: str, modname: str):
    m = sys.modules.get(modname)
    if m is not None:
        return m
    s = importlib.util.spec_from_file_location(modname, TREE / "collect" / fname)
    m = importlib.util.module_from_spec(s)
    sys.modules[modname] = m
    s.loader.exec_module(m)
    return m


def adapter():
    """어댑터 한 벌 — 팀즈·일정 스크립트가 쓰는 모듈 이름과 같게 불러 한 번만 싣는다."""
    return _load("Get-MailViaCopilot.py", "lm27_collect_copilot_adapter")


def teams_adapter():
    return _load("Get-TeamsViaCopilot.py", "lm27t_collect_teams_copilot")


def cal_adapter():
    return _load("Get-CalViaCopilot.py", "lm27t_collect_cal_copilot")


def probe_module():
    return _load("probe_copilot.py", "lm27t_collect_probe_copilot")


class Sandbox:
    """%TEMP%\\lm27t_wp25_*\\{root\\{data,config}, lad} — 시험 하나의 ROOT·LAD. ``cleanup()`` 으로 지운다."""

    def __init__(self, **cfg_over):
        self.dir = guard_write(tempfile.mkdtemp(prefix="lm27t_wp25_"))
        self.root = self.dir / "root"
        (self.root / "data").mkdir(parents=True)
        (self.root / "config").mkdir()
        shutil.copy2(SETTINGS, self.root / "config" / "settings_registry.json")
        self.lad = self.dir / "lad"
        self.paths = Paths(self.root, lad=self.lad)
        self.cfg = load_config(self.paths, overrides=cfg_over or None)
        self.kr = K.Keyring(primary_kid=K.kid_of(MASTER), primary_secret=MASTER, all={K.kid_of(MASTER): MASTER})

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def api(self, *, fail_flush: bool = False) -> dict:
        """실물 정제·저장 묶음(``lm27.privacy.sanitize`` · ``lm27.store``) — 레코드 문맥만 시험 키·사전으로."""
        real = adapter().store_api()
        mk = real["make_record_context"]
        sb = self

        def mrc(root, src, pc_id, **kw):
            return mk(root, src, pc_id, paths=sb.paths, cfg=sb.cfg, keyring=sb.kr, registry={}, local=None,
                      os_names=["홍길동"])
        real["make_record_context"] = mrc
        if fail_flush:
            real_writer = real["SegmentWriter"]

            class Broken(real_writer):
                def flush(self):
                    raise OSError("디스크 가득")
            real["SegmentWriter"] = Broken
        return real

    def write_json(self, name: str, obj) -> Path:
        p = guard_write(self.dir / name)
        p.write_bytes(json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"))
        return p

    def blanks(self, d0="2026-09-01", d1="2026-09-07", axes=("mail_in", "mail_out"), src="mail.copilot",
               name="blanks.json") -> str:
        items = [{"todo_id": f"{src}:{d0}:{d1}:{a}", "date_range": [d0, d1], "kind_axis": a} for a in axes]
        return str(self.write_json(name, items))

    def rows(self, kind: str, src: str) -> list:
        from lm27.store import read_store_since
        return read_store_since(self.paths, PC, kind, src, None)[0]

    def cursor(self, src: str):
        from lm27.store import load_raw_cursor
        return (load_raw_cursor(self.paths, PC) or {}).get(src)

    def tree_bytes(self) -> bytes:
        """샌드박스의 모든 파일 바이트(gzip 은 풀어서) — 카나리아 검사용."""
        import gzip
        parts = []
        for f in sorted(self.dir.rglob("*")):
            if f.is_file():
                data = f.read_bytes()
                parts.append(gzip.decompress(data) if f.suffix == ".gz" else data)
        return b"\n".join(parts)


def run_adapter(sb: Sandbox, src: str, argv: list, *, rows=None, more=False, script=None, env=None, now=NOW,
                transport=None, caps_factory=None, bridge=None, api=None, answer_fn=None, registry=None):
    """어댑터 run(src, …) → (rc, 상태 dict, Notices, 응답기). 스텁 전송·가상 시계·시험 게이트·작업 모드 환경을 브리지에 주입."""
    from tests.bridge.stub_responder import StubResponder
    resp = StubResponder([REGISTRY[s] for s in ("lookup_mail", "lookup_teams", "lookup_calendar")], script=script,
                         rows=rows, more=more, answer_fn=answer_fn)
    bkw = {"transport": transport or StubTransport(resp), "env": env or work_env(),
           "registry": registry if registry is not None else {"version": 1}, "gate_base": gate_base(sb.paths),
           "clock": VirtualClock(), "heartbeat": False}
    notices = Notices()
    err = io.StringIO()
    rc = adapter().run(src, [*argv, "--pc", PC, "--events", "off"], paths=sb.paths, cfg=sb.cfg, environ={}, now=now,
                       api=api or sb.api(), bridge=bridge, bridge_kw=bkw, caps_factory=caps_factory, notices=notices,
                       err=err)
    lines = [x for x in err.getvalue().splitlines() if x.strip()]
    status = json.loads(lines[-1])["_status"] if lines else {}
    return rc, status, notices, resp
