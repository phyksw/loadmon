# -*- coding: utf-8 -*-
r"""명명 군집과 이름 — `name_groups` · `rule_title` · 제목 캐시(H §5, 계약 §2.10 · §3.15).

- **명명 군집은 이름·라벨을 함께 붙이기 위한 묶음이다. 인스턴스를 합치지 않는다**(H-I5): 군집 안의 단위업무는 각자
  `unit_id`·투입·리드타임을 그대로 가진다. 코파일럿에는 군집 하나를 항목 하나로 보낸다.
- 묶는 조건(합집합-찾기, `unit_id` 순 — 결정적): G1 `follow_of`(같은 문서군의 앞 인스턴스) · G2 둘 다 SELF 이고 범용이 아닌
  문서군 공유 · G3 범용이 아닌 강한 문서군(강도 3 — 첨부·must_link) 공유 + 주 상대 같음. 제약(어기면 그 합치기를 건너뜀):
  군집 안 확정 과제(출처 user·token·rule) ≤ 1 · 크기 ≤ `hier.name.maxGroup` · 범용 문서군으로는 묶지 않음 · APP 는 앱만으로 묶지 않음.
- 대표 = 첫 차수 시작이 가장 이른 구성원(동률 unit_id). 군집 키 = `grp:` + sha1(대표 시작 근거 키)[:12](계약 §4.4) — 군집이
  자라도 대표가 바뀌지 않으므로 키가 안정하다.
- 규칙 이름(`rule_title`) 순서: doc(범용 아닌 문서군 중 귀속 분 최대의 최근 이름) → subject(대표 시작 근거 제목) →
  app(앱 범주 이름 + ' 작업') → generic('<분야 이름>·<기능 이름> 단위업무'). `title_src` 저장값은 `rule_` 접두(계약 §3.15).
  시간 코어 업무 표지(`SELF:…@MM-DD`·`MANUAL:t:…` — W-G8 키로만 만든 label)와 로컬 키 모양은 어느 단계에서도 이름이 되지
  않는다(W2 검토 C08 — `is_marker`). MANUAL 업무는 사용자가 적은 수동 기록 글이 제목 재료다(`unitlabel._subjects`).
- 제목 캐시 `data\local_only\hier\title_cache.json`(`lm27.title_cache/1`) — 한 번 정한 이름을 고정한다(H §5.4). 군집이
  사라지면 `hier.name.cacheKeepDays` 뒤 지운다. 쓰기는 `fsx.atomic_write`, 직전 판은 `.bak`.

표준 라이브러리만 쓴다.
"""
import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from lm27.hier import match as _match
from lm27.hier.features import default_cfg, get
from lm27.hier.names import ukey
from lm27.time.tokens import GENERIC_RE, is_generic_key
from lm27.util import fsx

__all__ = [
    "APP_CAT_NAME", "CONFIRMED_SOURCES", "Group", "TITLE_SRC", "TitleCache", "app_cat_name", "clip_title", "day_of",
    "display_stem", "group_key", "is_generic_stem", "is_marker", "name_groups", "rule_title", "subject_title",
    "title_material",
]

CONFIRMED_SOURCES = frozenset({"user", "token", "rule"})
TITLE_SRC = ("user", "ai", "rule_doc", "rule_subject", "rule_app", "rule_generic")
CACHE_SCHEMA = "lm27.title_cache/1"
CACHE_FILE = "title_cache.json"
CACHE_BAK = "title_cache.json.bak"
TAIL = re.compile(r"([_\-\s]?(v\d+(\.\d+)?|rev\d+|r\d+|최종|final|수정본?|사본|copy|\(\d+\)|\d{6,8}))$", re.I)
_EXT = re.compile(r"\.[0-9A-Za-z]{1,5}$")
_DS_TOKENS = re.compile(r"\[과제:[^\]]+\]|\[사람[^\]]*\]|\[나\]")
_SUBJ_TOKENS = re.compile(r"\[과제:[^\]]+\]|\[사람[^\]]*\]|\[나\]|\[이메일@[^\]]*\]|\[전화\]|\[금액\]")
_SUBJ_STEMS = ("부탁", "요청", "검토", "송부", "공유", "회신", "보고")
# 시간 코어 업무 표지(W-G8 — 키로만 만든 'SELF:<문서군 키>@MM-DD' · 'MANUAL:t:<해시>' 등)와 로컬 키 모양은 이름이 아니다(W2 검토 C08)
_MARKER_RX = re.compile(r"^\s*(?:S1|ACK|COORD|SELF|APP|REPORT(?:_ONLY)?|MANUAL)\s*:", re.I)
_KEYISH_RX = re.compile(r"(?<![0-9A-Za-z])(?:[a-z]?(?=[0-9]*[a-f])[0-9a-f]{12,}|[a-z]\d*:[0-9a-f]{8,})(?![0-9a-f])")
# 앱 범주 → 프롬프트·이름 표기(H §6.2 표). 사무·소통은 앱별, 미상은 '미상 프로그램'(exe 이름을 내보내지 않는다)
APP_CAT_NAME = {"CAD": "CAD 프로그램", "해석": "해석 프로그램", "광학": "광학 설계 프로그램", "EDA": "회로 설계 프로그램",
                "FPGA": "FPGA 도구", "SW": "개발 도구", "계측": "계측 프로그램"}
