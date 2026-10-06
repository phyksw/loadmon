# -*- coding: utf-8 -*-
r"""유효 레지스트리 = 내장 ⊕ 팀 ⊕ 개인 로컬(H §3 · §2.5, 계약 §2.10 · §3.19 · §3.20 · X-235 · X-237 · X-238 · X-247).

- `merge(team, local, cfg)`: 순수 함수(같은 입력 → 같은 출력). 예약 과제 5개·내장 어휘·내장 영역 키워드를 주입하고,
  팀 과제·개인 과제(`L-…`)·overlays·roots·어휘·규칙·never_pairs·domain_meta 를 H §3.4 표대로 합친다.
- `load_effective(paths, cfg, now)`: 팀 레지스트리를 고르는 유일한 함수(H §3.1) — 서버(주입된 fetch) → 304 면 캐시
  → 서버 불가면 오프라인 사본(캐시보다 판이 클 때·검증 통과 시) → 캐시 → 내장. 개인 로컬은
  `data\local_only\hier\registry_local.json`(깨지면 `.bak`). 자동 대응(maps_to)은 파일에 기록한다.
- `hier_hash(reg)`: 분류 결과에 영향을 주는 부분만의 해시(재분류 필요 판단, 로컬 전용).

`data\team\registry.json`(팀 레지스트리 캐시 — pepper 포함, 반출 금지)을 읽는 허용 모듈이다(L-22 · X-237).
pepper 는 유효 레지스트리에 싣지 않는다(분류기는 읽지 않는다 — X-238). 팀 서버는 분류기를 돌리지 않고
`merge(team, None, None)` 의 `resolve`·예약 표만 쓴다(H §3.6).

폴더·공용 문서는 평문을 들고 다니지 않는다: `folders` 는 개인 키로 해시한 폴더 키(`s`+16hex, 목적 `dir` —
계약 §4.2), `shared_docs` 는 문서군 키(`doc_key`)로 바꿔 둔다. 키링이 없으면 둘 다 비고 경고를 남긴다.
"""
import hashlib
import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from lm27.hier import registry_schema as _schema
from lm27.hier import vocab as _vocab
from lm27.hier.names import ukey
from lm27.hier.vocab import VocabItem
from lm27.paths import OFFLINE_REGISTRY_NAME  # noqa: F401 — 오프라인 사본 이름(TAB §5.3) 단일원 = lm27.paths(시험이 R. 로 씀)
from lm27.util import fsx

BUILTIN_EMPTY: dict = {"schema": _schema.SCHEMA, "version": 0}
EMPTY_LOCAL: dict = {"schema": _schema.LOCAL_SCHEMA}
LOCAL_FILE = "registry_local.json"
LOCAL_BAK = "registry_local.json.bak"
LEARNED_FILE = "rules_learned.json"
SOURCES = ("server", "cache", "offline", "builtin")
_SEG_RX = re.compile(r"[\s_\-.]+")
_PERSON_KEY_RX = re.compile(r"^p_[0-9a-f]{12}$")
# 퇴역·미상 코드를 읽을 때의 대체 코드(H §2.3.4 — 분야·기능은 ETC, 업무 유형은 결정 목록 '그 밖' 줄의 OFFICE)
READ_FALLBACK = {"fields": "ETC", "functions": "ETC", "activity_types": "OFFICE", "step_types": ""}


# ───────────────────────── 자료구조(H §3.4) ─────────────────────────
@dataclass(frozen=True)
class ProjectView:
    id: str
    name: str
    domain: str
    status: str
    merged_into: str | None
    origin: str                                     # team | local | reserved
    aliases: tuple[str, ...] = ()
    codenames: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    never: tuple[str, ...] = ()
    mail_domains: tuple[str, ...] = ()
    customers: tuple[str, ...] = ()
    partners: tuple[str, ...] = ()
    folder_keys: frozenset[str] = frozenset()       # folders 를 개인 키로 해시한 값 — 평문 폴더명은 들고 다니지 않는다
    apps: tuple[str, ...] = ()
    default_field: str = ""
    default_func: str = ""
    ax_link: bool = False
    shared_fams: frozenset[str] = frozenset()       # shared_docs → 문서군 키
    copilot_desc: str = ""
    period: tuple[str, str] | None = None
    proposal_id: str | None = None
    mask_name: bool = False
    maps_to: str | None = None                      # 개인 과제 → 대응된 팀 과제
    adopted: tuple[tuple[str, str], ...] = ()       # 팀 과제: (person_key, proposal_id)


@dataclass(frozen=True)
class Rule:
    """팀 규칙(`TR…`) 또는 개인 학습 규칙(`LK-…`·`LT-…`). 조건·결과는 (키, 값) 하나씩. 가점이다(H §2.3.5)."""
    id: str
    cond: tuple[str, str]
    then: tuple[str, str]
    w: float | None                                 # None = 기본 가중(teamRule·keyRule·learnedToken 설정)
    origin: str                                     # team | learned
    status: str = "active"
    note: str = ""


