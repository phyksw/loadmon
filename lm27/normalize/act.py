# -*- coding: utf-8 -*-
r"""화행 판정(적재 시) · 수동 태깅 · 코파일럿 답 덮어쓰기(계약 §2.7 · §6.6 · X-090 · X-091 · X-203 · O-12 · CT §6 · §10).

    classify_act(row, ctx=None) -> (act, conf)    act ∈ ACTS(7종), conf ∈ [0, 1] — mail·teams 만, 그 밖 kind 는 ("", 0.0)
    save_tag(paths, msg_key, act)                 data\local_only\tag_feedback.json 에 사람이 붙인 화행(CT §10)
    load_tags(paths) -> {msg_key: act}
    load_ai_acts(paths) -> {msg_key: (act, conf)} data\derived\ai_out\speech_act.json 의 by=ai·manual, conf h·m 답(B §8.2)
    speech_act_items(rows) / write_speech_act_in(paths, rows)   규칙 회색 지대 메시지만 ai_in 항목으로(B §2.5 · §8.2)

우선순위(X-090): **수동 태깅 > 코파일럿 speech_act(by=ai, conf h·m) > 규칙**. 저장 행의 ``act`` 는 늘 ``""`` 이고(계약 §3.1),
판정은 적재 때마다 다시 한다(``lm27.normalize.load`` 가 파생 열 ``act``·``act_conf``·``act_source`` 로 붙인다).

규칙(CT §6 가중 규칙 — 정규화 명세가 생기면 그 재료, 계약 O-1·O-12). 입력은 저장 행의 단서 코드 ``act_cues``(수집 때
원문에서 뽑은 것) ∪ 정제문(``subject_masked``·``body_masked``·``text_masked``)에서 다시 뽑은 단서(``lm27.normalize.cues``)와
구조(방향·대화 종류·멘션·수신 구분·첨부·플래그)다. 점수는 행동별 상수의 최댓값이다:

| 조건 | 판정 · 점수 |
|---|---|
| 메일 ``flags.teams_notice``(팀즈 '놓친 활동' 알림 — X-133) | notice 0.95 |
| ``priv_class = social`` | social 0.90 |
| 메일 ``flags.meeting_response``(회의 수락·거절 발신·수신) | info 0.70 — 회의 응답은 업무 시작·수락 신호가 아니다 |
| 받은 대량 메일(``list_unsub``·``precedence``·``esp``·``body_unsub``·``ad``·광고 의심 띠) | notice 0.85 |
| 단서 없음 + 정제문이 인사·감사 낱말뿐 | social 0.70 |
| **받음**: req | request 0.60 (+0.10 ask 동반 · +0.05 sched · +0.05 @멘션 · +0.05 상급자/PM(``teams.pmWhoKeys``) · −0.10 참조(cc) · −0.10 대량(DL) 수신) |
| 받음: ask + sched(기한 있는 질문 — W §11.3) | request 0.55 |
| 받음: 1:1 방의 ask(질문형 가중 — CT §6) | request 0.45 — question 0.50 과 함께 회색 지대(코파일럿이 가른다) |
| 받음: rep·done | report 0.55(둘 다 0.60) — req 도 있으면 request·report 모두 0.50(보고인지 검토 의뢰인지 회색 지대) |
| ack | ack 0.60(짧은 단독 수락 0.75) |
| ask | question 0.50 |
| fyi·cancel | info 0.55 · 받은 대량 메일·채널 공지 = notice 0.60 |
| **보냄**: rep·done | report 0.60(둘 다 +0.05, 첨부 +0.05) — '확인 부탁드립니다' 같은 맺음말 요청 어미보다 앞선다(B §8.2 예 3) |
| 보냄: req(rep·done 없음) | request 0.55(+0.10 sched) — 보낸 지시(S1o) |
| 보냄: ack(rep·done·req 없음) | ack 0.60(짧은 단독 0.75) |
| 그 밖 | info 0.30 |

동점은 받음 = request > report > ack > question > notice > info, 보냄 = report > request > ack > question > info 순.
낱말 부분 일치(LM24 ``ORDER_HINTS`` — 확인·공유·일정·가능·필요)로 지시를 만들지 않는다(CT §6 · CT-10). 회색 지대 =
``GRAY_LO ≤ conf < GRAY_HI`` 이면서 받은 직접 메시지(1:1·멘션·수신 to) 또는 보낸 메시지 — 그것만 코파일럿 ``speech_act`` 에
묻는다(B §2.3 '정규화 직후(화행 회색 지대만)').

수동 태깅 파일(CT §10): ``{"<msg_key>": {"act": "request", "by": "user", "at": "<UTC>"}}`` — 키·열거·시각만(원문 없음),
``lm27.util.fsx.atomic_write`` 로만 쓴다. 표준 라이브러리 + ``lm27.paths``·``lm27.util``·``lm27.normalize.cues`` 만 쓴다.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from lm27.normalize.cues import ACT_CUES, extract
from lm27.util import fsx

__all__ = [
    "ACTS", "AI_CONF", "AI_STAGE", "CONF_MANUAL", "GRAY_HI", "GRAY_LO", "MSG_KEY_RX", "TAG_FILE",
    "ActContext", "act_context", "classify_act", "is_direct", "is_gray", "load_ai_acts", "load_tags", "message_text",
    "save_tag", "speech_act_items", "write_speech_act_in",
]

ACTS = ("request", "ack", "question", "report", "info", "social", "notice")   # 계약 §6.6 화행 어휘(7종)
TAG_FILE = "tag_feedback.json"                                                 # data\local_only\ (CT §10 · X-091)
AI_STAGE = "speech_act"                                                        # 브리지 단계 id(B §8.2)
AI_BY = ("ai", "manual")                                                       # 코파일럿 답(manual = 수동 붙여넣기 답, B §7.10)
AI_CONF = {"h": 0.90, "m": 0.75}                                               # l 은 참고만 — 덮지 않는다(B §8.2)
CONF_MANUAL = 1.0
GRAY_LO, GRAY_HI = 0.40, 0.55
SRC_VER = "act/1"                                                              # 규칙 판(ai_in src_ver — 내용 키에 안 들어감)
MSG_KEY_RX = re.compile(r"^m[0-9a-f]{24}$")
_W16_RX = re.compile(r"^w[0-9a-f]{16}$")
_COPILOT = frozenset({"mail.copilot", "cal.copilot", "teams.copilot"})
_MASS_FLAGS = ("list_unsub", "precedence", "esp", "body_unsub", "ad")
_TEXT_COLS = ("subject_masked", "body_masked", "text_masked")
_TOKEN_RX = re.compile(r"\[[^\[\]]{1,60}\]")
_PUNCT_RX = re.compile(r"[\s.,!?~^·…:;()\-_/'\"ㅎㅋㅠㅜ]+")
_SOCIAL = frozenset({
    "감사합니다", "감사해요", "감사드립니다", "감사", "고맙습니다", "고마워요", "고마워", "수고하셨습니다", "수고하세요",
    "수고많으셨습니다", "수고", "많으셨습니다", "고생하셨습니다", "고생많으셨습니다", "고생", "좋은", "하루", "되세요",
    "보내세요", "주말", "안녕하세요", "안녕히", "계세요", "가세요", "반갑습니다", "축하드립니다", "축하합니다", "축하해요",
    "생일", "명절", "새해", "복", "많이", "받으세요", "즐거운", "행복한", "편안한", "저녁", "점심", "맛있게", "드세요",
    "thanks", "thank", "you", "thx", "ty", "hello", "hi", "good", "morning", "have", "a", "nice", "day", "weekend",
    "congrats", "congratulations", "님", "모두", "다들", "오늘도", "이번", "주도"})
_SOCIAL_MAX = 60
_SHORT = 15
_TAG_LOCK = threading.Lock()


@dataclass(frozen=True)
class ActContext:
    """규칙 판정 문맥. ``pm_keys`` = 상급자·PM 가명 키(``teams.pmWhoKeys`` — w + 16hex, 실명 없음)."""
    pm_keys: frozenset = frozenset()


def act_context(cfg=None) -> ActContext:
    """설정(``Cfg`` 또는 사전) → ``ActContext``. 없으면 빈 문맥."""
    if cfg is None:
        return ActContext()
    if isinstance(cfg, ActContext):
        return cfg
    if isinstance(cfg, Mapping):
        keys = cfg.get("teams.pmWhoKeys", ())
    else:
        keys = cfg["teams.pmWhoKeys"]
    return ActContext(pm_keys=frozenset(k for k in (keys or ()) if isinstance(k, str) and _W16_RX.match(k)))


# ───────────────────────────── 행 읽기 도우미 ─────────────────────────────
def _flags(row: Mapping) -> Mapping:
    f = row.get("flags")
    return f if isinstance(f, Mapping) else {}


def _dir(row: Mapping) -> str:
    d = row.get("direction")
    if d in ("out", "sent"):
        return "out"
    if d in ("in", "received"):
        return "in"
    return "unknown"


def message_text(row: Mapping) -> str:
    """판정에 쓰는 정제문(제목·본문·증인 요약을 줄바꿈으로 이은 것). 원문이 아니다."""
    return "\n".join(v for v in (row.get(c) for c in _TEXT_COLS) if isinstance(v, str) and v)


def _cues_of(row: Mapping, text: str) -> set[str]:
    stored = row.get("act_cues")
    out = {c for c in stored if c in ACT_CUES} if isinstance(stored, (list, tuple)) else set()
    out.update(extract(text))
    return out


def _bare(text: str) -> str:
    """정제 토큰·구두점을 뺀 글(짧은 단독 수락·인사 판정용)."""
    return _PUNCT_RX.sub(" ", _TOKEN_RX.sub(" ", unicodedata.normalize("NFKC", text).lower())).strip()


def _social_only(text: str) -> bool:
    b = _bare(text)
    if not b or len(b) > _SOCIAL_MAX:
        return False
    words = b.split()
    return all(w in _SOCIAL for w in words)


def is_direct(row: Mapping) -> bool:
    """나에게 직접 온 메시지인가(1:1 방 · @멘션 · 메일 수신 to 이고 참조 아님) — W §2.2 `direct` 와 같은 뜻."""
    fl = _flags(row)
    if row.get("kind") == "teams":
        return row.get("chat_type") == "1:1" or bool(fl.get("mentions_me"))
    return row.get("rcv") == "to" and not fl.get("cc")


def _mass(row: Mapping) -> bool:
    fl = _flags(row)
    return any(fl.get(k) for k in _MASS_FLAGS) or row.get("ad_band") == "suspect"


def _bulk(row: Mapping) -> bool:
    return row.get("kind") == "mail" and (row.get("rcv") == "bulk" or bool(_flags(row).get("bulk")))


def _pm(row: Mapping, ctx: ActContext) -> bool:
    if not ctx.pm_keys:
        return False
    who = row.get("sender_key") if row.get("kind") == "mail" else row.get("author_key")
    return isinstance(who, str) and who in ctx.pm_keys


def _pick(sc: dict, order: tuple) -> tuple[str, float]:
    best = max(sc.values())
    for a in order:
        if sc.get(a, 0.0) == best:
            return a, round(best, 2)
    return "info", round(best, 2)                  # pragma: no cover — order 가 모든 키를 덮는다


_IN_ORDER = ("request", "report", "ack", "question", "notice", "info")
_OUT_ORDER = ("report", "request", "ack", "question", "info")


# ───────────────────────────── 규칙 판정 ─────────────────────────────
def classify_act(row: Mapping, ctx=None) -> tuple[str, float]:
    """저장 행 하나 → (화행, 확신 0~1). mail·teams 만 판정하고 그 밖 kind 는 ("", 0.0)."""
    kind = row.get("kind")
    if kind not in ("mail", "teams"):
        return "", 0.0
    ctx = act_context(ctx)
    fl = _flags(row)
    if kind == "mail" and fl.get("teams_notice"):
        return "notice", 0.95
    if row.get("priv_class") == "social":
        return "social", 0.90
    d = _dir(row)
    if kind == "mail" and fl.get("meeting_response"):
        return "info", 0.70
    if d != "out" and kind == "mail" and _mass(row):
        return "notice", 0.85
    text = message_text(row)
    cues = _cues_of(row, text)
    if not cues and text and _social_only(text):
        return "social", 0.70
    req, rep, done, ack, ask, sched, cancel, fyi = (c in cues for c in ACT_CUES)
    short = bool(text) and len(_bare(text)) <= _SHORT
    sc = {"info": 0.30}
    if fyi or cancel:
        sc["info"] = 0.55
    if ask:
        sc["question"] = 0.50
    if ack:
        sc["ack"] = 0.75 if short else 0.60
    if d == "out":
        if rep or done:
            sc["report"] = 0.60 + (0.05 if rep and done else 0.0) + \
                (0.05 if (row.get("attach_keys") or row.get("file_keys") or fl.get("has_file")) else 0.0)
            if ack:
                sc["ack"] = 0.30
        if req:
            sc["request"] = (0.55 + (0.10 if sched else 0.0)) if not (rep or done) else 0.25
            if ack and not (rep or done):
                sc["ack"] = 0.50
        return _pick(sc, _OUT_ORDER)
    r = 0.0
    if req and (rep or done):
        r = 0.50                                     # '결과 첨부드리니 확인 부탁드립니다' — 보고인지 검토 의뢰인지 회색 지대
    elif req:
        r = 0.60 + (0.10 if ask else 0.0) + (0.05 if sched else 0.0)
    elif ask and sched:
        r = 0.55                                     # 기한 있는 질문 → request(W §11.3)
    elif ask and kind == "teams" and row.get("chat_type") == "1:1":
        r = 0.45                                     # 1:1 질문형 가중(CT §6) — 회색 지대
    if r:
        if fl.get("mentions_me"):
            r += 0.05
        if _pm(row, ctx):
            r += 0.05
        if kind == "mail" and (row.get("rcv") == "cc" or fl.get("cc")):
            r -= 0.10
        if _bulk(row):
            r -= 0.10
        sc["request"] = r
    if rep or done:
        sc["report"] = 0.50 if req else (0.60 if (rep and done) else 0.55)
    if _bulk(row) or (kind == "teams" and row.get("chat_type") == "channel" and not fl.get("mentions_me") and fyi):
        if not (r >= 0.50 or rep or done):
            sc["notice"] = 0.60
    return _pick(sc, _IN_ORDER)


def is_gray(act: str, conf: float) -> bool:
    """규칙 점수가 회색 지대인가(코파일럿 speech_act 대상 후보)."""
    return act in ACTS and act not in ("notice", "social") and isinstance(conf, (int, float)) and \
        GRAY_LO <= float(conf) < GRAY_HI


# ───────────────────────────── 수동 태깅(CT §10 · X-091) ─────────────────────────────
def _utc_now(now=None) -> str:
    if isinstance(now, str):
        return now
    t = now if isinstance(now, datetime) else datetime.now(UTC)
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_tags(obj) -> dict:
    out = {}
    if not isinstance(obj, Mapping):
        return out
    for k, v in obj.items():
        if not (isinstance(k, str) and MSG_KEY_RX.match(k) and isinstance(v, Mapping) and v.get("act") in ACTS):
            continue
        e = {"act": v["act"], "by": "user"}
        at = v.get("at")
        if isinstance(at, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", at):
            e["at"] = at
        out[k] = e
    return out


def save_tag(paths, msg_key: str, act: str | None, *, now=None) -> dict:
    """사람이 붙인 화행 하나를 저장한다(``act`` 가 None·"" 이면 그 태그를 지운다). 저장 뒤의 그 항목(지웠으면 {})을
    돌려준다. ``msg_key`` = 메시지 키(m + 24hex), ``act`` ∈ ACTS — 아니면 ValueError. 원문은 받지도 쓰지도 않는다."""
    if not isinstance(msg_key, str) or not MSG_KEY_RX.match(msg_key):
        raise ValueError("save_tag: msg_key 형식(m + 24hex)이 아닙니다")
    if act not in (None, "") and act not in ACTS:
        raise ValueError("save_tag: 화행 코드가 아닙니다")
    path = paths.local_only_file(TAG_FILE)
    with _TAG_LOCK:
        cur = _valid_tags(fsx.read_json(path, {}, want=dict))
        if act:
            cur[msg_key] = {"act": act, "by": "user", "at": _utc_now(now)}
        else:
            cur.pop(msg_key, None)
        fsx.atomic_write(path, fsx.canon_bytes(dict(sorted(cur.items()))) + b"\n")
    return dict(cur.get(msg_key, {}))


def load_tags(paths) -> dict[str, str]:
    """``tag_feedback.json`` → {msg_key: act}(형식이 맞는 항목만). 파일이 없으면 {}."""
    obj = fsx.read_json(paths.local_only_file(TAG_FILE), {}, want=dict)
    return {k: v["act"] for k, v in sorted(_valid_tags(obj).items())}


# ───────────────────────────── 코파일럿 speech_act(B §8.2) ─────────────────────────────
def _item_key(msg_key: str) -> str:
    return "msg:" + msg_key


def load_ai_acts(paths) -> dict[str, tuple[str, float]]:
    """``ai_out\\speech_act.json`` → {msg_key: (act, conf)} — 덮어쓸 자격(by ∈ ai·manual, conf ∈ h·m)이 있는 답만."""
    obj = fsx.read_json(paths.ai_out(AI_STAGE), None, want=dict)
    items = obj.get("items") if isinstance(obj, Mapping) else None
    out: dict[str, tuple[str, float]] = {}
    if not isinstance(items, Mapping):
        return out
    for k in sorted(items):
        v = items[k]
        mk = k[4:] if isinstance(k, str) and k.startswith("msg:") else k
        if not (isinstance(mk, str) and MSG_KEY_RX.match(mk) and isinstance(v, Mapping) and v.get("by") in AI_BY):
            continue
        ans = v.get("ans")
        if not isinstance(ans, Mapping) or ans.get("act") not in ACTS or ans.get("conf") not in AI_CONF:
            continue
        out[mk] = (ans["act"], AI_CONF[ans["conf"]])
    return out


def _conv(row: Mapping) -> str:
    if row.get("kind") == "teams":
        ck = row.get("chat_key") or row.get("msg_key") or ""
        if row.get("chat_type") == "channel" and row.get("thread_key"):
            return f"{ck}:{row['thread_key']}"
        return str(ck)
    return str(row.get("thread_key") or row.get("msg_key") or "")


def _chat_field(row: Mapping) -> str:
    if row.get("kind") == "teams":
        ct = row.get("chat_type")
        return ct if ct in ("1:1", "group", "channel", "meeting") else "group"
    rcv = row.get("rcv")
    return rcv if rcv in ("to", "cc", "bulk") else "to"


def speech_act_items(rows: Iterable[Mapping], ctx=None) -> list[dict]:
    """규칙 화행이 회색 지대인 메시지 → ``ai_in\\speech_act.jsonl`` 항목(B §2.5 · §8.2). ``rows`` 는 ``load_evidence``
    출력(``act``·``act_conf``·``act_source`` 가 붙은 행) 또는 저장 행. 코파일럿 증인·사적·광고·수동·AI 판정 행은 뺀다.
    ``prev`` = 같은 대화의 직전 메시지 화행. 항목 키 = ``"msg:" + msg_key``(정렬)."""
    msgs = []
    for r in rows:
        if not isinstance(r, Mapping) or r.get("kind") not in ("mail", "teams"):
            continue
        mk = r.get("msg_key")
        if not (isinstance(mk, str) and MSG_KEY_RX.match(mk)) or r.get("src") in _COPILOT:
            continue
        msgs.append(r)
    msgs.sort(key=lambda r: (_conv(r), str(r.get("ts_utc") or ""), str(r.get("id") or "")))
    out, prev_conv, prev = [], None, "-"
    for r in msgs:
        conv = _conv(r)
        if conv != prev_conv:
            prev_conv, prev = conv, "-"
        act, conf = r.get("act"), r.get("act_conf")
        if act not in ACTS or not isinstance(conf, (int, float)):
            act, conf = classify_act(r, ctx)
        src = r.get("act_source") or "rule"
        d = _dir(r)
        ok = (src == "rule" and r.get("priv_class") not in ("private", "social") and not _flags(r).get("ad")
              and is_gray(act, conf) and (d == "out" or is_direct(r)))
        if ok:
            text = (r.get("subject_masked") if r.get("kind") == "mail" else r.get("body_masked")) or ""
            meta = {"priv_class": r.get("priv_class") or "work", "rules_ver": r.get("rules_ver") or ""}
            if r.get("ad_band"):
                meta["ad_band"] = r["ad_band"]
            out.append({"key": _item_key(r["msg_key"]), "group": "",
                        "fields": {"ch": r["kind"], "dir": "out" if d == "out" else "in", "chat": _chat_field(r),
                                   "prev": prev, "text": str(text)[:120]},
                        "rule": {"act": act, "score": round(float(conf), 2)}, "src_ver": SRC_VER, "meta": meta})
        prev = act
    out.sort(key=lambda it: it["key"])
    return out


def write_speech_act_in(paths, rows: Iterable[Mapping], ctx=None) -> int:
    """회색 지대 항목을 ``data\\derived\\ai_in\\speech_act.jsonl`` 에 원자 기록(한 줄 = 항목, 정규 JSON). 쓴 항목 수."""
    items = speech_act_items(rows, ctx)
    data = b"".join(fsx.canon_bytes(it) + b"\n" for it in items)
    fsx.atomic_write(paths.ai_in(AI_STAGE), data)
    return len(items)
