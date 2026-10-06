# -*- coding: utf-8 -*-
"""WP-24 시험 조립 — %TEMP% 임시 트리(Paths) · 가상 시계 · 스텁 전송 · 정제 게이트 · 합성 ai_in.

    rig = Rig(stages=[ActStage()], script={"t_act": ["ok"]})
    rig.write_ai_in("t_act", rows)          # [{key, group?, fields, rule?, meta?}]
    results = rig.run()                      # run_stages(rt, specs)
    rig.store("t_act") · rig.ai_out("t_act") · rig.result("t_act") · rig.journal("t_act") · rig.tree_bytes()

실제 Edge·네트워크·메일·팀즈 0. 감사·저장소·결과 봉투는 모두 임시 트리 안에만 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from lm27.bridge.clock import VirtualClock
from lm27.bridge.env import CopilotEnv
from lm27.bridge.gate import GateBase, clock_iso_of
from lm27.bridge.messages import Notices
from lm27.bridge.runner import make_runtime, run_stages
from lm27.bridge.session import BridgeProfile
from lm27.bridge.transport_stub import StubTransport
from lm27.config import load_config
from lm27.bridge.settings import load_settings
from lm27.paths import Paths
from lm27.privacy.detect import SanitizeContext

from tests.bridge.stub_responder import StubResponder

TREE = Path(__file__).resolve().parents[3]
REGISTRY_FILE = TREE / "config" / "settings_registry.json"
RUN = "20261005-101500-3fa2"
RUN2 = "20261006-090000-0b2c"
ENV_SAFE = {"COMPUTERNAME": "DESKTOP-ZZTEST1", "USERNAME": "lm27tester", "USERDOMAIN": "EXAMPLEDOM"}
REG = {"version": 12, "codes": {"projects": ["P-0007", "P-0012", "P-0003"], "vocab.field": ["MECH", "OPT", "ETC"],
                                "vocab.func": ["DESIGN", "ANALYSIS", "ETC"], "catalog": ["AG01", "AG02"]}}


def work_env(**kw) -> CopilotEnv:
    """업무 모드 + 웹 근거 끔 확인(web_exposed=False)."""
    base = {"tier": "premium", "work_toggle": "present", "work_mode": "work", "web_grounding": "off",
            "web_exposed": False}
    base.update(kw)
    return CopilotEnv(**base)


def exposed_env(**kw) -> CopilotEnv:
    base = {"tier": "unknown", "work_toggle": "unknown", "work_mode": "unknown", "web_grounding": "unknown",
            "web_exposed": True}
    base.update(kw)
    return CopilotEnv(**base)


def settings(tmp: str, overrides=None):
    cfg = load_config(registry_path=REGISTRY_FILE, config_path=Path(tmp) / "no_config.json", overrides=overrides)
    return load_settings(cfg=cfg), cfg


class Rig:
    def __init__(self, *, stages=(), script=None, noise=None, seed=0, answers=None, rows=None, more=False,
                 overrides=None, env=None, registry=REG, sctx=None, responder=None, transport=None, run_id=RUN,
                 answer_fn=None, clock=None, tmp=None):
        self.tmp = tmp or tempfile.mkdtemp(prefix="lm27t_wp24_")
        self.own_tmp = tmp is None
        self.paths = Paths(os.path.join(self.tmp, "root"), lad=os.path.join(self.tmp, "lad"))
        os.makedirs(self.paths.root, exist_ok=True)
        self.clock = clock or VirtualClock()
        self.cfg, self.raw_cfg = settings(self.tmp, overrides)
        self.stages = list(stages)
        self.events: list = []
        self.notices = Notices(emit=self._emit)
        self.profile = BridgeProfile(self.paths)
        self.responder = responder or StubResponder(self.stages, script=script, noise=noise, seed=seed,
                                                    answers=answers, rows=rows, more=more, answer_fn=answer_fn)
        self.transport = transport if transport is not None else StubTransport(self.responder)
        self.sctx = sctx or SanitizeContext()
        self.registry = registry
        self.env = env if env is not None else work_env()
        self.run_id = run_id
        self.rt = None
        self.new_runtime()

    def _emit(self, ev, **fields):
        self.events.append((ev, fields))

    def notified(self) -> list:
        return [f.get("code") for ev, f in self.events if ev == "notice"]

    def gate_base(self):
        return GateBase(self.sctx, None, None, paths=self.paths, pc_id=None, policy=self.cfg.web_exposure_policy,
                        clock_iso=clock_iso_of(self.clock), environ=dict(ENV_SAFE), machine_guid="")

    def new_runtime(self, *, run_id=None, transport=None, env=None):
        self.run_id = run_id or self.run_id
        if transport is not None:
            self.transport = transport
        if env is not None:
            self.env = env
        self.rt = make_runtime(self.paths, self.run_id, cfg=self.cfg, clock=self.clock, transport=self.transport,
                               gate_base=self.gate_base(), env=self.env, profile=self.profile, notices=self.notices,
                               emit=self._emit, registry=self.registry, raw_cfg=self.raw_cfg)
        return self.rt

    def write_ai_in(self, stage: str, rows) -> None:
        p = Path(self.paths.ai_in(stage))
        p.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        p.write_bytes(body.encode("utf-8"))

    def run(self, stages=None):
        return run_stages(self.rt, list(stages if stages is not None else self.stages))

    # ── 읽기 ───────────────────────────────────────────────────────────
    def _jsonl(self, p):
        p = Path(p)
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def store(self, stage: str) -> list:
        return self._jsonl(self.paths.ai_store(stage))

    def journal(self, stage: str, run_id=None) -> list:
        from lm27.bridge.journal import run_file
        return self._jsonl(run_file(self.paths, run_id or self.run_id, "journal", stage))

    def result(self, stage: str, run_id=None) -> dict:
        from lm27.bridge.journal import run_file
        return json.loads(Path(run_file(self.paths, run_id or self.run_id, "result", stage)).read_text("utf-8"))

    def ai_out(self, stage: str) -> dict:
        return json.loads(Path(self.paths.ai_out(stage)).read_text(encoding="utf-8"))

    def sends(self) -> int:
        return getattr(self.transport, "sends", 0)

    def tree_bytes(self):
        """임시 트리의 모든 파일 (상대 경로, 바이트) — 카나리아 검사용."""
        out = []
        for p in sorted(Path(self.tmp).rglob("*")):
            if p.is_file():
                out.append((p.relative_to(self.tmp).as_posix(), p.read_bytes()))
        return out

    def cleanup(self):
        if self.own_tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


def act_rows(n: int, *, start: int = 0, text="도면 검토 부탁드립니다", group="") -> list:
    out = []
    for i in range(start, start + n):
        out.append({"key": f"msg:{i:05d}", "group": group,
                    "fields": {"ch": "teams" if i % 2 else "mail", "dir": "in", "chat": "1:1", "prev": "-",
                               "text": f"{text} {i}번 항목"},
                    "rule": {"act": "request"}, "meta": {"priv_class": "work", "ad_band": "keep", "rules_ver": "x"}})
    return out


def label_rows(n: int, *, start: int = 0) -> list:
    out = []
    for i in range(start, start + n):
        out.append({"key": f"grp:{i:05d}", "group": "P-0012" if i % 3 else "P-0007",
                    "fields": {"kinds": "메일발신 3·문서 1", "subjects": [f"[과제:P-0012] 공차 해석 결과 공유 {i}"],
                               "files": [f"공차해석_{i}.xlsx"], "apps": ["해석 프로그램"], "domains": ["사내"],
                               "cands": [["P-0012", 0.62]]},
                    "rule": {"project": "P-0012", "field": "OPT", "func": "ANALYSIS", "title": "공차 해석",
                             "reg_set": "ab12cd34"}})
    return out


def flow_rows(n: int, *, start: int = 0) -> list:
    out = []
    for i in range(start, start + n):
        steps = [["S1", "REQ_IN"], ["S2", "APP_CAE"], ["S3", "DOC_XLS"], ["S4", "MEET"], ["S5", "REPORT_OUT"]]
        out.append({"key": f"ws:W{i:04d}", "group": "P-0012" if i % 2 else "P-0007",
                    "fields": {"project": "P-0012", "func": "ANALYSIS", "steps": steps,
                               "tasks": [f"공차 해석 {i}", "시험 지그 설계"]}})
    return out


def review_rows(n: int) -> list:
    return [{"key": f"review:week:2026-W{40 + i}", "fields": {"kind": "week", "period": f"2026-W{40 + i}",
                                                            "facts": [["F1", "완료"], ["F2", "진행"]]}}
            for i in range(n)]


def agent_rows(n: int) -> list:
    return [{"key": f"ag:T{i:03d}", "fields": {"type": "DOC_XLS", "label": f"결과 정리 {i}", "freq": "주 1~2회"}}
            for i in range(n)]


def sub_rows(n: int) -> list:
    return [{"key": f"sa:W{i:04d}", "fields": {"project": "P-0012", "role": f"해석 담당 {i}",
                                               "steps": ["S1 의뢰 접수", "S2 해석 수행"]}} for i in range(n)]


def window_rows(stage: str, windows) -> list:
    return [{"key": f"{stage}:{a}:{b}", "fields": {"d0": a, "d1": b}} for a, b in windows]
