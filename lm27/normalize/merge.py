# -*- coding: utf-8 -*-
r"""메시지 병합(읽기 시 파생 — 계약 §2.7 · C §7 · CM §7 · CT §5 · X-131 · X-148 · T-11).

    merge_messages(rows, *, off_min=None, stats=None) -> list[dict]

같은 메시지·일정이 여러 경로(COM·색인·반입·OWA·UIA·웹)와 여러 PC 로 들어와도 **한 번만** 남긴다. 세그먼트는 불변이므로
병합은 읽기 사본에서만 한다(원 행은 바꾸지 않는다). 입력 순서와 무관하게 같은 결과를 낸다(정렬 키 명시 — T-02).

1. **같은 키**: mail·cal·teams 행 중 ``*.copilot`` 이 아닌 것을 ``(kind, msg_key)`` 로 묶는다(PC 간·경로 간 합집합 — C §7.3).
2. **교차 경로 보조 병합**(같은 메시지가 경로마다 다른 키로 들어온 경우 — C §7.2 퍼지 키 · X-148): 두 묶음의
   ``(경로 ID, pc_id)`` 집합이 겹치지 않을 때만(한 PC·한 경로 안의 다른 키는 다른 메시지다) 아래가 모두 맞으면 합친다.
   - mail: 같은 ``box`` · 시각 차 ≤ 120초(분 단위 ±2분) · 정제 제목이 같다(둘 다 비었으면 같은 ``thread_key`` 필수) ·
     ``thread_key``·``sender_key`` 는 둘 다 있으면 같아야 하고 · 상대 키 집합은 둘 다 있으면 겹쳐야 한다.
   - cal: 시작·끝 차 ≤ 60초 · 정제 제목이 같다(둘 다 비었으면 같은 반복 시리즈 ``thread_key`` 필수).
   - teams: 시각 차 ≤ 120초 · 작성자(``author_key``)가 둘 다 있으면 같고 · 정제 본문이 10자 이상이며 같거나 한쪽이
     다른 쪽의 앞부분(20자 이상) — UIA 합성 방 키와 웹 방 키가 달라도 같은 메시지는 1회만(CT §15 #6).
   정밀도가 exact·minute 인 묶음만 보조 병합한다(date·summary 는 3의 흡수 규칙). 후보 쌍은 (시각 차, 키) 순으로 본다.
3. **date-only 흡수**(C §7.3): 같은 (날짜, 방향, 대화)에 exact·minute 사본이 있으면 date 정밀도 메시지는 버린다(존재
   증거 역할 끝 — mail 대화 = ``thread_key``, teams 대화 = ``chat_key``(채널은 + 답글 루트)). 날짜는 date 행 = 그 행의
   수집 오프셋, 정밀 행 = ``off_min``(사람 근무 시간대, 없으면 그 행의 오프셋).
4. ``*.copilot`` 증인 행은 메시지 행과 **병합하지 않는다**(X-046 · B Q23③). 같은 ``(경로 ID, msg_key)`` 증인끼리만 하나로
   (observed_at 최대, 동률 id 사전순).

필드 단위 최선 값(C §7.1 — 신뢰 순위 COM > 색인 > 반입 > OWA(minute) > OWA(date) > Copilot, 팀즈는 웹 > UIA — X-148
'웹 chat_key 우선'):

- 기준 행 = 신뢰 순위(경로 순위 → 정밀도 → id) 첫 행. ``id``·``msg_key``·``kind``·``src``·``pc_id``·``kid``·``rules_ver``·
  ``san`` 과 아래에 없는 열은 기준 행 것.
- 시각 묶음(``ts_utc``·``ts_local_offset``·``ts_precision``·``ts_end``·``flags.utc_suspect``) = 정밀도 최선 행(exact > minute >
  date > summary > unknown, 동률 경로 순위).
- 비어 있지 않은 첫 값(신뢰 순위): 대화·방 키, 방 종류, 발신자 키·라벨, 수신 수, 정제문 열, 장소 분류, 바쁨 등.
  ``rcv``·``direction`` 은 ``unknown`` 이 아닌 첫 값, ``abs_hint`` 는 ``none`` 이 아닌 첫 값.
- 짝 열은 같은 행에서: (``attach_keys``·``attach_names_masked``·``attach_exts``) · (``file_keys``·``file_names_masked``) ·
  (``n_participants``·``flags.n_part_est``) · (``author_key``·``flags.author_inherited``).
- 합집합: ``counterpart_keys``(≤20, 넘으면 ``flags.cap_hit``) · ``act_cues`` · ``priv_why``(≤8) · ``ad_why``(≤10). 최댓값:
  ``confidence``·``observed_at``·``refw_depth``·``priv_score``·``priv_score_base``·``ad_score``·``flags.sensitivity``. 논리합:
  나머지 bool 플래그·``is_reply``·``replied``·``i_sent_in_conv``.
- **공사 판정은 가장 엄격한 쪽**: 한 행이라도 private·social 이면 병합 행도 그 등급이고 텍스트 열·``act_cues`` 를 비운다
  (``lm27.privacy.records.redact_fields`` — C11). 광고 의심 띠(suspect)도 한 행이라도 있으면 suspect.
- 파생 열: ``provenance`` = 묶인 행 [{id, src, pc_id, ts_utc, ts_precision}](신뢰 순위) · ``alias_keys`` = 묶인 msg_key 전부
  (정렬 — 수동 태깅·코파일럿 답이 어느 키로 저장됐든 찾게).

``stats`` 에 사전을 주면 건수를 채운다: rows_in · rows_out · exact_merged · fuzzy_merged · date_absorbed · copilot_dups.
표준 라이브러리 + ``lm27.privacy``(정제 열 단일원) 만 쓴다. 파일을 읽거나 쓰지 않는다.
"""
from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