_OFFICE_APP = {"excel": "엑셀", "word": "워드", "powerpoint": "파워포인트", "pdf_tools": "PDF", "onenote": "메모",
               "file_utils": "메모", "hancom_office": "한글", "office_other": "사무 프로그램"}
_COMM_APP = {"outlook": "메일", "teams": "메신저", "slack": "메신저", "web_meeting": "화상 회의",
             "edge": "웹 브라우저", "chrome": "웹 브라우저", "web_browser": "웹 브라우저", "remote_access": "원격 접속",
             "private_messenger": "메신저"}
UNKNOWN_APP = "미상 프로그램"


def app_cat_name(cat: str, app_id: str = "") -> str:
    """앱 범주(카탈로그 한글 9종) → 프롬프트·이름 표기. 사무·소통은 앱별 이름, 카탈로그 밖·미상은 '미상 프로그램'."""
    if cat in APP_CAT_NAME:
        return APP_CAT_NAME[cat]
    if cat == "사무":
        return _OFFICE_APP.get(app_id, "사무 프로그램")
    if cat == "소통":
        return _COMM_APP.get(app_id, "메신저")
    return UNKNOWN_APP


# ───────────────────────── 군집(H §5.2) ─────────────────────────
@dataclass(frozen=True)
class Group:
    key: str                                   # 'grp:' + 12hex
    anchor: str                                # 대표 시작 근거 키(로컬 키 — local_only 에만)
    rep: str                                   # 대표 unit_id
    members: tuple[str, ...]                   # unit_id 정렬
    effort_min: int = 0                        # 구성원 투입 합(정수 분)
    first_t: int = 0                           # 대표 첫 차수 시작(로컬 초)
    last_t: int = 0                            # 구성원 마지막 근거 시각(로컬 초)


def group_key(anchor_key: str) -> str:
    """군집 키 'grp:' + sha1(anchor_key)[:12](계약 §4.4)."""
    return "grp:" + hashlib.sha1(str(anchor_key).encode("utf-8")).hexdigest()[:12]


def _uid(t) -> str:
    return str(get(t, "unit_id", None) or get(t, "id", "") or "")


def _fams(t) -> dict[str, int]:
    d = get(t, "fams", None)
    if d is None:
        d = get(t, "docs", None)
    if not isinstance(d, Mapping):
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, int) and not isinstance(v, bool):
            out[str(k)] = v
        elif isinstance(v, Mapping) and isinstance(v.get("strength"), int):
            out[str(k)] = int(v["strength"])
        else:
            out[str(k)] = 2
    return out


def _start(t) -> int:
    s = get(t, "start", None)
    if isinstance(s, int) and s:
        return s
    cs = get(t, "cycles", None) or []
    vals = [get(c, "s", None) for c in cs]
    vals = [v for v in vals if isinstance(v, int)]
    return min(vals) if vals else 0


def _last(t) -> int:
    e = get(t, "end", None)
    if isinstance(e, int) and e:
        return e
    cs = get(t, "cycles", None) or []
    vals = [x for c in cs for x in (get(c, "e", None), get(c, "s", None)) if isinstance(x, int)]
    return max(vals) if vals else 0


