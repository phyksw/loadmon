# -*- coding: utf-8 -*-
r"""L2 교환(B §6) — rid 봉투 조립 · 프롬프트 게이트 · 봉투 추출·잘림 복구 · 항목 검증 · 상태 분류 10종 · 재시도 사다리.

    ar = ask(spec, batch, ac)            # 질의 1건(사다리 포함 최대 3회 전송 + 형식·에코 재전송 1회)
    status, info = classify(spec, res, meta, ctx, ingest)    # 전송 결과 1건 → B §6.6 상태(수동 반입도 같은 함수)

규칙
  · 전송마다 새 rid(``R`` + 5자, 글자판 ``23456789ABCDEFGHJKMNPQRSTVWXYZ``) — 늦은 답·다른 채팅·지난 실행의 답을 기계적으로
    거른다. 프롬프트에 서약 문자열은 마지막 줄 지시에 딱 1번.
  · 머리말은 질의마다 **전부** 싣는다(혼자서 완결). 예시 형식은 ``<…>`` 자리표시자라 그 자체로 유효한 JSON 이 아니다.
  · L2 는 같은 묶음을 다시 보내는 것까지만 한다(형식·에코 1회, 빈 답·일시 오류 사다리 1·2단, 거절 화법 변형 1회).
    묶음을 바꾸는 일(반분·재질의·연기)은 L3(``runner``).
  · 사다리(LM24 ``run_roundtrip`` 일반화): 0단 = 채팅 정책 · 등급 모델 · 설정 대기 / 1단 = 새 채팅 · 대기 절반(하한
    120·30초 — ``settings.rung_timeouts``) / 2단 = 새 채팅 · ``bridge.modelFallback``. 각 단 대기는 min(…, 질의 마감 − 60초),
    질의 마감까지 ``bridge.minAskSec`` 미만이면 다음 단을 건너뛴다(``rung_skipped``). soft 서킷이면 2단을 쓰지 않는다.
  · 원문 비저장(B9): 프롬프트·답은 메모리에만. 저널은 길이·sha256·번호·상태만, 원문 캡처(``bridge.rawCapture``, 기본
    꺼짐)만 게이트 통과본을 TTL 로(``fsio.write_text_ttl`` — 이 파일과 manual.py 만 부른다, G-B7).
"""
from __future__ import annotations

import hashlib
import secrets
from collections import Counter
from dataclasses import dataclass, field

from lm27.bridge import fsio, jsonx
from lm27.bridge.budget import ASK_MARGIN_S
from lm27.bridge.clock import stamp
from lm27.bridge.messages import FATAL_PHASES
from lm27.bridge.stages import base as B
from lm27.bridge.transport import SendRequest

RID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
RID_LEN = 5
STATUSES = ("ok", "partial", "truncated", "echo", "format", "empty", "service_error", "timeout", "refusal",
            "transport_fatal")
WHOLE_FAIL = ("echo", "format", "empty", "timeout")
ERROR_REPLY_MAX = 500            # 정형 오류 문구: 몸통 500자 미만이고(LM24 is_error_reply)
ERROR_HEAD = 300                 # 앞 300자에 표식
# 정형 오류 문구(LM24 tools/copilot_auto.ERROR_REPLY_MARKS 유지 — 비교는 소문자)
ERROR_MARKS = ("응답할 수 없습니다", "응답 할 수 없습니다", "문제가 발생했", "무언가 잘못", "죄송합니다. 지금은",
               "sorry, i can't respond", "something went wrong", "can't respond right now")
REFUSAL_MARKS = ("도와드릴 수 없", "답변드릴 수 없", "요청을 처리할 수 없", "i can't help with", "i cannot help with",
                 "i'm not able to help")
UNAVAILABLE_MARKS = ("조회 도구가 없", "연결된 도구가 없", "데이터 조회 도구", "no connected tool", "액세스할 수 없",
                     "접근할 수 없", "권한이 없", "검색할 수 없", "work content isn't available")
NOLIC_MARKS = ("업무 데이터에 액세스할 수 없", "업무 데이터에 접근할 수 없", "work content isn't available",
               "work data isn't available")