from lm27.privacy import redact_fields

__all__ = ["COPILOT_SRCS", "FUZZY_SEC", "MSG_KINDS", "PREC_RANK", "SRC_RANK", "merge_messages", "src_rank"]

MSG_KINDS = ("mail", "cal", "teams")
COPILOT_SRCS = frozenset({"mail.copilot", "cal.copilot", "teams.copilot"})
SRC_RANK = {                         # 낮을수록 신뢰(C §7.1 · CM §7 · X-148)
    "mail.com": 0, "mail.index": 1, "mail.import": 2, "mail.owa": 3, "mail.copilot": 9,
    "cal.com": 0, "cal.index": 1, "cal.import": 2, "cal.owa": 3, "cal.copilot": 9,
    "teams.web": 0, "teams.uia": 1, "teams.copilot": 9,
}
PREC_RANK = {"exact": 0, "minute": 1, "date": 2, "summary": 3, "unknown": 4}
EXACT = ("exact", "minute")
FUZZY_SEC = {"mail": 120, "cal": 60, "teams": 120}
TEAMS_BODY_MIN = 10                  # 보조 병합에 쓰는 팀즈 본문 최소 길이(짧은 '넵' 끼리 합치지 않게)
TEAMS_PREFIX_MIN = 20                # 한쪽이 다른 쪽의 앞부분일 때 인정하는 최소 길이
CAP = {"counterpart_keys": 20, "priv_why": 8, "ad_why": 10}
ACT_CUES = ("req", "rep", "done", "ack", "ask", "sched", "cancel", "fyi")
PRIV_ORDER = {"private": 4, "social": 3, "media": 2, "unknown": 1, "work": 0}
_TIME_COLS = ("ts_utc", "ts_local_offset", "ts_precision", "ts_end")
_FIRST = ("thread_key", "chat_key", "chat_type", "sender_key", "sender_label", "n_to", "n_cc", "importance",
          "focused_other", "busy", "location_class", "box", "folder_role", "doc_key", "app_id", "ad_partial",
          "subject_masked", "body_masked", "chat_title_masked", "text_masked", "categories_masked")
_PAIRS = (("attach_keys", ("attach_keys", "attach_names_masked", "attach_exts")),
          ("file_keys", ("file_keys", "file_names_masked")))
_INT_FLAGS = ("response", "meeting_status")
_COUPLED_FLAGS = frozenset({"utc_suspect", "n_part_est", "author_inherited", "sensitivity", "response",
                            "meeting_status"})


