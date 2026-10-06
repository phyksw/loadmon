# -*- coding: utf-8 -*-
r"""열 허용 목록 ``SCHEMAS`` · 봉인 행 ``SanitizedRow`` · 단일 관문 ``sanitize_record()``(P §10 · 계약 §3.1~§3.5 · C6·C7·C11·C15).

원시 레코드(메모리 — P §10.2 원시 이름)를 받아 **열 허용 목록에 있는 열만** 가진 봉인 행을 만든다. 순서(P §10.3):
원시 검증(필수·형·금지 원시 필드 → ``bad_raw``) → 사적 폴더·삭제 편지함 → 키(정제 **전** 원문으로 HMAC, 키 없음 모드면
필수 kind 는 ``no_key`` 폐기·선택 kind 는 null + ``flags.no_key``) → 파생 특징(광고 헤더·본문 플래그·``act_cues``·
``abs_hint``·rcv) → 텍스트 정제(자격증명이면 ``cred`` 폐기) → 광고 점수(drop 이면 ``ad`` 폐기) → 공사 판정 → 사적이면
텍스트·``act_cues`` 비움 → 키 없음 모드면 ``[사람#…]``→``[사람]`` → 조립 → ``id``(정제문 해시) → 모든 열 검증(I12 —
위반이면 ``error(ColumnViolation)``, 감사에는 열 이름만) → 봉인.

봉인(L-11 ③ · 계약 §2.2): ``SanitizedRow`` 는 이 모듈의 ``_SEAL`` 로만 만들어진다. ``data`` 는 읽기 전용(``MappingProxyType``·
튜플)이고 ``__replace__``·``__copy__``·``__deepcopy__``·피클은 TypeError, dataclass 가 아니라 ``dataclasses.replace`` 도
통하지 않는다. 저장은 ``lm27.store.SegmentWriter.append(row)`` 하나(봉인·``SCHEMAS`` 재검증).

계약 v1.2 결정 반영: C6(주키 없는 ``pc.events`` 는 ``<layer>|<event_class>``, ``pc_compute`` 는 ``app_id`` 로 id) ·
C7(수집기 원시 모양 — teams ``is_me=null → direction unknown``·``participants=[{name}]``·``chat_title=null``, mail A단·OMG
행 ``rcv=unknown``·``in_reply_to`` bool, pc_file 원시 힌트 ``folder_role·root_id·op=save·target_mtime·pdf_sibling``·
``flags.autosave·final_name``, 무텍스트 ``pc.events``·라이선스) · C11(``redact_row``·``redact_fields`` — '_masked 로
끝나는 열' 규칙 폐기) · C15(``pc_session``(pc.sampler)의 ``dir_keys`` — 원시 ``fg_doc_path`` 의 상위 폴더 1~2단).

``act_cues`` 는 정규화 패키지의 훅 ``lm27.normalize.cues.extract(text)``(WP-18, 에이전트 사본 포함)를 부른다. 그 모듈이
트리에 아직 없으면 단서는 비운다(import 오류를 삼키지 않는다 — 모듈 존재를 ``find_spec`` 으로 본다).

감사: 행마다 결과를 ``rc.audit`` 에 스스로 센다(``AuditSink._note_outcome`` — 버림 사유·가린 범주·공사·광고, I9).
이 모듈은 에이전트 bin 사본에도 들어간다(표준 라이브러리 + 사본 안 모듈).
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import importlib.util
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from lm27.util import fsx

from . import keys as K
from .classify import (
    AD_WHY,
    TITLE_KEEP_CLASSES,
    WindowContext,
    abs_hint,
    ad_score_adjusted,
    adlike_localpart,
    body_unsub,
    header_flags,
    priv_why_codes,
    private_score,
    private_score_adjusted,
    room_prior,
)
from .classify import RoomStat as RoomStat
from .classify import window_class as _window_class
from .detect import SanitizeContext, _dict_rx, norm_person, sanitize
from .rules import COMPOUND_SURNAMES, NAME_STOP, RULES_VERSION

__all__ = [
    "ACT_CUES", "COPILOT_SRCS", "KINDS", "SCHEMAS", "SRCS_BY_KIND",
    "KindSpec", "RecordContext", "RecordOutcome", "RoomStat", "SanitizedRow", "WorkWindow",
    "check_row", "dict_name", "path_excluded", "record_id", "redact_fields", "redact_row", "remask_persons",
    "resanitize_row", "row_dict",
    "sanitize_record", "validate_columns",
]

# ───────────────────────────── 어휘 ─────────────────────────────
KINDS = ("mail", "cal", "teams", "pc_session", "pc_file", "pc_git", "pc_compute", "manual")
SRCS_BY_KIND = MappingProxyType({                       # 계약 §6.5 경로 ID 21종
    "mail": ("mail.com", "mail.index", "mail.owa", "mail.import", "mail.copilot"),
    "cal": ("cal.com", "cal.index", "cal.owa", "cal.import", "cal.copilot"),
    "teams": ("teams.uia", "teams.web", "teams.copilot"),
    "pc_session": ("pc.sampler", "pc.events"),
    "pc_file": ("pc.files", "pc.mru", "pc.recent"),
    "pc_git": ("pc.git",),
    "pc_compute": ("pc.compute",),
    "manual": ("manual",),
})
COPILOT_SRCS = frozenset({"mail.copilot", "cal.copilot", "teams.copilot"})
ACT_CUES = ("req", "rep", "done", "ack", "ask", "sched", "cancel", "fyi")
TS_PRECISIONS = ("exact", "minute", "date", "summary", "unknown")
PRIV_CLASSES = ("work", "unknown", "media", "private", "social")
PRIV_WHY_ALL = ("explicit", "strong", "weak", "social", "work", "ack", "reg_token", "one_to_one", "group_meeting",
                "offhours", "room_private", "room_work", "personal_mail", "app", "site", "profile", "inprivate", "media")
BOXES = ("inbox", "sent", "other")
MAIL_FOLDER_ROLES = ("inbox", "sent", "junk", "deleted", "archive", "subfolder", "other")
FILE_FOLDER_ROLES = ("desktop", "documents", "downloads", "onedrive", "sharepoint", "root", "other")
RCV = ("to", "cc", "bulk", "na", "unknown")
ABS_HINTS = ("half_am", "half_pm", "half", "leave", "sick", "early", "out", "trip", "none")
BUSY = ("free", "tentative", "busy", "oof", "elsewhere")
LOCATION_CLASSES = ("online", "room", "external", "none")
CHAT_TYPES = ("1:1", "group", "channel", "meeting", "self")
APP_CLASSES = ("office", "cad", "sim", "eda", "ide", "pdf", "viewer", "browser", "chat_work", "mail_work",
               "messenger_private", "media", "game", "system", "idle", "other", "remote", "meeting")
SITE_CLASSES = ("app", "inprivate", "profile", "site", "work_site", "other")
SESSION_STATES = ("active", "locked", "disconnected", "remote")
LAYERS = ("L0", "L1", "L2", "L3")
EVENT_CLASSES = ("boot", "shutdown", "sleep", "wake", "logon", "logoff", "lock", "unlock", "rdp_connect",
                 "rdp_disconnect", "crash")
FILE_OPS = ("create", "modify", "open", "save")
SIZE_BUCKETS = ("<100KB", "100KB-1MB", "1-4MB", "4-16MB", "16-64MB", ">64MB")
MAN_KINDS = ("work", "offsite", "instr", "report", "absence", "exclude", "attended", "must_link", "cannot_link",
             "retract")
AD_BANDS = ("keep", "suspect")

# ───────────────────────────── 형식 ─────────────────────────────
HEX16_RX = re.compile(r"^[0-9a-f]{16}$")
PC_RX = re.compile(r"^pcx?_[0-9a-f]{16}$")
SRC_RX = re.compile(r"^(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)$")
UTC_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OFF_RX = re.compile(r"^[+-](?:0\d|1[0-4]):[0-5]\d$")
VER_RX = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,3}$")
KID_RX = re.compile(r"^k[0-9a-f]{8}$")
APP_ID_RX = re.compile(r"^[a-z0-9_.:\-]{1,48}$")
FG_EXE_RX = re.compile(r"^[a-z0-9_.\-]{1,64}\.exe$")
EXT_RX = re.compile(r"^\.[0-9a-z]{1,5}$")
ROOT_ID_RX = re.compile(r"^R\d{2}$")
REG_ID_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,15}$")
VOCAB_RX = re.compile(r"^[0-9A-Za-z가-힣_]{1,20}$")
CATEGORY_RX = re.compile(r"^[0-9A-Za-z가-힣_ \-]{1,20}$")
SENDER_LABEL_RX = re.compile(r"^(?:사내|개인메일|미상|고객사:[A-Za-z0-9_\-]{1,16}|협력사:[A-Za-z0-9_\-]{1,16}|[a-z0-9.\-]{3,80})$")
REF_KEY_RX = re.compile(r"^(?:[me][0-9a-f]{24}|[dh][0-9a-f]{16})$")
SAN_CODE_RX = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
_CTRL_RX = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SURR_RX = re.compile("[\ud800-\udfff]")          # UTF-16 서로게이트 코드 포인트(파이썬 str 에 남은 것 — 외톨이 판정용)
_UTC_IN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?\s*(Z|[+-]\d{2}:?\d{2})?$")
_DATE_IN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_PREFIX_RX = re.compile(r"^\s*(?:re|fw|fwd|회신|전달|답장)\s*[:：]\s*", re.I)
_EMAIL_RX = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24})$")
_URL_RX = re.compile(r"(?i)^[a-z][a-z0-9+.\-]{1,15}://")
_PERSON_TAG = re.compile(r"\[사람#[0-9a-f]{6}\]")
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")

# 팀즈 '놓친 활동' 알림 메일(D-15 · X-133) — 표식만(시간 근거 해석은 시간 코어). 광고 점수를 매기지 않는다(존재 증거 보존).
TEAMS_NOTICE_DOMAINS = ("teams.microsoft.com",)
TEAMS_NOTICE_SUBJECT = re.compile(r"(?i)(?:microsoft\s?teams|놓친\s?(?:활동|메시지|대화)|missed\s+(?:activity|messages?|chats?))")
ONLINE_LOC_RX = re.compile(r"(?i)(?:teams|zoom|webex|google\s?meet|skype|https?://|온라인|화상)")
ROOM_LOC_RX = re.compile(r"(?i)(?:회의실|미팅룸|세미나실|강당|대회의|소회의|room|conference|meeting|\d{1,2}\s?층|\b[A-Z]?\d{2,4}호)")
PATH_ONLY_TOKENS = frozenset({"temp", "downloads", "임시", "다운로드"})

FORBIDDEN_RAW_ALL = frozenset({"username", "computername", "machine_guid"})
COMPUTED_FLAGS = frozenset({"private", "ad", "no_key"})
CONF_DEFAULT = 1.0
CONF_COPILOT = 0.3
CONF_COPILOT_MAX = 0.4


# ───────────────────────────── 열 허용 목록 ─────────────────────────────
COMMON_COLUMNS = frozenset({
    "id", "kind", "src", "pc_id", "ts_utc", "ts_local_offset", "ts_precision", "ts_end", "direction", "act",
    "act_cues", "thread_key", "chat_key", "counterpart_keys", "n_participants", "doc_key", "app_id", "attach_keys",
    "flags", "confidence", "observed_at", "rules_ver", "kid", "san", "priv_score", "priv_class", "priv_why"})
COMMON_REQUIRED = frozenset({"id", "kind", "src", "pc_id", "ts_utc", "ts_local_offset", "ts_precision", "act",
                             "observed_at", "rules_ver", "kid", "priv_class", "confidence"})


@dataclass(frozen=True)
class KindSpec:
    """kind 하나의 열 허용 목록(P §10.1·§10.2 + 계약 §3.2). ``text_fields`` = 정제문 열 → (원시 원천, 최대 글자, 목록 상한)
    — 순서가 레코드 id 의 '정제문 연결' 순서다. ``schemas_v1.json`` 은 ``selftest.schema_snapshot(SCHEMAS)`` 의 정규 바이트."""
    kind: str
    columns: frozenset
    text_fields: MappingProxyType
    flag_keys: frozenset
    required: frozenset
    keys_required: bool
    forbidden_raw: frozenset = frozenset()


def _spec(kind, extra, text_fields, flag_keys, required, keys_required, forbidden_raw=()):
    return KindSpec(kind=kind, columns=frozenset(COMMON_COLUMNS | set(extra) | set(text_fields)),
                    text_fields=MappingProxyType(dict(text_fields)), flag_keys=frozenset(flag_keys),
                    required=frozenset(COMMON_REQUIRED | set(required)), keys_required=keys_required,
                    forbidden_raw=frozenset(forbidden_raw))


SCHEMAS = MappingProxyType({
    "mail": _spec(
        "mail",
        ("msg_key", "box", "folder_role", "sender_key", "sender_label", "n_to", "n_cc", "rcv", "attach_exts",
         "importance", "is_reply", "refw_depth", "focused_other", "ad_score", "ad_band", "ad_why", "ad_partial",
         "abs_hint", "replied", "i_sent_in_conv"),
        {"subject_masked": ("subject", 120, None), "attach_names_masked": ("attach_names", 80, 5),
         "categories_masked": ("categories", 30, 3), "text_masked": ("copilot_text", 200, None)},
        ("has_file", "list_unsub", "precedence", "esp", "body_unsub", "bulk", "cc", "sensitivity", "cat_private", "ad",
         "private", "meeting_response", "cap_hit", "utc_suspect", "deferred", "teams_notice"),
        ("msg_key", "box", "folder_role"), True),
    "cal": _spec(
        "cal",
        ("msg_key", "busy", "location_class", "abs_hint"),
        {"subject_masked": ("subject", 120, None), "categories_masked": ("categories", 30, 3),
         "text_masked": ("copilot_text", 200, None)},
        ("sensitivity", "cat_private", "private", "recurring", "all_day", "online_meeting", "organizer_me",
         "recurrence_incomplete", "response", "meeting_status", "cap_hit", "utc_suspect"),
        ("msg_key", "ts_end"), True),
    "teams": _spec(
        "teams",
        ("msg_key", "chat_type", "author_key", "file_keys", "priv_score_base", "abs_hint"),
        {"body_masked": ("body_text", 300, None), "file_names_masked": ("file_names", 80, 5),
         "chat_title_masked": ("chat_title", 60, None), "text_masked": ("copilot_text", 200, None)},
        ("mentions_me", "has_file", "private", "cap_hit", "utc_suspect", "n_part_est", "author_inherited"),
        ("msg_key", "chat_key", "chat_type"), True),
    "pc_session": _spec(
        "pc_session",
        ("fg_exe", "app_class", "site_class", "session_state", "idle_sec", "layer", "event_class", "dir_keys"),
        {"title_masked": ("fg_title", 120, None)},
        ("end_uncertain", "stuck", "always_on", "remote", "utc_suspect", "no_key", "inprivate"),
        ("session_state", "layer", "ts_end"), False,
        ("message", "user", "computer")),
    "pc_file": _spec(
        "pc_file",
        ("path_key", "ext", "folder_role", "root_id", "op", "size_bucket", "ooxml_totaltime", "ooxml_revision",
         "dir_keys"),
        {"name_masked": ("path", 80, None)},
        ("view_only", "edit", "author_other", "pdf_export", "final_name", "has_file", "no_key", "autosave"),
        ("op",), False),
    "pc_git": _spec(
        "pc_git",
        ("commit_key", "n_commits", "n_files", "exts"),
        {"msg_masked": ("subject", 120, None)},
        ("cap_hit",),
        ("commit_key", "n_commits", "doc_key"), True,
        ("author", "author_name", "author_email", "email")),
    "pc_compute": _spec(
        "pc_compute",
        ("cpu_core",),
        {},
        ("solver", "license", "end_uncertain"),
        ("ts_end", "app_id"), False,
        ("user", "host", "server")),
    "manual": _spec(
        "manual",
        ("work_category", "hours", "project_id", "role_field", "role_func", "man_kind", "ref_keys", "retract_of"),
        {"text_masked": ("note", 200, None)},
        (),
        ("work_category", "man_kind"), False),
})


# ───────────────────────────── 열 검증(I12) ─────────────────────────────
def _isint(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _v_rx(rx):
    return lambda v, k: isinstance(v, str) and rx.fullmatch(v) is not None


def _v_enum(vals):
    s = frozenset(vals)
    return lambda v, k: isinstance(v, str) and v in s


def _v_int(a, b):
    return lambda v, k: _isint(v) and a <= v <= b


def _v_float(a, b):
    return lambda v, k: _isnum(v) and a <= v <= b


def _v_bool(v, k):
    return isinstance(v, bool)


def _v_list(item, n):
    return lambda v, k: isinstance(v, (list, tuple)) and len(v) <= n and all(item(x, k) for x in v)


def _v_text(n):
    return lambda v, k: isinstance(v, str) and len(v) <= n and _CTRL_RX.search(v) is None


def _v_opt(f):
    return lambda v, k: v is None or f(v, k)


def _v_counts(v, k):
    return isinstance(v, (dict, MappingProxyType)) and all(
        isinstance(c, str) and SAN_CODE_RX.match(c) and _isint(n) and n >= 0 for c, n in v.items())


def _v_direction(v, k):
    if k == "mail":
        return v in ("in", "out", "unknown")
    if k == "teams":
        return v in ("sent", "received", "unknown")
    return v is None


def _v_msg_key(v, k):
    rx = r"^e[0-9a-f]{24}$" if k == "cal" else r"^m[0-9a-f]{24}$"
    return isinstance(v, str) and re.fullmatch(rx, v) is not None


def _v_folder_role(v, k):
    return v in (MAIL_FOLDER_ROLES if k == "mail" else FILE_FOLDER_ROLES)


_FLAG_INT = {"sensitivity": (0, 3), "response": (0, 5), "meeting_status": (0, 7)}


def _v_flags(v, k):
    if not isinstance(v, (dict, MappingProxyType)):
        return False
    allowed = SCHEMAS[k].flag_keys
    for fk, fv in v.items():
        if fk not in allowed:
            return False
        if fk in _FLAG_INT and not (k == "pc_file" and fk == "has_file"):
            lo, hi = _FLAG_INT[fk]
            if not (_isint(fv) and lo <= fv <= hi):
                return False
        elif not isinstance(fv, bool):
            return False
    return True


def _v_key(prefix, n):
    return _v_rx(re.compile("^" + prefix + "[0-9a-f]{" + str(n) + "}$"))


def _v_party_key(v, k):
    return v == "self" or (isinstance(v, str) and re.fullmatch(r"^w[0-9a-f]{16}$", v) is not None)


VALIDATORS = MappingProxyType({
    "id": _v_rx(HEX16_RX), "kind": _v_enum(KINDS), "src": _v_rx(SRC_RX), "pc_id": _v_rx(PC_RX),
    "ts_utc": _v_rx(UTC_RX), "ts_local_offset": _v_rx(OFF_RX), "ts_precision": _v_enum(TS_PRECISIONS),
    "ts_end": _v_opt(_v_rx(UTC_RX)), "direction": _v_direction, "act": lambda v, k: v == "",
    "act_cues": _v_list(_v_enum(ACT_CUES), 8), "thread_key": _v_opt(_v_key("t", 16)),
    "chat_key": _v_opt(_v_key("h", 16)), "counterpart_keys": _v_list(_v_key("w", 16), 20),
    "n_participants": _v_opt(_v_int(0, 10000)), "doc_key": _v_opt(_v_rx(re.compile(r"^[dr][0-9a-f]{16}$"))),
    "app_id": _v_opt(_v_rx(APP_ID_RX)), "attach_keys": _v_list(_v_key("d", 16), 10), "flags": _v_flags,
    "confidence": _v_float(0.0, 1.0), "observed_at": _v_rx(UTC_RX), "rules_ver": _v_rx(VER_RX),
    "kid": _v_rx(KID_RX), "san": _v_counts, "priv_score": _v_opt(_v_int(-50, 50)), "priv_class": _v_enum(PRIV_CLASSES),
    "priv_why": _v_list(_v_enum(PRIV_WHY_ALL), 8),
    # mail
    "msg_key": _v_msg_key, "box": _v_enum(BOXES), "folder_role": _v_folder_role, "sender_key": _v_opt(_v_party_key),
    "sender_label": _v_opt(_v_rx(SENDER_LABEL_RX)), "n_to": _v_opt(_v_int(0, 10000)), "n_cc": _v_opt(_v_int(0, 10000)),
    "rcv": _v_opt(_v_enum(RCV)), "subject_masked": _v_text(120), "attach_names_masked": _v_list(_v_text(80), 5),
    "attach_exts": _v_list(_v_rx(EXT_RX), 10), "categories_masked": _v_list(_v_text(30), 3),
    "importance": _v_opt(_v_int(0, 2)), "is_reply": _v_opt(_v_bool), "refw_depth": _v_opt(_v_int(0, 9)),
    "focused_other": _v_opt(_v_bool), "ad_score": _v_opt(_v_int(-20, 20)), "ad_band": _v_opt(_v_enum(AD_BANDS)),
    "ad_why": _v_list(_v_enum(AD_WHY), 10), "ad_partial": _v_opt(_v_bool), "abs_hint": _v_opt(_v_enum(ABS_HINTS)),
    "replied": _v_opt(_v_bool), "i_sent_in_conv": _v_opt(_v_bool), "text_masked": _v_text(200),
    # cal
    "busy": _v_opt(_v_enum(BUSY)), "location_class": _v_opt(_v_enum(LOCATION_CLASSES)),
    # teams
    "chat_type": _v_enum(CHAT_TYPES), "author_key": _v_opt(_v_party_key), "file_names_masked": _v_list(_v_text(80), 5),
    "file_keys": _v_list(_v_key("d", 16), 10), "body_masked": _v_text(300), "chat_title_masked": _v_text(60),
    "priv_score_base": _v_opt(_v_int(-50, 50)),
    # pc_session
    "fg_exe": _v_opt(_v_rx(FG_EXE_RX)), "app_class": _v_enum(APP_CLASSES), "title_masked": _v_text(120),
    "site_class": _v_opt(_v_enum(SITE_CLASSES)), "session_state": _v_enum(SESSION_STATES),
    "idle_sec": _v_opt(_v_int(0, 4294968)), "layer": _v_enum(LAYERS), "event_class": _v_opt(_v_enum(EVENT_CLASSES)),
    "dir_keys": _v_list(_v_key("s", 16), 3),
    # pc_file
    "path_key": _v_opt(_v_key("f", 16)), "name_masked": _v_text(80), "ext": _v_opt(_v_rx(EXT_RX)),
    "root_id": _v_opt(_v_rx(ROOT_ID_RX)), "op": _v_enum(FILE_OPS), "size_bucket": _v_opt(_v_enum(SIZE_BUCKETS)),
    "ooxml_totaltime": _v_opt(_v_int(0, 100000)), "ooxml_revision": _v_opt(_v_int(0, 100000)),
    # pc_git
    "commit_key": _v_key("g", 16), "msg_masked": _v_text(120), "n_commits": _v_int(1, 10000),
    "n_files": _v_opt(_v_int(0, 100000)), "exts": _v_list(_v_rx(EXT_RX), 10),
    # pc_compute
    "cpu_core": _v_opt(_v_float(0.0, 256.0)),
    # manual
    "work_category": _v_rx(CATEGORY_RX), "hours": _v_opt(_v_float(0.0, 24.0)), "project_id": _v_opt(_v_rx(REG_ID_RX)),
    "role_field": _v_opt(_v_rx(VOCAB_RX)), "role_func": _v_opt(_v_rx(VOCAB_RX)), "man_kind": _v_enum(MAN_KINDS),
    "ref_keys": _v_list(_v_rx(REF_KEY_RX), 5), "retract_of": _v_opt(_v_rx(HEX16_RX)),
})


def validate_columns(kind: str, row) -> list:
    """행(dict·Mapping)의 열 검증 위반 열 이름 목록(빈 목록 = 통과). 허용 밖 열·필수 열 누락·형식 위반(I12).
    위반 목록에는 열 이름만(값 없음)."""
    spec = SCHEMAS[kind]
    bad = sorted(c for c in row if c not in spec.columns)
    bad += sorted(c for c in spec.required if c not in row or row.get(c) is None)
    for c in sorted(row):
        if c in spec.columns and c not in bad:
            f = VALIDATORS.get(c)
            if f is None or not f(row[c], kind):
                bad.append(c)
    if row.get("kind") != kind:
        bad.append("kind")
    elif row.get("src") not in SRCS_BY_KIND[kind]:
        bad.append("src")
    return list(dict.fromkeys(bad))


# ───────────────────────────── 봉인 행 ─────────────────────────────
_SEAL = object()


def _freeze(v):
    if isinstance(v, (dict, MappingProxyType)):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    return v


def _thaw(v):
    if isinstance(v, (dict, MappingProxyType)):
        return {k: _thaw(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_thaw(x) for x in v]
    return v


class SanitizedRow:
    """정제 통과 행(봉인). 생성자는 이 모듈 안 전용(``_SEAL`` 확인) — 수집기가 직접 만들 수 없다(I2·L-11).
    ``data`` 는 읽기 전용(MappingProxyType·튜플). 복제·변경 수단은 모두 TypeError."""
    __slots__ = ("kind", "data", "_seal")

    def __init__(self, kind: str, data, seal):
        if seal is not _SEAL:
            raise TypeError("SanitizedRow 는 sanitize_record() 만 만든다")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "data", _freeze(data))
        object.__setattr__(self, "_seal", seal)

    def __setattr__(self, name, value):
        raise TypeError("봉인 행은 바꿀 수 없다")

    def __delattr__(self, name):
        raise TypeError("봉인 행은 바꿀 수 없다")

    def __replace__(self, **changes):
        raise TypeError("봉인 행은 복제·변경할 수 없다")

    def __copy__(self):
        raise TypeError("봉인 행은 복제할 수 없다")

    def __deepcopy__(self, memo):
        raise TypeError("봉인 행은 복제할 수 없다")

    def __reduce_ex__(self, protocol):
        raise TypeError("봉인 행은 직렬화로 복제할 수 없다")

    def __repr__(self) -> str:
        return f"SanitizedRow(kind={self.kind!r}, id={self.data.get('id')!r})"

    def to_dict(self) -> dict:
        """쓰기·시험용 일반 dict 사본(봉인 밖 — 바꿔도 이 행은 그대로)."""
        return _thaw(self.data)


def row_dict(row: SanitizedRow) -> dict:
    """봉인 행의 dict 사본(저장 직렬화용)."""
    return row.to_dict()


def check_row(row) -> None:
    """저장 지점의 봉인·열 재검증(``SegmentWriter.append`` — 계약 §2.3). 봉인이 아니면 TypeError, 열 위반이면 ValueError
    (위반 열 이름만)."""
    if not isinstance(row, SanitizedRow) or getattr(row, "_seal", None) is not _SEAL:
        raise TypeError("SanitizedRow 만 저장할 수 있다(sanitize_record 통과 행)")
    bad = validate_columns(row.kind, row.data)
    if bad:
        raise ValueError("열 검증 실패: " + ",".join(bad[:5]))


@dataclass(frozen=True)
class RecordOutcome:
    """``status`` ∈ stored·dropped·error. dropped 사유: cred·ad·private_folder·folder_excluded·bad_raw·no_key,
    error 사유: 예외 유형명(열 위반은 ``ColumnViolation``). ``hits`` = 범주별 가린 건수."""
    status: str
    row: SanitizedRow | None
    reason: str | None
    hits: dict

    def as_pair(self) -> tuple:
        """수집 공통 명세 §11 의 2-튜플 표기 ``(record | None, audit)`` 호환. audit 에는 status·reason·hits 만."""
        return (self.row.to_dict() if self.status == "stored" and self.row is not None else None,
                {"status": self.status, "reason": self.reason, "hits": dict(self.hits)})


# ───────────────────────────── 문맥 ─────────────────────────────
@dataclass(frozen=True)
class WorkWindow:
    """근무창(표준창·평일·휴일) — 공사 판정의 offhours(평일 표준창 밖·주말·공휴일) 판정용(P §12.1)."""
    start_min: int = 9 * 60
    end_min: int = 18 * 60
    weekdays: frozenset = frozenset({0, 1, 2, 3, 4})
    holidays: frozenset = frozenset()

    def offhours(self, ts_utc: str, off_min: int) -> bool:
        lt = _parse_utc_dt(ts_utc) + timedelta(minutes=off_min)
        if lt.weekday() not in self.weekdays or lt.date().isoformat() in self.holidays:
            return True
        m = lt.hour * 60 + lt.minute
        if self.start_min <= self.end_min:
            return not (self.start_min <= m < self.end_min)
        return not (m >= self.start_min or m < self.end_min)


@dataclass
class RecordContext:
    """수집 실행 1회 단위 문맥(P §3.2) — ``lm27.privacy.context.make_record_context()`` 가 만든다.
    ``keyring`` = Keyring(프로그램 폴더)·AgentKeys(에이전트)·NoKeys(키 없음 모드). ``my_addrs`` 는 메모리 전용."""
    pc_id: str
    src: str
    sctx: SanitizeContext
    keyring: object
    my_addrs: frozenset = frozenset()
    corresp_domains: set = field(default_factory=set)
    ad_lists: dict = field(default_factory=dict)
    private_chats: set = field(default_factory=set)
    room_stats: dict = field(default_factory=dict)
    work_window: WorkWindow | None = None
    off_min: int = 540
    audit: object = None
    no_key: bool = False
    wctx: WindowContext | None = None
    path_exclude: tuple = ("개인", "가족", "사진", "private", "personal")
    private_categories: tuple = ("개인", "Personal", "Private", "가족")
    ad_extra_words: tuple = ()
    private_extra_words: tuple = ()
    private_extra_work_words: tuple = ()
    final_words: tuple = ()
    stage: str = "collect"
    mode: str = "program"
    sent_threads: set = field(default_factory=set)
    people: dict = field(default_factory=dict)          # who_key → {names, smtp, self, internal, first, last} (메모리)
    corresp_new: dict = field(default_factory=dict)     # 도메인 → 마지막 발신일(이번 실행에서 본 것, 메모리)
    on_commit: object = None                            # 로컬 사전 갱신 저장 함수(context 가 붙인다)

    def __post_init__(self):
        self.my_addrs = frozenset(str(a).strip().lower() for a in (self.my_addrs or ()) if str(a).strip())
        self.self_norms = frozenset(x for x in (_name_norm(n) for n in (self.sctx.self_names or ())) if x)
        self._internal = tuple(str(d).lower() for d in (self.sctx.internal_domains or ()))
        self._personal = frozenset(str(d).lower() for d in (self.sctx.personal_mail_domains or ()))
        self._cat_private = frozenset(str(c).strip().casefold() for c in self.private_categories if str(c).strip())

    def add_my_addrs(self, addrs) -> None:
        """파이프 첫 줄 ``_meta.my_addrs``(메모리 전용). 본인 도메인은 사내 도메인으로 런타임에 더한다(P §17.2)."""
        new = {str(a).strip().lower() for a in (addrs or ()) if isinstance(a, str) and _EMAIL_RX.match(a.strip())}
        if not new:
            return
        self.my_addrs = frozenset(self.my_addrs | new)
        doms = [a.rsplit("@", 1)[1] for a in sorted(new)]
        extra = [d for d in doms if d not in self._internal]
        if extra:
            self._internal = tuple(dict.fromkeys((*self._internal, *extra)))

    def offhours(self, ts_utc: str) -> bool:
        return bool(self.work_window and self.work_window.offhours(ts_utc, self.off_min))

    def commit_local(self) -> int:
        """이번 실행에서 배운 사람 사전·왕래 도메인을 로컬 전용 파일에 합친다(P §9.6·§11.3). 저장한 항목 수."""
        if self.on_commit is None or not (self.people or self.corresp_new):
            return 0
        return int(self.on_commit(self) or 0)


# ───────────────────────────── 작은 도구 ─────────────────────────────
def _s(v) -> str:
    """원시 문자열 필드(아니면 ""). 앞뒤 공백 제거."""
    return v.strip() if isinstance(v, str) else ""


def _has_surr(v) -> bool:
    if isinstance(v, str):
        return _SURR_RX.search(v) is not None
    if isinstance(v, dict):
        return any(_has_surr(k) or _has_surr(x) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return any(_has_surr(x) for x in v)
    return False


def _fix_surr(v):
    """외톨이 서로게이트 → U+FFFD(짝이 맞는 둘은 한 글자로 합친다). 페이지 JS 의 UTF-16 자르기(``.slice(0,n)``)가 이모지를
    반으로 자르면 CDP JSON(ensure_ascii 이스케이프)이 외톨이 하나를 넘긴다 — 그대로 두면 키·id 를 만들 때
    UnicodeEncodeError 로 행 전체가 error 가 되고(방 제목이면 그 방 메시지 전부) 수집기는 커서를 진전시킨다(영구 누락)."""
    if isinstance(v, str):
        return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace") if _SURR_RX.search(v) else v
    if isinstance(v, dict):
        return {_fix_surr(k): _fix_surr(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_fix_surr(x) for x in v)
    return v


def dict_name(n, self_low=frozenset()) -> str | None:
    """사람 사전(표시명 → who_key)에 넣을 이름(P §9.6 — ``context._persons`` 와 같은 규칙): NFKC·앞뒤 공백 제거, 40자 이하,
    정규화 핵심(norm_person) 2자 이상, 복성만(남궁…)·일반어(NAME_STOP)·본인 이름(``self_low`` 소문자)·이메일 모양 제외.
    통과하면 그 이름, 아니면 None."""
    n2 = unicodedata.normalize("NFKC", str(n or "")).strip()
    if not n2 or len(n2) > 40 or _EMAIL_RX.match(n2):
        return None
    core = norm_person(n2)
    if len(core) <= 1 or core in COMPOUND_SURNAMES or n2 in NAME_STOP or n2.lower() in self_low:
        return None
    return n2


def _name_norm(n) -> str:
    """본인 이름 비교용 정규화: norm_person(NFKC·소문자·괄호·호칭 꼬리·구분자 제거) 뒤 '님'·'씨' 꼬리 제거."""
    x = norm_person(str(n or ""))
    return re.sub(r"(?:님|씨)$", "", x)


def _parse_utc_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _utc(v) -> str | None:
    """원시 시각 → ``YYYY-MM-DDTHH:MM:SSZ``(오프셋이 있으면 UTC 로 환산, 없으면 UTC 로 본다). 형식 밖이면 None."""
    if not isinstance(v, str):
        return None
    m = _UTC_IN.match(v.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, tz = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz != "Z":
        sign = -1 if tz[0] == "-" else 1
        t = tz[1:].replace(":", "")
        off = sign * (int(t[:2]) * 60 + int(t[2:]))
        if abs(off) > 14 * 60:
            return None
        dt = dt - timedelta(minutes=off)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_off(v) -> tuple[str, int] | None:
    """원시 오프셋(``+09:00`` 또는 정수 분) → (문자열, 분). 형식 밖이면 None."""
    if _isint(v) and abs(v) <= 14 * 60:
        h, m = divmod(abs(v), 60)
        return f"{'-' if v < 0 else '+'}{h:02d}:{m:02d}", v
    if isinstance(v, str) and OFF_RX.match(v.strip()):
        t = v.strip()
        mins = int(t[1:3]) * 60 + int(t[4:6])
        return t, -mins if t[0] == "-" else mins
    return None


def _local(ts_utc: str, off_min: int) -> datetime:
    return _parse_utc_dt(ts_utc) + timedelta(minutes=off_min)


def _minute(ts_utc: str) -> str:
    return ts_utc[:16]


def _norm_text(t: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", t or "").split())


def _norm_subject(subj: str) -> str:
    """대화 제목 정규화(P §9.3 thread 재료): RE·FW 접두 반복 제거·공백 축약·소문자."""
    s = _norm_text(subj)
    for _ in range(10):
        t = _PREFIX_RX.sub("", s)
        if t == s:
            break
        s = t
    return s.lower()


def _prefix_depth(subj: str) -> int:
    s, n = unicodedata.normalize("NFKC", subj or ""), 0
    for _ in range(9):
        t = _PREFIX_RX.sub("", s, count=1)
        if t == s:
            break
        s, n = t, n + 1
    return n


def _domain(addr: str | None) -> str:
    return addr.rsplit("@", 1)[1].lower() if addr and "@" in addr else ""


def _dom_in(dom: str, doms) -> bool:
    return bool(dom) and any(dom == d or dom.endswith("." + d) for d in doms)


def _addr(v) -> str | None:
    a = _s(v).strip("<>").strip()
    return a.lower() if a and _EMAIL_RX.match(a) else None


def _party(x) -> tuple[str | None, str]:
    """원시 사람 표기(``{addr, name}`` 또는 문자열) → (주소|None, 표시명)."""
    if isinstance(x, dict):
        return _addr(x.get("addr") or x.get("address")), _s(x.get("name"))[:120]
    if isinstance(x, str):
        a = _addr(x)
        return (a, "") if a else (None, _s(x)[:120])
    return None, ""


def _parties(v) -> list:
    if v is None:
        return []
    if isinstance(v, (dict, str)):
        v = [v]
    if not isinstance(v, (list, tuple)):
        raise _Drop("bad_raw")
    return [p for p in (_party(x) for x in v[:10000]) if p[0] or p[1]]


def _strlist(v, cap: int) -> list:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        raise _Drop("bad_raw")
    return [x for x in v if isinstance(x, str) and x.strip()][:cap]


def _bool(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "1", "yes"))


def _int_or_none(v, lo, hi):
    if _isint(v) and lo <= v <= hi:
        return v
    if isinstance(v, float) and v.is_integer() and lo <= v <= hi:
        return int(v)
    return None


def _keep_int(v, lo, hi):
    """범위 안 정수면 그 정수, None 이면 None, 그 밖이면 원래 값 — 열 검증(I12)이 잡아 error(ColumnViolation) 로 낸다."""
    if v is None:
        return None
    iv = _int_or_none(v, lo, hi)
    return iv if iv is not None else v


def _merge(acc: dict, hits: dict) -> None:
    for k, v in (hits or {}).items():
        acc[k] = acc.get(k, 0) + v


def _plain_person(v):
    if isinstance(v, list):
        return [_plain_person(x) for x in v]
    return _PERSON_TAG.sub("[사람]", v or "")


def _ext_of(name: str) -> str | None:
    b = name.rsplit(".", 1)
    if len(b) == 2:
        e = "." + unicodedata.normalize("NFKC", b[1]).lower().strip()
        if EXT_RX.match(e):
            return e
    return None


def _size_bucket(n) -> str | None:
    if not _isnum(n) or n < 0:
        return None
    for lim, name in ((100_000, "<100KB"), (1_000_000, "100KB-1MB"), (4_000_000, "1-4MB"), (16_000_000, "4-16MB"),
                      (64_000_000, "16-64MB")):
        if n < lim:
            return name
    return ">64MB"


_CUES_FN: object = None


def _cues_fn():
    """``lm27.normalize.cues.extract``(WP-18 — 에이전트 사본 포함). 모듈 파일이 아직 없으면 None(단서 없음)."""
    global _CUES_FN
    if _CUES_FN is None:
        if importlib.util.find_spec("lm27.normalize.cues") is None:
            _CUES_FN = False
        else:
            _CUES_FN = importlib.import_module("lm27.normalize.cues").extract
    return _CUES_FN or None


def _cues(text: str) -> list:
    fn = _cues_fn()
    if fn is None or not text:
        return []
    out = fn(text) or ()
    return sorted({c for c in out if c in ACT_CUES}, key=ACT_CUES.index)[:8]


class _Drop(Exception):
    """행 폐기(사유 코드·가린 건수)."""

    def __init__(self, reason: str, hits: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.hits = hits or {}


# ───────────────────────────── 사적 폴더(P §10.4) ─────────────────────────────
def path_excluded(path, rc) -> bool:
    """파일·git 수집 경로 전용 사적 폴더 제외(P §10.4) — 폴더 부분만 본다(파일 이름은 텍스트 필터로 쓰지 않는다).
    경로 전용 토큰(temp·downloads·임시·다운로드)은 폴더명 완전 일치, ASCII 키워드는 단어 경계, 한글 키워드는 부분 일치.
    ``rc`` = RecordContext(``path_exclude``) 또는 키워드 목록."""
    kws = rc.path_exclude if isinstance(rc, RecordContext) else tuple(rc or ())
    p = unicodedata.normalize("NFKC", str(path or ""))
    if _URL_RX.match(p):
        p = unquote(urlsplit(p).path or "")
    segs = [x for x in re.split(r"[\\/]+", p) if x][:-1]
    if not segs or not kws:
        return False
    low = [s.lower() for s in segs]
    for kw in kws:
        k = unicodedata.normalize("NFKC", str(kw or "")).strip().lower()
        if not k:
            continue
        if k in PATH_ONLY_TOKENS:
            if k in low:
                return True
        elif k.isascii():
            rx = re.compile(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])")
            if any(rx.search(s) for s in low):
                return True
        elif any(k in s for s in low):
            return True
    return False


# ───────────────────────────── 레코드 id(P §10.1 · 계약 §3.1 · C6) ─────────────────────────────
def record_id(row, spec: KindSpec | None = None) -> str:
    """``sha1(src|pc_id|ts_utc|주키|sha1(정제 텍스트 열을 \\x1f 로 이은 것))[:16]``. 주키 = msg_key → commit_key → path_key →
    doc_key 중 첫 값. 주키가 없으면 ``pc.events`` 는 ``<layer>|<event_class>``, ``pc_compute`` 는 ``app_id``(C6)."""
    spec = spec or SCHEMAS[row["kind"]]
    texts = []
    for col in spec.text_fields:
        v = row.get(col)
        if isinstance(v, (list, tuple)):
            texts.extend(str(x) for x in v)
        elif v:
            texts.append(str(v))
    th = hashlib.sha1("\x1f".join(texts).encode("utf-8")).hexdigest()
    primary = row.get("msg_key") or row.get("commit_key") or row.get("path_key") or row.get("doc_key") or ""
    if not primary:
        if row.get("kind") == "pc_session" and row.get("src") == "pc.events":
            primary = f"{row.get('layer') or ''}|{row.get('event_class') or ''}"
        elif row.get("kind") == "pc_compute":
            primary = row.get("app_id") or ""
    blob = "|".join((row["src"], row["pc_id"], row["ts_utc"], primary, th))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# ───────────────────────────── 조립기 ─────────────────────────────
class _Build:
    """원시 1건 → 행 조립(메모리). 원문은 self.raw 에만 있고 결과 행에는 정제문·키·열거·숫자만 간다."""

    def __init__(self, spec: KindSpec, rc: RecordContext):
        self.spec, self.rc, self.kind = spec, rc, spec.kind
        self.copilot = rc.src in COPILOT_SRCS
        self.row: dict = {}
        self.texts: dict = {}
        self.hits: dict = {}
        self.flags: dict = {}
        self.cues: list = []
        self.priv = ("work", None, [])            # (class, score, why)
        self.ad_band: str | None = None
        self.ad_partial = False
        self.no_key = False
        self.after: list = []                    # 저장 성공 뒤 문맥 갱신(같은 배치의 뒤 행이 쓴다)
        self.party_names: dict = {}              # 이 레코드 당사자 표시명 → 사람 키 16hex(글 정제 2차 — W1b)
        self._party_sctx = None

    # ── 키 ──
    def key(self, fn, material):
        """필수 키 — 키 없음이면 행 폐기(no_key)."""
        try:
            return fn(self.rc.keyring, material)
        except K.NoKeyError:
            raise _Drop("no_key") from None

    def key_opt(self, fn, material):
        """선택 키 — 키 없음이면 None + flags.no_key."""
        try:
            return fn(self.rc.keyring, material)
        except K.NoKeyError:
            self.no_key = True
            return None

    def who(self, addr, name):
        ident = K.person_ident(addr, name)
        return self.key_opt(K.who_key, ident) if ident else None

    # ── 텍스트 ──
    def parties_ctx(self, parties) -> None:
        """이 레코드 당사자(보낸·받는 사람·주최자·참석자·팀즈 작성자·참여자)의 표시명을 이 레코드 글 정제에 쓴다 — 첫 수집
        (빈 사람 사전)에서도 제목·본문·방 제목·파일 이름의 동료 실명이 원문으로 남지 않게(I1 · W1b). 이름 → 그 사람의
        who_key(주소가 있으면 smtp, 없으면 name — P §9.3). 본인·성만 이름·일반어·이미 사전에 있는 이름은 뺀다."""
        rc = self.rc
        self_low = {str(s).lower() for s in (rc.sctx.self_names or ())}
        base = rc.sctx.persons or {}
        extra: dict = {}
        for a, n in parties:
            if not n or self.is_self(a, n):
                continue
            nm = dict_name(n, self_low)
            if nm is None or nm in base or nm in extra or _name_norm(nm) in rc.self_norms:
                continue
            k = self.who(a, nm)
            extra[nm] = k[1:] if k else "0" * 16        # 키 없음 → 토큰은 마무리에서 [사람] 으로 강등(no_key)
        self.party_names = extra
        self._party_sctx = None

    def _remask_parties(self, r, col: str, max_len: int):
        """1차 정제문에 당사자 이름이 남았으면 그 이름만 든 사전으로 한 번 더 정제(기존 토큰은 보호 구간 — 멱등).
        큰 사람 사전 정규식을 레코드마다 다시 만들지 않으려고 작은 사전으로 2차를 돈다."""
        if not self.party_names or not r.text:
            return r
        low = r.text.casefold()
        if not any(n.casefold() in low for n in self.party_names):
            return r
        if self._party_sctx is None:
            self._party_sctx = dataclasses.replace(self.rc.sctx, persons=dict(self.party_names))
        r2 = sanitize(r.text, col, self._party_sctx, max_len)
        if r2.drop:
            return r
        hits = dict(r.hits)
        _merge(hits, r2.hits)
        return dataclasses.replace(r2, hits=hits)

    def text(self, col: str, value, max_len: int) -> str:
        v = value if isinstance(value, str) else ""
        if not v.strip():
            self.texts[col] = ""
            return ""
        r = sanitize(v, col, self.rc.sctx, max_len)
        if r.drop:
            raise _Drop("cred", {"cred": 1})
        r = self._remask_parties(r, col, max_len)
        _merge(self.hits, r.hits)
        self.texts[col] = r.text
        return r.text

    def textlist(self, col: str, values, max_len: int, cap: int) -> list:
        out = []
        for v in _strlist(values, cap):
            r = sanitize(v, col, self.rc.sctx, max_len)
            if r.drop:
                raise _Drop("cred", {"cred": 1})
            r = self._remask_parties(r, col, max_len)
            _merge(self.hits, r.hits)
            if r.text:
                out.append(r.text)
        self.texts[col] = out
        return out

    # ── 공통 원시 ──
    def common(self, raw: dict) -> dict:
        r = {k: v for k, v in raw.items() if isinstance(k, str) and not k.startswith("_")}
        if (FORBIDDEN_RAW_ALL | self.spec.forbidden_raw) & r.keys():
            raise _Drop("bad_raw")
        if r.get("act") not in (None, ""):
            raise _Drop("bad_raw")
        off = _parse_off(r.get("ts_local_offset"))
        if off is None:
            raise _Drop("bad_raw")
        self.off_s, self.off_min = off
        prec = r.get("ts_precision") or "minute"
        if prec not in TS_PRECISIONS:
            raise _Drop("bad_raw")
        if self.copilot and prec not in ("date", "summary"):
            prec = "date"
        obs = _utc(r.get("observed_at"))
        if obs is None:
            raise _Drop("bad_raw")
        conf = r.get("confidence", CONF_COPILOT if self.copilot else CONF_DEFAULT)
        if not _isnum(conf) or not 0.0 <= conf <= 1.0:
            raise _Drop("bad_raw")
        if self.copilot:
            conf = min(float(conf), CONF_COPILOT_MAX)
        self.row.update(kind=self.kind, src=self.rc.src, pc_id=self.rc.pc_id, ts_local_offset=self.off_s,
                        ts_precision=prec, observed_at=obs, confidence=float(conf), act="")
        fl = r.get("flags")
        if fl is not None and not isinstance(fl, dict):
            raise _Drop("bad_raw")
        for k, v in (fl or {}).items():
            if k in self.spec.flag_keys and k not in COMPUTED_FLAGS:
                if k in _FLAG_INT:
                    lo, hi = _FLAG_INT[k]
                    iv = _int_or_none(v, lo, hi)
                    if iv:
                        self.flags[k] = iv
                elif _bool(v):
                    self.flags[k] = True
        return r

    def ts(self, r: dict, name: str = "ts_utc") -> str:
        t = _utc(r.get(name))
        if t is None:
            raise _Drop("bad_raw")
        self.row["ts_utc"] = t
        return t

    def cp_material(self, r: dict, ts: str) -> str:
        """``*.copilot`` 증인 행 키 재료(계약 §4.2): ``cp:<src>|<DATE>|<sha256(canon_bytes(답 행))[:16]>``."""
        body = {k: v for k, v in r.items() if k not in ("observed_at", "confidence", "flags", "ts_local_offset")}
        h = hashlib.sha256(fsx.canon_bytes(body)).hexdigest()[:16]
        return f"cp:{self.rc.src}|{_local(ts, self.off_min).date().isoformat()}|{h}"

    def is_self(self, addr, name) -> bool:
        if addr and addr in self.rc.my_addrs:
            return True
        return bool(not addr and name and _name_norm(name) in self.rc.self_norms)

    def counterparts(self, parties) -> list:
        keys = set()
        for a, n in parties:
            if self.is_self(a, n):
                continue
            k = self.who(a, n)
            if k:
                keys.add(k)
        out = sorted(keys)
        if len(out) > 20:
            self.flags["cap_hit"] = True
        return out[:20]

    def learn(self, parties, when: str) -> None:
        """사람 사전 갱신 재료(P §9.6, 메모리). 저장은 ``rc.commit_local()``. 주소 없는 이름(팀즈·OWA 표시명)도 사전 규칙
        (``dict_name``)을 통과하면 이름 기반 키(``name:`` — P §9.3)로 배운다(W1b — 주소가 없다고 사전에 오르지 않으면 그 동료
        실명이 영영 가려지지 않는다). 배운 이름은 저장 성공 뒤 같은 실행의 다음 레코드부터 바로 쓴다(``_apply_after``)."""
        day = when[:10]
        self_low = {str(s).lower() for s in (self.rc.sctx.self_names or ())}
        for a, n in parties:
            if not a:
                n = dict_name(n, self_low)
                if n is None:
                    continue
            k = self.who(a, n)
            if not k:
                continue
            self.after.append(("person", k, a, n, day, self.is_self(a, n),
                               _dom_in(_domain(a), self.rc._internal)))

    def private(self, text: str, **kw) -> None:
        rc = self.rc
        s, cls, det = private_score_adjusted(text, extra_words=rc.private_extra_words,
                                             extra_work_words=rc.private_extra_work_words, **kw)
        why = priv_why_codes(det, text=text, chat_type=kw.get("chat_type", ""), offhours=kw.get("offhours", False),
                             room_prior=kw.get("room_prior", ""), personal_mail=kw.get("personal_mail", False))
        self.priv = (cls, max(-50, min(50, int(s))), why)

    # ── kind 별 ──
    def mail(self, r: dict) -> None:
        rc = self.rc
        ts = self.ts(r)
        if self.copilot:
            self.row.update(box="other", folder_role="other", direction="unknown")
            self.row["msg_key"] = self.key(K.msg_key, self.cp_material(r, ts))
            t = self.text("text_masked", r.get("copilot_text"), 200)
            self.private(t, offhours=rc.offhours(ts))
            return
        box = r.get("box")
        if box not in BOXES:
            raise _Drop("bad_raw")
        role = r.get("folder_role") or {"inbox": "inbox", "sent": "sent"}.get(box, "other")
        if role not in MAIL_FOLDER_ROLES:
            raise _Drop("bad_raw")
        if role == "deleted":
            raise _Drop("folder_excluded")
        subject = r.get("subject") if isinstance(r.get("subject"), str) else ""
        body = r.get("body_text") if isinstance(r.get("body_text"), str) else ""
        s_addr, s_name = _addr(r.get("sender_addr")), _s(r.get("sender_name"))[:120]
        known = "to" in r or "cc" in r
        to, cc = _parties(r.get("to")), _parties(r.get("cc"))
        me_sender = box == "sent" or self.is_self(s_addr, s_name)
        sender = [(s_addr, s_name)] if (s_addr or s_name) else []
        # 키(정제 전 원문)
        conv = _s(r.get("conversation_id"))
        topic = _norm_subject(_s(r.get("conversation_topic")) or subject)
        tmat = ("conv:" + conv) if conv else (("topic:" + topic) if topic else "")
        tk = self.key_opt(K.thread_key, tmat) if tmat else None
        mid = _s(r.get("internet_message_id")).strip("<>").strip().lower()
        if mid:
            mmat = "mid:" + mid
        else:
            idents = sorted({K.person_ident(a, n) or "" for a, n in (sender + to + cc)} - {""})
            mmat = "mail:" + "|".join((box, _minute(ts), tmat, ",".join(idents), topic[:80]))
        self.row["msg_key"] = self.key(K.msg_key, mmat)
        if tk:
            self.row["thread_key"] = tk
        # 사람·방향·수신
        self.row["box"], self.row["folder_role"] = box, role
        if me_sender:
            self.row["direction"], self.row["sender_key"] = "out", "self"
        else:
            self.row["direction"] = "in" if (box == "inbox" or sender) else "unknown"
            self.row["sender_key"] = self.who(s_addr, s_name) if sender else None
        self.row["sender_label"] = self.label(s_addr if s_addr else
                                              (sorted(rc.my_addrs)[0] if me_sender and rc.my_addrs else None))
        parties = ([] if me_sender else sender) + to + cc
        self.row["counterpart_keys"] = self.counterparts(parties)
        if known:
            self.row["n_to"], self.row["n_cc"] = len(to), len(cc)
            ids = {K.person_ident(a, n) or n for a, n in (sender + to + cc)}
            self.row["n_participants"] = min(10000, len(ids | ({"self"} if me_sender else set())))
        if me_sender:
            rcv = "na"
        elif not known or not rc.my_addrs:
            rcv = "unknown"
        elif any(a in rc.my_addrs for a, _n in to if a):
            rcv = "to"
        elif any(a in rc.my_addrs for a, _n in cc if a):
            rcv = "cc"
        else:
            rcv = "bulk"
        self.row["rcv"] = rcv
        if rcv == "bulk":
            self.flags["bulk"] = True
        elif rcv == "cc":
            self.flags["cc"] = True
        # 텍스트(당사자 표시명도 가린다 — 첫 수집의 빈 사람 사전에서도, W1b)
        self.parties_ctx(sender + to + cc)
        subj_m = self.text("subject_masked", subject, 120)
        names = _strlist(r.get("attach_names"), 10)
        self.textlist("attach_names_masked", names, 80, 5)
        self.row["attach_keys"] = [k for k in (self.key_opt(K.doc_key, n) for n in names[:10]) if k]
        self.row["attach_exts"] = sorted({e for e in (_ext_of(n) for n in names) if e})[:10]
        cats = _strlist(r.get("categories"), 10)
        self.textlist("categories_masked", cats, 30, 3)
        cat_private = any(c.strip().casefold() in rc._cat_private for c in cats)
        if cat_private:
            self.flags["cat_private"] = True
        sens = _int_or_none(r.get("sensitivity"), 0, 3) or 0
        if sens:
            self.flags["sensitivity"] = sens
        imp = _int_or_none(r.get("importance"), 0, 2)
        if imp is not None:
            self.row["importance"] = imp
        if _bool(r.get("has_attach")) or names:
            self.flags["has_file"] = True
        depth = _prefix_depth(subject)
        self.row["is_reply"] = bool(r.get("in_reply_to")) or depth > 0
        self.row["refw_depth"] = min(depth, 9)
        hdr = header_flags(r.get("headers_text")) if isinstance(r.get("headers_text"), str) else {}
        for src_k, fk in (("list_unsubscribe", "list_unsub"), ("precedence_bulk", "precedence"), ("esp", "esp")):
            if hdr.get(src_k):
                self.flags[fk] = True
        bu = body_unsub(body)
        if bu:
            self.flags["body_unsub"] = True
        fo = r.get("focused_other")
        if isinstance(fo, bool):
            self.row["focused_other"] = fo
        for bk in ("replied", "i_sent_in_conv"):
            if isinstance(r.get(bk), bool):
                self.row[bk] = r[bk]
        if tk and tk in rc.sent_threads:
            self.row["i_sent_in_conv"] = True
        self.cues = _cues(subject + "\n" + body)
        self.row["abs_hint"] = abs_hint(subject + "\n" + body)
        s_dom = _domain(s_addr)
        notice = self.flags.get("teams_notice") or (
            _dom_in(s_dom, TEAMS_NOTICE_DOMAINS)
            or (s_dom.endswith("microsoft.com") and TEAMS_NOTICE_SUBJECT.search(subject) is not None))
        if notice:
            self.flags["teams_notice"] = True
        # 광고(받은 메일만 — 보낸 편지함·내 발신·팀즈 알림 제외)
        if not me_sender and not notice:
            internal = _dom_in(s_dom, rc._internal)
            # 사전에 등록된 협력사·고객사 도메인 = 업무 관계(감점만 — P §11.2 work_relation). 고객사도 등록된 거래처다.
            partner_doms = [d for p in (*(rc.sctx.partners or ()), *(rc.sctx.customers or ()))
                            for d in p.get("domains", ())]
            al = rc.ad_lists or {}
            sk = self.row.get("sender_key")
            blocked = _dom_in(s_dom, al.get("block_domains", ())) or (sk and sk in al.get("block_senders", ())) \
                or any(p.search(subject) for p in al.get("block_subject_rx", ()))
            allowed = _dom_in(s_dom, al.get("allow_domains", ())) or (sk and sk in al.get("allow_senders", ()))
            m = {"subject": subject, "internal": internal, "corresp_domain": _dom_in(s_dom, rc.corresp_domains),
                 "partner": _dom_in(s_dom, partner_doms), "hdr": hdr, "body_unsub": bu,
                 "focused_other": fo is True, "folder": role, "rcv": rcv, "n_recipients": len(to) + len(cc),
                 "adlike_localpart": adlike_localpart(s_addr.split("@", 1)[0] if s_addr else ""),
                 "i_sent_in_conv": self.row.get("i_sent_in_conv") is True, "blocked": bool(blocked),
                 "allowed": bool(allowed)}
            score, band, why = ad_score_adjusted(m, rc.ad_extra_words)
            self.ad_band, self.ad_partial = band, not isinstance(r.get("headers_text"), str)
            if band == "drop":
                raise _Drop("ad", dict(self.hits))
            self.row.update(ad_score=max(-20, min(20, int(score))), ad_band=band, ad_why=[w for w in why if w in AD_WHY][:10],
                            ad_partial=self.ad_partial)
            if band == "suspect":
                self.flags["ad"] = True
        # 공사(정제문으로)
        if me_sender:
            rdoms = [_domain(a) for a, _n in to + cc if a]
            personal = bool(rdoms) and all(d in rc._personal for d in rdoms)
        else:
            personal = bool(s_dom) and s_dom in rc._personal and not _dom_in(s_dom, rc._internal)
        self.private(subj_m, offhours=rc.offhours(ts), personal_mail=personal, sensitivity=sens,
                     private_category=cat_private)
        # 같은 실행의 뒤 행이 쓴다: 보낸 대화 · 왕래 도메인(P §11.3 — 보낸 편지함을 먼저 처리)
        if me_sender:
            if tk:
                self.after.append(("sent_thread", tk))
            for a, _n in to + cc:
                d = _domain(a)
                if d and not _dom_in(d, rc._internal) and d not in rc._personal:
                    self.after.append(("corresp", d, _local(ts, self.off_min).date().isoformat()))
        self.learn(sender + to + cc, ts)

    def label(self, addr: str | None) -> str:
        """발신 계급 라벨(P §10.2 sender_label — 이메일 토큰 라벨과 같은 규칙)."""
        rc = self.rc
        dom = _domain(addr)
        if not dom:
            return "미상"
        if _dom_in(dom, rc._internal):
            return "사내"
        if dom in rc._personal:
            return "개인메일"
        lab = None
        for c in rc.sctx.customers or ():
            if _dom_in(dom, c.get("domains", ())):
                lab = "고객사:" + c["id"]
        for v in rc.sctx.partners or ():
            if _dom_in(dom, v.get("domains", ())):
                lab = "협력사:" + v["id"]
        if lab and SENDER_LABEL_RX.match(lab):
            return lab
        return dom if SENDER_LABEL_RX.match(dom) else "미상"

    def cal(self, r: dict) -> None:
        rc = self.rc
        ts = _utc(r.get("start_utc")) or _utc(r.get("ts_utc"))
        end = _utc(r.get("end_utc")) or _utc(r.get("ts_end"))
        if ts is None:
            raise _Drop("bad_raw")
        if end is None:
            if not self.copilot:
                raise _Drop("bad_raw")
            end = (_parse_utc_dt(ts) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if end < ts:
            end = ts
        self.row["ts_utc"], self.row["ts_end"] = ts, end
        if self.copilot:
            self.row["msg_key"] = self.key(K.cal_key, self.cp_material(r, ts))
            t = self.text("text_masked", r.get("copilot_text"), 200)
            self.private(t, offhours=rc.offhours(ts))
            return
        subject = r.get("subject") if isinstance(r.get("subject"), str) else ""
        body = r.get("body_text") if isinstance(r.get("body_text"), str) else ""
        gid = _s(r.get("global_appointment_id"))
        mat = (f"gid:{gid}|{_minute(ts)}" if gid else f"cal:{_minute(ts)}|{_minute(end)}|{_norm_subject(subject)[:80]}")
        self.row["msg_key"] = self.key(K.cal_key, mat)
        recurring = _bool(r.get("is_recurring"))
        if gid and recurring:
            tk = self.key_opt(K.thread_key, "series:" + gid)
            if tk:
                self.row["thread_key"] = tk
        org = [_party(r["organizer"])] if r.get("organizer") else []
        org = [p for p in org if p[0] or p[1]]
        att = _parties(r.get("attendees"))
        if self.flags.get("organizer_me") or any(self.is_self(a, n) for a, n in org):
            self.flags["organizer_me"] = True
        self.row["counterpart_keys"] = self.counterparts(org + att)
        if "attendees" in r:
            ids = {K.person_ident(a, n) or n for a, n in org + att}
            self.row["n_participants"] = min(10000, len(ids | {"self"}))
        busy = r.get("busy_status")
        if _isint(busy) and 0 <= busy <= 4:
            busy = BUSY[busy]
        self.row["busy"] = busy if busy in BUSY else None
        resp = _int_or_none(r.get("response_status"), 0, 5)
        if resp:
            self.flags["response"] = resp
        ms = _int_or_none(r.get("meeting_status"), 0, 7)
        if ms:
            self.flags["meeting_status"] = ms
        loc = _s(r.get("location"))
        online = _bool(r.get("online")) or bool(loc and ONLINE_LOC_RX.search(loc))
        self.row["location_class"] = ("online" if online else "none" if not loc
                                      else "room" if ROOM_LOC_RX.search(loc) else "external")
        for raw_k, fk in (("is_recurring", "recurring"), ("all_day", "all_day"), ("online", "online_meeting"),
                          ("recurrence_incomplete", "recurrence_incomplete")):
            v = r.get(raw_k)
            if _bool(v) or (_isint(v) and v > 0):
                self.flags[fk] = True
        if online:
            self.flags["online_meeting"] = True
        self.parties_ctx(org + att)                     # 주최자·참석자 표시명도 가린다(W1b)
        subj_m = self.text("subject_masked", subject, 120)
        cats = _strlist(r.get("categories"), 10)
        self.textlist("categories_masked", cats, 30, 3)
        cat_private = any(c.strip().casefold() in rc._cat_private for c in cats)
        if cat_private:
            self.flags["cat_private"] = True
        sens = _int_or_none(r.get("sensitivity"), 0, 3) or 0
        if sens:
            self.flags["sensitivity"] = sens
        self.row["abs_hint"] = abs_hint(subject + "\n" + body)
        self.private(subj_m, offhours=rc.offhours(ts), sensitivity=sens, private_category=cat_private)
        self.learn(org + att, ts)

    def teams(self, r: dict) -> None:
        rc = self.rc
        ts = self.ts(r)
        if self.copilot:
            day = _local(ts, self.off_min).date().isoformat()
            self.row["msg_key"] = self.key(K.msg_key, self.cp_material(r, ts))
            self.row["chat_key"] = self.key(K.chat_key, f"cp:{rc.src}|{day}")
            self.row["chat_type"], self.row["direction"] = "group", "unknown"
            t = self.text("text_masked", r.get("copilot_text"), 200)
            self.private(t, offhours=rc.offhours(ts))
            return
        ct = r.get("chat_type") or "unknown"
        n_part = _int_or_none(r.get("n_participants"), 0, 10000)
        if ct == "unknown":
            ct, n_part = "group", 2
            self.flags["n_part_est"] = True
        if ct not in CHAT_TYPES:
            raise _Drop("bad_raw")
        if ct == "self":
            n_part = 1
        chat_id = _s(r.get("chat_id"))
        if not chat_id:
            raise _Drop("bad_raw")
        body = r.get("body_text") if isinstance(r.get("body_text"), str) else ""
        a_addr, a_name = _addr(r.get("author_addr")), _s(r.get("author_name"))[:120]
        mid = _s(r.get("message_id"))
        if mid:
            mmat = "tid:" + mid
        else:
            lt = _local(ts, self.off_min)
            bh = hashlib.sha256(_norm_text(body).encode("utf-8")).hexdigest()[:16]
            mmat = "teams:" + "|".join((lt.date().isoformat(), chat_id, norm_person(a_name or a_addr or ""),
                                        lt.strftime("%H:%M"), bh))
        self.row["msg_key"] = self.key(K.msg_key, mmat)
        self.row["chat_key"] = self.key(K.chat_key, chat_id)
        rid = _s(r.get("reply_to_id"))
        if rid:
            tk = self.key_opt(K.thread_key, "reply:" + rid)
            if tk:
                self.row["thread_key"] = tk
        self.row["chat_type"] = ct
        if n_part is not None:
            self.row["n_participants"] = n_part
        is_me = r.get("is_me")
        if is_me is True:
            self.row["direction"], self.row["author_key"] = "sent", "self"
        else:
            self.row["direction"] = "received" if is_me is False else "unknown"
            self.row["author_key"] = self.who(a_addr, a_name) if (a_addr or a_name) else None
        parts = _parties(r.get("participants"))
        if is_me is not True and (a_addr or a_name):
            parts = parts + [(a_addr, a_name)]
        self.row["counterpart_keys"] = self.counterparts(parts)
        self.learn(parts + ([(a_addr, a_name)] if is_me is True else []), ts)   # P §9.6 — 주소 있는 작성자·참여자만
        if _bool(r.get("mentions_me")):
            self.flags["mentions_me"] = True
        self.parties_ctx(parts + ([(a_addr, a_name)] if (a_addr or a_name) else []))   # 작성자·참여자 표시명(W1b)
        files = _strlist(r.get("file_names"), 10)
        self.textlist("file_names_masked", files, 80, 5)
        self.row["file_keys"] = [k for k in (self.key_opt(K.doc_key, n) for n in files[:10]) if k]
        if files:
            self.flags["has_file"] = True
        body_m = self.text("body_masked", body, 300)
        self.cues = _cues(body)
        self.row["abs_hint"] = abs_hint(body)
        if ct in ("group", "channel", "meeting"):
            self.text("chat_title_masked", r.get("chat_title"), 60)
        ck = self.row["chat_key"]
        off = rc.offhours(ts)
        base, _cls, _det = private_score(body_m, chat_type=ct, offhours=off)
        self.row["priv_score_base"] = max(-50, min(50, int(base)))
        st = rc.room_stats.get(ck)
        rp = room_prior(st) if isinstance(st, RoomStat) else ""
        self.private(body_m, chat_type=ct, offhours=off, room_prior=rp, user_private_chat=ck in rc.private_chats)
        self.after.append(("room", ck, base))

    def pc_session(self, r: dict) -> None:
        rc = self.rc
        ts = self.ts(r)
        self.row["session_state"] = r.get("session_state")
        if rc.src == "pc.events":
            self.row["layer"] = r.get("layer")
            self.row["event_class"] = r.get("event_class")
            end = _utc(r.get("ts_end"))
            if end is None:
                raise _Drop("bad_raw")
            self.row["ts_end"] = max(end, ts)
            return
        fg = _s(r.get("fg_exe")).lower()
        app_class = r.get("app_class") or "other"
        self.row["fg_exe"] = fg or None
        self.row["app_class"] = app_class
        aid = _s(r.get("app_id")) or (("unknown:" + fg) if fg else "")
        self.row["app_id"] = aid or None
        self.row["idle_sec"] = _keep_int(r.get("idle_sec"), 0, 4294968)
        self.row["layer"] = r.get("layer") or ("L2" if app_class in ("idle", "system") else "L3")
        end = _utc(r.get("ts_end"))
        if end is None:
            iv = r.get("interval_sec")
            if not _isnum(iv) or iv < 0:
                raise _Drop("bad_raw")
            end = (_parse_utc_dt(ts) + timedelta(seconds=int(iv))).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.row["ts_end"] = max(end, ts)
        title = r.get("fg_title") if isinstance(r.get("fg_title"), str) else ""
        wc = rc.wctx if rc.wctx is not None else WindowContext(sctx=rc.sctx)
        if wc.sctx is None:
            wc = WindowContext(private_exes=wc.private_exes, private_profiles=wc.private_profiles,
                               work_title_patterns=wc.work_title_patterns, sctx=rc.sctx)
        v = _window_class(fg, title, app_class, wc)
        if v.title_masked:
            t = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", title))
            for cand in (t, t.rsplit(" - ", 1)[0], t.split(" - ", 1)[0]):
                rr = sanitize(cand, "title", rc.sctx, 120)
                if rr.text == v.title_masked:
                    _merge(self.hits, rr.hits)
                    break
        self.texts["title_masked"] = v.title_masked
        self.row["site_class"] = v.site_class
        if v.inprivate:
            self.flags["inprivate"] = True
        why = []
        if v.priv_class in ("private", "media"):
            why = [v.site_class] if v.site_class in ("app", "site", "profile", "inprivate") else []
            if v.priv_class == "media":
                why.append("media")
        self.priv = (v.priv_class, None, why)
        if v.priv_class == "work":
            name = _s(r.get("fg_doc_name"))
            if not name and app_class in TITLE_KEEP_CLASSES and title:
                name = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", title)).split(" - ", 1)[0].strip()
            if name:
                dk = self.key_opt(K.doc_key, name)
                if dk:
                    self.row["doc_key"] = dk
                    dpath = _s(r.get("fg_doc_path"))
                    if dpath:
                        try:
                            self.row["dir_keys"] = K.dir_keys_of(rc.keyring, dpath, 2)
                        except K.NoKeyError:
                            self.no_key = True

    def pc_file(self, r: dict) -> None:
        rc = self.rc
        self.ts(r)
        path = _s(r.get("path"))
        if not path:
            raise _Drop("bad_raw")
        if path_excluded(path, rc):
            raise _Drop("private_folder")
        name = K.base_name(path)
        self.text("name_masked", name, 80)
        self.row["ext"] = _ext_of(name)
        dk = self.key_opt(K.doc_key, name) if name else None
        if dk:
            self.row["doc_key"] = dk
        pk = self.key_opt(K.path_key, path)
        if pk:
            self.row["path_key"] = pk
        try:
            self.row["dir_keys"] = K.dir_keys_of(rc.keyring, path, 3)
        except K.NoKeyError:
            self.no_key = True
        role = r.get("folder_role")
        if role not in FILE_FOLDER_ROLES:
            low = path.replace("/", "\\").lower()
            role = ("sharepoint" if "sharepoint" in low and _URL_RX.match(path) else
                    "onedrive" if "\\onedrive" in low else "desktop" if "\\desktop\\" in low else
                    "documents" if "\\documents\\" in low else "downloads" if "\\downloads\\" in low else "other")
        self.row["folder_role"] = role
        rid = r.get("root_id")
        self.row["root_id"] = rid if isinstance(rid, str) and ROOT_ID_RX.match(rid) else None
        op = r.get("op") or "modify"
        self.row["op"] = op                                  # 열거 밖이면 열 검증이 잡는다(I12)
        self.row["size_bucket"] = _size_bucket(r.get("size"))
        for k in ("ooxml_totaltime", "ooxml_revision"):
            self.row[k] = _keep_int(r.get(k), 0, 100000)
        by = r.get("ooxml_last_modified_by")
        if isinstance(by, str) and by.strip():
            a = _addr(by)
            if not self.is_self(a, None if a else by):
                self.flags["author_other"] = True
        if _bool(r.get("pdf_sibling")):
            self.flags["pdf_export"] = True
        if op == "open":
            self.flags["view_only"] = True
        elif op in ("modify", "save"):
            self.flags["edit"] = True
        if not self.flags.get("final_name") and rc.final_words:
            low = name.lower()
            if any(str(w).lower() in low for w in rc.final_words if str(w).strip()):
                self.flags["final_name"] = True

    def pc_git(self, r: dict) -> None:
        rc = self.rc
        self.ts(r)
        repo = _s(r.get("repo_root"))
        sha = _s(r.get("commit_sha"))
        if not repo or not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
            raise _Drop("bad_raw")
        if path_excluded(repo + "\\x", rc):
            raise _Drop("private_folder")
        self.row["doc_key"] = self.key(K.repo_key, repo)
        self.row["commit_key"] = self.key(K.commit_key, sha)
        self.text("msg_masked", r.get("subject"), 120)
        self.row["n_commits"] = _keep_int(r.get("n_commits", 1), 1, 10000)
        self.row["n_files"] = _keep_int(r.get("n_files"), 0, 100000)
        self.row["exts"] = sorted({e for e in (_ext_of("x" + x if x.startswith(".") else x)
                                               for x in _strlist(r.get("exts"), 50)) if e})[:10]

    def pc_compute(self, r: dict) -> None:
        ts = self.ts(r)
        end = _utc(r.get("ts_end"))
        if end is None:
            raise _Drop("bad_raw")
        self.row["ts_end"] = max(end, ts)
        fg = _s(r.get("fg_exe")).lower()
        aid = _s(r.get("app_id")) or (("unknown:" + fg) if fg else "")
        if not aid:
            raise _Drop("bad_raw")
        self.row["app_id"] = aid
        cpu = r.get("cpu_core")
        self.row["cpu_core"] = None if cpu is None else (round(float(cpu), 3) if _isnum(cpu) else cpu)

    def manual(self, r: dict) -> None:
        cat = _s(r.get("category"))[:40]
        if not cat or not CATEGORY_RX.match(cat):
            raise _Drop("bad_raw")
        from .gate import check_team_label                  # 지연 import(gate → records 순환 회피)
        from .gate import GateContext
        if check_team_label(cat, GateContext(sctx=self.rc.sctx, canaries=()), 20):
            raise _Drop("bad_raw")
        self.row["work_category"] = cat
        ts = _utc(r.get("ts_utc"))
        prec = None
        if ts is None:
            m = _DATE_IN.match(_s(r.get("date")))
            if not m:
                raise _Drop("bad_raw")
            st = _HHMM.match(_s(r.get("start")))
            hh, mi = (int(st.group(1)), int(st.group(2))) if st else (0, 0)
            try:
                local = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mi, tzinfo=UTC)
            except ValueError:
                raise _Drop("bad_raw") from None
            ts = (local - timedelta(minutes=self.off_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
            prec = "minute" if st else "date"
            en = _HHMM.match(_s(r.get("end")))
            if st and en:
                e_local = local.replace(hour=int(en.group(1)), minute=int(en.group(2)))
                if e_local < local:
                    e_local += timedelta(days=1)
                self.row["ts_end"] = (e_local - timedelta(minutes=self.off_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            end = _utc(r.get("ts_end"))
            if end is not None:
                self.row["ts_end"] = max(end, ts)
        self.row["ts_utc"] = ts
        if prec and "ts_precision" not in (r or {}):
            self.row["ts_precision"] = prec
        hours = r.get("hours")
        self.row["hours"] = None if hours is None else (float(hours) if _isnum(hours) else hours)
        # P §10.2 text_masked = sanitize(note + " / " + entity) — 두 조각을 따로 정제해 " / " 로 잇는다(같은 모양).
        # 이어 붙인 뒤 정제하면 note 끝의 경로가 " / " 앞에서 경로 규칙(끝 조건)을 놓친다(WP-10 CR 참조).
        note = self.text("text_masked", _s(r.get("note")), 200)
        ent_raw = _s(r.get("entity"))
        room = 200 - len(note) - (3 if note else 0)
        if ent_raw.strip() and room > 0:
            ent = self.text("text_masked", ent_raw, room)
            self.texts["text_masked"] = note + " / " + ent if note and ent else (note or ent)
        else:
            self.texts["text_masked"] = note
        for k in ("project_id", "role_field", "role_func", "retract_of"):
            v = r.get(k)
            self.row[k] = v if v not in ("", None) else None
        mk = r.get("man_kind") or "work"
        self.row["man_kind"] = mk
        refs = r.get("ref_keys") or []
        self.row["ref_keys"] = list(refs) if isinstance(refs, (list, tuple)) else refs

    # ── 마무리 ──
    def run(self, raw) -> RecordOutcome:
        if not isinstance(raw, dict):
            raise _Drop("bad_raw")
        r = self.common(raw)
        getattr(self, self.kind)(r)
        cls, score, why = self.priv
        if cls in ("private", "social"):
            self.texts = {c: ([] if isinstance(v, list) else "") for c, v in self.texts.items()}
            self.cues = []
            if "private" in self.spec.flag_keys:            # pc_session 등은 priv_class 열만(P §10.2 flags 허용 키)
                self.flags["private"] = True
        if self.rc.no_key or self.no_key:
            self.texts = {c: _plain_person(v) for c, v in self.texts.items()}
        if self.no_key and "no_key" in self.spec.flag_keys:
            self.flags["no_key"] = True
        row = dict(self.row)
        row.update(self.texts)
        row["act_cues"] = list(self.cues)
        if self.flags:
            row["flags"] = dict(sorted(self.flags.items()))
        row.update(rules_ver=RULES_VERSION, kid=getattr(self.rc.keyring, "kid", K.NO_KID),
                   san=dict(sorted(self.hits.items())), src=self.rc.src, pc_id=self.rc.pc_id, act="",
                   priv_class=cls, priv_score=score, priv_why=list(why)[:8])
        row = {k: v for k, v in row.items() if v is not None}
        row["id"] = record_id(row, self.spec)
        bad = validate_columns(self.kind, row)
        if bad:
            if self.rc.audit is not None:
                self.rc.audit.add("err", "column:" + bad[0])
            return RecordOutcome("error", None, "ColumnViolation", {})
        self._apply_after()
        return RecordOutcome("stored", SanitizedRow(self.kind, row, _SEAL), None, dict(self.hits))

    def _apply_after(self) -> None:
        rc = self.rc
        for item in self.after:
            if item[0] == "sent_thread":
                rc.sent_threads.add(item[1])
            elif item[0] == "corresp":
                rc.corresp_domains.add(item[1])
                rc.corresp_new[item[1]] = max(rc.corresp_new.get(item[1], ""), item[2])
            elif item[0] == "room":
                st = rc.room_stats.get(item[1]) or RoomStat(0, 0, 0)
                rc.room_stats[item[1]] = RoomStat(st.n + 1, st.n_private + (item[2] >= 2), st.n_work + (item[2] <= -2))
            elif item[0] == "person":
                _k, wk, addr, name, day, is_self, internal = item
                p = rc.people.setdefault(wk, {"names": set(), "smtp": set(), "self": False, "internal": False,
                                              "first": day, "last": day})
                if name and not _EMAIL_RX.match(name):
                    p["names"].add(_CTRL_RX.sub(" ", name)[:60])
                if addr:
                    p["smtp"].add(addr)
                p["self"] = p["self"] or is_self
                p["internal"] = p["internal"] or internal
                p["first"], p["last"] = min(p["first"], day), max(p["last"], day)
                if not p["self"] and name:               # 같은 실행의 다음 레코드부터 이 이름을 가린다(W1b)
                    nm = dict_name(name, {str(s).lower() for s in (rc.sctx.self_names or ())})
                    if nm is not None and _name_norm(nm) not in rc.self_norms:
                        rc.sctx.persons.setdefault(nm, wk[1:])


# ───────────────────────────── 공개 함수 ─────────────────────────────
def sanitize_record(kind: str, raw: dict, rc: RecordContext) -> RecordOutcome:
    """수집기 단일 관문(P §10.3). 원시 1건 → ``RecordOutcome``(stored 면 봉인 행). 알 수 없는 kind·경로 ID 불일치는
    프로그래밍 오류라 ValueError(수집기 중단 — fail-closed). 한 행의 오류로 수집 전체를 멈추지 않는다(error 결과)."""
    spec = SCHEMAS.get(kind)
    if spec is None:
        raise ValueError("sanitize_record: 알 수 없는 kind")
    if not isinstance(rc, RecordContext):
        raise TypeError("sanitize_record: RecordContext 가 필요합니다")
    if rc.src not in SRCS_BY_KIND[kind]:
        raise ValueError("sanitize_record: 경로 ID 와 kind 가 맞지 않습니다")
    b = _Build(spec, rc)
    try:
        if _has_surr(raw):                       # 입력 정규화 첫 단계 — 외톨이 서로게이트(원문 사본은 메모리에만)
            raw = _fix_surr(raw)
        out = b.run(raw)
    except _Drop as d:
        out = RecordOutcome("dropped", None, d.reason, dict(d.hits))
    except Exception as e:                       # noqa: BLE001 — 한 행 오류로 수집 전체 중단 금지(원문·메시지 없이 유형만)
        if rc.audit is not None:
            rc.audit.add("err", type(e).__name__)
        out = RecordOutcome("error", None, type(e).__name__, {})
    if rc.audit is not None:
        rc.audit._note_outcome(out.status, out.reason, out.hits if out.status == "stored" else None,
                               priv=b.priv[0] if out.status == "stored" else None, ad=b.ad_band,
                               ad_partial=b.ad_partial)
    return out


def _ver(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def remask_persons(kind: str, row, ctx: SanitizeContext | None = None):
    """G2 보강(W1b): 지금 사람 사전(``ctx.persons``)의 이름이 저장 행 텍스트 열에 남아 있으면 **그 열만** 지금 문맥으로 다시
    정제한다(규칙 판이 같아도 — 행을 쓴 뒤에 배운 이름). → ``(행, 범주별 건수)``. 남은 이름이 없으면 같은 행 객체를 돌려준다
    (바뀌었는지는 ``is`` 로 본다). 원본은 바꾸지 않는다. 기존 토큰은 보호 구간이라 멱등이다(I5)."""
    if ctx is None or not ctx.persons or kind not in SCHEMAS:
        return row, {}
    rx = _dict_rx(ctx.persons)
    if rx is None:
        return row, {}
    out, hits, changed = None, {}, False
    for col in SCHEMAS[kind].text_fields:
        v = row.get(col)
        if not v:
            continue
        vals = list(v) if isinstance(v, (list, tuple)) else [v]
        if not any(isinstance(x, str) and x and rx.search(x) for x in vals):
            continue
        new = []
        for x in vals:
            if isinstance(x, str) and x and rx.search(x):
                r = sanitize(x, col, ctx)
                new.append("" if r.drop else r.text)
                _merge(hits, {"cred": 1} if r.drop else r.hits)
            else:
                new.append(x)
        if out is None:
            out = dict(row)
        out[col] = new if isinstance(v, (list, tuple)) else new[0]
        changed = True
    return (out, hits) if changed else (row, {})


def resanitize_row(kind: str, row, ctx: SanitizeContext | None = None):
    """적재 시 재정제(G2 · P §10.5): ``rules_ver`` 가 지금보다 낮은 행은 텍스트 열을 지금 규칙으로 다시 정제하고, 같은 판인
    행도 지금 사람 사전의 이름이 남은 열은 다시 가린다(``remask_persons`` — W1b, 첫 실행에 남은 실명). → ``(행, 범주별 건수)``.
    원본은 바꾸지 않는다(사본). 자격증명이 뒤늦게 걸리면 그 값만 비운다(행·시간 근거 유지). ``id`` 는 다시 계산하지 않는다
    (행 정체성은 최초 저장 때 고정). 가림은 늘기만 한다(I5 — 토큰은 보호 구간). 바뀐 것이 없으면 같은 행 객체."""
    if _ver(row.get("rules_ver", "0.0.0")) >= _ver(RULES_VERSION):
        return remask_persons(kind, row, ctx)
    out, hits = dict(row), {}
    for col in SCHEMAS[kind].text_fields:
        v = out.get(col)
        if not v:
            continue
        vals = list(v) if isinstance(v, (list, tuple)) else [v]
        new = []
        for x in vals:
            if not x:
                new.append(x)
                continue
            r = sanitize(str(x), col, ctx)
            new.append("" if r.drop else r.text)
            _merge(hits, {"cred": 1} if r.drop else r.hits)
        out[col] = new if isinstance(v, (list, tuple)) else new[0]
    out["rules_ver"] = RULES_VERSION
    return out, hits


def redact_fields(kind: str) -> tuple:
    """소급 가림(P §12.5 · C11)에서 비울 열 단일원 — 그 kind 의 정제문 열 + ``act_cues``(내용에서 뽑은 단서).
    키·시간·열거·숫자 열(abs_hint 포함 — R-P8)은 그대로 둔다."""
    return (*SCHEMAS[kind].text_fields, "act_cues")


def redact_row(kind: str, row) -> dict:
    """행 하나를 가린 사본(텍스트 열 ``""``/``[]`` — 행 수·키·시간 열 불변, ``id`` 그대로). 원본은 바꾸지 않는다.
    세그먼트 교체는 ``lm27.bundle.merge.redact_rewrite_own``(WP-12)이 ``write_segment`` 로만 한다(C11 · X-175)."""
    out = dict(row)
    for col in redact_fields(kind):
        if col in out:
            out[col] = [] if isinstance(out[col], (list, tuple)) else ""
    return out