# 답이 'Work IQ'(업무 데이터 접근 토글 — 2026-08 개편)를 말하면 업무 모드가 꺼진 것이지 계정 등급(R-NOLIC)이 아니다(H13)
WORKIQ_MARKS = ("work iq", "업무 iq")
CONTENT_PHASES = ("replied", "no_reply", "empty_reply", "stub", "manual")


def new_rid(used: set, ok=None) -> str:
    """전송마다 새 rid(한 실행에서 쓴 rid 와 겹치면 다시 뽑는다, B §6.1). ``ok(rid)`` 가 거짓이면 다시 뽑는다 — 정제 탐지가
    rid 를 개인정보로 오인하는 모양(예: 통화 코드 + 숫자 ``RMB85F`` → 금액)이면 프롬프트 게이트가 단계를 멈추므로
    (fail-closed), 게이트가 깨끗하다고 보는 rid 만 쓴다(``gate.StageGate.rid_ok``)."""
    while True:
        r = "R" + "".join(secrets.choice(RID_ALPHABET) for _ in range(RID_LEN))
        if r in used or (ok is not None and not ok(r)):
            continue
        used.add(r)
        return r


# ───────────────────────── 조립(B §6.2·§6.3) ─────────────────────────
@dataclass
class AsmMeta:
    """분류에 필요한 조립 정보(수동 반입은 목록 파일에서 되살린다)."""
    rid: str
    item_ids: list
    id_to_key: dict
    items: dict = field(default_factory=dict)        # 번호 → WorkItem(검증·정규화 재료)


@dataclass
class Assembled(AsmMeta):
    text: str = ""
    line_spans: dict = field(default_factory=dict)   # 항목 번호 → text 안 (시작, 끝)
    header_span: tuple = (0, 0)
    in_chars: int = 0


def footer_lines(spec, rid: str, n: int, *, strict_format: bool = False) -> list:
    lines = [B.ANSWER_HEAD_PROMPT]
    for i, t in enumerate(B.FOOTER_TEMPLATE):
        if i == 1 and spec.kind == "lookup":
            lines.append(B.LOOKUP_COUNT_PROMPT.format(rid=rid))
        else:
            lines.append(t.format(rid=rid, n=n, unknown_rule=spec.unknown_rule()))
    if spec.kind != "lookup":
        lines.append(B.NO_WEB_PROMPT)
    lines.append(B.FORMAT_LINE_TEMPLATE.format(format_line=spec.format_line()))
    if strict_format:
        lines.append(B.STRICT_FORMAT_PROMPT)
    lines.append(B.PLEDGE_TEMPLATE.format(rid=rid))
    return lines


def footer_len(spec, n: int) -> int:
    """답 형식 꼬리 길이(패킹 예산 계산용 — 자리 값은 가장 긴 모양)."""
    return len("\n".join(footer_lines(spec, "R" + "Z" * RID_LEN, max(1, n), strict_format=True))) + 1


def assemble(spec, batch, ctx, rid: str, *, compact: bool = False, context_block: str = "", note: str = "",
             strict_format: bool = False, rephrase: bool = False) -> Assembled:
    """프롬프트 한 벌(B §6.2 골격 글자 그대로) + 줄 지도."""
    n = len(batch)
    head = [spec.title_line(rid, n, batch, ctx)]
    alt = spec.rephrase() if rephrase else None
    body = alt if alt else spec.header(ctx, compact)
    if body:
        head.append(body)
    if note:
        head.append(B.NOTE_PROMPT.format(notes=note))
    text = "\n".join(head)
    header_span = (0, len(text))
    parts = [text]
    if context_block:
        parts.append(context_block)
    spans, ids, id_to_key, items = {}, [], {}, {}
    cols = spec.columns()
    if cols:
        parts.append(cols)
    pos = len("\n".join(parts))
    for i, it in enumerate(batch, 1):
        ids.append(i)
        id_to_key[i] = it.key
        items[i] = it
        if cols:
            line = spec.item_line(it, i)
            start = pos + 1
            parts.append(line)
            pos = start + len(line)
            spans[i] = (start, pos)
    parts.extend(footer_lines(spec, rid, n, strict_format=strict_format))
    text = "\n".join(parts)
    return Assembled(rid=rid, item_ids=ids, id_to_key=id_to_key, items=items, text=text, line_spans=spans,
                     header_span=header_span, in_chars=len(text))