# ───────────────────────────── 작은 도구 ─────────────────────────────
def src_rank(row: Mapping) -> int:
    return SRC_RANK.get(str(row.get("src") or ""), 5)


def _prec(row: Mapping) -> int:
    return PREC_RANK.get(str(row.get("ts_precision") or ""), 5)


def _trust_key(row: Mapping) -> tuple:
    return (src_rank(row), _prec(row), str(row.get("id") or ""), str(row.get("pc_id") or ""))


def _time_key(row: Mapping) -> tuple:
    return (_prec(row), src_rank(row), str(row.get("id") or ""), str(row.get("pc_id") or ""))


def _epoch(ts) -> float | None:
    if not isinstance(ts, str) or len(ts) < 16:
        return None
    try:
        dt = datetime.strptime(ts[:19] if len(ts) >= 19 else ts[:16], "%Y-%m-%dT%H:%M:%S" if len(ts) >= 19
                               else "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC).timestamp()


def _off_min(row: Mapping) -> int | None:
    s = row.get("ts_local_offset")
    if not isinstance(s, str) or len(s) != 6 or s[0] not in "+-" or s[3] != ":":
        return None
    try:
        v = int(s[1:3]) * 60 + int(s[4:6])
    except ValueError:
        return None
    return -v if s[0] == "-" else v


def _local_date(row: Mapping, off_min: int | None):
    t = _epoch(row.get("ts_utc"))
    if t is None:
        return None
    off = off_min if off_min is not None else (_off_min(row) or 0)
    return (datetime.fromtimestamp(t, UTC) + timedelta(minutes=off)).date()


def _norm(s) -> str:
    if not isinstance(s, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def _flags(row: Mapping) -> Mapping:
    f = row.get("flags")
    return f if isinstance(f, Mapping) else {}


def _strs(v) -> list[str]:
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, (list, tuple)) else []


def _nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (str, list, tuple, dict)):
        return len(v) > 0
    return True


# ───────────────────────────── 묶음 ─────────────────────────────
class _Cluster:
    __slots__ = ("cid", "members", "srcpc")

    def __init__(self, cid: str, members: list):
        self.cid = cid
        self.members = sorted(members, key=_trust_key)
        self.srcpc = {(str(m.get("src") or ""), str(m.get("pc_id") or "")) for m in members}

    def first(self, col):
        for m in self.members:
            v = m.get(col)
            if _nonempty(v):
                return v
        return None

    def time_row(self) -> Mapping:
        return min(self.members, key=_time_key)

    def ts(self) -> float | None:
        return _epoch(self.time_row().get("ts_utc"))

    def exact(self) -> bool:
        return self.time_row().get("ts_precision") in EXACT


def _subject(c: _Cluster, kind: str) -> str:
    col = "body_masked" if kind == "teams" else "subject_masked"
    return _norm(c.first(col))


def _mail_ok(a: _Cluster, b: _Cluster) -> bool:
    if (a.first("box") or "") != (b.first("box") or ""):
        return False
    sa, sb = _subject(a, "mail"), _subject(b, "mail")
    ta, tb = a.first("thread_key"), b.first("thread_key")
    if sa != sb:
        return False
    if not sa and not (ta and ta == tb):
        return False
    if ta and tb and ta != tb:
        return False
    xa, xb = a.first("sender_key"), b.first("sender_key")
    if xa and xb and xa != xb:
        return False
    ca = {k for m in a.members for k in _strs(m.get("counterpart_keys"))}
    cb = {k for m in b.members for k in _strs(m.get("counterpart_keys"))}
    return not (ca and cb and not (ca & cb))


def _cal_ok(a: _Cluster, b: _Cluster) -> bool:
    ea, eb = _epoch(a.time_row().get("ts_end")), _epoch(b.time_row().get("ts_end"))
    if ea is None or eb is None or abs(ea - eb) > FUZZY_SEC["cal"]:
        return False
    sa, sb = _subject(a, "cal"), _subject(b, "cal")
    if sa != sb:
        return False
    if not sa:
        ta, tb = a.first("thread_key"), b.first("thread_key")
        return bool(ta and ta == tb)
    return True


