# -*- coding: utf-8 -*-
r"""스텁 전송(B §11.4) — 브라우저 층 없이 L2·L3 를 돌리는 ``StubTransport``(시험·합성 E2E 전용).

  · 시험(같은 프로세스): ``StubTransport(responder)`` — ``responder(prompt, rid, stage) -> (phase, body)``.
  · 하위 프로세스 E2E: 환경 변수 ``LM_COPILOT_STUB=<폴더>`` 이면 ``from_env()`` 가 ``FileResponder`` 로 만든다.
    폴더의 ``<stage>.json`` 이 단계별 답을 정한다(LM24 의 '프롬프트 첫 키로 파일 고르기' 대신 **단계 ID 로 직접**)::

        {"mode": ["ok"], "default": {"act": "info", "conf": "m"}, "by_key": {"msg:4c1d…": {"act": "request"}},
         "rows": [ … ], "more": false}

    ``mode`` 는 그 단계의 질의 순번별 모드 목록(마지막 것이 반복). 모드: ``ok`` ``partial:<비율>`` ``truncate:<비율>``
    ``echo`` ``stale`` ``empty`` ``format`` ``refusal`` ``unavailable`` ``nolic`` ``service_error`` ``forbidden_time``
    ``unknown_code`` ``pii_in_answer``. 답에는 rid 와 항목 번호가 자동으로 채워진다. 조회 단계(``[항목]`` 줄이 없는
    프롬프트)는 ``rows`` 를 행으로 돌려준다.
  · 받은 프롬프트는 메모리(``sent_texts``)에만 둔다 — 카나리아 검사용, 디스크에 쓰지 않는다.
  · 결과 봉투의 ``transport`` 가 ``"stub"`` 이라 산출물에 스텁 흔적이 남는다. 배포 설정에 이 변수가 있으면 probe 가 경고한다.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets

from lm27.bridge import fsio
from lm27.bridge.transport import RID_RX, SendRequest, SendResult, norm, pledge_rx

ENV_VAR = "LM_COPILOT_STUB"
MODES = ("ok", "partial", "truncate", "echo", "stale", "empty", "format", "refusal", "unavailable", "nolic",
         "service_error", "forbidden_time", "unknown_code", "pii_in_answer")
_STAGE_RX = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_ITEM_HEAD_RX = re.compile(r"^\s*\[항목\]")
_ITEM_LINE_RX = re.compile(r"^\s*(\d{1,4})\s*\|")
_FORMAT_RX = re.compile(r"^-\s*형식\([^)]*\)\s*:\s*(.+)$")
_RID_ALPHA = "23456789ABCDEFGHJKMNPQRSTVWXYZ"

# 정형 문구(L2 분류표의 표식과 같은 계열 — 시험 재료)
REFUSAL_TEXT = "죄송합니다. 이 요청은 도와드릴 수 없습니다."
UNAVAILABLE_TEXT = "조회 도구가 없어 요청하신 기간의 내용을 찾을 수 없습니다."
NOLIC_TEXT = "업무 데이터에 액세스할 수 없습니다. 이 계정에서는 메일과 채팅을 근거로 쓸 수 없습니다."
SERVICE_ERROR_TEXT = "죄송합니다. 지금은 응답할 수 없습니다. 잠시 후 다시 시도해 주세요."
FORMAT_TEXT = "요청하신 항목을 검토했습니다. 대부분 업무 관련 내용으로 보입니다."
UNKNOWN_CODE = "X_UNKNOWN_CODE"


def item_ids(prompt: str) -> list[int]:
    """프롬프트 ``[항목]`` 줄 아래 ``번호 | …`` 줄의 번호들(``[답 형식]`` 앞까지)."""
    ids, inside = [], False
    for line in str(prompt or "").splitlines():
        if _ITEM_HEAD_RX.match(line):
            inside = True
            continue
        if inside:
            if line.strip().startswith("["):
                break
            m = _ITEM_LINE_RX.match(line)
            if m:
                ids.append(int(m.group(1)))
    return ids


def other_rid(rid: str) -> str:
    """rid 와 다른 형식 맞는 rid(지난 답 흉내 — stale)."""
    while True:
        r = "R" + "".join(secrets.choice(_RID_ALPHA) for _ in range(5))
        if r != rid and RID_RX.match(r):
            return r


def _fake_phone() -> str:
    # 합성 전화번호를 런타임에 조립한다(저장소 텍스트에 번호 리터럴을 두지 않는다)
    return "-".join(("0" + "1" + "0", "7" * 4, "3" * 4))


def envelope_text(rid: str, items: list, n: int | None = None, *, more: bool | None = None,
                  pledge: bool = True) -> str:
    env = {"rid": rid, "n": len(items) if n is None else n}
    if more is not None:
        env["more"] = more
    env["items"] = items
    body = "```json\n" + json.dumps(env, ensure_ascii=False) + "\n```"
    return body + (f"\n[[END {rid}]]" if pledge else "")


def build_reply(mode: str, rid: str, ids: list[int], answers: dict | None = None, *, rows: list | None = None,
                more: bool = False, prompt: str = "") -> tuple[str, str]:
    """모드 하나 → (phase, body). ``answers`` = 번호 → 답 dict(없으면 빈 dict)."""
    name, _, arg = str(mode or "ok").partition(":")
    if name not in MODES:
        raise ValueError(f"스텁 모드가 아닙니다: {mode}")
    answers = answers or {}
    if rows is not None and not ids:                     # 조회 단계 — 행 목록
        items = [{"id": i + 1, **r} for i, r in enumerate(rows) if isinstance(r, dict)]
        lookup = True
    else:
        items = [{"id": i, **(answers.get(i) or {})} for i in ids]
        lookup = False
    if name == "ok":
        return "stub", envelope_text(rid, items, more=more if lookup else None)
    if name == "partial":
        r = float(arg or 0.5)
        keep = items[:max(0, min(len(items), math.floor(len(items) * r)))]
        return "stub", envelope_text(rid, keep, n=len(items), more=more if lookup else None)
    if name == "truncate":
        r = float(arg or 0.5)
        full = envelope_text(rid, items, more=more if lookup else None, pledge=False)
        return "stub", full[:max(1, int(len(full) * r))]
    if name == "echo":
        fmt = ""
        for line in str(prompt or "").splitlines():
            m = _FORMAT_RX.match(line.strip())
            if m:
                fmt = m.group(1)
        return "stub", "```json\n" + (fmt or '{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>} ]}') + "\n```"
    if name == "stale":
        r2 = other_rid(rid)
        return "stub", envelope_text(r2, items)
    if name == "empty":
        return "stub", ""
    if name == "format":
        return "stub", FORMAT_TEXT + f"\n[[END {rid}]]"
    if name == "refusal":
        return "stub", REFUSAL_TEXT
    if name == "unavailable":
        return "stub", UNAVAILABLE_TEXT
    if name == "nolic":
        return "stub", NOLIC_TEXT
    if name == "service_error":
        return "stub", SERVICE_ERROR_TEXT
    first = dict(items[0]) if items else {"id": ids[0] if ids else 1}
    if name == "forbidden_time":
        first["start"] = "09:00"
    elif name == "unknown_code":
        k = next((k for k, v in first.items() if k != "id" and isinstance(v, str)), "code")
        first[k] = UNKNOWN_CODE
    elif name == "pii_in_answer":
        k = next((k for k, v in first.items() if k != "id" and isinstance(v, str)), "note")
        first[k] = str(first.get(k) or "") + " 담당 홍길동 연락처 " + _fake_phone()
    return "stub", envelope_text(rid, [first] + items[1:], more=more if lookup else None)


class FileResponder:
    """``LM_COPILOT_STUB`` 폴더의 ``<stage>.json`` 으로 답을 만든다. 단계 파일이 없으면 ``ok`` + 빈 답."""

    def __init__(self, stub_dir):
        self.dir = os.fspath(stub_dir)
        self.counts: dict[str, int] = {}
        self._cache: dict[str, dict] = {}

    def spec(self, stage: str) -> dict:
        if stage not in self._cache:
            if not _STAGE_RX.match(stage or ""):
                raise ValueError("스텁: 단계 이름 형식이 아닙니다")
            d = fsio.read_json(fsio.child(self.dir, stage + ".json"), {})
            self._cache[stage] = d if isinstance(d, dict) else {}
        return self._cache[stage]

    def respond(self, prompt: str, rid: str, stage: str, item_keys=()) -> tuple[str, str]:
        sp = self.spec(stage)
        modes = sp.get("mode") or ["ok"]
        modes = [modes] if isinstance(modes, str) else list(modes)
        k = self.counts.get(stage, 0)
        self.counts[stage] = k + 1
        mode = modes[min(k, len(modes) - 1)]
        ids = item_ids(prompt)
        default = sp.get("default") if isinstance(sp.get("default"), dict) else {}
        by_key = sp.get("by_key") if isinstance(sp.get("by_key"), dict) else {}
        answers = {}
        for i in ids:
            key = item_keys[i - 1] if 0 < i <= len(item_keys) else None
            ans = dict(default)
            if key is not None and isinstance(by_key.get(key), dict):
                ans.update(by_key[key])
            answers[i] = ans
        rows = sp.get("rows") if isinstance(sp.get("rows"), list) else ([] if not ids else None)
        return build_reply(mode, rid, ids, answers, rows=rows, more=bool(sp.get("more")), prompt=prompt)

    def __call__(self, prompt: str, rid: str, stage: str) -> tuple[str, str]:
        return self.respond(prompt, rid, stage)


class StubTransport:
    """L1 대체(B §11.4). ``responder(prompt, rid, stage) -> (phase, body)`` — ``respond(…, item_keys)`` 가 있으면 그것."""

    kind = "stub"

    def __init__(self, responder=None, *, stub_dir=None, work_mode: str = "unknown"):
        if responder is None:
            if stub_dir is None:
                raise ValueError("StubTransport: responder 또는 stub_dir 가 필요합니다")
            responder = FileResponder(stub_dir)
        self.responder = responder
        self.work_mode = work_mode
        self.sends = 0
        self.chat_seq = 0
        self.sent_texts: list[str] = []          # 메모리만(카나리아 검사용)
        self.requests: list[SendRequest] = []
        self.opened = False
        self.closed = False

    def open(self) -> str:
        self.opened = True
        return "ready"

    def new_chat(self) -> bool:
        self.chat_seq += 1
        return True

    def close(self) -> None:
        self.closed = True

    def roundtrip(self, req: SendRequest) -> SendResult:
        self.sends += 1
        self.sent_texts.append(req.text)
        self.requests.append(req)
        if req.fresh:
            self.new_chat()
        fn = getattr(self.responder, "respond", None)
        if callable(fn):
            phase, body = fn(req.text, req.rid, req.stage, req.item_keys)
        else:
            phase, body = self.responder(req.text, req.rid, req.stage)
        body = body or ""
        n = len(norm(req.text))
        done = "pledge" if pledge_rx(req.rid).search(body) else ("stable" if body else "")
        return SendResult(phase=phase, body=body, done_by=done, pick="stub", busy_seen=None, in_chars=n,
                          injected_chars=n, model_note="stub", model_used=req.model, work_mode=self.work_mode,
                          chat_seq=self.chat_seq)


def from_env(environ=None) -> StubTransport | None:
    """``LM_COPILOT_STUB`` 가 있으면 그 폴더의 ``StubTransport``, 없으면 None. 폴더가 없으면 ValueError(조용히 실전송 금지)."""
    environ = os.environ if environ is None else environ
    v = str(environ.get(ENV_VAR) or "").strip()
    if not v:
        return None
    if not os.path.isdir(v):
        raise ValueError(f"{ENV_VAR} 폴더가 없습니다")
    return StubTransport(stub_dir=v)
