# -*- coding: utf-8 -*-
r"""증거 정규화 — 저장 행 → 시간 코어 형(W §2 · 부록 A `evidence.py`, 계약 §2.9 · §3.1~§3.3 · §4.3 · X-200~X-206 · X-212).

`normalize(records, profile, cfg, as_of, tags) -> (Evidence, audit)`

- 입력 `records` 는 `lm27.normalize.load.load_evidence` 의 출력 행(정제·병합·파생 열 `act`·`subject_tokens` 부착,
  계약 §2.7)이다. 원문은 없다. 시간 코어는 정제된 키·열거·정제문 토큰만 읽는다.
- 시각: `ts_utc`(UTC) → 근무 시간대 로컬 초 lsec(기준점 2020-01-01 00:00 로컬, 오프셋은 `time.tzOffsetMin` 하나 —
  W §2.1 · 계약 §3.14 · X-174). `ts_local_offset` 은 관측 순간 오프셋일 뿐 변환에 쓰지 않는다.
- 정밀도(W §2.1): `unknown` 은 격리(건수만), `date`·`summary` 는 시간 근거가 아니다(봉투는 `envelope.py` 가 판정).
- 사적·친목·광고 메시지는 버리고 건수만 남긴다(P R-P1·R-P2). 창 표본은 버리지 않고 사적 표본(부정 증거)으로 둔다.
- 형 대응: `pc_session`(pc.sampler) → `Samp`(X-201 앱 분류·X-202 세션 상태), `pc_session`(pc.events) → `PcSpan`
  (끝 불확실은 '확실한 끝'까지만), `mail`·`teams` → `Msg`(X-203), `cal` → `Meet`(X-204), `pc_file` → `DocE`(X-200),
  `pc_compute` → `Comp`, `pc_git` → `Commit`(X-216), `manual` → `Man`.
- 문서군 키는 `lm27.time.tokens.fam_key`(계약 §4.3). 이름(정제된 `name_masked`·첨부 이름)은 범용 판정·토큰에만 쓰고
  `Evidence.fam_names`·`fam_tokens` 로 로컬 분석에만 넘긴다(팀 반출물에 넣지 않는다 — W §2.1).
- 결정성(관문 G2): 모든 목록을 정준 키로 정렬하고, 중복 동률은 레코드 id 로 가른다. 입력 순서와 무관하다.

지연 import(첫 사용 때만): `lm27.privacy.keys`(문서군 정규화), `lm27.catalog`(기타 공학 앱 범주),
`lm27.normalize.absence`(일정 근태 범주). 표준 라이브러리 외 다른 의존은 없다. 파일을 쓰지 않는다.
"""
from __future__ import annotations

import functools
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from lm27.time.calendar import DAY, EPOCH, d_of
from lm27.time.tokens import B_GENERIC, boilerplate, fam, fam_key, generic_stems, raw_tokens

__all__ = [
    "ACTS",
    "Comp",
    "Commit",
    "DocE",
    "Evidence",
    "Man",
    "Meet",
    "Msg",
    "PcSpan",
    "Samp",
    "lsec_of",
    "normalize",
]

MIN, HOUR = 60, 3600
PRECS = ("exact", "minute", "date", "summary", "unknown")
PREC_RANK = {"exact": 0, "minute": 1, "date": 2, "summary": 3}
EXACT = ("exact", "minute")
ACTS = ("request", "ack", "question", "report", "info", "notice", "social")
CUE_ACT = (("req", "request"), ("rep", "report"), ("done", "report"), ("ack", "ack"), ("ask", "question"),
           ("sched", "info"), ("cancel", "info"), ("fyi", "info"))
PRIV_CLASSES = ("work", "unknown", "media", "private", "social")
MAN_KINDS = ("work", "offsite", "instr", "report", "absence", "exclude", "attended", "must_link", "cannot_link",
             "retract")
LEAVE_CODES = ("full", "am", "pm")
COVERAGE_STATUS = ("ok", "zero_ok", "partial", "out_of_horizon", "blocked", "transport_fail", "not_attempted")
AXES = ("mail_in", "mail_out", "cal", "teams", "pc")
# X-201: 저장 app_class → 시간 코어 Samp.cls
APP_CLASS_MAP = {
    "office": "office", "pdf": "office", "viewer": "office", "cad": "cad", "sim": "sim", "eda": "eda",
    "ide": "ide", "browser": "browser", "mail_work": "mail", "chat_work": "chat", "messenger_private": "chat",
    "meeting": "meet", "remote": "remote", "system": "system", "idle": "system", "media": "other",
    "game": "other", "other": "other",
}
ENG_CATEGORIES = frozenset({"CAD", "해석", "광학", "EDA", "FPGA", "SW", "계측"})   # 카탈로그 공학 범주(계약 §2.8)
CODE_EXT = (".py", ".c", ".cpp", ".h", ".m", ".js", ".ts", ".java", ".cs", ".v", ".vhd")
TEXT_COLS = ("subject_masked", "body_masked", "msg_masked", "text_masked")
DOC_OPS = {"modify": "save", "save": "save", "create": "create", "open": "open"}
RESULT_PRE_S, RESULT_POST_S = 120, 300          # 연산 끝 −2분 ~ +5분의 같은 문서군 저장 = 결과 파일(X-200)
_EPOCH_ORD = EPOCH.toordinal()
_EPOCH_DT = datetime(EPOCH.year, EPOCH.month, EPOCH.day)