def name_groups(tasks: Iterable, rule_labels: Mapping, cfg=None, *, generic=None) -> list[Group]:
    """명명 군집(H §5.2). tasks = UnitIn·tasks.json 행·UnitTask, rule_labels = {unit_id: RuleLabel}(확정 과제 제약).
    generic = 문서군 키 → 범용인가(기본 `lm27.time.tokens.is_generic_key` — '@' 키·B_GENERIC). 결과는 군집 키 순."""
    cfg = default_cfg(cfg)
    max_group = int(cfg["hier.name.maxGroup"])
    gen = generic if generic is not None else is_generic_key
    units = {}
    for t in tasks:
        uid = _uid(t)
        if uid:
            units[uid] = t
    ids = sorted(units)
    parent = {u: u for u in ids}
    members = {u: {u} for u in ids}
    confirmed = {}
    for u in ids:
        rl = rule_labels.get(u) if rule_labels else None
        src = get(rl, "source", None)
        proj = get(rl, "project", None)
        if src in CONFIRMED_SOURCES and proj:
            confirmed[u] = proj

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def projs(root: str) -> set:
        return {confirmed[m] for m in members[root] if m in confirmed}

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if len(projs(ra) | projs(rb)) > 1 or len(members[ra]) + len(members[rb]) > max_group:
            return
        lo, hi = sorted((ra, rb))
        parent[hi] = lo
        members[lo] |= members.pop(hi)

    fams = {u: _fams(units[u]) for u in ids}
    kinds = {u: str(get(units[u], "kind", "") or "") for u in ids}
    peers = {u: str(get(units[u], "peer", "") or "") for u in ids}
    for u in ids:                                                       # G1 follow_of
        fo = get(units[u], "follow_of", None)
        if isinstance(fo, str) and fo in parent:
            union(u, fo)
    pairs: set[tuple[str, str]] = set()
    by_fam: dict[str, list[str]] = defaultdict(list)
    for u in ids:
        if kinds[u] == "SELF":
            for fk in fams[u]:
                if not gen(fk):
                    by_fam[fk].append(u)
    for lst in by_fam.values():                                         # G2 SELF 문서군 공유
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                pairs.add((min(a, b), max(a, b)))
    for a, b in sorted(pairs):
        union(a, b)
    pairs = set()
    by_strong: dict[tuple[str, str], list[str]] = defaultdict(list)
    for u in ids:
        if peers[u]:
            for fk, st in fams[u].items():
                if st >= 3 and not gen(fk):
                    by_strong[(fk, peers[u])].append(u)
    for lst in by_strong.values():                                      # G3 강한 문서군 + 같은 상대
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                pairs.add((min(a, b), max(a, b)))
    for a, b in sorted(pairs):
        union(a, b)
    out = []
    for root in sorted({find(u) for u in ids}):
        ms = sorted(members[root])
        rep = min(ms, key=lambda m: (_start(units[m]) or 1 << 62, m))
        anchor = str(get(units[rep], "first_key", "") or "") or rep
        eff = sum(int(get(units[m], "effort_min", 0) or 0) for m in ms)
        out.append(Group(group_key(anchor), anchor, rep, tuple(ms), eff, _start(units[rep]),
                         max((_last(units[m]) for m in ms), default=0)))
    seen: dict[str, Group] = {}
    for g in sorted(out, key=lambda x: (x.key, x.rep)):                  # 같은 시작 근거 키(드묾)는 대표 ID 로 가른다
        k = g.key if g.key not in seen else group_key(g.anchor + "|" + g.rep)
        seen[k] = Group(k, g.anchor, g.rep, g.members, g.effort_min, g.first_t, g.last_t)
    return [seen[k] for k in sorted(seen)]


# ───────────────────────── 규칙 이름(H §5.3) ─────────────────────────
def display_stem(name: str) -> str:
    """문서 이름 → 표시 줄기: 확장자·과제/사람 토큰·판·날짜·사본 꼬리(최대 5회) 제거, 구분자 → 공백."""
    x = unicodedata.normalize("NFKC", str(name or ""))
    x = _EXT.sub("", x)
    x = _DS_TOKENS.sub(" ", x)
    for _ in range(5):
        y = TAIL.sub("", x).strip(" _-")
        if y == x:
            break
        x = y
    x = re.sub(r"[_\-]+", " ", x)
    return " ".join(x.split())


def subject_title(subj: str, boiler: Iterable[str] | None = None) -> str:
    """제목 → 이름 후보: 회신·전달 머리·꺾쇠 가림 토큰·상용구·'부탁/요청/검토…' 꼴 낱말 제거."""
    bp = frozenset(boiler) if boiler is not None else _match.boilerplate(None)
    x = unicodedata.normalize("NFKC", str(subj or ""))
    x = _match.RE_PREFIX.sub("", x)
    x = _SUBJ_TOKENS.sub(" ", x)
    words = [w for w in x.split() if w.lower().strip(".,") not in bp
             and not any(w.startswith(b) and len(w) - len(b) <= 2 for b in _SUBJ_STEMS)]
    return " ".join(words).strip(" .,")


