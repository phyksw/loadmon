# -*- coding: utf-8 -*-
r"""LM27 정제 단일 관문(P 소유 — 계약 §2.2) — 공개 API 재수출. 분석·브리지·팀 코드는 이 패키지만 import 한다
(수집기 파이썬은 ``lm27.privacy.sanitize`` 한 모듈만 — L-10).

관문 4개(P §1.2): G1 수집 경계 ``sanitize_record`` · G2 적재 시 재정제 ``resanitize_row`` · G3 코파일럿 전송 직전
``gate_copilot``·``gate_prompt_text`` · G4 팀 업로드 직전 ``check_team_payload``(``spec`` 필수 — ``TEAM_SPEC_V1`` 을 호출자가
넘긴다, 이 패키지는 ``lm27.team`` 을 import 하지 않는다 — X-304). 감사는 ``AuditSink``(건수·판·해시만).

이 ``__init__`` 은 이 패키지 안 모듈만 최상위에서 import 한다 — ``lm27.hier``·``lm27.team``·``lm27.config`` 는 프로그램 폴더
모드 함수 안에서만 지연 import(X-304, 에이전트 bin 사본에는 그 패키지가 없다 — 계약 §1.3). 저장소 쓰기(``lm27.store``)는
이 패키지가 아니라 ``lm27.store.SegmentWriter`` 다(store → privacy 한 방향).
"""
from .audit import AuditSink
from .classify import WindowContext, WindowVerdict, ad_score, private_score, room_prior, window_class
from .context import (
    LocalOnly,
    build_context,
    context_cache_obj,
    make_gate_context,
    make_record_context,
    read_context_cache,
    refresh_context_cache,
    self_name_set,
    write_context_cache,
)
from .detect import SanitizeContext, SanitizeResult
from .gate import (
    GateContext,
    GateItem,
    GateResult,
    GateSpecError,
    StageSpec,
    Violation,
    check_team_label,
    check_team_payload,
    forbidden_codes,
    gate_copilot,
    gate_prompt_text,
    gate_text,
)
from .keys import (
    AGENT_PURPOSES,
    KEYS_VERSION,
    PURPOSES,
    AgentKeys,
    Keyring,
    NoKeyError,
    NoKeyringError,
    dir_key,
    doc_fam,
    doc_key,
    keyed,
    load_agent_keys,
    load_keyring,
    peer_key,
    who_key,
    write_agent_subkeys,
)
from .records import (
    KINDS,
    SCHEMAS,
    RecordContext,
    RecordOutcome,
    RoomStat,
    SanitizedRow,
    path_excluded,
    record_id,
    redact_fields,
    redact_row,
    resanitize_row,
    sanitize_record,
)
from .rules import RULES_HASH, RULES_VERSION
from .scan import Hit, scan, tokens_of
from .selftest import run_selftest
from . import sanitize  # 수집기 관문 모듈 = 부를 수 있는 sanitize() — import 순서와 무관하게 같은 객체(sanitize.py 참조)

__all__ = [
    "AGENT_PURPOSES", "KEYS_VERSION", "KINDS", "PURPOSES", "RULES_HASH", "RULES_VERSION", "SCHEMAS",
    "AgentKeys", "AuditSink", "GateContext", "GateItem", "GateResult", "GateSpecError", "Hit", "Keyring", "LocalOnly",
    "NoKeyError", "NoKeyringError", "RecordContext", "RecordOutcome", "RoomStat", "SanitizeContext", "SanitizeResult",
    "SanitizedRow", "StageSpec", "Violation", "WindowContext", "WindowVerdict",
    "ad_score", "build_context", "check_team_label", "check_team_payload", "context_cache_obj", "dir_key", "doc_fam",
    "doc_key", "forbidden_codes", "gate_copilot", "gate_prompt_text", "gate_text", "keyed", "load_agent_keys",
    "load_keyring", "make_gate_context", "make_record_context", "path_excluded", "peer_key", "private_score",
    "read_context_cache", "record_id", "redact_fields", "redact_row", "refresh_context_cache", "resanitize_row",
    "room_prior", "run_selftest", "sanitize", "sanitize_record", "scan", "self_name_set", "tokens_of", "who_key",
    "window_class", "write_agent_subkeys", "write_context_cache",
]