# ───────────────────────────── 형(W §2.2.1 — 계약 이름) ─────────────────────────────
@dataclass(frozen=True, slots=True)
class Samp:
    """샘플러 표본(틱) — 실측 구간 [a, b)."""
    pc: str
    a: int
    b: int
    state: str          # active | idle | locked | disconnected | sleep
    cls: str            # office|cad|cae|sim|eda|ide|eng|browser|mail|chat|meet|remote|explorer|system|other
    fam: str            # 문서군 키('' = 문서 키 없음)
    priv: str           # work | unknown | media | private | social
    idle: int | None    # idle_sec 원값
    app: str            # app_id(미지 = 'unknown:<exe>')


@dataclass(frozen=True, slots=True)
class PcSpan:
    """L0/L1 가동(이벤트 로그)."""
    pc: str
    a: int
    b: int
    layer: str


@dataclass(frozen=True, slots=True)
class Msg:
    id: str
    t: int
    dir: str                    # in | out
    act: str                    # request|ack|question|report|info|notice|social
    conv: str                   # 메일 thread_key · 팀즈 chat_key(+채널 답글 루트)
    peer: str
    prec: str
    direct: bool
    atts: tuple[str, ...]       # 첨부 문서군 키
    tokens: frozenset[str]
    ch: str                     # mail | teams
    flags: frozenset[str]       # cc · bulk · deferred · meeting_response · utc · notice
    key: str                    # msg_key
    n_part: int
    proj: str | None


@dataclass(frozen=True, slots=True)
class Meet:
    id: str
    a: int
    b: int
    status: str                 # accepted | organizer | tentative | declined | cancelled | none
    organizer: str              # 'self'(flags.organizer_me) 또는 ''(X-204 — 주최자 키는 저장하지 않는다)
    attendees: tuple[str, ...]  # counterpart_keys
    n_att: int
    tokens: frozenset[str]
    online: bool
    personal: bool
    all_day: bool
    category: str               # offsite | edu | trip | leave | ''
    key: str = ""               # msg_key(e24) — 확인 응답 attended 의 대상
    series: str = ""            # 반복 시리즈 키(thread_key)


@dataclass(frozen=True, slots=True)
class DocE:
    id: str
    pc: str
    t: int
    kind: str                   # create | save | export | open | result
    raw: str                    # 정제된 파일 이름(로컬 전용 — 코드 확장자 판정)
    fam: str
    folder: str                 # dir_keys[:2] 를 '+' 로 이은 것(X-200)
    autosave: bool
    burst: bool
    other: bool
    proj: str | None


@dataclass(frozen=True, slots=True)
class Comp:
    pc: str
    a: int
    b: int
    app: str
    fam: str


@dataclass(frozen=True, slots=True)
class Commit:
    pc: str
    t: int
    fam: str                    # 저장소 키 r16 그대로(X-216)
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True)
class Man:
    kind: str                   # work|offsite|instr|report|absence|exclude|attended|must_link|cannot_link
    d: date | None
    a: int | None
    b: int | None
    hours: float | None
    ref: str                    # 참조 문서군 키(attended 는 회의 msg_key)
    tokens: frozenset[str]
    key: str                    # 참조 증거 키(msg_key·chat_key …), 없으면 레코드 id
    id: str = ""
    proj: str | None = None


@dataclass
class Evidence:
    """정규화 결과(W 부록 A `Evidence` + 구현 확장 — X-217)."""
    samples: list[Samp]
    pcon: list[PcSpan]
    msgs: list[Msg]
    meets: list[Meet]
    docs: list[DocE]
    comps: list[Comp]
    commits: list[Commit]
    manual: list[Man]
    leaves: dict[date, str]
    coverage: dict[tuple[date, str], str]
    audit: Counter
    as_of: int
    d0: date
    d1: date
    common_tokens: frozenset[str]
    utc_suspect: bool
    shared_docs: frozenset[str]
    fam_tokens: dict[str, frozenset[str]] = field(default_factory=dict)
    fam_names: dict[str, str] = field(default_factory=dict)
    generic_fams: frozenset[str] = frozenset()
    tz_offset_min: int = 540
    warnings: list[str] = field(default_factory=list)

    @property
    def common(self) -> frozenset[str]:
        """참조 구현 이름(IDF 상용 토큰)."""
        return self.common_tokens


# ───────────────────────────── 시각 변환 ─────────────────────────────
@functools.lru_cache(maxsize=16384)
def _day_index(ymd: str) -> int:
    return date.fromisoformat(ymd).toordinal() - _EPOCH_ORD


def _utc_lsec(ts: str, off_s: int) -> int:
    """'YYYY-MM-DDTHH:MM:SSZ' → 로컬 초. 다른 ISO 형(오프셋·소수 초)도 받는다. 형식 오류는 ValueError."""
    if not isinstance(ts, str):
        raise ValueError("시각이 문자열이 아니다")
    if len(ts) == 20 and ts[10] == "T" and ts[19] == "Z" and ts[13] == ":" and ts[16] == ":":
        h, mi, se = int(ts[11:13]), int(ts[14:16]), int(ts[17:19])
        if h > 23 or mi > 59 or se > 59:
            raise ValueError("시각 범위 오류")
        return _day_index(ts[:10]) * DAY + h * HOUR + mi * MIN + se + off_s
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    u = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return int((u - _EPOCH_DT).total_seconds()) + off_s