@dataclass(frozen=True)
class Agent:
    """agentic 카탈로그 항목(H §2.3.6). desc 는 팀 화면용 — 코파일럿에는 copilot_desc 만 보낸다."""
    id: str
    name: str
    axis: str = ""
    status: str = "running"
    desc: str = ""
    copilot_desc: str = ""
    step_types: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    owner_label: str = ""


def _resolve_in(projects: Mapping[str, ProjectView], pid):
    """merged_into·maps_to 사슬 끝. 순환이면 순환 안의 사전순 첫 ID, 사슬이 모르는 ID 로 나가면 마지막으로 아는 ID."""
    if pid is None:
        return None
    seen: list[str] = []
    cur = pid
    while True:
        pv = projects.get(cur)
        nxt = (pv.merged_into or pv.maps_to) if pv is not None else None
        if not nxt or nxt == cur or nxt not in projects:
            return cur
        if cur in seen:
            return min(seen[seen.index(cur):])
        seen.append(cur)
        cur = nxt


@dataclass(frozen=True)
class EffectiveRegistry:
    version: int
    hier_hash: str
    source: str
    projects: dict[str, ProjectView]                # 예약·팀·개인 모두(ID → 뷰)
    alias_ix: dict[str, str]                        # ukey(이름·별칭·코드네임) → 과제 ID(대표)
    folder_ix: dict[str, str]                       # 폴더 키 → 과제 ID(대표)
    root_ix: dict[str, str]                         # 감시 root_id → 과제 ID(대표)
    vocab: dict[str, dict[str, VocabItem]]          # fields/functions/activity_types/step_types → code → 항목(표 순서)
    domain_kw: dict[str, tuple[str, ...]]           # 영역 → 유효 키워드(head 모드)
    rules: tuple[Rule, ...]                         # 팀 규칙 + 개인 학습 규칙(active 만)
    never_pairs: frozenset[frozenset[str]]          # ukey 쌍
    public_suffix: dict[str, str]                   # 도메인 접미 → 계급
    agents: tuple[Agent, ...]
    catalog_version: str
    warnings: tuple[str, ...]
    domain_desc: dict[str, str] = field(default_factory=dict)      # 영역 설명 덮어쓰기(비면 내장)
    agent_axes: dict[str, str] = field(default_factory=dict)
    customers: tuple[dict, ...] = ()                # 팀 ∪ privacy.customers({id, names, domains})
    partners: tuple[dict, ...] = ()
    internal_domains: tuple[str, ...] = ()
    calendar: dict | None = None                    # 팀 레지스트리 달력(lm27.time.calendar.load_calendar 가 읽는다)
    pepper_id: str = ""
    person: dict = field(default_factory=dict)      # 개인 로컬 person{default_field, default_func}
    codename_review: dict | None = None             # 개인 로컬 초기 코드네임 검토 상태(H §8.1)
    local_maps: dict[str, str] = field(default_factory=dict)       # 이번 병합에서 새로 정해진 개인 과제 대응 {L-id: P-id}

    # ── 조회 ──────────────────────────────────────────────────────────
    def resolve(self, pid):
        """merged_into·maps_to 사슬 끝 대표 ID(순환이면 사슬 안 사전순 첫 ID). 모르는 ID 는 그대로."""
        return _resolve_in(self.projects, pid)

    def domain_of(self, pid) -> str:
        """과제 → 영역(H-I2: 레지스트리·예약 표의 값). None·모르는 ID → 'UNC'."""
        if pid is None:
            return "UNC"
        r = self.resolve(pid)
        if r in _vocab.RESERVED:
            return _vocab.RESERVED[r]
        pv = self.projects.get(r)
        return pv.domain if pv is not None else "UNC"

    def active_ids(self) -> list[str]:
        """분류 후보: 팀 active + maps_to 없는 개인 active(L-…), 예약·병합된 과제 제외, ID 정렬."""
        return sorted(p.id for p in self.projects.values()
                      if p.origin != "reserved" and p.status == "active" and not p.merged_into and not p.maps_to)

    def project(self, pid) -> ProjectView | None:
        return self.projects.get(pid)

    def name_of(self, pid) -> str:
        """대표 과제의 표시 이름(모르는 ID 는 ID 그대로)."""
        r = self.resolve(pid)
        pv = self.projects.get(r)
        return pv.name if pv is not None else str(r or "")

    def is_reserved(self, pid) -> bool:
        return pid in _vocab.RESERVED

    def vocab_codes(self, kind: str, include_retired: bool = False) -> list[str]:
        """어휘 코드(표 순서: 내장 → 팀 새 코드 → 개인 L_ 코드)."""
        return [c for c, it in self.vocab[kind].items() if include_retired or it.status == "active"]

    def read_code(self, kind: str, code) -> str:
        """옛 라벨 읽기: 활성 코드는 그대로, 퇴역 코드는 replaced_by 사슬(없으면 대체 코드), 모르는 코드는 대체 코드."""
        table = self.vocab[kind]
        cur, seen = code, set()
        while cur in table and table[cur].status != "active" and cur not in seen:
            seen.add(cur)
            cur = table[cur].replaced_by or READ_FALLBACK[kind]
        if cur in table and table[cur].status == "active":
            return cur
        return READ_FALLBACK[kind]

    def team_code(self, kind: str, code) -> str:
        """팀 묶음에 실을 코드: 개인 `L_` 코드는 maps_to(팀·내장 코드) 또는 대체 코드(H §12.4)."""
        it = self.vocab[kind].get(code)
        if it is not None and it.origin == "local":
            tgt = it.maps_to
            if tgt and tgt in self.vocab[kind] and self.vocab[kind][tgt].origin != "local":
                return self.read_code(kind, tgt)
            return READ_FALLBACK[kind]
        return self.read_code(kind, code)

    def privacy_dict(self) -> dict:
        """정제 사전 가명화 출처(X-247 · P §8.1): 과제 코드네임(+ mask_name 이면 이름·별칭) · 고객사 · 협력사 · 사내 도메인.
        퇴역 과제의 코드네임도 가린다. 토큰 ID 는 `P-…`·`L-…` 그대로. 예약 과제는 싣지 않는다."""
        projects = []
        for pid in sorted(self.projects):
            p = self.projects[pid]
            if p.origin == "reserved":
                continue
            names = list(p.codenames)
            if p.mask_name:
                names += [p.name, *p.aliases]
            names = list(dict.fromkeys(n for n in names if n))
            if names:
                projects.append({"id": pid, "codenames": names})
        return {"projects": projects, "customers": [dict(c) for c in self.customers],
                "partners": [dict(c) for c in self.partners], "internal_domains": list(self.internal_domains)}


