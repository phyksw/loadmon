# -*- coding: utf-8 -*-
r"""로컬 표시 해석과 보고서 변형(R §3.6 · 부록 A `Resolver`, 계약 §1.2 · §4.2).

키를 사람이 읽는 글자로 바꾼다. 무엇으로 바꾸는지는 **변형**(variant)이 정한다.

| 키 | `full`(로컬 앱·개인 전체판) | `redacted`(개인 가림판) | `team`(팀 묶음 — 빌더 WP-34 가 정본) |
|---|---|---|---|
| 동료 who_key | 사람 사전 `names[0]`, 없으면 `동료 #k` | `동료 #k` | `동료 #k`(peer_key 는 빌더가 pepper 로) |
| 본인 | 사람 사전 `self` 이름, 없으면 `나` | `나` | `나` |
| 외부 상대 | 계급 토큰(`[고객사:C01]`·`[협력사:V02]`·`외부`) + 정제 표시명 | 계급 토큰만 | 계급 토큰만 |
| 문서군 fam_key | 정제된 문서 이름 | `문서 #k` | 싣지 않음(None) |
| 메시지 msg_key | 정제된 제목 | None | None |
| 회의 ID | 정제된 회의 제목 | `회의 MM-DD` | None |
| 단위업무 제목 | 분류 단계 제목(정제본) | 안전 검사 통과 제목, 아니면 `<분야>·<기능> 단위업무 #n` | 같음 |
| 과제 이름 | 레지스트리 이름 | `mask_name` 이면 과제 ID, 아니면 이름 | 레지스트리 라벨 |
| 앱 | 카탈로그 표시명, 미상은 `미상 프로그램(…exe)` | 카탈로그 표시명, 미상은 `미상 프로그램` | 카탈로그 앱 ID |

번호표 `k`(R §3.6): 보고서 모델 안에서 공유 투입 분 ↓ → 공동 단위업무 수 ↓ → 키 사전순으로 1부터(`model.Refs` 가 정해 넘긴다).
가림판 제목의 안전 검사: 사람 사전의 이름(한글 2자 이상·ASCII 4자 이상)·로컬 키 모양·사람 토큰(`[사람#…]`)이 없을 것
(`team.unitTitleMode = generic` 이면 늘 일반 제목). 마지막 관문은 `model.redaction_violations`(G-R8) — 거기서 걸리면 가림판을
만들지 않는다. 표준 라이브러리만 쓴다. 파일을 읽거나 쓰지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

__all__ = ["KEY_RX", "VARIANTS", "Resolver", "external_class", "person_names"]

VARIANTS = ("full", "redacted", "team")
SELF_DEFAULT = "나"
EXT_NAMES = {"customer": "고객사", "partner": "협력사", "other": "외부"}
UNKNOWN_APP = "미상 프로그램"
UNKNOWN_PREFIX = "unknown:"
# 로컬 키 모양(계약 §4.2 — who_key·m/e 24hex·t/h/d/r/f/s/g 16hex) — 가림판·팀 반출물 금지 값
KEY_RX = re.compile(r"(?<![0-9A-Za-z])(?:[wthdrfsg][0-9a-f]{16}|[me][0-9a-f]{24})(?![0-9a-f])")
_HANGUL = re.compile(r"[가-힣]")
_ASCII = re.compile(r"[A-Za-z0-9]")


def _g(o, k, d=None):
    if o is None:
        return d
    v = o.get(k, d) if isinstance(o, Mapping) else getattr(o, k, d)
    return d if v is None else v


def person_names(person_dir) -> list[str]:
    """사람 사전의 이름 중 검사 대상(한글 2자 이상 또는 ASCII 영숫자 4자 이상 — R §9.2.4 G-R8), 긴 것부터."""
    out = set()
    people = _g(person_dir, "people", {}) or {}
    for rec in people.values() if isinstance(people, Mapping) else ():
        for nm in _g(rec, "names", ()) or ():
            s = " ".join(str(nm or "").split())
            if len(_HANGUL.findall(s)) >= 2 or len(_ASCII.findall(s)) >= 4:
                out.add(s)
    return sorted(out, key=lambda s: (-len(s), s))


def _domains(items) -> list[tuple[str, str]]:
    out = []
    for it in items or ():
        for d in _g(it, "domains", ()) or ():
            if isinstance(d, str) and d.strip():
                out.append((d.strip().lower().lstrip("@").lstrip("."), str(_g(it, "id", "") or "")))
    return out


def external_class(who: str, person_dir, registry) -> tuple[str, str]:
    """외부 상대의 (계급, 레지스트리 ID) — 사람 사전 smtp 도메인 ↔ 레지스트리 customers·partners 도메인. 모르면 ('other', '')."""
    rec = (_g(person_dir, "people", {}) or {}).get(who) or {}
    doms = {str(a).rsplit("@", 1)[-1].lower() for a in (_g(rec, "smtp", ()) or ()) if "@" in str(a)}
    for kind, items in (("customer", _g(registry, "customers", ())), ("partner", _g(registry, "partners", ()))):
        for d, rid in _domains(items):
            if any(x == d or x.endswith("." + d) for x in doms):
                return kind, rid
    return "other", ""


class Resolver:
    """변형별 키 → 글자. `people_ref`·`doc_ref` = 모델 번호표(키 → k), `titles` = 단위업무 제목 원천(unit_id → 정제 제목)."""

    def __init__(self, variant: str, person_dir=None, registry=None, evidence=None, *, people_ref=None, doc_ref=None,
                 fam_names=None, proposals=None, title_mode: str = "label"):
        if variant not in VARIANTS:
            raise ValueError(f"변형 이름 오류 {variant!r} — {', '.join(VARIANTS)} 중 하나")
        self.variant = variant
        self.local = variant == "full"
        self.person_dir = person_dir if isinstance(person_dir, Mapping) else None
        people = _g(self.person_dir, "people", {}) or {}
        self.people = people if isinstance(people, Mapping) else {}
        self.self_keys = frozenset(k for k, v in self.people.items() if bool(_g(v, "self", False)))
        self.registry = registry
        self.evidence = evidence
        self.people_ref = dict(people_ref or {})
        self.doc_ref = dict(doc_ref or {})
        self.fam_names = dict(fam_names if fam_names is not None else (_g(evidence, "fam_names", {}) or {}))
        self.proposals = {str(_g(p, "proposal_id", "")): p for p in (proposals or ()) if _g(p, "proposal_id")}
        self.title_mode = title_mode if title_mode in ("label", "generic") else "label"
        self._names = person_names(self.person_dir)
        self._msg_by_key: dict[str, str] | None = None
        self._apps: dict | None = None

    # ── 사람 ──
    def ref_of(self, who: str) -> int | None:
        return self.people_ref.get(who)

    def numbered(self, ref) -> str:
        return f"동료 #{ref}" if ref is not None else "동료"

    def self_name(self) -> str:
        if self.local:
            for k in sorted(self.self_keys):
                nm = (_g(self.people.get(k), "names", ()) or ())
                if nm:
                    return str(nm[0])
        return SELF_DEFAULT

    def person(self, who: str) -> str:
        """동료 who_key → 표시 이름(R §3.6). 본인 키면 본인 이름(전체판) 또는 '나'."""
        if who in self.self_keys:
            return self.self_name()
        if self.local:
            nm = _g(self.people.get(who), "names", ()) or ()
            if nm and str(nm[0]).strip():
                return str(nm[0])
        return self.numbered(self.people_ref.get(who))

    def external(self, who: str) -> str:
        """외부 상대 → 계급 토큰(+ 전체판은 정제 표시명)."""
        kind, rid = external_class(who, self.person_dir, self.registry)
        tok = f"[{EXT_NAMES[kind]}:{rid}]" if (rid and kind != "other") else EXT_NAMES[kind]
        if self.local:
            nm = _g(self.people.get(who), "names", ()) or ()
            if nm and str(nm[0]).strip():
                return f"{tok} {nm[0]}"
        return tok

    def who(self, who: str) -> str:
        """근거 줄의 상대(사내·미확인 = 사람, 외부 = 계급) — 사람 사전에 없으면 번호표 또는 '상대'."""
        if not who:
            return ""
        rec = self.people.get(who)
        if rec is not None and not bool(_g(rec, "internal", False)) and who not in self.self_keys:
            return self.external(who)
        if rec is None and who not in self.people_ref:
            return "상대" if not self.local else "상대(사람 사전에 없음)"
        return self.person(who)

    # ── 문서·메시지·회의 ──
    def doc(self, fam: str) -> str | None:
        if self.variant == "team":
            return None
        k = self.doc_ref.get(fam)
        if self.local:
            nm = self.fam_names.get(fam)
            if nm:
                return str(nm)
        return f"문서 #{k}" if k is not None else "문서"

    def msg(self, msg_key: str) -> str | None:
        if not self.local:
            return None
        if self._msg_by_key is None:
            self._msg_by_key = {}
            for line in (_g(self.evidence, "lines", {}) or {}).values():
                k = str(line.get("key") or "")
                if k and line.get("title") and k not in self._msg_by_key:
                    self._msg_by_key[k] = str(line["title"])
        return self._msg_by_key.get(msg_key)

    def meeting(self, meet_id: str, d: str | None = None) -> str | None:
        if self.variant == "team":
            return None
        if self.local:
            line = (_g(self.evidence, "lines", {}) or {}).get(meet_id)
            if line and line.get("title"):
                return str(line["title"])
        return "회의" + (f" {str(d)[5:10]}" if d else "")

    # ── 과제·앱·제목 ──
    def project(self, key: str) -> str:
        if not key or key == "UNC":
            return "과제 없음"
        reg = self.registry
        pv = None
        if reg is not None and hasattr(reg, "project"):
            pv = reg.project(key)
        if pv is None and reg is not None and hasattr(reg, "resolve") and hasattr(reg, "project"):
            pv = reg.project(reg.resolve(key))
        if pv is not None:
            if not self.local and bool(_g(pv, "mask_name", False)):
                return key
            return str(_g(pv, "name", "") or key)
        if isinstance(reg, Mapping):
            for p in reg.get("projects") or ():
                if isinstance(p, Mapping) and p.get("id") == key:
                    if not self.local and p.get("mask_name"):
                        return key
                    return str(p.get("name") or key)
        prop = self.proposals.get(key)
        if prop is not None:
            return str(_g(prop, "label", "") or key) if self.local else key
        return key

    def app(self, app_id: str) -> str:
        a = str(app_id or "")
        if self._apps is None:
            from lm27.catalog import entries           # 카탈로그 단일원(계약 §2.8)
            self._apps = {p.app_id: p for p in entries()}
        p = self._apps.get(a)
        if p is not None:
            return str(p.name)
        if a.startswith(UNKNOWN_PREFIX):
            return f"{UNKNOWN_APP}({a[len(UNKNOWN_PREFIX):]})" if self.local else UNKNOWN_APP
        if self.variant == "team":
            return a
        return a if a else UNKNOWN_APP

    def title_safe(self, title: str) -> bool:
        """가림판에 그대로 낼 수 있는 제목인가(사람 이름·로컬 키·사람 토큰 없음)."""
        s = str(title or "")
        if not s.strip() or "[사람" in s or KEY_RX.search(s):
            return False
        return not any(nm in s for nm in self._names)

    def unit_title(self, title: str, generic: str) -> str:
        """단위업무 제목(R §3.6): 전체판은 그대로, 가림판·팀은 안전한 제목 또는 일반 제목."""
        if self.local:
            return str(title or "") or generic
        if self.title_mode == "generic" or not self.title_safe(title):
            return generic
        return " ".join(str(title).split())[:40]
