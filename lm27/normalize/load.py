# -*- coding: utf-8 -*-
r"""증거 적재 — 번들 로더 → 재정제(G2) → 병합 → 파생 열(계약 §2.7 · §3.1 · X-060 · X-090 · X-133 · P §10.5 · §12.4 · §12.5).

    load_evidence(paths, cfg, d0, d1) -> list[dict]      분석(시간 코어·분류·보고서)이 읽는 증거 행 — 원문 없음
    load_report() -> dict                                 마지막 적재의 건수 보고(조용한 손실 금지)
    apply_acts(rows, paths, cfg) -> dict                  화행 파생 열만 다시(코파일럿 답·수동 태그가 바뀐 뒤)

흐름(모두 메모리 사본 위에서 — 세그먼트·로컬 원장은 바꾸지 않는다):

1. **번들 로더**: kind 8종을 ``lm27.bundle.loader.iter_records(paths, kind, d0, d1, cfg=cfg, resanitize=훅)`` 로 읽는다
   (``data\pcs`` 를 읽는 유일 모듈 — L-08. 기간 경계는 근무 시간대, 같은 id 는 observed_at 최대, 소급 가림 읽기 오버레이).
2. **훅**(행마다): (a) 소급 가림 오버레이에 걸린 행은 ``redact_row`` 로 한 번 더 — 정제문 열과 함께 ``act_cues`` 도 비운다
   (계약 C11 — 단서도 내용에서 나온 것). (b) **G2 재정제**: ``rules_ver`` 가 지금 규칙(``RULES_VERSION``)보다 낮은 행만
   ``resanitize_row`` 로 텍스트 열을 지금 규칙으로 다시 가린다(P §10.5 — 가림은 늘기만, ``id`` 그대로). 정제 문맥은 필요할
   때 한 번만 만든다: 키링(``create=False``) + 유효 레지스트리(``lm27.hier.registry.load_effective`` — 네트워크 없음,
   ``persist=False``) + 로컬 사전 → ``build_context``(수집 때와 같은 사전·본인 이름). 키링이 없으면 새로 생긴 사람 태그는
   ``[사람]`` 평문 토큰으로 바꾼다(P §9.4 키 없음 규칙).
3. **병합**: ``lm27.normalize.merge.merge_messages(rows, off_min=time.tzOffsetMin)`` — msg_key·교차 경로 병합, date-only 흡수,
   ``*.copilot`` 제외(C §7).
4. **방 성향 재계산**(P §12.4 '적재 시점 — 전체 중복 제거본으로'): teams 방마다 ``RoomStat(n, priv_score_base ≥ 2 건,
   ≤ −2 건)`` → ``room_prior`` 가 private 인 방, 그리고 사용자 지정 사적 방(``local_only\private_chats.json``)의 행은
   ``priv_class=private`` 로 바꾸고 정제문·단서를 비운다(사용자 지정 방은 전부, 성향 방은 ``priv_score_base > −4`` 인 행만 —
   강한 업무 근거 행은 남긴다). ``priv_why`` 에 ``room_private``.
5. **파생 열**(저장하지 않는다 — 적재 때마다 결정적으로 다시 만든다):
   - ``subject_tokens`` = ``lm27.privacy.tokens_of(subject_masked · body_masked · msg_masked · text_masked 중 첫 비어 있지 않은
     값)`` — kind mail·cal·teams·pc_git·manual(X-060, C §3.2).
   - ``act``·``act_conf``·``act_source`` — mail·teams(그 밖 kind 는 저장값 ``""`` 그대로): 규칙(``classify_act``) → 코파일럿
     ``speech_act`` 답(by=ai·manual, conf h·m) → 수동 태깅(``tag_feedback.json``) 순으로 덮는다(X-090: 수동 최우선).
     ``alias_keys`` 의 어느 키로 저장된 태그·답이든 찾는다.
   - ``presence_of = "teams"`` — 팀즈 '놓친 활동' 알림 메일(``flags.teams_notice``)은 팀즈 수신 존재 표식이다(X-133 · D-15 —
     시간은 상한으로만, 해석은 시간 코어). ``act = notice``.
   - ``provenance``·``alias_keys`` — 병합이 붙인다(메시지 kind).

감사: 실행 1회에 ``load_resanitize`` 이벤트 1줄(P §15.2 — 건수·범주 코드만: 재정제·가림 범주·병합·오버레이·방 가림).
결정성: 같은 번들·설정·로컬 파일이면 같은 결과(행 순서 (ts_utc, kind, id, pc_id)). 파일 쓰기는 감사 1줄뿐이다.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime

from lm27.bundle import loader
from lm27.normalize.act import act_context, classify_act, load_ai_acts, load_tags
from lm27.normalize.merge import COPILOT_SRCS, merge_messages
from lm27.privacy import (
    RULES_VERSION,
    SCHEMAS,
    AuditSink,
    LocalOnly,
    NoKeyringError,
    RoomStat,
    build_context,
    load_keyring,
    redact_row,
    resanitize_row,
    room_prior,
    tokens_of,
)

__all__ = ["DERIVED_COLUMNS", "EVIDENCE_KINDS", "TOKEN_KINDS", "apply_acts", "load_evidence", "load_report"]

EVIDENCE_KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual")
TOKEN_KINDS = ("mail", "cal", "teams", "pc_git", "manual")
TOKEN_COLS = ("subject_masked", "body_masked", "msg_masked", "text_masked")
DERIVED_COLUMNS = ("subject_tokens", "act", "act_conf", "act_source", "presence_of", "provenance", "alias_keys")
ROOM_STRONG_WORK = -4                        # P §12.4 — priv_score_base 가 이 값 이하인 행은 성향 방이어도 남긴다
_PERSON_TAG = re.compile(r"\[사람#[0-9a-f]{6}\]")
_LOCK = threading.Lock()
_LAST: dict = {}


def _ver(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


_CUR = _ver(RULES_VERSION)


# ───────────────────────────── G2 재정제 훅 ─────────────────────────────
def _plain_new(old: dict, new: dict, kind: str) -> None:
    """키 없음 모드: 재정제가 새로 만든 ``[사람#…]`` 만 ``[사람]`` 으로(이미 있던 태그는 그대로 — 행 사이 일관성)."""
    for col in SCHEMAS[kind].text_fields:
        o, n = old.get(col), new.get(col)
        if isinstance(n, str):
            keep = set(_PERSON_TAG.findall(o)) if isinstance(o, str) else set()
            new[col] = _PERSON_TAG.sub(lambda m, k=keep: m.group(0) if m.group(0) in k else "[사람]", n)
        elif isinstance(n, list):
            ol = o if isinstance(o, list) else []
            out = []
            for i, x in enumerate(n):
                keep = set(_PERSON_TAG.findall(ol[i])) if i < len(ol) and isinstance(ol[i], str) else set()
                out.append(_PERSON_TAG.sub(lambda m, k=keep: m.group(0) if m.group(0) in k else "[사람]", x)
                           if isinstance(x, str) else x)
            new[col] = out


def _keyless(sctx) -> bool:
    """주입된 정제 문맥이 키 없음(0 바이트 키·사람 하위 키 없음 — SanitizeContext 기본값)인가."""
    return sctx is not None and getattr(sctx, "person_subkey", None) is None and \
        not any(getattr(sctx, "key", b"") or b"")


class _Hook:
    """``iter_records`` 의 ``resanitize`` 훅 — 오버레이 단서 비우기(C11) + G2 재정제(P §10.5)."""

    def __init__(self, paths, cfg, *, sctx=None, audit=None):
        self.paths, self.cfg, self.audit = paths, cfg, audit
        self.ov = loader.load_overlay(paths)
        self._sctx, self._built, self.plain = sctx, sctx is not None, _keyless(sctx)
        self.resanitized = 0
        self.overlay = 0
        self.hits: dict = defaultdict(int)

    def ctx(self):
        if not self._built:
            try:
                kr = load_keyring(self.paths.data(), self.audit, create=False)
            except NoKeyringError:
                kr = None
            from lm27.hier.registry import load_effective     # 프로그램 폴더 모드의 유효 레지스트리(X-247 — 지연 import)
            reg, _st = load_effective(self.paths, self.cfg, kr=kr, persist=False)
            self._sctx = build_context(self.cfg, reg, LocalOnly.load(self.paths), kr, audit=self.audit)
            self.plain = kr is None
            self._built = True
        return self._sctx

    def __call__(self, kind: str, row: dict) -> dict:
        if self.ov and (self.ov.get("chat") or self.ov.get("msg")) and loader.overlay_hit(row, self.ov):
            row = redact_row(kind, row)
            self.overlay += 1
        if kind in SCHEMAS and _ver(row.get("rules_ver", "0.0.0")) < _CUR:
            new, hits = resanitize_row(kind, row, self.ctx())
            if self.plain:
                _plain_new(row, new, kind)
            for k, v in hits.items():
                self.hits[k] += int(v)
            self.resanitized += 1
            row = new
        return row


# ───────────────────────────── 방 성향(P §12.4) ─────────────────────────────
def _room_privacy(rows: list[dict], private_chats) -> int:
    rooms: dict = defaultdict(list)
    for r in rows:
        ck = r.get("chat_key")
        if r.get("kind") == "teams" and isinstance(ck, str) and ck and r.get("src") not in COPILOT_SRCS:
            rooms[ck].append(r)
    user_rooms = set(private_chats or ())
    changed = 0
    for ck in sorted(rooms):
        lst = rooms[ck]
        user = ck in user_rooms
        if not user:
            bases = [r.get("priv_score_base") for r in lst]
            st = RoomStat(len(lst), sum(1 for b in bases if isinstance(b, int) and b >= 2),
                          sum(1 for b in bases if isinstance(b, int) and b <= -2))
            if room_prior(st) != "private":
                continue
        for r in lst:
            if r.get("priv_class") in ("private", "social"):
                continue
            b = r.get("priv_score_base")
            if not user and isinstance(b, int) and not isinstance(b, bool) and b <= ROOM_STRONG_WORK:
                continue
            r.update(redact_row("teams", r))
            r["priv_class"] = "private"
            fl = dict(r.get("flags") or {})
            fl["private"] = True
            r["flags"] = dict(sorted(fl.items()))
            why = {x for x in (r.get("priv_why") or ()) if isinstance(x, str)} | {"room_private"}
            r["priv_why"] = sorted(why)[:8]
            changed += 1
    return changed


# ───────────────────────────── 파생 열 ─────────────────────────────
def _keys(r: Mapping) -> list[str]:
    ks = r.get("alias_keys")
    if isinstance(ks, list) and ks:
        return sorted(k for k in ks if isinstance(k, str))
    mk = r.get("msg_key")
    return [mk] if isinstance(mk, str) and mk else []


def _tokens(rows: list[dict]) -> None:
    for r in rows:
        if r.get("kind") in TOKEN_KINDS:
            txt = next((v for v in (r.get(c) for c in TOKEN_COLS) if isinstance(v, str) and v), "")
            r["subject_tokens"] = tokens_of(txt)


def _acts(rows: list[dict], actx, tags: Mapping, ai: Mapping) -> dict:
    n = {"act_rule": 0, "act_ai": 0, "act_manual": 0, "presence": 0}
    for r in rows:
        kind = r.get("kind")
        if kind not in ("mail", "teams"):
            continue
        act, conf = classify_act(r, actx)
        source = "rule"
        keys = _keys(r)
        hit = next((ai[k] for k in keys if k in ai), None)
        if hit is not None:
            act, conf, source = hit[0], hit[1], "ai"
        tag = next((tags[k] for k in keys if k in tags), None)
        if tag is not None:
            act, conf, source = tag, 1.0, "manual"
        r["act"], r["act_conf"], r["act_source"] = act, conf, source
        n["act_" + source] += 1
        fl = r.get("flags")
        if kind == "mail" and isinstance(fl, Mapping) and fl.get("teams_notice"):
            r["presence_of"] = "teams"
            n["presence"] += 1
    return n


def apply_acts(rows: list[dict], paths, cfg) -> dict:
    """적재된 행(``load_evidence`` 출력)의 화행 파생 열(``act``·``act_conf``·``act_source``·``presence_of``)을 지금의 수동
    태깅·코파일럿 답으로 다시 붙인다(제자리 갱신) — 브리지 ``speech_act`` 단계 뒤나 화면에서 태그를 붙인 뒤 번들을 다시
    읽지 않고 고칠 때. 원천별 건수를 돌려준다."""
    return _acts(rows, act_context(cfg), load_tags(paths), load_ai_acts(paths))


def _as_date(d):
    if d is None or (isinstance(d, date) and not isinstance(d, datetime)):
        return d
    if isinstance(d, datetime):
        return d.date()
    return date.fromisoformat(str(d)[:10])


# ───────────────────────────── 공개 함수 ─────────────────────────────
def load_evidence(paths, cfg, d0, d1, *, kinds: Iterable[str] | None = None, sctx=None, audit=None) -> list[dict]:
    """[d0, d1](근무 시간대 로컬 날짜, 양끝 포함 · None = 열림)의 증거 행 → 정제·병합·파생 열이 붙은 사본 목록.

    ``kinds`` = 읽을 kind(기본 8종 전부). 시험·호출자 주입: ``sctx`` = G2 정제 문맥(``SanitizeContext`` — 주면 키링·레지스트리를
    읽지 않는다), ``audit`` = ``AuditSink``(주면 계수만 더하고 기록은 호출자 몫) · ``False``(감사 끔) · None(1줄 기록)."""
    t0 = time.monotonic()
    a, b = _as_date(d0), _as_date(d1)
    want = tuple(kinds) if kinds is not None else EVIDENCE_KINDS
    bad = [k for k in want if k not in EVIDENCE_KINDS]
    if bad:
        raise ValueError("load_evidence: 증거 kind 가 아닙니다")
    own_sink = audit is None
    sink = AuditSink.open(paths.data(), None, "load", "load", paths=paths) if own_sink else (audit or None)
    hook = _Hook(paths, cfg, sctx=sctx, audit=sink)
    rows: list[dict] = []
    per_kind = {}
    for kind in want:
        got = list(loader.iter_records(paths, kind, a, b, cfg=cfg, resanitize=hook))
        rep = loader.load_report()
        per_kind[kind] = {"records": len(got), "segments_read": rep.get("segments_read", 0),
                          "duplicates": rep.get("duplicates", 0), "skipped": len(rep.get("skipped") or ()),
                          "missing": len(rep.get("missing") or ())}
        rows.extend(got)
    mst: dict = {}
    out = merge_messages(rows, off_min=int(cfg["time.tzOffsetMin"]), stats=mst)
    room = _room_privacy(out, LocalOnly.load(paths).private_chats)
    _tokens(out)
    n = apply_acts(out, paths, cfg)
    report = {"d0": a.isoformat() if a else None, "d1": b.isoformat() if b else None, "kinds": per_kind,
              "rows_in": len(rows), "rows_out": len(out), "merge": dict(sorted(mst.items())),
              "resanitized": hook.resanitized, "masked": dict(sorted(hook.hits.items())), "overlay_rows": hook.overlay,
              "room_private": room, **n}
    if sink is not None:
        for k, v in sorted(hook.hits.items()):
            sink.add("masked", k, v)
        for name, v in (("resanitized", hook.resanitized), ("overlay", hook.overlay), ("room_private", room)):
            sink.add("load", name, v)
        for name in ("exact_merged", "fuzzy_merged", "date_absorbed", "copilot_dups"):
            sink.add("merge", name.replace("_merged", ""), int(mst.get(name, 0)))
        if own_sink:
            sink.flush("load_resanitize", rows_in=len(rows), rows_out=len(out),
                       dur_ms=int((time.monotonic() - t0) * 1000))
    with _LOCK:
        _LAST.clear()
        _LAST.update(report)
    return out


def load_report() -> dict:
    """마지막 ``load_evidence`` 의 건수 보고(kind 별 세그먼트·레코드·건너뜀·없는 파일, 병합·재정제·가림·화행 원천)."""
    with _LOCK:
        out = dict(_LAST)
    if "kinds" in out:
        out["kinds"] = {k: dict(v) for k, v in out["kinds"].items()}
    return out
