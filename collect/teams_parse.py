# -*- coding: utf-8 -*-
r"""collect\teams_parse.py — 팀즈 수집 판정용 순수 함수(LM28 WP3). 브라우저·파일·시계를 모른다(오늘 날짜는 인자).

  · key_of(date, hhmm, frm, chat, summary) — 중복 키(C-21). 날짜를 넣고(다른 날 같은 글은 2행), 본문·방 이름은
    privacy.sanitize 를 거친 글로 만든다. G1(run.py scrub_csv)이 저장 파일의 summary·chat 을 가린 뒤에도 원문으로 새로 읽은
    같은 메시지와 키가 같다(sanitize 는 멱등).
  · msg_hash(date, hhmm, frm, summary) — 방 커서(teams_web_rooms.json 의 newest_read)에 싣는 짧은 해시(원문을 남기지 않는다).
  · room_id(이름) — sha1(정규화한 방 이름·대화 ID)[:12].
  · iso_local(s) — <time datetime> → 이 PC 로컬 (date, (시, 분)) (owa_parse.iso_local 그대로 — 두 웹 수집기가 같은 해석).
  · room_verdict(events) → complete | cut_budget | cut_no_scroller | roomgone | incremental_ok (F-06·W1-05).
  · day_ranges(rooms, list_end, d0, d1, cap) → teams 축 LMSTATUS ranges(P4 — 검증된 날만 ok).
  · merge_keep_outside(old, new, d0, d1) — 기간 밖 옛 행은 그대로, 기간 안은 이번 행으로(W1-17 — Graph·Copilot 의 'w' 덮어쓰기 대신).
  · merge_union(old, new, keyf) — 덮지 않고 합치기(기간을 다 읽지 못한 Graph).
  · name_keys(name, label) — 방 이름 후보(정규화): 목록 이름 + aria-label 앞 조각 1~4개를 이은 것(CSV 방 이름 규칙).
  · title_fits(chat, name, label) — 머리 제목이 그 방인가(전환 확인용 — 외부·괄호·'외 n명'·단체방 이름 순서 같은 표기 차이 허용).
  · overlap(fp, pool) — 화면 메시지 지문 중 pool 에 든 비율(앞 방 화면 그대로 판정).
"""
import functools
import hashlib
import os
import re
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_CORE = os.path.join(os.path.dirname(_HERE), "core")
for _p in (_HERE, _CORE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import owa_parse  # noqa: E402  — 날짜 조각·ranges·<time datetime> 해석(WP2)
import privacy  # noqa: E402  — LM28 정제 단일원(WP7)

DAY = timedelta(days=1)
VERIFIED = ("complete", "incremental_ok")
VERDICTS = ("complete", "incremental_ok", "cut_budget", "cut_no_scroller", "roomgone")
TOP_DATE = date(1, 1, 1)          # 방 처음(맨 위)까지 확인했다 — 커서의 oldest 에 '0001-01-01' 로 싣는다


def norm_name(s):
    """비교용 이름 — 공백·마침표·가운뎃점·쉼표·괄호·대괄호·하이픈을 지우고 소문자(LM24 Get-TeamsWeb._norm 과 같은 규칙)."""
    return re.sub(r"[\s.·,()\[\]-]+", "", str(s or "")).lower()


@functools.lru_cache(maxsize=16384)
def _clean_cached(s, ctx):
    return re.sub(r"\s+", " ", privacy.sanitize(s, "summary", ctx)[0]).strip()


def clean(s, ctx=None):
    """정제된 글(공백 하나로) — 키 재료. ctx 는 privacy.make_ctx(cfg) — G1(scrub_csv)과 같은 사전으로 가려야 G1 뒤에도 키가
    같다(없으면 기본 규칙). 같은 글·같은 문맥은 다시 정제하지 않는다(캐시)."""
    return _clean_cached(str(s or ""), ctx)


def key_of(day, hhmm, frm, chat, summary, ctx=None):
    """(날짜, HH:MM, 보낸이, 방, 정제 요지 40자) — 같은 메시지를 두 경로·두 실행이 잡아도 한 번만 센다.
    방 이름도 정제한다: G1 이 chat 열을 가리므로(scrub_csv cols summary·chat) 원문 방 이름으로 만들면 키가 갈린다."""
    return (str(day or "")[:10], str(hhmm or "")[:5], norm_name(frm), norm_name(clean(chat, ctx)),
            clean(summary, ctx)[:40])


def row_key(time_s, frm, chat, summary, ctx=None):
    """CSV 행(time='YYYY-MM-DD HH:MM')의 key_of."""
    t = str(time_s or "")
    return key_of(t[:10], t[11:16], frm, chat, summary, ctx)


def msg_hash(day, hhmm, frm, summary, ctx=None):
    """방 커서용 메시지 해시 16자 — 방은 커서의 키라 넣지 않는다(목록 이름과 머리 제목이 달라도 같은 값)."""
    raw = "|".join((str(day or "")[:10], str(hhmm or "")[:5], norm_name(frm), clean(summary, ctx)[:40]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def room_id(ident):
    return hashlib.sha1(norm_name(ident).encode("utf-8")).hexdigest()[:12]


def iso_local(s):
    return owa_parse.iso_local(s)


def name_keys(name, label=""):
    """방 이름 후보(정규화) — 목록 이름, 그리고 aria-label 앞 조각 1~4개를 이은 것(단체방 머리 'A, B, C' 와 맞춘다)."""
    out = {norm_name(name)}
    parts = [x.strip() for x in re.split(r"[,|·]", str(label or "")) if x.strip()]
    for k in range(1, min(4, len(parts)) + 1):
        out.add(norm_name(",".join(parts[:k])))
    return {x for x in out if len(x) >= 2}


_NOTE = re.compile(r"[(\[（【][^)\]）】]{0,40}[)\]）】]")
_MORE = re.compile(r"\s*(?:외|및)\s*\d+\s*명.*$|\s*(?:and|\+)\s*\d+\s*(?:others?|more|people)?\s*$", re.I)
_SPLIT = re.compile(r"[,、，;·|/&]")


def strip_notes(s):
    """머리 제목의 덧붙임을 뗀다 — 괄호 표기('(외부)'·'[External]'·'(게스트)')와 '외 2명'·'and 3 others'·'+2'."""
    return _MORE.sub("", _NOTE.sub(" ", str(s or ""))).strip()


def name_parts(s, k=8):
    """이름 조각(정규화) — 덧붙임을 뗀 뒤 쉼표·가운뎃점 등으로 나눈 앞 k 개(2자 이상)."""
    out = []
    for x in _SPLIT.split(strip_notes(s))[:k]:
        x = norm_name(x)
        if len(x) >= 2:
            out.append(x)
    return out


def title_fits(chat, name, label=""):
    """머리 제목이 그 방인가 — 방 전환 확인용(CSV 방 이름은 이 규칙을 쓰지 않는다: 정확히 같을 때만 머리 제목을 쓴다).
    ① 정규화해 같음(name_keys) ② 덧붙임('(외부)'·'[External]'·'외 2명')을 떼면 같음 ③ 단체방 이름 순서만 다름 — 머리 조각
    2개 이상이 모두 목록 aria-label 조각 안 ④ 한쪽이 다른 쪽을 품고 짧은 쪽이 긴 쪽의 절반 이상(2자 이상).
    (비슷한 이름의 다른 방을 고를 위험은 호출 쪽이 '누른 뒤 화면이 바뀜'·'앞 방 지문 아님'으로 함께 막는다.)"""
    c = norm_name(chat)
    if len(c) < 2:
        return False
    keys = name_keys(name, label)
    if c in keys:
        return True
    c2 = norm_name(strip_notes(chat))
    keys2 = keys | {x for x in (norm_name(strip_notes(name)),) if len(x) >= 2}
    if len(c2) >= 2 and c2 in keys2:
        return True
    hp = name_parts(chat)
    if len(hp) >= 2 and set(hp) <= set(name_parts(label or name, 12)):
        return True
    for n in keys2:
        a, b = (n, c2) if len(n) <= len(c2) else (c2, n)
        if len(a) >= 2 and a in b and 2 * len(a) >= len(b):
            return True
    return False


def overlap(fp, pool):
    """화면 메시지 지문 fp 중 pool(집합)에 든 비율 0..1 — fp 나 pool 이 비면 0."""
    fp = [x for x in (fp or ()) if x]
    if not fp or not pool:
        return 0.0
    return sum(1 for x in fp if x in pool) / len(fp)


def room_verdict(events):
    """한 방을 읽으며 생긴 일(events — 'gone'·'overlap'·'reached_d0'·'top_confirmed'·'no_scroller'·'budget'·'max_scroll'·
    'stall' 의 모음) → 판정. 앞의 것이 이긴다:
      gone → roomgone(방 전환 확인 실패 — 그 방 행 0) · overlap → incremental_ok(지난 실행의 newest_read 와 겹침 — 이어짐 검증) ·
      reached_d0·top_confirmed → complete · no_scroller → cut_no_scroller(스크롤 영역 못 찾음 — '처음까지 읽음' 아님, F-06) ·
      그 밖(예산·되감기 상한·정체) → cut_budget."""
    ev = set(events or ())
    if "gone" in ev:
        return "roomgone"
    if "overlap" in ev:
        return "incremental_ok"
    if "reached_d0" in ev or "top_confirmed" in ev:
        return "complete"
    if "no_scroller" in ev:
        return "cut_no_scroller"
    return "cut_budget"


def _as_date(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def day_ranges(rooms, list_end, d0, d1, cap=None):
    """방 판정 → teams 축 ranges([{axis:'teams', from, to, st}]). 일자 d 는 둘 다 맞을 때만 ok, 그 밖은 partial:
      ① 목록이 끝에 닿았거나(list_end), 목록 마지막 방(마지막 활동을 아는 방 중 맨 아래)의 마지막 활동이 d 보다 이르다
         — 목록은 최근 활동순이라 d 에 활동한 방은 모두 목록 안에 있다.
      ② 마지막 활동이 d 이후(또는 모름)인 모든 방이 complete·incremental_ok 로 d 이하까지 읽혔다(read_to ≤ d) — roomgone·cut·
         안 연 방이 하나라도 있으면 아니다.
    rooms: 목록 순서의 [{last: date|None(마지막 활동), verdict: str|None(안 열었으면 None), read_to: date|None(이어서 읽은
    가장 오래된 날)}]. cap(오늘) 이후 날의 ok 는 partial(아직 메시지가 더 온다 — 다음 실행이 다시 읽게)."""
    d0, d1 = _as_date(d0), _as_date(d1)
    if not d0 or not d1 or d0 > d1:
        return []
    rs = []
    for r in rooms or ():
        rs.append((_as_date(r.get("last")), r.get("verdict"), _as_date(r.get("read_to"))))
    tail = next((x[0] for x in reversed(rs) if x[0] is not None), None)
    day_st, d = {}, d0
    while d <= d1:
        a = bool(list_end) or (tail is not None and tail < d)
        b = all(v in VERIFIED and rt is not None and rt <= d for last, v, rt in rs if last is None or last >= d)
        st = "ok" if (a and b) else "partial"
        if st == "ok" and cap is not None and d >= cap:
            st = "partial"
        day_st[d] = st
        d += DAY
    return owa_parse.ranges_of(day_st, "teams")


def merge_keep_outside(old, new, d0, d1, col=0):
    """옛 행 중 기간(d0~d1) 밖은 그대로 두고, 기간 안은 이번 행(new)으로 바꾼다(W1-17). 이번 행 중 기간 밖 행은 옛 행에 같은
    행이 없을 때만 더한다. 이번 행끼리 같은 행은 하나로. → 시각(col 열)순 목록."""
    a, b = str(d0)[:10], str(d1)[:10]

    def tday(r):
        return str(r[col] if len(r) > col else "")[:10]

    out = [list(r) for r in (old or ()) if r and not (a <= tday(r) <= b)]
    have = {tuple(r) for r in out}
    for r in new or ():
        r = list(r)
        t = tuple(r)
        if t in have:
            continue
        have.add(t)
        out.append(r)
    out.sort(key=lambda r: str(r[col] if len(r) > col else ""))
    return out


def merge_union(old, new, keyf, col=0):
    """덮지 않고 합치기 — 옛 행은 모두 두고, 이번 행은 같은 키(keyf)가 없을 때만 더한다. → 시각순 목록."""
    out = [list(r) for r in (old or ()) if r]
    keys = {keyf(r) for r in out}
    for r in new or ():
        k = keyf(r)
        if k in keys:
            continue
        keys.add(k)
        out.append(list(r))
    out.sort(key=lambda r: str(r[col] if len(r) > col else ""))
    return out
