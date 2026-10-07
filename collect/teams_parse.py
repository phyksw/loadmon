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