def _teams_ok(a: _Cluster, b: _Cluster) -> bool:
    xa, xb = a.first("author_key"), b.first("author_key")
    if xa and xb and xa != xb:
        return False
    if not xa or not xb:
        da, db = a.first("direction"), b.first("direction")
        if da and db and "unknown" not in (da, db) and da != db:
            return False
    sa, sb = _subject(a, "teams"), _subject(b, "teams")
    if len(sa) < TEAMS_BODY_MIN or len(sb) < TEAMS_BODY_MIN:
        return False
    if sa == sb:
        return True
    short, long_ = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(short) >= TEAMS_PREFIX_MIN and long_.startswith(short)


_OK = {"mail": _mail_ok, "cal": _cal_ok, "teams": _teams_ok}


def _bucket(c: _Cluster, kind: str):
    """후보 칸 — 같은 칸 안에서만 쌍을 본다(teams = 본문 앞 10자, mail = (box, 제목 또는 대화 키), cal = 제목 또는 시리즈)."""
    s = _subject(c, kind)
    if kind == "teams":
        return s[:TEAMS_BODY_MIN] if len(s) >= TEAMS_BODY_MIN else None
    tk = c.first("thread_key")
    if not s and not tk:
        return None
    key = s if s else ("", tk)
    return (c.first("box") or "", key) if kind == "mail" else key


def _fuzzy(kind: str, clusters: list[_Cluster]) -> tuple[list[_Cluster], int]:
    """교차 경로 보조 병합(순서 무관 — 후보 쌍을 (시각 차, cid) 로 정렬해 탐욕 합치기, (경로, PC) 겹치면 거절)."""
    lim = FUZZY_SEC[kind]
    buckets: dict = defaultdict(list)
    for c in clusters:
        if not c.exact() or c.ts() is None:
            continue
        b = _bucket(c, kind)
        if b is not None:
            buckets[b].append(c)
    cands = []
    for lst in buckets.values():
        lst.sort(key=lambda c: (c.ts(), c.cid))
        for i, a in enumerate(lst):
            ta = a.ts()
            for b in lst[i + 1:]:
                dt = b.ts() - ta
                if dt > lim:
                    break
                if a.srcpc & b.srcpc:
                    continue
                if _OK[kind](a, b):
                    cands.append((dt, min(a.cid, b.cid), max(a.cid, b.cid)))
    if not cands:
        return clusters, 0
    cands.sort()
    parent = {c.cid: c.cid for c in clusters}
    sets = {c.cid: set(c.srcpc) for c in clusters}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    merged = 0
    for _dt, x, y in cands:
        rx, ry = find(x), find(y)
        if rx == ry or sets[rx] & sets[ry]:
            continue
        root, child = (rx, ry) if rx < ry else (ry, rx)
        parent[child] = root
        sets[root] |= sets.pop(child)
        merged += 1
    groups: dict = defaultdict(list)
    for c in clusters:
        groups[find(c.cid)].extend(c.members)
    return [_Cluster(cid, ms) for cid, ms in sorted(groups.items())], merged


# ───────────────────────────── 병합 행 ─────────────────────────────
def _prov(m: Mapping) -> dict:
    return {"id": m.get("id"), "src": m.get("src"), "pc_id": m.get("pc_id"), "ts_utc": m.get("ts_utc"),
            "ts_precision": m.get("ts_precision")}


