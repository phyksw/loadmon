# -*- coding: utf-8 -*-
"""스텁 응답기(B §11.4) — 프롬프트의 ``[항목]`` 줄에서 번호를 읽고 단계 스키마에 맞는 답을 만든다.

    r = StubResponder(stages, script={"t_act": ["truncate:0.6", "ok"]})     # 단계별 질의 순번 모드(마지막 반복)
    r = StubResponder(stages, noise={"partial:0.5": 0.10, "truncate:0.5": 0.05, "empty": 0.03,
                                     "service_error": 0.02}, seed=7)        # 전송마다 결정적 난수로 모드
    t = StubTransport(r)

모드: ``transport_stub.build_reply`` 의 것(ok·partial·truncate·echo·stale·empty·format·refusal·unavailable·nolic·
service_error·forbidden_time·unknown_code·pii_in_answer) + ``phase:<L1 단계>``(치명·전송 실패 흉내) + ``crash``(프로세스
강제 종료 흉내 — ``Crash`` 는 BaseException). 답 값은 ``answers``(항목 key → 답) → 단계 ``stub_answer()`` 순.
조회형은 ``rows``(구간 key → 행 목록, 또는 함수)를 돌려준다. 받은 프롬프트는 메모리(``prompts``)에만 둔다.
"""
from __future__ import annotations

import random
from collections import Counter

from lm27.bridge.transport_stub import build_reply, item_ids


class Crash(BaseException):
    """강제 종료 흉내(except Exception 에 잡히지 않는다)."""


class StubResponder:
    def __init__(self, stages=None, *, script=None, default="ok", answers=None, rows=None, more=False, noise=None,
                 seed=0, answer_fn=None):
        self.stages = {s.id: s for s in (stages or ())} if not isinstance(stages, dict) else dict(stages)
        self.script = dict(script or {})
        self.default = default
        self.answers = dict(answers or {})
        self.rows = rows
        self.more = more
        self.noise = dict(noise or {})
        self.rng = random.Random(seed)
        self.answer_fn = answer_fn
        self.count: Counter = Counter()
        self.modes: list = []
        self.prompts: list = []

    def _mode(self, stage: str) -> str:
        k = self.count[stage]
        self.count[stage] += 1
        seq = self.script.get(stage)
        if seq:
            return seq[min(k, len(seq) - 1)]
        if self.noise:
            x = self.rng.random()
            acc = 0.0
            for m, p in self.noise.items():
                acc += p
                if x < acc:
                    return m
        return self.default

    def _answer(self, spec, key):
        if self.answer_fn is not None:
            a = self.answer_fn(spec, key)
            if a is not None:
                return a
        if key in self.answers:
            return dict(self.answers[key])
        return spec.stub_answer() if spec is not None else {}

    def respond(self, prompt, rid, stage, item_keys=()):
        mode = self._mode(stage)
        self.modes.append((stage, mode))
        self.prompts.append(prompt)
        if mode == "crash":
            raise Crash("강제 종료 흉내")
        if mode.startswith("phase:"):
            return mode.split(":", 1)[1], ""
        spec = self.stages.get(stage)
        ids = item_ids(prompt)
        answers = {i: self._answer(spec, item_keys[i - 1] if 0 < i <= len(item_keys) else None) for i in ids}
        rows = None
        more = False
        if spec is not None and spec.kind == "lookup":
            key = item_keys[0] if item_keys else ""
            rows = self.rows(key) if callable(self.rows) else list((self.rows or {}).get(key, []))
            more = self.more(key) if callable(self.more) else bool(self.more)
        return build_reply(mode, rid, ids, answers, rows=rows, more=more, prompt=prompt)

    def __call__(self, prompt, rid, stage):
        return self.respond(prompt, rid, stage)