@dataclass(frozen=True)
class RegistryStatus:
    source: str                                     # server | cache | offline | builtin
    version: int
    fetched_at: str | None                          # 받은 시각(UTC ISO) — 캐시·사본은 파일 시각
    hier_hash: str
    warnings: tuple[str, ...]
    stale: bool = False                             # 받은 지 hier.registry.staleWarnDays 초과
    adopt_offline: bool = False                     # 오프라인 사본을 골랐다(팀 클라이언트가 캐시로 옮길 대상)
    local_maps: dict[str, str] = field(default_factory=dict)       # 이번에 새로 자동 대응한 개인 과제

    def label_ko(self) -> str:
        """화면 한 줄(H §3.1)."""
        if self.source == "builtin":
            return "팀 레지스트리 없음 — 초기 상태"
        if self.source == "offline":
            return f"레지스트리 v{self.version}(오프라인 사본)"
        when = (self.fetched_at or "")[5:10]
        where = "서버" if self.source == "server" else "캐시"
        return f"레지스트리 v{self.version}({when} 받음, {where})" if when else f"레지스트리 v{self.version}({where})"


# ───────────────────────── 폴더 키·문서군 키 ─────────────────────────
def seg_norm(seg) -> str:
    """폴더 한 단계 이름 정규화(H §4.2): NFKC → casefold → 공백·_·-·. 묶음을 '_' 로 → 앞뒤 '_' 제거."""
    t = unicodedata.normalize("NFKC", str(seg or "")).casefold()
    return _SEG_RX.sub("_", t).strip("_")


def keyers_from(kr) -> tuple[Callable[[str], str], Callable[[str], str]]:
    """키링 → (폴더 키, 문서군 키) 함수. 폴더 = 's' + keyed(kr, 'dir', 'seg:' + seg_norm(seg), 16)(계약 §4.2),
    문서군 = lm27.privacy.keys.doc_key(kr, 이름)(계약 §4.3)."""
    from lm27.privacy import keys as _keys          # 지연 import — 정제 패키지는 분류 패키지를 import 하지 않는다(X-304)

    def folder(seg: str) -> str:
        return "s" + _keys.keyed(kr, "dir", "seg:" + seg_norm(seg), 16)

    def doc(name: str) -> str:
        return _keys.doc_key(kr, name)
    return folder, doc


# ───────────────────────── 병합(H §3.4) ─────────────────────────
def _tuple(xs) -> tuple:
    return tuple(dict.fromkeys(x for x in (xs or ()) if x))


def _union(a, b) -> tuple:
    return tuple(dict.fromkeys([*(a or ()), *(b or ())]))


def _period(p) -> tuple[str, str] | None:
    per = p.get("period")
    if isinstance(per, dict) and per.get("from"):
        return per["from"], per.get("to", "") or ""
    return None


