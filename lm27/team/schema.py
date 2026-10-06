# -*- coding: utf-8 -*-
r"""팀 묶음 스키마 v1.0 — 빌더·서버 공용 검증기와 ``TEAM_SPEC_V1`` 단일원(TAB §2.3 · 계약 §3.18 · X-270 · L-23).

공개 API
  ``TEAM_SPEC_V1``                 필드 → 값 클래스 표(최상위 = TAB §2.3.2 표 = P §14.5 표의 필드). P 의
                                   ``check_team_payload(payload, gctx, spec)`` 에 **늘 명시해서** 넘긴다(X-304).
  ``validate_team_bundle(obj, registry, side, …) -> list[Err]``
                                   형식(값 클래스) + 일관성(TAB §2.3.2 의 integrity·참조 무결성) + 레지스트리 대조(경고).
  ``BYTES_GUARD``                  정규 바이트 전체에 거는 마지막 그물(빌더 3중 검사의 3단 · 서버 수신 재검사).
  ``team_text(s, maxlen, field, ctx)``  자유 문자열 검사(빌더가 필드마다 부른다 — P ``check_team_label``·``forbidden_codes``).
  ``active_spans(days, gap=2)``    alloc 일자 → active 구간(TAB §4.6, I7 대조의 한 함수).
  ``judge_hello(...)``             ``/api/hello`` 판정표(TAB §2.9 · §6.1 매핑) — 클라이언트·포트 진단 공용.

``TEAM_SPEC_V1`` 노드 형식(P 쪽 순회기가 읽는 약속 — 이 docstring 이 정본):
  · ``"CLASS"``      값 클래스. 끝 ``?`` = null 허용, ``|EMPTY`` = 빈 문자열 허용.
      CONST:<값> · VER · DATETIME_OFFSET · DATE · MONTH · NUM(유한 수 ≥0) · SNUM(유한 수, 음수 허용) · BOOL ·
      PERSON_KEY · PEER_KEY · UNIT_ID · ROLE_ID · PROJECT_ID · PROPOSAL_ID · NEED_ID · REG_ID · APP_ID · HEX8 ·
      LABEL20 · LABEL30 · LABEL40 · COUNTS(코드 → NUM) · ENUM{a,b,…}(닫힌 값) · ENUM:<어휘>(레지스트리
      vocab: fields · functions · activity_types · step_types) · RE:<정규식>(fullmatch).
  · ``dict``         객체 — 키는 이 사전의 키만(그 밖 = unknown_key).
  · ``[node]``       배열 — 원소마다 node.
  · ``{"$row": [n0, n1, …]}``   고정 길이 행(배열) — 자리마다 노드.
  · ``{"$map": node, "$key": "CLASS"}``  키가 열린 사전 — 키는 $key 클래스, 값은 node.
  빠져도 되는 키는 ``OPTIONAL`` 표(경로 표기 ``units[].first_evidence``)에 있다 — 값 클래스와는 따로다.

원칙: 서버는 묶음을 **고치지 않고 거절**한다(조용한 보정·재스케일 금지, TAB §6 ``mm_scale`` 폐기). 오류 목록에는 경로·코드·
한국어 사유만 싣고 값은 싣지 않는다. 이 모듈은 표준 라이브러리만 쓰고 ``lm27.privacy`` 는 함수 안에서만 부른다
(team → privacy 한 방향, 계약 X-304).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ───────────────────────────── 이름·판 ─────────────────────────────
SCHEMA_NAME = "lm27.team_bundle"
SCHEMA_MAJOR = 1
SCHEMA_MINOR = 0
ACCEPTS = {str(SCHEMA_MAJOR): SCHEMA_MINOR}          # /api/hello 의 accepts.team_bundle (TAB §2.6)
APP_ID = "LM27-team"                                # 계약 §4.7 팀 서버 신원(작업·뮤텍스 이름 아님 — L-15 예외, v1.2 C22)
PROTO = "lm27-team/1"
API_LEVEL = 1
MAX_DEPTH = 32                                       # JSON 중첩 상한(계약 §5.3)
MAX_PERIOD_DAYS = 400
DAY_MIN = 1440

# HTTP 422 코드(TAB §3.6) — 막는 오류는 이 다섯 중 하나로 응답 코드가 정해진다
BLOCK_CODES = ("schema", "unknown_major", "forbidden_content", "integrity", "ref_missing")
# 경고 코드(저장은 하되 /api/members flags·취합 warnings 에 표시)
WARN_CODES = ("unknown_key", "unknown_member", "pepper_mismatch", "calendar_mismatch", "unknown_project",
              "gantt_mismatch", "unknown_vocab", "unknown_agent")

TAGS = ("regular", "extended", "night", "holiday")
DOMAINS = ("DEV", "MP", "EXT", "COM", "AX")         # 과제·제안 영역 5종(계약 §3.18 · X-232)
DOMAINS_ALL = DOMAINS + ("UNC",)                     # UNC 는 파생 전용(과제가 없는 역할)
ACTIVITY_TYPES = ("DEV", "OFFICE", "FIELD", "PM", "PL", "SUPPORT", "EDU")   # 계약 §3.18 기본 7종
START_KINDS = ("S1i", "S1o", "S2", "M")
END_KINDS = ("E1o", "E1i", "E2", "E3c", "E3i", "M")  # + null (X-207)
PRECISIONS = ("exact", "minute", "date", "none")
GRADES = ("A", "B", "C", "D", "E", "M")              # M = 수동 기록 전용(X-207)
UNIT_STATUS = ("closed", "open", "estimated")
SPAN_KINDS = ("lead", "active")
WHY = ("digital_io", "repeat_weekly", "repeat_monthly", "structured_input", "low_accountability", "verifiable",
       "tool_access")                                # X-278 tool_access 추가
FITS = ("적합", "조건부", "부적합")
AGENT_GRADES = ("상", "중", "하")
QUALITY_GRADES = ("reliable", "caution", "unreliable")
COV_AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
COV_STATES = ("ok", "zero_ok", "partial", "out_of_horizon", "blocked", "transport_fail", "not_attempted")
RESERVED_PROJECTS = {"P-9901": "DEV", "P-9902": "MP", "P-9903": "EXT", "P-9904": "COM", "P-9905": "AX"}

# ───────────────────────────── 형식 정규식 ─────────────────────────────
RX = {
    "PERSON_KEY": re.compile(r"p_[0-9a-f]{12}"),
    "PEER_KEY": re.compile(r"c_[0-9a-f]{12}"),
    "UNIT_ID": re.compile(r"u_[0-9a-f]{10}"),
    "ROLE_ID": re.compile(r"r_[0-9a-f]{6}"),
    "PROJECT_ID": re.compile(r"P-\d{4}"),
    "PROPOSAL_ID": re.compile(r"pr_\d{1,4}"),
    "NEED_ID": re.compile(r"n_[0-9a-f]{6}"),
    "REG_ID": re.compile(r"[A-Za-z][A-Za-z0-9_\-]{0,23}"),
    "APP_ID": re.compile(r"[a-z0-9_.\-]{1,24}"),
    "HEX8": re.compile(r"[0-9a-f]{8}"),
    "DATE": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "MONTH": re.compile(r"\d{4}-\d{2}"),
    "VER": re.compile(r"\d{4}\.\d{1,2}\.\d{1,3}|\d+\.\d+(?:\.\d+)?|[0-9a-f]{16}"),
    "DATETIME_OFFSET": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[+-]\d{2}:\d{2}|Z)"),
    "VOCAB_CODE": re.compile(r"[A-Z][A-Z0-9_]{1,15}"),
}
RULES_VER_RX = re.compile(r"\d{4}\.\d{1,2}\.\d{1,3}")
HEX16_RX = re.compile(r"[0-9a-f]{16}")
SCHEMA_VER_RX = re.compile(r"(\d+)\.(\d+)")
_LABEL_MAX = {"LABEL20": 20, "LABEL30": 30, "LABEL40": 40}
_SRC_RX = r"(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)"
_PROBE_KEY_RX = r"[a-z]{2,8}\.[a-z]{2,10}"

# ───────────────────────────── TEAM_SPEC_V1 ─────────────────────────────
_GEN_SPEC = {"app": "LABEL40", "app_version": "VER", "core_version": "LABEL40", "rules_ver": "VER",
             "rules_hash": "VER", "registry_version": "NUM", "calendar_version": "LABEL40",
             "catalog_version": "LABEL40"}
_BY_TAG = {"regular": "NUM", "extended": "NUM", "night": "NUM", "holiday": "NUM"}
_GRADE3 = "ENUM{상,중,하}"
_FIT3 = "ENUM{적합,조건부,부적합}"

TEAM_SPEC_V1 = {
    "schema": "CONST:" + SCHEMA_NAME,
    "schema_version": "VER",
    "generator": _GEN_SPEC,
    "built_at": "DATETIME_OFFSET",
    "person": {"person_key": "PERSON_KEY", "member_id": "REG_ID?", "self_label": "LABEL20",
               "self_peer_key": "PEER_KEY?", "pepper_id": "HEX8?", "field": "ENUM:fields|EMPTY",
               "work_tz_offset_min": "SNUM", "peer_scope": "ENUM{team,personal}"},
    "period": {"from": "DATE", "to": "DATE", "analyzed_until": "DATETIME_OFFSET", "months": ["MONTH"]},
    "summary": {"std_day_min": "NUM", "months": [{
        "month": "MONTH", "workdays": "NUM", "covered_workdays": "NUM", "absence_days": "NUM", "avail_days": "SNUM",
        "envelope_min": "NUM", "by_tag": _BY_TAG, "attributed_min": "NUM", "unattributed_min": "NUM", "mm": "NUM",
        "load_pct": "NUM?"}]},
    "envelope_daily": {"cols": ["ENUM{date,regular,extended,night,holiday}"],
                       "rows": [{"$row": ["DATE", "NUM", "NUM", "NUM", "NUM"]}]},
    "alloc_daily": {"cols": ["ENUM{date,unit_id,tag,min}"],
                    "rows": [{"$row": ["DATE", "UNIT_ID", "ENUM{regular,extended,night,holiday}", "NUM"]}]},
    "projects": [{"project_id": "PROJECT_ID", "domain": "ENUM{DEV,MP,EXT,COM,AX}"}],
    "proposals": [{"proposal_id": "PROPOSAL_ID", "kind": "ENUM{project,role}", "label": "LABEL40",
                   "domain_guess": "ENUM{DEV,MP,EXT,COM,AX}"}],
    "roles": [{"role_id": "ROLE_ID", "project_id": "PROJECT_ID?", "proposal_id": "PROPOSAL_ID?",
               "field": "ENUM:fields", "function": "ENUM:functions"}],
    "units": [{
        "unit_id": "UNIT_ID", "role_id": "ROLE_ID", "title": "LABEL40", "title_mode": "ENUM{label,generic}",
        "activity_type": "ENUM:activity_types", "ax_link": "BOOL",
        "start": {"kind": "ENUM{S1i,S1o,S2,M}", "at": "DATETIME_OFFSET?", "precision": "ENUM{exact,minute,date,none}"},
        "end": {"kind": "ENUM{E1o,E1i,E2,E3c,E3i,M}?", "at": "DATETIME_OFFSET?",
                "precision": "ENUM{exact,minute,date,none}"},
        "grade": "ENUM{A,B,C,D,E,M}", "status": "ENUM{closed,open,estimated}", "first_evidence": "DATE?",
        "last_evidence": "DATE?", "lead_time_h": "NUM?", "effort_min": "NUM",
        "spans": [{"$row": ["DATE", "DATE", "ENUM{lead,active}"]}], "peers": ["PEER_KEY"], "apps": ["APP_ID"],
        "apps_unknown_min": "NUM", "evidence_n": {"$map": "NUM", "$key": "RE:[a-z_]{1,16}"}}],
    "workflows": [{
        "role_id": "ROLE_ID", "units": ["UNIT_ID"],
        "steps": [{"no": "NUM", "type": "ENUM:step_types", "label": "LABEL30", "n": "NUM", "median_min": "NUM",
                   "agent_grade": _GRADE3 + "|EMPTY", "subagent": _FIT3,
                   "why": ["ENUM{" + ",".join(WHY) + "}"], "wait_in_median_min": "NUM?", "work_share": "NUM?",
                   "bottleneck": "ENUM{wait,work,both}|EMPTY", "sample": "ENUM{ok,thin}"}],
        "edges": [{"$row": ["NUM", "NUM", "NUM"]}]}],
    "agentic": {"catalog_version": "LABEL40|EMPTY",
                "matches": [{"agent_id": "REG_ID", "role_id": "ROLE_ID", "step_type": "ENUM:step_types",
                             "grade": _GRADE3, "units": ["UNIT_ID"]}],
                "needs": [{"need_id": "NEED_ID", "step_type": "ENUM:step_types", "label": "LABEL40", "grade": _GRADE3,
                           "freq_per_month": "NUM", "units": ["UNIT_ID"], "src": "ENUM{ai,rule}"}],
                "subagents": [{"role_id": "ROLE_ID", "fit": _FIT3,
                               "chain": [{"step_no": "NUM", "proposal": "LABEL40"}]}]},
    "peers": [{"peer_key": "PEER_KEY", "scope": "ENUM{team,personal}", "units": "NUM", "shared_effort_min": "NUM"}],
    "peers_external": {"customer": "NUM", "partner": "NUM", "other": "NUM"},
    "privacy_counts": "COUNTS",
    "catalog_proposals": [{"exe": r"RE:[a-z0-9_.\-]{1,64}\.exe", "company": "LABEL40", "product": "LABEL40",
                           "n_days": "NUM", "minutes": "NUM"}],
    "quality": {
        "grade": "ENUM{reliable,caution,unreliable}|EMPTY", "reasons": ["LABEL20"],
        "pcs": [{"ord": "NUM", "label_auto": "LABEL20", "kind": "LABEL20", "agent_impl": "ENUM{py,ps,none}",
                 "observed_days": "NUM", "event_days": "NUM", "stuck_days": "NUM",
                 "probe": {"$map": "LABEL20", "$key": "RE:" + _PROBE_KEY_RX}}],
        "coverage": [{"axis": "ENUM{" + ",".join(COV_AXES) + "}",
                      "days": {"$map": "NUM", "$key": "ENUM{" + ",".join(COV_STATES) + "}"},
                      "srcs": ["RE:" + _SRC_RX], "exact_ratio": "NUM?"}],
        "days": {"weekdays": "NUM", "no_evidence_weekdays": "NUM", "long_days_16h": "NUM", "anomaly_days": "NUM"},
        "confirm_queue": {"open": "NUM", "resolved": "NUM"},
        "estimated_min_ratio": "NUM", "team_text_rejected": "NUM",
        "copilot": {"used": "BOOL", "items": "NUM", "failed_items": "NUM"}},
    "integrity": {"envelope_min": "NUM", "alloc_min": "NUM", "unattributed_min": "NUM", "rows_env": "NUM",
                  "rows_alloc": "NUM", "units": "NUM"},
}

# 빠져도 되는 키(값 클래스와 별개 — 판 차이·선택 필드). 그 밖 스펙 키는 모두 필수.
OPTIONAL = frozenset({
    "units[].first_evidence", "units[].last_evidence", "units[].lead_time_h",
    "workflows[].steps[].wait_in_median_min", "workflows[].steps[].work_share", "workflows[].steps[].bottleneck",
    "workflows[].steps[].sample", "agentic.needs[].src",
    "quality.pcs", "quality.coverage", "quality.days", "quality.confirm_queue", "quality.estimated_min_ratio",
    "quality.team_text_rejected", "quality.copilot", "quality.coverage[].exact_ratio", "quality.pcs[].probe",
    "quality.pcs[].stuck_days", "quality.pcs[].event_days", "generator.catalog_version",
    "generator.registry_version", "generator.calendar_version",
})
# 0~1 비율이어야 하는 수(형 검사에 더해)
RATIO_PATHS = frozenset({"quality.estimated_min_ratio", "quality.coverage[].exact_ratio",
                         "workflows[].steps[].work_share"})
# 정수여야 하는 수(X-275 '정수 ≥0' 보강)
INT_PATHS = frozenset({
    "summary.std_day_min", "summary.months[].workdays", "summary.months[].covered_workdays",
    "summary.months[].envelope_min", "summary.months[].by_tag.*", "summary.months[].attributed_min",
    "summary.months[].unattributed_min", "envelope_daily.rows[].1", "envelope_daily.rows[].2",
    "envelope_daily.rows[].3", "envelope_daily.rows[].4", "alloc_daily.rows[].3", "units[].effort_min",
    "units[].apps_unknown_min", "units[].evidence_n.*", "workflows[].steps[].no", "workflows[].steps[].n",
    "workflows[].steps[].median_min", "workflows[].steps[].wait_in_median_min", "workflows[].edges[].0",
    "workflows[].edges[].1", "workflows[].edges[].2", "agentic.subagents[].chain[].step_no", "peers[].units",
    "peers[].shared_effort_min", "peers_external.*", "privacy_counts.*", "catalog_proposals[].n_days",
    "catalog_proposals[].minutes", "integrity.*", "person.work_tz_offset_min", "generator.registry_version",
})


def spec_table() -> list[tuple[str, str]]:
    """``TEAM_SPEC_V1`` → [(경로, 값 클래스)] — P §14.5 대조표의 생성물(L-23 · X-270). 정렬된 경로 순."""
    out: list[tuple[str, str]] = []

    def walk(node, path):
        if isinstance(node, str):
            out.append((path, node))
        elif isinstance(node, list):
            walk(node[0], path + "[]")
        elif isinstance(node, dict) and "$row" in node:
            out.append((path, "[" + ", ".join(x if isinstance(x, str) else "…" for x in node["$row"]) + "]"))
        elif isinstance(node, dict) and "$map" in node:
            out.append((path, "{" + node["$key"] + ": " + (node["$map"] if isinstance(node["$map"], str) else "…") + "}"))
        else:
            for k in sorted(node):
                walk(node[k], f"{path}.{k}" if path else k)
    walk(TEAM_SPEC_V1, "")
    return sorted(out)


# ───────────────────────────── 바이트 그물 ─────────────────────────────
BYTES_GUARD = [                                                   # TAB §2.4 — 문자열 경계와 무관한 것만
    re.compile(rb"[^\s@\"]{1,64}@[^\s@\"]{1,255}\.[A-Za-z]{2,}"),   # 이메일
    re.compile(rb"(?<![0-9a-z_])w[0-9a-f]{16}(?![0-9a-f])"),        # who_key
    re.compile(rb"pcx?_[0-9a-f]{16}"),                              # pc_id
    re.compile(rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),   # GUID
    re.compile(rb"(?i)https?://"),
]
BYTES_GUARD_NAMES = ("email", "who_key", "pc_id", "guid", "url")


def bytes_guard_hits(raw: bytes) -> list[str]:
    """정규 바이트에서 걸린 그물 이름(값은 돌려주지 않는다)."""
    return [nm for nm, rx in zip(BYTES_GUARD_NAMES, BYTES_GUARD, strict=True) if rx.search(raw)]


# ───────────────────────────── 오류 ─────────────────────────────
@dataclass(frozen=True)
class Err:
    """검증 결과 하나. ``blocking=False`` 는 경고(저장은 하되 표시). msg 는 한국어 사유 — 값을 싣지 않는다."""

    path: str
    code: str
    msg: str
    blocking: bool = True

    def as_detail(self) -> str:
        return f"{self.path}: {self.code}"


def blocking(errs) -> list[Err]:
    return [e for e in errs if e.blocking]


def first_code(errs) -> str:
    """막는 오류 중 응답 코드로 쓸 것 — unknown_major > schema > ref_missing > integrity > forbidden_content 순."""
    order = ("unknown_major", "schema", "ref_missing", "integrity", "forbidden_content")
    codes = {e.code for e in errs if e.blocking}
    for c in order:
        if c in codes:
            return c
    return "schema"


# ───────────────────────────── 작은 도우미 ─────────────────────────────
def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def has_control(s: str) -> bool:
    """제어·서식 문자(Cc·Cf — zero-width·BOM 포함)가 있는가."""
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in s)


def parse_date(s) -> date | None:
    if not isinstance(s, str) or not RX["DATE"].fullmatch(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_dt(s) -> datetime | None:
    """ISO 8601 + 오프셋(또는 Z) → aware datetime. 오프셋이 없거나 형식이 틀리면 None."""
    if not isinstance(s, str) or not RX["DATETIME_OFFSET"].fullmatch(s):
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_between(d0: date, d1: date) -> list[str]:
    out, y, m = [], d0.year, d0.month
    while (y, m) <= (d1.year, d1.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def depth(obj, limit: int = MAX_DEPTH + 1) -> int:
    """중첩 깊이(스칼라 0). limit 를 넘으면 그 값에서 멈춘다(깊은 입력에 재귀 폭발 없음)."""
    best = 0
    stack = [(obj, 1)]
    while stack:
        o, d = stack.pop()
        if isinstance(o, (dict, list)):
            if d > best:
                best = d
            if best >= limit:
                return best
            for x in (o.values() if isinstance(o, dict) else o):
                if isinstance(x, (dict, list)):
                    stack.append((x, d + 1))
    return best


def schema_version_of(obj) -> tuple[int, int] | None:
    v = obj.get("schema_version") if isinstance(obj, dict) else None
    m = SCHEMA_VER_RX.fullmatch(v) if isinstance(v, str) else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def period_key_of(obj) -> str:
    """``<from>_<to>`` (TAB §2.2)."""
    p = obj["period"]
    return f"{p['from']}_{p['to']}"


def role_id_of(scope_id: str | None, field: str, func: str) -> str:
    """R-8 · 계약 §4.4: ``"r_" + sha256("LM27.role|" + (과제 또는 제안 또는 "UNC") + "|" + 분야 + "|" + 기능)[:6]``."""
    s = "LM27.role|" + (scope_id or "UNC") + "|" + (field or "") + "|" + (func or "")
    return "r_" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:6]


def pepper_id_of(pepper_hex: str) -> str:
    """TAB §2.3.3: ``sha256(bytes.fromhex(pepper))[:8]``."""
    return hashlib.sha256(bytes.fromhex(pepper_hex)).hexdigest()[:8]


def active_spans(days, gap: int = 2) -> list[tuple[date, date]]:
    """alloc 이 있는 날들을 정렬해, 사이 빈 날이 gap 이하이면 한 구간으로 잇는다(결정적, TAB §4.6)."""
    out: list[tuple[date, date]] = []
    for d in sorted(set(days)):
        if out and (d - out[-1][1]).days <= gap + 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def registry_vocab(registry) -> dict[str, set[str]]:
    """레지스트리 ``vocab.{fields,functions,activity_types,step_types}``(객체 목록 ``{code,…}`` 또는 옛 문자열) → 코드 집합.
    레지스트리가 없거나 그 어휘가 없으면 그 이름은 빠진다(호출자는 형식만 본다)."""
    out: dict[str, set[str]] = {}
    voc = registry.get("vocab") if isinstance(registry, dict) else None
    if not isinstance(voc, dict):
        return out
    for name in ("fields", "functions", "activity_types", "step_types"):
        items = voc.get(name)
        if not isinstance(items, list):
            continue
        codes = set()
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("code"), str):
                codes.add(it["code"])
            elif isinstance(it, str):
                codes.add(it)
        if codes:
            out[name] = codes
    return out


# ───────────────────────────── 값 클래스 검사 ─────────────────────────────
class _Ctx:
    def __init__(self, side, server_minor, bundle_minor, vocab, errs):
        self.side = side
        self.server_minor = server_minor
        self.bundle_minor = bundle_minor
        self.vocab = vocab
        self.errs = errs
        self.seen_unknown = set()

    def err(self, path, code, msg, block=True):
        self.errs.append(Err(path, code, msg, block))


def _generic(path: str) -> str:
    """'units[3].spans[0]' → 'units[].spans[]' (OPTIONAL·INT_PATHS 표 대조용)."""
    return re.sub(r"\[\d+\]", "[]", path)


def _check_class(v, cls: str, path: str, c: _Ctx) -> None:
    gp = _generic(path)
    nullable = cls.endswith("?")
    if nullable:
        cls = cls[:-1]
    empty_ok = cls.endswith("|EMPTY")
    if empty_ok:
        cls = cls[:-6]
    if v is None:
        if not nullable:
            c.err(path, "schema", "빈 값(null)은 허용되지 않습니다")
        return
    if empty_ok and v == "":
        return
    bad = False
    if cls.startswith("CONST:"):
        bad = v != cls[6:]
    elif cls in ("NUM", "SNUM"):
        if not _is_num(v) or (cls == "NUM" and v < 0):
            bad = True
        elif gp in INT_PATHS or _star(gp) in INT_PATHS:
            bad = not _is_int(v)
        if not bad and gp in RATIO_PATHS and not 0 <= v <= 1:
            bad = True
    elif cls == "BOOL":
        bad = not isinstance(v, bool)
    elif cls in _LABEL_MAX:
        bad = not isinstance(v, str) or len(v) > _LABEL_MAX[cls] or has_control(v)
    elif cls == "COUNTS":
        bad = not isinstance(v, dict) or any(not isinstance(k, str) or not re.fullmatch(r"[a-z_:]{1,32}", k)
                                             or not _is_int(x) or x < 0 for k, x in v.items())
    elif cls.startswith("ENUM{"):
        bad = v not in cls[5:-1].split(",")
    elif cls.startswith("ENUM:"):
        name = cls[5:]
        if not isinstance(v, str) or not RX["VOCAB_CODE"].fullmatch(v):
            bad = True
        elif name in c.vocab and v not in c.vocab[name]:
            c.err(path, "unknown_vocab", "레지스트리 어휘에 없는 코드입니다", block=False)
        elif name == "activity_types" and name not in c.vocab and v not in ACTIVITY_TYPES:
            c.err(path, "unknown_vocab", "기본 업무 유형 코드가 아닙니다", block=False)
    elif cls.startswith("RE:"):
        bad = not isinstance(v, str) or not re.fullmatch(cls[3:], v)
    elif cls == "DATE":
        bad = parse_date(v) is None
    elif cls == "DATETIME_OFFSET":
        bad = parse_dt(v) is None
    elif cls == "MONTH":
        bad = not isinstance(v, str) or not RX["MONTH"].fullmatch(v) or not 1 <= int(v[5:]) <= 12
    elif cls in RX:
        bad = not isinstance(v, str) or not RX[cls].fullmatch(v)
    else:                                                              # 스펙 오류 — 막는다(fail-closed)
        bad = True
    if bad:
        c.err(path, "schema", f"값 형식이 {cls} 가 아닙니다")
    elif isinstance(v, str) and has_control(v):
        c.err(path, "schema", "제어·서식 문자가 들어 있습니다")


def _star(gp: str) -> str:
    """'summary.months[].by_tag.regular' → 'summary.months[].by_tag.*'(열린 사전 값)."""
    return gp.rsplit(".", 1)[0] + ".*" if "." in gp else gp


def _walk(v, node, path: str, c: _Ctx) -> None:
    if isinstance(node, str):
        _check_class(v, node, path, c)
        return
    if isinstance(node, list):
        if not isinstance(v, list):
            c.err(path, "schema", "배열이어야 합니다")
            return
        for i, x in enumerate(v):
            _walk(x, node[0], f"{path}[{i}]", c)
        return
    if "$row" in node:
        cols = node["$row"]
        if not isinstance(v, list) or len(v) != len(cols):
            c.err(path, "schema", f"길이 {len(cols)} 행이어야 합니다")
            return
        for i, (x, n) in enumerate(zip(v, cols, strict=True)):
            _walk(x, n, f"{path}.{i}" if path.endswith("]") else f"{path}[{i}]", c)
        return
    if "$map" in node:
        if not isinstance(v, dict):
            c.err(path, "schema", "객체여야 합니다")
            return
        for k, x in v.items():
            kc = node["$key"]
            if kc.startswith("ENUM{"):
                okk = k in kc[5:-1].split(",")
            else:
                okk = isinstance(k, str) and bool(re.fullmatch(kc[3:], k))
            if not okk:
                c.err(f"{path}.?", "schema", "허용되지 않는 키 이름입니다")
                continue
            _walk(x, node["$map"], f"{path}.{k}", c)
        return
    if not isinstance(v, dict):
        c.err(path, "schema", "객체여야 합니다")
        return
    for k in node:
        p = f"{path}.{k}" if path else k
        if k not in v:
            if _generic(p) not in OPTIONAL:
                c.err(p, "schema", "필수 필드가 없습니다")
            continue
        _walk(v[k], node[k], p, c)
    for k in v:
        if k in node:
            continue
        p = f"{path}.?" if path else "?"
        if not isinstance(k, str) or has_control(k) or len(k) > 40:
            c.err(p, "schema", "키 이름이 형식에 맞지 않습니다")
        elif c.bundle_minor is not None and c.bundle_minor > c.server_minor:
            c.err(f"{path}.{k}" if path else k, "unknown_key", "이 서버가 모르는 필드(새 MINOR) — 무시합니다", block=False)
        else:
            c.err(f"{path}.{k}" if path else k, "schema", "스키마에 없는 필드입니다")


# ───────────────────────────── 일관성 검사 ─────────────────────────────
def _num_eq(a, b, tol) -> bool:
    return _is_num(a) and _is_num(b) and abs(a - b) <= tol


def _check_consistency(obj: dict, registry, calendar, gap: int, c: _Ctx) -> None:
    per = obj["period"]
    d0, d1 = parse_date(per["from"]), parse_date(per["to"])
    if d0 is None or d1 is None:
        return
    if d0 > d1:
        c.err("period", "schema", "기간 시작이 끝보다 늦습니다")
        return
    if (d1 - d0).days + 1 > MAX_PERIOD_DAYS:
        c.err("period", "schema", f"기간이 {MAX_PERIOD_DAYS}일을 넘습니다")
    if per["months"] != months_between(d0, d1):
        c.err("period.months", "schema", "기간의 달 목록이 기간과 다릅니다")
    au = parse_dt(per["analyzed_until"])
    if au is not None and not d0 <= au.date() <= d1 + timedelta(days=1):
        c.err("period.analyzed_until", "schema", "분석 끝 시각이 기간 밖입니다")

    # envelope_daily
    env = {}
    ed = obj["envelope_daily"]
    if ed["cols"] != ["date", *TAGS]:
        c.err("envelope_daily.cols", "schema", "열 이름이 다릅니다")
    prev = None
    for i, row in enumerate(ed["rows"]):
        d = parse_date(row[0])
        if d is None or not all(_is_int(x) for x in row[1:]):
            continue
        p = f"envelope_daily.rows[{i}]"
        if prev is not None and d <= prev:
            c.err(p, "schema", "날짜가 오름차순·중복 없음이 아닙니다")
        prev = d
        if not d0 <= d <= d1:
            c.err(p, "schema", "기간 밖 날짜입니다")
        if any(x > DAY_MIN for x in row[1:]) or sum(row[1:]) > DAY_MIN:
            c.err(p, "integrity", "하루 봉투가 1440분을 넘습니다")
        env[d] = dict(zip(TAGS, row[1:], strict=True))

    # units
    units = {}
    for i, u in enumerate(obj["units"]):
        uid = u.get("unit_id")
        if uid in units:
            c.err(f"units[{i}].unit_id", "schema", "단위업무 ID 중복")
        units[uid] = (i, u)

    # alloc_daily
    ad = obj["alloc_daily"]
    if ad["cols"] != ["date", "unit_id", "tag", "min"]:
        c.err("alloc_daily.cols", "schema", "열 이름이 다릅니다")
    seen, by_dt, by_unit, unit_days, alloc_sum = set(), {}, {}, {}, 0
    for i, row in enumerate(ad["rows"]):
        d = parse_date(row[0])
        if d is None or not _is_int(row[3]) or row[2] not in TAGS:
            continue
        p = f"alloc_daily.rows[{i}]"
        if not 1 <= row[3] <= DAY_MIN:
            c.err(p, "schema", "귀속 분이 1~1440 이 아닙니다")
        if not d0 <= d <= d1:
            c.err(p, "schema", "기간 밖 날짜입니다")
        k = (d, row[1], row[2])
        if k in seen:
            c.err(p, "schema", "(날짜, 단위업무, 꼬리표) 중복")
        seen.add(k)
        if row[1] not in units:
            c.err(p, "ref_missing", "units 에 없는 단위업무입니다")
        by_dt[(d, row[2])] = by_dt.get((d, row[2]), 0) + row[3]
        by_unit[row[1]] = by_unit.get(row[1], 0) + row[3]
        unit_days.setdefault(row[1], set()).add(d)
        alloc_sum += row[3]
    for (d, t), a in sorted(by_dt.items()):
        if a > env.get(d, {}).get(t, 0):
            c.err(f"alloc_daily@{d.isoformat()}.{t}", "integrity", "하루·꼬리표 귀속 합이 봉투보다 큽니다")

    # summary
    std = obj["summary"]["std_day_min"]
    cal_std = calendar.get("std_day_min") if isinstance(calendar, dict) else getattr(calendar, "std_day_min", None)
    if _is_int(cal_std) and std != cal_std:
        c.err("summary.std_day_min", "calendar_mismatch", "표준 근무일 분이 팀 달력과 다릅니다", block=False)
    sm = obj["summary"]["months"]
    if [m.get("month") for m in sm] != per["months"]:
        c.err("summary.months", "schema", "요약 달 목록이 기간의 달과 다릅니다")
    for i, m in enumerate(sm):
        p = f"summary.months[{i}]"
        mon = m.get("month")
        if not isinstance(mon, str) or not all(_is_num(m.get(k)) for k in ("workdays", "envelope_min", "attributed_min",
                                                                             "unattributed_min", "mm", "avail_days")):
            continue
        e_tag = {t: sum(v[t] for d, v in env.items() if month_of(d) == mon) for t in TAGS}
        e_sum = sum(e_tag.values())
        a_sum = sum(a for (d, _t), a in by_dt.items() if month_of(d) == mon)
        bt = m.get("by_tag") or {}
        ok = (m["envelope_min"] == e_sum and all(bt.get(t) == e_tag[t] for t in TAGS)
              and m["attributed_min"] == a_sum and m["unattributed_min"] == e_sum - a_sum)
        wd = m["workdays"]
        if ok:
            ok = _num_eq(m["mm"], e_sum / (std * wd), 1e-9) if std and wd else m["mm"] == 0
        if ok and _is_num(m.get("covered_workdays")) and _is_num(m.get("absence_days")):
            ok = _num_eq(m["avail_days"], m["covered_workdays"] - m["absence_days"], 1e-9)
        if ok:
            av = m["avail_days"]
            lp = m.get("load_pct")
            if av <= 0 or not std:
                ok = lp is None
            else:
                ok = _num_eq(lp, e_sum / (std * av) * 100, 1e-6)
        if not ok:
            c.err(p, "integrity", "월 요약이 일자 표와 맞지 않습니다(봉투·꼬리표·귀속·MM·가용·로드)")
        if calendar is not None and hasattr(calendar, "month_workdays") and _is_int(wd):
            try:
                cw = calendar.month_workdays(int(mon[:4]), int(mon[5:7]))
            except ValueError:
                cw = None
            if cw is not None and cw != wd:
                c.err(f"{p}.workdays", "calendar_mismatch", "그 달 근무일이 팀 달력과 다릅니다", block=False)

    # projects · proposals · roles
    reg_projects = {}
    if isinstance(registry, dict) and isinstance(registry.get("projects"), list):
        reg_projects = {x.get("id"): x for x in registry["projects"] if isinstance(x, dict)}
    proj_ids = set()
    for i, pr in enumerate(obj["projects"]):
        pid = pr.get("project_id")
        if pid in proj_ids:
            c.err(f"projects[{i}].project_id", "schema", "과제 ID 중복")
        proj_ids.add(pid)
        if registry is not None and pid not in reg_projects and pid not in RESERVED_PROJECTS:
            c.err(f"projects[{i}].project_id", "unknown_project", "레지스트리에 없는 과제 — 묶음의 영역을 씁니다",
                  block=False)
    prop_ids = set()
    for i, pr in enumerate(obj["proposals"]):
        pid = pr.get("proposal_id")
        if pid in prop_ids:
            c.err(f"proposals[{i}].proposal_id", "schema", "제안 ID 중복")
        prop_ids.add(pid)
    roles = {}
    for i, r in enumerate(obj["roles"]):
        p = f"roles[{i}]"
        rid = r.get("role_id")
        if rid in roles:
            c.err(f"{p}.role_id", "schema", "역할 ID 중복")
        roles[rid] = r
        pj, pp = r.get("project_id"), r.get("proposal_id")
        if pj is not None and pp is not None:
            c.err(p, "schema", "과제와 제안을 함께 가리킬 수 없습니다")
        if pj is not None and pj not in proj_ids:
            c.err(f"{p}.project_id", "ref_missing", "projects 에 없는 과제입니다")
        if pp is not None and pp not in prop_ids:
            c.err(f"{p}.proposal_id", "ref_missing", "proposals 에 없는 제안입니다")
        if isinstance(rid, str) and isinstance(r.get("field"), str) and isinstance(r.get("function"), str) \
                and rid != role_id_of(pj or pp, r["field"], r["function"]):
            c.err(f"{p}.role_id", "integrity", "역할 ID 가 (과제·분야·기능) 식과 다릅니다(R-8)")

    # units 세부
    for uid, (i, u) in units.items():
        p = f"units[{i}]"
        if u.get("role_id") not in roles:
            c.err(f"{p}.role_id", "ref_missing", "roles 에 없는 역할입니다")
        if _is_int(u.get("effort_min")) and u["effort_min"] != by_unit.get(uid, 0):
            c.err(f"{p}.effort_min", "integrity", "투입 분이 그 단위업무 귀속 합과 다릅니다")
        fe, le = parse_date(u.get("first_evidence")), parse_date(u.get("last_evidence"))
        if fe and le and fe > le:
            c.err(p, "schema", "첫 근거가 마지막 근거보다 늦습니다")
        apps = u.get("apps")
        if isinstance(apps, list) and len(apps) > 20:
            c.err(f"{p}.apps", "schema", "앱은 20개까지입니다")
        spans = u.get("spans")
        if not isinstance(spans, list):
            continue
        leads, acts = 0, []
        for j, s in enumerate(spans):
            if not (isinstance(s, list) and len(s) == 3):
                continue
            a, b = parse_date(s[0]), parse_date(s[1])
            if a and b and a > b:
                c.err(f"{p}.spans[{j}]", "schema", "구간 시작이 끝보다 늦습니다")
            if s[2] == "lead":
                leads += 1
            elif s[2] == "active" and a and b:
                acts.append((a, b))
        if leads != 1:
            c.err(f"{p}.spans", "schema", "lead 구간은 정확히 하나여야 합니다")
        want = active_spans(unit_days.get(uid, ()), gap)
        if sorted(acts) != want:
            c.err(f"{p}.spans", "gantt_mismatch", "active 구간이 귀속 일자에서 다시 만든 것과 다릅니다 — 서버 값을 씁니다",
                  block=False)

    # workflows
    unit_role = {uid: u.get("role_id") for uid, (_i, u) in units.items()}
    for i, w in enumerate(obj["workflows"]):
        p = f"workflows[{i}]"
        rid = w.get("role_id")
        if rid not in roles:
            c.err(f"{p}.role_id", "ref_missing", "roles 에 없는 역할입니다")
        for uid in w.get("units") or ():
            if unit_role.get(uid) != rid:
                c.err(f"{p}.units", "ref_missing", "그 역할의 단위업무가 아닙니다")
                break
        nos = [s.get("no") for s in w.get("steps") or () if isinstance(s, dict)]
        if len(set(nos)) != len(nos) or any(not _is_int(n) or n < 1 for n in nos):
            c.err(f"{p}.steps", "schema", "단계 번호가 1 이상·중복 없음이 아닙니다")
        for e in w.get("edges") or ():
            if isinstance(e, list) and len(e) == 3 and (e[0] not in nos or e[1] not in nos):
                c.err(f"{p}.edges", "ref_missing", "단계에 없는 번호를 잇습니다")
                break

    # agentic
    ag = obj["agentic"]
    agents = None
    if isinstance(registry, dict) and isinstance(registry.get("agents"), list):
        agents = {x.get("id") for x in registry["agents"] if isinstance(x, dict)}
    for i, mt in enumerate(ag.get("matches") or ()):
        p = f"agentic.matches[{i}]"
        aid = mt.get("agent_id")
        if isinstance(aid, str) and not aid.startswith("AG"):
            c.err(f"{p}.agent_id", "schema", "에이전트 ID 는 AG 로 시작합니다")
        elif agents is not None and aid not in agents:
            c.err(f"{p}.agent_id", "unknown_agent", "카탈로그에 없는 에이전트입니다", block=False)
        if mt.get("role_id") not in roles:
            c.err(f"{p}.role_id", "ref_missing", "roles 에 없는 역할입니다")
        _check_unit_refs(mt.get("units"), units, p, c)
    need_ids = set()
    for i, nd in enumerate(ag.get("needs") or ()):
        p = f"agentic.needs[{i}]"
        if nd.get("need_id") in need_ids:
            c.err(f"{p}.need_id", "schema", "니즈 ID 중복")
        need_ids.add(nd.get("need_id"))
        _check_unit_refs(nd.get("units"), units, p, c)
    for i, sa in enumerate(ag.get("subagents") or ()):
        if sa.get("role_id") not in roles:
            c.err(f"agentic.subagents[{i}].role_id", "ref_missing", "roles 에 없는 역할입니다")

    # person
    pe = obj["person"]
    mid = pe.get("member_id")
    if isinstance(mid, str):
        if not mid.startswith("M"):
            c.err("person.member_id", "schema", "구성원 ID 는 M 으로 시작합니다")
        elif isinstance(registry, dict) and isinstance(registry.get("members"), list) \
                and mid not in {x.get("id") for x in registry["members"] if isinstance(x, dict)}:
            c.err("person.member_id", "unknown_member", "레지스트리 구성원에 없는 ID 입니다", block=False)
    off = pe.get("work_tz_offset_min")
    if _is_int(off) and not -720 <= off <= 840:
        c.err("person.work_tz_offset_min", "schema", "근무 시간대 오프셋 범위(-720~840분) 밖입니다")

    # generator
    g = obj["generator"]
    for k, v in g.items():
        if isinstance(v, str) and len(v) > 40:
            c.err(f"generator.{k}", "schema", "40자를 넘습니다")
    if isinstance(g.get("rules_ver"), str) and not RULES_VER_RX.fullmatch(g["rules_ver"]):
        c.err("generator.rules_ver", "schema", "정제 규칙 판 형식이 아닙니다")
    if isinstance(g.get("rules_hash"), str) and not HEX16_RX.fullmatch(g["rules_hash"]):
        c.err("generator.rules_hash", "schema", "정제 규칙 해시는 16자리 16진수입니다")

    # integrity
    integ = obj["integrity"]
    env_sum = sum(sum(v.values()) for v in env.values())
    want = {"envelope_min": env_sum, "alloc_min": alloc_sum, "unattributed_min": env_sum - alloc_sum,
            "rows_env": len(ed["rows"]), "rows_alloc": len(ad["rows"]), "units": len(obj["units"])}
    for k, v in want.items():
        if integ.get(k) != v:
            c.err(f"integrity.{k}", "integrity", "본문에서 다시 센 값과 다릅니다")


def _check_unit_refs(lst, units, path, c) -> None:
    for uid in lst or ():
        if uid not in units:
            c.err(f"{path}.units", "ref_missing", "units 에 없는 단위업무입니다")
            return


# ───────────────────────────── 공용 검증기 ─────────────────────────────
def validate_team_bundle(obj, registry=None, side: str = "server", *, calendar=None, payload_check=None,
                         server_minor: int = SCHEMA_MINOR, gap: int = 2, pepper_id: str | None = None) -> list[Err]:
    """팀 묶음 검증(TAB §2.3.2) → ``[Err]``(빈 목록 = 통과). 막는 오류가 하나라도 있으면 서버는 422.

    registry  서버(또는 클라이언트 캐시) 레지스트리 dict — 없으면 레지스트리 대조 경고를 건너뛴다.
    side      ``server`` | ``client``(빌더). 규칙은 같고, 서버만 ``payload_check`` 를 반드시 넘긴다.
    calendar  ``lm27.time.calendar.Calendar``(월 근무일·std_day_min 대조 — 다르면 경고 calendar_mismatch).
    payload_check  ``obj -> [(경로, 코드)]`` — P ``check_team_payload(obj, gctx, spec=TEAM_SPEC_V1)`` 래퍼.
                  위반은 ``forbidden_content``(막음). 형식 오류가 있으면 부르지 않는다(구조가 깨진 입력을 넘기지 않음).
    pepper_id  서버 pepper 의 id — 묶음 값과 다르면 경고 pepper_mismatch.
    """
    if side not in ("server", "client"):
        raise ValueError("side 는 server 또는 client")
    errs: list[Err] = []
    if not isinstance(obj, dict):
        return [Err("", "schema", "최상위가 객체가 아닙니다")]
    if depth(obj) > MAX_DEPTH:
        return [Err("", "schema", f"중첩이 {MAX_DEPTH} 단계를 넘습니다")]
    if obj.get("schema") != SCHEMA_NAME:
        return [Err("schema", "schema", "팀 묶음 스키마 이름이 아닙니다")]
    ver = schema_version_of(obj)
    if ver is None:
        return [Err("schema_version", "schema", "판 형식은 MAJOR.MINOR 입니다")]
    if str(ver[0]) not in ACCEPTS:
        return [Err("schema_version", "unknown_major", "이 서버가 받지 않는 묶음 주판입니다 — LM27 을 같은 판으로 맞추세요")]
    c = _Ctx(side, server_minor, ver[1], registry_vocab(registry), errs)
    _walk(obj, TEAM_SPEC_V1, "", c)
    if blocking(errs):
        return errs
    _check_consistency(obj, registry, calendar if calendar is not None else _registry_calendar(registry), gap, c)
    pid = obj["person"].get("pepper_id")
    if pepper_id and pid and pid != pepper_id:
        errs.append(Err("person.pepper_id", "pepper_mismatch", "팀 pepper 가 다른 묶음 — 동료 연결에 쓰지 않습니다", False))
    if payload_check is not None and not blocking(errs):
        for path, code in payload_check(obj) or ():
            errs.append(Err(str(path), "forbidden_content", f"팀 업로드 금지 내용({code})"))
    return errs


def _registry_calendar(registry):
    cal = registry.get("calendar") if isinstance(registry, dict) else None
    return cal if isinstance(cal, dict) else None


# ───────────────────────────── 자유 문자열 검사(빌더용) ─────────────────────────────
def team_text(s, maxlen: int, field: str, ctx) -> str | None:
    """TAB §2.4 — NFKC·Cc/Cf 제거·공백 접기·자르기 뒤 P ``check_team_label``·``forbidden_codes``·로컬 사전 검사.
    걸리면 None(호출자가 대체 라벨), 비면 "". ``ctx`` = ``gctx``·``audit``(dict)·``audit_fields``(dict)·
    ``local_dict_hit(s) -> bool``(``self_label`` 은 호출자가 None 을 넘겨 사전 검사를 건너뛴다)."""
    from lm27.privacy import check_team_label, forbidden_codes          # team → privacy 한 방향(X-304)
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = " ".join(s.split())[:maxlen]
    if not s:
        return ""
    hit = getattr(ctx, "local_dict_hit", None)
    if check_team_label(s, ctx.gctx, maxlen) or forbidden_codes(s, ctx.gctx) or (hit is not None and hit(s)):
        ctx.audit["team_text_rejected"] = ctx.audit.get("team_text_rejected", 0) + 1
        ctx.audit_fields[field] = ctx.audit_fields.get(field, 0) + 1
        return None
    return s


def privacy_payload_check(cfg):
    """서버 수신 재검사용 ``payload_check`` — P ``check_team_payload(obj, gctx, spec=TEAM_SPEC_V1)``(spec 명시, X-304).
    서버에는 키링·로컬 사전이 없으므로 게이트 문맥은 ``make_gate_context(None, cfg, None, stage="team_server", audit=None)``
    으로 만든다(정제 사전 없음·카나리아 = 서버 PC 환경 — WP-11 에 요청한 서버 모드, 완료 보고 CR)."""
    def check(obj):
        from lm27 import privacy
        gctx = privacy.make_gate_context(None, cfg, None, stage="team_server", audit=None)
        out = []
        for v in privacy.check_team_payload(obj, gctx, TEAM_SPEC_V1) or ():
            path = getattr(v, "path", None) if not isinstance(v, (tuple, list)) else v[0]
            code = getattr(v, "code", None) if not isinstance(v, (tuple, list)) else v[1]
            out.append((str(path or ""), str(code or "forbidden")))
        return out
    return check


# ───────────────────────────── /api/hello 판정(TAB §2.9 · 계약 §6.1) ─────────────────────────────
HELLO_REASON = {"timeout": "R-TEAM-TIMEOUT", "refused": "R-TEAM-REFUSED", "dns": "R-TEAM-DNS", "proxy": "R-TEAM-PROXY",
                "lm24": "R-TEAM-LM24", "other_lm": "R-TEAM-OTHERAPP", "other_app": "R-TEAM-OTHERAPP",
                "http_error": "R-TEAM-OTHERAPP", "wrong_major": "R-TEAM-VERSION"}


def judge_hello(status: int | None, body=None, *, whoami=None, team=None, proxy=False, error: str | None = None) -> str:
    """관측 → ``result``(ok · other_lm · lm24 · other_app · http_error · wrong_major · proxy · timeout · refused · dns).

    status/body  ``GET /api/hello`` 의 HTTP 코드와 JSON(객체가 아니면 None). error = 연결 실패 종류(timeout·refused·dns).
    whoami/team  hello 가 404 일 때 ``/api/whoami``·``/api/team`` JSON — **모양만** 보고 버린다(LM24 응답엔 경로·토큰이 있다).
    proxy        응답에 프록시 표식 헤더(Via·Proxy-*)가 있었는가(X-271)."""
    if error in ("timeout", "refused", "dns"):
        return error
    if proxy and not (isinstance(body, dict) and body.get("app") == APP_ID):
        return "proxy"
    if status == 200 and isinstance(body, dict):
        app = body.get("app")
        if app == APP_ID and str(body.get("proto") or "").startswith("lm27-team/"):
            acc = (body.get("accepts") or {}).get("team_bundle") if isinstance(body.get("accepts"), dict) else None
            if isinstance(acc, dict) and str(SCHEMA_MAJOR) not in acc:
                return "wrong_major"
            return "ok"
        if isinstance(app, str) and app.startswith("LM"):
            return "other_lm"
        return "other_app"
    if status == 404:
        if isinstance(whoami, dict) and "root" in whoami:
            return "lm24"
        if isinstance(team, dict) and isinstance(team.get("members"), list) and ("uploads" in team or "agg_note" in team):
            return "lm24"
        return "other_app"
    if status is None:
        return "other_app"
    return "http_error" if status >= 400 else "other_app"


def canon_size_ok(raw: bytes, max_mb: int) -> bool:
    return len(raw) <= max_mb * 1024 * 1024


def loads_bundle(raw: bytes):
    """팀 묶음 바이트 → 객체(UTF-8 · 중복 키 · NaN 거부). ValueError(UnicodeDecodeError 포함)를 그대로 올린다."""
    from lm27.util.fsx import loads_strict
    if raw[:3] == b"\xef\xbb\xbf":
        raise ValueError("BOM")                       # 정규 바이트에는 BOM 이 없다(미리보기=실전송)
    return loads_strict(raw)


def major_of(raw: bytes) -> int | None:
    """바이트에서 주판만 빠르게(취합기의 MAJOR 별 읽기 함수 선택, TAB §4.2)."""
    m = re.search(rb'"schema_version":"(\d+)\.\d+"', raw)
    return int(m.group(1)) if m else None


def dumps_canon(obj) -> bytes:
    """정규 바이트(``fsx.canon_bytes`` 와 같은 규칙)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
