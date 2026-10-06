# -*- coding: utf-8 -*-
"""합성 페르소나·시험 키(WP-05) — 자리표시자만 쓴다: 본인 홍길동 · 동료 김철수 · 과제A~F · 고객사A(C01) · 협력사(V01) ·
example 도메인. 그 밖의 동료는 '동료B'처럼 이름이 아닌 표지로 둔다(실명 금지).

텍스트 조각(parts) — 원시·정제 모양을 한 번에 그린다:
    ("과제 ", ("proj", 0), " 회로 검토")   → 원시 "과제 과제A 회로 검토" / 정제 "과제 [과제:P-0001] 회로 검토"
    조각 = 문자열(그대로) | ("proj", i) | ("org", "C01") | ("person", "p01" 또는 "self")
SynthKeys 는 P §9.3 과 같은 방식(subkey = HMAC(master, b"lm27:"+purpose), keyed = HMAC(subkey, 값)[:n])의 시험용 고정 키다.
실제 키링이 아니며, 하류 WP 가짜 입력의 키 모양·일관성(같은 재료 → 같은 키)만 맞춘다.
"""
from __future__ import annotations

import hashlib
import hmac
import random
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

RULES_VER = "2026.10.0"            # 계약 §2.2 RULES_VERSION 모양(합성 저장 행 표기용)
OFFSET_KST = 540
INTERNAL_DOMAIN = "corp.example"

# 문서군 꼬리(계약 §4.3 · v1.2 C16 — lm27.privacy.keys.DOC_TAIL 과 같은 식): 낱말·판 꼬리는 앞에 구분자가 있을 때만,
# '(n)' 은 구분자 없이도. 날짜 숫자 꼬리는 남긴다. 구분자 묶음은 '_'.
_TAILS = re.compile(r"(?:[\s_\-]+(?:복사본|사본|수정본?|copy|최종|final|v\d{1,3}(?:\.\d{1,3}){0,2}|rev\.?\s?\d{1,3}|r\d{1,3})"
                    r"|\s?\(\d{1,3}\))$")
_FAM_SEP = re.compile(r"[\s_\-.]+")


@dataclass(frozen=True, slots=True)
class Person:
    pid: str                 # self · p01 … · c01 · v01
    name: str                # 표시명(원문 — 정제 전 메모리에만)
    addr: str                # example 도메인 주소
    title: str = ""          # 호칭(책임·선임 …)
    org: str = "internal"    # self · internal · customer · partner

    @property
    def is_self(self) -> bool:
        return self.org == "self"


@dataclass(frozen=True, slots=True)
class Project:
    pid: str                     # 레지스트리 ID P-0001 …
    codename: str                # 과제A …
    domain: str                  # DEV · MP · EXT · COM · AX
    topics: tuple[str, ...]      # 문서·제목에 쓰는 주제 낱말


@dataclass(frozen=True, slots=True)
class Org:
    oid: str        # C01 · V01
    name: str       # 고객사A · 협력사
    domain: str     # custa.example · partner.example
    kind: str       # customer · partner


@dataclass(frozen=True, slots=True)
class PcSpec:
    key: str                 # PC1 · PC2 · CLOUD
    kind: str                # desktop · laptop · vdi · cloud
    machine_guid: str        # 합성 GUID(원값 — 레코드에 넣지 않는다)
    pc_id: str               # "pc_" + sha256("LM27.pc|" + guid.lower())[:16] (계약 §4.1)
    install_id: str          # 32hex
    offset_min: int          # 수집 순간 로컬 오프셋(클라우드PC 는 0 = UTC)
    roles: tuple[str, ...]