class _Merge:
    def __init__(self, cfg, folder_key, doc_key):
        self.cfg = cfg
        self.folder_key = folder_key
        self.doc_key = doc_key
        self.warns: list[str] = []
        self.need_keys = False

    def warn(self, s: str) -> None:
        self.warns.append(s)

    def fkeys(self, folders) -> frozenset[str]:
        if not folders:
            return frozenset()
        if self.folder_key is None:
            self.need_keys = True
            return frozenset()
        return frozenset(self.folder_key(f) for f in folders)

    def dkeys(self, docs) -> frozenset[str]:
        if not docs:
            return frozenset()
        if self.doc_key is None:
            self.need_keys = True
            return frozenset()
        return frozenset(self.doc_key(d) for d in docs)

    def view(self, p: dict, origin: str, **extra) -> ProjectView:
        return ProjectView(
            id=p["id"], name=p["name"], domain=p["domain"], status=p.get("status", "active"),
            merged_into=p.get("merged_into") or None, origin=origin,
            aliases=_tuple(p.get("aliases")), codenames=_tuple(p.get("codenames")),
            keywords=_tuple(p.get("keywords")), never=_tuple(p.get("never")),
            mail_domains=_tuple(p.get("mail_domains")), customers=_tuple(p.get("customers")),
            partners=_tuple(p.get("partners")), folder_keys=self.fkeys(p.get("folders")),
            apps=_tuple(p.get("apps")), default_field=p.get("default_field", "") or "",
            default_func=p.get("default_func", "") or "", ax_link=bool(p.get("ax_link", False)),
            shared_fams=self.dkeys(p.get("shared_docs")), copilot_desc=p.get("copilot_desc", "") or "",
            period=_period(p), mask_name=bool(p.get("mask_name", False)), **extra)


def _reserved_views() -> dict[str, ProjectView]:
    return {pid: ProjectView(id=pid, name=_vocab.reserved_name(pid), domain=dom, status="active", merged_into=None,
                             origin="reserved", copilot_desc=_vocab.reserved_desc(pid))
            for pid, dom in _vocab.RESERVED.items()}