def lsec_of(x, off_min: int) -> int:
    """분석 시각 `as_of` 등 → 근무 시간대 로컬 초.

    int = 이미 로컬 초 · 시간대 있는 datetime = 그 순간 · 시간대 없는 datetime = 근무 시간대 벽시계 ·
    date = 그날 끝(23:59:59) · str = ISO(끝이 Z·오프셋이면 그 순간, 아니면 근무 시간대 벽시계).
    """
    if isinstance(x, bool):
        raise TypeError("as_of 에 bool 은 쓸 수 없다")
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        s = x.strip().replace(" ", "T", 1) if len(x.strip()) > 10 else x.strip()
        if len(s) == 10:
            return lsec_of(date.fromisoformat(s), off_min)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return lsec_of(dt, off_min)
    if isinstance(x, datetime):
        if x.tzinfo is not None:
            u = x.astimezone(timezone.utc).replace(tzinfo=None)
            return int((u - _EPOCH_DT).total_seconds()) + off_min * MIN
        return int((x - _EPOCH_DT).total_seconds())
    if isinstance(x, date):
        return (x.toordinal() - _EPOCH_ORD + 1) * DAY - 1
    raise TypeError(f"as_of 형 오류: {type(x).__name__}")


# ───────────────────────────── 입력 접근 도우미 ─────────────────────────────
def _get(obj, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _flags(r: Mapping) -> Mapping:
    f = r.get("flags")
    return f if isinstance(f, Mapping) else {}


def _int_or_none(v) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v:
        return int(v)
    return None


def _as_date(x) -> date:
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _str_list(v) -> list[str]:
    if not isinstance(v, list | tuple):
        return []
    return [x for x in v if isinstance(x, str) and x]


_LAZY: dict[str, object] = {}


def _lazy(name: str):
    """지연 import 한 의존 함수(첫 사용 때만). 없으면 ImportError 가 그대로 올라간다(L-06 — 삼키지 않는다)."""
    fn = _LAZY.get(name)
    if fn is None:
        if name == "cat_of":
            from lm27.catalog import cat_of as fn
        elif name == "meet_category":
            from lm27.normalize.absence import meet_category as fn
        else:                                   # pragma: no cover — 내부 오용
            raise KeyError(name)
        _LAZY[name] = fn
    return fn


class _Tags:
    """HierTags{msg: {msg_key: proj}, fam: {fam_key: proj}, shared_fams: set}(계약 §3.15 · H X8). None 허용."""

    def __init__(self, tags):
        self.msg = dict(_get(tags, "msg", None) or {})
        self.fam = dict(_get(tags, "fam", None) or {})
        self.shared = frozenset(_get(tags, "shared_fams", None) or ())

    @staticmethod
    def _proj(v):
        if isinstance(v, Mapping):
            v = v.get("proj")
        return v if isinstance(v, str) and v else None

    def msg_proj(self, k: str):
        return self._proj(self.msg.get(k)) if k else None

    def fam_proj(self, f: str):
        return self._proj(self.fam.get(f)) if f else None


# ───────────────────────────── normalize ─────────────────────────────
def normalize(records: Iterable[Mapping], profile, cfg, as_of, tags=None) -> tuple[Evidence, Counter]:
    """저장 행 → `Evidence`(W §2.4 · 계약 X-212). 반환 `(Evidence, audit)` — audit 은 버린 건수(원문 없음).

    profile(Mapping 또는 속성 객체, 모두 선택): `d0`·`d1`(분석 기간, 없으면 증거·as_of 로) · `leaves`
    ({날짜: full|am|pm} — `lm27.normalize.absence.leaves`) · `coverage`({(날짜, kind_axis): status} 또는
    `[{date, kind_axis, status}]`) · `shared_docs`(공용 문서군 키).
    tags: HierTags 또는 None.
    """
    n = _Norm(profile, cfg, as_of, tags)
    return n.run(records)


class _Norm:
    def __init__(self, profile, cfg, as_of, tags):
        self.cfg = cfg
        self.off_min = int(cfg["time.tzOffsetMin"])
        self.off_s = self.off_min * MIN
        self.as_of = lsec_of(as_of, self.off_min)
        self.slack = int(cfg["time.envelope.futureSlackMin"]) * MIN
        self.idle_active = int(cfg["time.envelope.idleActiveSec"])
        self.mail_off = cfg["time.envelope.mailTimeOffsetH"]
        self.stuck_cover = float(cfg["time.envelope.stuckCoverH"]) * HOUR
        self.stuck_ratio = float(cfg["time.envelope.stuckIdleRatio"])
        self.utc_share = float(cfg["time.envelope.utcSuspectShare"])
        self.idf_max = float(cfg["episode.tokens.idfMaxDf"])
        self.idf_min_n = int(cfg["episode.tokens.idfMinN"])
        self.burst_n = int(cfg["pc.files.burstN"])
        self.boiler = boilerplate(cfg)
        self.stems = generic_stems(cfg)
        self.profile = profile
        self.tags = _Tags(tags)
        self.audit: Counter = Counter()
        self.warnings: list[str] = []
        self.names: dict[str, tuple[int, str]] = {}
        self.dirs: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        self._fam_cache: dict[tuple[str, str | None, tuple], str] = {}
        self._famname_cache: dict[str, str] = {}
        self.fam_names: dict[str, str] = {}

    # --- 공용 ---
    def lsec(self, ts) -> int:
        return _utc_lsec(ts, self.off_s)

    def toks(self, r: Mapping) -> set[str]:
        st = r.get("subject_tokens")
        if isinstance(st, list | tuple):
            return raw_tokens([x for x in st if isinstance(x, str)], self.boiler)
        return raw_tokens([r.get(c) for c in TEXT_COLS if isinstance(r.get(c), str)], self.boiler)

    def _fam_of_name(self, name: str) -> str:
        v = self._famname_cache.get(name)
        if v is None:
            v = fam(name)
            self._famname_cache[name] = v
        return v

    def note_name(self, dk, name, prio: int) -> None:
        if not dk or not isinstance(name, str) or not name.strip():
            return
        cur = self.names.get(dk)
        cand = (prio, name)
        if cur is None or cand < cur:
            self.names[dk] = cand

    def fam_ctx(self, dk, name: str | None = None, dirs: Iterable[str] | None = None) -> str:
        """doc_key(+이름·폴더 키) → 문서군 키. 이름·폴더를 모르면 앞서 모은 색인(파일 행)을 쓴다."""
        if not dk or not isinstance(dk, str):
            return ""
        nm = name if (isinstance(name, str) and name.strip()) else (self.names.get(dk, (9, None))[1])
        dk_dirs = tuple(dirs) if dirs else None
        ck = (dk, nm, dk_dirs)
        hit = self._fam_cache.get(ck)
        if hit is not None:
            return hit
        if dk_dirs is None:
            ds = self.dirs.get(dk)
            dk_dirs = next(iter(ds)) if ds and len(ds) == 1 else ()
        f = fam_key(dk, nm, dk_dirs, self.cfg, stems=self.stems)
        if f and f != B_GENERIC and f not in self.fam_names:   # B_GENERIC 은 여러 이름의 묶음 — 이름 없음
            best = self.names.get(dk, (9, nm))[1]      # 색인의 최선 이름 — 처리 순서와 무관(G2)
            if best:
                self.fam_names[f] = self._fam_of_name(best)
        self._fam_cache[ck] = f
        return f

    # --- 실행 ---
    def run(self, records: Iterable[Mapping]) -> tuple[Evidence, Counter]:
        rows = []
        for r in records:
            if not isinstance(r, Mapping):
                self.audit["행_형식오류"] += 1
                continue
            rows.append(r)
        self._index_names(rows)
        S, pcon_raw, msgs_raw, meets, docs_raw, comps, commits, manual_raw = [], [], [], [], [], [], [], []
        for r in rows:
            kind = r.get("kind")
            prec = r.get("ts_precision")
            if prec not in PRECS:
                self.audit["정밀도_형식오류"] += 1
                continue
            if prec == "unknown":
                self.audit["격리_시각불명"] += 1
                continue
            try:
                t = self.lsec(r.get("ts_utc"))
            except (ValueError, TypeError):
                self.audit["시각_형식오류"] += 1
                continue
            if t < 0:
                self.audit["기준점_이전"] += 1
                continue
            if kind == "pc_session":
                self._session(r, t, S, pcon_raw)
            elif kind in ("mail", "teams"):
                self._msg(r, t, prec, msgs_raw)
            elif kind == "cal":
                self._meet(r, t, prec, meets)
            elif kind == "pc_file":
                self._doc(r, t, prec, docs_raw)
            elif kind == "pc_compute":
                self._comp(r, t, comps)
            elif kind == "pc_git":
                self._commit(r, t, prec, commits)
            elif kind == "manual":
                self._manual(r, t, prec, manual_raw)
            else:
                self.audit["알수없는_kind"] += 1
        S = self._stuck(S)
        S.sort(key=lambda s: (s.a, s.pc, s.b, s.cls, s.fam, s.state, s.priv, s.app,
                              -1 if s.idle is None else s.idle))
        comps.sort(key=lambda c: (c.a, c.pc, c.app, c.b, c.fam))
        commits.sort(key=lambda c: (c.t, c.fam, c.pc, tuple(sorted(c.tokens))))
        pcon = self._pcon(pcon_raw, S, docs_raw, commits, comps)
        msgs = self._dedupe_msgs(msgs_raw)
        meets.sort(key=lambda m: (m.a, m.id))
        docs = self._docs(docs_raw, comps)
        manual = self._retract(manual_raw)
        sent_ex = [m for m in msgs if m.dir == "out" and m.prec in EXACT]
        utc_suspect = len(sent_ex) >= 5 and \
            sum(1 for m in sent_ex if (m.t % DAY) < 8 * HOUR) / len(sent_ex) >= self.utc_share
        if utc_suspect:
            self.warnings.append("UTC 저장 의심 — 정밀 발신의 00~08시 비율이 문턱 이상(보정은 하지 않음, Q13)")
        fam_tokens = self._fam_tokens(S, docs, comps, msgs, manual)
        common = self._idf(msgs, S, docs, fam_tokens)
        generic = frozenset(f for f in fam_tokens if f == B_GENERIC or "@" in f)
        d0, d1 = self._period(S, pcon, msgs, meets, docs, comps, commits, manual)
        shared = frozenset(str(x) for x in (_get(self.profile, "shared_docs", None) or ()) if x) | self.tags.shared
        ev = Evidence(samples=S, pcon=pcon, msgs=msgs, meets=meets, docs=docs, comps=comps, commits=commits,
                      manual=manual, leaves=self._leaves(), coverage=self._coverage(), audit=self.audit,
                      as_of=self.as_of, d0=d0, d1=d1, common_tokens=common, utc_suspect=utc_suspect,
                      shared_docs=shared, fam_tokens=fam_tokens,
                      fam_names={f: self.fam_names[f] for f in sorted(fam_tokens) if f in self.fam_names},
                      generic_fams=generic, tz_offset_min=self.off_min, warnings=self.warnings)
        return ev, self.audit

    # --- 0. 이름·폴더 색인(범용 판정용, 결정적: 우선순위·이름 최소) ---
    def _index_names(self, rows) -> None:
        for r in rows:
            kind = r.get("kind")
            if kind == "pc_file":
                dk = r.get("doc_key")
                nm = r.get("name_masked")
                if isinstance(nm, str) and nm and isinstance(r.get("ext"), str) and "." not in nm[-6:]:
                    nm = nm + r["ext"]
                self.note_name(dk, nm, 0)
                dks = _str_list(r.get("dir_keys"))[:2]
                if dk and dks:
                    self.dirs[dk].add(tuple(dks))
            elif kind == "mail":
                for k, nm in zip(_str_list(r.get("attach_keys")), _str_list(r.get("attach_names_masked")), strict=False):
                    self.note_name(k, nm, 1)
            elif kind == "teams":
                for k, nm in zip(_str_list(r.get("file_keys")), _str_list(r.get("file_names_masked")), strict=False):
                    self.note_name(k, nm, 1)
            elif kind == "pc_session":
                ti = r.get("title_masked")
                if isinstance(ti, str) and ti:
                    self.note_name(r.get("doc_key"), ti.split(" - ")[0], 2)

    # --- 1. pc_session ---
    def _session(self, r, t, S, pcon_raw) -> None:
        pc = r.get("pc_id") or ""
        try:
            b = self.lsec(r.get("ts_end"))
        except (ValueError, TypeError):
            b = t
        fl = _flags(r)
        events = r.get("src") == "pc.events" or r.get("layer") in ("L0", "L1")
        if t > self.as_of + self.slack:
            self.audit["미래시각_폐기"] += 1
            return
        if b <= t:
            self.audit["샘플_역순"] += 1
            return
        if events and r.get("event_class") != "sleep":
            pcon_raw.append((pc, t, b, str(r.get("layer") or "L0"), bool(fl.get("end_uncertain"))))
            return
        if fl.get("stuck"):
            self.audit["고착_표본_폐기"] += 1
            return
        if events:                                      # pc.events 절전 구간 = 부정 증거(X-202)
            S.append(Samp(pc, t, b, "sleep", "system", "", "work", None, "system"))
            return
        ss = r.get("session_state")
        idle = _int_or_none(r.get("idle_sec"))
        if ss in ("active", "remote"):
            state = "idle" if (idle is not None and idle > self.idle_active) else "active"
        elif ss in ("locked", "disconnected"):
            state = ss
        else:
            self.audit["세션상태_형식오류"] += 1
            return
        cls = self._cls(r)
        dk = r.get("doc_key")
        ti = r.get("title_masked")
        f = self.fam_ctx(dk, ti.split(" - ")[0] if isinstance(ti, str) and ti else None) if dk else ""
        priv = r.get("priv_class")
        if priv not in PRIV_CLASSES:
            priv = "work"
        app = r.get("app_id") or cls
        S.append(Samp(pc, t, b, state, cls, f, priv, idle, str(app)))

    def _cls(self, r) -> str:
        ac = r.get("app_class")
        cls = APP_CLASS_MAP.get(ac, "other")
        if ac == "system" and str(r.get("fg_exe") or "").lower() == "explorer.exe":
            return "explorer"
        if cls == "other":
            app = r.get("app_id")
            if isinstance(app, str) and app and not app.startswith("unknown:"):
                cat = _lazy("cat_of")(app)
                if cat in ENG_CATEGORIES:
                    return "eng"
        return cls

    def _stuck(self, S: list[Samp]) -> list[Samp]:
        """(PC, 날) 커버 ≥ stuckCoverH 이고 idle>0 비율 < stuckIdleRatio → 그 PC·그날 표본 폐기(하한 폴백)."""
        by_pd: dict[tuple[str, date], list[Samp]] = defaultdict(list)
        for s in S:
            by_pd[(s.pc, d_of(s.a))].append(s)
        stuck = set()
        for k, lst in by_pd.items():
            cov = sum(x.b - x.a for x in lst)
            vals = [x.idle for x in lst if x.idle is not None]
            if cov >= self.stuck_cover and vals and sum(1 for v in vals if v > 0) / len(vals) < self.stuck_ratio:
                stuck.add(k)
                self.audit["고착_PC날_폐기"] += 1
        if not stuck:
            return S
        return [s for s in S if (s.pc, d_of(s.a)) not in stuck]

    def _pcon(self, pcon_raw, S, docs_raw, commits, comps) -> list[PcSpan]:
        """L0/L1 가동. 끝 불확실 구간은 그 PC 의 마지막 관측(표본 끝·저장·커밋·연산)까지만(W §2.8)."""
        obs: dict[str, list[int]] = defaultdict(list)
        if any(u for *_x, u in pcon_raw):
            for s in S:
                obs[s.pc].append(s.b)
            for d in docs_raw:
                obs[d["pc"]].append(d["t"])
            for c in commits:
                obs[c.pc].append(c.t)
            for c in comps:
                obs[c.pc] += [c.a, c.b]
            for v in obs.values():
                v.sort()
        out = []
        for pc, a, b, layer, unc in pcon_raw:
            if unc:
                inside = [x for x in obs.get(pc, ()) if a <= x <= b]
                nb = max(inside) if inside else a
                if nb <= a:
                    self.audit["가동_끝불확실_제외"] += 1
                    continue
                b = nb
            out.append(PcSpan(pc, a, b, layer))
        out.sort(key=lambda p: (p.pc, p.a, p.b, p.layer))
        return out

    # --- 2. mail · teams ---
    def _msg(self, r, t, prec, out) -> None:
        kind = r["kind"]
        fl = _flags(r)
        act = r.get("act") if r.get("act") in ACTS else ""
        if not act:
            cues = set(_str_list(r.get("act_cues")))
            act = next((a for c, a in CUE_ACT if c in cues), "info")
        if fl.get("teams_notice"):
            act = "notice"
        if r.get("priv_class") in ("private", "social") or fl.get("ad") or act == "social":
            self.audit["사적·광고_시간근거제외"] += 1
            return
        if self.mail_off is not None and prec in EXACT and fl.get("utc_suspect"):
            t += int(round(float(self.mail_off) * HOUR))
        if prec in EXACT and t > self.as_of + self.slack:
            self.audit["미래시각_폐기"] += 1
            return
        rid = str(r.get("id") or "")
        key = str(r.get("msg_key") or rid)
        cp = _str_list(r.get("counterpart_keys"))
        if kind == "mail":
            d = r.get("direction")
            if d not in ("in", "out"):
                self.audit["방향미상"] += 1
                d = "in"
            direct = r.get("rcv") == "to" and not fl.get("cc")
            conv = r.get("thread_key") or key
            sender = r.get("sender_key")
            peer = sender if (d == "in" and isinstance(sender, str) and sender.startswith("w")) else (cp[0] if cp else "")
            pairs = zip(_str_list(r.get("attach_keys")), _str_list(r.get("attach_names_masked")) + [None] * 10,
                        strict=False)
            ch = "mail"
        else:
            dr = r.get("direction")
            d = "out" if dr == "sent" else "in"
            if dr not in ("sent", "received"):
                self.audit["방향미상"] += 1
            direct = r.get("chat_type") == "1:1" or bool(fl.get("mentions_me"))
            conv = r.get("chat_key") or key
            if r.get("chat_type") == "channel" and r.get("thread_key"):
                conv = f"{conv}:{r['thread_key']}"
            author = r.get("author_key")
            peer = author if (d == "in" and isinstance(author, str) and author.startswith("w")) else (cp[0] if cp else "")
            pairs = zip(_str_list(r.get("file_keys")), _str_list(r.get("file_names_masked")) + [None] * 10,
                        strict=False)
            ch = "teams"
        atts = tuple(sorted({f for f in (self.fam_ctx(k, nm) for k, nm in pairs) if f}))
        mfl = {k for k in ("cc", "bulk", "deferred", "meeting_response") if fl.get(k)}
        if fl.get("utc_suspect"):
            mfl.add("utc")
        if act == "notice":
            mfl.add("notice")
        np_ = _int_or_none(r.get("n_participants"))
        out.append(Msg(rid, t, d, act, str(conv), str(peer), prec, bool(direct), atts, frozenset(self.toks(r)), ch,
                       frozenset(mfl), key, np_ if np_ is not None else 2, self.tags.msg_proj(key)))

    def _dedupe_msgs(self, raw: list[Msg]) -> list[Msg]:
        """msg_key 별 정밀도 최선 사본 하나(동률은 id 사전순), 같은 (날짜, 방향, 대화)의 정밀 사본이 있으면 date 사본 흡수."""
        best: dict[str, Msg] = {}
        for m in raw:
            cur = best.get(m.key)
            if cur is None:
                best[m.key] = m
                continue
            self.audit["중복_병합"] += 1
            if (PREC_RANK[m.prec], m.id) < (PREC_RANK[cur.prec], cur.id):
                best[m.key] = m
        msgs = list(best.values())
        exact_keys = {(d_of(m.t), m.dir, m.conv) for m in msgs if m.prec in EXACT}
        keep = []
        for m in msgs:
            if m.prec == "date" and (d_of(m.t), m.dir, m.conv) in exact_keys:
                self.audit["date-only_흡수"] += 1
                continue
            keep.append(m)
        keep.sort(key=lambda m: (m.t, m.id, m.key))
        return keep

    # --- 3. cal ---
    def _meet(self, r, t, prec, out) -> None:
        fl = _flags(r)
        if prec not in EXACT:
            self.audit["일정_정밀도부족"] += 1
            return
        try:
            b = self.lsec(r.get("ts_end"))
        except (ValueError, TypeError):
            self.audit["일정_끝없음"] += 1
            return
        lim = self.as_of + self.slack
        if t > lim:
            self.audit["미래시각_폐기"] += 1
            return
        b = min(b, lim)
        if b <= t:
            self.audit["일정_역순"] += 1
            return
        resp = _int_or_none(fl.get("response"))
        ms = _int_or_none(fl.get("meeting_status"))
        busy = r.get("busy")
        if ms in (5, 7):
            status = "cancelled"
        elif fl.get("organizer_me") or resp == 1:
            status = "organizer"
        elif resp == 3:
            status = "accepted"
        elif resp == 4:
            status = "declined"
        elif resp in (2, 5):
            status = "tentative"
        elif busy in ("busy", "oof", "elsewhere"):
            status = "accepted"
        elif busy == "tentative":
            status = "tentative"
        else:
            status = "none"
        sens = _int_or_none(fl.get("sensitivity")) or 0
        personal = sens >= 1 or bool(fl.get("cat_private")) or bool(fl.get("private")) or \
            r.get("priv_class") in ("private", "social")
        cp = tuple(sorted(_str_list(r.get("counterpart_keys"))))
        np_ = _int_or_none(r.get("n_participants"))
        cat = _lazy("meet_category")(r)
        out.append(Meet(str(r.get("id") or ""), t, b, status, "self" if fl.get("organizer_me") else "", cp,
                        np_ if np_ is not None else len(cp) + 1,
                        frozenset() if personal else frozenset(self.toks(r)),     # 개인 일정 제목 토큰은 싣지 않는다(P-T12)
                        bool(fl.get("online_meeting")), personal, bool(fl.get("all_day")),
                        cat if isinstance(cat, str) else "", str(r.get("msg_key") or ""),
                        str(r.get("thread_key") or "")))

    # --- 4. pc_file ---
    def _doc(self, r, t, prec, out) -> None:
        if prec not in EXACT:
            self.audit["문서_정밀도부족"] += 1
            return
        if t > self.as_of + self.slack:
            self.audit["미래시각_폐기"] += 1
            return
        fl = _flags(r)
        if fl.get("pdf_export"):
            kind = "export"
        else:
            kind = DOC_OPS.get(r.get("op"), "open")
        if fl.get("view_only") and kind != "export":
            kind = "open"
        dk = r.get("doc_key")
        nm = r.get("name_masked") if isinstance(r.get("name_masked"), str) else ""
        ext = r.get("ext") if isinstance(r.get("ext"), str) else ""
        raw = nm if (not ext or nm.lower().endswith(ext.lower())) else nm + ext
        dks = _str_list(r.get("dir_keys"))[:2]
        f = self.fam_ctx(dk, nm or None, dks) if dk else ""
        out.append({"id": str(r.get("id") or ""), "pc": r.get("pc_id") or "", "t": t, "kind": kind, "raw": raw,
                    "fam": f, "folder": "+".join(dks), "autosave": bool(fl.get("autosave")),
                    "other": bool(fl.get("author_other"))})

    def _docs(self, raw: list[dict], comps: list[Comp]) -> list[DocE]:
        """결과 파일 파생(X-200) → 뭉치(같은 PC·폴더·분 ≥ pc.files.burstN → 첫 1건만 앵커 후보) → 정렬."""
        ends: dict[tuple[str, str], list[int]] = defaultdict(list)
        for c in comps:
            if c.fam and c.b > c.a:
                ends[(c.pc, c.fam)].append(c.b)
        for d in raw:
            if d["kind"] in ("save", "create") and d["fam"] and (d["pc"], d["fam"]) in ends and \
                    any(e - RESULT_PRE_S <= d["t"] <= e + RESULT_POST_S for e in ends[(d["pc"], d["fam"])]):
                d["kind"] = "result"
        by_fm: dict[tuple, list[dict]] = defaultdict(list)
        for d in raw:
            by_fm[(d["pc"], d["folder"], d["t"] // MIN)].append(d)
        burst_ids = set()
        for lst in by_fm.values():
            if len(lst) >= self.burst_n:
                lst.sort(key=lambda d: (d["t"], d["raw"], d["id"], d["fam"], d["kind"]))
                for d in lst[1:]:
                    burst_ids.add(id(d))
                self.audit["파일뭉치_대표1건"] += len(lst) - 1
        out = [DocE(d["id"], d["pc"], d["t"], d["kind"], d["raw"], d["fam"], d["folder"], d["autosave"],
                    id(d) in burst_ids, d["other"], self.tags.fam_proj(d["fam"])) for d in raw]
        out.sort(key=lambda e: (e.t, e.fam, e.kind, e.pc, e.id, e.raw))
        return out

    # --- 5. pc_compute · pc_git ---
    def _comp(self, r, t, out) -> None:
        fl = _flags(r)
        if fl.get("license") and not fl.get("solver"):
            self.audit["라이선스행_제외"] += 1
            return
        if t > self.as_of + self.slack:
            self.audit["미래시각_폐기"] += 1
            return
        try:
            b = self.lsec(r.get("ts_end"))
        except (ValueError, TypeError):
            b = t
        if fl.get("end_uncertain"):
            b = t                                   # 지어낸 끝은 쓰지 않는다 — 기계 시간 0, 제출 앵커만
        if b < t:
            self.audit["연산_역순"] += 1
            return
        out.append(Comp(r.get("pc_id") or "", t, b, str(r.get("app_id") or ""), self.fam_ctx(r.get("doc_key"))))

    def _commit(self, r, t, prec, out) -> None:
        if prec not in EXACT:
            self.audit["커밋_정밀도부족"] += 1
            return
        if t > self.as_of + self.slack:
            self.audit["미래시각_폐기"] += 1
            return
        out.append(Commit(r.get("pc_id") or "", t, str(r.get("doc_key") or ""), frozenset(self.toks(r))))

    # --- 6. manual ---
    def _manual(self, r, t, prec, out) -> None:
        mk = r.get("man_kind") or "work"
        if mk not in MAN_KINDS:
            self.audit["수동_종류오류"] += 1
            return
        refs = _str_list(r.get("ref_keys"))
        if prec in EXACT:
            if t > self.as_of + self.slack:
                self.audit["미래시각_폐기"] += 1
                return
            a = t
            try:
                b = self.lsec(r.get("ts_end")) if r.get("ts_end") else None
            except (ValueError, TypeError):
                b = None
        else:
            a = b = None
        hours = r.get("hours")
        hours = float(hours) if isinstance(hours, int | float) and not isinstance(hours, bool) and hours == hours \
            else None
        if a is not None and b is None and mk == "work" and hours:
            b = a + int(round(hours * HOUR))
        if a is not None and b is not None and b <= a:
            b = None if mk != "work" else a
        doc_refs = [k for k in refs if k[:1] in ("d", "r")]
        msg_refs = [k for k in refs if k[:1] in ("m", "h", "t")]
        ev_refs = [k for k in refs if k[:1] == "e"]
        if mk == "attended":
            ref = ev_refs[0] if ev_refs else ""
        else:
            ref = self.fam_ctx(doc_refs[0]) if doc_refs else ""
        key = (msg_refs or ev_refs or [str(r.get("id") or "")])[0]
        toks = self.toks(r)
        for k in doc_refs:
            nm = self.names.get(k, (9, None))[1]
            if nm:
                toks |= raw_tokens([self._fam_of_name(nm)], self.boiler)
        proj = r.get("project_id") if isinstance(r.get("project_id"), str) and r.get("project_id") else None
        out.append((Man(mk, d_of(t), a, b, hours, ref, frozenset(toks), key, str(r.get("id") or ""), proj),
                    r.get("retract_of")))

    def _retract(self, raw: list[tuple[Man, object]]) -> list[Man]:
        gone = {str(x) for m, x in raw if m.kind == "retract" and x}
        out = []
        for m, _x in raw:
            if m.kind == "retract":
                continue
            if m.id and m.id in gone:
                self.audit["수동_철회"] += 1
                continue
            out.append(m)
        out.sort(key=lambda m: (m.d or date.min, -1 if m.a is None else m.a, m.kind, m.key, m.id, m.ref))
        return out

    # --- 7. 토큰·IDF·기간·근태·커버리지 ---
    def _fam_tokens(self, S, docs, comps, msgs, manual) -> dict[str, frozenset[str]]:
        fams = {s.fam for s in S} | {e.fam for e in docs} | {c.fam for c in comps} | \
            {f for m in msgs for f in m.atts} | {m.ref for m in manual if m.kind != "attended"}
        out = {}
        for f in sorted(x for x in fams if x):
            nm = self.fam_names.get(f, "")
            out[f] = frozenset(raw_tokens([nm], self.boiler)) if nm else frozenset()
        return out

    def _idf(self, msgs, S, docs, fam_tokens) -> frozenset[str]:
        nodes = [set(m.tokens) for m in msgs if m.tokens]
        fams = sorted({e.fam for e in docs} | {s.fam for s in S if s.fam})
        nodes += [set(fam_tokens.get(f, ())) for f in fams if f]
        if len(nodes) < self.idf_min_n:
            return frozenset()
        df = Counter(t for nd in nodes for t in nd)
        return frozenset(t for t, c in df.items() if c / len(nodes) > self.idf_max)

    def _period(self, S, pcon, msgs, meets, docs, comps, commits, manual) -> tuple[date, date]:
        d0 = _get(self.profile, "d0", None)
        d1 = _get(self.profile, "d1", None)
        if d0 is not None and d1 is not None:
            return _as_date(d0), _as_date(d1)
        ts = [s.a for s in S] + [p.a for p in pcon] + [m.t for m in msgs] + [m.a for m in meets] + \
            [e.t for e in docs] + [c.a for c in comps] + [c.t for c in commits] + \
            [m.a for m in manual if m.a is not None]
        days = [d_of(t) for t in ts] + [m.d for m in manual if m.d is not None]
        last = d_of(self.as_of)
        lo = _as_date(d0) if d0 is not None else (min(days) if days else last)
        hi = _as_date(d1) if d1 is not None else min(max(days) if days else last, last)
        if hi < lo:
            hi = lo
        return lo, hi

    def _leaves(self) -> dict[date, str]:
        out: dict[date, str] = {}
        for k, v in (_get(self.profile, "leaves", None) or {}).items():
            if v not in LEAVE_CODES:
                self.warnings.append("근태 코드 오류 — 무시(full·am·pm 만)")
                continue
            out[_as_date(k)] = v
        return dict(sorted(out.items()))

    def _coverage(self) -> dict[tuple[date, str], str]:
        cov = _get(self.profile, "coverage", None) or {}
        rank = {s: i for i, s in enumerate(COVERAGE_STATUS)}
        out: dict[tuple[date, str], str] = {}

        def put(d, ax, st):
            if ax not in AXES or st not in rank:
                self.audit["커버리지_형식오류"] += 1
                return
            k = (_as_date(d), ax)
            cur = out.get(k)
            if cur is None or rank[st] < rank[cur]:
                out[k] = st                          # 같은 (날짜, 축)이 여럿이면 최선 값(C §5.3)

        if isinstance(cov, Mapping):
            for k, st in cov.items():
                if isinstance(k, tuple) and len(k) == 2:
                    put(k[0], k[1], st)
                elif isinstance(k, str) and "|" in k:
                    d, ax = k.split("|", 1)
                    put(d, ax, st)
                else:
                    self.audit["커버리지_형식오류"] += 1
        else:
            for row in cov:
                put(_get(row, "date"), _get(row, "kind_axis"), _get(row, "status"))
        return dict(sorted(out.items()))