@dataclass(frozen=True)
class Persona:
    me: Person
    peers: tuple[Person, ...]
    projects: tuple[Project, ...]
    orgs: tuple[Org, ...]
    pcs: tuple[PcSpec, ...]
    internal_domains: tuple[str, ...]
    winuser: str                       # 원시 경로의 사용자 폴더명(자리표시자)
    person_key: str                    # 번들 소유자 p_ + 12hex
    offset_min: int = OFFSET_KST
    _by_pid: dict = field(default_factory=dict, repr=False, compare=False)

    def person(self, pid: str) -> Person:
        if not self._by_pid:
            self._by_pid.update({p.pid: p for p in (self.me, *self.peers)})
        return self._by_pid[pid]

    def pc(self, key: str) -> PcSpec:
        for p in self.pcs:
            if p.key == key:
                return p
        raise KeyError(key)

    def org(self, oid: str) -> Org:
        for o in self.orgs:
            if o.oid == oid:
                return o
        raise KeyError(oid)

    @property
    def internal_peers(self) -> tuple[Person, ...]:
        return tuple(p for p in self.peers if p.org == "internal")

    @property
    def external_peers(self) -> tuple[Person, ...]:
        return tuple(p for p in self.peers if p.org in ("customer", "partner"))

    def label_of(self, p: Person) -> str:
        """sender_label(P §10.2): 사내 · 고객사:<ID> · 협력사:<ID>."""
        if p.org in ("self", "internal"):
            return "사내"
        dom = p.addr.rsplit("@", 1)[-1]
        for o in self.orgs:
            if o.domain == dom:
                return f"{'고객사' if o.kind == 'customer' else '협력사'}:{o.oid}"
        return dom

    def render(self, parts: Sequence, keys: SynthKeys | None = None) -> tuple[str, str, dict[str, int]]:
        """텍스트 조각 → (원시 문자열, 정제 모양 문자열, 범주별 가림 건수 san)."""
        raw: list[str] = []
        masked: list[str] = []
        san: dict[str, int] = {}
        for part in parts:
            if isinstance(part, str):
                raw.append(part)
                masked.append(part)
                continue
            tag, ref = part
            if tag == "proj":
                pj = self.projects[ref]
                raw.append(pj.codename)
                masked.append(f"[과제:{pj.pid}]")
                cat = "project"
            elif tag == "org":
                o = self.org(ref)
                raw.append(o.name)
                masked.append(f"[{'고객사' if o.kind == 'customer' else '협력사'}:{o.oid}]")
                cat = o.kind
            elif tag == "person":
                p = self.person(ref)
                raw.append(p.name)
                if p.is_self:
                    masked.append("[나]")
                    cat = "self"
                else:
                    tag6 = (keys or synth_keys()).name_tag(p.name)
                    masked.append(f"[사람#{tag6}]")
                    cat = "person"
            else:
                raise ValueError(f"알 수 없는 조각: {tag}")
            san[cat] = san.get(cat, 0) + 1
        return "".join(raw), "".join(masked), san

    def mask(self, text: str, keys: SynthKeys | None = None) -> tuple[str, dict[str, int]]:
        """원시 문자열(파일 이름 등) 속 자리표시자(과제 코드네임·고객사·협력사·사내 사람 이름)를 정제 모양 토큰으로.
        합성 자료 범위의 그리기일 뿐 정제기가 아니다."""
        k = keys or synth_keys()
        reps: list[tuple[str, str, str]] = [(p.codename, f"[과제:{p.pid}]", "project") for p in self.projects]
        reps += [(o.name, f"[{'고객사' if o.kind == 'customer' else '협력사'}:{o.oid}]", o.kind) for o in self.orgs]
        reps += [(p.name, "[나]" if p.is_self else f"[사람#{k.name_tag(p.name)}]", "self" if p.is_self else "person")
                 for p in (self.me, *self.internal_peers)]
        san: dict[str, int] = {}
        out = text
        for src, dst, cat in sorted(reps, key=lambda x: -len(x[0])):
            n = out.count(src)
            if n:
                out = out.replace(src, dst)
                san[cat] = san.get(cat, 0) + n
        return out, san

    def ctx_dict(self, keys: SynthKeys | None = None) -> dict:
        """정제 문맥용 사전(P §18.1 문맥 A 모양): 사내 도메인·고객사·협력사·과제 코드네임·사람 사전·본인 이름."""
        k = keys or synth_keys()
        return {
            "internal_domains": list(self.internal_domains),
            "customers": [{"id": o.oid, "names": [o.name], "domains": [o.domain]} for o in self.orgs
                          if o.kind == "customer"],
            "partners": [{"id": o.oid, "names": [o.name], "domains": [o.domain]} for o in self.orgs
                         if o.kind == "partner"],
            "projects": [{"id": p.pid, "codenames": [p.codename]} for p in self.projects],
            "persons": {p.name: k.keyed("person", "name:" + norm_person(p.name), 16) for p in self.internal_peers},
            "self_names": [self.me.name],
        }


def norm_person(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).lower()


def doc_fam(name: str) -> str:
    """합성 문서 이름의 문서군(계약 §4.3 · C16 규칙 그대로 — 정본은 lm27.privacy.keys.doc_fam, 같음을 시험이 본다).
    NFKC → 경로면 기본 이름 → 소문자 → 확장자 제거 → 꼬리 반복 제거(최대 5회) → 비면 원래 이름 → 구분자 묶음은 '_'."""
    s = re.split(r"[\\/]", unicodedata.normalize("NFKC", name))[-1].lower().strip()
    s = re.sub(r"\.(?:gz|zip|7z)$", "", s)
    t = re.sub(r"\.(?:prt|asm|drw)\.\d{1,4}$", "", s)
    s = (t if t != s else re.sub(r"\.[0-9a-z]{1,5}$", "", s)).strip()
    base = s
    for _ in range(5):
        t = _TAILS.sub("", s)
        if t == s:
            break
        s = t
    if not _FAM_SEP.sub("", s):
        s = base
    return _FAM_SEP.sub("_", s).strip("_")


