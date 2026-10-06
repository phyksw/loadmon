# -*- coding: utf-8 -*-
r"""개인정보 재검사 게이트 연결(B §9 · P §13 G3) — **``lm27.privacy`` 를 import 하는 유일한 브리지 파일.**

    base = GateBase.open(paths, cfg, kr=kr, registry=reg, pc_id=pc_id)      # 호출 1회(정제 문맥·카나리아)
    sg = base.for_stage(spec.id, web_exposed=env.web_exposed)               # 단계마다(감사 stage="copilot:<단계>")
    kept, dropped = sg.items(spec, work_items)        # ① 항목 게이트 gate_copilot + ①' 웹 노출 엄격 규칙(§9.7)
    ok, counts = sg.prompt(text)                      # ② 프롬프트 게이트 gate_prompt_text + S5 번호 토큰 잔여
    ans = sg.answer(ans, spec.item_schema)            # ③ 입수 정제 sanitize(…, "copilot_answer") — 답의 문자열 필드마다

규칙
  · ① 에서 걸린 항목은 보내지도 다시 묻지도 않는다 — 호출자(L3)가 ``gated:<사유>`` 규칙 커밋(confirm=true).
  · ``GateSpecError``(허용 밖 필드 = 프로그래밍 오류)·② 실패는 ``StageGateError`` — 단계 중지 stop_kind=gate(재시도 없음).
  · 웹 노출(``web_exposed``, B §4.11)이면 ``make_gate_context(web_grounding=True)``(X-111·X-112) + 엄격 규칙 S1~S5.
    ID 글자판 ``ID_CHARS`` 는 P §5 보호 구간(``lm27.privacy.rules.TOKEN_RX``)과 같다(관문 G-B11 — 시험이 대조).
  · 목록형 텍스트 필드는 원소의 줄바꿈을 공백으로 바꾼 뒤 ``"\n"`` 으로 이어 한 문자열로 넘기고 돌아온 값을 다시 나눈다(§9.2).
  · 감사는 정제 명세의 ``AuditSink`` 한 벌(범주별 건수·판만). 결과 봉투에는 ``summary()``(§9.4 — ``drop:``·``remask:``
    접두를 뗀 이름, X-113)를 싣는다.
"""
from __future__ import annotations

import dataclasses
import re
from collections import Counter
from datetime import UTC, datetime

from lm27 import privacy as P

ID_CHARS = r"[A-Za-z0-9_\-]{1,16}"
RX_MAIL_ORG = re.compile(r"\[이메일@(고객사|협력사):" + ID_CHARS + r"\]")
RX_ORG_ID = re.compile(r"\[(고객사|협력사):" + ID_CHARS + r"\]")
RX_PERSON_KEY = re.compile(r"\[사람#[0-9a-f]{6}\]")
RX_AMOUNT = re.compile(r"\[(?:금액|비율)\]")
RX_CUSTOMER = re.compile(r"\[(?:이메일@)?고객사(?::" + ID_CHARS + r")?\]")
RX_WEB_RESIDUE = re.compile(r"\[(?:고객사|협력사):|\[이메일@(?:고객사|협력사):|\[사람#")
LIST_SEP = "\n"
DROP_TEXT = "[삭제]"
AUDIT_SRC = "copilot"
RULES_VERSION = P.RULES_VERSION
POLICIES = ("strict", "block")


class StageGateError(Exception):
    """② 프롬프트 게이트 실패 또는 단계 명세 위반(GateSpecError) — 그 단계는 아무것도 보내지 않고 멈춘다."""

    def __init__(self, counts=None, reason: str = "gate_blocked"):
        super().__init__(reason)
        self.counts = dict(counts or {})
        self.reason = reason


def privacy_spec(spec, text_fields=None) -> P.StageSpec:
    """L4 단계 → 정제 관문의 ``StageSpec``(B §9.2). 시간·식별 필드가 허용 목록에 있으면 StageGateError(gate_spec)."""
    tf = tuple(text_fields if text_fields is not None else (spec.text_fields or ()))
    try:
        return P.StageSpec(name=spec.id, allowed_fields=frozenset(spec.send_fields), text_fields=frozenset(tf),
                           max_item_chars=int(spec.gate_max_chars))
    except P.GateSpecError as e:
        raise StageGateError({"spec": 1}, "gate_spec") from e


