# -*- coding: utf-8 -*-
r"""분류 특징 — 정제·병합이 끝난 증거 행 → `Feat`(H §4.1 · §4.2, 계약 §2.10 · §3.1~§3.3 · §4.3 · X-244 · X-245 · C15).

- 입력은 `lm27.normalize.load.load_evidence` 의 출력 행(정제·병합 끝, 원문 없음)이다. 정제문(`*_masked`)·키·열거만 읽는다.
- `Feat.kind` 대응(X-244): mail.*→mail · cal.*→cal · teams.*→teams · pc_file→file · pc.sampler→win · pc_git→git ·
  pc_compute→compute · manual→manual · *.copilot→summary(요약 증인, 가중 `hier.rule.summaryMult`). pc.events 는 특징이 없다.
- 사적·친목·광고(`priv_class ∈ {private, social}` · `flags.ad`) 행은 특징을 만들지 않는다(W §2.1-4 와 같은 원칙).
- **문서군 키는 시간 코어와 같은 규칙**으로 만든다(`FamKeyer` — `lm27.time.evidence` 의 이름·폴더 색인 + `lm27.time.tokens.fam_key`).
  그래야 `HierTags.fam` 의 키가 `DocE.fam`·`Samp.fam` 과 맞는다(W1a CR — WP-19). 범용 이름이 폴더 키 없이 묶인
  `B_GENERIC` 은 문서군 정체가 아니므로 특징의 `fams` 에 넣지 않는다.
- 상대 계급(`dom_labels`): 받은 메일 `sender_label` ∪ 상대 who_key 를 로컬 사람 사전(`person_dir.json`, P §9.6)으로 주소
  도메인에 대응시킨 계급 — 사내 · 개인메일 · 고객사:<id> · 협력사:<id> · 공공 도메인 계급(`public_domain_classes`, 기본 기관) ·
  그 밖 도메인 소문자(로컬 전용 — 프롬프트·팀으로 가지 않는다). 상대 원 도메인은 `mail_doms` 에 따로 둔다(R6·규칙 `if.domain`).
- 앱 범주(X-245): 행에는 `app_id`, 범주는 `lm27.catalog.cat_of(app_id)`(한글 9종).

표준 라이브러리 + `lm27.hier.match`·`lm27.time.tokens`·`lm27.time.calendar`(지연: `lm27.catalog`·`lm27.privacy.rules`·
`lm27.config`). 파일을 쓰지 않는다. 결정적이다(행 순서와 무관 — 정렬 키 명시).
"""
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from types import MappingProxyType

from lm27.hier import match as _match
from lm27.hier.names import ukey
from lm27.time.calendar import DAY, EPOCH
from lm27.time.tokens import B_GENERIC, fam_key, generic_stems

__all__ = [
    "FEAT_KIND_VALUES", "Feat", "FamKeyer", "PersonClasses", "default_cfg", "domain_class", "feat", "features_of", "get",
    "lsec_of", "month_of", "person_classes", "text_key", "union_feat",
]

FEAT_KIND_VALUES = ("mail", "teams", "cal", "file", "win", "git", "compute", "manual", "summary")
SKIP_PRIV = frozenset({"private", "social"})
INTERNAL = "사내"
PERSONAL = "개인메일"
_EMPTY_ENT: Mapping[str, frozenset[str]] = MappingProxyType({k: frozenset() for k in _match.ENT_KINDS})
# 정규화 단계가 화행을 아직 못 붙였을 때 act_cues 로 가늠(시간 코어 `CUE_ACT` 와 같은 순서)
CUE_ACT = (("req", "request"), ("rep", "report"), ("done", "report"), ("ack", "ack"), ("ask", "question"),
           ("sched", "info"), ("cancel", "info"), ("fyi", "info"))
MAN_SKIP = frozenset({"retract", "exclude", "absence", "cannot_link"})
FLAG_KEEP = ("organizer_me", "online_meeting", "all_day", "recurring", "cc", "bulk", "mentions_me")
_EXT_RX = re.compile(r"\.([0-9a-z_]{1,10})$")
_BODY_HEAD = 120                       # 팀즈 본문 앞 120자(H §4.1)