def _merge_cluster(c: _Cluster) -> dict:
    ms = c.members
    base = ms[0]
    out = dict(base)
    out["provenance"] = [_prov(m) for m in ms]
    out["alias_keys"] = sorted({m["msg_key"] for m in ms if isinstance(m.get("msg_key"), str)})
    if len(ms) == 1:
        return out
    kind = base.get("kind")
    tm = c.time_row()
    for col in _TIME_COLS:
        if col in tm or col in out:
            out[col] = tm.get(col)
    for col in _FIRST:
        v = c.first(col)
        if v is not None:
            out[col] = v
    for d_col in ("rcv", "direction"):
        vals = [m.get(d_col) for m in ms if m.get(d_col) not in (None, "", "unknown")]
        if vals:
            out[d_col] = vals[0]
    hints = [m.get("abs_hint") for m in ms if m.get("abs_hint") not in (None, "", "none")]
    if hints:
        out["abs_hint"] = hints[0]
    for lead, cols in _PAIRS:
        src = next((m for m in ms if _strs(m.get(lead))), None)
        if src is not None:
            for col in cols:
                out[col] = src.get(col)
    flags: dict = {}
    for m in ms:
        for k, v in _flags(m).items():
            if k not in _COUPLED_FLAGS and v is True:
                flags[k] = True
    tfl = _flags(tm)
    if tfl.get("utc_suspect"):
        flags["utc_suspect"] = True
    np_src = next((m for m in ms if isinstance(m.get("n_participants"), int)
                   and not isinstance(m.get("n_participants"), bool)), None)
    if np_src is not None:
        out["n_participants"] = np_src["n_participants"]
        if _flags(np_src).get("n_part_est"):
            flags["n_part_est"] = True
    au_src = next((m for m in ms if _nonempty(m.get("author_key"))), None)
    if au_src is not None:
        out["author_key"] = au_src["author_key"]
        if _flags(au_src).get("author_inherited"):
            flags["author_inherited"] = True
    sens = [v for v in (_flags(m).get("sensitivity") for m in ms) if isinstance(v, int) and not isinstance(v, bool)]
    if sens:
        flags["sensitivity"] = max(sens)
    for k in _INT_FLAGS:
        v = next((x for x in (_flags(m).get(k) for m in ms) if isinstance(x, int) and not isinstance(x, bool)), None)
        if v is not None:
            flags[k] = v
    cps = sorted({k for m in ms for k in _strs(m.get("counterpart_keys"))})
    if cps or "counterpart_keys" in out:
        if len(cps) > CAP["counterpart_keys"]:
            cps = cps[:CAP["counterpart_keys"]]
            flags["cap_hit"] = True
        out["counterpart_keys"] = cps
    cues = {x for m in ms for x in _strs(m.get("act_cues"))}
    if cues or "act_cues" in out:
        out["act_cues"] = [x for x in ACT_CUES if x in cues]
    for col in ("priv_why", "ad_why"):
        vals = sorted({x for m in ms for x in _strs(m.get(col))})
        if vals or col in out:
            out[col] = vals[:CAP[col]]
    for col in ("confidence", "refw_depth", "priv_score", "priv_score_base", "ad_score"):
        vals = [m.get(col) for m in ms if isinstance(m.get(col), (int, float)) and not isinstance(m.get(col), bool)]
        if vals:
            out[col] = max(vals)
    obs = [m.get("observed_at") for m in ms if isinstance(m.get("observed_at"), str)]
    if obs:
        out["observed_at"] = max(obs)
    for col in ("is_reply", "replied", "i_sent_in_conv"):
        if any(m.get(col) is True for m in ms):
            out[col] = True
    if any(m.get("ad_band") == "suspect" for m in ms):
        out["ad_band"] = "suspect"
    priv = max((str(m.get("priv_class") or "work") for m in ms), key=lambda p: PRIV_ORDER.get(p, 0))
    if PRIV_ORDER.get(priv, 0) >= PRIV_ORDER["social"]:
        out["priv_class"] = priv
        if any(_flags(m).get("private") for m in ms) or priv == "private":
            flags["private"] = True
        for col in redact_fields(kind):
            if col in out:
                out[col] = [] if isinstance(out[col], (list, tuple)) else ""
    if flags or "flags" in out:
        out["flags"] = dict(sorted(flags.items()))
    return out


# ───────────────────────────── date-only 흡수 ─────────────────────────────
def _conv_key(row: Mapping):
    kind = row.get("kind")
    if kind == "teams":
        ck = row.get("chat_key") or row.get("msg_key")
        if row.get("chat_type") == "channel" and row.get("thread_key"):
            ck = f"{ck}:{row['thread_key']}"
        d = row.get("direction")
        return ("teams", "out" if d == "sent" else "in", ck)
    if kind == "mail":
        return ("mail", str(row.get("box") or ""), row.get("thread_key") or row.get("msg_key"))
    return None