def load_keys(paths):
    r"""주 키링(``data\keys\privacy_keyring.json``) — 없으면 None(키 없이 정제: 사람 표지는 ``[사람]``). 만들지 않는다."""
    try:
        return P.load_keyring(paths.data(), None, create=False)
    except P.NoKeyringError:
        return None


def build_sctx(paths, cfg_raw, kr, registry, *, os_names=None):
    """정제 문맥(``build_context``) — 설정·유효 레지스트리·로컬 사전·키."""
    return P.build_context(cfg_raw, registry, P.LocalOnly.load(paths), kr, os_names=os_names)


def text_fields_of(spec, items) -> tuple:
    """단계의 텍스트 필드 — 명시가 없으면 보낼 필드 중 값이 문자열·문자열 목록인 것(B §8.0.1 기본)."""
    if spec.text_fields is not None:
        return tuple(spec.text_fields)
    out = []
    for f in spec.send_fields:
        for it in items:
            v = it.fields.get(f)
            if isinstance(v, str) or (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
                out.append(f)
                break
    return tuple(out)


def _join(v):
    if isinstance(v, list):
        return LIST_SEP.join(str(x).replace("\r", " ").replace("\n", " ") for x in v)
    return v


def _split(orig, v):
    if isinstance(orig, list):
        s = str(v or "")
        return s.split(LIST_SEP) if s else []
    return v


class GateBase:
    """호출 1회의 게이트 문맥(정제 문맥·카나리아). ``for_stage`` 가 단계별 감사·웹 노출을 붙인다."""

    def __init__(self, sctx, cfg_raw=None, kr=None, *, paths=None, pc_id=None, policy: str = "strict",
                 clock_iso=None, environ=None, machine_guid=None, local=None, audit: bool = True):
        self.sctx = sctx
        self.cfg_raw = cfg_raw
        self.kr = kr
        self.paths = paths
        self.pc_id = pc_id
        self.policy = policy if policy in POLICIES else "strict"
        self.clock_iso = clock_iso
        self.environ = environ
        self.machine_guid = machine_guid
        self.local = local
        self.audit = audit and paths is not None
        self._base = {}

    @classmethod
    def open(cls, paths, cfg_raw, *, kr=None, registry=None, pc_id=None, policy: str = "strict", clock_iso=None,
             environ=None, os_names=None) -> GateBase:
        sctx = build_sctx(paths, cfg_raw, kr, registry, os_names=os_names)
        return cls(sctx, cfg_raw, kr, paths=paths, pc_id=pc_id, policy=policy, clock_iso=clock_iso, environ=environ)

    def _gctx(self, web: bool):
        if web not in self._base:
            kw = {}
            if self.environ is not None:
                kw["environ"] = self.environ
                kw["machine_guid"] = self.machine_guid or ""
            elif self.machine_guid is not None:
                kw["machine_guid"] = self.machine_guid
            self._base[web] = P.make_gate_context(self.sctx, self.cfg_raw, self.kr, stage="copilot", audit=None,
                                                  web_grounding=web, local=self.local, paths=self.paths, **kw)
        return self._base[web]

    def _audit(self, stage_id: str):
        if not self.audit:
            return None
        clk = self.clock_iso
        return P.AuditSink.open(None, self.pc_id, "copilot:" + stage_id, AUDIT_SRC, paths=self.paths,
                                clock=clk)

    def for_stage(self, stage_id: str, *, web_exposed: bool) -> StageGate:
        g = self._gctx(bool(web_exposed))
        g = dataclasses.replace(g, audit=self._audit(stage_id), stage="copilot:" + stage_id)
        return StageGate(stage_id, g, web_exposed=bool(web_exposed), policy=self.policy)


def clock_iso_of(clock):
    """브리지 시계 → 감사 시각 함수(UTC 'YYYY-MM-DDTHH:MM:SSZ' — 가상 시계면 결정적)."""
    def now():
        return datetime.fromtimestamp(int(clock.now()), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return now


class StageGate:
    """단계 1개의 게이트. 건수는 ``stats``(결과 봉투 ``gate`` 요약 — 원문·항목 key 없음)."""

    def __init__(self, stage_id: str, gctx, *, web_exposed: bool, policy: str = "strict"):
        self.stage_id = stage_id
        self.gctx = gctx
        self.web_exposed = web_exposed
        self.policy = policy
        self.items_in = 0
        self._seen: set = set()               # 셈한 항목 key — 다시 거르는 항목(수동 반입 재질의)은 items_in 에 한 번만
        self.dropped: Counter = Counter()
        self.remask: Counter = Counter()
        self.web: Counter = Counter()
        self.prompt_blocked = 0
        self.answer_hits: Counter = Counter()
        self.answer_drop = 0

    def carry(self, prev) -> None:
        """수동 전환으로 게이트를 다시 열 때 앞 게이트의 건수를 이어받는다 — 결과 봉투 ``gate`` 요약과 입수 정제 감사가
        호출 전체를 덮게(앞 게이트는 감사를 내보내지 않고 버려진다)."""
        if prev is None or prev is self:
            return
        self.items_in += prev.items_in
        self._seen |= prev._seen
        for name in ("dropped", "remask", "web", "answer_hits"):
            getattr(self, name).update(getattr(prev, name))
        self.prompt_blocked += prev.prompt_blocked
        self.answer_drop += prev.answer_drop

    # ── ① 항목 게이트 + ①' 엄격 규칙 ───────────────────────────────────
    def items(self, spec, work_items, text_fields=None):
        """→ (남은 항목 목록 — fields 는 재가림 값, [(key, 사유)] 제외 목록). 허용 밖 필드면 StageGateError."""
        work_items = list(work_items)
        tf = tuple(text_fields if text_fields is not None else text_fields_of(spec, work_items))
        pspec = privacy_spec(spec, tf)
        by_key = {it.key: it for it in work_items}
        gis = []
        for it in work_items:
            f = {k: (_join(v) if k in tf else v) for k, v in it.fields.items()}
            gis.append(P.GateItem(it.key, f, dict(it.meta or {})))
        try:
            res = P.gate_copilot(gis, pspec, self.gctx)
        except P.GateSpecError as e:
            raise StageGateError({"spec": 1}, "gate_spec") from e
        self.items_in += sum(1 for gi in gis if gi.item_id not in self._seen)
        self._seen.update(gi.item_id for gi in gis)
        for k, v in res.counts.items():
            if k.startswith("drop:"):
                self.dropped[k[5:]] += v
            elif k.startswith("remask:"):
                self.remask[k[7:]] += v
        dropped = list(res.dropped)
        kept = res.kept
        if self.web_exposed:
            kept, wdrop = self._strict_web(spec, kept, tf)
            dropped += wdrop
        out = []
        for gi in kept:
            it = by_key[gi.item_id]
            nf = {k: (_split(it.fields.get(k), v) if k in tf else v) for k, v in gi.fields.items()}
            out.append(dataclasses.replace(it, fields=nf))
        return out, dropped

    def _strict_web(self, spec, gitems, tf):
        """웹 노출 엄격 규칙(B §9.7): S1 번호 축약 · S2 사람 키 평문 · S3 금액+고객사 항목 제외 · S4 필드 빈 값."""
        kept, dropped, c = [], [], Counter()
        for gi in gitems:
            fields = [f for f in tf if f in gi.fields]
            blob = LIST_SEP.join(str(gi.fields[f]) for f in fields)
            if RX_AMOUNT.search(blob) and RX_CUSTOMER.search(blob):
                dropped.append((gi.item_id, "web_combo"))
                c["combo_drop"] += 1
                continue
            nf = dict(gi.fields)
            for f in fields:
                t = str(nf[f])
                t, n1 = RX_MAIL_ORG.subn(lambda m: "[이메일@" + m.group(1) + "]", t)
                t, n2 = RX_ORG_ID.subn(lambda m: "[" + m.group(1) + "]", t)
                t, n3 = RX_PERSON_KEY.subn("[사람]", t)
                nf[f] = t
                c["id_strip"] += n1 + n2
                c["person_plain"] += n3
            for f in spec.web_drop_fields:
                if nf.get(f):
                    c["field_drop:" + f] += 1
                    nf[f] = [] if isinstance(nf[f], list) else ""
            kept.append(P.GateItem(gi.item_id, nf, gi.meta))
        self.web.update(c)
        au = self.gctx.audit
        if au is not None:
            for _iid, why in dropped:
                au.add("dropped", why)
            for k, v in sorted(c.items()):
                if k != "combo_drop" and v:
                    au.add("remask", "web_" + k.replace(":", "_"), v)
            au.flush("gate_copilot", rows_in=len(gitems), rows_out=len(kept))
        return kept, dropped

    # ── ② 프롬프트 게이트 ──────────────────────────────────────────────
    def rid_ok(self, rid: str) -> bool:
        """rid 가 정제 탐지·카나리아에 걸리지 않는가(통화 코드 + 숫자 같은 우연한 모양을 피한다 — ``exchange.new_rid``)."""
        probe = f"[LM27 요청 {rid}] [[END {rid}]]"
        t, hits = P.gate_text(probe, self.gctx)
        return t == probe and not hits and not P.scan(probe, self.gctx.sctx)

    def prompt(self, text: str):
        """전송마다(사다리 재전송 포함). → (통과, {범주: 건수}). 웹 노출이면 번호 토큰 잔여(S5)도 실패."""
        ok, counts = P.gate_prompt_text(text, self.gctx)
        counts = dict(counts)
        if ok and self.web_exposed and RX_WEB_RESIDUE.search(text or ""):
            ok, counts = False, {"web_residue": 1}
        if not ok:
            self.prompt_blocked += 1
        return ok, counts

    # ── ③ 입수 정제 ────────────────────────────────────────────────────
    def text(self, s: str, max_len: int | None = None) -> str:
        """답 글 하나를 정제(원문 캡처·문자열 필드용). 자격증명이면 '[삭제]'."""
        r = P.sanitize(str(s), "copilot_answer", self.gctx.sctx, max_len=max_len)
        if r.drop:
            self.answer_drop += 1
            return DROP_TEXT
        for k, v in r.hits.items():
            self.answer_hits[k] += int(v)
        return r.text

    def answer(self, value, schema=()):
        """검증·정규화를 마친 답(dict·list·str)의 **자유 문자열**을 정제한다(코드·열거 값은 그대로)."""
        return self._walk(value, {f.name: f for f in schema} if schema else None)

    def _walk(self, v, spec_map):
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                f = spec_map.get(k) if spec_map is not None else None
                if spec_map is not None and f is None:
                    out[k] = x                                   # 명세 밖(단계가 입력에서 붙인 값) — 그대로
                elif f is not None and f.kind in ("enum", "code", "int", "bool"):
                    out[k] = x
                elif f is not None and f.kind in ("list", "obj", "nullable_obj") and f.item:
                    out[k] = self._walk(x, {g.name: g for g in f.item})
                else:
                    out[k] = self._walk(x, None if f is None else {})
            return out
        if isinstance(v, list):
            return [self._walk(x, spec_map) for x in v]
        if isinstance(v, str) and v:
            return self.text(v)
        return v

    def summary(self) -> dict:
        """결과 봉투 ``gate``(B §9.4)."""
        out = {"rules_ver": RULES_VERSION, "items_in": self.items_in, "dropped": dict(sorted(self.dropped.items())),
               "remask": dict(sorted(self.remask.items())), "prompt_blocked": self.prompt_blocked,
               "answer_hits": dict(sorted(self.answer_hits.items())), "answer_drop": self.answer_drop}
        web = {"exposed": self.web_exposed, "policy": self.policy}
        fd = {k.split(":", 1)[1]: v for k, v in self.web.items() if k.startswith("field_drop:")}
        for k in ("id_strip", "person_plain", "combo_drop"):
            web[k] = int(self.web.get(k, 0))
        web["field_drop"] = dict(sorted(fd.items()))
        out["web"] = web
        return out

    def flush_answer_audit(self) -> None:
        """입수 정제 건수를 감사 1줄로(범주별 건수만)."""
        au = self.gctx.audit
        if au is None or not (self.answer_hits or self.answer_drop):
            return
        for k, v in sorted(self.answer_hits.items()):
            au.add("masked", k, v)
        if self.answer_drop:
            au.add("dropped", "answer_cred", self.answer_drop)
        au.flush("gate_copilot", rows_in=0, rows_out=0)


def scan_hits(text: str, sctx=None) -> dict:
    """치환 없는 탐지 건수 — 진단(diagnose)·시험용."""
    return {h.cat: h.n for h in P.scan(text or "", sctx)}