class SynthKeys:
    """시험용 고정 키(P §9.3 방식). purpose 이름은 계약 §4.2 PURPOSES."""

    def __init__(self, master: bytes):
        self.master = master
        self.kid = "k" + hashlib.sha256(master).hexdigest()[:8]
        self._sub: dict[str, bytes] = {}

    def subkey(self, purpose: str) -> bytes:
        k = self._sub.get(purpose)
        if k is None:
            k = hmac.new(self.master, b"lm27:" + purpose.encode("ascii"), hashlib.sha256).digest()
            self._sub[purpose] = k
        return k

    def keyed(self, purpose: str, value: str, n: int = 16) -> str:
        return hmac.new(self.subkey(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()[:n]

    # 계약 §4.2 키 모양
    def who(self, p: Person) -> str:
        return "w" + self.keyed("person", "smtp:" + p.addr.lower())

    def name_tag(self, name: str) -> str:
        return self.keyed("person", "name:" + norm_person(name), 6)

    def msg(self, material: str) -> str:
        return "m" + self.keyed("msg", material, 24)

    def cal(self, material: str) -> str:
        return "e" + self.keyed("cal", material, 24)

    def thread(self, material: str) -> str:
        return "t" + self.keyed("thread", material)

    def chat(self, material: str) -> str:
        return "h" + self.keyed("chat", material)

    def doc(self, name: str) -> str:
        return "d" + self.keyed("doc", "n:" + doc_fam(name))

    def repo(self, name: str) -> str:
        return "r" + self.keyed("repo", norm_person(name))

    def path(self, full: str) -> str:
        return "f" + self.keyed("path", full.lower())

    def dir(self, name: str) -> str:
        return "s" + self.keyed("dir", unicodedata.normalize("NFKC", name).lower())

    def commit(self, sha: str) -> str:
        return "g" + self.keyed("commit", sha.lower())


_KEYS: dict[int, SynthKeys] = {}


def synth_keys(seed: int = 0) -> SynthKeys:
    """시드별 시험 키(같은 시드 → 같은 kid·같은 키)."""
    k = _KEYS.get(seed)
    if k is None:
        k = _KEYS[seed] = SynthKeys(hashlib.sha256(f"lm27-synth-master/{seed}".encode()).digest())
    return k


def _guid(r: random.Random) -> str:
    h = f"{r.getrandbits(128):032x}"
    return f"{h[0:8]}-{h[8:12]}-4{h[13:16]}-{'89ab'[r.randrange(4)]}{h[17:20]}-{h[20:32]}"


def pc_id_of(machine_guid: str) -> str:
    """계약 §4.1: "pc_" + sha256("LM27.pc|" + MachineGuid.lower())[:16]."""
    return "pc_" + hashlib.sha256(("LM27.pc|" + machine_guid.lower()).encode("utf-8")).hexdigest()[:16]


_PERSONAS: dict[int, Persona] = {}


def default_persona(seed: int = 0) -> Persona:
    """기본 페르소나(같은 시드 → 같은 GUID·pc_id·install_id·person_key)."""
    hit = _PERSONAS.get(seed)
    if hit is not None:
        return hit
    r = random.Random(f"lm27-persona/{seed}")
    me = Person("self", "홍길동", "gildong.hong@corp.example", "선임", "self")
    peers = (
        Person("p01", "김철수", "chulsoo.kim@corp.example", "책임"),
        Person("p02", "동료B", "peer.b@corp.example", "선임"),
        Person("p03", "동료C", "peer.c@corp.example", "책임"),
        Person("p04", "동료D", "peer.d@corp.example", "수석"),
        Person("p05", "동료E", "peer.e@corp.example", "사원"),
        Person("c01", "고객사A 담당", "buyer@custa.example", "", "customer"),
        Person("v01", "협력사 담당", "sales@partner.example", "", "partner"),
    )
    projects = (
        Project("P-0001", "과제A", "DEV", ("회로도", "시험계획", "도면")),
        Project("P-0002", "과제B", "DEV", ("해석보고", "센서사양", "보정표")),
        Project("P-0003", "과제C", "MP", ("양산검토", "품질지표", "원가표")),
        Project("P-0004", "과제D", "EXT", ("견적서", "납기표", "사양협의")),
        Project("P-0005", "과제E", "COM", ("주간보고", "회의록", "교육자료")),
        Project("P-0006", "과제F", "AX", ("자동화", "변환스크립트", "데이터정리")),
    )
    orgs = (Org("C01", "고객사A", "custa.example", "customer"), Org("V01", "협력사", "partner.example", "partner"))

    def _pc(key: str, kind: str, off: int, roles: tuple[str, ...]) -> PcSpec:
        g = _guid(r)
        return PcSpec(key, kind, g, pc_id_of(g), f"{r.getrandbits(128):032x}", off, roles)

    pcs = (_pc("PC1", "desktop", OFFSET_KST, ("pc1",)), _pc("PC2", "laptop", OFFSET_KST, ("pc2",)),
           _pc("CLOUD", "cloud", 0, ("cloud",)))
    p = Persona(me, peers, projects, orgs, pcs, (INTERNAL_DOMAIN,), "hong", f"p_{r.getrandbits(48):012x}")
    _PERSONAS[seed] = p
    return p