def clip_title(t: str, n: int = 25) -> str:
    """n 자로 자른다 — 8자 이후의 마지막 공백에서 끊는다."""
    t = str(t or "")
    if len(t) <= n:
        return t
    cut = t[:n]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp >= 8 else cut).strip()


def is_generic_stem(stem: str, stems: Iterable[str]) -> bool:
    """범용 줄기(보고서·자료·문서·회의록·untitled …)인가 — `episode.docs.genericStems` + 시간 코어 범용 정규식."""
    k = ukey(stem)
    if not k:
        return True
    if k in {ukey(x) for x in stems}:
        return True
    return bool(GENERIC_RE.match(unicodedata.normalize("NFKC", stem).lower().strip()))


def _bad(st: str, stems) -> bool:
    return len(st) < 2 or st.replace(" ", "").isdigit() or is_generic_stem(st, stems) or is_marker(st)


def is_marker(s: str) -> bool:
    """시간 코어 업무 표지·로컬 키 모양인가(C08 — 제목·이름 재료로 쓰지 않는다)."""
    t = unicodedata.normalize("NFKC", str(s or ""))
    return bool(_MARKER_RX.match(t) or _KEYISH_RX.search(t))


def rule_title(group: Mapping, ctx=None) -> tuple[str, str]:
    """규칙 이름(H §5.3) → (이름, 출처 doc|subject|app|generic). group = {'docs': [(이름, 귀속 분)], 'subjects': [...],
    'app_cat': 범주, 'app_id': app_id, 'field': 코드, 'func': 코드}. ctx = {'reg', 'cfg'}(이름 표기·범용 줄기·글자 수)."""
    reg = get(ctx, "reg", None)
    cfg = default_cfg(get(ctx, "cfg", None))
    n = int(cfg["hier.name.titleMax"])
    stems = tuple(cfg["episode.docs.genericStems"])
    boiler = _match.boilerplate(cfg)
    for nm, _m in sorted(group.get("docs", ()), key=lambda x: (-x[1], str(x[0]))):
        st = display_stem(nm)
        if not _bad(st, stems):
            return clip_title(st, n), "doc"
    for s in group.get("subjects", ()):
        st = subject_title(s, boiler)
        if not _bad(st, stems):
            return clip_title(st, n), "subject"
    cat = group.get("app_cat") or ""
    if cat:
        return clip_title(app_cat_name(cat, group.get("app_id") or "") + " 작업", n), "app"
    fc, cc = group.get("field") or "ETC", group.get("func") or "ETC"
    return clip_title(f"{_vname(reg, 'fields', fc)}·{_vname(reg, 'functions', cc)} 단위업무", n), "generic"


def _vname(reg, kind: str, code: str) -> str:
    if reg is not None:
        it = reg.vocab.get(kind, {}).get(code)
        if it is not None:
            return it.name
    from lm27.hier.vocab import builtin_item                  # 레지스트리 없이(도구·시험) — 내장 어휘 이름
    it = builtin_item(kind, code)
    return it.name if it is not None else code