# ───────────────────────── 분류(B §6.6) ─────────────────────────
def _has(text: str, marks) -> bool:
    low = (text or "").lower()
    return any(m.lower() in low for m in marks)


def _lic(text: str) -> str:
    """조회 불가 답의 까닭: ``workiq_off``(업무 모드 토글이 꺼짐 — 능력 기록 안 함) · ``nolic``(계정 단위) · ``noconn``(단계별)."""
    if _has(text, WORKIQ_MARKS):
        return "workiq_off"
    return "nolic" if _has(text, NOLIC_MARKS) else "noconn"


def _validate_items(spec, obj, meta: AsmMeta, ctx, ingest, info) -> None:
    """봉투 항목 검증(B §6.5) → info 의 answers·invalid·missing·dup·extra·extra_fields·dropped."""
    items = obj.get("items") if isinstance(obj.get("items"), list) else []
    want = set(meta.item_ids)
    ok, invalid, dup, extra = {}, {}, 0, 0
    counts: Counter = info["dropped"]
    for raw in items:
        if not isinstance(raw, dict):
            extra += 1
            continue
        try:
            iid = int(str(raw.get("id")).strip())
        except (TypeError, ValueError):
            extra += 1
            continue
        if iid not in want:
            extra += 1
            continue
        if iid in ok or iid in invalid:
            dup += 1
            continue
        ans, err, c = B.check_item(spec, raw, ctx)
        counts.update({k: v for k, v in c.items() if k in ("forbidden_field", "extra_fields", "trunc", "list_items")})
        if err:
            invalid[iid] = err
            continue
        it = meta.items.get(iid)
        err = spec.validate(ans, it, ctx) if it is not None else ""
        if err:
            invalid[iid] = err
            continue
        ans = spec.normalize(ans, it, ctx) if it is not None else ans
        ok[iid] = ingest(ans) if ingest is not None else ans
    info.update(answers=ok, invalid=invalid, dup=dup, extra=extra,
                missing=[i for i in meta.item_ids if i not in ok and i not in invalid])
    info["extra_fields"] = int(counts.get("extra_fields", 0))


def _validate_rows(spec, obj, meta: AsmMeta, ctx, ingest, info) -> None:
    """조회형: 행마다 검사(시각 필드 허용) → 항목 1(구간)의 답 {rows, more, n}."""
    rows_in = obj.get("items") if isinstance(obj.get("items"), list) else []
    it = meta.items.get(meta.item_ids[0]) if meta.item_ids else None
    rows = []
    counts: Counter = info["dropped"]
    for raw in rows_in:
        ans, err, c = B.check_item(spec, raw, ctx, allow_time=True)
        counts.update({k: v for k, v in c.items() if k in ("forbidden_field", "extra_fields", "trunc")})
        if err:
            counts["bad_row"] += 1
            continue
        row, codes = spec.normalize_row(ans, it, ctx)
        for code in codes or ():
            counts[str(code)] += 1
        if row is not None:
            rows.append(row)
    try:
        n_decl = int(obj.get("n"))
    except (TypeError, ValueError):
        n_decl = -1
    ans = {"rows": rows, "more": obj.get("more") is True, "n": n_decl}
    ans = spec.normalize(ans, it, ctx) if it is not None else ans
    if ingest is not None:
        ans = ingest(ans)
    first = meta.item_ids[0] if meta.item_ids else 1
    info.update(answers={first: ans}, invalid={}, dup=0, extra=0, missing=[], n_decl=n_decl, n_items=len(rows_in))
    info["extra_fields"] = int(counts.get("extra_fields", 0))