# ───────────────────────── 공용 도우미 ─────────────────────────
def get(obj, name: str, default=None):
    """사전·속성 객체 공용 읽기(tasks.json 행과 `UnitTask` 객체를 같이 받는다)."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


@lru_cache(maxsize=1)
def _builtin_cfg():
    from lm27.config import Cfg, load_registry          # 지연 import — 설정 레지스트리 선언 기본값만(개인 덮어쓰기 없음)
    return Cfg(load_registry())


def default_cfg(cfg=None):
    """cfg 가 없으면 설정 레지스트리 선언 기본값 Cfg(시험·도구용). 있으면 그대로."""
    return cfg if cfg is not None else _builtin_cfg()


def _str_list(v) -> list[str]:
    if not isinstance(v, list | tuple):
        return []
    return [x for x in v if isinstance(x, str) and x]


def _flags(r: Mapping) -> Mapping:
    f = r.get("flags")
    return f if isinstance(f, Mapping) else {}


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or ""))


_EPOCH_DT = datetime(EPOCH.year, EPOCH.month, EPOCH.day)


def lsec_of(ts, off_min: int) -> int:
    """UTC ISO 시각 → 근무 시간대 로컬 초(기준점 `lm27.time.calendar.EPOCH` 00:00 로컬 — 계약 §3.14). 형식 오류는 0."""
    if not isinstance(ts, str) or not ts:
        return 0
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    u = dt.astimezone(timezone.utc).replace(tzinfo=None)
    v = int((u - _EPOCH_DT).total_seconds()) + int(off_min) * 60
    return max(v, 0)


def month_of(t: int) -> str:
    """로컬 초 → 'YYYY-MM'(0 = 모름 → '')."""
    if not t:
        return ""
    d = EPOCH + timedelta(days=int(t) // DAY)
    return f"{d.year:04d}-{d.month:02d}"


# ───────────────────────── Feat ─────────────────────────
@dataclass(frozen=True, eq=False)
class Feat:
    """증거 하나의 분류 특징(H §4.1). 앞 15 필드가 명세 형이고, 그 뒤는 단위업무 모음·이름·질문용 확장(로컬 전용)."""
    id: str
    kind: str                                   # FEAT_KIND_VALUES
    t: int = 0                                  # 근무 시간대 로컬 초(0 = 모름) — 기간 밖 판정(R12)
    toks: frozenset[str] = frozenset()          # match_tokens(text)
    ent: Mapping[str, frozenset[str]] = field(default_factory=lambda: _EMPTY_ENT)   # {'과제': {...}, '고객사': {...}, '협력사': {...}}
    dom_labels: frozenset[str] = frozenset()    # 상대 계급
    app: str = ""                               # app_id('' 없음, 'unknown:<exe>' 미상)
    app_cat: str = ""                           # 카탈로그 범주(CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통·'')
    exts: frozenset[str] = frozenset()          # 문서·첨부 확장자('.xlsx' 꼴, 소문자)
    dir_keys: frozenset[str] = frozenset()      # 상위 폴더 세그먼트 키(§4.2)
    root_id: str = ""                           # 감시 루트 ID
    conv: str = ""                              # 대화 키(메일 thread_key · 팀즈 chat_key[:답글 루트]) — 시간 코어 Msg.conv 와 같다
    fams: frozenset[str] = frozenset()          # 문서군 키(시간 코어 fam_key — git 은 저장소 키 r16 그대로)
    manual: Mapping | None = None               # manual 행의 {project_id, role_field, role_func}
    weight_mult: float = 1.0                    # summary 0.5(hier.rule.summaryMult), 그 밖 1.0
    # ── 확장 ──
    key: str = ""                               # msg_key(메시지·일정) 또는 id
    src: str = ""                               # 경로 ID
    direction: str = ""                         # in | out | ''
    act: str = ""                               # 화행(정규화 파생 — 없으면 act_cues 로 가늠)
    text: str = ""                              # 토큰 재료 정제문(메모리 전용 — 디스크에 쓰지 않는다)
    subject: str = ""                           # 제목 요지 재료(메일·일정 제목, 팀즈 방 이름·본문 앞)
    names: tuple[tuple[str, str], ...] = ()     # (문서군 키, 정제된 문서 이름) — 파일·첨부·창 문서
    mail_doms: frozenset[str] = frozenset()     # 상대 원 도메인(R6·규칙 if.domain 대조, 로컬 전용)
    t_end: int = 0                              # 구간 끝(일정·창·연산), 없으면 0
    flags: frozenset[str] = frozenset()         # FLAG_KEEP 중 켜진 것
    refs: frozenset[str] = frozenset()          # manual ref_keys(증거 키)
    peers: frozenset[str] = frozenset()         # 상대 who_key(나 제외)

    def text_lower(self) -> str:
        return self.text.lower()


def _ent_of(text: str) -> Mapping[str, frozenset[str]]:
    e = _match.ent_tokens(text)
    if not any(e.values()):
        return _EMPTY_ENT
    return MappingProxyType({k: frozenset(v) for k, v in e.items()})


def feat(id: str, kind: str, text: str = "", *, boiler=None, **kw) -> Feat:
    """정제문 하나로 특징을 만든다(골든 시험·합집합 특징·도구용). 토큰·꺾쇠 토큰은 text 에서 뽑는다."""
    t = str(text or "")
    if "exts" in kw:
        kw["exts"] = frozenset(e.lower() for e in kw["exts"])
    for k in ("dom_labels", "dir_keys", "fams", "mail_doms", "flags", "refs", "peers"):
        if k in kw:
            kw[k] = frozenset(kw[k])
    return Feat(id=id, kind=kind, toks=frozenset(_match.match_tokens(t, boiler)), ent=_ent_of(t), text=t, **kw)


def union_feat(feats: Iterable[Feat], id: str, kind: str = "file") -> Feat:
    """특징 여러 개의 합집합(문서군 하나 = 합집합 특징 하나 — H §4.5·§4.6). 시각은 가장 이른 것."""
    fs = list(feats)
    if not fs:
        return Feat(id=id, kind=kind)
    ent: dict[str, set] = {k: set() for k in _match.ENT_KINDS}
    for f in fs:
        for k, v in f.ent.items():
            ent.setdefault(k, set()).update(v)
    apps = {f.app for f in fs if f.app}
    cats = {f.app_cat for f in fs if f.app_cat}
    roots = {f.root_id for f in fs if f.root_id}
    ts = [f.t for f in fs if f.t]
    return Feat(
        id=id, kind=kind, t=min(ts) if ts else 0,
        toks=frozenset().union(*(f.toks for f in fs)),
        ent=MappingProxyType({k: frozenset(v) for k, v in ent.items()}) if any(ent.values()) else _EMPTY_ENT,
        dom_labels=frozenset().union(*(f.dom_labels for f in fs)),
        app=next(iter(apps)) if len(apps) == 1 else "", app_cat=next(iter(cats)) if len(cats) == 1 else "",
        exts=frozenset().union(*(f.exts for f in fs)), dir_keys=frozenset().union(*(f.dir_keys for f in fs)),
        root_id=next(iter(roots)) if len(roots) == 1 else "",
        fams=frozenset().union(*(f.fams for f in fs)),
        weight_mult=max(f.weight_mult for f in fs),
        text=" ".join(f.text for f in fs if f.text),
        names=tuple(sorted({n for f in fs for n in f.names})),
        mail_doms=frozenset().union(*(f.mail_doms for f in fs)))


# ───────────────────────── 문서군 키(시간 코어와 같은 규칙) ─────────────────────────
class FamKeyer:
    """`lm27.time.evidence` 의 이름·폴더 색인(`_index_names`)과 `fam_ctx` 를 그대로 따른다 — HierTags.fam 키가 시간 코어
    `DocE.fam`·`Samp.fam`·첨부 문서군 키와 같아지도록(W1a CR · 계약 §4.3). 색인은 모든 행(사적 행 포함)에서 만든다."""

    def __init__(self, records: Iterable[Mapping], cfg=None):
        self.cfg = default_cfg(cfg)
        self.stems = generic_stems(self.cfg)
        self.names: dict[str, tuple[int, str]] = {}
        self.dirs: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        self._cache: dict[tuple, str] = {}
        for r in records:
            if isinstance(r, Mapping):
                self._index(r)

    def _note(self, dk, name, prio: int) -> None:
        if not dk or not isinstance(name, str) or not name.strip():
            return
        cur = self.names.get(dk)
        cand = (prio, name)
        if cur is None or cand < cur:
            self.names[dk] = cand

    def _index(self, r: Mapping) -> None:
        kind = r.get("kind")
        if kind == "pc_file":
            dk = r.get("doc_key")
            nm = r.get("name_masked")
            if isinstance(nm, str) and nm and isinstance(r.get("ext"), str) and "." not in nm[-6:]:
                nm = nm + r["ext"]
            self._note(dk, nm, 0)
            dks = _str_list(r.get("dir_keys"))[:2]
            if dk and dks:
                self.dirs[dk].add(tuple(dks))
        elif kind == "mail":
            for k, nm in zip(_str_list(r.get("attach_keys")), _str_list(r.get("attach_names_masked")), strict=False):
                self._note(k, nm, 1)
        elif kind == "teams":
            for k, nm in zip(_str_list(r.get("file_keys")), _str_list(r.get("file_names_masked")), strict=False):
                self._note(k, nm, 1)
        elif kind == "pc_session":
            ti = r.get("title_masked")
            if isinstance(ti, str) and ti:
                self._note(r.get("doc_key"), ti.split(" - ")[0], 2)

    def key(self, dk, name: str | None = None, dirs: Iterable[str] | None = None) -> str:
        """doc_key(+이름·폴더 키) → 시간 코어 문서군 키. 이름·폴더를 모르면 색인(파일 행)을 쓴다."""
        if not dk or not isinstance(dk, str):
            return ""
        nm = name if (isinstance(name, str) and name.strip()) else self.names.get(dk, (9, None))[1]
        dk_dirs = tuple(dirs) if dirs else None
        ck = (dk, nm, dk_dirs)
        hit = self._cache.get(ck)
        if hit is not None:
            return hit
        if dk_dirs is None:
            ds = self.dirs.get(dk)
            dk_dirs = next(iter(ds)) if ds and len(ds) == 1 else ()
        f = fam_key(dk, nm, dk_dirs, self.cfg, stems=self.stems)
        self._cache[ck] = f
        return f

    def best_name(self, dk) -> str:
        """색인의 최선 이름(파일 > 첨부 > 창 — 처리 순서와 무관)."""
        return self.names.get(dk, (9, ""))[1] or ""


def _fam_ok(f: str) -> bool:
    return bool(f) and f != B_GENERIC


# ───────────────────────── 상대 계급 ─────────────────────────
@lru_cache(maxsize=1)
def _personal_domains() -> frozenset[str]:
    from lm27.privacy.rules import PERSONAL_MAIL_DOMAINS   # 지연 import — 정제 규칙의 공용 개인 메일 도메인 표(단일원)
    return frozenset(d.lower() for d in PERSONAL_MAIL_DOMAINS)


def _dom_match(d: str, x: str) -> bool:
    x = str(x or "").lower().strip(".")
    return bool(x) and (d == x or d.endswith("." + x))


def domain_class(dom: str, reg, personal: Iterable[str] | None = None) -> str:
    """메일 도메인 → 계급(H §4.1): 사내 > 개인메일 > 고객사:<id> > 협력사:<id> > 공공 계급 > 도메인 소문자."""
    d = str(dom or "").lower().strip().strip(".")
    if not d:
        return ""
    if any(_dom_match(d, x) for x in (get(reg, "internal_domains", ()) or ())):
        return INTERNAL
    pers = _personal_domains() if personal is None else frozenset(personal)
    if d in pers:
        return PERSONAL
    for c in get(reg, "customers", ()) or ():
        if any(_dom_match(d, x) for x in (c.get("domains") or ())):
            return "고객사:" + str(c.get("id"))
    for v in get(reg, "partners", ()) or ():
        if any(_dom_match(d, x) for x in (v.get("domains") or ())):
            return "협력사:" + str(v.get("id"))
    pub = get(reg, "public_suffix", {}) or {}
    for suf in sorted(pub, key=lambda s: (-len(s), s)):
        if d.endswith(str(suf).lower()):
            return str(pub[suf])
    return d


@dataclass(frozen=True)
class PersonClasses:
    """who_key → (계급 집합, 원 도메인 집합). 본인(self:true) 항목은 싣지 않는다."""
    labels: Mapping[str, frozenset[str]] = field(default_factory=dict)
    domains: Mapping[str, frozenset[str]] = field(default_factory=dict)


def person_classes(person_dir, reg, personal: Iterable[str] | None = None) -> PersonClasses:
    """로컬 사람 사전(`lm27-persondir/1`) → 상대 계급 색인. 사전이 없으면 빈 색인(받은 메일 sender_label 만 쓴다 — H §14)."""
    people = get(person_dir, "people", None) if person_dir is not None else None
    if not isinstance(people, Mapping):
        return PersonClasses()
    labels: dict[str, frozenset[str]] = {}
    doms: dict[str, frozenset[str]] = {}
    for wk in sorted(people):
        p = people[wk]
        if not isinstance(p, Mapping) or p.get("self"):
            continue
        ls, ds = set(), set()
        for addr in _str_list(p.get("smtp")):
            dom = addr.rsplit("@", 1)[-1].lower().strip() if "@" in addr else ""
            if dom:
                ds.add(dom)
                c = domain_class(dom, reg, personal)
                if c:
                    ls.add(c)
        if not ls and p.get("internal"):
            ls.add(INTERNAL)
        if ls:
            labels[wk] = frozenset(ls)
        if ds:
            doms[wk] = frozenset(ds)
    return PersonClasses(labels, doms)


# ───────────────────────── 행 → Feat ─────────────────────────
def _kind_of(r: Mapping) -> str:
    kind, src = r.get("kind"), str(r.get("src") or "")
    if src.endswith(".copilot"):
        return "summary"
    if kind in ("mail", "teams", "cal", "manual"):
        return kind
    if kind == "pc_file":
        return "file"
    if kind == "pc_session":
        return "win" if src == "pc.sampler" else ""          # pc.events 는 특징이 없다(X-244)
    if kind == "pc_git":
        return "git"
    if kind == "pc_compute":
        return "compute"
    return ""


def _act_of(r: Mapping) -> str:
    a = r.get("act")
    if isinstance(a, str) and a:
        return a
    cues = set(_str_list(r.get("act_cues")))
    return next((act for c, act in CUE_ACT if c in cues), "")


def _ext_of(name: str) -> str:
    m = _EXT_RX.search(_nfkc(name).lower())
    return "." + m.group(1) if m else ""


class _Builder:
    def __init__(self, records: list[Mapping], reg, person_dir, catalog, cfg):
        self.cfg = default_cfg(cfg)
        self.reg = reg
        self.keyer = FamKeyer(records, self.cfg)
        self.pc = person_classes(person_dir, reg)
        self.off_min = int(self.cfg["time.tzOffsetMin"])
        self.summary_mult = float(self.cfg["hier.rule.summaryMult"])
        self.boiler = _match.boilerplate(self.cfg)
        self.catalog = catalog
        self._extra = None
        self._cat_cache: dict[str, str] = {}
        self.retracted = {str(r.get("retract_of")) for r in records
                          if r.get("kind") == "manual" and r.get("man_kind") == "retract" and r.get("retract_of")}

    def cat_of(self, app: str) -> str:
        if not app:
            return ""
        hit = self._cat_cache.get(app)
        if hit is None:
            cat = self.catalog
            if cat is None:
                from lm27 import catalog as cat              # 지연 import — 카탈로그 단일원(X-245)
                self.catalog = cat
            if self._extra is None:
                pe = getattr(cat, "programs_extra", None)
                self._extra = tuple(pe(self.cfg)) if callable(pe) else ()
            hit = cat.cat_of(app, self._extra) if self._extra else cat.cat_of(app)
            self._cat_cache[app] = hit or ""
        return hit

    def peers_of(self, r: Mapping) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        who = set(_str_list(r.get("counterpart_keys")))
        for k in ("sender_key", "author_key"):
            v = r.get(k)
            if isinstance(v, str) and v.startswith("w"):
                who.add(v)
        labels, doms = set(), set()
        for w in who:
            labels |= self.pc.labels.get(w, frozenset())
            doms |= self.pc.domains.get(w, frozenset())
        return frozenset(labels), frozenset(doms), frozenset(who)

    def build(self, r: Mapping) -> Feat | None:
        fk = _kind_of(r)
        if not fk:
            return None
        if r.get("priv_class") in SKIP_PRIV or _flags(r).get("ad"):
            return None
        rid = str(r.get("id") or "")
        if not rid:
            return None
        kind = r.get("kind")
        fl = _flags(r)
        t = lsec_of(r.get("ts_utc"), self.off_min)
        t_end = lsec_of(r.get("ts_end"), self.off_min) if r.get("ts_end") else 0
        common = {"t": t, "t_end": t_end, "src": str(r.get("src") or ""),
                  "flags": frozenset(k for k in FLAG_KEEP if fl.get(k))}
        key = str(r.get("msg_key") or rid)
        if fk == "summary":
            text = _nfkc(r.get("text_masked"))
            return self._mk(rid, fk, text, key=key, subject=text[:60], weight_mult=self.summary_mult, **common)
        if kind == "mail":
            subj = _nfkc(r.get("subject_masked"))
            att_names = _str_list(r.get("attach_names_masked"))
            cats = _str_list(r.get("categories_masked"))
            text = " ".join([subj, *att_names, *cats]).strip()
            labels, doms, who = self.peers_of(r)
            sl = r.get("sender_label")
            d = r.get("direction")
            if isinstance(sl, str) and sl and d == "in":
                labels = labels | {sl}
            names = tuple((self.keyer.key(k, nm), nm)
                          for k, nm in zip(_str_list(r.get("attach_keys")), att_names, strict=False))
            exts = {e if e.startswith(".") else "." + e for e in (x.lower() for x in _str_list(r.get("attach_exts")))}
            exts |= {_ext_of(nm) for _f, nm in names if _ext_of(nm)}
            return self._mk(rid, fk, text, key=key, conv=str(r.get("thread_key") or key), subject=subj,
                            dom_labels=labels, mail_doms=doms, peers=who, direction=d if d in ("in", "out") else "",
                            act=_act_of(r), exts=frozenset(exts), names=tuple(n for n in names if _fam_ok(n[0])),
                            fams=frozenset(f for f, _n in names if _fam_ok(f)), **common)
        if kind == "teams":
            title = _nfkc(r.get("chat_title_masked"))
            body = _nfkc(r.get("body_masked"))[:_BODY_HEAD]
            fnames = _str_list(r.get("file_names_masked"))
            text = " ".join(x for x in [title, body, *fnames] if x).strip()
            labels, doms, who = self.peers_of(r)
            conv = str(r.get("chat_key") or key)
            if r.get("chat_type") == "channel" and r.get("thread_key"):
                conv = f"{conv}:{r['thread_key']}"
            dr = r.get("direction")
            names = tuple((self.keyer.key(k, nm), nm)
                          for k, nm in zip(_str_list(r.get("file_keys")), fnames, strict=False))
            return self._mk(rid, fk, text, key=key, conv=conv, subject=(title or body)[:60], dom_labels=labels,
                            mail_doms=doms, peers=who,
                            direction="out" if dr == "sent" else ("in" if dr == "received" else ""),
                            act=_act_of(r), exts=frozenset(e for e in (_ext_of(n) for n in fnames) if e),
                            names=tuple(n for n in names if _fam_ok(n[0])),
                            fams=frozenset(f for f, _n in names if _fam_ok(f)), **common)
        if kind == "cal":
            subj = _nfkc(r.get("subject_masked"))
            cats = _str_list(r.get("categories_masked"))
            personal = int(fl.get("sensitivity") or 0) >= 1 or bool(fl.get("cat_private")) or bool(fl.get("private"))
            labels, doms, who = (frozenset(), frozenset(), frozenset()) if personal else self.peers_of(r)
            text = "" if personal else " ".join([subj, *cats]).strip()
            return self._mk(rid, fk, text, key=key, subject="" if personal else subj, dom_labels=labels,
                            mail_doms=doms, peers=who, **common)
        if kind == "pc_file":
            nm = _nfkc(r.get("name_masked"))
            ext = str(r.get("ext") or "").lower()
            if ext and not ext.startswith("."):
                ext = "." + ext
            dk = r.get("doc_key")
            dks = _str_list(r.get("dir_keys"))
            f = self.keyer.key(dk, nm or None, dks[:2]) if dk else ""
            full = nm if (not ext or nm.lower().endswith(ext)) else nm + ext
            return self._mk(rid, fk, nm, key=key, exts=frozenset({ext}) if ext else frozenset(),
                            dir_keys=frozenset(dks[:3]), root_id=str(r.get("root_id") or ""),
                            fams=frozenset({f}) if _fam_ok(f) else frozenset(),
                            names=((f, full),) if _fam_ok(f) and full else (), **common)
        if kind == "pc_session":
            title = _nfkc(r.get("title_masked"))
            app = str(r.get("app_id") or "")
            dk = r.get("doc_key")
            f = self.keyer.key(dk, title.split(" - ")[0] if title else None) if dk else ""
            nm = title.split(" - ")[0] if title else ""
            return self._mk(rid, fk, title, key=key, app=app, app_cat=self.cat_of(app),
                            dir_keys=frozenset(_str_list(r.get("dir_keys"))[:3]),
                            fams=frozenset({f}) if _fam_ok(f) else frozenset(),
                            names=((f, nm),) if _fam_ok(f) and nm else (), **common)
        if kind == "pc_git":
            dk = str(r.get("doc_key") or "")
            exts = {e if e.startswith(".") else "." + e for e in (x.lower() for x in _str_list(r.get("exts")))}
            return self._mk(rid, fk, _nfkc(r.get("msg_masked")), key=key, exts=frozenset(exts),
                            fams=frozenset({dk}) if dk else frozenset(), **common)
        if kind == "pc_compute":
            app = str(r.get("app_id") or "")
            f = self.keyer.key(r.get("doc_key")) if r.get("doc_key") else ""
            return self._mk(rid, fk, "", key=key, app=app, app_cat=self.cat_of(app),
                            fams=frozenset({f}) if _fam_ok(f) else frozenset(), **common)
        if kind == "manual":
            mk = r.get("man_kind")
            if mk in MAN_SKIP or rid in self.retracted:
                return None
            text = " ".join(x for x in (_nfkc(r.get("text_masked")), _nfkc(r.get("work_category"))) if x)
            man = {k: str(r.get(k) or "") for k in ("project_id", "role_field", "role_func")}
            return self._mk(rid, fk, text, key=key, subject=_nfkc(r.get("text_masked"))[:60],
                            manual=MappingProxyType(man) if any(man.values()) else None,
                            refs=frozenset(_str_list(r.get("ref_keys"))), **common)
        return None

    def _mk(self, rid: str, kind: str, text: str, **kw) -> Feat:
        return Feat(id=rid, kind=kind, toks=frozenset(_match.match_tokens(text, self.boiler)) if text else frozenset(),
                    ent=_ent_of(text) if text else _EMPTY_ENT, text=text, **kw)


def features_of(records: Iterable[Mapping], reg, person_dir=None, catalog=None, cfg=None) -> list[Feat]:
    """정제·병합이 끝난 증거 행 → 분류 특징(H §4.1). 같은 id 는 하나만(정렬 후 첫 행). 결과는 (t, id) 순."""
    rows = [r for r in records if isinstance(r, Mapping)]
    b = _Builder(rows, reg, person_dir, catalog, cfg)
    seen: set[str] = set()
    out: list[Feat] = []
    for r in sorted(rows, key=lambda x: (str(x.get("id") or ""), str(x.get("observed_at") or ""),
                                         str(x.get("src") or ""))):
        rid = str(r.get("id") or "")
        if rid in seen:
            continue
        f = b.build(r)
        if f is not None:
            seen.add(rid)
            out.append(f)
    out.sort(key=lambda f: (f.t, f.id))
    return out


def text_key(f: Feat) -> tuple[frozenset[str], str]:
    """점수 메모 키(같은 정제문·토큰의 특징은 텍스트 규칙 결과가 같다)."""
    return f.toks, ukey(f.text) if f.text else ""