def _absorb(rows: list[dict], off_min: int | None) -> tuple[list[dict], int]:
    exact = set()
    for r in rows:
        if r.get("ts_precision") in EXACT:
            k = _conv_key(r)
            d = _local_date(r, off_min)
            if k is not None and d is not None:
                exact.add((d, *k))
    out, n = [], 0
    for r in rows:
        if r.get("ts_precision") == "date":
            k = _conv_key(r)
            d = _local_date(r, None)
            if k is not None and d is not None and (d, *k) in exact:
                n += 1
                continue
        out.append(r)
    return out, n


# ───────────────────────────── 공개 함수 ─────────────────────────────
def merge_messages(rows: Iterable[Mapping], *, off_min: int | None = None, stats: dict | None = None) -> list[dict]:
    """저장 행(모든 kind 가능) → 병합 사본 목록((ts_utc, kind, id) 정렬). mail·cal·teams 만 병합하고 나머지 kind 는
    그대로(사본) 지나간다. ``off_min`` = date-only 흡수에서 정밀 행의 날짜를 정할 근무 시간대(분)."""
    rows_in, msgs, cps, others = 0, defaultdict(list), defaultdict(list), []
    for r in _dedupe_ids(rows):
        rows_in += 1
        kind = r.get("kind")
        mk = r.get("msg_key")
        if kind in MSG_KINDS and isinstance(mk, str) and mk:
            if r.get("src") in COPILOT_SRCS:
                cps[(str(r.get("src")), mk)].append(r)
            else:
                msgs[(kind, mk)].append(r)
        else:
            others.append(dict(r))
    exact_merged = sum(len(v) - 1 for v in msgs.values())
    out: list[dict] = []
    fuzzy_merged = 0
    for kind in MSG_KINDS:
        cl = [_Cluster(f"{k}|{mk}", v) for (k, mk), v in sorted(msgs.items()) if k == kind]
        cl, n = _fuzzy(kind, cl)
        fuzzy_merged += n
        out.extend(_merge_cluster(c) for c in cl)
    out, absorbed = _absorb(out, off_min)
    cp_dups = 0
    for (_src, _mk), v in sorted(cps.items()):
        v = sorted(v, key=_trust_key)
        v.sort(key=lambda m: str(m.get("observed_at") or ""), reverse=True)      # 안정 정렬: 관측 최신, 동률 id 순
        best = dict(v[0])
        best["provenance"] = [_prov(m) for m in sorted(v, key=_trust_key)]
        best["alias_keys"] = [best["msg_key"]]
        cp_dups += len(v) - 1
        out.append(best)
    out.extend(others)
    out.sort(key=lambda r: (str(r.get("ts_utc") or ""), str(r.get("kind") or ""), str(r.get("id") or ""),
                            str(r.get("pc_id") or "")))
    if stats is not None:
        stats.update(rows_in=rows_in, rows_out=len(out), exact_merged=exact_merged, fuzzy_merged=fuzzy_merged,
                     date_absorbed=absorbed, copilot_dups=cp_dups)
    return out


def _canon(row: Mapping) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)


def _dedupe_ids(rows: Iterable[Mapping]) -> list[Mapping]:
    """같은 ``(kind, id)`` 사본은 하나로(observed_at 최대, 동률은 정규 JSON 사전순 — 단일 로더와 같은 규칙, T-11).
    id 가 없는 행은 그대로 둔다. 입력 순서와 무관한 결과를 위해 먼저 한다."""
    best: dict = {}
    loose = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            loose.append(r)
            continue
        k = (str(r.get("kind") or ""), rid)
        cur = best.get(k)
        if cur is None:
            best[k] = r
            continue
        a, b = str(r.get("observed_at") or ""), str(cur.get("observed_at") or "")
        if a > b or (a == b and _canon(r) < _canon(cur)):
            best[k] = r
    loose.sort(key=_canon)
    return [best[k] for k in sorted(best)] + loose