def classify(spec, res, meta: AsmMeta, ctx=None, ingest=None) -> tuple[str, dict]:
    """전송 결과 1건 → (상태, info) — B §6.6 순서 그대로. 수동 반입(B §10.4)도 이 함수."""
    info: dict = {"reason": "", "side": "", "answers": {}, "invalid": {}, "missing": list(meta.item_ids), "dup": 0,
                  "extra": 0, "extra_fields": 0, "dropped": Counter(), "how": "", "cut": False, "pledge": False}
    phase = res.phase
    body = res.body or ""
    if phase == "manual_pending":
        return "manual_pending", info
    if phase in FATAL_PHASES:
        info["reason"] = phase
        return "transport_fatal", info
    if phase == "input_overflow":
        info["side"] = "input"
        return "truncated", info
    if phase == "inject_mismatch":
        info["reason"] = "inject_mismatch"
        return "format", info
    if phase == "empty_reply":
        return "empty", info
    if phase not in CONTENT_PHASES:
        info["reason"] = phase or "unknown_phase"                   # busy_before_send·send_failed·cdp_error·모르는 단계
        return "service_error", info
    if phase == "no_reply" and not body.strip():
        return "timeout", info
    s = body.strip()
    if s and len(s) < ERROR_REPLY_MAX and _has(s[:ERROR_HEAD], ERROR_MARKS):
        info["reason"] = "error_reply"
        return "service_error", info
    x = jsonx.extract(body, meta.rid)
    info.update(how=x.how, cut=x.cut, pledge=x.pledge)
    if x.kind == "env":
        if spec.kind == "lookup":
            _validate_rows(spec, x.obj, meta, ctx, ingest, info)
            if x.how == "salvaged" or x.cut or phase == "no_reply":
                info["side"] = "output"
                return "truncated", info
            if info["n_decl"] != info["n_items"]:
                return "partial", info
            return "ok", info
        _validate_items(spec, x.obj, meta, ctx, ingest, info)
        if x.how == "salvaged" or x.cut or phase == "no_reply":
            info["side"] = "output"
            return "truncated", info
        if not info["answers"]:
            info["reason"] = "no_valid_items"
            return "format", info
        if info["missing"] or info["invalid"]:
            return "partial", info
        return "ok", info
    if x.kind in ("echo", "stale"):
        info["reason"] = "stale" if x.kind == "stale" else "example"
        return "echo", info
    if spec.kind == "lookup" and (_has(body, UNAVAILABLE_MARKS) or _has(body, WORKIQ_MARKS)):
        info["reason"] = "unavailable"
        info["lic"] = _lic(body)
        return "refusal", info
    if _has(body, REFUSAL_MARKS):
        info["reason"] = "policy"
        return "refusal", info
    if phase == "no_reply":
        return "timeout", info
    if not s:
        return "empty", info
    info["reason"] = "no_envelope"
    return "format", info


