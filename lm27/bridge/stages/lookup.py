# -*- coding: utf-8 -*-
r"""조회 단계 ``lookup_mail`` · ``lookup_teams`` · ``lookup_calendar``(B §8.1 · 계약 §2.12 · §2.17 · §3.2 · §6.5 · X-046 ·
X-082~X-084 · X-257 · X-258) — Copilot 이 내 메일·팀즈·일정을 검색해 돌려준 **요약 행(존재 증인)** 을 받는다.

  · 항목 1개 = 구간 1개(``d0``~``d1``, 양 끝 포함, ``bridge.lookup.windowDays`` 이하) = 질의 1건(새 채팅·업무 모드).
    키 ``<단계>:<d0>:<d1>``, 내용 키 = 단계 + d0·d1. 답은 행 봉투 ``{rid, n, more, items[행…]}`` → 접은 답
    ``{"rows": [...], "more": bool, "n": int}``(구간을 끝까지 못 담으면 실행기가 ``capped=true`` 를 붙인다).
  · 행 상한 = min(``bridge.lookup.maxRows``, ⌊(답 예산 − 200) / 행 추정⌋) — 행 추정 메일 130 · 팀즈 120 · 일정 110(B §8.1).
  · 행 검사(``normalize_row``): ``t`` 는 날짜만 남긴다(시각이 붙어 오면 떼고 ``time_dropped``), 구간 밖 날짜는 버린다
    (``out_of_window`` — 환각 방어), 형식 밖은 버린다(``bad_time``). 상대·수신 구분·대화 종류·화행·장소는 열거 밖이면
    ``-``·``other`` 로 바꾸고, 제목·요지는 60자에서 자른다.
  · 가득 참(``is_full``) = 잘림 · ``more`` · 행 수 ≥ ⌊행 상한 × ``bridge.lookup.fullRatio``⌋ → 구간을 반으로 쪼갠다
    (``split`` — 7일이면 3일·4일). ``bridge.lookup.minWindowDays`` 보다 못 쪼개면 받은 행을 커밋하고 ``capped``.
  · 폴백 없음 — 조회는 규칙으로 대신할 수 없다(빈 구간은 원장에 '코파일럿 조회 실패(사유)'로 남는다).
  · 시각을 묻지 않는다: 일정의 분 단위 시각은 COM·색인·OWA 몫이고 Copilot 요약은 시간 근거가 아니다(D-9).

머리말은 구간 날짜를 품는데 ``StageSpec.header(ctx, compact)`` 는 묶음을 받지 않으므로 ``title_line`` 이 조립 중인 묶음을
기억해 둔다(``lm27.bridge.stages.remember_batch``). 빈 묶음(패킹 예산 계산)이면 같은 길이의 자리 날짜를 쓴다.

어댑터 공용 순수 도구(``collect\Get-MailViaCopilot.py`` 가 쓴다 — 이 모듈은 정제 관문을 import 하지 않는다):
``plan_windows`` · ``ai_in_rows`` · ``leaves``(쪼갠 구간 펼치기) · ``witness_text`` · ``witness_raw``(증인 원시 행 —
``ts_precision="summary"`` · ``confidence`` 0.3 · 그 날짜 00:00 근무 시간대의 UTC · 답 행은 ``cp_row`` 로만 넘겨 키 재료가
된다, 계약 §4.2 'cp'). 증인 행은 메시지 행과 병합하지 않는다(경로 ID ``*.copilot`` — WP-11·18).

이전 판 ``Get-MailViaCopilot.py``·``Get-TeamsViaCopilot.py`` 의 ``UNABLE_MARKS``·``EMPTY_MARKS``(B §14)는 ``UNABLE_MARKS``·
``EMPTY_MARKS`` 로 옮겼다 — 답 글이 '조회 불가'·'결과 없음' 문구인지 ``reply_kind`` 가 가른다(L2 분류가 단계 표식을 쓰도록 CR).

입수 정제(B §9.1 ③ — '조회 행 포함'): L2 는 조회 답 ``{rows, more, n}`` 전체를 단계 ``item_schema`` 로 걷는다. 행 필드만 있으면
``rows`` 가 명세 밖이라 그대로 남으므로(행의 글이 정제되지 않은 채 저장소·ai_out 에 닿는다 — 완료 보고 CR), 행 스키마에 선택
필드 ``rows``(같은 행 스키마의 목록)를 더해 둔다(``_with_rows``). 행 하나를 검사할 때는 ``rows`` 가 없으니 영향이 없다.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta

from lm27.bridge.stages import as_text, current_batch, cut, fields_of, remember_batch, remembered_ctx
from lm27.bridge.stages.base import F, StageSpec

__all__ = [
    "AXES_OF", "CAL_RULES_TEMPLATE", "EMPTY_MARKS", "KIND_OF", "LOOKUP_TITLE_TEMPLATE", "LookupCalendar", "LookupMail",
    "LookupTeams", "MAIL_RULES_TEMPLATE", "SRC_OF", "STAGE_OF", "TEAMS_RULES_TEMPLATE", "UNABLE_MARKS", "WITNESS_CONFIDENCE",
    "ai_in_rows", "day_start_utc", "leaves", "parse_window_key", "plan_windows", "reply_kind", "window_key",
    "witness_raw", "witness_text",
]

# ───────────────────────── 경로·단계 대응(계약 §6.5) ─────────────────────────
SRC_OF = {"lookup_mail": "mail.copilot", "lookup_teams": "teams.copilot", "lookup_calendar": "cal.copilot"}
STAGE_OF = {v: k for k, v in SRC_OF.items()}
KIND_OF = {"mail.copilot": "mail", "teams.copilot": "teams", "cal.copilot": "cal"}
AXES_OF = {"mail.copilot": ("mail_in", "mail_out"), "teams.copilot": ("teams",), "cal.copilot": ("cal",)}
WITNESS_CONFIDENCE = 0.3          # 계약 §3.4 'Copilot summary 증인'
WITNESS_TEXT_MAX = 200            # text_masked ≤ 200(계약 §3.2)
ROW_TEXT_MAX = 60                 # 제목·요지 60자(B §8.1 행 검증)
ROW_MARGIN = 200                  # 행 상한 식의 봉투 몫(B §8.1)
FALLBACK_ROWS = 30                # 문맥(설정·답 예산)을 모를 때의 행 상한 표기
SRC_VER = "collect/1"
PLACEHOLDER_DAY = "0000-00-00"    # 빈 묶음(패킹 예산 계산)의 자리 날짜 — 실제 날짜와 같은 길이
SPLIT_DEPTH_MAX = 8

# ───────────────────────── 프롬프트(B §8.1 — 정제기 이름 탐지에 걸리는 두 문구만 바꿈, 완료 보고 CR) ─────────────────────────
LOOKUP_TITLE_TEMPLATE = "[LM27 요청 {rid} · {title} · 구간 {d0}~{d1}]"
RULES_HEAD_PROMPT = "규칙:"
MAIL_FIRST_TEMPLATE = "내 Outlook 메일(받은 편지함과 보낸 편지함)에서 {d0}부터 {d1}까지(양 끝 포함) 주고받은 업무 메일을 검색해 주세요."
TEAMS_FIRST_TEMPLATE = "내 Microsoft Teams 채팅에서 {d0}부터 {d1}까지(양 끝 포함) 주고받은 업무 메시지를 검색해 주세요."
CAL_FIRST_TEMPLATE = "내 Outlook 일정에서 {d0}부터 {d1}까지(양 끝 포함) 잡힌 업무 일정을 검색해 주세요."
MAIL_REPHRASE_TEMPLATE = "내 Outlook 메일에서 {d0}~{d1} 기간의 업무 메일을 검색해서, 찾은 것만 아래 형식으로 정리해 주세요."
TEAMS_REPHRASE_TEMPLATE = ("내 Microsoft Teams 채팅에서 {d0}~{d1} 기간의 업무 메시지를 검색해서, 찾은 것만 아래 형식으로 "
                           "정리해 주세요.")
CAL_REPHRASE_TEMPLATE = "내 Outlook 일정에서 {d0}~{d1} 기간의 업무 일정을 검색해서, 찾은 것만 아래 형식으로 정리해 주세요."
_COMMON_TAIL = (
    "- 제목은 요지만 40자 이내로 쓰고 전화번호·계좌·금액·주소는 뺍니다.",
    "- 날짜만 씁니다. 시각은 쓰지 않습니다.",
    "- 최대 {max_rows}행까지만 씁니다. 더 있으면 more 를 true 로 씁니다.",
)
# B 원문 '사람 이름 대신 메일 도메인(예: @example.com)' 은 정제기가 '이름 대신'·'@도메인' 을 사람으로 잡아 프롬프트 게이트가
# 단계를 멈춘다 — 같은 뜻으로 바꿨다(완료 보고 CR: WP-10 이름 문맥 규칙).
MAIL_RULES_TEMPLATE = (
    "- 실제로 검색된 메일만 씁니다. 예시·추정으로 행을 만들지 않고, 확실하지 않은 행은 뺍니다.",
    "- 자동 알림·광고·뉴스레터·시스템 메일은 뺍니다.",
    '- 상대는 사람을 쓰지 말고 메일 도메인(예: example.com)만 쓰고, 모르면 "-" 로 씁니다.',
) + _COMMON_TAIL
TEAMS_RULES_TEMPLATE = (
    "- 실제로 검색된 메시지만 씁니다. 예시·추정으로 행을 만들지 않고, 확실하지 않은 행은 뺍니다.",
    "- 자동 알림·광고·뉴스레터·시스템 메시지는 뺍니다.",
    "- 상대는 이름을 쓰지 말고 대화 종류만 씁니다.",
) + _COMMON_TAIL
CAL_RULES_TEMPLATE = (
    "- 실제로 검색된 일정만 씁니다. 예시·추정으로 행을 만들지 않고, 확실하지 않은 행은 뺍니다.",
    "- 참석자는 쓰지 않습니다.",
) + _COMMON_TAIL
MAIL_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, '
                      '"t": <"YYYY-MM-DD">, "d": <"in"|"out">, "who": <상대 도메인 또는 "-">, "rcv": <"to"|"cc"|"bulk"|"-">, '
                      '"s": <제목 요지>, "th": <RE:·FW: 를 뗀 스레드 제목 요지>} ]}')
TEAMS_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, '
                       '"t": <"YYYY-MM-DD">, "d": <"in"|"out">, "chat": <"1:1"|"group"|"channel"|"meeting"|"-">, '
                       '"act": <"request"|"report"|"other">, "s": <요지 40자 이내>} ]}')
CAL_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, '
                     '"t": <"YYYY-MM-DD">, "allday": <true|false>, "busy": <0|1|2|3>, "s": <제목 요지>, '
                     '"loc": <"teams"|"room"|"-">} ]}')
MAIL_UNKNOWN_PROMPT = "이 기간에 메일이 정말 없으면 items 를 빈 목록, n 을 0 으로 씁니다"
TEAMS_UNKNOWN_PROMPT = "이 기간에 메시지가 정말 없으면 items 를 빈 목록, n 을 0 으로 씁니다"
CAL_UNKNOWN_PROMPT = "이 기간에 일정이 정말 없으면 items 를 빈 목록, n 을 0 으로 씁니다"

# 이전 판 표식(B §14 — 이전 판 메일·팀즈 조회 스크립트 두 벌의 합집합: 팀즈 커넥터 없음 · '메시지가 없음' 문구 포함).
# 비교는 소문자.
UNABLE_MARKS = ("조회 불가", "조회가 불가", "조회할 수 없", "검색할 수 없", "검색이 불가", "액세스할 수 없", "접근할 수 없",
                "권한이 없", "지원되지 않", "지원하지 않", "제공되지 않", "cannot search", "can't search", "unable to",
                "no access", "don't have access", "조회 도구가 없", "데이터 조회 도구", "연결된 도구가 없", "도구가 없어",
                "no connected tool", "not connected to teams")
EMPTY_MARKS = ("없음", "찾을 수 없", "검색 결과가 없", "메일이 없", "일정이 없", "메시지가 없", "no emails", "no events",
               "no messages", "couldn't find", "could not find")

ROW_T_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?$")
WHO_RX = re.compile(r"^@?([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+)$")
DAY_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIRS = ("in", "out")
RCV = ("to", "cc", "bulk", "-")
CHATS = ("1:1", "group", "channel", "meeting", "-")
ACTS = ("request", "report", "other")
LOCS = ("teams", "room", "-")


def reply_kind(text: str) -> str:
    """답 글의 성격: ``unable``(조회 불가 문구) · ``empty``(결과 없음 문구) · ``other``(이전 판 _reply_status)."""
    low = as_text(text).lower()
    if any(m in low for m in UNABLE_MARKS):
        return "unable"
    if any(m in low for m in EMPTY_MARKS):
        return "empty"
    return "other"


def _day(v) -> date | None:
    s = as_text(v)
    if not DAY_RX.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ───────────────────────── 단계 ─────────────────────────
class _Lookup(StageSpec):
    """조회형 공통(B §8.1). 하위 클래스가 경로·문구·행 스키마·행 정규화만 정한다."""

    kind = "lookup"
    model_class = "fast"
    chat_policy = "fresh_each"
    want_work_mode = True
    max_items = 1
    min_split = 0
    allow_time = True
    send_fields = ("d0", "d1")
    text_fields = ()
    content_key_fields = ("d0", "d1")
    src = ""
    est_row = 120
    first_template = ""
    rephrase_template = ""
    rules_template: tuple = ()
    format_text = ""
    unknown_text = ""

    # ── 프롬프트 ──
    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        d0, d1 = self._window(batch)
        return LOOKUP_TITLE_TEMPLATE.format(rid=rid, title=self.title_ko, d0=d0, d1=d1)

    @staticmethod
    def _window(batch) -> tuple[str, str]:
        f = fields_of(batch[0]) if batch else {}
        a, b = _day(f.get("d0")), _day(f.get("d1"))
        return (a.isoformat() if a else PLACEHOLDER_DAY), (b.isoformat() if b else PLACEHOLDER_DAY)

    def _head(self, first: str, d0: str, d1: str, ctx) -> str:
        rows = self.max_rows(ctx)
        return "\n".join([first.format(d0=d0, d1=d1), RULES_HEAD_PROMPT]
                         + [t.format(max_rows=rows) for t in self.rules_template])

    def header(self, ctx, compact: bool = False) -> str:
        d0, d1 = self._window(current_batch(self, ctx))
        return self._head(self.first_template, d0, d1, ctx)

    def rephrase(self) -> str | None:
        """거절·조회 불가 1회(B §8.1): 첫 문장을 검색형 화법으로(이전 판 계승) — 규칙 줄은 그대로."""
        d0, d1 = self._window(current_batch(self, any_ctx=True))
        return self._head(self.rephrase_template, d0, d1, remembered_ctx(self))

    def columns(self) -> str:
        return ""                                   # 조회는 [항목] 줄이 없다(구간은 첫 줄·머리말에)

    def item_line(self, it, n) -> str:
        return ""

    def format_line(self) -> str:
        return self.format_text

    def unknown_rule(self) -> str:
        return self.unknown_text

    # ── 행 상한·가득 참·쪼개기 ──
    def max_rows(self, ctx=None) -> int:
        """min(``bridge.lookup.maxRows``, ⌊(답 예산 − 200) / 행 추정⌋)(B §8.1 · X-258)."""
        cfg = getattr(ctx, "cfg", None) if ctx is not None else None
        lk = getattr(cfg, "lookup", None)
        cap = int(getattr(lk, "max_rows", 0) or 0)
        pack_out = int(getattr(ctx, "pack_out", 0) or 0) if ctx is not None else 0
        pack_out = pack_out or int(getattr(cfg, "answer_max_chars", 0) or 0)
        est = (pack_out - ROW_MARGIN) // self.est_row if pack_out > ROW_MARGIN else 0
        vals = [v for v in (cap, est) if v > 0]
        return max(1, min(vals)) if vals else FALLBACK_ROWS

    def is_full(self, ans, status, ctx) -> bool:
        if status == "truncated":
            return True
        if not isinstance(ans, dict):
            return False
        if ans.get("more") is True:
            return True
        rows = ans.get("rows") if isinstance(ans.get("rows"), list) else []
        n_decl = ans.get("n") if isinstance(ans.get("n"), int) and not isinstance(ans.get("n"), bool) else 0
        n = max(len(rows), n_decl)
        lk = getattr(getattr(ctx, "cfg", None), "lookup", None)
        ratio = float(getattr(lk, "full_ratio", 0) or 0) or 1.0
        return n >= max(1, math.floor(self.max_rows(ctx) * ratio))

    def split(self, it, ctx):
        """구간을 반으로(7일 → 3일·4일). ``bridge.lookup.minWindowDays`` 이하면 None(더 못 쪼갬 → capped)."""
        f = fields_of(it)
        a, b = _day(f.get("d0")), _day(f.get("d1"))
        if a is None or b is None or b < a:
            return None
        days = (b - a).days + 1
        lk = getattr(getattr(ctx, "cfg", None), "lookup", None)
        min_w = max(1, int(getattr(lk, "min_window_days", 1) or 1))
        if days <= min_w:
            return None
        mid = a + timedelta(days=days // 2 - 1)
        out = []
        for x, y in ((a, mid), (mid + timedelta(days=1), b)):
            out.append({"key": window_key(self.id, x.isoformat(), y.isoformat()),
                        "fields": {"d0": x.isoformat(), "d1": y.isoformat()}})
        return out

    # ── 행 검증(B §8.1 표) ──
    def normalize_row(self, row, it, ctx):
        codes: list[str] = []
        m = ROW_T_RX.match(as_text(row.get("t")))
        if not m:
            return None, ("bad_time",)
        d = _day(m.group(1))
        if d is None:
            return None, ("bad_time",)
        if m.group(2) is not None:
            codes.append("time_dropped")
        f = fields_of(it) if it is not None else {}
        a, b = _day(f.get("d0")), _day(f.get("d1"))
        if a is not None and b is not None and not (a <= d <= b):
            return None, ("out_of_window",)
        out = {k: v for k, v in row.items() if k != "t"}
        out["t"] = d.isoformat()
        out = self._norm_fields(out, codes)
        if out is None:
            return None, tuple(codes) + ("bad_row_value",)
        return out, tuple(codes)

    def _norm_fields(self, out: dict, codes: list) -> dict | None:
        return out

    def normalize(self, ans, it, ctx):
        rows = ans.get("rows") if isinstance(ans, dict) and isinstance(ans.get("rows"), list) else []
        n = ans.get("n") if isinstance(ans, dict) and isinstance(ans.get("n"), int) else len(rows)
        return {"rows": rows, "more": bool(isinstance(ans, dict) and ans.get("more") is True), "n": int(n)}


def _with_rows(fields: tuple) -> tuple:
    """행 스키마 + 선택 ``rows``(같은 행 스키마의 목록) — L2 입수 정제가 답 봉투의 행 글까지 걷게 한다(위 머리말)."""
    return tuple(fields) + (F("rows", "list", required=False, item=tuple(fields)),)


def _dir(out: dict, codes: list) -> bool:
    d = as_text(out.get("d")).lower()
    if d not in DIRS:
        return False
    out["d"] = d
    return True


def _enum(out: dict, name: str, allowed: tuple, default: str, codes: list) -> None:
    v = as_text(out.get(name)).lower() if name in out else ""
    if v in allowed:
        out[name] = v
        return
    if name in out:
        codes.append(f"{name}_fixed")
    out[name] = default


def _texts(out: dict, *names: str) -> None:
    for name in names:
        if name in out:
            out[name] = cut(out[name], ROW_TEXT_MAX)


class LookupMail(_Lookup):
    id = "lookup_mail"
    title_ko = "메일 조회"
    prompt_ver = "lookup_mail/1.0"
    src = "mail.copilot"
    est_row = 130
    est_out_per_item = 130
    first_template = MAIL_FIRST_TEMPLATE
    rephrase_template = MAIL_REPHRASE_TEMPLATE
    rules_template = MAIL_RULES_TEMPLATE
    format_text = MAIL_FORMAT_PROMPT
    unknown_text = MAIL_UNKNOWN_PROMPT
    item_schema = _with_rows((F("t", "str"), F("d", "str"), F("who", "str", required=False, max_len=120),
                              F("rcv", "str", required=False), F("s", "str", required=False, max_len=ROW_TEXT_MAX),
                              F("th", "str", required=False, max_len=ROW_TEXT_MAX)))
    stub = {"t": "2026-09-01", "d": "in", "who": "-", "rcv": "to", "s": "업무 메일", "th": "업무 메일"}

    def _norm_fields(self, out, codes):
        if not _dir(out, codes):
            return None
        w = as_text(out.get("who"))
        m = WHO_RX.match(w)
        if m:
            out["who"] = "@" + m.group(1).lower()
        else:
            if w and w != "-":
                codes.append("who_fixed")
            out["who"] = "-"
        _enum(out, "rcv", RCV, "-", codes)
        _texts(out, "s", "th")
        return out


class LookupTeams(_Lookup):
    id = "lookup_teams"
    title_ko = "팀즈 조회"
    prompt_ver = "lookup_teams/1.0"
    src = "teams.copilot"
    est_row = 120
    est_out_per_item = 120
    first_template = TEAMS_FIRST_TEMPLATE
    rephrase_template = TEAMS_REPHRASE_TEMPLATE
    rules_template = TEAMS_RULES_TEMPLATE
    format_text = TEAMS_FORMAT_PROMPT
    unknown_text = TEAMS_UNKNOWN_PROMPT
    item_schema = _with_rows((F("t", "str"), F("d", "str"), F("chat", "str", required=False),
                              F("act", "str", required=False), F("s", "str", required=False, max_len=ROW_TEXT_MAX)))
    stub = {"t": "2026-09-01", "d": "in", "chat": "1:1", "act": "other", "s": "업무 대화"}

    def _norm_fields(self, out, codes):
        if not _dir(out, codes):
            return None
        _enum(out, "chat", CHATS, "-", codes)
        _enum(out, "act", ACTS, "other", codes)
        _texts(out, "s")
        return out


class LookupCalendar(_Lookup):
    id = "lookup_calendar"
    title_ko = "일정 조회"
    prompt_ver = "lookup_calendar/1.0"
    src = "cal.copilot"
    est_row = 110
    est_out_per_item = 110
    first_template = CAL_FIRST_TEMPLATE
    rephrase_template = CAL_REPHRASE_TEMPLATE
    rules_template = CAL_RULES_TEMPLATE
    format_text = CAL_FORMAT_PROMPT
    unknown_text = CAL_UNKNOWN_PROMPT
    item_schema = _with_rows((F("t", "str"), F("allday", "bool", required=False), F("busy", "int", required=False),
                              F("s", "str", required=False, max_len=ROW_TEXT_MAX), F("loc", "str", required=False)))
    stub = {"t": "2026-09-01", "allday": False, "busy": 2, "s": "업무 회의", "loc": "teams"}

    def _norm_fields(self, out, codes):
        b = out.get("busy")
        if b is not None and not (isinstance(b, int) and 0 <= b <= 3):
            codes.append("busy_fixed")
            out.pop("busy", None)
        if "allday" in out:
            out["allday"] = bool(out["allday"])
        _enum(out, "loc", LOCS, "-", codes)
        _texts(out, "s")
        return out


# ───────────────────────── 어댑터 공용 순수 도구(collect\Get-*ViaCopilot.py) ─────────────────────────
def window_key(stage: str, d0: str, d1: str) -> str:
    """항목 키 ``<단계>:<d0>:<d1>``(B §8.1 ai_in)."""
    return f"{stage}:{d0}:{d1}"


def parse_window_key(key: str) -> tuple[str, str] | None:
    parts = str(key or "").split(":")
    if len(parts) != 3 or _day(parts[1]) is None or _day(parts[2]) is None:
        return None
    return parts[1], parts[2]


def plan_windows(days, window_days: int, *, recheck: bool = False) -> list[tuple[str, str]]:
    """날짜들 → 이어진 날끼리 ``window_days`` 이하 구간들(날짜 순). ``recheck``(조회 능력 TTL 뒤 첫 확인 — B §7.13)이면
    첫 구간을 하루로 줄여 맨 앞에 둔다(거절이면 그 1건에서 멈추고, 되면 나머지를 이어 묻는다)."""
    ds = sorted({d if isinstance(d, date) else date.fromisoformat(str(d)) for d in days})
    w = max(1, int(window_days or 1))
    out: list[tuple[date, date]] = []
    run: list[date] = []
    for d in ds:
        if run and (d - run[-1]).days != 1:
            out.extend(_chunks(run, w))
            run = []
        run.append(d)
    if run:
        out.extend(_chunks(run, w))
    if recheck and out and out[0][0] != out[0][1]:
        a, b = out[0]
        out[0:1] = [(a, a), (a + timedelta(days=1), b)]
    return [(a.isoformat(), b.isoformat()) for a, b in out]


def _chunks(run: list, w: int) -> list:
    return [(run[i], run[min(i + w, len(run)) - 1]) for i in range(0, len(run), w)]


def ai_in_rows(stage: str, windows) -> list[dict]:
    """구간들 → ``ai_in`` 행(B §2.5 — 보낼 필드는 d0·d1 뿐)."""
    return [{"key": window_key(stage, a, b), "group": "", "fields": {"d0": a, "d1": b}, "src_ver": SRC_VER}
            for a, b in windows]


def leaves(items: dict, key: str, _depth: int = 0) -> list[tuple[str, dict | None]]:
    """``ai_out.items`` 에서 구간 하나의 잎 구간들 — 쪼갠 부모(``by=rule``·``why=split``)는 자식으로 펼친다.
    반환 ``[(잎 키, 항목 기록 또는 None)]``(기록이 없으면 None — 아직 접히지 않음)."""
    e = items.get(key) if isinstance(items, dict) else None
    if isinstance(e, dict) and e.get("by") == "rule" and e.get("why") == "split" and _depth < SPLIT_DEPTH_MAX:
        kids = (e.get("ans") or {}).get("split") if isinstance(e.get("ans"), dict) else None
        out: list = []
        for k in kids or ():
            if isinstance(k, str):
                out.extend(leaves(items, k, _depth + 1))
        return out or [(key, e)]
    return [(key, e if isinstance(e, dict) else None)]


def _fmt_off(off_min: int) -> str:
    sign = "-" if off_min < 0 else "+"
    h, m = divmod(abs(int(off_min)), 60)
    return f"{sign}{h:02d}:{m:02d}"


def day_start_utc(day, off_min: int) -> str:
    """그 날짜 00:00(근무 시간대 ``off_min``)의 UTC ``YYYY-MM-DDTHH:MM:SSZ``(B §8.1 ts_utc)."""
    d = day if isinstance(day, date) else date.fromisoformat(str(day))
    t = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(minutes=int(off_min))
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def witness_text(src: str, row: dict) -> str:
    """증인 행 글(B §8.1): 메일 = 제목 요지 + ' / ' + 스레드 요지(다를 때), 팀즈·일정 = 요지. 200자 이하."""
    s = as_text(row.get("s"))
    if src == "mail.copilot":
        th = as_text(row.get("th"))
        if th and th != s:
            s = f"{s} / {th}" if s else th
    return cut(s, WITNESS_TEXT_MAX)


def witness_raw(src: str, row: dict, *, off_min: int, observed: str) -> dict:
    """답 행 1개 → 증인 원시 행(정제 관문 ``sanitize_record(kind, raw, rc)`` 입력, 계약 §3.2 '*.copilot').
    ``ts_precision="summary"`` 고정 · ``confidence`` 0.3 · 그 날짜 00:00(근무 시간대)의 UTC · 글은 ``copilot_text``.
    답 행 전체는 ``cp_row`` 로만 넘긴다 — 키 재료(계약 §4.2 ``cp:<src>|<DATE>|<sha256(답 행)>``)가 되고 저장되지 않는다."""
    day = row["t"]
    raw = {"ts_utc": day_start_utc(day, off_min), "ts_local_offset": _fmt_off(off_min), "ts_precision": "summary",
           "observed_at": observed, "confidence": WITNESS_CONFIDENCE, "copilot_text": witness_text(src, row),
           "cp_row": {k: row[k] for k in sorted(row)}}
    if src == "cal.copilot":
        raw["end_utc"] = day_start_utc(date.fromisoformat(day) + timedelta(days=1), off_min)
    return raw