def title_material(g: Group, units: Mapping, rep_ff=None) -> dict:
    """군집 → `rule_title` 재료. 문서는 범용 아닌 문서군만(귀속 분 합 큰 순), 제목은 대표의 것, 앱은 귀속 분 최대 범주."""
    fam_min: dict[str, int] = defaultdict(int)
    fam_name: dict[str, str] = {}
    cat_min: dict[str, int] = defaultdict(int)
    app_min: dict[str, int] = defaultdict(int)
    for m in g.members:
        u = units.get(m)
        if u is None:
            continue
        for fk in sorted(set(get(u, "fams", {}) or {}) | set(get(u, "fam_min", {}) or {})):
            if is_generic_key(fk):
                continue
            fam_min[fk] += int((get(u, "fam_min", {}) or {}).get(fk, 0))
            nm = (get(u, "fam_names", {}) or {}).get(fk)
            if nm and (fk not in fam_name or nm > fam_name[fk]):
                fam_name[fk] = nm
        for cat, v in (get(u, "app_min", {}) or {}).items():
            cat_min[cat] += int(v)
        for a, v in (get(u, "app_ids", {}) or {}).items():
            app_min[a] += int(v)
    docs = [(fam_name[fk], fam_min[fk]) for fk in sorted(fam_name)]
    rep = units.get(g.rep)
    # 제목 재료는 H §5.3 의 넷(문서·제목·앱·일반)뿐 — 시간 코어 label 은 키로만 만든 표지라 쓰지 않는다(C08)
    subjects = [s for s in (get(rep, "subjects", ()) or ()) if not is_marker(s)] if rep is not None else []
    tech = {c: v for c, v in cat_min.items() if c in APP_CAT_NAME}
    pick = tech or dict(cat_min)
    cat = min(pick.items(), key=lambda kv: (-kv[1], kv[0]))[0] if pick else ""
    if not cat and rep is not None:
        for f, _w, r in get(rep, "ev", ()) or ():
            if r == "app" and f.app_cat:
                cat = f.app_cat
                break
    app_id = ""
    if cat and app_min:
        app_id = min(app_min.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return {"docs": docs, "subjects": subjects, "app_cat": cat, "app_id": app_id,
            "field": get(rep_ff, "field", "ETC") or "ETC", "func": get(rep_ff, "func", "ETC") or "ETC"}


# ───────────────────────── 제목 캐시(H §5.4) ─────────────────────────
@dataclass
class TitleCache:
    """`lm27.title_cache/1` — {groups: {12hex: {title, src, conf, at, prompt_ver, anchor, seen, ask?}}}."""
    groups: dict = field(default_factory=dict)
    path: object = None
    bak: object = None
    raw: bytes | None = None

    @classmethod
    def for_paths(cls, paths) -> "TitleCache":
        r"""`data\local_only\hier\title_cache.json`(+ .bak) — 경로는 lm27.paths 로만."""
        return cls.load(paths.hier_local_file(CACHE_FILE), paths.hier_local_file(CACHE_BAK))

    @classmethod
    def load(cls, path, bak=None) -> "TitleCache":
        """파일이 깨졌으면 .bak 로(둘 다 깨지면 빈 캐시). 파일이 없으면 빈 캐시."""
        obj, raw = _read_obj(path)
        if obj is None and bak is not None:
            obj, _ = _read_obj(bak)
        groups = obj.get("groups") if isinstance(obj, Mapping) and obj.get("schema") == CACHE_SCHEMA else None
        return cls(dict(groups) if isinstance(groups, Mapping) else {}, path, bak, raw)

    @staticmethod
    def k(gkey: str) -> str:
        return gkey[4:] if gkey.startswith("grp:") else gkey

    def get(self, gkey: str) -> dict | None:
        v = self.groups.get(self.k(gkey))
        return dict(v) if isinstance(v, Mapping) else None

    def put(self, gkey: str, **fields) -> None:
        cur = dict(self.groups.get(self.k(gkey)) or {})
        cur.update({k: v for k, v in fields.items() if v is not None})
        self.groups[self.k(gkey)] = cur

    def touch(self, gkey: str, day: str, anchor: str) -> None:
        cur = dict(self.groups.get(self.k(gkey)) or {})
        if day:
            cur["seen"] = day
        cur.setdefault("anchor", anchor)
        self.groups[self.k(gkey)] = cur

    def prune(self, today: date, keep_days: int) -> int:
        """마지막으로 본 날이 keep_days 보다 오래된 항목을 지운다. 지운 수."""
        lim = (today - timedelta(days=int(keep_days))).isoformat()
        old = [k for k, v in self.groups.items() if isinstance(v, Mapping) and str(v.get("seen") or "9999") < lim]
        for k in old:
            del self.groups[k]
        return len(old)

    def to_obj(self) -> dict:
        return {"schema": CACHE_SCHEMA, "groups": {k: self.groups[k] for k in sorted(self.groups)}}

    def save(self) -> bool:
        """원자 쓰기(직전 판은 .bak). 바뀐 것이 없으면 쓰지 않고 False."""
        if self.path is None:
            raise ValueError("TitleCache.save: 경로가 없습니다")
        data = fsx.canon_bytes(self.to_obj())
        if self.raw is not None and data == self.raw:
            return False
        if self.raw is not None and self.bak is not None:
            fsx.atomic_write(self.bak, self.raw)
        fsx.atomic_write(self.path, data)
        self.raw = data
        return True


def _read_obj(path):
    if path is None:
        return None, None
    try:
        raw = fsx.read_bytes(path)
    except OSError:
        return None, None
    try:
        obj = fsx.loads_strict(raw)
    except (ValueError, UnicodeDecodeError):
        return None, None
    return (obj, raw) if isinstance(obj, Mapping) else (None, None)


def day_of(now) -> date | None:
    """now(datetime·date·None) → 날짜."""
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return None