def _team_alias_map(team_projects: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in team_projects:
        for a in [p["name"], *p.get("aliases", []), *p.get("codenames", [])]:
            k = ukey(a)
            if len(k) >= 2:
                out.setdefault(k, p["id"])
    return out


def _merge_vocab(m: _Merge, team_vocab, local_vocab) -> dict[str, dict[str, VocabItem]]:
    out: dict[str, dict[str, VocabItem]] = {k: {it.code: it for it in _vocab.BUILTIN_VOCAB[k]}
                                             for k in _vocab.VOCAB_KINDS}
    tv = team_vocab if isinstance(team_vocab, dict) else {}
    for kind in _vocab.VOCAB_KINDS:
        table = out[kind]
        for it in tv.get(kind, []):
            code = it["code"]
            base = table.get(code)
            extra = {k: it[k] for k in ("tool_access", "verifiable", "kind", "cls") if k in it}
            if base is not None:
                table[code] = VocabItem(
                    code=code, name=it.get("name", base.name), status=it.get("status", base.status),
                    replaced_by=it.get("replaced_by", base.replaced_by),
                    keywords=_union(base.keywords, it.get("keywords")), apps=_union(base.apps, it.get("apps")),
                    exts=_union(base.exts, it.get("exts")), origin=base.origin, maps_to=base.maps_to,
                    tool_access=extra.get("tool_access", base.tool_access),
                    verifiable=extra.get("verifiable", base.verifiable), kind=extra.get("kind", base.kind),
                    cls=extra.get("cls", base.cls))
            else:
                table[code] = VocabItem(
                    code=code, name=it.get("name", code), status=it.get("status", "active"),
                    replaced_by=it.get("replaced_by", ""), keywords=_tuple(it.get("keywords")),
                    apps=_tuple(it.get("apps")), exts=_tuple(it.get("exts")),
                    origin="legacy" if it.get("legacy") else "team", tool_access=extra.get("tool_access"),
                    verifiable=extra.get("verifiable"), kind=extra.get("kind", ""), cls=extra.get("cls", ""))
    lv = local_vocab if isinstance(local_vocab, dict) else {}
    for kind in _schema.LOCAL_VOCAB_KINDS:
        table = out[kind]
        for it in lv.get(kind, []):
            code = it["code"]
            if code in table:
                m.warn(f"local_vocab_conflict:vocab_add.{kind}.{code}")
                continue
            table[code] = VocabItem(code=code, name=it.get("name", code), status=it.get("status", "active"),
                                    keywords=_tuple(it.get("keywords")), apps=_tuple(it.get("apps")),
                                    exts=_tuple(it.get("exts")), origin="local", maps_to=it.get("maps_to", "") or "")
    return out


def _apply_domain_meta(kw: dict[str, list[str]], desc: dict[str, str], dm) -> None:
    if not isinstance(dm, dict):
        return
    for c, ov in dm.items():
        if c not in kw:
            continue
        if ov.get("desc"):
            desc[c] = ov["desc"]
        drop = {ukey(x) for x in ov.get("keywords_remove", [])}
        cur = [x for x in kw[c] if ukey(x) not in drop]
        have = {ukey(x) for x in cur}
        for x in ov.get("keywords_add", []):
            k = ukey(x)
            if k and k not in have and k not in drop:
                cur.append(x)
                have.add(k)
        kw[c] = cur


def _rule_from(r: dict, origin: str) -> Rule | None:
    cond, then = r.get("if"), r.get("then")
    if not (isinstance(cond, dict) and isinstance(then, dict) and len(cond) == 1 and len(then) == 1):
        return None
    (ck, cv), = cond.items()
    (tk, tv), = then.items()
    if not (isinstance(ck, str) and isinstance(tk, str) and isinstance(cv, str) and isinstance(tv, str)):
        return None
    w = r.get("w")
    w = float(w) if isinstance(w, int | float) and not isinstance(w, bool) else None
    return Rule(id=str(r.get("id", "")), cond=(ck, cv), then=(tk, tv), w=w, origin=origin,
                status=str(r.get("status", "active")), note=str(r.get("note", "") or ""))


def _parties(team_list, cfg_list) -> tuple[dict, ...]:
    out: dict[str, dict] = {}
    for src in (team_list or [], cfg_list or []):
        for p in src:
            if isinstance(p, Mapping) and isinstance(p.get("id"), str) and p["id"] not in out:
                out[p["id"]] = {"id": p["id"], "names": list(p.get("names", []) or []),
                                "domains": list(p.get("domains", []) or [])}
    return tuple(out[k] for k in out)


def merge(team, local, cfg=None, *, person_key: str | None = None, learned=(), folder_key=None, doc_key=None,
          source: str | None = None) -> EffectiveRegistry:
    """유효 레지스트리(H §3.4). team·local 은 원본 객체(None = 없음) — 안에서 client 의미로 검증·정리한다.
    cfg 가 None 이면(팀 서버) 설정에서 오는 값(공공 도메인 계급·개인 추가 고객사 등)은 비운다."""
    m = _Merge(cfg, folder_key, doc_key)
    t = None
    if team is not None:
        t, errs = _schema.clean_registry(team)
        if t is None:
            m.warn("team_rejected")
        m.warns.extend(str(e) for e in errs if e.level != _schema.REJECT)
    loc = None
    if local is not None:
        loc, errs = _schema.clean_local(local)
        if loc is None:
            m.warn("local_rejected")
        m.warns.extend("local." + str(e) for e in errs if e.level != _schema.REJECT)
    t = t or {}
    loc = loc or {}
    team_projects: list[dict] = list(t.get("projects", []))
    views: dict[str, ProjectView] = _reserved_views()
    team_alias = _team_alias_map(team_projects)
    overlays = loc.get("overlays", {}) or {}
    for pid in overlays:
        if pid not in {p["id"] for p in team_projects}:
            m.warn(f"overlay_unknown:overlays.{pid}")
    # 팀 과제 + overlays
    for p in team_projects:
        ov = overlays.get(p["id"]) or {}
        q = dict(p)
        if ov:
            keep = []
            for a in ov.get("aliases", []):
                owner = team_alias.get(ukey(a))
                if owner is not None and owner != p["id"]:
                    m.warn(f"local_alias_conflict:overlays.{p['id']}")
                    continue
                keep.append(a)
            q["aliases"] = list(_union(p.get("aliases"), keep))
            for fld in ("keywords", "never", "mail_domains", "folders"):
                q[fld] = list(_union(p.get(fld), ov.get(fld)))
            if not q.get("default_field") and ov.get("default_field"):
                q["default_field"] = ov["default_field"]
        adopted = tuple((a["person_key"], a["proposal_id"]) for a in p.get("adopted", []))
        views[p["id"]] = m.view(q, "team", adopted=adopted)
    # 개인 과제(L-…) — 대응: 팀 adopted > 파일 maps_to > 이름·별칭 ukey 일치(팀이 이긴다)
    adopted_ix = {(pk, pr): v.id for v in views.values() for pk, pr in v.adopted}
    local_maps: dict[str, str] = {}
    team_ids = {p["id"] for p in team_projects}
    for p in loc.get("projects", []):
        target = None
        pr = p.get("proposal_id")
        if person_key and pr and (person_key, pr) in adopted_ix:
            target = adopted_ix[(person_key, pr)]
        file_map = p.get("maps_to")
        if target is None and file_map:
            if file_map in team_ids:
                target = file_map
            else:
                m.warn(f"maps_to_missing:projects.{p['id']}")
        if target is None:
            for a in [p["name"], *p.get("aliases", []), *p.get("codenames", [])]:
                hit = team_alias.get(ukey(a))
                if hit is not None:
                    target = hit
                    break
        if target is not None and target != file_map:
            local_maps[p["id"]] = target
            m.warn(f"local_auto_mapped:projects.{p['id']}")
        q = dict(p)
        if target is not None:
            for fld in ("aliases", "codenames"):
                keep = []
                for a in p.get(fld, []):
                    owner = team_alias.get(ukey(a))
                    if owner is not None and owner != target:
                        m.warn(f"local_alias_conflict:projects.{p['id']}")
                        continue
                    keep.append(a)
                q[fld] = keep
        views[p["id"]] = m.view(q, "local", proposal_id=pr or None, maps_to=target)
    # 코파일럿 설명 최종 검사 — 팀 ⊕ 개인을 합친 뒤의 코드네임·별칭·(mask_name) 이름이 어느 설명에도 들지 않게(B14)
    hide = set()
    for v in views.values():
        if v.origin != "reserved":
            names = [*v.codenames, *v.aliases, *([v.name] if v.mask_name else [])]
            hide.update(k for k in (ukey(x) for x in names) if len(k) >= 2)
    for pid, v in list(views.items()):
        d = ukey(v.copilot_desc)
        if v.origin != "reserved" and d and any(k in d for k in hide):
            m.warn(f"desc_has_codename:projects.{pid}")
            views[pid] = replace(v, copilot_desc="")
    # 색인
    alias_ix: dict[str, str] = {}
    folder_ix: dict[str, str] = {}
    for v in views.values():
        if v.origin == "reserved" or (v.status == "retired" and not v.merged_into):
            continue
        rep = _resolve_in(views, v.id)
        for a in (v.name, *v.aliases, *v.codenames):
            k = ukey(a)
            if len(k) >= 2:
                alias_ix.setdefault(k, rep)
        for fk in sorted(v.folder_keys):
            if fk in folder_ix and folder_ix[fk] != rep:
                m.warn(f"folder_conflict:projects.{v.id}")
                continue
            folder_ix[fk] = rep
    root_ix: dict[str, str] = {}
    for rid, pid in (loc.get("roots", {}) or {}).items():
        if pid in views:
            root_ix[rid] = _resolve_in(views, pid)
        else:
            m.warn(f"root_unknown:roots.{rid}")
    # 어휘·영역
    vocab = _merge_vocab(m, t.get("vocab"), loc.get("vocab_add"))
    kw = {c: list(_vocab.DOMAIN_META[c]["keywords"]) for c in _vocab.DOMAINS}
    desc: dict[str, str] = {}
    _apply_domain_meta(kw, desc, t.get("domain_meta"))
    _apply_domain_meta(kw, desc, loc.get("domain_meta"))
    domain_kw = {c: tuple(kw[c]) for c in _vocab.DOMAINS}
    # 규칙
    rules: list[Rule] = []
    for r in t.get("rules", []):
        if r.get("status", "active") == "active":
            rr = _rule_from(r, "team")
            if rr is not None:
                rules.append(rr)
    for r in learned or ():
        if not isinstance(r, Mapping) or r.get("status") != "active":
            continue
        rr = _rule_from(r, "learned")
        if rr is None or not rr.id:
            m.warn("learned_rule_bad")
            continue
        rules.append(rr)
    pairs = set()
    for a, b in [*t.get("never_pairs", []), *loc.get("never_pairs", [])]:
        ka, kb = ukey(a), ukey(b)
        if ka and kb and ka != kb:
            pairs.add(frozenset((ka, kb)))
    # 설정에서 오는 값
    if "public_domain_classes" in t:
        public = dict(t["public_domain_classes"])
    elif cfg is not None:
        public = dict(cfg["hier.publicDomainClasses"])
    else:
        public = {}
    customers = _parties(t.get("customers"), cfg["privacy.customers"] if cfg is not None else None)
    partners = _parties(t.get("partners"), cfg["privacy.partners"] if cfg is not None else None)
    doms = list(t.get("internal_domains", []))
    if cfg is not None:
        doms += [str(d).lower() for d in cfg["privacy.internalDomains"]]
    internal = tuple(dict.fromkeys(doms))
    meta = t.get("agents_meta") or {}
    agents = tuple(Agent(id=a["id"], name=a["name"], axis=a.get("axis", ""), status=a.get("status", "running"),
                         desc=a.get("desc", ""), copilot_desc=a.get("copilot_desc", ""),
                         step_types=_tuple(a.get("step_types")), inputs=tuple(a.get("inputs", [])),
                         outputs=tuple(a.get("outputs", [])), keywords=_tuple(a.get("keywords")),
                         owner_label=a.get("owner_label", "")) for a in t.get("agents", []))
    if m.need_keys:
        m.warn("no_keyring:folders")
    reg = EffectiveRegistry(
        version=int(t.get("version", 0)), hier_hash="", source=source or ("builtin" if not t else "team"),
        projects=views, alias_ix=alias_ix, folder_ix=folder_ix, root_ix=root_ix, vocab=vocab, domain_kw=domain_kw,
        rules=tuple(rules), never_pairs=frozenset(pairs), public_suffix=public, agents=agents,
        catalog_version=str(meta.get("catalog_version", "") or ""), warnings=tuple(dict.fromkeys(m.warns)),
        domain_desc=desc, agent_axes=dict(meta.get("axes", {}) or {}), customers=customers, partners=partners,
        internal_domains=internal, calendar=t.get("calendar"), pepper_id=str(t.get("pepper_id", "") or ""),
        person=dict(loc.get("person", {}) or {}), codename_review=loc.get("codename_review"),
        local_maps=local_maps)
    return _with_hash(reg)


def _with_hash(reg: EffectiveRegistry) -> EffectiveRegistry:
    return replace(reg, hier_hash=hier_hash(reg))


def _hash_payload(reg: EffectiveRegistry) -> dict:
    projects = []
    for pid in sorted(reg.projects):
        p = reg.projects[pid]
        projects.append({
            "id": p.id, "domain": p.domain, "status": p.status, "merged_into": p.merged_into, "origin": p.origin,
            "aliases": list(p.aliases), "codenames": list(p.codenames), "keywords": list(p.keywords),
            "never": list(p.never), "mail_domains": list(p.mail_domains), "customers": list(p.customers),
            "partners": list(p.partners), "folder_keys": sorted(p.folder_keys), "apps": list(p.apps),
            "default_field": p.default_field, "default_func": p.default_func, "ax_link": p.ax_link,
            "shared_fams": sorted(p.shared_fams), "copilot_desc": p.copilot_desc,
            "period": list(p.period) if p.period else None, "proposal_id": p.proposal_id, "mask_name": p.mask_name,
            "maps_to": p.maps_to})
    rules = [{"id": r.id, "if": list(r.cond), "then": list(r.then), "w": r.w, "origin": r.origin} for r in reg.rules]
    return {
        "projects": projects, "alias_ix": reg.alias_ix, "folder_ix": reg.folder_ix, "root_ix": reg.root_ix,
        "vocab": {k: [it.to_obj() for it in reg.vocab[k].values()] for k in sorted(reg.vocab)},
        "rules": rules, "never_pairs": sorted(sorted(p) for p in reg.never_pairs),
        "domain_meta": {"keywords": {c: list(v) for c, v in reg.domain_kw.items()}, "desc": reg.domain_desc},
        "public_domain_classes": reg.public_suffix,
    }


def hier_hash(reg: EffectiveRegistry) -> str:
    """분류 해시(H §2.5): 분류 결과에 영향을 주는 부분만 — 과제(이름·메모·created_at 제외, 대신 이름 색인 포함)·
    어휘·규칙·never_pairs·domain_meta·public_domain_classes. sha256 앞 16자."""
    return hashlib.sha256(fsx.canon_bytes(_hash_payload(reg))).hexdigest()[:16]


def builtin_registry(cfg=None) -> EffectiveRegistry:
    """팀·개인 레지스트리가 없는 초기 상태(H §3.5) — 예약 과제 5개 + 내장 어휘 + 내장 영역 키워드."""
    return merge(None, None, cfg, source="builtin")


# ───────────────────────── 적재(H §3.1) ─────────────────────────
def _fetch_result(r):
    """fetch 결과 → (status, obj). 객체(.status·.obj) · (status, obj) 튜플 · {status, obj} 사전을 받는다."""
    if isinstance(r, tuple) and len(r) == 2:
        return r[0], r[1]
    if isinstance(r, Mapping):
        return r.get("status"), r.get("obj")
    return getattr(r, "status", None), getattr(r, "obj", None)


def _mtime_iso(path) -> str | None:
    try:
        st = os.stat(fsx.longp(path))
    except OSError:
        return None
    return datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usable(obj) -> bool:
    return isinstance(obj, dict) and not _schema.blocking(_schema.validate_registry(obj, "client"))


def _read_local(paths, warns: list[str]) -> tuple[dict | None, bytes | None]:
    """개인 로컬 레지스트리. 깨졌으면 .bak 로 복구(둘 다 깨지면 빈 것 + 경고)."""
    main = paths.hier_local_file(LOCAL_FILE)
    if not os.path.exists(fsx.longp(main)):
        return None, None
    try:
        raw = fsx.read_bytes(main)
        obj = fsx.loads_strict(raw)
        if isinstance(obj, dict):
            return obj, raw
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    warns.append("local_broken")
    bak = fsx.read_json(paths.hier_local_file(LOCAL_BAK), default=None)
    if isinstance(bak, dict):
        warns.append("local_from_bak")
        return bak, None
    return None, None


def _read_person_key(paths) -> str | None:
    b = fsx.read_json(paths.bundle_json(), default=None)
    pk = b.get("person_key") if isinstance(b, dict) else None
    return pk if isinstance(pk, str) and _PERSON_KEY_RX.match(pk) else None


def _read_learned(paths) -> list:
    obj = fsx.read_json(paths.hier_local_file(LEARNED_FILE), default=None, want=None)
    if isinstance(obj, dict):
        obj = obj.get("rules")
    return list(obj) if isinstance(obj, list) else []


def persist_local_maps(paths, local_obj: dict, local_maps: Mapping[str, str], raw: bytes | None = None) -> bool:
    """자동 대응(maps_to)을 개인 로컬 레지스트리 파일에 기록(H §3.4 '파일에 기록'). 직전 판은 .bak 로 남긴다.
    바꿀 것이 없으면 쓰지 않고 False."""
    if not local_maps or not isinstance(local_obj, dict):
        return False
    new = dict(local_obj)
    changed = False
    projects = []
    for p in local_obj.get("projects", []) or []:
        if isinstance(p, dict) and p.get("id") in local_maps and p.get("maps_to") != local_maps[p["id"]]:
            p = dict(p)
            p["maps_to"] = local_maps[p["id"]]
            changed = True
        projects.append(p)
    if not changed:
        return False
    new["projects"] = projects
    if raw is not None:
        fsx.atomic_write(paths.hier_local_file(LOCAL_BAK), raw)
    fsx.atomic_write(paths.hier_local_file(LOCAL_FILE), fsx.canon_bytes(new))
    return True


def load_effective(paths, cfg, now=None, *, fetch=None, kr=None, folder_key=None, doc_key=None,
                   person_key: str | None = None, learned=None, persist: bool = True
                   ) -> tuple[EffectiveRegistry, RegistryStatus]:
    """그 순간의 유효 레지스트리 하나(H §3.1). 분석은 이것 하나로 기간 전체를 다시 분류한다.

    fetch: 팀 서버 받기 함수 `fetch(timeout_s=…)` → (status, obj)(200 = 새 판 — 캐시 교체는 팀 클라이언트 몫,
           304 = 캐시가 최신). None 이면 서버에 묻지 않는다(오프라인 사본·캐시·내장만 — 정제 문맥·클라우드PC).
    kr:    키링(폴더 키·문서군 키). folder_key·doc_key 를 직접 주면 그것이 앞선다(시험).
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)                 # 순진한 시각은 UTC 로 본다
    warns: list[str] = []
    timeout = cfg["team.registryTimeoutSec"]
    stale_days = cfg["hier.registry.staleWarnDays"]
    offline_dir = cfg["team.offlineDir"]
    team, src, fetched_at, adopt_offline = None, "builtin", None, False
    status_code = None
    if fetch is not None:
        try:
            status_code, obj = _fetch_result(fetch(timeout_s=timeout))
        except (OSError, TimeoutError, ValueError) as e:
            warns.append(f"server_unreachable:{type(e).__name__}")
            status_code, obj = None, None
        if status_code == 200:
            if _usable(obj):
                team, src, fetched_at = obj, "server", now.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                warns.append("server_rejected")
    if team is None:
        cache_path = paths.registry_cache()
        cache = fsx.read_json(cache_path, default=None)
        if cache is not None and not _usable(cache):
            warns.append("cache_rejected")
            cache = None
        if status_code == 304 and cache is not None:
            team, src, fetched_at = cache, "cache", now.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            off = None
            off_path = paths.offline_registry(offline_dir) if offline_dir else None   # 계약 v1.2 §0.7 C19
            if off_path:
                off = fsx.read_json(off_path, default=None)
                if off is not None and not _usable(off):
                    warns.append("offline_rejected")
                    off = None
            if off is not None and (cache is None or off["version"] > cache["version"]):
                team, src, fetched_at, adopt_offline = off, "offline", _mtime_iso(off_path), True
            elif cache is not None:
                team, src, fetched_at = cache, "cache", _mtime_iso(cache_path)
    local, local_raw = _read_local(paths, warns)
    if person_key is None:
        person_key = _read_person_key(paths)
    if learned is None:
        learned = _read_learned(paths)
    if kr is not None and (folder_key is None or doc_key is None):
        fk, dk = keyers_from(kr)
        folder_key = folder_key or fk
        doc_key = doc_key or dk
    reg = merge(team, local, cfg, person_key=person_key, learned=learned, folder_key=folder_key, doc_key=doc_key,
                source=src)
    if persist and local is not None and reg.local_maps:
        persist_local_maps(paths, local, reg.local_maps, local_raw)
    stale = False
    if fetched_at and src in ("cache", "offline"):
        try:
            t0 = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            stale = (now - t0).total_seconds() > stale_days * 86400
        except ValueError:
            stale = False
    all_warns = tuple(dict.fromkeys([*warns, *reg.warnings]))
    st = RegistryStatus(source=src, version=reg.version, fetched_at=fetched_at, hier_hash=reg.hier_hash,
                        warnings=all_warns, stale=stale, adopt_offline=adopt_offline, local_maps=dict(reg.local_maps))
    return reg, st