# ───────────────────────── 채팅 정책(B §6.9) ─────────────────────────
class ChatState:
    """단계 하나의 채팅 상태. continue = 첫 질의 · 직전 질의가 ok·partial 아님 · 같은 채팅 질의 수 ≥ chatTurns ·
    chatTurns 0 이면 새 채팅. fresh_each = 질의마다."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.turns = 0
        self.last = None
        self.first = True
        self.force_fresh = False

    def need_fresh(self, spec) -> bool:
        if spec.chat_policy == "fresh_each" or self.first or self.force_fresh:
            return True
        if self.last not in ("ok", "partial"):
            return True
        ct = int(self.cfg.chat_turns)
        return ct <= 0 or self.turns >= ct

    def after_send(self, status: str, *, fresh: bool) -> int:
        self.first = False
        self.force_fresh = False
        self.turns = 1 if fresh else self.turns + 1
        self.last = status
        return self.turns


# ───────────────────────── ask(B §6.8) ─────────────────────────
@dataclass
class AskResult:
    status: str
    reason: str = ""
    answers: dict = field(default_factory=dict)      # 프롬프트 번호 → 정규화된 답(커밋 후보)
    missing: list = field(default_factory=list)
    invalid: dict = field(default_factory=dict)      # 번호 → 사유 코드
    dup: int = 0
    extra: int = 0
    extra_fields: int = 0
    rids: list = field(default_factory=list)
    sends: int = 0
    rung: int = 0
    rungs: Counter = field(default_factory=Counter)
    rung_skipped: int = 0
    done_by: str = ""
    pick: str = ""
    sec: float = 0.0
    transport_phase: str = ""
    model_used: str = ""
    work_mode: str = ""
    gate: dict = field(default_factory=dict)
    in_chars: int = 0
    reply_len: int = 0
    side: str = ""
    injected_chars: int = 0
    dropped: Counter = field(default_factory=Counter)
    lic: str = ""
    resent_fmt: bool = False
    rephrased: bool = False
    statuses: list = field(default_factory=list)     # 전송마다의 상태(계측)
    meta: object = None                              # 마지막 조립 정보(수동 목록·재질의)


@dataclass
class AskCtx:
    """L3 가 L2 에 주는 문맥(질의 1건)."""
    cfg: object
    clock: object
    transport: object
    gate: object                                     # StageGate(② 프롬프트·③ 입수)
    journal: object = None
    tracer: object = None
    chat: ChatState | None = None
    used_rids: set = field(default_factory=set)
    stage_deadline: float = float("inf")
    circuit_soft: bool = False
    stage_ctx: object = None
    context_block: str = ""
    compact: bool = False
    note: str = ""
    depth: int = 0
    seq: int = 0
    raw_capture: bool = False
    rawcap_dir: object = None
    web_exposed: bool = True
    run_id: str = ""


def model_for(spec, rung: int, cfg) -> str:
    if rung >= 2:
        return cfg.model_fallback
    return cfg.model_for(spec.model_class)


def _timeouts(rung: int, deadline: float, ac: AskCtx) -> tuple[float, float]:
    reply, first = ac.cfg.rung_timeouts(rung)
    cap = max(0.0, deadline - ac.clock.mono() - ASK_MARGIN_S)
    return min(reply, cap) if cap > 0 else reply, min(first, cap) if cap > 0 else first


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def ingest_schema(spec) -> tuple:
    """입수 정제 ③ 의 스키마 — 조회형(과 단건 행 봉투)의 답 ``{rows, n, more}`` 는 ``rows`` 의 각 행을 행 스키마의 글 필드로
    정제한다(W1 통합 창 — WP-25 CR: 행 글이 ai_out·저널에 원문으로 닿던 것. 단계 쪽 우회와 겹쳐도 정제는 멱등)."""
    sch = tuple(spec.item_schema)
    if (spec.kind == "lookup" or getattr(spec, "row_envelope", False)) and not any(f.name == "rows" for f in sch):
        sch += (B.F("rows", "list", required=False, item=tuple(spec.item_schema)),)
    return sch


def ask(spec, batch, ac: AskCtx) -> AskResult:
    """질의 1건(B §6.8). 프롬프트 게이트 실패는 ``StageGateError``(호출자 L3 가 단계 중지)."""
    from lm27.bridge.gate import StageGateError
    clock, cfg = ac.clock, ac.cfg
    t0 = clock.mono()
    deadline = min(t0 + cfg.roundtrip_max_sec, ac.stage_deadline)
    chat = ac.chat or ChatState(cfg)
    rung, resent_fmt, rephrased, strict = 0, False, False, False
    fresh = chat.need_fresh(spec)
    ar = AskResult(status="")
    sch = ingest_schema(spec)
    ingest = (lambda a: ac.gate.answer(a, sch)) if ac.gate is not None else None
    first_send = True
    rid_ok = getattr(ac.gate, "rid_ok", None) if ac.gate is not None else None
    while True:
        rid = new_rid(ac.used_rids, rid_ok)
        asm = assemble(spec, batch, ac.stage_ctx, rid, compact=ac.compact, context_block=ac.context_block,
                       note=ac.note, strict_format=strict, rephrase=rephrased)
        ar.meta = asm
        if ac.gate is not None:
            ok, counts = ac.gate.prompt(asm.text)
            if not ok:
                if ac.journal is not None:
                    ac.journal.write("gate_blocked", seq=ac.seq, rid=rid, counts=dict(counts))
                raise StageGateError(counts)
            ar.gate = {"ok": True, "counts": dict(counts)}
        rto, fto = _timeouts(rung, deadline, ac)
        req = SendRequest(rid, asm.text, bool(fresh or rung > 0), model_for(spec, rung, cfg), rto, fto, deadline,
                          spec.id, bool(spec.want_work_mode), item_keys=tuple(it.key for it in batch))
        if ac.journal is not None:
            ac.journal.write("req", seq=ac.seq, rid=rid, rung=rung, fresh=req.fresh, depth=ac.depth, n=len(batch),
                             items=[{"n": i, "key": it.key, "ck": it.ck} for i, it in enumerate(batch, 1)],
                             in_chars=asm.in_chars, prompt_ver=spec.prompt_ver, prompt_sha256=_sha(asm.text),
                             gate_prompt=ar.gate or None, model_wanted=req.model)
        s0 = clock.mono()
        res = ac.transport.roundtrip(req)
        sec = round(clock.mono() - s0, 1)
        ar.sends += 1
        ar.rids.append(rid)
        ar.rungs[str(rung)] += 1
        ar.rung = rung
        if res.phase == "manual_pending":
            if ac.journal is not None:
                ac.journal.write("exported", seq=ac.seq, rid=rid, n=len(batch), in_chars=asm.in_chars)
            ar.status, ar.transport_phase, ar.pick = "manual_pending", res.phase, "manual"
            ar.in_chars = asm.in_chars
            ar.missing = list(asm.item_ids)
            return ar
        status, info = classify(spec, res, asm, ac.stage_ctx, ingest)
        turn = chat.after_send(status, fresh=req.fresh)
        ar.statuses.append(status)
        if ac.journal is not None:
            ac.journal.write("resp", seq=ac.seq, rid=rid, rung=rung, transport=getattr(ac.transport, "kind", ""),
                             phase=res.phase, status=status, reason=info.get("reason") or "", done_by=res.done_by,
                             pick=res.pick, sec=sec, reply_len=len(res.body or ""), ok=len(info["answers"]),
                             missing=list(info["missing"]), invalid={str(k): v for k, v in info["invalid"].items()},
                             dup=info["dup"], extra=info["extra"], extra_fields=info["extra_fields"], how=info["how"],
                             model_used=res.model_used, work_mode=res.work_mode)
        if ac.tracer is not None:
            ac.tracer.send(req, res, stage=spec.id, rung=rung, status=status, sec=sec, chat_turn=turn,
                           web_exposed=ac.web_exposed, kind="send" if first_send else "resend")
        first_send = False
        if ac.raw_capture and ac.rawcap_dir is not None and ac.gate is not None:
            _rawcap(ac, spec, rid, asm.text, res.body or "")
        ar.status, ar.reason = status, info.get("reason") or ""
        ar.answers, ar.missing, ar.invalid = info["answers"], list(info["missing"]), dict(info["invalid"])
        ar.dup, ar.extra, ar.extra_fields = info["dup"], info["extra"], info["extra_fields"]
        ar.dropped.update(info["dropped"])
        ar.side, ar.lic = info.get("side") or "", info.get("lic") or ""
        ar.done_by, ar.pick, ar.transport_phase = res.done_by, res.pick, res.phase
        ar.model_used, ar.work_mode = res.model_used, res.work_mode
        ar.in_chars, ar.reply_len, ar.injected_chars = asm.in_chars, len(res.body or ""), res.injected_chars
        ar.sec = round(clock.mono() - t0, 1)
        left = deadline - clock.mono()
        if status in ("ok", "partial", "truncated", "timeout", "transport_fatal"):
            return ar
        if status == "refusal":
            if not rephrased and spec.rephrase():
                rephrased, fresh, ar.rephrased = True, True, True
                continue
            return ar
        if status in ("echo", "format"):
            if not resent_fmt and left >= cfg.min_ask_sec:
                resent_fmt, fresh, ar.resent_fmt = True, True, True
                strict = status == "format"
                continue
            return ar
        if status in ("empty", "service_error"):
            max_rung = 1 if ac.circuit_soft else 2
            if rung < max_rung and left >= cfg.min_ask_sec:
                rung += 1
                continue
            if rung < max_rung:
                ar.rung_skipped += 1
            return ar
        return ar


def _rawcap(ac: AskCtx, spec, rid: str, prompt: str, body: str) -> None:
    """원문 캡처(``bridge.rawCapture`` — 진단용, 기본 꺼짐): ② 통과 프롬프트 + ③ 입수 정제한 답, TTL 보존(B §9.5)."""
    clean = ac.gate.text(body) if body else ""
    name = f"{stamp(ac.clock)}_{spec.id}_{rid}.txt"
    try:
        fsio.write_text_ttl(fsio.child(ac.rawcap_dir, name), prompt + "\n\n---\n\n" + clean,
                            ttl_days=ac.cfg.raw_capture_ttl_days, clock=ac.clock)
    except OSError:
        pass
