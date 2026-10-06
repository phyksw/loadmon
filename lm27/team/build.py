# -*- coding: utf-8 -*-
r"""팀 업로드 묶음 빌더 — 허용 목록으로 하나씩 고른다(TAB §2.3·§2.4·§2.5·§2.7, 계약 §3.18·§4.2·L-22·T-21·RP15).

    item = build_and_queue(analysis, {"from": "2026-07-01", "to": "2026-09-30"}, cfg)      # cli `lm27 team build`
    obj, audit = build_team_bundle(analysis, period, registry, pepper, overrides, cfg, env=env)
    set_mask(paths, unit_id, "title" | "detail" | "none") · drop_need(paths, need_id)          # 미리보기 가림(TAB §2.5)

입력 ``analysis`` = 지금 분석 결과의 보고서 모델 전체판(``lm27.report.load_model(<current.json 의 run_id>)`` — 계약 §7.1).
빌더는 모델을 **통째로 직렬화하지 않는다.** ``TEAM_SPEC_V1``(``lm27.team.schema`` 단일원) 의 필드를 하나씩 골라 새 사전을
만든다(L-22: 사전 펼치기·``dict(obj)``·``deepcopy(analysis…)`` 0, PC 레지스트리의 호스트 표시명 필드는 읽지 않는다).
동료 표시명·문서 이름·근거 키·who_key 는 싣지 않는다 — 모델 ``refs.people`` 의 who_key 만 꺼내 로컬 사람 사전 주소로
``peer_key``(팀 pepper HMAC, 없으면 개인 키링 — P §9.7)를 만든다(TAB §2.3.3).

- 시간 수치는 정수 분 표(모델 ``tables`` = 시간 코어 ``team_tables.json``)에서만 나온다: ``envelope_daily``·``alloc_daily``
  는 기간 안 행을 그대로, ``summary.months[]`` 는 그 행의 합 + ``mm = 봉투 ÷ (std_day_min × 근무일)`` · ``avail = 덮은 근무일 −
  부재`` · ``load_pct``(TAB §2.3.2 식 — 개인 = 팀, TAB R-3). 묶음 기간이 분석 기간과 같은 달은 덮은 근무일·부재를 모델 값
  그대로 쓰고, 기간 일부만 올리는 달은 모델 ``days[]``(근무일·부재)로 다시 센다.
- 분류 조각(과제·제안·역할·단위업무 제목·업무 유형)은 ``lm27.hier.team_out.team_parts``(H §12.4 — 개인 ``L_`` 코드 대응·
  role_id 재계산·generic 제목)를 부른다. 시간 필드(시작·종료 근거 종류·등급·상태·spans·투입)는 W §4.11 대응표대로 모델에서.
- 워크플로우·agentic·서브에이전트·동료 지표·측정 품질은 개인 보고서 모델과 같은 값이다(RP15 · RPT-12): 품질 등급은
  ``lm27.report.analysis.quality.period_quality`` 로 묶음 기간의 달 등급을 합친다.
- 자유 문자열(단위업무 제목·단계 라벨·제안 이름·니즈 이름·서브에이전트 제안·본인 라벨)은 모두 ``schema.team_text``(P
  ``check_team_label``·``forbidden_codes`` + 로컬 사전)를 거친다. 걸리면 대체 라벨(generic·단계 유형 이름)을 넣고 건수만
  센다. 마지막 3중 검사(자유 문자열 재검사 → P ``check_team_payload(obj, gctx, TEAM_SPEC_V1)`` → 정규 바이트 ``BYTES_GUARD``)
  가 하나라도 걸리면 빌드 실패(rc 1, 필드 경로·코드만 — 값은 어디에도 찍지 않는다).
- 정규 바이트 한 벌(``canon_bytes``)을 ``data\outbox\team\pending\`` 에 원자 쓰기(미리보기 = 실전송 — TAB §2.7). 같은 바이트가
  대기 중이면 그대로(rc 4), 같은 기간의 다른 미전송 항목은 ``dropped``(superseded). 전송 바이트 sha 와 필드별 거절 수는
  정제 감사 ``gate_team`` 에 남긴다(P §15.4).

rc(계약 §8.3): 0 만듦 · 2 만들었으나 막힘(blockers — 크기·검증) 또는 만들 수 없는 기간(분석 먼저) · 4 같은 묶음이 이미
대기 중 · 1 검사 실패(필드 경로만). 표준 라이브러리 + LM27 공개 함수만 쓴다.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from lm27.team import schema as S
from lm27.util import fsx

__all__ = ["BuildEnv", "BuildFailed", "BuildRefused", "FREE_TEXT_FIELDS", "OVERRIDES_SCHEMA", "TextCtx",
           "build_and_queue", "build_team_bundle", "drop_need", "load_env", "load_overrides", "pepper_of",
           "registry_cache", "set_mask", "size_blockers"]

SCHEMA_VERSION = f"{S.SCHEMA_MAJOR}.{S.SCHEMA_MINOR}"
APP_NAME = "LM27"
OVERRIDES_SCHEMA = "lm27.team_overrides/1"
GANTT_GAP = 2                                   # TAB §2.3.2 — active = active_spans(alloc 일자, gap=2)
MB = 1024 * 1024
# W §4.10.1 시작 근거 등급 — 진행 중(O) 단위업무의 잠정 등급(W §4.11 'grade = SG[시작]')
SG = {"S1": "A", "S1o": "A", "S1d": "B", "S2a": "B", "S2M": "B", "S2m": "C", "S2p": "C"}
TEAM_GRADES = frozenset(S.GRADES)
TEAM_STATUS = frozenset(S.UNIT_STATUS)
GRADE3 = frozenset(S.AGENT_GRADES)
FITS = frozenset(S.FITS)
WHY = frozenset(S.WHY)
# 자유 문자열 필드(TAB §2.4 — 마지막 검사 1단)와 최대 길이
FREE_TEXT_FIELDS = (("units[].title", 40), ("workflows[].steps[].label", 30), ("proposals[].label", 40),
                    ("agentic.needs[].label", 40), ("agentic.subagents[].chain[].proposal", 40),
                    ("person.self_label", 20))
_UNIT_RX = re.compile(r"u_[0-9a-f]{10}")
_NEED_RX = re.compile(r"n_[0-9a-f]{6}")
_PERSON_KEY_RX = re.compile(r"p_[0-9a-f]{12}")
_PEPPER_RX = re.compile(r"[0-9a-f]{64}")
_LOCAL_DT_RX = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2}))?")
_COUNT_KEY_RX = re.compile(r"[a-z_:]{1,32}")
_EXE_RX = re.compile(r"[a-z0-9_.\-]{1,64}\.exe")
_PROBE_KEY_RX = re.compile(r"[a-z]{2,8}\.[a-z]{2,10}")
_SRC_RX = re.compile(r"(?:(?:mail|cal|teams|pc)\.[a-z]{2,10}|manual)")
_HANGUL = re.compile(r"[가-힣]")
UNKNOWN_PREFIX = "unknown:"
COV_STATES = S.COV_STATES
COV_OK = frozenset({"ok", "zero_ok", "partial"})
REASON_MAX = 20                                  # quality.reasons[] = LABEL20


class BuildRefused(Exception):
    """만들 수 없는 요청(분석 기간 밖·모델 없음·번들 정보 없음) — rc 2, 한국어 한 줄. 파일을 쓰지 않는다."""


class BuildFailed(Exception):
    """마지막 3중 검사 실패 — rc 1. ``problems`` = ['경로: 코드'] (값 없음)."""

    def __init__(self, problems):
        self.problems = sorted(set(problems))
        super().__init__("팀 묶음 검사 실패 — 금지 내용이 남아 만들지 않았습니다: " + ", ".join(self.problems[:8]))


# ───────────────────────────── 작은 도우미 ─────────────────────────────
def _g(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def _int(v, d: int = 0) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else d


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return S.parse_date(v) if isinstance(v, str) else None


def _now(now=None) -> datetime:
    n = now or datetime.now(UTC)
    return n if n.tzinfo is not None else n.replace(tzinfo=UTC)


def _iso_off(local: str, off_min: int) -> str | None:
    """모델 로컬 시각 'YYYY-MM-DDTHH:MM' → ISO 8601 + 오프셋(계약 §9.4 — 팀 묶음 시각)."""
    from lm27.util.tz import fmt_offset
    m = _LOCAL_DT_RX.fullmatch(str(local or ""))
    if not m:
        return None
    return f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}{fmt_offset(off_min)}"


def _built_iso(now: datetime, off_min: int) -> str:
    from lm27.util.tz import fmt_offset, to_local
    return to_local(now, off_min).strftime("%Y-%m-%dT%H:%M:%S") + fmt_offset(off_min)


def _month_bounds(m: str) -> tuple[date, date]:
    y, mo = int(m[:4]), int(m[5:7])
    return date(y, mo, 1), date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)


def _period(period) -> tuple[date, date]:
    if isinstance(period, Mapping):
        a, b = period.get("from"), period.get("to")
    elif isinstance(period, (tuple, list)) and len(period) == 2:
        a, b = period
    else:
        a = b = None
    d0, d1 = _date(a), _date(b)
    if d0 is None or d1 is None:
        raise BuildRefused("기간 형식이 아닙니다 — {'from': 'YYYY-MM-DD', 'to': 'YYYY-MM-DD'}")
    if d0 > d1:
        raise BuildRefused("기간 시작이 끝보다 늦습니다")
    if (d1 - d0).days + 1 > S.MAX_PERIOD_DAYS:
        raise BuildRefused(f"기간이 {S.MAX_PERIOD_DAYS}일을 넘습니다 — 나눠서 만드세요")
    return d0, d1


def _dict_word_ok(w: str) -> bool:
    """로컬 사전 낱말 — 한글 2자 이상·ASCII 4자 이상만(짧은 항목 오탐 방지, TAB §2.4)."""
    if _HANGUL.search(w):
        return len(w) >= 2
    return len(w) >= 4


def registry_cache(paths) -> dict | None:
    r"""팀 레지스트리 캐시 ``data\team\registry.json``(pepper 포함 — 반출 금지, L-22 허용 모듈)."""
    obj = fsx.read_json(paths.registry_cache(), None, want=dict)
    return obj if isinstance(obj, dict) else None


def pepper_of(registry) -> str | None:
    pep = registry.get("pepper") if isinstance(registry, Mapping) else None
    return pep if isinstance(pep, str) and _PEPPER_RX.fullmatch(pep) else None


# ───────────────────────────── 자유 문자열 검사 문맥 ─────────────────────────────
class TextCtx:
    """``schema.team_text`` 문맥(TAB §2.4): 게이트 문맥 + 거절 건수 + 로컬 사전 부분 일치(대소문자 무시)."""

    def __init__(self, gctx, words=()):
        self.gctx = gctx
        self.audit: dict = {}
        self.audit_fields: dict = {}
        ws = set()
        for w in words or ():
            t = " ".join(unicodedata.normalize("NFKC", str(w or "")).split())
            if t and _dict_word_ok(t):
                ws.add(t.casefold())
        self._words = tuple(sorted(ws))

    def local_dict_hit(self, s: str) -> bool:
        low = unicodedata.normalize("NFKC", str(s or "")).casefold()
        return any(w in low for w in self._words)

    def text(self, s, maxlen: int, field_name: str):
        """통과 문자열 · 빈 값 "" · 걸림 None(호출자가 대체 라벨)."""
        return S.team_text(s, maxlen, field_name, self)

    def label_only(self, s, maxlen: int, field_name: str):
        """본인이 일부러 입력한 값(person.self_label) — 로컬 사전은 건너뛴다(TAB §2.4)."""
        return S.team_text(s, maxlen, field_name, _LabelOnly(self))

    def bad(self, s: str, maxlen: int) -> bool:
        """마지막 검사 1단 — 이미 고른 문자열을 같은 판정으로 다시(세지 않는다)."""
        from lm27.privacy import check_team_label, forbidden_codes
        if not s:
            return False
        return bool(check_team_label(s, self.gctx, maxlen) or forbidden_codes(s, self.gctx) or self.local_dict_hit(s))

    @property
    def rejected(self) -> int:
        return int(self.audit.get("team_text_rejected", 0))


class _LabelOnly:
    def __init__(self, base: TextCtx):
        self.gctx = base.gctx
        self.audit = base.audit
        self.audit_fields = base.audit_fields


# ───────────────────────────── 빌드 환경(로컬 자료) ─────────────────────────────
@dataclass
class BuildEnv:
    """빌더가 모델 밖에서 읽는 로컬 자료(모두 이 PC 안 — 팀 묶음에는 계산 결과만 실린다)."""
    paths: object = None
    person_key: str = ""
    person_dir: dict = field(default_factory=dict)       # local_only\person_dir.json(주소 → peer_key 재료)
    keyring: object = None                               # 개인 키링(pepper 가 없을 때 personal peer_key)
    internal_domains: tuple = ()
    eff_registry: object = None                          # lm27.hier.registry.EffectiveRegistry(team_parts)
    gctx: object = None                                  # lm27.privacy.GateContext(정제 사전·카나리아)
    local_words: tuple = ()                              # 로컬 사전(사람 표시명·계정·PC 이름·PC 별칭)
    privacy_counts: dict = field(default_factory=dict)   # 정제 감사 범주·행 사유 기간 합계
    coverage_cells: list | None = None                   # 커버리지 원장 셀(없으면 quality.coverage·pcs 생략)
    coverage_composite: object = None                    # (cells) → {(date, axis): {status, …}} — 원장 합성 함수
    pcs: list = field(default_factory=list)              # pc.json 허용 목록 조각
    exe_meta: dict = field(default_factory=dict)         # 이 PC 의 미상 프로그램 공개 메타(catalog_proposals)
    pc_id: str | None = None
    built_on: str = ""                                   # 만든 PC 라벨(label_auto — 호스트명 아님)
    warnings: list = field(default_factory=list)


def load_env(paths, cfg, *, period, registry=None, environ=None, machine_guid=None, pc_id=None,
             eff_registry=None) -> BuildEnv:
    """로컬 자료를 모은다(빌드 1회). ``environ``·``machine_guid``·``pc_id``·``eff_registry`` 는 시험 주입점."""
    from lm27 import privacy as P
    d0, d1 = _period(period)
    env = BuildEnv(paths=paths)
    b = fsx.read_json(paths.bundle_json(), None, want=dict) or {}
    pk = b.get("person_key")
    if not (isinstance(pk, str) and _PERSON_KEY_RX.fullmatch(pk)):
        raise BuildRefused("번들 정보(person_key)가 없습니다 — 먼저 [수집]을 한 번 실행하세요")
    env.person_key = pk
    local = P.LocalOnly.load(paths)
    env.person_dir = local.person_dir if isinstance(local.person_dir, dict) else {}
    try:
        env.keyring = P.load_keyring(paths.data(), None, create=False)
    except P.NoKeyringError:
        env.keyring = None
        env.warnings.append("키링이 없어 개인 동료 키를 만들 수 없습니다")
    if eff_registry is None:
        from lm27.hier.registry import load_effective
        eff_registry, _st = load_effective(paths, cfg, kr=env.keyring, persist=False)
    env.eff_registry = eff_registry
    sctx = P.build_context(cfg, eff_registry, local, env.keyring)
    # 사내 도메인 = 팀 레지스트리 ∪ privacy.internalDomains(유효 레지스트리가 합침) ∪ 본인 주소 도메인(P §17.2 — 실행 중
    # 자동으로 더하는 규칙과 같게, 레지스트리 캐시가 없어도 개인 범위 동료 키를 만든다 · U15). 공용 개인 메일 도메인은 빼고.
    personal = {str(d).strip().lower() for d in (getattr(sctx, "personal_mail_domains", ()) or ())}
    doms = [str(d).strip().lower() for d in (_g(eff_registry, "internal_domains", ()) or ()) if str(d).strip()]
    for p in (env.person_dir.get("people") or {}).values():
        if isinstance(p, Mapping) and p.get("self") is True:
            for a in p.get("smtp") or ():
                d = str(a).strip().lower().rsplit("@", 1)[-1] if isinstance(a, str) and "@" in a else ""
                if d and d not in personal:
                    doms.append(d)
    env.internal_domains = tuple(dict.fromkeys(doms))
    env.gctx = P.make_gate_context(sctx, cfg, env.keyring, stage="team", audit=None, environ=environ,
                                   machine_guid=machine_guid, local=local)
    ev = os.environ if environ is None else environ
    words = [str(ev.get(k) or "") for k in ("USERNAME", "COMPUTERNAME", "USERDOMAIN")]
    for p in (env.person_dir.get("people") or {}).values():
        if isinstance(p, Mapping):
            words += [str(n) for n in (p.get("names") or ()) if isinstance(n, str)]
    env.pcs, pc_words = _pc_parts(paths)
    env.local_words = tuple(sorted({w for w in words + pc_words if w}))
    env.pc_id = pc_id if pc_id is not None else _this_pc(paths)
    env.built_on = next((p["label_auto"] for p in env.pcs if p.get("_pc") == env.pc_id and p.get("label_auto")), "")
    env.privacy_counts = _privacy_counts(paths, cfg, d0, d1)
    env.coverage_cells, env.coverage_composite = _coverage(paths)
    if cfg["team.shareUnknownApps"] and env.pc_id:
        from lm27.agent.exemeta import load_exe_meta
        env.exe_meta = load_exe_meta(paths, env.pc_id) or {}
    return env


def _this_pc(paths) -> str | None:
    from lm27.bundle.ids import identify_pc
    return identify_pc(paths).pc_id


def _pc_parts(paths) -> tuple[list, list]:
    """pc.json 에서 허용 목록 필드만(라벨·종류·에이전트 구현·능력 판정·첫 관측) + 로컬 사전 낱말(사람이 붙인 PC 별칭).
    PC 이름 표시 필드는 읽지 않는다(TAB §2.3.3 · L-22) — PC 이름은 게이트 카나리아(환경)와 WP-12 의 사전 함수가 맡는다."""
    from lm27.bundle import pcreg
    out, words = [], []
    for pc in pcreg.load_all_pcs(paths):
        if not isinstance(pc, Mapping):
            continue
        installs = [x for x in (pc.get("installs") or ()) if isinstance(x, Mapping)]
        impl = str(_g(installs[-1], "impl", "") or "") if installs else ""
        caps = {}
        for k, c in sorted((pc.get("capabilities") or {}).items()):
            v = _g(c, "verdict", "")
            if isinstance(k, str) and _PROBE_KEY_RX.fullmatch(k) and isinstance(v, str) and v:
                caps[k] = v
        out.append({"_pc": str(pc.get("pc_id") or ""), "label_auto": str(pc.get("label_auto") or ""),
                    "kind": str(pc.get("kind") or ""), "agent_impl": impl if impl in ("py", "ps") else "none",
                    "first_seen": str(pc.get("first_seen") or ""), "probe": caps})
        lu = pc.get("label_user")
        if isinstance(lu, str) and lu.strip():
            words.append(lu.strip())
    fn = getattr(pcreg, "local_dict_words", None)        # WP-12 CR — PC 이름 표시 필드를 빌더 대신 읽어 주는 함수
    if fn is not None:
        words += [str(w) for w in (fn(paths) or ()) if isinstance(w, str)]
    out.sort(key=lambda p: (p["first_seen"] or "9999", p["_pc"]))
    return out, words


def _privacy_counts(paths, cfg, d0: date, d1: date) -> dict:
    """정제 감사(``privacy_audit`` 스트림 — 단일 로더) 의 가린 범주·버린 행 사유를 기간 합계로(TAB §2.3.2 · P §15.3)."""
    from lm27.bundle.loader import iter_records
    out: dict = defaultdict(int)
    for ev in iter_records(paths, "privacy_audit", d0, d1, cfg=cfg):
        for part in ("masked", "dropped"):
            for k, v in (ev.get(part) or {}).items():
                if isinstance(k, str) and _COUNT_KEY_RX.fullmatch(k) and isinstance(v, int) and not isinstance(v, bool) \
                        and v > 0:
                    out[k] += v
    return {k: out[k] for k in sorted(out)}


def _coverage(paths):
    """커버리지 원장 셀과 일자 합성 함수(``lm27.collect.ledger`` — 파생물, 원문 없음). 없으면 (None, None)."""
    from lm27.collect import ledger
    load, comp = getattr(ledger, "load_cells", None), getattr(ledger, "composite", None)
    if load is None or comp is None:
        return None, None
    cells = load(paths)
    return (cells or None), comp


# ───────────────────────────── 모델 읽기 ─────────────────────────────
def _check_model(analysis) -> None:
    if not isinstance(analysis, Mapping) or analysis.get("schema") != "lm27.report":
        raise BuildRefused("보고서 모델이 아닙니다 — 분석 결과(lm27.report)를 넘기세요")
    if str(analysis.get("schema_version", "")).split(".")[0] != "1":
        raise BuildRefused("보고서 모델 판이 다릅니다 — 보고서를 다시 만드세요(lm27 report build)")
    if analysis.get("variant") != "full":
        raise BuildRefused("가림판 모델로는 팀 묶음을 만들지 않습니다 — 전체판 모델이 필요합니다")


def _tables(analysis, d0: date, d1: date):
    """(봉투 행 [[date, r, e, n, h]], 귀속 행 [[date, unit, tag, min]]) — 기간 안, 정렬."""
    t = analysis.get("tables") or {}
    env = t.get("envelope_daily") or {}
    cols = list(env.get("cols") or ["date", *S.TAGS])
    ix = {c: i for i, c in enumerate(cols)}
    env_rows = []
    for row in env.get("rows") or ():
        dd = _date(row[ix.get("date", 0)]) if row else None
        if dd is None or not d0 <= dd <= d1:
            continue
        env_rows.append([dd.isoformat()] + [_int(row[ix[tg]]) if tg in ix else 0 for tg in S.TAGS])
    env_rows.sort(key=lambda r: r[0])
    al = t.get("alloc_daily") or {}
    acols = list(al.get("cols") or ["date", "unit_id", "tag", "min"])
    ax = {c: i for i, c in enumerate(acols)}
    order = {tg: i for i, tg in enumerate(S.TAGS)}
    alloc = []
    for row in al.get("rows") or ():
        dd = _date(row[ax.get("date", 0)]) if row else None
        uid, tag, mins = row[ax.get("unit_id", 1)], row[ax.get("tag", 2)], _int(row[ax.get("min", 3)])
        if dd is None or not d0 <= dd <= d1 or tag not in order or mins <= 0 or not isinstance(uid, str):
            continue
        alloc.append([dd.isoformat(), uid, tag, mins])
    alloc.sort(key=lambda r: (r[0], r[1], order[r[2]]))
    return env_rows, alloc


def _refs_people(analysis) -> dict:
    """정수 참조 → who_key(로컬 해석용 — 묶음에 싣지 않는다)."""
    out = {}
    for r, v in ((analysis.get("refs") or {}).get("people") or {}).items():
        k = _g(v, "key", "")
        if isinstance(k, str) and k:
            out[str(r)] = k
    return out


def _start_key(u) -> int:
    """generic 제목 번호(역할 안 시작 시각 순번)의 정렬 키 — 'YYYY-MM-DDTHH:MM' → YYYYMMDDHHMM."""
    s = next((c.get("s") for c in (u.get("cycles") or ()) if isinstance(c, Mapping) and c.get("s")), None) \
        or _g(u.get("start"), "at", None) or (u.get("first_evidence") or "")
    digits = re.sub(r"\D", "", str(s))[:12]
    return int(digits.ljust(12, "0")) if digits else 0


class _ModelProposals:
    """``team_parts`` 의 제안 큐 자리(H §7.6 ``team_payload``) — 보고서 모델의 제안 목록으로."""

    def __init__(self, rows):
        self.rows = [r for r in rows or () if isinstance(r, Mapping)]

    def team_payload(self, _labels):
        return [{"proposal_id": str(r.get("proposal_id")), "label": str(r.get("label") or ""),
                 "domain_guess": str(r.get("domain_guess") or "")} for r in self.rows if r.get("proposal_id")]


# ───────────────────────────── 조각 만들기 ─────────────────────────────
def _boundary(b, off: int, side: str) -> dict:
    """W §4.11 — 모델 경계(kind·at·precision) → 묶음 형. 시작이 없으면 S2·none, 끝이 없으면(진행 중) kind null."""
    kinds = S.START_KINDS if side == "start" else S.END_KINDS
    if isinstance(b, Mapping) and b.get("kind") in kinds:
        prec = b.get("precision") if b.get("precision") in S.PRECISIONS else "none"
        return {"kind": b["kind"], "at": _iso_off(b.get("at"), off), "precision": prec}
    if side == "start":
        return {"kind": "S2", "at": None, "precision": "none"}
    return {"kind": None, "at": None, "precision": "none"}


def _grade_status(u) -> tuple[str, str]:
    st = str(u.get("status") or "")
    st = st if st in TEAM_STATUS else "open"
    g = str(u.get("grade") or "")
    if g not in TEAM_GRADES:                                  # O(진행 중)·Z 등 — 시작 근거 잠정 등급(W §4.11)
        sb = next((c.get("sb") for c in (u.get("cycles") or ()) if isinstance(c, Mapping) and c.get("sb")), "")
        g = SG.get(str(sb), "C")
    return g, st


def _spans(u, days: list[date]) -> list:
    """lead 정확히 1개(모델 lead 띠를 투입일까지 넓힘) + active = active_spans(귀속 일자, gap 2)."""
    lead = next((s for s in (u.get("spans") or ()) if isinstance(s, list) and len(s) == 3 and s[2] == "lead"), None)
    a = _date(lead[0]) if lead else None
    b = _date(lead[1]) if lead else None
    if days:
        a = min(a, days[0]) if a else days[0]
        b = max(b, days[-1]) if b else days[-1]
    if a is None or b is None:
        return []
    out = [[a.isoformat(), max(a, b).isoformat(), "lead"]]
    out += [[x.isoformat(), y.isoformat(), "active"] for x, y in S.active_spans(days, GANTT_GAP)]
    return out


def _catalog_ids() -> frozenset:
    from lm27.catalog import entries
    return frozenset(p.app_id for p in entries())


def _apps(u, catalog: frozenset) -> tuple[list, int, list]:
    """(카탈로그 앱 ID ≤ 20, 카탈로그 밖 분 합, 미상 exe [(app_id, 분)]) — 미상·사내 도구 이름은 싣지 않는다(TAB R-9)."""
    ids, unknown_min, unknown = [], 0, []
    for it in u.get("apps") or ():
        if not (isinstance(it, (list, tuple)) and len(it) == 2):
            continue
        a, m = str(it[0] or ""), _int(it[1])
        if a in catalog and S.RX["APP_ID"].fullmatch(a):
            if a not in ids and len(ids) < 20:
                ids.append(a)
        else:
            unknown_min += max(0, m)
            if a.startswith(UNKNOWN_PREFIX):
                unknown.append((a, max(0, m)))
    return ids, unknown_min, unknown


class _PeerBook:
    """who_key → (peer_key, scope) — 로컬 사람 사전의 사내 도메인 주소로(P §9.7). 주소를 모르면 None(peer_unresolved)."""

    def __init__(self, env: BuildEnv, pepper: str | None):
        self.people = (env.person_dir or {}).get("people") or {}
        self.pepper = pepper
        self.kr = env.keyring
        self.doms = env.internal_domains
        self.cache: dict = {}

    def key_of_addrs(self, addrs):
        from lm27.privacy import peer_key
        if not self.pepper and self.kr is None:
            return None
        for a in sorted({str(x).strip().lower() for x in addrs or () if isinstance(x, str) and "@" in x}):
            k, scope = peer_key(self.pepper, a, self.doms, self.kr)
            if k:
                return k, scope
        return None

    def of(self, who: str):
        if who not in self.cache:
            rec = self.people.get(who)
            self.cache[who] = self.key_of_addrs(_g(rec, "smtp", ())) if isinstance(rec, Mapping) \
                and not rec.get("self") else None
        return self.cache[who]

    def self_key(self):
        for _w, rec in sorted(self.people.items()):
            if isinstance(rec, Mapping) and rec.get("self"):
                k = self.key_of_addrs(rec.get("smtp"))
                if k:
                    return k
        return None


def _role_map(sel: Mapping, parts: Mapping) -> dict:
    """모델 role_id → 팀 role_id(개인 L_ 코드 대응·제안 빼기로 바뀔 수 있다). 여럿이 하나로 모이면 투입 큰 모델 역할 순."""
    agg: dict = defaultdict(lambda: defaultdict(int))
    for uid, u in sel.items():
        agg[str(u.get("role_id") or "")][parts["units"][uid]["role_id"]] += _int(u.get("_effort"))
    out = {}
    for mr, tm in agg.items():
        out[mr] = sorted(tm.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return out


def _patch_projects(parts: dict, model_projects) -> None:
    """team_parts 가 영역을 못 정한 과제(유효 레지스트리에 없는 P-…)는 모델 영역(5종일 때)으로 싣고, 그것도 없으면 그
    역할을 과제 없음(UNC)으로 돌려 role_id 를 다시 계산한다 — 묶음 안 참조 무결성(TAB §2.3.2 roles[].project_id)."""
    have = {p["project_id"] for p in parts["projects"]}
    mdom = {str(_g(p, "project_id", "")): str(_g(p, "domain", "")) for p in model_projects or () if isinstance(p, Mapping)}
    newp = {}
    remap = {}
    for r in parts["roles"]:
        pid = r.get("project_id")
        if pid and pid not in have:
            dom = mdom.get(pid, "")
            if dom in S.DOMAINS:
                newp[pid] = dom
            else:
                nid = S.role_id_of(None, r["field"], r["function"])
                remap[r["role_id"]] = nid
                r["project_id"] = None
                r["role_id"] = nid
    parts["projects"] = sorted([*parts["projects"], *({"project_id": k, "domain": v} for k, v in newp.items())],
                               key=lambda p: p["project_id"])
    if remap:
        roles = {}
        for r in parts["roles"]:
            roles.setdefault(r["role_id"], r)
        parts["roles"] = [roles[k] for k in sorted(roles)]
        for row in parts["units"].values():
            row["role_id"] = remap.get(row["role_id"], row["role_id"])


def _step_name(code: str) -> str:
    from lm27.vocab.steps import STEP_TYPES
    st = STEP_TYPES.get(code)
    return st.name if st is not None else code


def _label_or(tc: TextCtx, value, maxlen: int, field_name: str, *fallbacks) -> str:
    """자유 문자열 → 통과값, 걸리거나 비면 대체 라벨(차례로 같은 검사), 끝까지 안 되면 ''(검사 1단이 다시 본다)."""
    v = tc.text(value, maxlen, field_name) if value else ""
    if v:
        return v
    for fb in fallbacks:
        if not fb:
            continue
        w = tc.text(fb, maxlen, field_name + "#fallback")
        if w:
            return w
    return ""


def _workflow(wf, rid: str, units: list, tc: TextCtx, detail: bool) -> dict | None:
    steps = [s for s in (wf.get("steps") or ()) if isinstance(s, Mapping) and _int(s.get("no")) >= 1]
    if not steps:
        return None
    bn: dict = defaultdict(set)
    for b in wf.get("bottlenecks") or ():
        if isinstance(b, Mapping) and b.get("kind") in ("wait", "work"):
            bn[_int(b.get("no"))].add(b["kind"])
    sample = wf.get("sample") if wf.get("sample") in ("ok", "thin") else "ok"
    out_steps, nos = [], set()
    for s in sorted(steps, key=lambda x: _int(x.get("no"))):
        no, code = _int(s.get("no")), str(s.get("code") or "")
        if no in nos or not S.RX["VOCAB_CODE"].fullmatch(code):
            continue
        nos.add(no)
        name = str(s.get("name") or "") or _step_name(code)
        label = (_label_or(tc, name or _step_name(code), 30, "workflows[].steps[].label", _step_name(code), code)
                 if detail else _label_or(tc, s.get("label"), 30, "workflows[].steps[].label", name,
                                          _step_name(code), code))
        kinds = bn.get(no, set())
        ws = _num(s.get("work_share"))
        wim = s.get("wait_in_median_min")
        out_steps.append({
            "no": no, "type": code, "label": label, "n": max(0, _int(s.get("n"))),
            "median_min": max(0, _int(s.get("median_min"))),
            "agent_grade": s.get("agent_grade") if s.get("agent_grade") in GRADE3 else "",
            "subagent": s.get("subagent") if s.get("subagent") in FITS else "부적합",
            "why": [w for w in (s.get("why") or ()) if w in WHY],
            "wait_in_median_min": max(0, int(wim)) if isinstance(wim, int) and not isinstance(wim, bool) else None,
            "work_share": min(1.0, max(0.0, float(ws))) if ws is not None else None,
            "bottleneck": "both" if len(kinds) == 2 else (next(iter(kinds)) if kinds else ""),
            "sample": sample})
    edges, seen = [], set()
    for e in list(wf.get("edges") or ()) + list(wf.get("edges_rest") or ()):
        if not (isinstance(e, (list, tuple)) and len(e) >= 3):
            continue
        i, j, n = _int(e[0]), _int(e[1]), _int(e[2])
        if i in nos and j in nos and (i, j) not in seen and n >= 0:
            seen.add((i, j))
            edges.append([i, j, n])
    edges.sort(key=lambda x: (-x[2], x[0], x[1]))
    return {"role_id": rid, "units": sorted(units), "steps": out_steps, "edges": edges}


def _months_summary(analysis, d0, d1, au_date, env_rows, alloc, std: int):
    """summary.months[] — TAB §2.3.2 식. 분석과 같은 범위의 달은 덮은 근무일·부재 = 모델 값, 일부만이면 days[] 로."""
    run = analysis.get("run") or {}
    a0, a1 = _date(run.get("from")), _date(run.get("to"))
    mrows = {str(m.get("m")): m for m in analysis.get("months") or () if isinstance(m, Mapping)}
    days = {str(x.get("d")): x for x in analysis.get("days") or () if isinstance(x, Mapping)}
    out = []
    for m in S.months_between(d0, d1):
        mr = mrows.get(m)
        if mr is None:
            raise BuildRefused(f"분석 결과에 {m} 달이 없습니다 — 그 기간으로 분석한 뒤 다시 만드세요")
        first, last = _month_bounds(m)
        lo, hi = max(d0, first), min(d1, last)
        wd = _int(mr.get("workdays"))
        if a0 and a1 and (lo, hi) == (max(a0, first), min(a1, last)):
            covered = _int(mr.get("covered_workdays"))
            absence = float(_num(mr.get("absence_days")) or 0.0)
        else:
            covered, absence = 0, 0.0
            d = lo
            while d <= min(hi, au_date):
                x = days.get(d.isoformat())
                if x is not None and not x.get("hol"):
                    covered += 1
                    absence += min(1.0, max(0.0, float(_num(x.get("leave")) or 0.0)))
                d += timedelta(days=1)
        tag = dict.fromkeys(S.TAGS, 0)
        for r in env_rows:
            if r[0][:7] == m:
                for tg, v in zip(S.TAGS, r[1:], strict=True):
                    tag[tg] += v
        e = sum(tag.values())
        att = sum(r[3] for r in alloc if r[0][:7] == m)
        avail = covered - absence
        out.append({"month": m, "workdays": wd, "covered_workdays": covered, "absence_days": absence,
                    "avail_days": avail, "envelope_min": e, "by_tag": tag, "attributed_min": att,
                    "unattributed_min": e - att, "mm": (e / (std * wd)) if std and wd else 0.0,
                    "load_pct": (e / (std * avail) * 100) if avail > 0 and std else None})
    return out


def _quality(analysis, months: list, d0, d1, au_date, n_unresolved, env: BuildEnv, rejected: int) -> dict:
    """측정 품질 — 등급·사유 = R §4.9 기간 등급(같은 함수 ``period_quality`` — RP15) + 동료 미해결 수(R §4.5)."""
    from lm27.report.analysis.quality import period_quality
    mq = {str(m.get("m")): (m.get("quality") or {}) for m in analysis.get("months") or () if isinstance(m, Mapping)}
    pq = period_quality({m: mq.get(m, {}) for m in months})
    reasons = [str(r) for r in pq.get("reasons") or () if isinstance(r, str) and 0 < len(r) <= REASON_MAX]
    if n_unresolved:
        reasons.append(f"peer_unresolved:{min(n_unresolved, 9999)}")
    grade = pq.get("grade") if pq.get("grade") in S.QUALITY_GRADES else ""
    q: dict = {"grade": grade, "reasons": reasons}
    est = env_min = 0
    for x in analysis.get("days") or ():
        dd = _date(_g(x, "d", ""))
        if dd and d0 <= dd <= d1:
            est += _int(_g(x, "est_min", 0))
            env_min += _int(_g(x, "env_min", 0))
    q["estimated_min_ratio"] = min(1.0, est / env_min) if env_min > 0 else 0.0
    qo = qr = 0
    for it in analysis.get("queue") or ():
        dd = _date(_g(it, "date", "") or "")
        if dd is not None and not d0 <= dd <= d1:
            continue
        if _g(it, "status", "open") == "open":
            qo += 1
        else:
            qr += 1
    q["confirm_queue"] = {"open": qo, "resolved": qr}
    q["team_text_rejected"] = rejected
    flags = analysis.get("flags") or {}
    ai = man = rule = 0
    for v in (flags.get("label_sources") or {}).values():
        ai += _int(_g(v, "ai", 0))
        man += _int(_g(v, "manual", 0))
        rule += _int(_g(v, "rule", 0))
    used = flags.get("copilot") in ("ai", "partial") or ai > 0
    q["copilot"] = {"used": bool(used), "items": ai + man, "failed_items": rule if used else 0}
    cov = _coverage_rows(env, analysis, d0, d1, au_date)
    if cov is not None:
        q["coverage"], q["pcs"] = cov
    return q


def _coverage_rows(env: BuildEnv, analysis, d0, d1, au_date):
    """커버리지 원장 → (coverage[축], pcs[]) — 묶음 기간 근무일(분석 시각까지)만. 원장이 없으면 None(선택 필드 생략)."""
    cells = env.coverage_cells
    if not cells or env.coverage_composite is None:
        return None
    hi = min(d1, au_date)
    work = sorted(str(x.get("d")) for x in analysis.get("days") or ()
                  if isinstance(x, Mapping) and not x.get("hol") and _date(x.get("d")) and d0 <= _date(x.get("d")) <= hi)
    wset = set(work)
    inside = [c for c in cells if isinstance(c, Mapping) and c.get("date") in wset]
    comp = env.coverage_composite(inside)
    coverage = []
    for ax in S.COV_AXES:
        axc = [c for c in inside if c.get("kind_axis") == ax]
        if not axc:
            continue
        days = dict.fromkeys(COV_STATES, 0)
        for d in work:
            st = _g(comp.get((d, ax)), "status", "not_attempted")
            days[st if st in days else "not_attempted"] += 1
        n_min = sum(_int(c.get("n_minute")) for c in axc)
        n_all = n_min + sum(_int(c.get("n_date")) + _int(c.get("n_unknown")) for c in axc)
        coverage.append({"axis": ax, "days": {k: v for k, v in days.items() if v},
                         "srcs": sorted({str(c.get("src")) for c in axc if _SRC_RX.fullmatch(str(c.get("src") or ""))}),
                         "exact_ratio": (n_min / n_all) if n_all else None})
    pcs = []
    for i, p in enumerate(env.pcs, start=1):
        mine = [c for c in inside if c.get("pc_id") == p["_pc"] and c.get("kind_axis") == "pc"]
        obs = {c["date"] for c in mine if c.get("status") == "ok" and _int(c.get("n")) > 0}
        evd = {c["date"] for c in mine if c.get("src") == "pc.events" and c.get("status") == "ok" and _int(c.get("n")) > 0}
        row = {"ord": i, "label_auto": p["label_auto"] or f"PC{i}", "kind": p["kind"] or "desktop",
               "agent_impl": p["agent_impl"], "observed_days": len(obs), "event_days": len(evd)}
        if p["probe"]:
            row["probe"] = {k: p["probe"][k] for k in sorted(p["probe"])}
        pcs.append(row)
    return coverage, pcs


def _catalog_proposals(units_unknown: dict, env: BuildEnv, tc: TextCtx) -> list:
    """미상 프로그램 라벨링 제안(team.shareUnknownApps — TAB §2.3.2 · CP §6.4). exe 이름은 라벨 검사를 통과한 것만."""
    out = []
    for app, (mins, days) in sorted(units_unknown.items()):
        exe = app[len(UNKNOWN_PREFIX):]
        if not _EXE_RX.fullmatch(exe) or tc.text(exe, 64, "catalog_proposals[].exe") != exe:
            continue
        meta = env.exe_meta.get(exe) if isinstance(env.exe_meta, Mapping) else None
        comp = _label_or(tc, _g(meta, "company", ""), 40, "catalog_proposals[].company")
        prod = _label_or(tc, _g(meta, "product", ""), 40, "catalog_proposals[].product")
        out.append({"exe": exe, "company": comp, "product": prod, "n_days": len(days), "minutes": mins})
    return out


# ───────────────────────────── 빌더 ─────────────────────────────
def build_team_bundle(analysis, period, registry, pepper, overrides, cfg, *, env: BuildEnv | None = None,
                      now=None) -> tuple[dict, dict]:
    """TAB §8.2 ``build_team_bundle(analysis, period, registry, pepper, overrides, cfg) -> (obj, audit)``.

    registry = 팀 레지스트리 캐시(원본 dict 또는 None — pepper·검증 대조용), pepper = 64hex 또는 None,
    overrides = ``data\\team\\overrides.json`` 내용. ``env`` 가 없으면 ``load_env(Paths(), …)``. 막히면 ``BuildRefused``(rc 2),
    마지막 검사에 걸리면 ``BuildFailed``(rc 1)."""
    from lm27 import LM27_VERSION
    from lm27.hier.team_out import team_parts
    from lm27.privacy import RULES_HASH, RULES_VERSION, check_team_payload
    _check_model(analysis)
    d0, d1 = _period(period)
    if env is None:
        from lm27.paths import Paths
        env = load_env(Paths(), cfg, period=period, registry=registry)
    now = _now(now)
    run = analysis.get("run") or {}
    a0, a1 = _date(run.get("from")), _date(run.get("to"))
    if a0 is None or a1 is None or d0 < a0 or d1 > a1:
        raise BuildRefused(f"팀 묶음 기간이 지금 분석 결과 기간({run.get('from')}~{run.get('to')}) 밖입니다 — "
                           "그 기간으로 분석한 뒤 다시 만드세요")
    model_off = _int(run.get("tz_offset_min"), _int(cfg["time.tzOffsetMin"]))
    work_off = _int(cfg["time.tzOffsetMin"])
    as_of = _LOCAL_DT_RX.match(str(run.get("as_of") or ""))
    as_of_d = _date(as_of.group(1)) if as_of else a1
    if as_of_d is None or as_of_d < d0:
        raise BuildRefused("그 기간은 아직 분석되지 않았습니다 — 분석 시각 이후의 기간입니다")
    if as_of_d > d1:
        au, au_date = f"{d1.isoformat()}T23:59:59" + _off_str(model_off), d1
    else:
        au, au_date = _iso_off(f"{as_of.group(1)}T{as_of.group(2)}", model_off), as_of_d
    ov = overrides if isinstance(overrides, Mapping) else {}
    ov_units = {k: v for k, v in (ov.get("units") or {}).items() if isinstance(k, str) and v in ("title", "detail")}
    ov_needs = {k for k, v in (ov.get("needs") or {}).items() if v == "drop"}
    ov_matches = {k for k, v in (ov.get("matches") or {}).items() if v == "drop"}
    ov_subs = {k for k, v in (ov.get("subagents") or {}).items() if v == "drop"}
    tc = TextCtx(env.gctx, env.local_words)
    pepper = pepper if isinstance(pepper, str) and _PEPPER_RX.fullmatch(pepper) else None
    std = _int((analysis.get("denominator") or {}).get("std_day_min"), 480) or 480

    # ── 정수 분 표(기간 안) · 단위업무 선택(투입이 있는 것만 — W §4.11 '미착수·투입 0 은 올리지 않는다') ──
    env_rows, alloc = _tables(analysis, d0, d1)
    model_units = {str(u.get("unit_id")): u for u in analysis.get("units") or () if isinstance(u, Mapping)}
    effort: dict = defaultdict(int)
    adays: dict = defaultdict(set)
    for d, uid, _t, m in alloc:
        effort[uid] += m
        adays[uid].add(d)
    missing = sorted(u for u in effort if u not in model_units)
    if missing:
        raise BuildFailed([f"alloc_daily: 모델에 없는 단위업무 {len(missing)}개"])
    sel = {}
    for uid in sorted(effort):
        u = model_units[uid]
        row = {k: u.get(k) for k in ("unit_id", "project_id", "proposal_id", "field", "function", "activity_type",
                                     "ax_link", "title", "role_id", "cycles", "start", "end", "grade", "status",
                                     "lead_min", "first_evidence", "last_evidence", "spans", "peers", "apps", "docs")}
        row["_effort"] = effort[uid]
        sel[uid] = row

    # ── 분류 조각(H §12.4 — team_parts) ──
    props = [p for p in analysis.get("proposals") or () if isinstance(p, Mapping)]
    drop_props = {str(p.get("proposal_id")): "drop" for p in props if p.get("domain_guess") not in S.DOMAINS}
    for k, v in (ov.get("proposals") or {}).items():
        if v == "drop":
            drop_props[str(k)] = "drop"
    labels = {uid: {"project": u.get("project_id"), "proposal_id": u.get("proposal_id"),
                    "field": u.get("field") or "ETC", "func": u.get("function") or "ETC",
                    "wtype": u.get("activity_type") or "OFFICE", "ax_link": bool(u.get("ax_link")),
                    "title": str(u.get("title") or "")} for uid, u in sel.items()}
    parts = team_parts(labels, env.eff_registry, _ModelProposals(props), {"units": ov_units, "proposals": drop_props},
                       cfg=cfg, starts={uid: _start_key(u) for uid, u in sel.items()}, text_check=tc.text,
                       title_mode=str(cfg["team.unitTitleMode"]))
    _patch_projects(parts, analysis.get("projects"))
    rmap = _role_map(sel, parts)
    team_role_units: dict = defaultdict(list)
    for uid in sel:
        team_role_units[parts["units"][uid]["role_id"]].append(uid)

    # ── 동료(TAB §2.3.3) ──
    book = _PeerBook(env, pepper)
    who_of = _refs_people(analysis)
    full_period = d0 <= a0 and d1 >= a1
    peer_units: dict = defaultdict(set)
    peer_effort: dict = defaultdict(int)
    unresolved = set()
    scope_of: dict = {}
    for uid, u in model_units.items():
        if not full_period and uid not in sel:
            continue
        eff = sel[uid]["_effort"] if uid in sel else _int(u.get("effort_min"))
        keys = set()
        for ref in u.get("peers") or ():
            who = who_of.get(str(ref))
            if not who:
                continue
            k = book.of(who)
            if k is None:
                unresolved.add(who)
                continue
            keys.add(k[0])
            scope_of[k[0]] = k[1]
        for k in keys:
            peer_units[k].add(uid)
            peer_effort[k] += eff
    peers = [{"peer_key": k, "scope": scope_of[k], "units": len(peer_units[k]), "shared_effort_min": peer_effort[k]}
             for k in peer_units]
    peers.sort(key=lambda p: (-p["shared_effort_min"], -p["units"], p["peer_key"]))
    selfk = book.self_key()

    # ── 단위업무 ──
    catalog = _catalog_ids()
    unknown_use: dict = {}
    units_out = []
    detail_roles = set()
    for uid, u in sel.items():
        tp = parts["units"][uid]
        detail = ov_units.get(uid) == "detail"
        if detail:
            detail_roles.add(tp["role_id"])
        days = sorted(date.fromisoformat(x) for x in adays[uid])
        grade, status = _grade_status(u)
        apps, unk_min, unknown = _apps(u, catalog)
        for a, m in unknown:
            mins, ds = unknown_use.get(a, (0, set()))
            unknown_use[a] = (mins + m, ds | adays[uid])
        lead_min = u.get("lead_min")
        upeers = sorted({k[0] for k in (book.of(who_of.get(str(r), "")) for r in u.get("peers") or ()
                                        if who_of.get(str(r))) if k})
        units_out.append({
            "unit_id": uid, "role_id": tp["role_id"], "title": tp["title"], "title_mode": tp["title_mode"],
            "activity_type": tp["activity_type"], "ax_link": bool(tp["ax_link"]),
            "start": _boundary(u.get("start"), model_off, "start"),
            "end": _boundary(u.get("end") if status != "open" else None, model_off, "end"),
            "grade": grade, "status": status,
            "first_evidence": u.get("first_evidence") if _date(u.get("first_evidence")) else None,
            "last_evidence": u.get("last_evidence") if _date(u.get("last_evidence")) else None,
            "lead_time_h": (lead_min / 60) if isinstance(lead_min, int) and not isinstance(lead_min, bool)
            and lead_min >= 0 else None,
            "effort_min": u["_effort"], "spans": _spans(u, days),
            "peers": [] if detail else upeers, "apps": [] if detail else apps,
            "apps_unknown_min": 0 if detail else unk_min,
            "evidence_n": {} if detail else {"file": len(u.get("docs") or ()), "app": len(u.get("apps") or ())}})

    # ── 워크플로우(RP15 — 모델 역할 워크플로우 그대로) ──
    wfs = (analysis.get("workflows") or {}).get("roles") or {}
    best_model_role: dict = {}
    for mr, tr in sorted(rmap.items()):
        cur = best_model_role.get(tr)
        e = sum(sel[u]["_effort"] for u in sel if str(sel[u].get("role_id")) == mr)
        if cur is None or e > cur[1] or (e == cur[1] and mr < cur[0]):
            best_model_role[tr] = (mr, e)
    workflows = []
    for tr in sorted(team_role_units):
        mr = best_model_role.get(tr, ("", 0))[0]
        wf = wfs.get(mr) if isinstance(wfs, Mapping) else None
        if isinstance(wf, Mapping):
            w = _workflow(wf, tr, team_role_units[tr], tc, tr in detail_roles)
            if w is not None:
                workflows.append(w)
    step_nos = {w["role_id"]: {s["no"]: s for s in w["steps"]} for w in workflows}

    # ── agentic(RP15 — 모델 team 절을 역할·단위업무만 묶음 범위로) ──
    in_bundle = set(sel)
    team = analysis.get("team") or {}
    matches: dict = {}
    for mt in team.get("agentic_matches") or ():
        if not isinstance(mt, Mapping):
            continue
        aid, st, gr = str(mt.get("agent_id") or ""), str(mt.get("step_type") or ""), mt.get("grade")
        tr = rmap.get(str(mt.get("role_id") or ""))
        us = sorted(set(mt.get("units") or ()) & in_bundle)
        if not (tr and us and aid.startswith("AG") and S.RX["REG_ID"].fullmatch(aid)
                and S.RX["VOCAB_CODE"].fullmatch(st) and gr in GRADE3):
            continue
        if f"{aid}|{tr}|{st}" in ov_matches:
            continue
        key = (aid, tr, st)
        old = matches.get(key)
        if old is None:
            matches[key] = {"agent_id": aid, "role_id": tr, "step_type": st, "grade": gr, "units": us}
        else:
            old["units"] = sorted(set(old["units"]) | set(us))
            if S.AGENT_GRADES.index(gr) < S.AGENT_GRADES.index(old["grade"]):
                old["grade"] = gr
    ag = analysis.get("agentic") or {}
    needs = []
    for nd in ag.get("needs") or ():
        if not isinstance(nd, Mapping):
            continue
        nid, st, gr = str(nd.get("need_id") or ""), str(nd.get("step_type") or ""), nd.get("grade")
        us = sorted(set(nd.get("units") or ()) & in_bundle)
        if not (_NEED_RX.fullmatch(nid) and S.RX["VOCAB_CODE"].fullmatch(st) and gr in GRADE3 and us) \
                or nd.get("dropped") or nid in ov_needs:
            continue
        label = _label_or(tc, nd.get("label") or nd.get("name"), 40, "agentic.needs[].label",
                          f"{_step_name(st)} 자동화")
        fpm = _num(nd.get("freq_per_month"))
        needs.append({"need_id": nid, "step_type": st, "label": label, "grade": gr,
                      "freq_per_month": max(0.0, float(fpm)) if fpm is not None else 0.0, "units": us,
                      "src": "ai" if nd.get("by") == "ai" else "rule"})
    needs.sort(key=lambda n: n["need_id"])
    subs: dict = {}
    for sa in team.get("subagents") or ():
        if not isinstance(sa, Mapping):
            continue
        mr = str(sa.get("role_id") or "")
        tr = rmap.get(mr)
        if not tr or sa.get("fit") not in FITS or tr in ov_subs:
            continue
        if best_model_role.get(tr, ("", 0))[0] != mr:
            continue
        chain = []
        for c in sa.get("chain") or ():
            no = _int(_g(c, "step_no", 0))
            stp = step_nos.get(tr, {}).get(no)
            if stp is None:
                continue
            chain.append({"step_no": no, "proposal": _label_or(
                tc, _g(c, "proposal", ""), 40, "agentic.subagents[].chain[].proposal",
                f"{stp['label']} 단계 보조", f"{_step_name(stp['type'])} 단계 보조")})
        subs[tr] = {"role_id": tr, "fit": sa["fit"], "chain": sorted(chain, key=lambda c: c["step_no"])}

    # ── 사람·기간·요약·품질 ──
    member = str(cfg["team.memberId"] or "")
    if member and not (member.startswith("M") and S.RX["REG_ID"].fullmatch(member)):
        env.warnings.append("구성원 ID 형식이 아니어서 싣지 않았습니다(M 으로 시작하는 레지스트리 ID)")
        member = ""
    raw_label = str(cfg["team.selfLabel"] or "")
    self_label = tc.label_only(raw_label, 20, "person.self_label") if raw_label else ""
    if self_label is None:
        env.warnings.append("팀 표시 라벨이 검사에 걸려 비웠습니다 — 서버가 '팀원-<키>' 로 표시합니다")
        self_label = ""
    months = S.months_between(d0, d1)
    summary = _months_summary(analysis, d0, d1, au_date, env_rows, alloc, std)
    gen_m = analysis.get("generator") or {}
    obj = {
        "schema": S.SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generator": {"app": APP_NAME, "app_version": LM27_VERSION,
                      "core_version": str(gen_m.get("core_version") or "")[:40],
                      "rules_ver": RULES_VERSION, "rules_hash": RULES_HASH,
                      "registry_version": _int(gen_m.get("registry_version")),
                      "calendar_version": str(gen_m.get("calendar_version") or "")[:40],
                      "catalog_version": str(gen_m.get("catalog_version") or "")[:40]},
        "built_at": _built_iso(now, work_off),
        "person": {"person_key": env.person_key, "member_id": member or None, "self_label": self_label,
                   "self_peer_key": selfk[0] if selfk else None,
                   "pepper_id": S.pepper_id_of(pepper) if pepper else None,
                   "field": str(parts.get("person", {}).get("field") or ""), "work_tz_offset_min": work_off,
                   "peer_scope": "team" if pepper else "personal"},
        "period": {"from": d0.isoformat(), "to": d1.isoformat(), "analyzed_until": au, "months": months},
        "summary": {"std_day_min": std, "months": summary},
        "envelope_daily": {"cols": ["date", *S.TAGS], "rows": env_rows},
        "alloc_daily": {"cols": ["date", "unit_id", "tag", "min"], "rows": alloc},
        "projects": [{"project_id": p["project_id"], "domain": p["domain"]} for p in parts["projects"]],
        "proposals": [{"proposal_id": p["proposal_id"], "kind": p["kind"], "label": p["label"],
                       "domain_guess": p["domain_guess"]} for p in parts["proposals"]],
        "roles": [{"role_id": r["role_id"], "project_id": r["project_id"], "proposal_id": r["proposal_id"],
                   "field": r["field"], "function": r["function"]} for r in parts["roles"] if r["role_id"] in team_role_units],
        "units": units_out,
        "workflows": workflows,
        "agentic": {"catalog_version": str(ag.get("catalog_version") or gen_m.get("catalog_version") or "")[:40],
                    "matches": [matches[k] for k in sorted(matches)], "needs": needs,
                    "subagents": [subs[k] for k in sorted(subs)]},
        "peers": peers,
        "peers_external": {k: max(0, _int(((analysis.get("peers") or {}).get("external") or {}).get(k)))
                           for k in ("customer", "partner", "other")},
        "privacy_counts": {k: v for k, v in (env.privacy_counts or {}).items() if _COUNT_KEY_RX.fullmatch(k)},
        "catalog_proposals": _catalog_proposals(unknown_use, env, tc) if cfg["team.shareUnknownApps"] else [],
        "quality": {},
        "integrity": {},
    }
    used_props = {r["proposal_id"] for r in obj["roles"] if r["proposal_id"]}
    obj["proposals"] = [p for p in obj["proposals"] if p["proposal_id"] in used_props]
    used_proj = {r["project_id"] for r in obj["roles"] if r["project_id"]}
    obj["projects"] = [p for p in obj["projects"] if p["project_id"] in used_proj]
    obj["quality"] = _quality(analysis, months, d0, d1, au_date, len(unresolved), env, tc.rejected)
    env_sum = sum(sum(r[1:]) for r in env_rows)
    al_sum = sum(r[3] for r in alloc)
    obj["integrity"] = {"envelope_min": env_sum, "alloc_min": al_sum, "unattributed_min": env_sum - al_sum,
                        "rows_env": len(env_rows), "rows_alloc": len(alloc), "units": len(units_out)}
    if model_off != work_off:
        env.warnings.append("분석 시간대와 지금 근무 시간대 설정이 다릅니다 — 분석을 다시 하면 맞춰집니다")

    # ── 마지막 3중 검사(TAB §2.4) ──
    problems = []
    for path, maxlen, val in _free_strings(obj):
        if tc.bad(val, maxlen):
            problems.append(f"{path}: label")
    for v in check_team_payload(obj, env.gctx, S.TEAM_SPEC_V1) or ():
        problems.append(f"{v[0]}: {v[1]}")
    for nm in S.bytes_guard_hits(fsx.canon_bytes(obj)):
        problems.append(f"(bytes): {nm}")
    if problems:
        raise BuildFailed(problems)
    audit = {"team_text_rejected": tc.rejected, "fields": {k: tc.audit_fields[k] for k in sorted(tc.audit_fields)},
             "peer_unresolved": len(unresolved), "warnings": list(env.warnings)}
    return obj, audit


def _off_str(off: int) -> str:
    from lm27.util.tz import fmt_offset
    return fmt_offset(off)


def _free_strings(obj: Mapping):
    """(경로, 최대 길이, 값) — 마지막 검사 1단의 자유 문자열 필드(TAB §2.4)."""
    for i, u in enumerate(obj["units"]):
        yield f"units[{i}].title", 40, u["title"]
    for i, w in enumerate(obj["workflows"]):
        for j, s in enumerate(w["steps"]):
            yield f"workflows[{i}].steps[{j}].label", 30, s["label"]
    for i, p in enumerate(obj["proposals"]):
        yield f"proposals[{i}].label", 40, p["label"]
    for i, n in enumerate(obj["agentic"]["needs"]):
        yield f"agentic.needs[{i}].label", 40, n["label"]
    for i, sa in enumerate(obj["agentic"]["subagents"]):
        for j, c in enumerate(sa["chain"]):
            yield f"agentic.subagents[{i}].chain[{j}].proposal", 40, c["proposal"]
    yield "person.self_label", 20, ""                     # 본인 라벨은 로컬 사전 예외 — 1단에서 다시 보지 않는다(2단이 본다)


def size_blockers(raw: bytes, cfg) -> list:
    """클라이언트 상한 ``team.maxBundleMb`` — 넘으면 보내기·내보내기를 막는다(TAB §2.3.2)."""
    lim = int(cfg["team.maxBundleMb"])
    if len(raw) > lim * MB:
        return [f"묶음이 {len(raw) // MB + 1}MB 로 상한({lim}MB)을 넘습니다 — 기간을 나눠 다시 만드세요"]
    return []


# ───────────────────────────── 만들고 대기열에 넣기 ─────────────────────────────
def build_and_queue(analysis, period, cfg, *, paths=None, now=None, env: BuildEnv | None = None, sink=None,
                    send=None):
    """TAB §2.7 — 허용 목록 빌드 → 공용 검증 → 정규 바이트 1벌 → 대기열(같은 바이트면 그대로, 같은 기간 다른 미전송은
    대체됨) → 정제 감사 ``gate_team``. 반환 = ``lm27.team.queue.QueueItem``(``rc``·``message``).
    ``team.autoSend`` 이고 막힌 것이 없으면 승인해 바로 보낸다(TAB §2.8). ``sink``·``send`` 는 시험 주입점."""
    from lm27.bundle.lock import BundleLock
    from lm27.team import queue as Q
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    now = _now(now)
    reg = registry_cache(paths)
    try:
        d0, d1 = _period(period)
        if env is None:
            env = load_env(paths, cfg, period=period, registry=reg)
        obj, audit = build_team_bundle(analysis, period, reg, pepper_of(reg), load_overrides(paths), cfg, env=env, now=now)
    except BuildRefused as e:
        return _said(Q.QueueItem.result(2, str(e)))
    except BuildFailed as e:
        return _said(Q.QueueItem.result(1, str(e), problems=e.problems))
    from lm27.time.calendar import load_calendar
    errs = S.validate_team_bundle(obj, registry=reg, side="client", calendar=load_calendar(paths, reg),
                                  gap=GANTT_GAP)
    raw = fsx.canon_bytes(obj)
    sha = fsx.sha256_hex(raw)
    blockers = list(dict.fromkeys([e.msg for e in S.blocking(errs)] + size_blockers(raw, cfg)))
    warns = sorted({e.code for e in errs if not e.blocking})
    per = f"{d0.isoformat()}_{d1.isoformat()}"
    try:
        with BundleLock(paths, "team_build", cfg=cfg):
            same = Q.find_pending(paths, sha)
            if same is not None:
                same.rc, same.message = 4, "같은 묶음이 이미 대기 중입니다(승인 상태 유지)"
                return _said(same)
            superseded = Q.supersede(paths, per, sha, now=now)
            meta = Q.new_meta(sha, len(raw), per, env.person_key, obj["built_at"], env.built_on, blockers, now=now,
                              warnings=warns + list(audit.get("warnings") or ()),
                              check={"violations": 0, "team_text_rejected": audit["team_text_rejected"],
                                     "peer_unresolved": audit["peer_unresolved"]})
            item = Q.write_pending(paths, per, raw, meta)
    except Q.QueueError as e:
        return _said(Q.QueueItem.result(1, str(e)))
    _audit_gate_team(paths, env, sha, len(raw), audit, sink)
    if blockers:
        item.rc, item.message = 2, "묶음을 만들었지만 보낼 수 없습니다: " + "; ".join(blockers)
        return _said(item)
    if cfg["team.autoSend"]:
        Q.approve(item, now=now)
        res = (send or Q.send_due)(cfg, paths=paths, now=now, only=(item.name,), trigger="build")
        item = Q.find_item(paths, item.name) or item
        item.message = "자동 전송 설정이라 승인 없이 보냈습니다" if _g(res, "sent", 0) else \
            "자동 전송 설정 — 지금은 보내지 못해 대기열에서 다시 보냅니다"
    else:
        item.message = "팀 묶음을 만들었습니다 — 미리보기에서 확인하고 [보내기]를 누르세요"
    if superseded:
        item.message += f"(같은 기간 이전 묶음 {len(superseded)}개는 대체됨)"
    item.rc = 0
    return _said(item)


def _said(item):
    """사람용 한 줄(계약 §8.6 — text 모드는 stderr, jsonl 모드는 이벤트). 값·경로 없이 결과 문구만."""
    from lm27.util import events
    events.emit("warn" if item.rc in (1, 2) else "msg", text_ko=item.message or "팀 묶음")
    return item


def _audit_gate_team(paths, env: BuildEnv, sha: str, nbytes: int, audit: Mapping, sink=None) -> None:
    """정제 감사 ``gate_team``(P §15.2·§15.4): 전송 바이트 sha · 자유 문자열 거절 수(필드별) · 동료 미해결 수."""
    from lm27.privacy import AuditSink
    au = sink if sink is not None else AuditSink.open(paths.data(), env.pc_id, "team", "team", paths=paths)
    n = int(audit.get("team_text_rejected") or 0)
    if n:
        au.add("dropped", "team_text", n)
    for f, k in sorted((audit.get("fields") or {}).items()):
        code = re.sub(r"[^a-z0-9_.]", "", f.replace("[]", "").replace("#fallback", ".fallback").lower())[:40]
        if code and k:
            au.add("gate_team", code, int(k))
    if audit.get("peer_unresolved"):
        au.add("gate_team", "peer_unresolved", int(audit["peer_unresolved"]))
    au.flush("gate_team", rows_in=1, rows_out=1, out_sha256=sha)


# ───────────────────────────── 미리보기 가림(TAB §2.5) ─────────────────────────────
def load_overrides(paths) -> dict:
    r"""``data\team\overrides.json``(``lm27.team_overrides/1``) — 없거나 깨졌으면 빈 가림."""
    obj = fsx.read_json(paths.team_overrides(), None, want=dict) or {}
    out = {"schema": OVERRIDES_SCHEMA}
    for k in ("units", "needs", "matches", "subagents", "proposals"):
        v = obj.get(k)
        out[k] = {str(a): str(b) for a, b in v.items() if isinstance(a, str) and isinstance(b, str)} \
            if isinstance(v, Mapping) else {}
    return out


def _save_overrides(paths, ov: Mapping) -> None:
    fsx.atomic_write(paths.team_overrides(), fsx.canon_bytes({k: ov[k] for k in sorted(ov)}))


def _edit_overrides(paths, part: str, key: str, value: str | None) -> bool:
    from lm27.bundle.lock import BundleLock
    with BundleLock(paths, "fg-write"):
        ov = load_overrides(paths)
        cur = ov[part].get(key)
        if cur == value or (value is None and cur is None):
            return False
        if value is None:
            ov[part].pop(key, None)
        else:
            ov[part][key] = value
        ov[part] = {k: ov[part][k] for k in sorted(ov[part])}
        _save_overrides(paths, ov)
    return True


def set_mask(paths, unit_id, mode) -> dict:
    """단위업무 가림 ``title`` · ``detail`` · ``none``(되돌리기) — 다음 빌드부터 적용(TAB §2.5). rc 0 바뀜 · 4 그대로 · 1 형식."""
    if not isinstance(unit_id, str) or not _UNIT_RX.fullmatch(unit_id):
        return {"rc": 1, "message": "단위업무 ID 형식이 아닙니다(u_ + 16진 10자리)"}
    if mode not in ("title", "detail", "none"):
        return {"rc": 1, "message": "가림은 title · detail · none 중 하나입니다"}
    changed = _edit_overrides(paths, "units", unit_id, None if mode == "none" else mode)
    msg = {"title": "제목을 가립니다", "detail": "세부를 가립니다(제목·동료·앱·단계 라벨)", "none": "가림을 되돌립니다"}[mode]
    return {"rc": 0 if changed else 4, "unit_id": unit_id, "mode": mode,
            "message": (msg + " — 다시 만들면 적용됩니다") if changed else "이미 그 상태입니다"}


def drop_need(paths, need_id) -> dict:
    """니즈 하나를 팀에 올리지 않기(TAB §2.5 · R §4.7.5). rc 0 바뀜 · 4 이미 뺌 · 1 형식."""
    if not isinstance(need_id, str) or not _NEED_RX.fullmatch(need_id):
        return {"rc": 1, "message": "니즈 ID 형식이 아닙니다(n_ + 16진 6자리)"}
    changed = _edit_overrides(paths, "needs", need_id, "drop")
    return {"rc": 0 if changed else 4, "need_id": need_id,
            "message": "다음 묶음부터 이 니즈를 빼고 보냅니다" if changed else "이미 빼 두었습니다"}
